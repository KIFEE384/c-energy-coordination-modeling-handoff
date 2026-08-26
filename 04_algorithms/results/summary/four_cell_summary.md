# 四格 KPI 汇总与 S_K（复审修订版语义）

> 四格基准为 M00_fair（ExportPolicy=PERMIT_RE_ONLY）；M10 取推荐场景 λ=100。
> M00_Q1（无外送）仅作 Q1 解释性对照，不参与四格归因；B_ref 为附件运行参照。
> 成本为购电成本（毛口径）；净成本与售电收入见 kpi_summary 扩展列。

| 指标 | B_ref | M00_Q1 | M00_fair | M01-xbase | M10 | M11 |
|---|---:|---:|---:|---:|---:|---:|
| Cost_CNY | 2,231,512,488 | 8,215 | 8,215 | 0 | 0 | 0 |
| Carbon_tCO2 | 2,045,367 | 9 | 9 | 0 | 0 | 0 |
| RenewableUtilization | 0.3106 | 0.5640 | 0.6791 | 0.6951 | 0.6792 | 0.6951 |
| PeakGridPurchase_MW | 497 | 32 | 32 | 0 | 0 | 0 |
| GridPurchaseStd_MW | 139 | 0 | 0 | 0 | 0 | 0 |
| MeanLatency_ms | nan | 5.00 | 5.00 | 5.00 | 5.00 | 5.00 |
| P95Latency_ms | nan | 5.00 | 5.00 | 5.00 | 5.00 | 5.00 |

### 改善率（相对 M00_fair）与 S_K/S_RU

| 指标 | M01-xbase | M10 | M11 | S_K/S_RU |
|---|---:|---:|---:|---:|
| Cost_CNY(-) | +100.0% | +100.0% | +100.0% | S_K=-8215 |
| Carbon_tCO2(-) | +100.0% | +100.0% | +100.0% | S_K=-9 |
| RenewableUtilization(+) | +0.0160 | +0.0000 | +0.0160 | S_RU=-0.0000 |
| PeakGridPurchase_MW(-) | +100.0% | +100.0% | +100.0% | S_K=-32 |
| GridPurchaseStd_MW(-) | +100.0% | +100.0% | +100.0% | S_K=-0 |

### 相对附件 B_ref 的改善率

| 指标 | M00_fair | M01-xbase | M10 | M11 |
|---|---:|---:|---:|---:|
| Cost_CNY(-) | +100.0% | +100.0% | +100.0% | +100.0% |
| Carbon_tCO2(-) | +100.0% | +100.0% | +100.0% | +100.0% |
| RenewableUtilization(+) | +0.3685 | +0.3845 | +0.3685 | +0.3845 |
| PeakGridPurchase_MW(-) | +93.6% | +100.0% | +100.0% | +100.0% |
| GridPurchaseStd_MW(-) | +99.8% | +100.0% | +100.0% | +100.0% |

> 诚实标记：M10 为缺口修复启发式、M11 为分解式联合启发式（外层候选+内层精确 MILP），
> 均不声称全局最优；S_K/S_RU 基于推荐点（M10 λ=100，M11 base）计算；
> 小样本同输入 gap 见 04_algorithms/results/q2_gap/gap_report.md；
> B_ref 为附件官方运行状态参照，不是本队优化结果。