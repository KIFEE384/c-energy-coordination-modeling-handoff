# `x_base` 可行共同基准验收

生成脚本：`04_algorithms/build_feasible_baseline.py`

输出：`02_data/processed/x_base_task_schedule.csv`

## 结果

| 检查项 | 结果 |
|---|---:|
| 任务总数 | 50,000 |
| 已排程任务 | 50,000 |
| 未排程任务 | 0 |
| 弹性任务延后数 | 90 |
| 任务唯一指派违约 | 0 |
| 实时任务非到达即开违约 | 0 |
| 截止期违约 | 0 |
| 任务占用 Hour 2406 | 0 |
| 本地网络 SLA 违约 | 0 |
| GPU/IT/设施容量违约 | 0 |
| 最大 GPU 利用率 | 99.9931%（RegionF, Hour 2316） |
| 最大 IT 利用率 | 97.6970%（RegionA, Hour 2401） |
| 最大设施功率利用率 | 97.6970%（RegionA, Hour 2401） |

`x_base` 是四格实验的共同任务边界。它不是附件 `B_ref`，也不是附件负荷复现基准 `x0`；`x0` 只用于证明 `B3_ref` 的负荷口径。Q3 的 `B3_ref` 继续单独报告，直到算法手用 `x_base` 重新生成四格中的 `M01`。

SHA-256：`4F5046ADCC0C71D9CEAAFC2C1152077185EA2806253D577488F1B282A2B5A245`
