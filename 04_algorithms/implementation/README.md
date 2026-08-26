# 算法模块（work/algorithm）

C 题“面向算电协同的多目标调度优化研究”的算法实现与全部数值结果。
所有代码遵循 `04_algorithms/算法实现接口.md` 的输出契约与验收断言；
口径与决策见 `07_decisions/decision_log.md`（尤其 DEC-008）。

## 模块文件

| 文件 | 职责 |
|---|---|
| `data_loader.py` | 统一加载六张附件 Excel；任务/容量/时延/电价/新能源/储能结构与派生计算 |
| `energy_solver.py` | 能源层求解：M00/M10 闭式解，M01/M11 能源层 HiGHS MILP（储能+外送，充放电与购售电互斥） |
| `kpi.py` | KPI 计算（成本=购电毛成本；碳排；新能源利用率；时延；峰值/标准差购电） |
| `validator.py` | 任务层与能源层全部验收断言（唯一指派/即开/截止期/时延/容量/守恒/SOC/互斥/终端） |
| `task_optimizer.py` | M10/M11 任务层：静态影子成本 + 贪心指派 + 局部搜索（加权标量化近似 Pareto） |
| `run_energy_cells.py` | 能源四格运行：M00 / M01（主+min-carbon）/ Q3(B3_ref) + B_ref 参照 |
| `run_q2_m10.py` | Q2/M10：多 lambda 任务优化 + M10 能源层 + 近似非支配表 |
| `run_q4_m11.py` | Q4/M11：任务重新优化（不锁死 Q2）+ 含储能能源层 |
| `run_summary.py` | 四格 KPI 汇总、改善率、S_K 计算 |
| `small_sample_gap.py` | M10 小样本精确 gap（CP-SAT 48 小时窗口） |
| `q1_prediction.py` | Q1A 需求画像与预测（SNaive24/168、HW24、滞后特征 RF；训练/验证/测试切分） |
| `q1_schedule.py` | Q1B x_Q1 基础调度输出与验证（与 x_base 同规则） |

## 结果输出（output/）

- `kpi_summary.csv`：全部模型/场景的统一 KPI 表（契约列 + 扩展列 SellRevenue_CNY/NetCost_CNY）
- `solver_log.jsonl`：逐区域/逐场景求解日志（含残差、RegionE Hour0 数据质量标记）
- `M00/ M01/ M01_mincarbon/ Q3_B3ref/`：energy_schedule.csv
- `M10/<scenario>/ M11/<scenario>/`：task_schedule.csv + energy_schedule.csv
- `q1/`：series.csv、predictions_test.csv、model_selection.md、x_Q1_task_schedule.csv、gantt_last24h.csv
- `summary/four_cell_summary.md`、`summary/S_K_table.csv`
- `q2_gap/gap_report.md`

## 关键结果速览（推荐场景 M10/M11 λ=100）

| 指标 | B_ref | M00 | M01 | M10 | M11 |
|---|---:|---:|---:|---:|---:|
| 购电成本 CNY | 2,231,512,488 | 8,215 | 0 | 0 | 0 |
| 碳排 tCO2 | 2,045,367 | 9 | 0 | 0 | 0 |
| 新能源利用率 | 31.06% | 56.40% | 69.51% | 67.92% | 69.51% |
| 峰值购电 MW | 497 | 32 | 0 | 0 | 0 |

- 数据特性：各区新能源可用量（均值约 800 MW）远大于设施负荷（约 450 MW），
  仅 RegionF Hour 2400 存在唯一 RE 缺口（31.6 MW，即 M00 全部成本来源）。
- M01（储能）与 M10（任务迁移 1 个训练任务）都能独立消除该缺口 → 成本/碳排归零，
  S_K>0 说明两种柔性互为替代（联合收益不叠加）。
- M11 联合最优：储能覆盖缺口，任务保持本地最优（时延 5ms），与 M10 的迁移解
  形成真实差异（AI 负荷逐时差异见 solver_log）。
- 全部结果通过任务层与能源层验收断言（0 违约）；M10/M11 为近似解，诚实标记非全局最优。

## 复现命令

```bash
python run_energy_cells.py --data-dir <附件数据目录> --repo-root <repo根目录>
python q1_prediction.py   --data-dir <附件数据目录> --repo-root <repo根目录>
python q1_schedule.py     --data-dir <附件数据目录> --repo-root <repo根目录>
python run_q2_m10.py      --data-dir <附件数据目录> --repo-root <repo根目录>
python run_q4_m11.py      --data-dir <附件数据目录> --repo-root <repo根目录>
python small_sample_gap.py --data-dir <附件数据目录> --repo-root <repo根目录> --lambda 100
python run_summary.py     --repo-root <repo根目录>
```

依赖：pandas、numpy、scipy(HiGHS milp)、ortools(CP-SAT)、statsmodels、scikit-learn。
