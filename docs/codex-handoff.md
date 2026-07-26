# Codex 交接同步文件

## 项目信息

- 项目：testStock / stock-ai-system
- GitHub：`https://github.com/hsomask/testStock.git`
- 本地路径：`D:\code\testStock`
- 开发分支：`dev`
- 技术栈：Python / Docker / PostgreSQL
- 当前状态：第一、第二、第三阶段主体已完成；等待下一交易日run_id现场冒烟；代码尚未提交

## 阶段行为等价门禁

每个新阶段开始前必须先完成行为等价审计，未通过或未确认时不得进入实施。

固定检查项：

1. 使用同一版本输入、配置和交易日比较旧基线与新候选。
2. 对比原始候选的股票、策略、评分、排序和入选原因。
3. 对比最终层级、过滤原因、交易模式和仓位限制。
4. 对比 `stock_signal`、候选快照、评价和ML样本的数量与唯一键。
5. 将差异分类为行为等价、明确口径修正、非预期变化或不可复现。
6. 非预期变化必须先修复；明确口径修正必须先确认。

门禁命令：

```bash
python -m analysis.behavior_equivalence_audit
```

第三阶段前置审计报告：

- `reports/audit/behavior_equivalence_phase3_precheck_20260725.md`
- 当前结论：`pass`
- 原始 selector：通过。
- 最终层级归并：通过，真实快照最终层级差异为0。
- 接近涨停90%板块感知定义、统一市场事实、T+1/T+3隔离已由用户确认接受。
- 历史市场评分因未保存全市场历史日截面无法完整重放，该限制已记录并接受。
- 机器可读确认记录：`config/behavior_policy.json`。

## 已完成的架构收敛

### 第一阶段：市场事实与最终决策

- `analysis/market_facts.py` 是唯一市场事实入口。
- 涨停口径按主板、ST、创业板、科创板、北交所区分。
- 强制满足：`触板数 = 封板数 + 炸板数`。
- `market.py`、`sentiment.py` 只消费同一个 `MarketFacts`。
- `analysis/daily_decision.py` 是唯一最终决策入口。
- 同一股票最终只能处于一个层级：
  `不可交易过滤 > 高风险回避 > 交易条件不满足 > 只观察 > 候选低吸`。
- renderer 不再自行去重、跨层排斥或重算交易模式。

### 第二阶段：Evaluation 时间模型

- 版本：`evaluation_v2`。
- `analysis/evaluation_time.py` 统一计算精确市场交易日 T+1/T+3。
- T+1 只使用下一交易日数据，首次写入后冻结。
- T+3 只使用第三个交易日及三日窗口数据，通过字段白名单补齐。
- 停牌或缺失目标日价格时不得顺延到“下一根K线”。
- T+1 的 `verification_tag`、`feedback_label`、`feedback_score` 不再读取T+3数据。
- T+3 使用独立字段：
  - `verification_tag_3d`
  - `feedback_label_3d`
  - `feedback_score_3d`
  - `attribution_tags_3d`
  - `attribution_text_3d`
- 规范读取入口：
  - `canonical_daily_evaluation_summary`
  - `canonical_daily_evaluation_result`
- 策略反馈、场景反馈、纠偏效果、ML、日报读取器、评价邮件和查询工具均消费规范视图。

### 第三阶段：信号链路与样本血缘

- `analysis/signal_identity.py` 统一生成稳定UUIDv5身份。
- `signal_id` 粒度：交易日 + 股票 + 原始策略。
- `decision_id` 粒度：交易日 + 股票，同一股票多个策略共享。
- 日报使用 `source_run_id`，T+1使用 `evaluation_run_id`，T+3使用 `t3_run_id`。
- `stock_signal.final_decision_layer` 是评价使用的规范最终层。
- 快照原始 `rule_layer` 保留，`canonical_final_layer` 提供唯一规范层。
- ML、场景反馈、纠偏效果改用 `signal_id` 关联。
- `canonical_signal_lineage` 是规范血缘查看入口。
- 历史回填工具：`analysis/signal_lineage_backfill.py`，默认dry-run。
- 严格门禁：`analysis/signal_lineage_check.py`。
- 实施报告：`reports/audit/signal_lineage_phase3_20260725.md`。

## 数据库迁移状态（2026-07-25）

- `sql/schema.sql` 的 evaluation_v2 增量字段及规范视图已应用。
- 25个历史信号日已迁移到 evaluation_v2。
- 规范明细：935条。
- T+1有效：930条。
- T+1验证标签错配：0。
- T+1反馈标签错配：0。
- 已到T+3日历成熟：905条。
- T+3价格完整：900条。
- T+3价格不足：5条。
- 未成熟T+3：30条，T+3标签保持NULL。
- 原有legacy记录保留，不删除；规范视图优先选择v2。

## 当前数据消费结果

- ML样本：601行。
- `trade_date + code + strategy` 去重后仍为601行，无重复放大。
- 其中T+3已完整：571行。
- 场景反馈输入：601行，168个分组。
- 策略反馈：6个策略组，662个T+1样本。

## 日常执行链路

`scripts/evaluation_entrypoint.sh` 会依次：

1. 幂等初始化数据库结构。
2. 运行T+1调度和行情覆盖检查。
3. 生成并保存冻结T+1。
4. 补齐已成熟T+3字段。
5. 刷新策略反馈、场景反馈、快照检查、ML和纠偏效果。

默认不重复执行历史T+1迁移。需要迁移legacy时显式设置：

```bash
EVAL_V2_BACKFILL_DAYS=30 bash scripts/evaluation_entrypoint.sh
```

## 关键命令

```bash
python -m analysis.evaluation_time_regression_check
python -m analysis.consistency_regression_check
python -m analysis.trade_plan_regression_check
python -m analysis.correction_regression_check
python -m analysis.correction_effectiveness_regression_check
python -m analysis.behavior_equivalence_audit
python -m analysis.signal_identity_regression_check
python -m analysis.signal_lineage_regression_check
python -m analysis.signal_lineage_check --date YYYYMMDD --strict
```

历史T+1迁移默认dry-run：

```bash
python -m analysis.evaluation_v2_backfill --as-of YYYYMMDD --days 30
python -m analysis.evaluation_v2_backfill --as-of YYYYMMDD --days 30 --apply
```

T+3成熟补齐默认dry-run：

```bash
python -m analysis.evaluation_maturity_backfill --as-of YYYYMMDD --days 30
python -m analysis.evaluation_maturity_backfill --as-of YYYYMMDD --days 30 --apply
```

查看规范评价：

```bash
python -m analysis.evaluation_query --mode daily --days 10
```

## 注意事项

- 不要再按 `generated_at` 选择“最新评价”；按规范视图和信号日期读取。
- 不要用晚于T+1的运行日期重新计算T+1标签。
- T+3补齐不得更新任何T+1字段。
- 不要删除legacy评价行，除非另有经过审核的数据清理方案。
- 报告中的“策略信号数”和“涉及股票数”是不同口径。
- 当前工作树尚未提交或推送。

## 下一步

- 本地现场冒烟已于 2026-07-25 完成，详见
  `reports/audit/full_chain_verification_20260725.md`。
- 两个产业概念资金榜已替换为行业关注度扩散和行业量价结构，
  详见 `reports/audit/industry_attention_statistics_20260726.md`。
- 2026-07-24 日报信号/快照均为25条，`source_run_id` 单一且一致。
- 2026-07-23 信号截至2026-07-24的T+1评价为30/30，
  明细和汇总 `evaluation_run_id` 单一且一致。
- 成熟T+3回填已生成独立 `t3_run_id`。
- 现场发现并修复同日重跑残留旧信号问题；真实重跑后严格血缘通过。
- 下一步可进入第四阶段LLM旁路接入；LLM不得进入事实计算和最终决策主链。
- 仍需在服务器dev环境跑一次完整 `evaluation_entrypoint.sh`，验证Linux部署入口。
- 验证通过后再提交dev，不要直接在main开发。
