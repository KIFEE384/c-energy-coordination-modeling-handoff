# 能源层四格验收报告（复审修订版语义）

- 任务层 x_base：零违约（运行前断言通过）
- M00_Q1 违约：0；M00_fair：0；M01-xbase：0；Q3-B3ref：0
- ExportPolicy：M00_Q1=FORBID；M00_fair/M01-xbase/Q3-B3ref=PERMIT_RE_ONLY（与 M10/M11 一致）

| ModelID | ScenarioID | ExportPolicy | Cost_CNY | SellRevenue_CNY | Carbon_tCO2 | RE_Util | Violations |
|---|---|---|---:|---:|---:|---:|---:|
| M00_Q1 | base | FORBID | 8,215 | 0 | 9 | 0.5640 | 0 |
| M00_fair | base | PERMIT_RE_ONLY | 8,215 | 419,808,578 | 9 | 0.6791 | 0 |
| M01-xbase | base | PERMIT_RE_ONLY | 0 | 459,209,647 | 0 | 0.6951 | 0 |
| Q3-B3ref | attachment_fixed_load | PERMIT_RE_ONLY | 0 | 459,212,664 | 0 | 0.6951 | 0 |
| B_ref | attachment_operation | reference_only | 2,231,512,488 | 429,852,350 | 2,045,367 | 0.3106 | 0 |