# 检查点B：轻量任务DAG验收

日期：2026-08-10

验收提交：`f52b47e`

## 结论

- 检查点B完成。
- 是否修改原有选股逻辑：否。
- 是否满足进入检查点C：是。

## 最终DAG

1. `evaluation`：评价前一信号交易日；失败或数据不足不阻止当日日报。
2. `daily_report`：沿用原 `entrypoint.sh`，当日行情、选股、快照和日报只计算一次。
3. `daily_email`：依赖日报成功；已有成功邮件记录时跳过。
4. `daily_reconcile`：无论前序结果如何均执行，失败可重试一次。

## 服务器真实运行结果

- `daily_pipeline`：`deferred`，符合Evaluation覆盖不足语义。
- `daily_initial`（修正前验证运行）：成功。
- `evaluation`：`deferred`。
- `daily_email`：成功，实际只发送一次。
- `daily_reconcile`：成功。
- 当日信号25条、快照25条、日报两种模式各一份。
- 没有Python导入、Bash语法、数据库或Docker硬错误。

## 验收中发现并修复的问题

原DAG继承旧链路的“先生成日报、Evaluation后再次调用daily_report”方式，导致行情获取和选股计算执行两次。任务账本确认两次日报计算分别耗时约114秒和105秒。

修正后：

- Evaluation前置。
- 当日日报只生成一次，并自然读取刚完成的Evaluation事实。
- 删除伪“重渲染”节点。
- 当天已有 `daily_pipeline=success/deferred` 时返回 `pipeline_already_completed`，阻止手动任务与crontab重复触发。
- 保留 `--force` 作为显式人工重跑开关。

## 检查覆盖

- DAG拓扑、循环依赖和未知依赖检查通过。
- Python全量编译通过。
- 新旧入口Bash语法通过。
- 非交易日真实容器路径返回 `skipped`。
- Evaluation `deferred/skip/error`状态映射通过。
- 上游失败、blocked传播、超时和重试检查通过。
- 邮件防重检查通过。
- 对账always-run检查通过。
- 整链防重真实数据库检查通过。
- 行为等价门禁通过，最终层级差异为0。

## 回退

兼容入口保留在 `scripts/report_with_evaluation_legacy_entrypoint.sh`，可通过 `USE_LEGACY_PIPELINE=1` 显式启用。检查点C不得在兼容脚本中新增功能。

## 检查点C约束

数据适配必须先包装原主源并逐字段验证等价，再接备用源。备用源只能补缺，不能静默覆盖主源；不得改变选股、评分、排序、层级、涨停定义或Evaluation公式。

## 验收边界说明

服务器完整手动运行发生在发现“日报计算两次”之前；该次运行用于确认任务账本、邮件防重和对账链路。重复计算修复后，已完成本地DAG回归、数据库防重检查和 `dry-run`，但尚未在服务器使用 `--force` 再执行一次最终版本完整DAG。因此，部署验收时仍需补一次最终版本服务器全链路运行。
