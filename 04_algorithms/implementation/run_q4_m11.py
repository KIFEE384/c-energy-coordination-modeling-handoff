# -*- coding: utf-8 -*-
"""M11（Q4）任务-能源联合优化编排。

口径（03_models/统一双柔性模型.md、04_algorithms/算法实现接口.md）：
  - Q4 任务变量独立：M11 重新执行任务层优化（不从 Q2 锁死解，仅以 x_base 为共同起点），
    每次任务方案都重新计算 AI 负荷并进入含储能的能源层求解；
  - 能源层使用 M01 口径（储能 + 新能源外送），目标最小净成本；
  - 与 Q2 相同的加权标量化生成近似非支配方案（诚实标记，不称全局最优）；
  - 对比 Q2 解仅作对照，不锁死。

输出：output/M11/<scenario>/task_schedule.csv、energy_schedule.csv、kpi 行、pareto.md。
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
from energy_solver import MODE_M01, build_energy_schedule
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
        df, _ = build_energy_schedule(problem, r, fac, ai, MODE_M01)
        frames.append(df)
    energy = pd.concat(frames, ignore_index=True)
    energy[OUT_COLUMNS].to_csv(out_dir / "energy_schedule.csv", index=False, encoding="utf-8-sig")
    return energy


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--lambdas", default=",".join(str(x) for x in LAMBDAS))
    parser.add_argument("--passes", type=int, default=0,
                        help="任务层缺口修复轮数；0=不迁移（储能覆盖缺口，联合最优），>0 强制迁移")
    args = parser.parse_args()

    problem = Problem(args.data_dir)
    x_base = load_x_base(args.repo_root)

    out_root = Path(__file__).resolve().parent / "output"
    log_path = out_root / "solver_log.jsonl"
    kpi_path = out_root / "kpi_summary.csv"

    kpi_rows = []
    pareto = []
    last_schedule_hash = None
    last_energy = None

    for lam in [float(x) for x in args.lambdas.split(",")]:
        scenario = f"lam{int(lam)}"
        t0 = time.time()
        optimizer = TaskOptimizer(problem, x_base)
        schedule = optimizer.optimize(lam, repair_passes=args.passes)

        v_task, nv_task = validate_task_schedule(problem, schedule, allow_migration=True)
        if nv_task:
            print(f"[{scenario}] 任务层违约 {nv_task}:", v_task[:5])
            continue

        cell_dir = out_root / "M11" / scenario
        cell_dir.mkdir(parents=True, exist_ok=True)
        schedule[["TaskID", "SourceRegion", "TargetRegion", "StartHour", "EndHour",
                  "NetworkLatency_ms", "GPU_Demand", "TaskType"]].to_csv(
            cell_dir / "task_schedule.csv", index=False, encoding="utf-8-sig")

        # 排程相同时复用能源结果（各 lambda 排程相同，避免重复 MILP）
        import hashlib
        sched_hash = hashlib.sha1(
            pd.util.hash_pandas_object(schedule, index=True).values).hexdigest()
        if sched_hash == last_schedule_hash and last_energy is not None:
            energy = last_energy
            last_energy.to_csv(cell_dir / "energy_schedule.csv", index=False, encoding="utf-8-sig")
        else:
            energy = solve_energy_for_schedule(problem, schedule, cell_dir)
            last_energy = energy
            last_schedule_hash = sched_hash
        v_energy, nv_energy = validate_energy_schedule(problem, energy, "m01")
        total_violations = nv_task + nv_energy
        kpi_rows.append(make_kpi_row("M11", scenario, problem, schedule, energy,
                                     total_violations, time.time() - t0,
                                     "task: x_base (storage covers deficit), energy: exact MILP"))
        pareto.append({"Scenario": scenario, "Lambda": lam,
                       "Cost_CNY": kpi_rows[-1]["Cost_CNY"],
                       "Carbon_tCO2": kpi_rows[-1]["Carbon_tCO2"],
                       "RE_Util": kpi_rows[-1]["RenewableUtilization"],
                       "MeanLatency_ms": kpi_rows[-1]["MeanLatency_ms"],
                       "P95Latency_ms": kpi_rows[-1]["P95Latency_ms"],
                       "Violations": total_violations})
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "event": "m11_cell", "scenario": scenario, "lambda": lam,
                "task_repair_passes": args.passes,
                "migrated_tasks": int((schedule.TargetRegion != schedule.SourceRegion).sum()),
                "runtime_s": round(time.time() - t0, 2),
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

    lines = ["# M11（Q4）任务-能源联合近似非支配方案", "",
             "> 任务层独立优化（不从 Q2 锁死）；联合最优决策为储能覆盖缺口小时、任务保持本地最优",
             "> （M10 无储能时必须迁移 1 个训练任务消除缺口，M11 有储能则不需要，AI 负荷逐时差异见 solver_log）。",
             "",
             "| Scenario | Lambda | Cost_CNY | Carbon_tCO2 | RE_Util | MeanLat | P95Lat | Violations |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in pareto:
        lines.append(f"| {row['Scenario']} | {row['Lambda']:.0f} | {row['Cost_CNY']:,.0f} | "
                     f"{row['Carbon_tCO2']:,.0f} | {row['RE_Util']:.4f} | "
                     f"{row['MeanLatency_ms']:.2f} | {row['P95Latency_ms']:.2f} | "
                     f"{row['Violations']} |")
    (out_root / "M11" / "pareto.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
