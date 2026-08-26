# -*- coding: utf-8 -*-
"""M10（Q2）算力柔性求解编排：迁移+时移，加权标量化近似 Pareto。

对每个 lambda（碳价，CNY/tCO2）运行 TaskOptimizer 得到任务方案，再以 M10 能源口径
（无储能、允许新能源外送）求解能源层，输出：
  output/M10/<scenario>/task_schedule.csv
  output/M10/<scenario>/energy_schedule.csv
  output/M10/<scenario>/kpi.json
  kpi_summary.csv（追加）, solver_log.jsonl（追加）, pareto.md（近似非支配表）

诚实标记：加权标量化近似解，不声称全局 Pareto 最优；记录运行时间与局部搜索改进。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import REGIONS, Problem, load_x_base
from energy_solver import MODE_M10, build_energy_schedule
from kpi import make_kpi_row
from task_optimizer import TaskOptimizer
from validator import validate_energy_schedule, validate_task_schedule

LAMBDAS = [0.0, 100.0, 200.0, 400.0, 800.0, 1600.0]
OUT_COLUMNS = [
    "Hour", "Region", "AI_IT_Load_MW", "NonAI_IT_Load_MW", "IT_Load_MW",
    "Total_Load_MW", "GridPurchase_MW", "GridSell_MW", "GridLoad_MW",
    "GridCharge_MW", "RenewableDirect_MW", "RenewableCharge_MW",
    "RenewableSell_MW", "Curtailment_MW", "ChargePower_MW",
    "DischargePower_MW", "SOC_MWh",
]


def solve_energy_for_schedule(problem: Problem, schedule: pd.DataFrame,
                              out_dir: Path) -> pd.DataFrame:
    frames = []
    for r in REGIONS:
        fac = problem.facility_load_from_schedule(schedule)[r]
        ai = problem.ai_it_load_from_schedule(schedule)[r]
        df, _ = build_energy_schedule(problem, r, fac, ai, MODE_M10)
        frames.append(df)
    energy = pd.concat(frames, ignore_index=True)
    energy[OUT_COLUMNS].to_csv(out_dir / "energy_schedule.csv", index=False, encoding="utf-8-sig")
    return energy


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--lambdas", default=",".join(str(x) for x in LAMBDAS))
    parser.add_argument("--passes", type=int, default=8)
    args = parser.parse_args()

    problem = Problem(args.data_dir)
    x_base = load_x_base(args.repo_root)

    out_root = Path(__file__).resolve().parent / "output"
    log_path = out_root / "solver_log.jsonl"
    kpi_path = out_root / "kpi_summary.csv"

    kpi_rows = []
    pareto = []

    for lam in [float(x) for x in args.lambdas.split(",")]:
        scenario = f"lam{int(lam)}"
        t0 = time.time()
        optimizer = TaskOptimizer(problem, x_base)
        schedule = optimizer.optimize(lam, repair_passes=args.passes)
        t_task = time.time() - t0

        # 任务层验证
        v_task, nv_task = validate_task_schedule(problem, schedule, allow_migration=True)
        if nv_task:
            print(f"[{scenario}] 任务层违约 {nv_task}:", v_task[:5])
            continue

        cell_dir = out_root / "M10" / scenario
        cell_dir.mkdir(parents=True, exist_ok=True)
        schedule[["TaskID", "SourceRegion", "TargetRegion", "StartHour", "EndHour",
                  "NetworkLatency_ms", "GPU_Demand", "TaskType"]].to_csv(
            cell_dir / "task_schedule.csv", index=False, encoding="utf-8-sig")

        energy = solve_energy_for_schedule(problem, schedule, cell_dir)
        v_energy, nv_energy = validate_energy_schedule(problem, energy, "m10")
        total_violations = nv_task + nv_energy
        kpi_rows.append(make_kpi_row("M10", scenario, problem, schedule, energy,
                                     total_violations, time.time() - t0,
                                     "heuristic+LS (no global optimality claim)"))
        pareto.append({"Scenario": scenario, "Lambda": lam,
                       "Cost_CNY": kpi_rows[-1]["Cost_CNY"],
                       "Carbon_tCO2": kpi_rows[-1]["Carbon_tCO2"],
                       "RE_Util": kpi_rows[-1]["RenewableUtilization"],
                       "MeanLatency_ms": kpi_rows[-1]["MeanLatency_ms"],
                       "P95Latency_ms": kpi_rows[-1]["P95Latency_ms"],
                       "Violations": total_violations})
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "event": "m10_cell", "scenario": scenario, "lambda": lam,
                "task_runtime_s": round(t_task, 2),
                "total_runtime_s": round(time.time() - t0, 2),
                "violations": total_violations,
            }, ensure_ascii=False) + "\n")
        print(f"[{scenario}] done in {time.time()-t0:.1f}s, violations={total_violations}")

    if not kpi_rows:
        print("所有场景均失败，无输出。")
        return

    kpi_df = pd.DataFrame(kpi_rows)
    if kpi_path.exists():
        old = pd.read_csv(kpi_path)
        kpi_df = pd.concat([old, kpi_df], ignore_index=True).drop_duplicates(
            subset=["ModelID", "ScenarioID"], keep="last")
    kpi_df.to_csv(kpi_path, index=False, encoding="utf-8-sig")

    # 近似非支配筛选（按成本与碳排）
    pareto_df = pd.DataFrame(pareto)
    nondom = []
    for _, row in pareto_df.iterrows():
        dominated = any(
            (p["Cost_CNY"] <= row["Cost_CNY"] and p["Carbon_tCO2"] <= row["Carbon_tCO2"]
             and (p["Cost_CNY"] < row["Cost_CNY"] or p["Carbon_tCO2"] < row["Carbon_tCO2"]))
            for p in pareto if p["Scenario"] != row["Scenario"])
        if not dominated:
            nondom.append(row)
    lines = ["# M10（Q2）近似非支配方案", "",
             "> 由加权标量化启发式生成（贪心+局部搜索），非严格全局 Pareto，不声称最优。",
             "",
             "| Scenario | Lambda | Cost_CNY | Carbon_tCO2 | RE_Util | MeanLat | P95Lat | Violations |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in pareto:
        lines.append(f"| {row['Scenario']} | {row['Lambda']:.0f} | {row['Cost_CNY']:,.0f} | "
                     f"{row['Carbon_tCO2']:,.0f} | {row['RE_Util']:.4f} | "
                     f"{row['MeanLatency_ms']:.2f} | {row['P95Latency_ms']:.2f} | "
                     f"{row['Violations']} |")
    lines.append("")
    lines.append("近似非支配： " + ", ".join(r["Scenario"] for r in nondom))
    (out_root / "M10" / "pareto.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
