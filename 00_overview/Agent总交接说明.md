# Agent 总交接说明

## 1. 你的任务

这是 C 题“面向算电协同的多目标调度优化研究”的完整 Agent 上下文。你可以负责建模解释、算法实现、验证或论文表达，但不能自行改变冻结事实、变量语义、硬约束、时间边界和 KPI 口径。

## 2. 必读顺序

1. `07_decisions/canonical_fact_ledger.yaml`：冻结事实和决策；
2. `03_models/统一双柔性模型.md`：统一数学模型；
3. `03_models/rationale/model_rationale.md`：题面到模型的理由和比较方法；
4. `04_algorithms/算法实现接口.md`：输入、输出、规模和求解接口；
5. `05_validation/当前状态与验收.md`：当前权威状态和阻断条件；
6. `00_overview/建模手最终交接总结.md`：建模手给算法手和论文手的任务拆分。

历史文件 `05_validation/多Agent复审报告.md` 只用于了解曾经发现的问题；若与当前文件冲突，以 `canonical_fact_ledger.yaml`、`decision_log.md`、统一模型和当前验收文件为准。

## 3. 不可混淆的基准

- `B_ref`：附件完整运行状态，外部比较状态；
- `x0`：来源区域、到达即启动的附件 AI 负荷复现排程；AI 负荷与 `B3_ref` 逐时一致，但有 44 个 GPU 超限；
- `x_Q1`：Q1 无迁移基础调度，弹性任务可延后；
- `x_base`：已验收的可行共同任务边界，四格实验使用；
- `B3_ref`：Q3 题设给定负荷，独立报告；不直接等同于四格 `M01`；
- `M00/M01/M10/M11`：必须在 `x_base` 的统一任务边界和统一能源口径下求解。

## 4. 四问关系

Q1完成需求画像、预测评价和无迁移基础调度；Q2首次开放时延可行迁移/时移，关闭储能；Q3固定附件给定负荷，只优化储能和购售电；Q4用独立任务变量与能源变量联合优化。Q1预测不作为 Q2-Q4 的确定性输入，Q4不得锁死 Q2 任务解。

## 5. 核心公式

`Omega_it(s)=max(0,min(s+d_i,t+1)-max(s,t))`；
`GPU_Load=sum(GPU_i*Omega*x)`；
`AI_IT_Load=sum(GPU_i*PowerMap(type_i)*Omega*x)`；
`FacilityLoad=PUE*(NonAI_IT_Load+AI_IT_Load)`。

能源层：

`RE_avail=RE_direct+RE_charge+RE_sell+Curtailment`；
`GridLoad+RE_direct+Discharge=FacilityLoad`；
`GridPurchase=GridLoad+GridCharge`；
`SOC_t=SOC_(t-1)+eta_c*ChargePower_t-Discharge_t/eta_d`。

## 6. 完成标准

算法 Agent 必须输出 `task_schedule`、`energy_schedule`、`kpi_summary` 和求解日志，并通过任务唯一指派、实时即开、截止期、SLA、GPU/IT/设施、能源守恒、SOC、购售电互斥和终端 SOC 验收。建模/论文 Agent 必须输出模型理由、论文段落、图表计划和 claim register，不得虚构结果。

当前阻断：Q1最终预测和 Q2-Q4数值求解尚未完成；因此 Pareto、改善率和 `S_K` 均不可写成已验证结论。
