# Q1 预测模型选择报告

时间切分：训练 0-2351，验证 2352-2375，测试 2376-2399（最后 24 小时实际任务）。

| 指标 | 主模型 | 验证 RMSE |
|---|---|---:|
| TaskCount | LagRF | 1.535 |
| GPU_Demand | LagRF | 54.308 |
| GPU_Hour | LagRF | 218.801 |
| AvgDuration | HW24 | 1.010 |

详细分数见 scores.csv；测试期预测见 predictions_test.csv。

> 注意：预测仅用于评价；最后 24 小时调度使用实际到达任务。