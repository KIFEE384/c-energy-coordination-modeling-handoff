# -*- coding: utf-8 -*-
"""能源层求解器（M00 / M10(Q2) / M01(Q3, M11能源层)）。

冻结口径（03_models/统一双柔性模型.md、07_decisions/decision_log.md）：
  - 能源动作 t = 0..2406，共 2407 小时；
  - RE_avail = RE_direct + RE_charge + RE_sell + Curtailment；
  - Grid_load + RE_direct + Discharge = P_fac；
  - GridPurchase = Grid_load + Grid_charge；GridSell = RE_sell（禁止购电转售）；
  - SOC_t = SOC_(t-1) + eta_c*ChargePower_t - Discharge_t/eta_d，SOC_-1 = InitialSOC；
  - 终端约束 SOC_2406 >= InitialSOC；
  - 购售电、充放电互斥由二元变量保证。

模式：
  - m00：无储能、无外送（纯反事实）。RE 直供最大化，多余弃电，电网补足。闭式解。
  - m10：无储能、允许新能源外送（Q2/M10）。购售电互斥。闭式解。
  - m01：储能 + 新能源外送（Q3/M01/M11 能源层）。MILP（HiGHS），目标默认最小化净成本，
    可选最小化碳排放。

所有求解结果逐时满足守恒残差 <= 1e-6 MW（默认容差可在函数内调整）。
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from data_loader import HOURS_ENERGY, Problem

MODE_M00 = "m00"
MODE_M10 = "m10"
MODE_M01 = "m01"

# 变量顺序（每小时的 12 个变量）
_V = ["re_direct", "re_charge", "re_sell", "curt", "grid_load",
      "grid_charge", "grid_sell", "charge", "discharge", "soc", "zc", "zs"]
_NV = len(_V)


def _slices(t: int):
    base = _NV * t
    return {name: base + i for i, name in enumerate(_V)}


# ----------------------------------------------------------------------
# 闭式解
# ----------------------------------------------------------------------
def _closed_form(region: str, p_fac: np.ndarray, re_avail: np.ndarray,
                 storage: dict, allow_export: bool) -> dict[str, np.ndarray]:
    """m00 / m10 闭式解。返回全部 10 个连续变量序列。"""
    n = HOURS_ENERGY
    z = np.zeros(n)
    if not allow_export:
        re_direct = np.minimum(re_avail, p_fac)
        curt = re_avail - re_direct
        grid_load = p_fac - re_direct
        return {
            "re_direct": re_direct, "re_charge": z.copy(), "re_sell": z.copy(),
            "curt": curt, "grid_load": grid_load, "grid_charge": z.copy(),
            "grid_sell": z.copy(), "charge": z.copy(), "discharge": z.copy(),
            "soc": np.full(n, storage["InitialSOC_MWh"]),
        }
    # 允许外送：购售电互斥 —— 有购电则不外送，有外送则不购电
    sell_cap = min(storage["SellLimit_MW"], storage["MaxGridExport_MW"])
    re_direct = np.minimum(re_avail, p_fac)
    surplus = np.maximum(re_avail - p_fac, 0.0)
    re_sell = np.minimum(surplus, sell_cap)
    curt = surplus - re_sell
    grid_load = p_fac - re_direct          # 外送时 p_fac<=re_avail -> grid_load=0
    return {
        "re_direct": re_direct, "re_charge": z.copy(), "re_sell": re_sell,
        "curt": curt, "grid_load": grid_load, "grid_charge": z.copy(),
        "grid_sell": re_sell.copy(), "charge": z.copy(), "discharge": z.copy(),
        "soc": np.full(n, storage["InitialSOC_MWh"]),
    }


# ----------------------------------------------------------------------
# MILP 解（m01：储能 + 外送）
# ----------------------------------------------------------------------
def _solve_milp(p_fac: np.ndarray, re_avail: np.ndarray, price: np.ndarray,
                sell_price: np.ndarray, carbon: np.ndarray,
                storage: dict, objective: str = "cost") -> dict[str, np.ndarray]:
    n = HOURS_ENERGY
    nvars = _NV * n
    idx = {name: np.array([_slices(t)[name] for t in range(n)]) for name in _V}

    eta_c = storage["ChargeEfficiency"]
    eta_d = storage["DischargeEfficiency"]
    cap = storage["StorageCapacity_MWh"]
    min_soc = storage["MinSOC_MWh"]
    init_soc = storage["InitialSOC_MWh"]
    max_charge = storage["MaxChargePower_MW"]
    max_discharge = storage["MaxDischargePower_MW"]
    max_import = storage["MaxGridImport_MW"]
    sell_cap = min(storage["SellLimit_MW"], storage["MaxGridExport_MW"])

    # 目标：min sum_t [ (grid_load+grid_charge)*w1 - re_sell*w2 ]
    if objective == "cost":
        w_load = price
        w_sell = sell_price
    elif objective == "carbon":
        # 主目标最小碳排；加 1e-9*净成本 次级项打破平局（避免对售电无差异导致弃电）
        w_load = carbon + 1e-9 * price
        w_sell = 1e-9 * sell_price
    else:
        raise ValueError(objective)
    c = np.zeros(nvars)
    c[idx["grid_load"]] = w_load
    c[idx["grid_charge"]] = w_load
    c[idx["re_sell"]] = -w_sell

    rows = []
    lb = []
    ub = []

    def add(coeffs: dict[int, float], lo: float, hi: float):
        row = np.zeros(nvars)
        for j, v in coeffs.items():
            row[j] = v
        rows.append(row)
        lb.append(lo)
        ub.append(hi)

    for t in range(n):
        s = _slices(t)
        # 1) 新能源分流
        add({s["re_direct"]: 1, s["re_charge"]: 1, s["re_sell"]: 1, s["curt"]: 1},
            re_avail[t], re_avail[t])
        # 2) 功率平衡
        add({s["grid_load"]: 1, s["re_direct"]: 1, s["discharge"]: 1}, p_fac[t], p_fac[t])
        # 3) ChargePower = RE_charge + Grid_charge
        add({s["charge"]: 1, s["re_charge"]: -1, s["grid_charge"]: -1}, 0, 0)
        # 4) GridSell = RE_sell（禁止购电转售）
        add({s["grid_sell"]: 1, s["re_sell"]: -1}, 0, 0)
        # 5) 购售电互斥：purchase <= MaxGridImport*(1-zs) -> purchase + MaxGridImport*zs <= MaxGridImport
        add({s["grid_load"]: 1, s["grid_charge"]: 1, s["zs"]: max_import}, -np.inf, max_import)
        # 6) 外送上限
        add({s["re_sell"]: 1, s["zs"]: -sell_cap}, -np.inf, 0)
        # 7) 充放电互斥
        add({s["charge"]: 1, s["zc"]: -max_charge}, -np.inf, 0)
        add({s["discharge"]: 1, s["zc"]: max_discharge}, -np.inf, max_discharge)
        # 8) SOC 递推
        if t == 0:
            add({s["soc"]: 1, s["charge"]: -eta_c, s["discharge"]: 1 / eta_d},
                init_soc, init_soc)
        else:
            prev = _slices(t - 1)["soc"]
            add({s["soc"]: 1, prev: -1, s["charge"]: -eta_c, s["discharge"]: 1 / eta_d},
                0, 0)
    # 9) 终端 SOC
    s_last = _slices(n - 1)
    add({s_last["soc"]: 1}, init_soc, np.inf)

    bounds = Bounds(
        lb=np.zeros(nvars),
        ub=np.full(nvars, np.inf),
    )
    for t in range(n):
        s = _slices(t)
        bounds.lb[s["soc"]] = min_soc
        bounds.ub[s["soc"]] = cap
        bounds.lb[s["zc"]] = 0
        bounds.ub[s["zc"]] = 1
        bounds.lb[s["zs"]] = 0
        bounds.ub[s["zs"]] = 1

    constraints = LinearConstraint(np.vstack(rows), np.array(lb), np.array(ub))
    result = milp(c=c, constraints=constraints, bounds=bounds,
                  integrality=np.array([1 if name in ("zc", "zs") else 0
                                        for name in _V] * n),
                  options={"time_limit": 300})
    if not result.success:
        raise RuntimeError(f"MILP 求解失败: {result.message}")

    x = result.x
    out = {name: x[idx[name]] for name in _V}
    out["solver_status"] = result.status
    out["solver_message"] = result.message
    out["objective"] = result.fun
    return out


# ----------------------------------------------------------------------
# 统一入口
# ----------------------------------------------------------------------
def solve_energy(region: str, p_fac: np.ndarray, problem: Problem, mode: str,
                 objective: str = "cost") -> dict:
    """求解单个区域的能源子问题。

    参数:
        region: 区域名
        p_fac:  逐时设施负荷（MW），长度 2407
        problem: Problem 实例
        mode:   m00 | m10 | m01
        objective: cost | carbon（仅 m01 有意义）

    返回:
        包含全部能源变量序列、守恒残差与求解信息的 dict。
    """
    p_fac = np.asarray(p_fac, dtype=float)
    re_avail = problem.re_avail(region)
    price = problem.price(region)
    sell_price = problem.sell_price(region)
    carbon = problem.carbon_intensity(region)
    storage = problem.storage[region]

    if mode == MODE_M00:
        out = _closed_form(region, p_fac, re_avail, storage, allow_export=False)
    elif mode == MODE_M10:
        out = _closed_form(region, p_fac, re_avail, storage, allow_export=True)
    elif mode == MODE_M01:
        out = _solve_milp(p_fac, re_avail, price, sell_price, carbon, storage, objective)
    else:
        raise ValueError(mode)

    # 逐时守恒与口径派生
    n = HOURS_ENERGY
    grid_purchase = out["grid_load"] + out["grid_charge"]
    grid_sell = out["grid_sell"]
    gross_cost = float(np.sum(grid_purchase * price))
    revenue = float(np.sum(grid_sell * sell_price))
    net_cost = gross_cost - revenue
    co2 = float(np.sum(grid_purchase * carbon))
    re_used = out["re_direct"] + out["re_charge"] + out["re_sell"]
    re_util = float(np.sum(re_used) / np.sum(re_avail)) if np.sum(re_avail) > 0 else 0.0

    residual_re = np.max(np.abs(re_used + out["curt"] - re_avail))
    residual_balance = np.max(np.abs(out["grid_load"] + out["re_direct"] + out["discharge"] - p_fac))
    # SOC 递推残差
    soc = out["soc"]
    soc_prev = np.concatenate([[storage["InitialSOC_MWh"]], soc[:-1]])
    residual_soc = np.max(np.abs(soc - soc_prev
                                 - storage["ChargeEfficiency"] * out["charge"]
                                 + out["discharge"] / storage["DischargeEfficiency"]))

    out.update({
        "grid_purchase": grid_purchase,
        "gross_cost": gross_cost,
        "sell_revenue": revenue,
        "net_cost": net_cost,
        "carbon_tco2": co2,
        "re_utilization": re_util,
        "peak_grid_purchase": float(np.max(grid_purchase)),
        "grid_purchase_std": float(np.std(grid_purchase)),
        "residual_re": float(residual_re),
        "residual_balance": float(residual_balance),
        "residual_soc": float(residual_soc),
        "terminal_soc": float(soc[-1]),
        "mode": mode,
    })
    return out


def build_energy_schedule(problem: Problem, region: str, p_fac: np.ndarray,
                          ai_load: np.ndarray | None, mode: str,
                          objective: str = "cost") -> tuple[pd.DataFrame, dict]:
    """生成符合输出契约的 energy_schedule 行集（单区域）。

    参数:
        ai_load: AI IT 负荷（MW）；Q3 固定口径传 Baseline_AI_IT_Load，任务口径传重算值。
    """
    import pandas as pd

    out = solve_energy(region, p_fac, problem, mode, objective)
    n = HOURS_ENERGY
    non_ai = problem.non_ai_load(region)
    if ai_load is None:
        ai_load = np.zeros(n)
    it_load = non_ai + np.asarray(ai_load, dtype=float)
    rows = []
    for t in range(n):
        rows.append({
            "Hour": t,
            "Region": region,
            "AI_IT_Load_MW": float(ai_load[t]),
            "NonAI_IT_Load_MW": float(non_ai[t]),
            "IT_Load_MW": float(it_load[t]),
            "Total_Load_MW": float(p_fac[t]),
            "GridPurchase_MW": float(out["grid_purchase"][t]),
            "GridSell_MW": float(out["grid_sell"][t]),
            "GridLoad_MW": float(out["grid_load"][t]),
            "GridCharge_MW": float(out["grid_charge"][t]),
            "RenewableDirect_MW": float(out["re_direct"][t]),
            "RenewableCharge_MW": float(out["re_charge"][t]),
            "RenewableSell_MW": float(out["re_sell"][t]),
            "Curtailment_MW": float(out["curt"][t]),
            "ChargePower_MW": float(out["charge"][t]),
            "DischargePower_MW": float(out["discharge"][t]),
            "SOC_MWh": float(out["soc"][t]),
        })
    return pd.DataFrame(rows), out
