# 检查点 R6：本地总验收

日期：2026-08-11
对比基线：`9941fa3`

## 本地已通过

- `python -m compileall -q analysis`。
- 除依赖当前实产日报文件的 `report_regression_check` 外，18 个回归模块全部通过。
- 运行契约、持久化契约、邮件、日报 Upsert、Evaluation 缺口、K 线刷新、身份对账、DAG、任务账本均有失败路径测试。
- `git diff --check` 通过。
- 行为等价审计：`gate_status=pass`，selector 源码一致，最终分层差异 0。
- 对生产数据库的诊断均使用只读连接。
- 迁移预检：ready；日报 71 个重复规范键、210 个旧重复行会先归档再从主表去重；任务幂等键无冲突。

## 旧代码对比

- 零差异文件：selector、市场评分、情绪评分、trade plan、纠偏引擎、watchlist Evaluation、报告 renderer。
- 保留旧日报前置模块、信号跟踪、回测统计及告警降级语义。
- 新 DAG 不递归调用旧全链路；邮件由 DAG 单独发送，日报 entrypoint 中已禁用。
- schema/calendar bootstrap 在 DAG 中只执行一次；复合 Evaluation 不进行整段自动重试。
- 变更集中在运行状态、数据修复、持久化唯一性、对账和数据源质量。

## 服务器待验收

- `bash -n scripts/evaluation_entrypoint.sh scripts/report_with_evaluation_entrypoint.sh entrypoint.sh`。
- 运行 `analysis.migration_preflight` 后执行 `analysis.init_db`，确认归档 210 行且唯一索引建立。
- Docker 内全量回归。
- 手动 DAG 仅跑一次，验证失败传递、邮件防重、日报规范行=1、缺失 Evaluation 自动补齐。
- 用新生成的当日日报运行 `analysis.report_regression_check --date YYYYMMDD`。

## 结论

本地代码验收达标；Linux shell、真实迁移和 Docker 全链路必须在服务器通过后才能判定最终上线完成。
