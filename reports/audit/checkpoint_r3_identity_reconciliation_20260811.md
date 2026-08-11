# 检查点 R3：身份级每日对账

日期：2026-08-11
对比基线：`9941fa3`

## 修改范围

- 信号、快照、Evaluation 统一从 `canonical_signal_lineage` 按策略粒度逐条核对。
- K 线覆盖分子和分母统一为策略信号粒度，不再用 distinct code 除以信号行数。
- Evaluation 行存在不再覆盖 K 线低覆盖事实；两者分别报告。
- 日报按规范键基数判断，0=missing、1=success、>1=duplicate。
- 邮件无任何历史账本记录为 unknown；有尝试无成功为 missing；成功记录为 success。
- 已知邮件失败、日报重复、身份缺失都会进入整体失败。

## 生产只读验证

- 最近 10 个交易日查询成功，规范信号数与原始信号数一致，快照身份无缺口。
- 发现 20260730、20260731、20260804、20260805 整份 Evaluation 缺失，证明 R2 缺口回补范围必要。
- 最近日期的日报都是相同 `unified/daily` 键重复：通常 2 条，20260810 为 5 条；并非合法多模式。
- 旧日期没有邮件任务事实，按 unknown 保留；20260810 有成功账本。

## 验证结果

- Python 语法检查：通过。
- `analysis.daily_reconciliation_regression_check`：通过。
- `analysis.persistence_contract_regression_check` 的身份级对账红灯已消除，仅剩 R4 幂等唯一键。
- 对生产数据库验证全程只读，没有写入对账或业务数据。

## 结论

R3 达标。对账从数量近似升级为身份一致性，不修改选股、评分或 Evaluation 计算。
