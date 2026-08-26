# -*- coding: utf-8 -*-
"""四格汇总、S_K、run_manifest 与 witness 生成（复审修订版语义 §6/§8）。

S_K 口径（03_models/统一双柔性模型_复审修订版.md §6）：
  - 最小化 KPI：S_K = K10 + K01 - K11 - K00（以 M00_fair 为基准）；
    S_K=0 联合等于两项单独之和；S_K>0 联合优于加和（互补）；S_K<0 替代/重叠。
  - 新能源利用率（最大化）：S_RU = RU11 - RU10 - RU01 + RU00。
  - 四个 K 来自匹配的推荐点（M10 λ=100，M11 base）。

run_manifest.csv：ModelID, ScenarioID, ExportPolicy, ExportCapSource, SellPriceSource,
  TaskScheduleHash, FacilityLoadHash, EnergyScheduleHash, CodeRevision, TimeRange, CreatedAt
witness_extremes.csv：零购电/零碳排/高售电收入/RE 缺口的区域-小时证据。

用法：python run_summary.py --data-dir <附件数据目录> --repo-root <repo根目录>
"""
from __future__ import annotations

import argparse
import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import Problem, load_x_base
from evidence import (build_witness_rows, code_revision, facility_load_hash,
                      sha256_file)

MINIMIZE_KPIS = ["Cost_CNY", "Carbon_tCO2", "PeakGridPurchase_MW", "GridPurchaseStd_MW"]
MAXIMIZE_KPIS = ["RenewableUtilization"]
TIME_RANGE = "0..2406"
EXPORT_SOURCE = "region_time_data.xlsx"
CREATED_AT = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
MANIFEST_MODELS = [
    ("M00_Q1", "base", "FORBID", "not_applicable", "not_applicable"),
    ("M00_fair", "base", "PERMIT_RE_ONLY", EXPORT_SOURCE, EXPORT_SOURCE),
    ("M10", "lam100", "PERMIT_RE_ONLY", EXPORT_SOURCE, EXPORT_SOURCE),
    ("M01-xbase", "base", "PERMIT_RE_ONLY", EXPORT_SOURCE, EXPORT_SOURCE),
    ("M11", "base", "PERMIT_RE_ONLY", EXPORT_SOURCE, EXPORT_SOURCE),
    ("Q3-B3ref", "attachment_fixed_load", "PERMIT_RE_ONLY", EXPORT_SOURCE, EXPORT_SOURCE),
]
DIR_MAP = {"M00_Q1": "M00_Q1", "M00_fair": "M00_fair", "M10": "M10/lam100",
           "M01-xbase": "M01-xbase", "M11": "M11/base", "Q3-B3ref": "Q3_B3ref"}


def synergy_value(k00, k10, k01, k11, maximize: bool) -> float:
    if maximize:
        return k11 - k10 - k01 + k00
    return k10 + k01 - k11 - k00


def improvement(baseline: float, value: float, maximize: bool) -> float:
    if maximize:
        return value - baseline
    return (baseline - value) / baseline if baseline != 0 else float("nan")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args()

    problem = Problem(args.data_dir)
    x_base = load_x_base(args.repo_root)
    out_root = Path(__file__).resolve().parent / "output"
    kpi = pd.read_csv(out_root / "kpi_summary.csv")
    sum_dir = out_root / "summary"
    sum_dir.mkdir(parents=True, exist_ok=True)

    def cell(model: str, scenario: str) -> pd.Series:
        row = kpi[(kpi["ModelID"] == model) & (kpi["ScenarioID"] == scenario)]
        assert len(row) == 1, f"{model}/{scenario} 应恰一行，实际 {len(row)}"
        return row.iloc[0]

    k00 = cell("M00_fair", "base")     # 四格公平基线（有外送）
    k01 = cell("M01-xbase", "base")
    k10 = cell("M10", "lam100")
    k11 = cell("M11", "base")
    kq1 = cell("M00_Q1", "base")       # Q1 解释性基线（无外送，仅对照）
    bref = cell("B_ref", "attachment_operation")

    cols = ["Cost_CNY", "Carbon_tCO2", "RenewableUtilization",
            "PeakGridPurchase_MW", "GridPurchaseStd_MW", "MeanLatency_ms", "P95Latency_ms"]
    lines = ["# 四格 KPI 汇总与 S_K（复审修订版语义）", "",
             "> 四格基准为 M00_fair（ExportPolicy=PERMIT_RE_ONLY）；M10 取推荐场景 λ=100。",
             "> M00_Q1（无外送）仅作 Q1 解释性对照，不参与四格归因；B_ref 为附件运行参照。",
             "> 成本为购电成本（毛口径）；净成本与售电收入见 kpi_summary 扩展列。", "",
             "| 指标 | B_ref | M00_Q1 | M00_fair | M01-xbase | M10 | M11 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for c in cols:
        vals = [bref[c], kq1[c], k00[c], k01[c], k10[c], k11[c]]
        fmt = "{:,.2f}" if c in ("MeanLatency_ms", "P95Latency_ms") else "{:,.0f}"
        if c == "RenewableUtilization":
            fmt = "{:.4f}"
        lines.append(f"| {c} | " + " | ".join(fmt.format(v) for v in vals) + " |")

    lines += ["", "### 改善率（相对 M00_fair）与 S_K/S_RU", "",
              "| 指标 | M01-xbase | M10 | M11 | S_K/S_RU |",
              "|---|---:|---:|---:|---:|"]
    sk_rows = []
    for c in cols:
        if c not in MINIMIZE_KPIS + MAXIMIZE_KPIS:
            continue
        mx = c in MAXIMIZE_KPIS
        i01 = improvement(k00[c], k01[c], mx)
        i10 = improvement(k00[c], k10[c], mx)
        i11 = improvement(k00[c], k11[c], mx)
        sk = synergy_value(k00[c], k10[c], k01[c], k11[c], mx)
        sk_rows.append({"KPI": c, "S_K_or_S_RU": sk})
        if mx:
            lines.append(f"| {c}(+) | {i01:+.4f} | {i10:+.4f} | {i11:+.4f} | S_RU={sk:+.4f} |")
        else:
            pct = lambda v: f"{v*100:+.1f}%" if v == v else "nan"
            lines.append(f"| {c}(-) | {pct(i01)} | {pct(i10)} | {pct(i11)} | S_K={sk:+.0f} |")

    lines += ["", "### 相对附件 B_ref 的改善率", "",
              "| 指标 | M00_fair | M01-xbase | M10 | M11 |",
              "|---|---:|---:|---:|---:|"]
    for c in cols:
        if c not in MINIMIZE_KPIS + MAXIMIZE_KPIS:
            continue
        mx = c in MAXIMIZE_KPIS
        vals = [improvement(bref[c], m[c], mx) for m in [k00, k01, k10, k11]]
        if mx:
            lines.append(f"| {c}(+) | " + " | ".join(f"{v:+.4f}" for v in vals) + " |")
        else:
            lines.append(f"| {c}(-) | " + " | ".join(f"{v*100:+.1f}%" for v in vals) + " |")

    lines += ["", "> 诚实标记：M10 为缺口修复启发式、M11 为分解式联合启发式（外层候选+内层精确 MILP），",
              "> 均不声称全局最优；S_K/S_RU 基于推荐点（M10 λ=100，M11 base）计算；",
              "> 小样本同输入 gap 见 04_algorithms/results/q2_gap/gap_report.md；",
              "> B_ref 为附件官方运行状态参照，不是本队优化结果。"]
    report = "\n".join(lines)
    (sum_dir / "four_cell_summary.md").write_text(report, encoding="utf-8")
    print(report)
    pd.DataFrame(sk_rows).to_csv(sum_dir / "S_K_table.csv", index=False, encoding="utf-8-sig")

    # ---- run_manifest.csv ----
    manifest = []
    for model, scenario, policy, cap_src, price_src in MANIFEST_MODELS:
        d = out_root / DIR_MAP[model]
        task_path = d / "task_schedule.csv"
        energy_path = d / "energy_schedule.csv"
        task_hash = sha256_file(task_path) if task_path.exists() else "not_applicable"
        if model in ("M00_Q1", "M00_fair", "M01-xbase"):
            fac_hash = facility_load_hash(problem, x_base)
        elif model == "Q3-B3ref":
            # 题设固定负荷：设施负荷 = PUE*(Baseline_AI+NonAI)，无任务排程
            arr = np.concatenate([np.round(problem.baseline_facility_load(r), 6)
                                  for r in problem.REGIONS])
            import hashlib
            fac_hash = hashlib.sha256(arr.tobytes()).hexdigest().upper()
        else:
            fac_hash = facility_load_hash(problem, Problem.load_task_schedule(task_path))
        energy_hash = sha256_file(energy_path) if energy_path.exists() else "n/a"
        manifest.append({
            "ModelID": model, "ScenarioID": scenario, "ExportPolicy": policy,
            "ExportCapSource": cap_src, "SellPriceSource": price_src,
            "TaskScheduleHash": task_hash, "FacilityLoadHash": fac_hash,
            "EnergyScheduleHash": energy_hash, "CodeRevision": code_revision(),
            "TimeRange": TIME_RANGE, "CreatedAt": CREATED_AT,
        })
    pd.DataFrame(manifest).to_csv(sum_dir / "run_manifest.csv", index=False, encoding="utf-8-sig")

    # ---- witness_extremes.csv ----
    witness_rows = []
    for model, dirn in DIR_MAP.items():
        ep = out_root / dirn / "energy_schedule.csv"
        if ep.exists():
            energy = pd.read_csv(ep)
            for w in build_witness_rows(problem, energy):
                witness_rows.append({"ModelID": model, **w})
    pd.DataFrame(witness_rows).to_csv(sum_dir / "witness_extremes.csv",
                                      index=False, encoding="utf-8-sig")
    print(f"\nrun_manifest 与 witness_extremes 已写出到 {sum_dir}")


if __name__ == "__main__":
    main()
