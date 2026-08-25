# 最终验收与阻断条件

## 运行前阻断检查

- [x] 用附件基准逐区逐时复现 SOC；`Hour=2406` 是运行区间，主结果运行 `0..2406`、终端为 `SOC_2406`。
- [x] 生成附件复现基准 `x0`：`TargetRegion=SourceRegion`，所有任务 `StartHour=ArrivalHour`；Q1 的弹性基础调度另记为 `x_Q1`，不得混称。
- [x] 比较 `B3_ref` 与 `P_fac(x0)`：最大误差 `3.33e-7 MW`，MAE `2.74e-10 MW`，RMSE `9.20e-9 MW`；负荷口径门禁通过。
- [x] 复现基准容量快检：`x0` 有 44 个 GPU 超限区域-小时，故不得直接作为四格共同基准。
- [x] 生成满足全部硬约束的共同基准 `x_base`（由 Q1 无迁移、允许弹性任务延后的最早可行规则产生）：50,000/50,000 任务已排程，90 个弹性任务延后，唯一指派/实时即开/截止期/本地 SLA 零违约，GPU/IT/设施容量零超限。
- [ ] 求解 M00/M01/M10/M11 并在同一 `x_base` 边界上通过能源守恒、SOC、购售电和 KPI 验收；完成后才允许计算 `S_K`。
- [x] Q2外送边界固定为允许新能源外送但无储能：`RE_avail=RE_direct+RE_sell+Curtailment`、`GridSell=RE_sell`、`RE_sell<=min(MaxGridExport,SellLimit)`；同时 `GridLoad+RE_direct=P_fac`、`GridPurchase=GridLoad`，禁止购电转售。

## 每次求解必须通过

- [ ] 任务唯一指派；实时 `StartHour=ArrivalHour`；`EndHour<=2406`；任务占用不含 `[2406,2407)`。
- [ ] Q1 `TargetRegion=SourceRegion`；Q2/Q4目标区域属于 `EligibleRegions_i`，且单向时延不超过上限。
- [ ] GPU、IT、设施、购电、售电、SOC均不超限；新能源分流、负荷平衡、SOC递推残差在声明容差内。
- [ ] Q2 `Charge=Discharge=GridCharge=RECharge=0` 且 `GridSell=RE_sell`；购售电互斥。
- [ ] Q3不读 Q2 schedule；Q4改变可行任务区域或启动点后，`AI_IT_Load(x)` 至少一个逐时值改变，并与固定 Q2 任务反事实比较。

## 结果可信度

- [ ] 预测只作留出评价，实际最后24小时调度使用实际任务。
- [ ] Q2/Q4近似方案报告运行时间、上下界或小样本精确 gap，不声称全局 Pareto 最优。
- [ ] 附件 `B_ref`、题设 `B3_ref`、可行共同基准 `x_base`、M00/M10/M01/M11 分表呈现；未生成 `x_base` 或未通过一致性检查时禁止报告 `S_K`。
- [ ] 未实际求解优化方案的改善结论仍标记 `EXPECTED`；门禁通过不等于优化结果已计算。
