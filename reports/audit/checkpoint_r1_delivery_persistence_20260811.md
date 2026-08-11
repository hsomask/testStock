# 检查点 R1：邮件真实性与日报幂等

日期：2026-08-11
对比基线：`9941fa3`

## 修改范围

- 邮件正文、附件选择、主题和交易日判断保持旧逻辑不变。
- SMTP 成功明确返回 `success`；配置缺失返回 `skipped_config_missing`；收件人为空返回 `skipped_recipient_missing`；发送异常返回 `failed`。
- 任务账本不再把上述失败或缺配置误记为成功，命令行在不可投递时返回非零退出码。
- 日报仍按旧字段写入相同内容和置信度，但同一 `(trade_date, report_mode, report_type)` 重渲染改为 Upsert。
- 初始化脚本规范化旧空键、保留每个规范键最新一条并建立唯一索引。

## 与旧代码的行为差异

- 保留：报告生成、报告模式、报告正文、附件、选股、评分、排序和 Evaluation 公式。
- 修正：旧代码把 SMTP 异常/缺配置继续记为成功；新代码如实记账并向 DAG 暴露失败。
- 修正：旧代码每次重渲染都追加日报；新代码覆盖同一规范日报，历史不同日期/模式不受影响。

## 验证结果

- `compileall`：通过。
- `analysis.r1_delivery_persistence_regression_check`：通过，覆盖缺配置、SMTP 异常、SMTP 成功和重复重渲染。
- 除跨阶段红灯测试外的回归检查：通过；旧 `20260724` 报告文件因仍包含已废弃的产业概念统计，不作为当前金样本。
- `analysis.behavior_equivalence_audit --json`：`gate_status=pass`，selector 源码一致，最终分层差异 0。
- `analysis.persistence_contract_regression_check` 中日报唯一键和 Upsert 红灯已经消除；剩余项属于 R3/R4。

## 结论

R1 达标。修改只收敛投递状态与日报存储语义，没有改动原有选股和报告业务计算。
