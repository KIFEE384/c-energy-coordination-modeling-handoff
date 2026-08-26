# -*- coding: utf-8 -*-
"""四格汇总、改善率与 S_K 计算（算法手最终交付的一部分）。

口径：
  - 改善率（论文口径，06_paper/数据洞察与作图清单.md）：
      成本/碳排/峰值购电/购电标准差 = (Baseline - Optimized)/Baseline；
      新能源利用率 = Optimized - Baseline；
  - S_K = (任务柔性增益) + (储能增益) - (联合增益)，其中增益为相对 M00 的改善：
      越小越好指标（成本/碳排）增益 = M00 - cell；越大越好指标（新能源利用率）增益 = cell - M00；
      S_K = Delta10 + Delta01 - Delta11；S_K > 0 表示联合优于单效应之和（超可加）。
  - 主对照场景：M10/M11 取 lambda=100（平衡碳价）作为推荐；另附 lambda=0（最低成本）。

输出：output/summary/four_cell_summary.md、S_K 表、kpi_summary 最终版。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

LOWER_BETTER = ["Cost_CNY", "Carbon_tCO2", "PeakGridPurchase_MW", "GridPurchaseStd_MW"]
HIGHER_BETTER = ["RenewableUtilization"]
RECOMMENDED_LAM = 100.0


def improvement(baseline: float, value: float, higher_better: bool) -> float:
    if higher_better:
        return value - baseline
    return (baseline - value) / baseline if baseline != 0 else float("nan")


def synergy(k00, k10, k01, k11, higher_better: bool) -> float:
    """S_K：两单效应增益之和 - 联合增益。"""
    d10 = improvement(k00, k10, higher_better)
    d01 = improvement(k00, k01, higher_better)
    d11 = improvement(k00, k11, higher_better)
    return d10 + d01 - d11


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args()

    out_root = Path(__file__).resolve().parent / "output"
    kpi = pd.read_csv(out_root / "kpi_summary.csv")
    sum_dir = out_root / "summary"
    sum_dir.mkdir(parents=True, exist_ok=True)

    def cell(model: str, scenario: str) -> pd.Series:
        row = kpi[(kpi["ModelID"] == model) & (kpi["ScenarioID"] == scenario)]
        assert len(row) == 1, f"{model}/{scenario} 应恰一行，实际 {len(row)}"
        return row.iloc[0]

    k00 = cell("M00", "base")
    k01 = cell("M01", "base")
    m10_rec = f"lam{int(RECOMMENDED_LAM)}"
    m11_rec = f"lam{int(RECOMMENDED_LAM)}"
    k10 = cell("M10", m10_rec)
    k11 = cell("M11", m11_rec)
    bref = cell("B_ref", "attachment_operation")

    # 四格表
    cols = ["Cost_CNY", "Carbon_tCO2", "RenewableUtilization",
            "PeakGridPurchase_MW", "GridPurchaseStd_MW", "MeanLatency_ms", "P95Latency_ms"]
    lines = ["# 四格 KPI 汇总与 S_K（算法手交付）", "",
             f"> 推荐对照场景 M10/M11 取 lambda={int(RECOMMENDED_LAM)}（平衡碳价）。",
             f"> 成本为购电成本（毛口径）；净成本与售电收入见 kpi_summary 扩展列。", "",
             "| 指标 | B_ref | M00 | M01(储能) | M10(任务) | M11(联合) |",
             "|---|---:|---:|---:|---:|---:|"]
    for c in cols:
        vals = [bref[c], k00[c], k01[c], k10[c], k11[c]]
        fmt = "{:,.2f}" if c in ("MeanLatency_ms", "P95Latency_ms") else "{:,.0f}"
        if c == "RenewableUtilization":
            fmt = "{:.4f}"
        lines.append(f"| {c} | " + " | ".join(fmt.format(v) for v in vals) + " |")

    # 相对 B_ref 与相对 M00 的改善率
    lines += ["", "### 改善率（相对 M00，即四格消融基准）", "",
              "| 指标 | M01 vs M00 | M10 vs M00 | M11 vs M00 | S_K |",
              "|---|---:|---:|---:|---:|"]
    for c in cols:
        if c not in LOWER_BETTER + HIGHER_BETTER:
            continue
        hb = c in HIGHER_BETTER
        i01 = improvement(k00[c], k01[c], hb)
        i10 = improvement(k00[c], k10[c], hb)
        i11 = improvement(k00[c], k11[c], hb)
        sk = synergy(k00[c], k10[c], k01[c], k11[c], hb)
        if hb:
            lines.append(f"| {c}(+) | {i01:+.4f} | {i10:+.4f} | {i11:+.4f} | {sk:+.4f} |")
        else:
            pct = lambda v: f"{v*100:+.1f}%" if v == v else "nan"
            lines.append(f"| {c}(-) | {pct(i01)} | {pct(i10)} | {pct(i11)} | S_K={sk:+.0f} |")

    lines += ["", "### 相对附件 B_ref 的改善率", "",
              "| 指标 | M00 | M01 | M10 | M11 |",
              "|---|---:|---:|---:|---:|"]
    for c in cols:
        if c not in LOWER_BETTER + HIGHER_BETTER:
            continue
        hb = c in HIGHER_BETTER
        vals = [improvement(bref[c], cell(m, s)[c], hb)
                for m, s in [("M00", "base"), ("M01", "base"), ("M10", m10_rec), ("M11", m11_rec)]]
        if hb:
            lines.append(f"| {c}(+) | " + " | ".join(f"{v:+.4f}" for v in vals) + " |")
        else:
            lines.append(f"| {c}(-) | " + " | ".join(f"{v*100:+.1f}%" for v in vals) + " |")

    lines += ["", "> 诚实标记：M10/M11 为加权标量化启发式近似解（贪心+局部搜索），非全局最优；",
              "> S_K 基于推荐场景 lambda=100 计算；小样本 gap 见 output/q2_gap/gap_report.md。",
              "> B_ref 为附件官方运行状态参照，不是本队优化结果。"]
    report = "\n".join(lines)
    (sum_dir / "four_cell_summary.md").write_text(report, encoding="utf-8")
    print(report)

    # S_K 表（多个 lambda 视角）
    sk_rows = []
    for lam in [0.0, 100.0, 200.0, 400.0, 800.0, 1600.0]:
        s = f"lam{int(lam)}"
        try:
            k10v = cell("M10", s)
            k11v = cell("M11", s)
        except AssertionError:
            continue
        sk_rows.append({
            "Scenario": s,
            "S_K_Cost_CNY": synergy(k00["Cost_CNY"], k10v["Cost_CNY"], k01["Cost_CNY"], k11v["Cost_CNY"], False),
            "S_K_Carbon_tCO2": synergy(k00["Carbon_tCO2"], k10v["Carbon_tCO2"], k01["Carbon_tCO2"], k11v["Carbon_tCO2"], False),
            "S_K_RE_Util": synergy(k00["RenewableUtilization"], k10v["RenewableUtilization"], k01["RenewableUtilization"], k11v["RenewableUtilization"], True),
        })
    sk_df = pd.DataFrame(sk_rows)
    sk_df.to_csv(sum_dir / "S_K_table.csv", index=False, encoding="utf-8-sig")
    print("\nS_K 表（多 lambda 视角）已写出:", sum_dir / "S_K_table.csv")


if __name__ == "__main__":
    main()
