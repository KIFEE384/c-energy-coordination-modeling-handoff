# -*- coding: utf-8 -*-
"""能源层四格运行：M00 / M01 / Q3(B3_ref) + B_ref 参照。

用法：
    python run_energy_cells.py --data-dir <附件数据目录> --repo-root <repo 根目录>

输出（repo/work/algorithm/output/ 下）：
    M00/energy_schedule.csv, M01/energy_schedule.csv, Q3_B3ref/energy_schedule.csv,
    kpi_summary.csv（累计追加）, solver_log.jsonl（累计追加）, validation_report.md

口径：
    - M00：x_base 设施负荷，无储能、无外送（纯反事实）；
    - M01：x_base 设施负荷，储能 + 外送（主结果最小净成本；另记录最小碳变体）；
    - Q3：附件给定 Baseline_AI_IT_Load+NonAI 设施负荷，储能 + 外送（题设实验，不与 M01 混称）；
    - B_ref：附件官方运行状态（region_time_data 直接统计，仅作参照）。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import REGIONS, Problem, load_x_base
from energy_solver import MODE_M00, MODE_M01, build_energy_schedule
from kpi import make_kpi_row
from validator import validate_energy_schedule, validate_task_schedule

OUT_COLUMNS = [
    "Hour", "Region", "AI_IT_Load_MW", "NonAI_IT_Load_MW", "IT_Load_MW",
    "Total_Load_MW", "GridPurchase_MW", "GridSell_MW", "GridLoad_MW",
    "GridCharge_MW", "RenewableDirect_MW", "RenewableCharge_MW",
    "RenewableSell_MW", "Curtailment_MW", "ChargePower_MW",
    "DischargePower_MW", "SOC_MWh",
]


def run_energy_cell(problem: Problem, model_id: str, scenario_id: str,
                    load_fn, mode: str, out_dir: Path,
                    log_rows: list[dict], objective: str = "cost") -> pd.DataFrame:
    """求解六区域能源子问题并写 energy_schedule。load_fn(region) -> (p_fac, ai_load)。"""
    t0 = time.time()
    frames = []
    per_region = {}
    for r in REGIONS:
        p_fac, ai_load = load_fn(r)
        df, out = build_energy_schedule(problem, r, p_fac, ai_load, mode, objective)
        frames.append(df)
        per_region[r] = out
        log_rows.append({
            "event": "energy_solve",
            "model": model_id,
            "scenario": scenario_id,
            "region": r,
            "mode": mode,
            "objective": objective,
            "gross_cost_cny": out["gross_cost"],
            "sell_revenue_cny": out["sell_revenue"],
            "net_cost_cny": out["net_cost"],
            "carbon_tco2": out["carbon_tco2"],
            "re_utilization": out["re_utilization"],
            "peak_grid_purchase_mw": out["peak_grid_purchase"],
            "grid_purchase_std_mw": out["grid_purchase_std"],
            "terminal_soc_mwh": out["terminal_soc"],
            "residual_re": out["residual_re"],
            "residual_balance": out["residual_balance"],
            "residual_soc": out["residual_soc"],
            "solver": out.get("solver_status", "closed-form"),
        })
    energy = pd.concat(frames, ignore_index=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    energy[OUT_COLUMNS].to_csv(out_dir / "energy_schedule.csv", index=False, encoding="utf-8-sig")
    runtime = time.time() - t0
    log_rows.append({
        "event": "energy_cell_done", "model": model_id, "scenario": scenario_id,
        "runtime_s": round(runtime, 3),
    })
    return energy, runtime


def b_ref_kpis(problem: Problem) -> dict:
    """附件官方运行状态 KPI（直接从 region_time_data 统计，含 Hour 2406）。"""
    cost = co2 = re_used = re_avail = revenue = 0.0
    peak = 0.0
    purchases = []
    for r in REGIONS:
        price = problem.price(r)
        sell = problem.sell_price(r)
        carbon = problem.carbon_intensity(r)
        gp = problem.series(r, "GridPurchase_MW")
        gs = problem.series(r, "GridSell_MW")
        used = problem.series(r, "UsedRenewable_MW")
        avail = problem.re_avail(r)
        cost += float(np.sum(gp * price))
        revenue += float(np.sum(gs * sell))
        co2 += float(np.sum(gp * carbon))
        re_used += float(np.sum(used + gs))
        re_avail += float(np.sum(avail))
        peak = max(peak, float(np.max(gp)))
        purchases.extend(gp.tolist())
    return {
        "Cost_CNY": cost,
        "SellRevenue_CNY": revenue,
        "NetCost_CNY": cost - revenue,
        "Carbon_tCO2": co2,
        "RenewableUtilization": re_used / re_avail if re_avail > 0 else 0.0,
        "PeakGridPurchase_MW": peak,
        "GridPurchaseStd_MW": float(np.std(purchases)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args()

    problem = Problem(args.data_dir)
    x_base = load_x_base(args.repo_root)

    # 1) 校验 x_base 任务层（M00/M01 的任务边界）
    task_violations, _ = validate_task_schedule(problem, x_base, allow_migration=False)
    assert not task_violations, f"x_base 任务层违约: {task_violations[:5]}"

    out_root = Path(__file__).resolve().parent / "output"
    out_root.mkdir(parents=True, exist_ok=True)
    log_path = out_root / "solver_log.jsonl"
    kpi_path = out_root / "kpi_summary.csv"

    log_rows: list[dict] = []
    kpi_rows: list[dict] = []

    def x_base_load(region: str):
        fac = problem.facility_load_from_schedule(x_base)[region]
        ai = problem.ai_it_load_from_schedule(x_base)[region]
        return fac, ai

    def q3_load(region: str):
        fac = problem.baseline_facility_load(region)
        ai = problem.baseline_ai_load(region)
        return fac, ai

    # ---- M00 ----
    energy_m00, rt_m00 = run_energy_cell(
        problem, "M00", "base", x_base_load, MODE_M00,
        out_root / "M00", log_rows)
    v_energy_m00, nv_m00 = validate_energy_schedule(problem, energy_m00, "m00")
    kpi_rows.append(make_kpi_row(
        "M00", "base", problem, x_base, energy_m00, nv_m00, rt_m00,
        "closed-form (deterministic)"))

    # ---- M01（主：最小净成本） ----
    energy_m01, rt_m01 = run_energy_cell(
        problem, "M01", "base", x_base_load, MODE_M01,
        out_root / "M01", log_rows, objective="cost")
    v_energy_m01, nv_m01 = validate_energy_schedule(problem, energy_m01, "m01")
    kpi_rows.append(make_kpi_row(
        "M01", "base", problem, x_base, energy_m01, nv_m01, rt_m01,
        "exact MILP (HiGHS), min net cost"))

    # ---- M01 最小碳变体（仅记录 KPI，不覆盖主结果） ----
    energy_m01c, rt_m01c = run_energy_cell(
        problem, "M01", "min_carbon", x_base_load, MODE_M01,
        out_root / "M01_mincarbon", log_rows, objective="carbon")
    v_m01c, nv_m01c = validate_energy_schedule(problem, energy_m01c, "m01")
    kpi_rows.append(make_kpi_row(
        "M01", "min_carbon", problem, x_base, energy_m01c, nv_m01c, rt_m01c,
        "exact MILP (HiGHS), min carbon"))

    # ---- Q3 / B3_ref（题设固定负荷实验） ----
    energy_q3, rt_q3 = run_energy_cell(
        problem, "Q3_B3ref", "attachment_fixed_load", q3_load, MODE_M01,
        out_root / "Q3_B3ref", log_rows, objective="cost")
    v_q3, nv_q3 = validate_energy_schedule(problem, energy_q3, "m01")
    kpi_rows.append(make_kpi_row(
        "Q3", "B3_ref", problem, None, energy_q3, nv_q3, rt_q3,
        "exact MILP (HiGHS), fixed attachment load"))

    # ---- B_ref 参照 ----
    bref = b_ref_kpis(problem)
    b_ref_row = {
        "ModelID": "B_ref", "ScenarioID": "attachment_operation",
        "MeanLatency_ms": np.nan, "P95Latency_ms": np.nan, **bref,
        "Violations": 0, "Runtime_s": 0.0, "LowerBound_or_Gap": "reference only",
    }
    kpi_rows.append(b_ref_row)

    # ---- 汇总输出 ----
    kpi_df = pd.DataFrame(kpi_rows)
    if kpi_path.exists():
        old = pd.read_csv(kpi_path)
        kpi_df = pd.concat([old, kpi_df], ignore_index=True).drop_duplicates(
            subset=["ModelID", "ScenarioID"], keep="last")
    kpi_df.to_csv(kpi_path, index=False, encoding="utf-8-sig")

    with log_path.open("a", encoding="utf-8") as fh:
        for row in log_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ---- 验证报告 ----
    lines = [
        "# 能源层四格验收报告",
        "",
        f"- 任务层 x_base：违约 {nv_m00 if False else 0}（运行前已断言通过）",
        f"- M00 能源层违约：{nv_m00}；M01 违约：{nv_m01}；M01(min-carbon) 违约：{nv_m01c}；Q3 违约：{nv_q3}",
    ]
    for label, vl in [("M00", v_energy_m00), ("M01", v_energy_m01),
                      ("M01_mincarbon", v_m01c), ("Q3", v_q3)]:
        if vl:
            lines.append(f"  {label}:")
            lines += [f"    - {v}" for v in vl[:10]]
    lines.append("")
    lines.append("| ModelID | ScenarioID | Cost_CNY(购电) | SellRevenue_CNY | NetCost_CNY | Carbon_tCO2 | RE_Util | Violations |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for _, row in kpi_df.iterrows():
        lines.append(
            f"| {row['ModelID']} | {row['ScenarioID']} | {row['Cost_CNY']:,.0f} | "
            f"{row['SellRevenue_CNY']:,.0f} | {row['NetCost_CNY']:,.0f} | "
            f"{row['Carbon_tCO2']:,.0f} | {row['RenewableUtilization']:.4f} | "
            f"{row['Violations']} |")
    report = "\n".join(lines)
    (out_root / "validation_report.md").write_text(report, encoding="utf-8")
    print(report)
    print("\n已写出:", out_root)


if __name__ == "__main__":
    main()
