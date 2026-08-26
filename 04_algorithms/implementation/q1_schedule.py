# -*- coding: utf-8 -*-
"""Q1B 基础可行调度 x_Q1 输出与验证。

口径（DEC-003 / DEC-007）：
  - x_Q1：固定 TargetRegion == SourceRegion、允许非实时任务延后的基础调度；
    与已冻结的可行共同基准 x_base 采用同一规则（截止期优先最早可行放置），
    因此 x_Q1 直接复用 x_base 排程并重新验证，保证论文 Q1 与四格基准口径一致。
  - 验证：唯一指派、实时即开、截止期、本地 SLA、GPU/IT/设施容量零违约、
    任务不占用 Hour 2406。
  - 统计：GPU-hour、各区域利用率、延后任务数、最后 24 小时（2376-2399 到达）任务甘特数据。

输出：output/q1/x_Q1_task_schedule.csv、output/q1/x_Q1_stats.md、output/q1/gantt_last24h.csv。
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import REGIONS, HOURS_ENERGY, Problem
from validator import validate_task_schedule

FROZEN_SHA256 = "4F5046ADCC0C71D9CEAAFC2C1152077185EA2806253D577488F1B282A2B5A245"
OUT_FIELDS = ["TaskID", "SourceRegion", "TargetRegion", "ArrivalHour",
              "StartHour", "EndHour", "NetworkLatency_ms", "GPU_Demand", "TaskType"]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args()

    problem = Problem(args.data_dir)
    x_base_path = Path(args.repo_root) / "02_data" / "processed" / "x_base_task_schedule.csv"

    digest = sha256_of(x_base_path)
    print("x_base SHA-256:", digest)
    print("frozen  SHA-256:", FROZEN_SHA256)
    if digest != FROZEN_SHA256:
        print("警告: x_base 文件哈希与冻结值不一致！")
    x_base = Problem.load_task_schedule(x_base_path)

    violations, nv = validate_task_schedule(problem, x_base, allow_migration=False)
    if nv:
        print("x_base 任务层违约:")
        for v in violations[:20]:
            print(" -", v)
        raise SystemExit(2)
    print("x_base 任务层零违约，可作 x_Q1。")

    out_dir = Path(__file__).resolve().parent / "output" / "q1"
    out_dir.mkdir(parents=True, exist_ok=True)

    x_q1 = x_base[OUT_FIELDS].copy()
    x_q1.to_csv(out_dir / "x_Q1_task_schedule.csv", index=False, encoding="utf-8-sig")

    # 统计
    meta = problem.tasks.set_index("TaskID")
    delayed = int((x_q1["StartHour"] > x_q1["ArrivalHour"]).sum()) if "ArrivalHour" in x_q1 else 0
    gpu_hours = float((x_q1["GPU_Demand"] * (x_q1["EndHour"] - x_q1["StartHour"])).sum())
    util = {}
    for r in REGIONS:
        gpu, ai = problem._loads_from_schedule(x_base)
        peak = float(max(gpu[r]))
        util[r] = peak / problem.capacity[r]["Available_GPU"]

    # 最后 24 小时到达任务甘特数据（2376-2399 实际到达任务）
    last24 = x_q1[(x_q1["ArrivalHour"] >= 2376) & (x_q1["ArrivalHour"] <= 2399)].copy()
    last24.to_csv(out_dir / "gantt_last24h.csv", index=False, encoding="utf-8-sig")

    lines = [
        "# Q1B x_Q1 基础调度报告", "",
        f"- x_base SHA-256: {digest}（冻结值: {FROZEN_SHA256}）",
        f"- 任务总数: {len(x_q1)}；延后任务数: {delayed}",
        f"- 总 GPU-hour: {gpu_hours:,.0f}",
        f"- 任务层违约: {nv}",
        "- 各区域峰值 GPU 利用率: " + ", ".join(f"{r} {util[r]*100:.2f}%" for r in REGIONS),
        f"- 最后 24 小时（2376-2399 到达）任务数: {len(last24)}（甘特数据见 gantt_last24h.csv）",
        "",
        "> x_Q1 与四格共同基准 x_base 同规则同排程，保证论文 Q1 与 M00/M01 口径一致。",
    ]
    (out_dir / "x_Q1_stats.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
