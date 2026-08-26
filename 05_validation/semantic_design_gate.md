# Semantic Design Gate（本轮复审）

状态：`PASSED WITH CONDITIONS`。

## 已通过

- Q1 固定本地目标区域，`x_base` 作为四格共同任务基准；`x0` 仅作附件负荷复现。
- 第一问无外送基线命名为 `M00_Q1`，四格公平基线命名为 `M00_fair`；二者不得合并。
- Q3 题设固定负荷与四格 `M01-xbase` 分开命名。
- `M00_fair/M10/M01-xbase/M11/Q3-B3ref` 的 `ExportPolicy=PERMIT_RE_ONLY`、附件外送上限和售电价格已冻结；`M00_Q1` 是唯一 `FORBID` 例外且不参与四格归因。
- Q4 明确要求任务变量变动后重算 AI 负荷。
- `S_K` 对最小化 KPI 的方向和最大化新能源利用率的转换已写入模型规范。

## 阻断条件

- 四格必须使用同一新能源外送政策；M00 禁止外送而其他格允许外送时，四格主效应 `BLOCKED`。
- 若只存在 `M00_Q1` 而没有同外送政策的 `M00_fair`，四格改善率和 `S_K` 保持 `BLOCKED`。
- M11 必须提供协调迭代和候选排程 hash；仅固定 Q2 负荷后优化储能时，只能称 staged/linked。
- Q3-B3ref 不得直接充当 M01。
- 结果文件未给出 `ExportPolicy`、外送上限和售电价格来源时，任何四格或 Q3-M01 比较均为 `BLOCKED`。
- 任何数值结论还需通过 result-evidence gate。
