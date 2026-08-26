# -*- coding: utf-8 -*-
"""M11（Q4）分解式联合优化（复审修订版语义 §5/§7）。

方法（分解式联合启发式）：
  外层生成候选任务排程 x^k（k=0..K）：
    - x^0 = x_base（不迁移）
    - x^k = 缺口小时定向修复（不同修复轮数 / 碳价权重）
  每个候选都重新计算 AI(x^k)、P_fac(x^k) 与排程哈希；
  内层对每个候选求解相同的含储能能源子问题（MODE_M01，min 净成本），得到 y*(x^k)；
  外层以 F(x^k, y*(x^k)) = 净成本（平局按时延、迁移数）选择最优候选；
  记录迭代轮次、候选排程哈希、AI/设施负荷哈希、内层目标与停止准则。

  诚实标记：分解式联合启发式，不声称全局最优；不锁死 Q2 任务解（候选独立生成）。
  ExportPolicy=PERMIT_RE_ONLY（与 M00_fair/M10/M01-xbase 一致）。

输出：output/M11/base/{task_schedule,energy_schedule}.csv、coordination_log.jsonl、kpi 行。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import REGIONS, Problem, load_x_base
from energy_solver import MODE_M01, build_energy_schedule
from evidence import facility_load_hash, sha256_df
from kpi import make_kpi_row
from task_optimizer import TaskOptimizer
from validator import validate_energy_schedule, validate_task_schedule

OUT_COLUMNS = [
    "Hour", "Region", "AI_IT_Load_MW", "NonAI_IT_Load_MW", "IT_Load_MW",
    "Total_Load_MW", "GridPurchase_MW", "GridSell_MW", "GridLoad_MW",
    "GridCharge_MW", "RenewableDirect_MW", "RenewableCharge_MW",
    "RenewableSell_MW", "Curtailment_MW", "ChargePower_MW",
    "DischargePower_MW", "SOC_MWh",
]

REPAIR_PASSES = [0, 1, 8]                 # 外层候选的修复轮数
LAMBDAS_FOR_CANDIDATES = [100.0, 400.0]   # 候选生成使用的碳价权重


def solve_energy_for_schedule(problem: Problem, schedule: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for r in REGIONS:
        fac = problem.facility_load_from_schedule(schedule)[r]
        ai = problem.ai_it_load_from_schedule(schedule)[r]
        df, _ = build_energy_schedule(problem, r, fac, ai, MODE_M01)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args()

    problem = Problem(args.data_dir)
    x_base = load_x_base(args.repo_root)

    out_root = Path(__file__).resolve().parent / "output"
    cell_dir = out_root / "M11" / "base"
    cell_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_root / "solver_log.jsonl"
    kpi_path = out_root / "kpi_summary.csv"
    coord_path = cell_dir / "coordination_log.jsonl"

    t0 = time.time()
    candidates = []  # (label, schedule_df)

    # 候选生成（外层）：不同修复轮数与碳价权重，排程哈希去重
    seen_hash = set()
    for lam in LAMBDAS_FOR_CANDIDATES:
        for passes in REPAIR_PASSES:
            optimizer = TaskOptimizer(problem, x_base)
            sched = optimizer.optimize(lam, repair_passes=passes)
            h = sha256_df(sched[["TaskID", "TargetRegion", "StartHour"]])
            if h in seen_hash:
                continue
            seen_hash.add(h)
            candidates.append((f"lam{int(lam)}_repair{passes}", sched))

    # 内层能源评估 + 外层选择
    evaluated = []
    for label, sched in candidates:
        v_task, nv_task = validate_task_schedule(problem, sched, allow_migration=True)
        if nv_task:
            print(f"[{label}] 任务层违约 {nv_task}，跳过")
            continue
        energy = solve_energy_for_schedule(problem, sched)
        v_energy, nv_energy = validate_energy_schedule(problem, energy, "m01")
        net_cost = 0.0
        gross_cost = 0.0
        for r in REGIONS:
            sub = energy[energy["Region"] == r]
            gross = float(np.sum(sub["GridPurchase_MW"] * problem.price(r)))
            revenue = float(np.sum(sub["GridSell_MW"] * problem.sell_price(r)))
            gross_cost += gross
            net_cost += gross - revenue
        mig = int((sched.TargetRegion != sched.SourceRegion).sum())
        mean_lat = float(sched.NetworkLatency_ms.mean())
        row = {
            "candidate": label,
            "task_schedule_hash": sha256_df(sched[["TaskID", "TargetRegion", "StartHour"]]),
            "facility_load_hash": facility_load_hash(problem, sched),
            "energy_schedule_hash": hashlib.sha256(
                energy[OUT_COLUMNS].to_csv(index=False).encode()).hexdigest().upper(),
            "migrated_tasks": mig,
            "mean_latency_ms": round(mean_lat, 4),
            "inner_net_cost_cny": round(net_cost, 2),
            "inner_gross_cost_cny": round(gross_cost, 2),
            "task_violations": nv_task,
            "energy_violations": nv_energy,
        }
        evaluated.append((label, sched, energy, row))
        with coord_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[{label}] net_cost={row['inner_net_cost_cny']:,.0f} mig={mig} "
              f"lat={mean_lat:.2f} violations={nv_task + nv_energy}")

    if not evaluated:
        print("无可行候选，M11 失败。")
        return

    # 外层选择：min 净成本，平局按时延、迁移数
    best = min(evaluated, key=lambda e: (e[3]["inner_net_cost_cny"],
                                         e[3]["mean_latency_ms"],
                                         e[3]["migrated_tasks"]))
    label, sched, energy, row = best
    with coord_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "event": "m11_selected", "selected": label,
            "selection_rule": "min inner net cost, tie-break latency then migrations",
            "runtime_s": round(time.time() - t0, 2),
        }, ensure_ascii=False) + "\n")

    # 写出选定方案
    sched[["TaskID", "SourceRegion", "TargetRegion", "StartHour", "EndHour",
           "NetworkLatency_ms", "GPU_Demand", "TaskType"]].to_csv(
        cell_dir / "task_schedule.csv", index=False, encoding="utf-8-sig")
    energy[OUT_COLUMNS].to_csv(cell_dir / "energy_schedule.csv", index=False, encoding="utf-8-sig")

    total_violations = row["task_violations"] + row["energy_violations"]
    kpi_rows = [make_kpi_row("M11", "base", problem, sched, energy, total_violations,
                             time.time() - t0,
                             "decomposed joint heuristic, outer candidates + inner exact MILP",
                             "PERMIT_RE_ONLY")]
    kpi_df = pd.DataFrame(kpi_rows)
    if kpi_path.exists():
        old = pd.read_csv(kpi_path)
        kpi_df = pd.concat([old, kpi_df], ignore_index=True).drop_duplicates(
            subset=["ModelID", "ScenarioID"], keep="last")
    kpi_df.to_csv(kpi_path, index=False, encoding="utf-8-sig")

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "event": "m11_cell", "scenario": "base",
            "selected_candidate": label,
            "candidate_count": len(evaluated),
            "runtime_s": round(time.time() - t0, 2),
            "violations": total_violations,
        }, ensure_ascii=False) + "\n")

    lines = ["# M11（Q4）分解式联合优化（复审修订版语义）", "",
             f"> 外层候选 {len(evaluated)} 个（缺口修复轮数×碳价权重，排程哈希去重），内层能源精确 MILP。",
             f"> 选定候选：**{label}**（规则：min 净成本，平局按时延/迁移数）。",
             "> 诚实标记：分解式联合启发式，不声称全局最优；任务解独立于 Q2 生成，不锁死。",
             "",
             "| Candidate | Migrated | MeanLat_ms | InnerNetCost_CNY | InnerGrossCost_CNY | TaskViol | EnergyViol |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for _, _, _, r in evaluated:
        lines.append(f"| {r['candidate']} | {r['migrated_tasks']} | {r['mean_latency_ms']:.2f} | "
                     f"{r['inner_net_cost_cny']:,.0f} | {r['inner_gross_cost_cny']:,.0f} | "
                     f"{r['task_violations']} | {r['energy_violations']} |")
    lines.append("")
    lines.append("迭代记录：coordination_log.jsonl（候选排程/设施/能源哈希、内层目标、停止准则）。")
    (out_root / "M11" / "pareto.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
