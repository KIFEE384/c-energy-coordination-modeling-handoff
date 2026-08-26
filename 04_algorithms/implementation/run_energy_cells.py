# -*- coding: utf-8 -*-
"""能源层四格运行（复审修订版语义，03_models/统一双柔性模型_复审修订版.md）。

单元命名与 ExportPolicy（DEC-008/DEC-009）：
  - M00_Q1  : x_base 负荷，无储能，ExportPolicy=FORBID（Q1 解释性基线，不参与四格归因）
  - M00_fair: x_base 负荷，无储能，ExportPolicy=PERMIT_RE_ONLY（四格公平基线）
  - M01-xbase: x_base 负荷，储能 + 外送，PERMIT_RE_ONLY（四格储能主效应）
  - Q3-B3ref: 附件固定负荷（B3_ref），储能 + 外送，PERMIT_RE_ONLY（题设实验，独立报告）
  - B_ref   : 附件官方运行状态（region_time_data 直接统计，仅参照）

输出（output/ 下）：
  M00_Q1/ M00_fair/ M01-xbase/ Q3_B3ref/ 的 energy_schedule.csv，
  kpi_summary.csv（含 ExportPolicy 列）, solver_log.jsonl, validation_report.md。
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
from energy_solver import MODE_M00, MODE_M01, MODE_M10, build_energy_schedule
from kpi import make_kpi_row
from validator import validate_energy_schedule, validate_task_schedule

OUT_COLUMNS = [
    "Hour", "Region", "AI_IT_Load_MW", "NonAI_IT_Load_MW", "IT_Load_MW",
    "Total_Load_MW", "GridPurchase_MW", "GridSell_MW", "GridLoad_MW",
    "GridCharge_MW", "RenewableDirect_MW", "RenewableCharge_MW",
    "RenewableSell_MW", "Curtailment_MW", "ChargePower_MW",
    "DischargePower_MW", "SOC_MWh",
]

PERMIT = "PERMIT_RE_ONLY"
FORBID = "FORBID"


def run_energy_cell(problem: Problem, model_id: str, scenario_id: str,
                    load_fn, mode: str, export_policy: str, out_dir: Path,
                    log_rows: list[dict], objective: str = "cost") -> pd.DataFrame:
    """求解六区域能源子问题并写 energy_schedule。load_fn(region) -> (p_fac, ai_load)。"""
    t0 = time.time()
    frames = []
    for r in REGIONS:
        p_fac, ai_load = load_fn(r)
        df, out = build_energy_schedule(problem, r, p_fac, ai_load, mode, objective)
        frames.append(df)
        log_rows.append({
            "event": "energy_solve",
            "model": model_id,
            "scenario": scenario_id,
            "export_policy": export_policy,
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
    log_rows.append({
        "event": "energy_cell_done", "model": model_id, "scenario": scenario_id,
        "export_policy": export_policy, "runtime_s": round(time.time() - t0, 3),
    })
    return energy


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

    # ---- M00_Q1（无外送，Q1 解释性基线） ----
    energy_q1 = run_energy_cell(problem, "M00_Q1", "base", x_base_load, MODE_M00, FORBID,
                                out_root / "M00_Q1", log_rows)
    _, nv = validate_energy_schedule(problem, energy_q1, "m00")
    kpi_rows.append(make_kpi_row("M00_Q1", "base", problem, x_base, energy_q1, nv,
                                 time.time(), "closed-form (deterministic)", FORBID))

    # ---- M00_fair（四格公平基线：无储能、允许外送） ----
    energy_fair = run_energy_cell(problem, "M00_fair", "base", x_base_load, MODE_M10, PERMIT,
                                  out_root / "M00_fair", log_rows)
    _, nv = validate_energy_schedule(problem, energy_fair, "m10")
    kpi_rows.append(make_kpi_row("M00_fair", "base", problem, x_base, energy_fair, nv,
                                 time.time(), "closed-form (deterministic)", PERMIT))

    # ---- M01-xbase（四格储能主效应） ----
    energy_m01 = run_energy_cell(problem, "M01-xbase", "base", x_base_load, MODE_M01, PERMIT,
                                 out_root / "M01-xbase", log_rows, objective="cost")
    _, nv = validate_energy_schedule(problem, energy_m01, "m01")
    kpi_rows.append(make_kpi_row("M01-xbase", "base", problem, x_base, energy_m01, nv,
                                 time.time(), "exact MILP (HiGHS), min net cost", PERMIT))

    # ---- Q3-B3ref（题设固定负荷实验，独立报告） ----
    energy_q3 = run_energy_cell(problem, "Q3-B3ref", "attachment_fixed_load", q3_load,
                                MODE_M01, PERMIT, out_root / "Q3_B3ref", log_rows,
                                objective="cost")
    _, nv = validate_energy_schedule(problem, energy_q3, "m01")
    kpi_rows.append(make_kpi_row("Q3-B3ref", "attachment_fixed_load", problem, None,
                                 energy_q3, nv, time.time(),
                                 "exact MILP (HiGHS), fixed attachment load", PERMIT))

    # ---- B_ref 参照 ----
    bref = b_ref_kpis(problem)
    b_ref_row = {
        "ModelID": "B_ref", "ScenarioID": "attachment_operation",
        "ExportPolicy": "reference_only", "MeanLatency_ms": np.nan,
        "P95Latency_ms": np.nan, **bref,
        "Violations": 0, "Runtime_s": 0.0, "LowerBound_or_Gap": "reference only",
    }
    kpi_rows.append(b_ref_row)

    kpi_df = pd.DataFrame(kpi_rows)
    if kpi_path.exists():
        old = pd.read_csv(kpi_path)
        kpi_df = pd.concat([old, kpi_df], ignore_index=True).drop_duplicates(
            subset=["ModelID", "ScenarioID"], keep="last")
    kpi_df.to_csv(kpi_path, index=False, encoding="utf-8-sig")

    with log_path.open("a", encoding="utf-8") as fh:
        for row in log_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 验证报告
    lines = ["# 能源层四格验收报告（复审修订版语义）", "",
             "- 任务层 x_base：零违约（运行前断言通过）",
             f"- M00_Q1 违约：{kpi_rows[0]['Violations']}；M00_fair：{kpi_rows[1]['Violations']}；"
             f"M01-xbase：{kpi_rows[2]['Violations']}；Q3-B3ref：{kpi_rows[3]['Violations']}",
             f"- ExportPolicy：M00_Q1={FORBID}；M00_fair/M01-xbase/Q3-B3ref={PERMIT}（与 M10/M11 一致）",
             ""]
    lines.append("| ModelID | ScenarioID | ExportPolicy | Cost_CNY | SellRevenue_CNY | Carbon_tCO2 | RE_Util | Violations |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for _, row in kpi_df.iterrows():
        lines.append(
            f"| {row['ModelID']} | {row['ScenarioID']} | {row['ExportPolicy']} | "
            f"{row['Cost_CNY']:,.0f} | {row['SellRevenue_CNY']:,.0f} | "
            f"{row['Carbon_tCO2']:,.0f} | {row['RenewableUtilization']:.4f} | "
            f"{row['Violations']} |")
    report = "\n".join(lines)
    (out_root / "validation_report.md").write_text(report, encoding="utf-8")
    print(report)
    print("\n已写出:", out_root)


if __name__ == "__main__":
    main()
