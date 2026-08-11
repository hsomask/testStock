# 检查点 R0：运行闭环纠错基线

日期：2026-08-11
基线提交：`9941fa3`

## 不可变行为

- `analysis/selector.py` 与基线一致。
- 原始选股公式、评分、排序、阈值、最终分层不在纠错范围内。
- 行为等价审计：`gate_status=pass`，最终分层差异为 0。

## 旧入口实测契约

- 日报当前只生成 `unified/daily`，所以每个交易日权威日报应为 1 条。
- 旧邮件函数在 SMTP 配置缺失或发送异常时返回 `None`，外层随后记为成功。
- 旧 K 线函数没有 `required_dates`，近期缓存完整会短路历史目标日修复。
- 旧 DAG 会忽略对账节点失败。
- 旧 DAG 重试成功后仍保留第一次失败的错误信息。
- `daily_report` 没有唯一键和 Upsert。
- `job_run_log.idempotency_key` 没有唯一约束。
- 对账使用数量和 `DISTINCT code`，没有使用 `canonical_signal_lineage`。

## 红灯测试结果

`analysis.runtime_contract_regression_check` 在基线准确捕获 5 项失败：

1. SMTP 缺配置没有明确跳过状态。
2. SMTP 异常没有失败状态。
3. K 线缺少历史必需日期契约。
4. 对账失败未传递到父 DAG。
5. 重试成功残留旧错误。

`analysis.persistence_contract_regression_check` 用于持续约束日报唯一键、Upsert、任务原子幂等和身份级对账。

R0 只建立失败门禁，不修改选股和业务计算。
