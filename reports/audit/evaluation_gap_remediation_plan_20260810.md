# Evaluation 漏评闭环与数据可用性改造方案

日期：2026-08-10  
范围：Evaluation T+1/T+3、历史 K 线缓存、行业映射快照、策略再评估与 LLM 数据准入。  
边界：本方案不修改 `analysis/selector.py` 的原始选股规则，不改变已有市场口径、决策层级和 T+1/T+3 隔离语义。

## 一、结论

漏评不是随机故障，而是两个确定性缺口叠加：

1. `get_stock_history()` 的缓存新鲜度只要求覆盖“前一工作日”，不知道 Evaluation 明确需要的 `target_1d_date`。当缓存已有足够历史行时，即使缺少目标日，也可能直接返回缓存。
2. 当覆盖率低于 80% 时，`scripts/evaluation_entrypoint.sh` 正确地执行 `defer` 并退出；但后续工具只补已有 Evaluation 的 T+3，不能发现和创建整日缺失的 T+1。

数据库时点还原与代码门禁完全一致：5个漏评日当晚覆盖率分别为 58.3%、72.0%、66.7%、68.0%、76.0%，均低于 80%；成功落库日均不低于 80%。

建议按“行为等价审计 → 目标日缓存修复 → 整日对账补评 → 历史回补 → 行业标签快照 → 数据再评估”的顺序实施。先修代码再回补，避免回补过程中再次触发同类缺口。

## 二、阶段0：行为等价审计

### 目标

证明本轮只修数据获取和评价调度，不改变原始候选、最终决策层和已冻结的 T+1 结果。

### 基线

- 固定至少3个历史交易日，保存 `stock_signal`、`candidate_feature_snapshot`、日报观察池及决策层分布。
- 记录 `(trade_date, code, strategy)`、`signal_id`、`decision_id`、`final_decision_layer`、观察价位和风险字段。
- 保存已有 Evaluation 的 `next_1d_return` 与 `t1_frozen_at`，修复后不得变化。

### 验收

- 原始选择器输出集合完全一致。
- 已存在信号的身份字段完全一致。
- 已有 T+1 行不重算、不覆盖；只允许新增原本整日缺失的 Evaluation。
- 新增行业字段在首阶段仅作为元数据，任何选股和降级逻辑不得读取。

涉及：`analysis/behavior_equivalence_audit.py`、`analysis/consistency_regression_check.py`、`analysis/signal_lineage_regression_check.py`。

## 三、阶段1：修复目标日 K 线缓存语义

### 当前缺口

`analysis/data_fetcher.py`：

- `_latest_expected_cache_date()` 固定返回前一工作日。
- `get_stock_history()` 只用 `latest_db_date >= fresh_cutoff` 判断新鲜度。
- API 返回后只保存数据库中不存在的日期；目标日已有盘中或残缺行时不会被收盘数据刷新。

`analysis/ensure_signal_kline_coverage.py` 虽然知道 `as_of_date`，调用 `get_stock_history()` 时却没有把目标日期传进去。

### 修改方案

扩展 `get_stock_history()`，增加明确的历史目标语义：

- `required_date`：调用方必须得到的交易日。
- `max_save_date`：历史评价不得保存晚于评价目标日的数据。
- `refresh_required_date`：允许收盘后刷新目标日已有行。

缓存命中规则改为：

- 未传 `required_date` 时保持现有通用行为。
- 传入时，只有数据库明确存在该日合格 OHLC 才算满足。
- 目标日缺失时必须尝试 API，不得因“历史行数足够”提前返回。
- API 结果入库前裁剪为 `date <= max_save_date`，避免历史评价产生时间穿越。
- 对 `required_date` 使用 upsert 刷新；当天数据仅允许在收盘保护时间之后刷新，历史日期可直接刷新。

`ensure_signal_kline_coverage()` 调用：

```text
required_date = as_of_date
max_save_date = as_of_date
refresh_required_date = true
```

### 回归用例

1. 缓存到昨天但缺目标日：必须调用 API。
2. 缓存已有目标日：不得进行无意义重复请求。
3. 目标日已有盘中行，收盘后 API 返回最终行：必须更新。
4. API 返回目标日之后的数据：不得入库。
5. API失败：保留原缓存并报告原因，不删除有效数据。
6. 停牌/无交易与上游延迟必须分开计数。

涉及：`analysis/data_fetcher.py`、`analysis/ensure_signal_kline_coverage.py`，新增目标日缓存回归测试。

## 四、阶段2：增加成熟信号日与 Evaluation 每日对账

### 当前缺口

- `evaluation_scheduler_check.infer_signal_date()` 只返回 `MAX(trade_date) < as_of_date`。
- `evaluation_v2_backfill.py` 的候选来自已有 summary，只迁移旧版本。
- `evaluation_maturity_backfill.py` 的候选也来自已有 summary，只补 T+3。

三者都无法发现“有成熟信号、完全没有 summary”的日期。

### 新增模块

新增 `analysis/evaluation_gap_reconcile.py`，默认 dry-run：

1. 以 `stock_signal` 的交易日为权威集合。
2. 用 `resolve_evaluation_horizons()` 判断 T+1 是否成熟。
3. 与 `canonical_daily_evaluation_summary` 做 anti-join。
4. 对缺失日期逐日检查目标日行情覆盖率。
5. 覆盖率 `<80%`：保留 pending，不写正式评价。
6. 覆盖率 `>=80%` 且 `--apply`：创建 T+1 Evaluation。
7. 已有 summary：严格跳过，保护 T+1 冻结语义。
8. 输出逐日 JSON：`ready/pending/recovered/already_exists/error`。

建议参数：

```text
--as-of YYYYMMDD
--days 30
--min-coverage 0.80
--time-budget 1800
--deep
--apply
```

### 调用位置

在 `scripts/evaluation_entrypoint.sh` 的 schema 初始化之后、当前日 scheduler 之前执行最近30天对账。这样即使当前日仍 defer，也能补早先已经成熟且现在数据完整的缺口。

23:00 重试任务继续保留，形成两层保障；无需新增第四个工作日 cron。

### 数据血缘

回补记录必须保留：

- 原始 `signal_date`、`target_1d_date`、`target_3d_date`。
- 实际执行日 `run_as_of_date`。
- 新的 `evaluation_run_id`。
- `diagnostics_json.recovery_reason = missing_daily_evaluation`。
- `diagnostics_json.recovered_at` 与回补前覆盖率。

## 五、阶段3：回补5个整日缺失的 Evaluation

代码修复和 dry-run 验证通过后再执行正式回补：

| signal_date | target_1d_date | 当前可用性 |
|---|---|---|
| 20260727 | 20260728 | 可回补 |
| 20260730 | 20260731 | 可回补 |
| 20260731 | 20260803 | 需接受 23/24 覆盖或继续补齐 603221 |
| 20260804 | 20260805 | 可回补 |
| 20260805 | 20260806 | 可回补 |

先运行对账 dry-run，确认目标集合恰好是预期缺口；再 `--apply`。随后运行 `evaluation_maturity_backfill` 补已成熟 T+3，并依次执行：

- `signal_lineage_check --strict`
- `snapshot_integrity_check`
- `evaluation_query`
- `ml_dataset_builder --min-coverage 0.9`
- `correction_effectiveness --min-coverage 0.8`

禁止直接修改汇总表或手写收益字段。

## 六、阶段4：行业映射正式进入信号与快照

### 数据事实

近期信号股票的 `stock_board_map` 行业映射覆盖率为100%，但每只股票平均和实际均为3个行业层级。例如：

- 002579：电子、元件、印制电路板。
- 000603：有色金属、贵金属、白银。

因此，直接随意选择一个值写入单值 `stock_signal.industry` 会丢失层级并造成不稳定口径。

### 建议

正式写入，但第一阶段采用完整标签快照，而非强行单值化：

- `stock_signal.industry_tags JSONB`
- `candidate_feature_snapshot.industry_tags JSONB`
- `industry_mapping_version TEXT`
- `industry_mapped_at TIMESTAMP`

每日生成信号时一次性批量读取候选代码映射，排序、去重后写入；快照复制当日信号标签，后续周度 mapper 刷新不得改写历史快照。

现有 `industry` 单值字段暂不作为权威字段。若以后需要主行业，必须先定义稳定层级或主行业字典，再新增 `primary_industry`；不能使用主题偏好或当前热门板块动态决定，因为那会造成特征泄漏和历史漂移。

首轮只保存元数据，不接入 `selector.py`、`daily_decision.py` 或纠偏权重，以保持行为等价。

## 七、阶段5：重新统计策略表现与 LLM 数据准入

回补完成后，旧的策略统计不能沿用，必须按规范视图重算：

- 按信号日、策略、最终决策层、风险层统计 T+1/T+3。
- 比较回补前后样本数、胜率、均值、回撤及策略排序。
- 单独标注 recovered 样本，检查其结果是否与正常准时样本存在系统差异。
- 检查策略反馈是否因漏评样本补入而改变 `hot/normal/weak/blocked`。

### LLM准入门槛

解释型旁路可在以下条件全部满足后开始：

- 最近20个成熟信号日 Evaluation 日完整率 `>=95%`。
- T+1 日覆盖率全部 `>=80%`，中位数 `>=95%`。
- 可学习样本使用现有 `coverage_1d >=90%` 门槛。
- 已成熟 T+3 完整率 `>=95%`。
- 信号、快照、Evaluation 血缘完整率100%。
- 快照核心字段覆盖率 `>=95%`。
- 行业标签上线后覆盖率 `>=95%`。

若 LLM 输出要影响评分或选股，建议提高到：至少60个完整交易日，并且每个主要策略至少100个合格样本；在此之前只允许生成解释、问题清单和离线建议，不进入正式决策链。

## 八、上线和回滚

### 上线顺序

1. 行为等价基线。
2. 目标日缓存修复及回归测试。
3. 对账模块 dry-run。
4. Linux 容器全链路验证。
5. 5日缺口正式回补。
6. 策略反馈与日报重算。
7. 行业标签只读落库。
8. 连续观察至少5个交易日。

### 回滚边界

- 代码可回滚，但已新增的历史 Evaluation 不应删除；它们是对真实缺口的补录。
- 回补前导出目标日期 summary/result 主键清单和行数。
- 行业字段为新增可空字段，回滚代码后不会影响旧链路。
- 不修改已有 T+1 冻结行，是最重要的数据安全约束。

## 九、最终验收

- 最近30天所有成熟 `stock_signal.trade_date` 都有且仅有一条规范 daily summary。
- 不存在整日漏评；pending 必须有明确覆盖率和缺失原因。
- 对账工具重复执行不新增重复记录，具备幂等性。
- 既有 T+1 的值和冻结时间在修复前后完全一致。
- T+3 只更新独立字段，不污染 T+1。
- 原始候选、最终决策层、观察价位和风险规则行为等价。
- 服务器21:00主链路与23:00重试连续5个交易日无漏评。

