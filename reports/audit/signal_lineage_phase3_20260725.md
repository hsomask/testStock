# 第三阶段：信号链路与样本血缘收敛

- 实施日期：2026-07-25
- 行为前置门禁：`pass`
- 数据迁移：已完成
- 数据库操作：只增加字段、索引和视图；未删除旧键、旧评价或历史快照

## 目标

将以下链路收敛为可稳定关联、可追踪运行来源、可执行完整性门禁的数据链：

```text
stock_signal
  → candidate_feature_snapshot
  → watchlist_evaluation_result / evaluation_v2
  → ML / context feedback / correction effectiveness
```

## 身份模型

### signal_id

- 粒度：交易日 + 股票代码 + 原始策略。
- 算法：固定命名空间的UUIDv5。
- 版本：`signal_id_v1`。
- 特性：不依赖数据库自增ID、插入顺序或服务器环境。
- 同一股票命中多个策略时，每个策略拥有独立 `signal_id`。

### decision_id

- 粒度：交易日 + 股票代码。
- 算法：固定命名空间的UUIDv5。
- 版本：`decision_id_v1`。
- 同一股票的多个策略信号共享一个 `decision_id`。
- 原始策略仍保留，最终决策层只有一个。

### run_id

- 日报运行生成UUIDv4 `source_run_id`。
- T+1评价生成独立 `evaluation_run_id`。
- T+3成熟补丁生成独立 `t3_run_id`。
- 历史运行无法可靠还原run_id，保持NULL，不按时间猜测或伪造。

## 最终层级

- 历史原始 `rule_layer` 和 `feature_json` 保留不动，作为审计证据。
- 新增 `canonical_final_layer`，按固定优先级产生唯一最终层：

```text
不可交易过滤
  > 高风险回避
  > 交易条件不满足
  > 只观察
  > 候选低吸
```

- `stock_signal.final_decision_layer` 与快照规范层保持一致。
- 新评价优先读取 `final_decision_layer`，不再用 `action_signal/signal_type` 推断。

## 数据库迁移结果

| 对象 | 总行数 | signal_id非空 | ID冲突 |
|---|---:|---:|---:|
| stock_signal | 1,859 | 1,859 | 0 |
| candidate_feature_snapshot | 661 | 661 | 0 |
| watchlist_evaluation_result | 935 | 935 | 0 |
| signal_performance | 1,762 | 1,762 | 0 |

其他结果：

- 快照无法映射原始信号：0。
- 评价无法映射原始信号：0。
- 规范最终层跨层冲突：0。
- 原始历史快照跨层记录：20个“日期×股票”，保留作为证据。
- 2026-06-26存在6条历史信号缺少快照。
- 这6条只标记为历史血缘缺口，补造快照数量：0。

## 消费者切换

以下消费者改用 `signal_id` 关联：

- ML数据集；
- 场景反馈；
- 纠偏效果；
- 规范信号血缘视图。

切换后验证：

- ML：601行，601个不同signal_id、425个股票级decision_id，重复0。
- 场景反馈：601行，168组。
- 纠偏输入：601行，601个不同signal_id、425个股票级decision_id，重复0。
- ML `rule_layer` 与 `final_layer` 不一致：0。
- 纠偏 `rule_layer` 与 `final_layer` 不一致：0。

## 完整性门禁

新增：

- `analysis/signal_identity_regression_check.py`
- `analysis/signal_lineage_regression_check.py`
- `analysis/signal_lineage_check.py`
- `analysis/signal_lineage_backfill.py`
- `canonical_signal_lineage` 视图

日常评价链路会在评价前、评价后各运行一次严格血缘检查。

最新交易日2026-07-24：

- 信号29条；
- 快照29条；
- 快照覆盖率100%；
- signal_id错误0；
- decision_id错误0；
- 信号/快照重复0；
- 孤儿快照0；
- 孤儿评价0；
- 最终层级冲突0。

## 验收命令

```powershell
python -m analysis.behavior_equivalence_audit
python -m analysis.signal_identity_regression_check
python -m analysis.signal_lineage_regression_check
python -m analysis.signal_lineage_check --date YYYYMMDD --strict
python -m analysis.signal_lineage_backfill
```

## 尚待现场冒烟

历史数据没有可靠run_id，因此无法验证历史运行来源。下一交易日正常生成日报后，需要确认：

- `stock_signal.source_run_id` 100%非空；
- `candidate_feature_snapshot.source_run_id` 100%非空且与信号一致；
- T+1评价后 `evaluation_run_id` 100%非空；
- T+3成熟后 `t3_run_id` 100%非空。

代码级双写已通过无数据库回归测试，现场冒烟不应使用当前行情伪造历史日报。
