# 两项门禁复现审计

审计脚本：`work/audit_two_gates.py`。原始附件未修改。

## Gate 1：2406 的能源/SOC索引

**结论：通过，采用运行小时 `t=0,...,2406`。**

证据如下：

- `storage_information.xlsx` 的 `SOC_State_Convention` 明确为“`SOC_MWh is end-of-hour; InitialSOC_MWh is before Hour 0`”。因此令 `SOC_-1=InitialSOC`，`SOC_t` 为 Hour `t` 动作后的时段末状态。
- `region_time_data.xlsx` 有 `Closure_2400_2406` 的 42 条记录；Hour 2406 仍提供六区域的非AI负荷、可用新能源、购售电和 SOC。例如 RegionD/E/F 在 Hour 2406 分别仍外送 180/220/220 MW，故它不是只含 SOC 的空状态点。
- 以给定充放电功率和效率复现 14,442 个区域小时的 SOC：最大绝对残差 0.999944 MWh、MAE 0.0000843 MWh、RMSE 0.008321 MWh。唯一显著异常为 RegionE、Hour 0（-0.999944 MWh），属于源表首小时 SOC 残差；不静默修正，并在实现日志中单列数据质量标记。
- 同时复现 `Total_Load-IT_Load*PUE` 最大绝对残差为 0.00005 MW，新能源分流最大残差为 0.0002 MW，均为原表保留精度误差。

**冻结口径：**任务占用为 `[0,2406)`；能源动作 `t=0,...,2406`；`SOC_-1=InitialSOC`，`SOC_t` 为 Hour `t` 末状态，终端约束为 `SOC_2406>=InitialSOC`；成本、碳排和新能源利用率均包含 Hour 2406。

## Gate 2：Q3负荷与共同基准 x0

**结论：通过。**

共同基准 `x0` 定义为：每项任务固定在来源区域、开始于 `ArrivalHour`，用任务分钟级实际重叠和 `power_mapping.xlsx` 汇总 AI IT 功率。与附件 `Baseline_AI_IT_Load_MW` 的 14,442 个区域-小时比较结果为：

| 指标 | 数值 |
|---|---:|
| 最大绝对误差 | `3.3333448e-7 MW` |
| MAE | `2.7395816e-10 MW` |
| RMSE | `9.1994657e-9 MW` |
| 误差大于 `1e-6 MW` 的区域小时数 | 0 |

这说明 `Baseline_AI_IT_Load_MW` 精确对应到达即启动复现基准 `x0`，差异完全来自源表六位小数显示。该结论只证明负荷口径一致，不证明 `x0` 满足算力硬约束。容量快检发现 `x0` 有 44 个区域-小时 GPU 超限，最大为 RegionF Hour 229：`1309.733/966=135.58%`。因此 Q3 的 `B3_ref` 不能直接作为四格 `M01`；必须先用 Q1 生成满足全部硬约束的 `x_base`，再计算四格和 `S_K`。

## 实现处理

- SOC 递推的常规数值容差取 `1e-4 MWh`；RegionE Hour 0 的已知源表异常单独列为外源数据质量残差，不由优化变量补偿或修改。
- 计算基准复现 KPI 时，使用题表给定的 `SOC_MWh` 作为参考；求解器生成方案则严格执行正式 SOC 递推和终端约束。

## Gate 3：可行共同任务基准 `x_base`

**结论：通过。** 使用 `04_algorithms/build_feasible_baseline.py`，固定目标区域为来源区域；实时任务在到达时启动，批量/训练任务按截止期优先寻找最早可行启动时刻。结果为 50,000/50,000 任务排程，90 个弹性任务延后，所有任务唯一指派且不占用 2406；截止期、本地 SLA、GPU、IT 和设施功率约束均零违反。最大 GPU 利用率为 RegionF Hour 2316 的 99.9931%，最大 IT 利用率为 RegionA Hour 2401 的 97.6970%。输出文件为 `02_data/processed/x_base_task_schedule.csv`，SHA-256 为 `4F5046ADCC0C71D9CEAAFC2C1152077185EA2806253D577488F1B282A2B5A245`。

该门禁只放行共同任务边界，不等同于 M00/M01/M10/M11 已求解；四格 KPI 与 `S_K` 仍须等待算法手完成能源和联合优化。
