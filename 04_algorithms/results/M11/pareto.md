# M11（Q4）分解式联合优化（复审修订版语义）

> 外层候选 2 个（缺口修复轮数×碳价权重，排程哈希去重），内层能源精确 MILP。
> 选定候选：**lam100_repair0**（规则：min 净成本，平局按时延/迁移数）。
> 诚实标记：分解式联合启发式，不声称全局最优；任务解独立于 Q2 生成，不锁死。

| Candidate | Migrated | MeanLat_ms | InnerNetCost_CNY | InnerGrossCost_CNY | TaskViol | EnergyViol |
|---|---:|---:|---:|---:|---:|---:|
| lam100_repair0 | 0 | 5.00 | -459,209,647 | 0 | 0 | 0 |
| lam100_repair1 | 1 | 5.00 | -459,205,351 | 0 | 0 | 0 |

迭代记录：coordination_log.jsonl（候选排程/设施/能源哈希、内层目标、停止准则）。