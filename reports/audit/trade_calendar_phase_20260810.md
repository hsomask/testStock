# 持久化交易日历阶段审计

日期：2026-08-10  
阶段：交易日口径收敛  
状态：本地实现与数据库首次同步完成，待服务器部署验证。

## 行为等价基线

- 原始 `analysis/selector.py` 与 HEAD 的标准化源码哈希一致。
- 最终决策层历史重放差异：0。
- 原 T+1/T+3 隔离回归：通过。
- 市场事实和接近涨停口径保持已批准版本不变。

## 实施内容

- 新增 `exchange_calendar` 与 `exchange_calendar_sync_run`。
- 新增统一访问模块 `analysis/trade_calendar.py`。
- 新增原子同步工具 `analysis/trade_calendar_sync.py`，默认 dry-run。
- 新增 `analysis/trade_calendar_regression_check.py`。
- `evaluation_time.py` 改为读取持久化开市日列表。
- 日报、邮件、Evaluation、板块历史、数据库审计、无效数据清理和涨停生态统一使用规范日历。
- 日报及 Evaluation Linux 入口在 schema 初始化后执行日历 `--ensure`。
- `init_db.py` 不再输出完整数据库连接串。

## 首次同步结果

| 指标 | 结果 |
|---|---:|
| 自然日行数 | 6466 |
| 开市日 | 4128 |
| 休市日 | 2081 |
| 未知未来日 | 257 |
| 起始日期 | 2010-01-01 |
| 权威截止日期 | 2026-12-31 |
| 生成截止日期 | 2027-09-14 |
| 同步校验 | 通过 |

2010—2025完整年度的开市日数量为238—245，均在设定的230—255合理区间内；未发现周末开市、重复日期或当前日期未覆盖。

## 切换后等价审计

数据库中57个历史信号日逐日比较：

- 旧外部日历与新持久化日历的交易日状态差异：0。
- T+1差异：0。
- T+2差异：0。
- T+3差异：0。
- 原始选股逻辑变更：无。

## 回归结果

- `analysis.trade_calendar_regression_check`：通过。
- `analysis.evaluation_time_regression_check`：通过。
- `analysis.consistency_regression_check`：通过。
- `analysis.signal_lineage_regression_check`：通过。
- `analysis.trade_plan_regression_check`：通过。
- `analysis.behavior_equivalence_audit`：通过。
- `analysis.validate_pipeline --date 20260807`：数据库与日历项目通过；本地缺少服务器日报产物，因此文件项出现3个预期失败，不属于数据库或代码故障。

## 待部署验证

1. 服务器拉取代码并重建镜像。
2. 手工执行一次 `trade_calendar_sync --ensure --apply`。
3. 运行 `trade_calendar_regression_check`。
4. 运行一次 Linux `evaluation_entrypoint.sh` dry/no-email 链路。
5. 连续观察5个交易日，确认日报、Evaluation与邮件使用同一交易日口径。
