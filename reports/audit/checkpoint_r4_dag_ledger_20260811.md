# 检查点 R4：DAG 与任务账本闭环

日期：2026-08-11
对比基线：`9941fa3`

## 修改范围

- 对账步骤失败现在会传递为父 DAG 失败。
- 每次子任务重试单独写账本；成功重试不再残留上次错误。
- 父任务使用日期级逻辑幂等键，数据库唯一约束为 `(idempotency_key, attempt_no)`，既防同次重复又保留历次尝试。
- 超过 3 小时仍 running 的 DAG/步骤会标记失败后再重试，避免永久悬挂。
- 同次 Evaluation 主调度的 signal_date 从历史回补队列排除，避免一次全链路重复跑正式评价。
- 建表和交易日历同步收敛为独立 bootstrap 节点，同一 DAG 只执行一次。
- Evaluation 复合脚本取消整体自动重试，避免末段失败后重复正式评价；仅幂等 bootstrap/对账保留重试。
- 同一日期父 DAG 最多允许一个 running 记录，防止手动并发竞态。
- 对账存在 failed 日期时命令返回非零，不再出现“JSON 失败、DAG 成功”。

## 与旧链路对比

- 步骤顺序仍为 Evaluation、日报、邮件、对账；Evaluation 内仍先正式 T+1，再修历史缺口和 T+3。
- 旧业务入口和选股入口不变，DAG 只显式传递原来被吞掉的状态。
- 邮件已发送判断保留；已成功发送不会重复投递。

## 验证结果

- `analysis.runtime_contract_regression_check`：通过。
- `analysis.pipeline_runner_regression_check`：通过，包括失败、超时、重试、deferred、已发送邮件。
- `analysis.task_ledger_regression_check`：通过。
- `analysis.persistence_contract_regression_check`：通过。
- 全量 Python 回归：通过。
- Linux `bash -n scripts/evaluation_entrypoint.sh` 和 Docker 实跑仍需服务器验收。

## 结论

R4 达标。运行状态、重试与幂等形成闭环，没有修改业务计算逻辑。
