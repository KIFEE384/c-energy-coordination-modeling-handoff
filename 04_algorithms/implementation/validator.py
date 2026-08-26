# -*- coding: utf-8 -*-
"""验收 validator（对应 05_validation/acceptance_tests.md 与 04_algorithms/算法实现接口.md）。

任务层断言：
  - 唯一指派：每个 TaskID 恰一条记录；GPU 占用不超 Available_GPU；
  - 实时任务 StartHour == ArrivalHour；
  - EndHour <= 2406 且不占用 [2406, 2407)（EndHour <= 2406）；
  - 截止期：EndHour <= LatestFinishHour（容差 TOL）；
  - Q1：TargetRegion == SourceRegion；
  - Q2/Q4：TargetRegion 属于 EligibleRegions，且单向时延 <= MaxLatency_ms；
  - GPU / IT / 设施功率逐区域逐时不超限（IT = NonAI + AI_IT；设施 = PUE * IT）。

能源层断言（给定 energy_schedule 与 mode）：
  - 新能源分流、功率平衡、SOC 递推残差 <= 容差；
  - SOC 边界、终端 SOC_2406 >= InitialSOC；
  - 购电 <= MaxGridImport、售电 <= min(MaxGridExport, SellLimit)；
  - 购售电、充放电互斥（数值上不出现同小时双正值，容差内）；
  - m10：无储能动作且 GridSell == RenewableSell。

返回 (violation 列表, 计数)。所有容差默认 1e-4（能源），1e-6（功率）。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from data_loader import HOURS_ENERGY, REGIONS, TOL, Problem

ENERGY_TOL = 1e-4


# ----------------------------------------------------------------------
# 任务层
# ----------------------------------------------------------------------
def validate_task_schedule(problem: Problem, schedule: pd.DataFrame,
                           allow_migration: bool = False) -> tuple[list[str], int]:
    violations: list[str] = []
    sched = schedule.copy()
    sched["TaskID"] = sched["TaskID"].astype(str)
    task_ids = set(problem.tasks["TaskID"])

    # 唯一指派
    if len(sched) != len(task_ids):
        violations.append(f"任务记录数 {len(sched)} != 任务总数 {len(task_ids)}")
    dup = sched["TaskID"].duplicated().sum()
    if dup:
        violations.append(f"重复 TaskID 记录 {dup} 条")
    missing = task_ids - set(sched["TaskID"])
    if missing:
        violations.append(f"缺失任务 {len(missing)} 条")

    # 关联 workload 表补齐任务属性（x_base CSV 不含 EarliestStartHour / MaxLatency_ms）
    task_meta = problem.tasks.set_index("TaskID")
    for col in ("TaskType", "SourceRegion", "ArrivalHour", "EarliestStartHour",
                "LatestFinishHour", "MaxLatency_ms", "GPU_Demand"):
        if col not in sched.columns:
            sched[col] = sched["TaskID"].map(task_meta[col])

    # 逐任务基本断言
    gpu_load = {r: np.zeros(HOURS_ENERGY) for r in REGIONS}
    ai_load = {r: np.zeros(HOURS_ENERGY) for r in REGIONS}
    for _, task in sched.iterrows():
        tid = task["TaskID"]
        src = task["SourceRegion"]
        dst = task["TargetRegion"]
        start = float(task["StartHour"])
        end = float(task["EndHour"])
        if not allow_migration and dst != src:
            violations.append(f"{tid}: Q1 不允许迁移 TargetRegion != SourceRegion")
        if allow_migration:
            if dst not in problem.eligible_regions(task):
                violations.append(f"{tid}: 目标区域 {dst} 不在可行时延集合内")
            else:
                lat = problem.latency.get((src, dst), math.inf)
                if lat > float(task["MaxLatency_ms"]) + TOL:
                    violations.append(f"{tid}: 时延 {lat} > MaxLatency {task['MaxLatency_ms']}")
        if task["TaskType"] == "RealTimeInference" and abs(start - float(task["ArrivalHour"])) > TOL:
            violations.append(f"{tid}: 实时任务未到达即开工 (start={start})")
        if end > 2406.0 + TOL:
            violations.append(f"{tid}: 占用 Hour 2406 之后 (EndHour={end})")
        if end > float(task["LatestFinishHour"]) + TOL:
            violations.append(f"{tid}: 超过截止期 LatestFinishHour={task['LatestFinishHour']}")
        if start < float(task["EarliestStartHour"]) - TOL:
            violations.append(f"{tid}: 早于 EarliestStartHour")

        # 累加负荷
        demand = float(task["GPU_Demand"])
        unit_power = problem.power[task["TaskType"]]
        for hour in range(math.floor(start), min(HOURS_ENERGY - 1, math.ceil(end) - 1) + 1):
            ov = problem.overlap(start, end, hour)
            if ov > 0:
                gpu_load[dst][hour] += demand * ov
                ai_load[dst][hour] += demand * unit_power * ov

    # 容量断言
    for r in REGIONS:
        cap = problem.capacity[r]
        for hour in range(HOURS_ENERGY):
            gpu = gpu_load[r][hour]
            it = problem.non_ai_load(r)[hour] + ai_load[r][hour]
            fac = it * cap["PUE"]
            if gpu > cap["Available_GPU"] + TOL:
                violations.append(f"{r} Hour {hour}: GPU 超限 {gpu:.4f} > {cap['Available_GPU']}")
            if it > cap["Max_IT_Power_MW"] + TOL:
                violations.append(f"{r} Hour {hour}: IT 超限 {it:.4f}")
            if fac > cap["Max_Facility_Power_MW"] + TOL:
                violations.append(f"{r} Hour {hour}: 设施超限 {fac:.4f}")
    return violations, len(violations)


# ----------------------------------------------------------------------
# 能源层
# ----------------------------------------------------------------------
def validate_energy_schedule(problem: Problem, energy: pd.DataFrame,
                             mode: str) -> tuple[list[str], int]:
    violations: list[str] = []
    for r in REGIONS:
        sub = energy[energy["Region"] == r].sort_values("Hour").reset_index(drop=True)
        if len(sub) != HOURS_ENERGY:
            violations.append(f"{r}: energy_schedule 行数 {len(sub)} != 2407")
            continue
        st = problem.storage[r]
        p_fac = sub["Total_Load_MW"].to_numpy(dtype=float)
        re_avail = problem.re_avail(r)
        price = problem.price(r)
        sell_price = problem.sell_price(r)

        re_direct = sub["RenewableDirect_MW"].to_numpy(dtype=float)
        re_charge = sub["RenewableCharge_MW"].to_numpy(dtype=float)
        re_sell = sub["RenewableSell_MW"].to_numpy(dtype=float)
        curt = sub["Curtailment_MW"].to_numpy(dtype=float)
        grid_load = sub["GridLoad_MW"].to_numpy(dtype=float)
        grid_charge = sub["GridCharge_MW"].to_numpy(dtype=float)
        grid_sell = sub["GridSell_MW"].to_numpy(dtype=float)
        charge = sub["ChargePower_MW"].to_numpy(dtype=float)
        discharge = sub["DischargePower_MW"].to_numpy(dtype=float)
        soc = sub["SOC_MWh"].to_numpy(dtype=float)
        gp = sub["GridPurchase_MW"].to_numpy(dtype=float)

        def chk(name: str, cond: np.ndarray, tol: float = ENERGY_TOL):
            bad = np.where(np.abs(cond) > tol)[0]
            for h in bad[:5]:
                violations.append(f"{r} Hour {h}: {name} 残差 {cond[h]:.6g}")

        chk("新能源分流", re_direct + re_charge + re_sell + curt - re_avail)
        chk("功率平衡", grid_load + re_direct + discharge - p_fac)
        chk("GridPurchase 定义", gp - (grid_load + grid_charge))
        chk("GridSell=RE_sell", grid_sell - re_sell)
        chk("Charge 定义", charge - (re_charge + grid_charge))
        chk("SOC 递推", soc - np.concatenate([[st["InitialSOC_MWh"]], soc[:-1]])
            - st["ChargeEfficiency"] * charge + discharge / st["DischargeEfficiency"])

        # 边界
        if np.max(gp) > st["MaxGridImport_MW"] + ENERGY_TOL:
            violations.append(f"{r}: 购电超 MaxGridImport {np.max(gp):.4f}")
        sell_cap = min(st["SellLimit_MW"], st["MaxGridExport_MW"])
        if np.max(grid_sell) > sell_cap + ENERGY_TOL:
            violations.append(f"{r}: 售电超上限 {np.max(grid_sell):.4f}")
        if np.min(soc) < st["MinSOC_MWh"] - ENERGY_TOL:
            violations.append(f"{r}: SOC 低于 MinSOC {np.min(soc):.4f}")
        if np.max(soc) > st["StorageCapacity_MWh"] + ENERGY_TOL:
            violations.append(f"{r}: SOC 超容量 {np.max(soc):.4f}")
        if soc[-1] < st["InitialSOC_MWh"] - ENERGY_TOL:
            violations.append(f"{r}: 终端 SOC {soc[-1]:.4f} < InitialSOC {st['InitialSOC_MWh']}")
        if np.max(charge) > st["MaxChargePower_MW"] + ENERGY_TOL:
            violations.append(f"{r}: 充电功率超限")
        if np.max(discharge) > st["MaxDischargePower_MW"] + ENERGY_TOL:
            violations.append(f"{r}: 放电功率超限")

        # 互斥（数值容差内不允许同小时双正值）
        both_cd = np.minimum(charge, discharge)
        if np.max(both_cd) > ENERGY_TOL:
            violations.append(f"{r}: 充放电同时为正 max={np.max(both_cd):.6g}")
        both_ps = np.minimum(gp, grid_sell)
        if np.max(both_ps) > ENERGY_TOL:
            violations.append(f"{r}: 购售电同时为正 max={np.max(both_ps):.6g}")

        if mode in ("m10", "q2"):
            if np.max(np.abs(charge)) > ENERGY_TOL or np.max(np.abs(discharge)) > ENERGY_TOL \
                    or np.max(np.abs(grid_charge)) > ENERGY_TOL or np.max(np.abs(re_charge)) > ENERGY_TOL:
                violations.append(f"{r}: m10 不应有储能动作")
            chk("m10 GridSell=RE_sell", grid_sell - re_sell)

        # 成本口径一致性
        expect_cost = float(np.sum(gp * price) - np.sum(grid_sell * sell_price))
        # 不在此处断言，仅记录
    return violations, len(violations)
