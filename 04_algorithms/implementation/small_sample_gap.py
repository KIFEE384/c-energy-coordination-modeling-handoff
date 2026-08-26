# -*- coding: utf-8 -*-
"""小样本精确 gap 评估（M10 启发式解质量诚实报告）。

方法（04_algorithms/算法实现接口.md 第 5 节）：
  - 取一个 48 小时窗口（默认 ArrivalHour in [400, 448)）内的柔性任务作为小样本；
  - 背景负荷 = x_base 负荷减去窗口任务在 x_base 中的排程贡献；
  - 精确模型：CP-SAT 二元指派（区域 × 窗口内整数启动小时），容量为硬约束，
    目标与启发式相同的标量化信号（静态影子成本 + lambda*碳价）；
  - 启发式：同一候选集上的贪心；
  - gap = (启发式目标 - 精确最优)/精确最优。

输出：output/q2_gap/gap_report.md 与日志行。
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import HOURS_TASK, REGIONS, TOL, Problem, load_x_base
from task_optimizer import TaskOptimizer

WINDOW_START = 400
WINDOW_LEN = 48


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--lambda", dest="lam", type=float, default=100.0)
    parser.add_argument("--window-start", type=int, default=WINDOW_START)
    parser.add_argument("--window-len", type=int, default=WINDOW_LEN)
    args = parser.parse_args()

    problem = Problem(args.data_dir)
    x_base = load_x_base(args.repo_root)
    opt = TaskOptimizer(problem, x_base)
    opt._prepare_ranks(args.lam)

    ws, wl = args.window_start, args.window_len
    we = ws + wl  # 窗口结束（排他）

    # 窗口任务：到达在窗口内、且可在窗口内完成
    window_tasks = []
    for tid, row in opt.schedule.items():
        if opt.task_type[tid] == "RealTimeInference":
            continue
        a = opt.attr[tid]
        if not (ws <= opt.arrival[tid] < we):
            continue
        latest_start = min(a["latest"], we) - 1
        if a["earliest"] > latest_start or a["earliest"] + a["duration_h"] > we:
            continue
        window_tasks.append(tid)

    # 背景负荷：x_base 全量负荷减去窗口任务的 x_base 贡献
    bg_gpu = {r: opt.gpu_load[r].copy() for r in REGIONS}
    bg_ai = {r: opt.ai_load[r].copy() for r in REGIONS}
    for tid in window_tasks:
        row = opt.schedule[tid]
        a = opt.attr[tid]
        region = row["TargetRegion"]
        for hour in range(math.floor(row["StartHour"]),
                          min(HOURS_TASK, math.ceil(row["EndHour"]) - 1) + 1):
            ov = max(0.0, min(row["EndHour"], hour + 1.0) - max(row["StartHour"], float(hour)))
            if ov > 0:
                bg_gpu[region][hour] -= a["demand"] * ov
                bg_ai[region][hour] -= a["demand"] * a["unit_power"] * ov
    # 背景快照（启发式会在 bg 上增量放置，精确解必须从纯背景出发）
    bg_gpu0 = {r: bg_gpu[r].copy() for r in REGIONS}
    bg_ai0 = {r: bg_ai[r].copy() for r in REGIONS}

    # 候选 (region, start) 集合（窗口内整数小时）
    candidates = {}
    for tid in window_tasks:
        row = opt.schedule[tid]
        a = opt.attr[tid]
        cand = []
        for r in opt.eligible[tid]:
            lo = max(a["earliest"], ws)
            hi = min(a["latest"], we - 1)
            if lo + a["duration_h"] > we:
                continue
            for s in range(lo, hi + 1):
                if s + a["duration_h"] <= we:
                    cand.append((r, s))
        candidates[tid] = cand

    def capacity_ok(tid: str, r: str, s: float) -> bool:
        a = opt.attr[tid]
        cap = problem.capacity[r]
        end = s + a["duration_h"]
        for hour in range(math.floor(s), min(HOURS_TASK, math.ceil(end) - 1) + 1):
            ov = max(0.0, min(end, hour + 1.0) - max(s, float(hour)))
            if ov <= 0:
                continue
            gpu = bg_gpu[r][hour] + a["demand"] * ov
            ai = bg_ai[r][hour] + a["demand"] * a["unit_power"] * ov
            it = opt.non_ai[r][hour] + ai
            if gpu > cap["Available_GPU"] + TOL or it > cap["Max_IT_Power_MW"] + TOL \
                    or it * cap["PUE"] > cap["Max_Facility_Power_MW"] + TOL:
                return False
        return True

    # ---- 精确模型（CP-SAT） ----
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    var = {}
    for tid in window_tasks:
        for (r, s) in candidates[tid]:
            var[(tid, r, s)] = model.NewBoolVar(f"x_{tid}_{r}_{s}")
    for tid in window_tasks:
        model.AddExactlyOne(var[(tid, r, s)] for (r, s) in candidates[tid])
    # 容量约束（逐区域逐小时；系数按 SCALE 缩放为整数以满足 CP-SAT 要求）
    SCALE = 1000
    for r in REGIONS:
        cap = problem.capacity[r]
        for h in range(ws, we):
            gpu_terms = []
            ai_terms = []
            for tid in window_tasks:
                a = opt.attr[tid]
                for (rr, s) in candidates[tid]:
                    if rr != r:
                        continue
                    end = s + a["duration_h"]
                    ov = max(0.0, min(end, h + 1.0) - max(s, float(h)))
                    if ov > 0:
                        gpu_terms.append((var[(tid, r, s)], int(round(a["demand"] * ov * SCALE))))
                        ai_terms.append((var[(tid, r, s)], int(round(a["demand"] * a["unit_power"] * ov * SCALE))))
            if gpu_terms:
                model.Add(sum(w * v for v, w in gpu_terms)
                          <= int(round((cap["Available_GPU"] - bg_gpu[r][h]) * SCALE)))
            if ai_terms:
                model.Add(sum(w * v for v, w in ai_terms)
                          + int(round(opt.non_ai[r][h] * SCALE))
                          <= int(round(cap["Max_IT_Power_MW"] * SCALE)))
                fac_terms = [(v, int(round(w * cap["PUE"]))) for v, w in ai_terms]
                model.Add(sum(w * v for v, w in fac_terms)
                          + int(round(opt.non_ai[r][h] * cap["PUE"] * SCALE))
                          <= int(round(cap["Max_Facility_Power_MW"] * SCALE)))

    # 目标：最小化标量化信号（按 SCALE 缩放为整数）
    obj_terms = []
    for tid in window_tasks:
        row = opt.schedule[tid]
        src = row["SourceRegion"]
        for (r, s) in candidates[tid]:
            score = opt._score(row, r, float(s), args.lam)
            obj_terms.append((var[(tid, r, s)], int(round(score * SCALE))))
    model.Minimize(sum(w * v for v, w in obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 300
    solver.parameters.num_workers = 8
    t0 = time.time()
    status = solver.Solve(model)
    solve_time = time.time() - t0
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("CP-SAT 未找到可行解，状态:", status)
        return
    exact_obj = solver.ObjectiveValue() / SCALE

    # ---- 启发式（同候选集） ----
    heuristic_obj = 0.0
    placed = 0
    unplaced = []
    for tid in window_tasks:
        row = opt.schedule[tid]
        src = row["SourceRegion"]
        best = None
        for (r, s) in candidates[tid]:
            if not capacity_ok(tid, r, float(s)):
                continue
            score = (opt._score(row, r, float(s), args.lam),
                     opt.lat.get((src, r), math.inf), s)
            if best is None or score < best[0]:
                best = (score, r, s)
        if best is not None:
            heuristic_obj += best[0][0]
            placed += 1
            a = opt.attr[tid]
            cap = problem.capacity[r]
            end = best[2] + a["duration_h"]
            for hour in range(math.floor(best[2]), min(HOURS_TASK, math.ceil(end) - 1) + 1):
                ov = max(0.0, min(end, hour + 1.0) - max(best[2], float(hour)))
                if ov > 0:
                    bg_gpu[best[1]][hour] += a["demand"] * ov
                    bg_ai[best[1]][hour] += a["demand"] * a["unit_power"] * ov
        else:
            unplaced.append(tid)

    # 未放置任务回退到 x_base 排程（保证负荷完整，物理上任务不会消失）
    for tid in unplaced:
        row = opt.schedule[tid]
        a = opt.attr[tid]
        region = row["TargetRegion"]
        for hour in range(math.floor(row["StartHour"]),
                          min(HOURS_TASK, math.ceil(row["EndHour"]) - 1) + 1):
            ov = max(0.0, min(row["EndHour"], hour + 1.0) - max(row["StartHour"], float(hour)))
            if ov > 0:
                bg_gpu[region][hour] += a["demand"] * ov
                bg_ai[region][hour] += a["demand"] * a["unit_power"] * ov

    gap = (heuristic_obj - exact_obj) / abs(exact_obj) if exact_obj != 0 else float("nan")

    # ---- 缺口小时对比（RegionF Hour 2400 是唯一 RE 缺口）与决策一致性 ----
    def placed_loads(assignments: dict) -> dict[str, np.ndarray]:
        g = {r: bg_gpu0[r].copy() for r in REGIONS}
        a_ = {r: bg_ai0[r].copy() for r in REGIONS}
        for tid, (r, s) in assignments.items():
            attr = opt.attr[tid]
            end = s + attr["duration_h"]
            for hour in range(math.floor(s), min(HOURS_TASK, math.ceil(end) - 1) + 1):
                ov = max(0.0, min(end, hour + 1.0) - max(s, float(hour)))
                if ov > 0:
                    g[r][hour] += attr["demand"] * ov
                    a_[r][hour] += attr["demand"] * attr["unit_power"] * ov
        return g, a_

    exact_assign = {}
    for tid in window_tasks:
        for (r, s) in candidates[tid]:
            if solver.Value(var[(tid, r, s)]) == 1:
                exact_assign[tid] = (r, float(s))
                break
    heur_assign = {}
    for tid in window_tasks:
        row = opt.schedule[tid]
        if row["StartHour"] >= ws and row["EndHour"] <= we:
            heur_assign[tid] = (row["TargetRegion"], row["StartHour"])
    agree = sum(1 for tid in window_tasks
                if tid in exact_assign and tid in heur_assign
                and exact_assign[tid] == heur_assign[tid])

    def deficit_mw(loads, ai_loads):
        """RE 缺口合计（设施口径，MW）。"""
        total = 0.0
        for r in REGIONS:
            pue = problem.capacity[r]["PUE"]
            deficit = np.maximum(
                pue * (opt.non_ai[r] + ai_loads[r]) - problem.re_avail(r), 0.0)
            total += float(deficit.sum())
        return total

    def real_cost_cny(ai_loads) -> float:
        """真实购电成本：仅缺口小时购电（绿电覆盖外无需购电）。"""
        cost = 0.0
        for r in REGIONS:
            pue = problem.capacity[r]["PUE"]
            deficit = np.maximum(
                pue * (opt.non_ai[r] + ai_loads[r]) - problem.re_avail(r), 0.0)
            cost += float(np.sum(deficit * problem.price(r)))
        return cost

    g_ex, a_ex = placed_loads(exact_assign)
    g_he, a_he = placed_loads(heur_assign)
    xb_g, xb_a = opt.gpu_load, opt.ai_load  # x_base 全量（含窗口任务）

    out_dir = Path(__file__).resolve().parent / "output" / "q2_gap"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# M10 小样本精确 gap 报告", "",
        f"- 窗口: 小时 [{ws}, {we})；窗口任务数: {len(window_tasks)}；lambda: {args.lam}",
        f"- CP-SAT 状态: {solver.StatusName(status)}；求解时间: {solve_time:.1f}s",
        f"- 精确最优目标: {exact_obj:.2f}；启发式目标: {heuristic_obj:.2f}（放置 {placed}/{len(window_tasks)}）",
        f"- gap: {gap*100:.2f}%（若目标为 0 则为平凡零，说明窗口内无成本相关决策）",
        f"- 决策一致性: {agree}/{len(window_tasks)}（精确与启发式 (区域,启动) 完全一致）",
        f"- RE 缺口总量（设施口径）：x_base={deficit_mw(xb_g, xb_a):.1f} MW，精确={deficit_mw(g_ex, a_ex):.1f} MW，启发式={deficit_mw(g_he, a_he):.1f} MW",
        f"- 真实缺口购电成本：x_base={real_cost_cny(xb_a):,.0f} 元，精确={real_cost_cny(a_ex):,.0f} 元，启发式={real_cost_cny(a_he):,.0f} 元",
        "",
        "> 说明：静态影子成本不随任务拥挤更新，精确模型可能把任务集中到名义富余小时造成真实缺口；",
        "> 最终 KPI 一律以真实能源层（energy_solver）结算，本表仅作解质量参考，不构成全局最优性声明。",
    ]
    (out_dir / "gap_report.md").write_text("\n".join(lines), encoding="utf-8")
    with (out_dir.parent.parent / "solver_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "event": "small_gap", "window": [ws, we], "n_tasks": len(window_tasks),
            "lambda": args.lam, "exact_obj": exact_obj, "heuristic_obj": heuristic_obj,
            "gap": gap, "decision_agreement": agree,
            "deficit_mw": {"x_base": deficit_mw(xb_g, xb_a),
                           "exact": deficit_mw(g_ex, a_ex),
                           "heuristic": deficit_mw(g_he, a_he)},
            "real_cost_cny": {"x_base": real_cost_cny(xb_a),
                              "exact": real_cost_cny(a_ex),
                              "heuristic": real_cost_cny(a_he)},
            "cp_sat_status": solver.StatusName(status),
            "solve_time_s": round(solve_time, 2),
        }, ensure_ascii=False) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
