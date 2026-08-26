# Result Evidence Gate（本轮复审）

状态：`BLOCKED PENDING REPRODUCIBLE OUTPUTS`。

当前工作区未包含算法分支的完整 KPI、逐时能源表、运行清单和 Q4 协调日志；因此不能在本地独立重算远程摘要中的数值。

## 必须补齐

- 四格同一场景、同一时间范围、同一外送政策的 `energy_schedule.csv`；
- `run_manifest.csv` 中 `M00_fair/M10/M01-xbase/M11/Q3-B3ref` 的相同 `ExportPolicy=PERMIT_RE_ONLY`、`ExportCapSource` 与 `SellPriceSource`，以及唯一 Q1-only 的 `M00_Q1/ExportPolicy=FORBID`；
- `M00_Q1` 与 `M00_fair` 分开的模型 ID、能源排程和用途说明；
- 每个 KPI 的任务/负荷/能源文件 hash；
- 成本、碳排、新能源分流、SOC、互斥和功率平衡的重算证书；
- Pareto 目标向量去重报告；
- Q2 gap 与最终 M10 的同输入差异对账；
- 零购电、零碳排和高售电收入的区域—小时 witness 表；
- Q4 外层任务—内层能源协调迭代记录。
- `M00_Q1` 到 `M00_fair` 的外送规则差异和重新结算记录；

在门禁解除前，所有改善率、`S_K`、Pareto 和联合最优性主张均为 `BLOCKED`。
