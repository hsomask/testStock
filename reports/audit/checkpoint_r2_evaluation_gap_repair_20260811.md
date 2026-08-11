# 检查点 R2：历史 K 线与整日 Evaluation 缺口修复

日期：2026-08-11
对比基线：`9941fa3`

## 根因与修改

- 旧 `get_stock_history` 只检查最新缓存日；近期缓存完整时会跳过历史目标日缺口。
- 新增可选 `required_dates`，仅 Evaluation 覆盖修复调用传入信号日和规范 T+1 日；旧调用者参数和返回尾部语义不变。
- 回补原先只扫描已有 `watchlist_evaluation_summary` 的低覆盖记录，整份缺失的交易日永远不可见。
- 新回补同时扫描近期 `stock_signal`，按持久化交易日历求规范 T+1 日，将“有信号、已成熟、无 Evaluation”加入修复队列。
- 整份缺失按正式评价原有 80% 门槛补跑；已有低覆盖评价仍维持 90% 重跑门槛。
- Evaluation 公式、标签、评分和聚合计算未修改。

## 验证结果

- Python 语法检查：通过。
- `analysis.evaluation_gap_regression_check`：通过，87.5% 整份缺失补跑一次，已有 87.5% 结果保持低权重。
- `analysis.kline_refresh_regression_check`：通过。
- `analysis.evaluation_time_regression_check`：通过，T+1 冻结/T+3 补齐契约保持。
- 全量可独立 Python 回归：通过。
- `analysis.behavior_equivalence_audit --json`：`gate_status=pass`，selector 源码一致，最终分层差异 0。
- 本机没有 Bash；`scripts/evaluation_entrypoint.sh` 的 Linux `bash -n` 及 Docker 实跑列入服务器验收门禁。

## 结论

R2 达标。它补齐数据和漏记流程，不改变旧选股逻辑或 Evaluation 算法。
