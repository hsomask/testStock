# V4-Evaluation 第 1 轮：观察池有效性验证最小闭环

## 当前项目背景

项目：`testStock`

当前阶段：

> V4-Evaluation：观察池有效性验证

前一阶段已经完成：

* V3-Stabilization：日报系统口径统一与稳定性收敛；
* 非交易日入口守卫；
* report_context 链路；
* pipeline_check / report_regression_check；
* 数据库非交易日污染审计；
* 20260523 / 20260524 的污染数据已 quarantine 并从业务表清理；
* `db_data_audit --days 30` 已经 0 异常。

现在进入新阶段：

> 验证日报观察池是否真的有用。

---

## 一、本轮目标

本轮只做一个最小评价闭环：

1. 从数据库读取历史 `stock_signal`；
2. 读取入选股票在入选后若干交易日的价格表现；
3. 计算基础表现指标；
4. 按观察池分层、策略来源、风险等级做聚合；
5. 输出 JSON + Markdown 报告；
6. 不修改 selector；
7. 不修改日报生成；
8. 不修改策略阈值；
9. 不修改邮件；
10. 不修改数据库原始数据。

本轮只评价，不优化策略。

---

## 二、本轮允许新增文件

允许新增：

```text
analysis/watchlist_evaluation.py
```

可选新增文档：

```text
docs/V4-EVALUATION.md
```

---

## 三、本轮禁止修改文件

禁止修改：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_mapping_quality.py
analysis/board_trend_tracker.py
entrypoint.sh
data/config.py
```

本轮只新增评价脚本，不改业务链路。

---

## 四、评价对象

优先读取数据库表：

```text
stock_signal
```

如果表不存在，脚本应输出明确提示并正常退出。

需要识别字段：

```text
trade_date
code
name
strategy
risk_level
action_signal
watchlist_layer
```

但考虑历史表字段可能不完整，脚本要做兼容：

* 如果没有 `watchlist_layer`，用 `risk_level / action_signal` 近似分层；
* 如果没有 `strategy`，标记为 `unknown`；
* 如果没有 `risk_level`，标记为 `unknown`；
* 不因为缺少非核心字段直接崩溃。

---

## 五、表现指标

本轮先计算最基础的 4 类指标：

### 1. 次日收益

```text
next_1d_return
```

定义：

```text
入选日后第一个交易日收盘价 / 入选日收盘价 - 1
```

### 2. 3 日收益

```text
next_3d_return
```

定义：

```text
入选日后第 3 个交易日收盘价 / 入选日收盘价 - 1
```

如果后续交易日不足 3 天，则标记为缺失，不强行计算。

### 3. 3 日最高涨幅

```text
max_3d_return
```

定义：

```text
入选后 3 个交易日内最高价 / 入选日收盘价 - 1
```

### 4. 3 日最大回撤

```text
max_3d_drawdown
```

第一版简单定义：

```text
入选后 3 个交易日内最低价 / 入选日收盘价 - 1
```

这是相对入选价的下行幅度，不做复杂路径回撤。

---

## 六、行情数据来源

优先复用现有函数：

```text
analysis.data_fetcher.get_stock_history
```

或项目中已有的历史行情获取函数。

要求：

1. 不新增外部数据源；
2. 不改 `data_fetcher.py`；
3. 如果某股票历史数据不足，记录为 missing；
4. 不因单只股票失败导致全局失败；
5. 对每只股票的失败原因写入 details。

---

## 七、防止未来函数

必须注意：

```text
不能用入选日之后才知道的信息决定是否入选；
本轮只读取已经存在的 stock_signal 作为入选记录；
后续行情只用于评价表现。
```

报告里明确写：

```text
本评价只用于复盘观察池表现，不构成实盘交易建议。
```

---

## 八、脚本命令

新增脚本支持：

```bash
python -m analysis.watchlist_evaluation --start 20260501 --end 20260531
```

也支持最近 N 天：

```bash
python -m analysis.watchlist_evaluation --days 30
```

如果都不传，默认：

```text
最近 30 天
```

---

## 九、输出文件

生成：

```text
reports/evaluation/watchlist_evaluation_YYYYMMDD_YYYYMMDD.json
reports/evaluation/watchlist_evaluation_YYYYMMDD_YYYYMMDD.md
```

其中 `YYYYMMDD_YYYYMMDD` 是评价区间。

不要写入 `reports/daily/`，避免和日报产物混在一起。

---

## 十、JSON 输出结构

建议结构：

```json
{
  "start_date": "20260501",
  "end_date": "20260531",
  "status": "ok",
  "summary": {
    "total_signals": 120,
    "evaluated_signals": 105,
    "missing_price_data": 15
  },
  "overall": {
    "avg_next_1d_return": 0.012,
    "win_rate_1d": 0.54,
    "avg_next_3d_return": 0.025,
    "win_rate_3d": 0.58,
    "avg_max_3d_return": 0.041,
    "avg_max_3d_drawdown": -0.021
  },
  "by_strategy": {},
  "by_layer": {},
  "by_risk_level": {},
  "details": []
}
```

---

## 十一、Markdown 报告结构

Markdown 报告建议：

```markdown
# 观察池有效性评估

## 1. 评价区间

## 2. 样本概况

## 3. 总体表现

## 4. 按策略来源分组

## 5. 按观察池分层分组

## 6. 按风险等级分组

## 7. 数据缺失与注意事项

## 8. 初步结论
```

结论必须谨慎：

```text
本报告仅反映历史观察池样本的后验表现；
样本量较小时不做强结论；
不作为实盘买卖依据。
```

---

## 十二、分组统计

至少输出这些分组：

```text
by_strategy
by_layer
by_risk_level
```

每组指标包括：

```text
count
evaluated_count
avg_next_1d_return
win_rate_1d
avg_next_3d_return
win_rate_3d
avg_max_3d_return
avg_max_3d_drawdown
missing_count
```

---

## 十三、实现建议

建议函数结构：

```python
def parse_args():
    ...

def resolve_date_range(args):
    ...

def get_db_conn():
    ...

def fetch_signals(conn, start_date, end_date):
    ...

def fetch_price_window(code, trade_date, days=5):
    ...

def evaluate_one_signal(signal):
    ...

def aggregate_metrics(records, group_key=None):
    ...

def build_report(result):
    ...

def save_outputs(result, markdown, start_date, end_date):
    ...

def main():
    ...
```

保持简单，不要引入复杂依赖。

---

## 十四、安全要求

1. 不写数据库；
2. 不更新 `stock_signal`；
3. 不更新 `signal_performance`；
4. 不删除任何数据；
5. 不修改 reports/daily；
6. 不调用 email；
7. 不调用 selector；
8. 不生成交易计划。

这是纯评价脚本。

---

## 十五、验收命令

执行：

```bash
python -m compileall analysis
python -m analysis.watchlist_evaluation --days 30
```

然后检查：

```bash
ls -lh reports/evaluation/
cat reports/evaluation/watchlist_evaluation_*.json
```

如果本地数据不够，也可以指定已有区间：

```bash
python -m analysis.watchlist_evaluation --start 20260501 --end 20260531
```

最后检查 Git：

```bash
git diff --stat
git status --short --untracked-files=all
```

---

## 十六、预期 diff

理想 diff：

```text
analysis/watchlist_evaluation.py
```

可选：

```text
docs/V4-EVALUATION.md
```

不应该出现：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
entrypoint.sh
data/config.py
reports/
__pycache__/
.claude/
PRDs/
```

注意：

```text
reports/evaluation/ 是运行产物，不要提交。
```

---

## 十七、提交要求

如果验收通过：

```bash
git add analysis/watchlist_evaluation.py
git commit -m "feat: add watchlist evaluation report"
```

如果新增文档：

```bash
git add docs/V4-EVALUATION.md
git commit -m "docs: add watchlist evaluation notes"
```

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
```

---

## 十八、本轮通过标准

1. 能读取 `stock_signal`；
2. 能按日期区间评价历史观察池；
3. 能计算次日收益、3 日收益、3 日最高涨幅、3 日下行幅度；
4. 能按 strategy / layer / risk_level 分组；
5. 能输出 JSON；
6. 能输出 Markdown；
7. 不写数据库；
8. 不改业务链路；
9. 不改 selector；
10. 不改日报生成；
11. 不提交运行产物。

# V4-Evaluation 第 2 轮：评价覆盖率校准与缺失原因拆分

## 当前背景

项目：`testStock`

当前阶段：

> V4-Evaluation：观察池有效性验证

第 1 轮已完成：

```text
新增 analysis/watchlist_evaluation.py
从 stock_signal 读取历史入选记录
计算 next_1d_return / next_3d_return / max_3d_return / max_3d_drawdown
按 strategy / layer / risk_level 聚合
输出 JSON + Markdown 到 reports/evaluation/
纯只读，不写数据库，不改业务链路
```

第 1 轮运行结果：

```text
总信号 383 条
有效评价 20 条
缺失 363 条
```

原因初步判断：

```text
348 条来自 5 月下旬，距今不足 3 个交易日，3 日指标缺失
15 条历史行情获取失败
20 条有效，主要是 5 月上旬信号
```

本轮目标不是调策略，而是校准评价脚本的覆盖率与缺失分类。

---

## 一、本轮目标

本轮只优化 `watchlist_evaluation.py` 的评价逻辑和输出解释。

目标：

1. 区分不同指标的可评价样本；
2. 不要求所有指标完整才算有效；
3. 允许 1 日指标和 3 日指标分别统计；
4. 明确缺失原因；
5. 输出覆盖率；
6. 避免用未成熟样本得出错误结论；
7. 不修改 selector；
8. 不修改日报；
9. 不写数据库。

---

## 二、允许修改文件

允许修改：

```text
analysis/watchlist_evaluation.py
```

可选修改：

```text
docs/V4-EVALUATION.md
```

---

## 三、禁止修改文件

禁止修改：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_mapping_quality.py
analysis/board_trend_tracker.py
entrypoint.sh
data/config.py
```

本轮只改评价脚本，不碰业务链路。

---

## 四、核心改造 1：指标级别有效样本

当前不要只用一个：

```text
evaluated_signals
```

而是拆成：

```json
{
  "total_signals": 383,
  "eligible_1d": 120,
  "evaluated_1d": 105,
  "eligible_3d": 35,
  "evaluated_3d": 20,
  "missing_price_data": 15,
  "immature_1d": 263,
  "immature_3d": 348
}
```

解释：

* `eligible_1d`：从入选日到当前，理论上已经有至少 1 个后续交易日；
* `eligible_3d`：理论上已经有至少 3 个后续交易日；
* `evaluated_1d`：实际拿到行情并算出 1 日收益；
* `evaluated_3d`：实际拿到行情并算出 3 日收益；
* `immature_1d`：还不够 1 个后续交易日；
* `immature_3d`：还不够 3 个后续交易日；
* `missing_price_data`：理论上应可评价，但行情获取失败或数据不足。

---

## 五、核心改造 2：缺失原因拆分

每条 signal 的缺失原因不要只写 “missing”。

至少拆成：

```text
not_mature_1d
not_mature_3d
price_fetch_failed
insufficient_price_window
missing_entry_close
invalid_code
unknown
```

JSON 中增加：

```json
"missing_reasons": {
  "not_mature_3d": 348,
  "price_fetch_failed": 15
}
```

Markdown 中也要展示：

```markdown
## 数据覆盖率与缺失原因

| 缺失原因 | 数量 | 说明 |
|---|---:|---|
| not_mature_3d | 348 | 入选时间太近，尚无 3 个后续交易日 |
| price_fetch_failed | 15 | 历史行情获取失败 |
```

---

## 六、核心改造 3：1 日和 3 日分开聚合

聚合统计时，不要要求所有指标都存在。

例如：

```text
avg_next_1d_return 只基于有 next_1d_return 的样本
win_rate_1d 只基于有 next_1d_return 的样本

avg_next_3d_return 只基于有 next_3d_return 的样本
win_rate_3d 只基于有 next_3d_return 的样本
```

每个分组输出：

```json
{
  "count": 100,
  "evaluated_1d_count": 80,
  "evaluated_3d_count": 20,
  "avg_next_1d_return": 0.012,
  "win_rate_1d": 0.54,
  "avg_next_3d_return": 0.025,
  "win_rate_3d": 0.58,
  "avg_max_3d_return": 0.041,
  "avg_max_3d_drawdown": -0.021
}
```

---

## 七、核心改造 4：样本成熟度提示

Markdown 报告开头增加样本成熟度提示：

```markdown
> 注意：本期多数信号来自近期，3 日表现尚未完全成熟。因此当前 3 日指标样本量较小，不能据此对策略优劣做强结论。
```

如果 `evaluated_3d_count / total_signals < 0.3`，报告结论必须自动降级为：

```text
样本不足，仅做覆盖率观察，不做策略优劣判断。
```

---

## 八、核心改造 5：评价基准日

脚本中需要明确一个 `as_of_date`：

```text
as_of_date = 当前日期或用户传入 --as-of
```

支持可选参数：

```bash
python -m analysis.watchlist_evaluation --start 20260501 --end 20260531 --as-of 20260603
```

如果不传 `--as-of`，默认今天。

用 `as_of_date` 判断样本是否成熟：

```text
入选日之后是否已经过了至少 1 / 3 个交易日
```

第一版可以简化使用自然日 + 历史行情实际长度判断，不强制维护交易日历，但输出要说明。

---

## 九、输出结构调整

JSON 的 `summary` 建议变成：

```json
"summary": {
  "total_signals": 383,
  "eligible_1d": 120,
  "evaluated_1d": 105,
  "eligible_3d": 35,
  "evaluated_3d": 20,
  "coverage_1d": 0.274,
  "coverage_3d": 0.052,
  "missing_price_data": 15,
  "missing_reasons": {
    "not_mature_3d": 348,
    "price_fetch_failed": 15
  }
}
```

---

## 十、Markdown 报告调整

增加一节：

```markdown
## 2. 数据覆盖率与样本成熟度
```

内容包括：

```text
总信号数
1 日可评价样本
1 日实际评价样本
3 日可评价样本
3 日实际评价样本
缺失原因
是否足以做策略结论
```

结论必须谨慎。

---

## 十一、安全要求

1. 不写数据库；
2. 不更新 stock_signal；
3. 不更新 signal_performance；
4. 不修改业务链路；
5. 不修改 selector；
6. 不发送邮件；
7. 不生成 daily report；
8. 不修改 reports/daily。

---

## 十二、验收命令

执行：

```bash
python -m compileall analysis
python -m analysis.watchlist_evaluation --start 20260501 --end 20260531
```

检查输出：

```bash
ls -lh reports/evaluation/
cat reports/evaluation/watchlist_evaluation_*.json
```

重点检查：

```text
summary 中存在 eligible_1d / evaluated_1d / eligible_3d / evaluated_3d
missing_reasons 中能区分 not_mature_3d 和 price_fetch_failed
Markdown 中有“样本成熟度”提示
```

最后检查 Git：

```bash
git diff --stat
git status --short --untracked-files=all
```

---

## 十三、预期 diff

理想 diff：

```text
analysis/watchlist_evaluation.py
```

可选：

```text
docs/V4-EVALUATION.md
```

不应该出现：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
entrypoint.sh
data/config.py
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十四、提交要求

如果验收通过：

```bash
git add analysis/watchlist_evaluation.py
git commit -m "chore: refine watchlist evaluation coverage"
```

如果新增文档：

```bash
git add docs/V4-EVALUATION.md
git commit -m "docs: add watchlist evaluation coverage notes"
```

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
```

---

## 十五、本轮通过标准

1. 1 日和 3 日指标分开统计；
2. 不再用单一 evaluated_signals 掩盖覆盖率；
3. 缺失原因明确拆分；
4. Markdown 有样本成熟度提示；
5. 低覆盖率时不做强策略结论；
6. 不写数据库；
7. 不改 selector；
8. 不改日报生成；
9. 不提交运行产物。

# V4-Evaluation 第 3 轮：watchlist_evaluation 统一评价入口与 daily 模式

## 当前项目背景

项目：`testStock`

当前阶段：

> V4-Evaluation：评价数据可信性建设

前置阶段已经完成：

1. V3-Stabilization 已完成并合并；
2. 非交易日入口守卫已完成；
3. 非交易日数据库污染已审计并 quarantine 清理；
4. `db_data_audit --days 30` 已无异常；
5. `email_sender.py` 非交易日守卫已完成；
6. `analysis/watchlist_evaluation.py` 已新增；
7. 第 1 轮 watchlist evaluation 已能读取 `stock_signal` 并输出 JSON/Markdown；
8. 第 2 轮已完成：

   * `eligible_1d / evaluated_1d`
   * `eligible_3d / evaluated_3d`
   * `coverage_1d / coverage_3d`
   * `missing_reasons`
   * `--as-of`
   * 样本成熟度提示与结论降级。

当前判断：

> 现在不是调策略阶段，而是先把评价数据做准确、可复现、可追踪。

本轮目标：

> 收敛 `watchlist_evaluation.py`，使其成为唯一评价入口，并支持区间评价模式与每日 T+1 验证模式。

---

## 一、本轮核心原则

不要新增：

```text
analysis/daily_verification.py
```

原因：

```text
每日 T+1 验证应该作为 watchlist_evaluation.py 的 daily 模式实现。
否则会出现两个评价脚本、两套指标口径、两套缺失原因定义，后续容易埋 bug。
```

本轮只收敛现有评价脚本，不新开评价系统。

---

## 二、本轮目标

本轮只做以下事情：

1. 明确 `watchlist_evaluation.py` 是唯一评价入口；
2. 保留原有区间评价能力；
3. 增加 `--mode range|daily`；
4. `range` 模式继续用于区间评价；
5. `daily` 模式用于每日 T+1 验证；
6. daily 模式复用现有取数、行情、指标、聚合逻辑；
7. 增加稳定 `signal_key`；
8. 统一单条信号评价函数；
9. 不写数据库；
10. 不调 selector；
11. 不改日报生成；
12. 不改邮件；
13. 不改 pipeline。

---

## 三、允许修改文件

只允许修改：

```text
analysis/watchlist_evaluation.py
```

可选新增或修改文档：

```text
docs/V4-EVALUATION.md
```

---

## 四、禁止修改文件

禁止修改：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_mapping_quality.py
analysis/board_trend_tracker.py
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
entrypoint.sh
data/config.py
```

本轮不改业务链路，不改策略，不改日报，不改数据库清理工具。

---

## 五、评价入口设计

`watchlist_evaluation.py` 支持：

```bash
python -m analysis.watchlist_evaluation --mode range --start 20260501 --end 20260531
python -m analysis.watchlist_evaluation --mode range --days 30
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529
```

默认模式：

```text
range
```

如果不传 `--mode`，保持原有行为，避免破坏旧命令。

---

## 六、range 模式要求

原有命令必须继续可用：

```bash
python -m analysis.watchlist_evaluation --start 20260501 --end 20260531
python -m analysis.watchlist_evaluation --days 30
```

range 模式含义：

```text
评价某个区间内所有 stock_signal 的整体表现。
```

输出仍然是：

```text
reports/evaluation/watchlist_evaluation_START_END.json
reports/evaluation/watchlist_evaluation_START_END.md
```

保留已有能力：

```text
eligible_1d
evaluated_1d
eligible_3d
evaluated_3d
coverage_1d
coverage_3d
missing_reasons
by_strategy
by_layer
by_risk_level
```

不要破坏现有 JSON/Markdown 结构。如果需要新增字段，只能追加，不能删除旧字段。

---

## 七、daily 模式要求

新增 daily 模式：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529
```

含义：

```text
用 as-of 日期的行情状态，验证 signal-date 当天的观察池信号。
```

例如：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260602 --as-of 20260603
```

表示：

```text
验证 20260602 日报/观察池在 20260603 的 T+1 表现。
```

daily 模式只读取：

```text
stock_signal.trade_date = signal_date
```

不要读取整个区间。

---

## 八、daily 模式输出文件

daily 模式输出：

```text
reports/evaluation/daily_watchlist_evaluation_SIGNALDATE_ASOFDATE.json
reports/evaluation/daily_watchlist_evaluation_SIGNALDATE_ASOFDATE.md
```

例如：

```text
reports/evaluation/daily_watchlist_evaluation_20260528_20260529.json
reports/evaluation/daily_watchlist_evaluation_20260528_20260529.md
```

不要写入：

```text
reports/daily/
```

---

## 九、统一 signal_key

新增统一 signal key 逻辑。

优先规则：

```text
如果 stock_signal 有 id 字段：
    signal_key = id
否则：
    signal_key = trade_date + code + strategy
```

实现为函数，例如：

```python
def build_signal_key(signal: dict) -> str:
    ...
```

每条 details 必须包含：

```json
{
  "signal_key": "...",
  "trade_date": "20260528",
  "code": "600000",
  "name": "...",
  "strategy": "...",
  "watchlist_layer": "...",
  "risk_level": "..."
}
```

目的：

```text
后续 range / daily / save-db 都使用同一评价单位。
```

---

## 十、统一单条信号评价函数

将单条信号评价逻辑收敛为一个函数，例如：

```python
def evaluate_signal_performance(signal: dict, as_of_date: str | None = None) -> dict:
    ...
```

要求：

1. range 模式调用它；
2. daily 模式也调用它；
3. 不复制评价逻辑；
4. 所有指标统一由该函数产生；
5. 缺失原因也由该函数输出。

输出字段至少包含：

```text
signal_key
trade_date
code
name
strategy
watchlist_layer
risk_level
entry_close
next_1d_return
next_3d_return
max_3d_return
max_3d_drawdown
is_mature_1d
is_mature_3d
price_status
missing_reason
```

---

## 十一、daily 模式 Markdown 结构

daily 模式 Markdown 至少包含：

```markdown
# 昨日观察池 T+1 验证报告

## 1. 验证对象

- 信号日期：
- 验证日期：
- 样本数：

## 2. 总体表现

- 1 日可评价样本数
- 1 日实际评价样本数
- 平均次日收益
- 次日胜率
- 平均最大下行幅度

## 3. 按观察池分层

## 4. 按策略来源

## 5. 按风险等级

## 6. 高风险池验证

## 7. 缺失原因

## 8. 初步结论
```

结论必须谨慎：

```text
本报告用于验证昨日观察池表现，不构成实盘买卖建议。
```

如果样本量过少，必须降级：

```text
样本量不足，仅做数据跟踪，不做策略优劣判断。
```

---

## 十二、daily 模式的辅助兑现判断

第一版只做简单规则，不做复杂 AI 判断。

### 可观察池

```text
next_1d_return > 0：上涨兑现
next_1d_return <= 0：未兑现或待观察
max_3d_drawdown < -0.04：风险失败
```

### 谨慎观察池

```text
next_1d_return 小幅波动且无大回撤：符合谨慎
next_1d_return > 0.03：可能过于保守
next_1d_return < -0.03：风险偏高
```

### 高风险复盘池

```text
next_1d_return < 0 或 max_3d_drawdown < -0.03：风险提示命中
next_1d_return > 0.03 且无明显回撤：可能过度保守
```

这些判断只作为辅助字段输出，例如：

```json
"verification_tag": "hit|miss|neutral|insufficient"
```

不要用它们调整策略。

---

## 十三、统一聚合逻辑

range 和 daily 都应复用同一套聚合函数，例如：

```python
def aggregate_metrics(records, group_key=None):
    ...
```

聚合仍然按：

```text
overall
by_strategy
by_layer
by_risk_level
```

不要为 daily 模式单独写另一套聚合算法。

---

## 十四、不写数据库

本轮不要新增表，不要写数据库。

原因：

```text
先把 range / daily 两种评价模式的口径稳定下来。
等评价入口和指标口径稳定后，再做 --save-db 落库。
```

禁止：

```text
写 stock_signal
写 signal_performance
新增 evaluation 表
更新任何数据库记录
```

---

## 十五、行情数据说明

当前评价行情仍然使用现有：

```text
get_stock_history
```

本轮不要新增行情缓存表。

但是 JSON 和 Markdown 里需要明确写：

```text
行情来源：get_stock_history 临时获取。
评价结果依赖当前行情接口可用性。
price_fetch_failed 会影响覆盖率。
```

这样避免误以为结果已经完全可复现。

---

## 十六、验收命令

执行：

```bash
python -m compileall analysis
```

range 模式：

```bash
python -m analysis.watchlist_evaluation --start 20260501 --end 20260531
python -m analysis.watchlist_evaluation --mode range --start 20260501 --end 20260531
```

daily 模式：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529
```

检查输出：

```bash
ls -lh reports/evaluation/
```

重点确认：

```text
1. 不传 --mode 的旧 range 命令仍可用；
2. --mode range 可用；
3. --mode daily 可用；
4. daily 输出 daily_watchlist_evaluation_SIGNALDATE_ASOFDATE 文件；
5. range 输出 watchlist_evaluation_START_END 文件；
6. details 中有 signal_key；
7. JSON 中有 overall / by_strategy / by_layer / by_risk_level；
8. Markdown 有 T+1 验证报告；
9. 不写数据库。
```

最后检查：

```bash
git diff --stat
git status --short --untracked-files=all
```

---

## 十七、预期 diff

理想 diff：

```text
analysis/watchlist_evaluation.py
```

可选：

```text
docs/V4-EVALUATION.md
```

不应该出现：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
entrypoint.sh
data/config.py
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十八、提交要求

如果验收通过：

```bash
git add analysis/watchlist_evaluation.py
git commit -m "chore: add daily mode to watchlist evaluation"
```

如果新增文档：

```bash
git add docs/V4-EVALUATION.md
git commit -m "docs: update watchlist evaluation modes"
```

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
```

---

## 十九、本轮通过标准

1. 不新增 `daily_verification.py`；
2. `watchlist_evaluation.py` 是唯一评价入口；
3. 原 range 模式继续可用；
4. 新 daily 模式可用；
5. daily 模式复用同一套单条信号评价函数；
6. daily 模式复用同一套聚合函数；
7. details 有稳定 `signal_key`；
8. JSON/Markdown 明确行情来源；
9. 不写数据库；
10. 不改 selector；
11. 不改日报；
12. 不提交运行产物。


# V4-Evaluation 第 3 轮 hotfix：修复 daily 模式 T+1 成熟度与行情取数

## 当前问题

`watchlist_evaluation.py` 新增 daily 模式后，运行：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529

生成报告：

reports/evaluation/daily_watchlist_evaluation_20260528_20260529.md

报告结果异常：

样本数: 85
1 日可评价样本数: 2
1 日实际评价样本数: 2
insufficient: 83
not_mature_1d: 79
price_fetch_failed: 4

但 20260528 -> 20260529 是 T+1 验证场景，理论上大多数样本应该可以计算 1 日表现。
因此当前 daily 模式的成熟度判断或行情取数逻辑存在 bug。

本轮只修 analysis/watchlist_evaluation.py，不要新增功能。

一、本轮目标

只修以下问题：

daily 模式下 T+1 成熟度判断；
as_of_date 边界是否包含验证日；
get_stock_history 返回数据的日期匹配；
股票代码格式导致行情取数失败的问题；
1d 和 3d 成熟度必须独立判断。

不要做：

新增数据库落库
新增 weekly/monthly
新增 daily_verification.py
修改 selector
修改日报
修改 email
修改 pipeline
二、允许修改文件

只允许修改：

analysis/watchlist_evaluation.py

可选修改：

docs/V4-EVALUATION.md
三、禁止修改文件

禁止修改：

analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
entrypoint.sh
data/config.py
四、必须检查的问题
1. 1d 成熟度不能依赖 3d

如果 as_of_date 已经覆盖入选后的第一个交易日，则：

is_mature_1d = True

即使 3 日还不成熟，也应该能算 1d。

不要因为缺 next_3d_return 就把整条记录标成 insufficient。

2. as_of_date 应该包含当天

daily 模式：

--signal-date 20260528 --as-of 20260529

应该允许使用 20260529 的日线数据。

检查价格窗口筛选是否错误使用了：

date < as_of_date

如果是，需要改成：

date <= as_of_date

或者明确包含验证日。

3. 行情窗口必须包含 signal_date 和 as_of_date

对每只股票，调试输出中至少能知道：

code
signal_date
as_of_date
price_dates
entry_close 是否存在
as_of_close 是否存在
missing_reason

可以在 details 中增加：

"price_dates": ["20260528", "20260529"],
"entry_close_found": true,
"as_of_close_found": true

如果担心 JSON 太大，只在 missing 的记录里输出 debug 字段。

4. 股票代码格式检查

确认 get_stock_history 需要的 code 格式。

如果 stock_signal.code 是：

000001
600000

但行情函数需要：

sz000001
sh600000

则必须统一处理。

不要因为代码格式问题导致大部分 price_fetch_failed 或 not_mature_1d。

5. missing_reason 要更准确

当前 not_mature_1d=79 很可能误判。
修复后缺失原因应更具体：

entry_date_not_found
as_of_date_not_found
price_fetch_failed
insufficient_future_days_for_3d
not_mature_3d
invalid_code

不要把行情日期匹配失败误写成 not_mature_1d。

五、验收命令

执行：

python -m compileall analysis
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529

检查输出：

cat reports/evaluation/daily_watchlist_evaluation_20260528_20260529.json
cat reports/evaluation/daily_watchlist_evaluation_20260528_20260529.md

验收标准：

1. 样本数仍约 85；
2. evaluated_1d 不应只有 2；
3. not_mature_1d 不应大面积出现；
4. 1d 和 3d 缺失原因分开；
5. 如果仍有大量缺失，必须能在 missing_reasons 中看出真实原因，比如 as_of_date_not_found 或 price_fetch_failed；
6. daily Markdown 仍能正常生成；
7. range 模式仍能正常运行。

再跑 range 模式：

python -m analysis.watchlist_evaluation --start 20260501 --end 20260531
六、Git 要求

不要提交运行产物：

reports/evaluation/
reports/daily/
__pycache__/
.claude/

本轮理想 diff：

analysis/watchlist_evaluation.py

提交前执行：

git diff --stat
git status --short --untracked-files=all

如果验收通过：

git add analysis/watchlist_evaluation.py
git commit -m "fix: correct daily watchlist evaluation maturity"

---

## 你的当前工作区处理建议

现在先别提交 `analysis/watchlist_evaluation.py`。先删掉或忽略运行产物：

```bash
git status --short --untracked-files=all

确认不要 add：

reports/evaluation/*.json
reports/evaluation/*.md

如果你要保留报告本地看，可以不删，但不要 git add reports/。

另外 PRDs/V3-Pmerge.md -> PRDs/V4-Evaluation.md 这个 rename/modify 是文档变更，建议和代码分开提交，等 watchlist_evaluation.py 修完后再处理。

# V4-Evaluation 第 4 轮：评价诊断层与分层有效性检查

## 当前项目背景

项目：`testStock`

当前阶段：

> V4-Evaluation：评价数据可信性建设

当前已完成：

1. `analysis/watchlist_evaluation.py` 已成为观察池评价入口；
2. 支持区间评价模式；
3. 支持每日 T+1 验证模式；
4. 已修复 `get_stock_history` 缓存导致 5 月下旬行情不更新的问题；
5. daily 模式 `20260528 -> 20260529` 验证结果已从：

   * `evaluated_1d = 2`
   * `coverage_1d = 2.4%`

   修复为：

   * `evaluated_1d = 81`
   * `coverage_1d = 95.3%`
6. 当前评价系统已经能较可靠地完成 T+1 验证。

但是最新 daily 报告暴露出一个新的评价问题：

```text
20260528 -> 20260529 daily 验证中：

总体：
- 样本数 85
- 有效 1d：81
- 平均次日收益：-1.39%
- 次日胜率：24.69%

按分层：
- 回避 / 高风险：平均 +2.46%，胜率 64.29%
- 观察：平均 -2.84%，胜率 13.64%
- 谨慎：平均 -1.88%，胜率 17.78%

按策略：
- 板块联动：平均 -3.99%，胜率 0%
- 短线强势：平均 -2.55%，胜率 25%
```

这说明当前 evaluation 已经不只是“能不能算”，而是需要开始自动识别：

```text
分层是否倒挂？
高风险池是否反而表现更强？
某些策略是否明显拖累？
当前结论是否只能作为单日观察？
```

本轮目标：

> 在 `watchlist_evaluation.py` 中增加评价诊断层，让系统自动识别异常，而不是靠人工看表。

---

## 一、本轮核心原则

本轮只做评价诊断，不做策略优化。

禁止做：

```text
修改 selector
修改策略阈值
新增策略
删除策略
修改日报
修改邮件
修改 pipeline
写数据库
新增 daily_verification.py
新增 weekly/monthly 模式
```

当前仍然处于：

```text
数据可信性建设 + 评价口径收敛
```

不是策略调参阶段。

---

## 二、本轮目标

本轮只修改 `analysis/watchlist_evaluation.py`，实现：

1. 增加 `diagnostics` 诊断字段；
2. 增加分层有效性诊断；
3. 增加高风险提示有效性诊断；
4. 增加策略弱表现诊断；
5. 增加结论等级；
6. Markdown 增加“评价诊断”章节；
7. JSON 输出机器可读诊断结果；
8. 保持 range / daily 两种模式可用；
9. 不写数据库；
10. 不改任何业务链路。

---

## 三、允许修改文件

只允许修改：

```text
analysis/watchlist_evaluation.py
```

可选修改：

```text
docs/V4-EVALUATION.md
```

---

## 四、禁止修改文件

禁止修改：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_mapping_quality.py
analysis/board_trend_tracker.py
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
entrypoint.sh
data/config.py
```

---

## 五、JSON 新增 diagnostics 字段

在评价结果 JSON 顶层新增：

```json
"diagnostics": {
  "confidence_level": "insufficient_data|daily_observation|preliminary_pattern|actionable_review",
  "conclusion_level": "observe_only|preliminary|review_required",
  "data_quality": {
    "coverage_1d": 0.953,
    "coverage_3d": 0.037,
    "evaluated_1d": 81,
    "evaluated_3d": 14,
    "price_fetch_failed": 4
  },
  "layer_diagnostics": {
    "layer_inversion_warning": true,
    "message": "...",
    "details": {}
  },
  "risk_diagnostics": {
    "high_risk_hit_rate": 0.35,
    "risk_warning": true,
    "message": "..."
  },
  "strategy_diagnostics": {
    "underperforming_strategies": [],
    "outperforming_strategies": [],
    "warnings": []
  },
  "diagnostic_messages": []
}
```

如果某些字段暂时无法计算，允许为 `null` 或空列表，但结构必须稳定。

---

## 六、诊断 1：confidence_level

增加评价置信等级。

建议规则：

```text
如果 evaluated_1d < 20 或 coverage_1d < 0.3：
    confidence_level = "insufficient_data"

否则如果 mode = daily：
    confidence_level = "daily_observation"

否则如果 evaluated_3d >= 30 且 coverage_3d >= 0.3：
    confidence_level = "preliminary_pattern"

否则如果 evaluated_3d >= 100 且 coverage_3d >= 0.6：
    confidence_level = "actionable_review"

其他：
    confidence_level = "insufficient_data"
```

注意：

```text
daily 模式即使 coverage_1d 很高，也只能是 daily_observation。
不能因为单日表现就给 actionable_review。
```

---

## 七、诊断 2：conclusion_level

根据 `confidence_level` 生成结论等级：

```text
insufficient_data:
    conclusion_level = "observe_only"

daily_observation:
    conclusion_level = "observe_only"

preliminary_pattern:
    conclusion_level = "preliminary"

actionable_review:
    conclusion_level = "review_required"
```

解释：

```text
observe_only：只观察，不调策略
preliminary：可作为初步模式观察
review_required：样本足够，可进入策略复盘讨论
```

---

## 八、诊断 3：分层有效性诊断

目标：检查观察池分层是否符合预期。

理想情况下：

```text
观察层表现 >= 谨慎层表现 >= 高风险 / 回避层表现
```

但当前报告出现：

```text
回避 / 高风险表现明显强于观察和谨慎
```

所以需要新增 `layer_inversion_warning`。

### 推荐规则

从 `by_layer` 中读取：

```text
观察
谨慎
高风险 / 回避
```

兼容字段名：

```text
观察 / 可观察
谨慎 / 谨慎观察
高风险 / 高风险复盘
回避
```

如果存在以下情况：

```text
高风险或回避层 avg_next_1d_return > 观察层 avg_next_1d_return + 0.01
并且
高风险或回避层 win_rate_1d > 观察层 win_rate_1d
并且
双方 evaluated_1d_count >= 5
```

则：

```json
"layer_inversion_warning": true
```

并输出 message：

```text
出现分层倒挂：高风险/回避层 T+1 表现优于观察层。当前仅作单日/区间观察，不建议单次结果直接调参。
```

如果样本不足：

```json
"layer_inversion_warning": false
"message": "分层样本不足，暂不判断分层有效性。"
```

---

## 九、诊断 4：高风险提示有效性诊断

目标：判断高风险池是否真的体现更高风险。

定义：

```text
high_risk_hit_rate =
高风险/回避样本中
next_1d_return < 0 或 max_3d_drawdown < -0.03
的比例
```

如果只有 1d 数据，没有 3d drawdown，则先用：

```text
next_1d_return < 0
```

第一版规则：

```text
如果高风险/回避 evaluated_1d_count >= 5：

    high_risk_hit_rate = 下跌样本数 / evaluated_1d_count

    如果 high_risk_hit_rate < 0.4 且 avg_next_1d_return > 0：
        risk_warning = true
        message = "高风险提示当日未明显兑现，需连续观察是否过度保守。"
    否则：
        risk_warning = false
```

注意：

```text
不要因为单日高风险池上涨就说风险规则失效。
只提示“需连续观察”。
```

---

## 十、诊断 5：策略弱表现诊断

目标：识别单日或区间中明显弱于整体的策略。

从 `by_strategy` 中读取每个策略表现。

规则：

```text
如果 strategy.evaluated_1d_count >= 10
且 strategy.avg_next_1d_return < overall.avg_next_1d_return - 0.015
则加入 underperforming_strategies
```

输出示例：

```json
"underperforming_strategies": [
  {
    "strategy": "板块联动",
    "evaluated_1d_count": 15,
    "avg_next_1d_return": -0.0399,
    "overall_avg_next_1d_return": -0.0139,
    "message": "板块联动当日表现弱于整体，需连续观察。"
  }
]
```

如果策略明显强于整体，也可以输出：

```text
outperforming_strategies
```

规则：

```text
evaluated_1d_count >= 10
且 avg_next_1d_return > overall.avg_next_1d_return + 0.015
```

但 Markdown 中要强调：

```text
单日结果不作为策略调整依据。
```

---

## 十一、诊断 6：数据质量诊断

基于 summary 输出：

```json
"data_quality": {
  "coverage_1d": ...,
  "coverage_3d": ...,
  "evaluated_1d": ...,
  "evaluated_3d": ...,
  "price_fetch_failed": ...,
  "missing_reasons": {}
}
```

如果：

```text
coverage_1d < 0.8
```

输出 warning：

```text
1 日覆盖率不足，T+1 结果不稳定。
```

如果：

```text
price_fetch_failed > 0
```

输出 warning：

```text
仍有行情获取失败样本，需关注数据源稳定性。
```

---

## 十二、Markdown 新增“评价诊断”章节

在 Markdown 报告中新增一节，建议放在“初步结论”之前：

```markdown
## 8. 评价诊断

### 8.1 数据质量

- 1 日覆盖率：
- 3 日覆盖率：
- 行情缺失数量：
- 置信等级：

### 8.2 分层有效性

- 是否出现分层倒挂：
- 诊断说明：

### 8.3 高风险提示有效性

- 高风险提示命中率：
- 诊断说明：

### 8.4 策略表现异常

- 弱表现策略：
- 强表现策略：
- 说明：
```

原来的“初步结论”顺延到后面。

---

## 十三、初步结论生成规则

根据 diagnostics 自动生成结论。

### insufficient_data

```text
样本覆盖不足，仅做数据跟踪，不做策略优劣判断。
```

### daily_observation

```text
本次 T+1 验证覆盖率较高，可用于单日复盘观察。但单日结果不作为策略调整依据。
```

如果有分层倒挂：

```text
本次出现分层倒挂现象，需连续观察是否为偶发市场风格切换。
```

### preliminary_pattern

```text
样本已具备初步观察价值，可用于形成策略复盘线索，但仍不建议直接自动调参。
```

### actionable_review

```text
样本覆盖度和数量较高，可进入人工策略复盘阶段。
```

---

## 十四、range / daily 兼容要求

本轮修改后，以下命令必须都可用：

```bash
python -m analysis.watchlist_evaluation --start 20260501 --end 20260531
python -m analysis.watchlist_evaluation --mode range --start 20260501 --end 20260531
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529
```

range 和 daily 都要输出 diagnostics。

如果某些 daily 专属字段在 range 中不适用，可以为空，但不要报错。

---

## 十五、验收命令

执行：

```bash
python -m compileall analysis
```

daily 模式：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529
```

range 模式：

```bash
python -m analysis.watchlist_evaluation --mode range --start 20260501 --end 20260531
```

检查输出：

```bash
cat reports/evaluation/daily_watchlist_evaluation_20260528_20260529.json
cat reports/evaluation/daily_watchlist_evaluation_20260528_20260529.md
```

重点确认：

```text
1. JSON 顶层有 diagnostics；
2. diagnostics 中有 confidence_level；
3. diagnostics 中有 layer_diagnostics；
4. diagnostics 中有 risk_diagnostics；
5. diagnostics 中有 strategy_diagnostics；
6. Markdown 中有“评价诊断”章节；
7. 当前 20260528 -> 20260529 应能识别出分层倒挂 warning；
8. 当前结果不得建议直接调策略；
9. range 模式仍然可用。
```

最后检查 Git：

```bash
git diff --stat
git status --short --untracked-files=all
```

---

## 十六、预期 diff

理想 diff：

```text
analysis/watchlist_evaluation.py
```

可选：

```text
docs/V4-EVALUATION.md
```

不应该出现：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
entrypoint.sh
data/config.py
reports/
__pycache__/
.claude/
PRDs/
```

运行产物不要提交：

```text
reports/evaluation/*.json
reports/evaluation/*.md
```

---

## 十七、提交要求

如果验收通过：

```bash
git add analysis/watchlist_evaluation.py
git commit -m "chore: add diagnostics to watchlist evaluation"
```

如果新增或修改文档：

```bash
git add docs/V4-EVALUATION.md
git commit -m "docs: update watchlist evaluation diagnostics"
```

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
```

---

## 十八、本轮通过标准

1. `watchlist_evaluation.py` 增加 diagnostics；
2. daily 和 range 模式都能输出 diagnostics；
3. 能识别分层倒挂；
4. 能识别高风险提示未兑现；
5. 能识别策略弱表现；
6. Markdown 有评价诊断章节；
7. 结论不建议单日调策略；
8. 不写数据库；
9. 不改 selector；
10. 不改日报；
11. 不提交运行产物。


# V4-Evaluation 第 5 轮：评价结果落库与可追踪

## 当前项目背景

项目：`testStock`

当前阶段：

> V4-Evaluation：评价数据可信性建设

当前已完成：

1. `analysis/watchlist_evaluation.py` 已成为统一评价入口；
2. 支持 `range` 区间评价模式；
3. 支持 `daily` 每日 T+1 验证模式；
4. 已修复 `get_stock_history` 缓存导致 5 月下旬行情不更新的问题；
5. daily 模式 `20260528 -> 20260529` 已能覆盖 81/85 条信号；
6. 已新增 `diagnostics` 诊断层：

   * `confidence_level`
   * `conclusion_level`
   * 分层倒挂诊断
   * 高风险提示有效性诊断
   * 策略弱表现诊断
   * 数据质量诊断
7. range / daily 模式均能输出 JSON + Markdown；
8. 当前仍然只输出文件，评价结果没有形成可追踪数据库记录。

本轮目标：

> 将 watchlist_evaluation 的评价结果写入 evaluation 专用表，形成可追踪的评价数据链路。

注意：本轮不是策略优化，不改 selector，不改日报，不改观察池生成逻辑。

---

## 一、本轮核心原则

只允许新增 / 修改 evaluation 相关落库逻辑。

禁止写回：

```text
stock_signal
signal_performance
daily_report
trade_plan
selector
```

评价结果只能写入新建的 evaluation 专用表：

```text
watchlist_evaluation_result
watchlist_evaluation_summary
```

---

## 二、本轮目标

本轮做以下事情：

1. 新增 evaluation 专用表；
2. `watchlist_evaluation.py` 增加 `--save-db` 参数；
3. 默认不写数据库；
4. 只有显式传 `--save-db` 才落库；
5. daily / range 两种模式都支持落库；
6. 使用 upsert，重复运行不会重复插入；
7. 明细表保存每条 signal 的评价结果；
8. summary 表保存每次评价任务的汇总结果；
9. 不改 selector；
10. 不改日报；
11. 不改邮件；
12. 不改 pipeline。

---

## 三、允许修改文件

允许修改：

```text
analysis/watchlist_evaluation.py
analysis/init_db.py
```

可选修改或新增文档：

```text
docs/V4-EVALUATION.md
```

---

## 四、禁止修改文件

禁止修改：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_mapping_quality.py
analysis/board_trend_tracker.py
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
entrypoint.sh
data/config.py
```

---

## 五、新增表 1：watchlist_evaluation_result

在 `analysis/init_db.py` 中新增表：

```sql
CREATE TABLE IF NOT EXISTS watchlist_evaluation_result (
    id SERIAL PRIMARY KEY,

    eval_mode TEXT NOT NULL,
    eval_start_date TEXT,
    eval_end_date TEXT,
    signal_trade_date TEXT NOT NULL,
    as_of_date TEXT,

    signal_key TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    strategy TEXT,
    watchlist_layer TEXT,
    risk_level TEXT,
    action_signal TEXT,

    entry_close NUMERIC,
    next_1d_return NUMERIC,
    next_3d_return NUMERIC,
    max_3d_return NUMERIC,
    max_3d_drawdown NUMERIC,

    is_mature_1d BOOLEAN,
    is_mature_3d BOOLEAN,
    price_status TEXT,
    missing_reason TEXT,
    verification_tag TEXT,

    confidence_level TEXT,
    conclusion_level TEXT,

    data_source TEXT DEFAULT 'get_stock_history',
    evaluated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE (eval_mode, signal_key, as_of_date)
);
```

说明：

* `eval_mode`：`range` 或 `daily`
* `signal_key`：由 `watchlist_evaluation.py` 统一生成
* `as_of_date`：评价基准日
* `UNIQUE (eval_mode, signal_key, as_of_date)` 防止重复跑重复写入

如果 `as_of_date` 为空，落库前必须填充为当前评价基准日，不允许写 null。

---

## 六、新增表 2：watchlist_evaluation_summary

在 `analysis/init_db.py` 中新增表：

```sql
CREATE TABLE IF NOT EXISTS watchlist_evaluation_summary (
    id SERIAL PRIMARY KEY,

    eval_mode TEXT NOT NULL,
    eval_start_date TEXT,
    eval_end_date TEXT,
    signal_date TEXT,
    as_of_date TEXT NOT NULL,

    total_signals INTEGER,
    eligible_1d INTEGER,
    evaluated_1d INTEGER,
    eligible_3d INTEGER,
    evaluated_3d INTEGER,
    coverage_1d NUMERIC,
    coverage_3d NUMERIC,
    price_fetch_failed INTEGER,

    avg_next_1d_return NUMERIC,
    win_rate_1d NUMERIC,
    avg_next_3d_return NUMERIC,
    win_rate_3d NUMERIC,
    avg_max_3d_return NUMERIC,
    avg_max_3d_drawdown NUMERIC,

    confidence_level TEXT,
    conclusion_level TEXT,

    layer_inversion_warning BOOLEAN,
    risk_warning BOOLEAN,

    diagnostics_json JSONB,
    summary_json JSONB,

    generated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE (eval_mode, eval_start_date, eval_end_date, signal_date, as_of_date)
);
```

说明：

* summary 表用于追踪每天 / 每段区间的评价覆盖率和诊断趋势；
* `diagnostics_json` 保存完整 diagnostics；
* `summary_json` 保存完整 summary；
* weekly/monthly 后续可以基于这个表汇总。

---

## 七、watchlist_evaluation.py 参数改造

新增参数：

```bash
--save-db
```

默认：

```text
不写数据库
```

只有显式传入：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529 --save-db
```

才写入 evaluation 表。

原有命令必须继续只输出文件：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529
python -m analysis.watchlist_evaluation --mode range --start 20260501 --end 20260531
```

---

## 八、落库函数设计

在 `watchlist_evaluation.py` 中增加：

```python
def save_evaluation_to_db(result: dict) -> None:
    ...
```

或拆分为：

```python
def save_evaluation_summary(conn, result: dict) -> None:
    ...

def save_evaluation_details(conn, result: dict) -> None:
    ...
```

要求：

1. 使用 `DATABASE_DSN`；
2. 数据库连接失败时打印错误并退出，不影响 JSON/Markdown 输出；
3. 使用 transaction；
4. summary 和 details 任一步失败，整体 rollback；
5. 成功后 commit；
6. 使用 upsert；
7. 不写入 `stock_signal`；
8. 不写入 `signal_performance`。

---

## 九、upsert 要求

### result 明细 upsert

使用：

```sql
INSERT INTO watchlist_evaluation_result (...)
VALUES (...)
ON CONFLICT (eval_mode, signal_key, as_of_date)
DO UPDATE SET
    entry_close = EXCLUDED.entry_close,
    next_1d_return = EXCLUDED.next_1d_return,
    next_3d_return = EXCLUDED.next_3d_return,
    max_3d_return = EXCLUDED.max_3d_return,
    max_3d_drawdown = EXCLUDED.max_3d_drawdown,
    is_mature_1d = EXCLUDED.is_mature_1d,
    is_mature_3d = EXCLUDED.is_mature_3d,
    price_status = EXCLUDED.price_status,
    missing_reason = EXCLUDED.missing_reason,
    verification_tag = EXCLUDED.verification_tag,
    confidence_level = EXCLUDED.confidence_level,
    conclusion_level = EXCLUDED.conclusion_level,
    evaluated_at = NOW();
```

### summary upsert

使用：

```sql
INSERT INTO watchlist_evaluation_summary (...)
VALUES (...)
ON CONFLICT (eval_mode, eval_start_date, eval_end_date, signal_date, as_of_date)
DO UPDATE SET
    total_signals = EXCLUDED.total_signals,
    eligible_1d = EXCLUDED.eligible_1d,
    evaluated_1d = EXCLUDED.evaluated_1d,
    eligible_3d = EXCLUDED.eligible_3d,
    evaluated_3d = EXCLUDED.evaluated_3d,
    coverage_1d = EXCLUDED.coverage_1d,
    coverage_3d = EXCLUDED.coverage_3d,
    price_fetch_failed = EXCLUDED.price_fetch_failed,
    avg_next_1d_return = EXCLUDED.avg_next_1d_return,
    win_rate_1d = EXCLUDED.win_rate_1d,
    avg_next_3d_return = EXCLUDED.avg_next_3d_return,
    win_rate_3d = EXCLUDED.win_rate_3d,
    avg_max_3d_return = EXCLUDED.avg_max_3d_return,
    avg_max_3d_drawdown = EXCLUDED.avg_max_3d_drawdown,
    confidence_level = EXCLUDED.confidence_level,
    conclusion_level = EXCLUDED.conclusion_level,
    layer_inversion_warning = EXCLUDED.layer_inversion_warning,
    risk_warning = EXCLUDED.risk_warning,
    diagnostics_json = EXCLUDED.diagnostics_json,
    summary_json = EXCLUDED.summary_json,
    generated_at = NOW();
```

---

## 十、result dict 要求

落库前，`watchlist_evaluation.py` 的 result 顶层应包含足够信息：

```json
{
  "mode": "daily",
  "start_date": null,
  "end_date": null,
  "signal_date": "20260528",
  "as_of_date": "20260529",
  "summary": {},
  "overall": {},
  "by_strategy": {},
  "by_layer": {},
  "by_risk_level": {},
  "diagnostics": {},
  "details": []
}
```

range 模式：

```json
{
  "mode": "range",
  "start_date": "20260501",
  "end_date": "20260531",
  "signal_date": null,
  "as_of_date": "20260602",
  ...
}
```

如果当前字段名不同，可以小范围补齐，但不要破坏现有 JSON 输出。

---

## 十一、details 字段要求

每条 detail 至少包含：

```json
{
  "signal_key": "...",
  "trade_date": "20260528",
  "code": "600000",
  "name": "...",
  "strategy": "...",
  "watchlist_layer": "...",
  "risk_level": "...",
  "action_signal": "...",
  "entry_close": 10.23,
  "next_1d_return": 0.012,
  "next_3d_return": null,
  "max_3d_return": null,
  "max_3d_drawdown": null,
  "is_mature_1d": true,
  "is_mature_3d": false,
  "price_status": "ok",
  "missing_reason": "insufficient_future_days_for_3d",
  "verification_tag": "hit"
}
```

如果某字段缺失，写 `None`，不要崩溃。

---

## 十二、初始化流程

修改 `analysis/init_db.py` 后，验收时需要执行：

```bash
python -m analysis.init_db
```

确保新表创建成功。

不要改已有表结构，不要 drop 表。

---

## 十三、安全要求

1. 默认不写数据库；
2. 只有 `--save-db` 才写；
3. 只写 evaluation 专用表；
4. 不写 `stock_signal`；
5. 不写 `signal_performance`;
6. 不删除任何数据；
7. 重复运行同一命令不会重复插入；
8. 数据库失败不影响 JSON/Markdown 输出；
9. 不修改业务链路。

---

## 十四、验收命令

执行：

```bash
python -m compileall analysis
python -m analysis.init_db
```

daily 模式不落库：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529
```

daily 模式落库：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529 --save-db
```

range 模式落库：

```bash
python -m analysis.watchlist_evaluation --mode range --start 20260501 --end 20260531 --save-db
```

重复运行一次 daily 落库：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529 --save-db
```

确认不会重复插入。

---

## 十五、数据库验收 SQL

执行：

```sql
SELECT COUNT(*)
FROM watchlist_evaluation_result
WHERE eval_mode = 'daily'
  AND signal_trade_date = '20260528'
  AND as_of_date = '20260529';
```

预期：

```text
约等于该 daily 模式 details 数量，例如 85
```

执行：

```sql
SELECT eval_mode, signal_date, as_of_date, total_signals, evaluated_1d, coverage_1d,
       confidence_level, conclusion_level, layer_inversion_warning, risk_warning
FROM watchlist_evaluation_summary
ORDER BY generated_at DESC
LIMIT 5;
```

预期能看到 daily / range 的 summary 记录。

重复运行后：

```sql
SELECT eval_mode, signal_key, as_of_date, COUNT(*)
FROM watchlist_evaluation_result
GROUP BY eval_mode, signal_key, as_of_date
HAVING COUNT(*) > 1;
```

预期：

```text
0 行
```

---

## 十六、输出文件要求

保留现有 JSON / Markdown 输出，不因为 `--save-db` 改变文件输出。

输出仍在：

```text
reports/evaluation/
```

不要写入：

```text
reports/daily/
```

运行产物不要提交。

---

## 十七、预期 diff

理想 diff：

```text
analysis/watchlist_evaluation.py
analysis/init_db.py
```

可选：

```text
docs/V4-EVALUATION.md
```

不应该出现：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
entrypoint.sh
data/config.py
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十八、提交要求

如果验收通过：

```bash
git add analysis/watchlist_evaluation.py analysis/init_db.py
git commit -m "feat: persist watchlist evaluation results"
```

如果新增或修改文档：

```bash
git add docs/V4-EVALUATION.md
git commit -m "docs: add watchlist evaluation persistence notes"
```

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
```

---

## 十九、本轮通过标准

1. 新增 evaluation 专用表；
2. `--save-db` 可用；
3. 默认不写数据库；
4. daily 模式可落库；
5. range 模式可落库；
6. 重复运行不重复插入；
7. summary 表可追踪 coverage / diagnostics；
8. result 表保存每条 signal 评价结果；
9. 不写回 stock_signal；
10. 不写回 signal_performance；
11. 不改 selector；
12. 不改日报；
13. 不提交运行产物。


# V4-Evaluation 5.1 Hotfix：as_of 边界修复与 evaluation 唯一键收敛

## 当前问题

第 5 轮已完成 evaluation 落库：

* 新增 `watchlist_evaluation_result`
* 新增 `watchlist_evaluation_summary`
* `watchlist_evaluation.py` 支持 `--save-db`
* daily / range 模式可落库
* 默认不写库，显式 `--save-db` 才写库

但 review 发现两个需要在第 6 轮前修复的问题。

---

## 一、问题 1：as_of_date 没有真正参与行情窗口截断

当前 `watchlist_evaluation.py` 中：

```python
def evaluate_signal_performance(signal):
    ...
    future_mask = all_dates > trade_date
    future = hist[future_mask].sort_values("date")
```

问题：

`as_of_date` 只是写入 result / DB，没有传入 `evaluate_signal_performance()`。

这会导致：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529
```

在未来重新运行时，可能使用 20260529 之后的行情，形成未来函数。

本轮必须修复。

---

## 二、问题 2：watchlist_evaluation_result 唯一键过粗

当前明细表唯一键：

```sql
UNIQUE (eval_mode, signal_key, as_of_date)
```

对 daily 模式基本够用，但对 range 模式可能不够。

例如两个区间：

```bash
--mode range --start 20260501 --end 20260531 --as-of 20260603
--mode range --start 20260515 --end 20260531 --as-of 20260603
```

同一个 `signal_key` 会冲突，后一个区间会覆盖前一个区间明细。

本轮建议将明细表唯一键收敛为：

```sql
UNIQUE (
  eval_mode,
  eval_start_date,
  eval_end_date,
  signal_trade_date,
  signal_key,
  as_of_date
)
```

daily 模式中 `eval_start_date / eval_end_date` 可为空字符串，`signal_trade_date` 为 signal_date。

---

## 三、本轮目标

只做 hotfix：

1. `evaluate_signal_performance()` 增加 `as_of_date` 参数；
2. 行情窗口必须限制为 `trade_date < date <= as_of_date`；
3. `evaluate_records()` 接收并传递 `as_of_date`；
4. range / daily 模式都使用相同 as_of 边界；
5. 修正 result 表唯一键；
6. 修正 upsert conflict key；
7. 不改 selector；
8. 不改日报；
9. 不改 email；
10. 不新增模式；
11. 不做 weekly/monthly；
12. 不做查询脚本。

---

## 四、允许修改文件

允许修改：

```text
analysis/watchlist_evaluation.py
sql/schema.sql
```

可选修改：

```text
analysis/init_db.py
```

仅当需要验证新约束或兼容初始化时修改。

---

## 五、禁止修改文件

禁止修改：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
entrypoint.sh
data/config.py
```

---

## 六、修复 as_of_date 边界

### 1. 修改函数签名

将：

```python
def evaluate_signal_performance(signal):
```

改为：

```python
def evaluate_signal_performance(signal, as_of_date=None):
```

### 2. 限制行情窗口

当前逻辑：

```python
future_mask = all_dates > trade_date
```

改为：

```python
if as_of_date:
    future_mask = (all_dates > trade_date) & (all_dates <= as_of_date)
else:
    future_mask = all_dates > trade_date
```

注意：

`as_of_date` 必须使用 `YYYYMMDD` 格式。

### 3. 刷新缓存后也要用相同边界

days=500 刷新后，也必须重新使用：

```python
(all_dates > trade_date) & (all_dates <= as_of_date)
```

不要刷新后忘记 as_of 边界。

### 4. 修改 evaluate_records

将：

```python
def evaluate_records(signals):
```

改为：

```python
def evaluate_records(signals, as_of_date=None):
```

内部调用：

```python
metrics, status = evaluate_signal_performance(sig, as_of_date=as_of_date)
```

### 5. main 中调用

daily 模式：

```python
evaluate_records(signals, as_of_date=as_of_date)
```

range 模式：

```python
evaluate_records(signals, as_of_date=as_of_date)
```

---

## 七、修复 status/debug 字段

对每条记录，建议在 debug 中加入：

```json
{
  "as_of_date": "20260529",
  "future_dates_used_last": "20260529",
  "future_dates_count": 1
}
```

这样后续能确认没有使用 as_of 之后的数据。

如果担心 JSON 太大，可以至少给缺失/异常记录输出。

---

## 八、修复 result 表唯一键

### 1. schema.sql

当前：

```sql
UNIQUE (eval_mode, signal_key, as_of_date)
```

改为：

```sql
UNIQUE (
    eval_mode,
    eval_start_date,
    eval_end_date,
    signal_trade_date,
    signal_key,
    as_of_date
)
```

### 2. 兼容已有数据库

如果表已存在，`CREATE TABLE IF NOT EXISTS` 不会更新旧唯一约束。

本轮需要在 schema.sql 中增加幂等迁移块：

```sql
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'watchlist_evaluation_result_eval_mode_signal_key_as_of_date_key'
    ) THEN
        ALTER TABLE watchlist_evaluation_result
        DROP CONSTRAINT watchlist_evaluation_result_eval_mode_signal_key_as_of_date_key;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_watchlist_eval_result_scope_signal'
    ) THEN
        ALTER TABLE watchlist_evaluation_result
        ADD CONSTRAINT uq_watchlist_eval_result_scope_signal
        UNIQUE (eval_mode, eval_start_date, eval_end_date, signal_trade_date, signal_key, as_of_date);
    END IF;
END $$;
```

注意：实际旧约束名可能不同，请先查或用安全判断。
如果不确定旧约束名，可以写查询 pg_constraint 的 DO block，按表名 + 约束定义判断。

### 3. upsert conflict key

将：

```sql
ON CONFLICT (eval_mode, signal_key, as_of_date)
```

改为：

```sql
ON CONFLICT (
    eval_mode,
    eval_start_date,
    eval_end_date,
    signal_trade_date,
    signal_key,
    as_of_date
)
```

---

## 九、验收命令

执行：

```bash
python -m compileall analysis
python -m analysis.init_db
```

daily 模式：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529 --save-db
```

重点检查：

1. `daily` 模式 3d 不应该使用 20260529 之后的数据；
2. `future_dates_count` 应约为 1；
3. `next_3d_return` 应为空；
4. `insufficient_future_days_for_3d` 应存在；
5. `evaluated_1d` 仍然较高；
6. 重复运行 `--save-db` 不产生重复。

range 模式：

```bash
python -m analysis.watchlist_evaluation --mode range --start 20260501 --end 20260531 --as-of 20260529
python -m analysis.watchlist_evaluation --mode range --start 20260515 --end 20260531 --as-of 20260529
```

确认两个不同区间可以共存，不互相覆盖明细。

---

## 十、数据库验收 SQL

确认没有重复：

```sql
SELECT eval_mode, eval_start_date, eval_end_date, signal_trade_date, signal_key, as_of_date, COUNT(*)
FROM watchlist_evaluation_result
GROUP BY eval_mode, eval_start_date, eval_end_date, signal_trade_date, signal_key, as_of_date
HAVING COUNT(*) > 1;
```

预期 0 行。

确认 daily 没有 3d 成熟误判：

```sql
SELECT COUNT(*)
FROM watchlist_evaluation_result
WHERE eval_mode = 'daily'
  AND signal_trade_date = '20260528'
  AND as_of_date = '20260529'
  AND is_mature_3d = true;
```

预期应为 0 或非常低，不能大面积为 true。

---

## 十一、预期 diff

理想 diff：

```text
analysis/watchlist_evaluation.py
sql/schema.sql
```

可选：

```text
analysis/init_db.py
```

不应该出现：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
entrypoint.sh
data/config.py
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十二、提交要求

如果验收通过：

```bash
git add analysis/watchlist_evaluation.py sql/schema.sql analysis/init_db.py
git commit -m "fix: enforce as-of boundary in watchlist evaluation"
```

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/
```

---

## 十三、本轮通过标准

1. `as_of_date` 真正限制行情窗口；
2. daily T+1 不再使用 as_of 之后的数据；
3. range 模式也遵守 as_of 边界；
4. result 表唯一键不会让不同 range 区间互相覆盖；
5. upsert 仍能防重复；
6. 不改业务链路；
7. 不改 selector；
8. 不改日报；
9. 不提交运行产物。

# V4-Evaluation 第 6 轮：评价结果查询与趋势追踪

## 当前项目背景

项目：`testStock`

当前阶段：

> V4-Evaluation：评价数据可信性建设

当前已完成：

1. `watchlist_evaluation.py` 已成为统一评价入口；
2. 支持 `range` 区间评价模式；
3. 支持 `daily` 每日 T+1 验证模式；
4. 支持 `diagnostics` 诊断层；
5. 支持 `--save-db` 落库；
6. 已新增 evaluation 专用表：

   * `watchlist_evaluation_result`
   * `watchlist_evaluation_summary`
7. 已修复 `as_of_date` 边界问题；
8. 已修复 result 表唯一键过粗问题；
9. daily T+1 验证不再使用未来数据。

当前评价数据已经可以落库。

本轮目标：

> 新增只读查询工具，用来查看 evaluation 表中的历史评价结果、覆盖率趋势、分层倒挂情况、风险警告、弱表现策略等。

本轮不做新的评价计算，不写数据库，不改策略。

---

## 一、本轮目标

本轮只做一个只读查询脚本：

```text
analysis/evaluation_query.py
```

目标：

1. 查询最近 evaluation summary；
2. 展示 daily / range 评价历史；
3. 展示 coverage_1d / coverage_3d 趋势；
4. 展示分层倒挂是否连续出现；
5. 展示风险警告是否连续出现；
6. 展示 price_fetch_failed 是否持续存在；
7. 展示 weak strategy / strong strategy；
8. 输出终端表格；
9. 可选输出 Markdown；
10. 不写数据库；
11. 不修改 evaluation 结果；
12. 不改 selector / daily_report / email / pipeline。

---

## 二、允许新增 / 修改文件

允许新增：

```text
analysis/evaluation_query.py
```

可选新增文档：

```text
docs/V4-EVALUATION.md
```

如果已有该文档，只能追加“查询工具说明”，不要写长篇迭代日志。

---

## 三、禁止修改文件

禁止修改：

```text
analysis/watchlist_evaluation.py
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
analysis/init_db.py
sql/schema.sql
entrypoint.sh
data/config.py
```

本轮不改评价计算，不改表结构，不改业务链路。

---

## 四、脚本命令设计

新增脚本：

```bash
python -m analysis.evaluation_query --latest
python -m analysis.evaluation_query --days 10
python -m analysis.evaluation_query --mode daily --days 10
python -m analysis.evaluation_query --mode range --days 30
```

可选：

```bash
python -m analysis.evaluation_query --days 10 --output-md
```

---

## 五、默认行为

如果不传参数：

```bash
python -m analysis.evaluation_query
```

默认等价于：

```bash
python -m analysis.evaluation_query --mode daily --days 10
```

也就是查看最近 10 天 daily 评价结果。

---

## 六、查询数据源

只读查询：

```text
watchlist_evaluation_summary
```

第一版不要查 `watchlist_evaluation_result` 明细表，除非需要补充 weak strategy 详情。

原因：

```text
第 6 轮目标是看趋势，不是分析单票明细。
```

---

## 七、输出字段

终端输出表格至少包含：

```text
generated_at
eval_mode
signal_date
as_of_date
eval_start_date
eval_end_date
total_signals
evaluated_1d
coverage_1d
evaluated_3d
coverage_3d
confidence_level
conclusion_level
layer_inversion_warning
risk_warning
price_fetch_failed
```

显示示例：

```text
日期        模式   信号日     as_of     总数  1d有效  1d覆盖  3d有效  3d覆盖  分层倒挂  风险警告  结论
20260529   daily  20260528  20260529  85    81      95.3%   0       0.0%    YES       YES      observe_only
```

---

## 八、diagnostics_json 解析

`watchlist_evaluation_summary` 中已有：

```text
diagnostics_json
summary_json
```

需要解析 `diagnostics_json`，提取：

```text
layer_inversion_warning
risk_warning
underperforming_strategies
outperforming_strategies
diagnostic_messages
```

终端简化显示：

```text
弱策略：板块联动
强策略：N字异动, 二次起爆
诊断：分层倒挂; 高风险提示未兑现
```

如果 JSON 解析失败，不要中断，显示 `N/A`。

---

## 九、趋势诊断

脚本输出表格后，增加一个简单趋势摘要：

```text
## 趋势摘要

- 最近 N 条评价记录：
- daily 记录数：
- 分层倒挂次数：
- 风险警告次数：
- 平均 coverage_1d：
- 平均 coverage_3d：
- price_fetch_failed 总数：
- 连续分层倒挂天数：
```

第一版规则：

```text
如果最近 3 条 daily 都 layer_inversion_warning = true：
    输出：连续分层倒挂，需重点观察，但不建议自动调参。

如果最近 3 条 daily 都 risk_warning = true：
    输出：高风险提示连续未兑现，需后续复盘风险分层逻辑。

如果 average coverage_1d < 0.8：
    输出：1 日覆盖率不足，评价数据仍不稳定。
```

注意：

```text
趋势摘要只提示，不做策略调整建议。
```

---

## 十、Markdown 输出

如果传：

```bash
python -m analysis.evaluation_query --days 10 --output-md
```

生成：

```text
reports/evaluation/evaluation_query_YYYYMMDD.md
```

Markdown 结构：

```markdown
# 观察池评价结果查询

## 1. 查询范围

## 2. 评价记录列表

## 3. 覆盖率趋势

## 4. 分层倒挂与风险警告

## 5. 策略表现提示

## 6. 趋势摘要

> 本查询基于 watchlist_evaluation_summary，只用于复盘评价系统是否稳定，不构成实盘买卖建议。
```

不要默认输出 Markdown，只有 `--output-md` 才输出。

---

## 十一、数据库连接

使用：

```python
from data.config import DATABASE_DSN
```

如果 `DATABASE_DSN` 缺失：

```text
[ERROR] DATABASE_DSN 未设置，无法查询 evaluation 表
```

正常退出。

如果表不存在：

```text
[ERROR] watchlist_evaluation_summary 表不存在，请先运行 python -m analysis.init_db
```

正常退出，不抛大异常。

---

## 十二、安全要求

1. 只读查询；
2. 不 insert；
3. 不 update；
4. 不 delete；
5. 不调用 watchlist_evaluation；
6. 不调用 get_stock_history；
7. 不调用 selector；
8. 不写 reports/daily；
9. 不发送邮件；
10. 不修改任何业务表。

---

## 十三、验收命令

执行：

```bash
python -m compileall analysis
python -m analysis.evaluation_query --latest
python -m analysis.evaluation_query --mode daily --days 10
python -m analysis.evaluation_query --mode range --days 30
python -m analysis.evaluation_query --mode daily --days 10 --output-md
```

检查：

```bash
ls -lh reports/evaluation/
git diff --stat
git status --short --untracked-files=all
```

验收重点：

```text
1. 能读取 watchlist_evaluation_summary；
2. 能显示最近记录；
3. 能显示 coverage_1d / coverage_3d；
4. 能显示 layer_inversion_warning / risk_warning；
5. 能解析 diagnostics_json 中的弱策略 / 强策略；
6. 趋势摘要不建议自动调策略；
7. 不写数据库；
8. 不改业务文件。
```

---

## 十四、预期 diff

理想 diff：

```text
analysis/evaluation_query.py
```

可选：

```text
docs/V4-EVALUATION.md
```

不应该出现：

```text
analysis/watchlist_evaluation.py
analysis/init_db.py
sql/schema.sql
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
entrypoint.sh
data/config.py
reports/
__pycache__/
.claude/
PRDs/
```

运行产物不要提交：

```text
reports/evaluation/*.md
reports/evaluation/*.json
```

---

## 十五、提交要求

如果验收通过：

```bash
git add analysis/evaluation_query.py
git commit -m "chore: add evaluation query tool"
```

如果新增文档：

```bash
git add docs/V4-EVALUATION.md
git commit -m "docs: add evaluation query notes"
```

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/
```

---

## 十六、本轮通过标准

1. 新增 `analysis/evaluation_query.py`；
2. 默认只读查询最近 daily 评价；
3. 支持 `--latest`；
4. 支持 `--days`；
5. 支持 `--mode daily|range`；
6. 能解析 diagnostics_json；
7. 能输出趋势摘要；
8. 可选输出 Markdown；
9. 不写数据库；
10. 不改业务链路；
11. 不提交运行产物。

# V4-Evaluation 第 7 轮：评价链路自动化接入前检查

## 当前项目背景

项目：`testStock`

当前阶段：

> V4-Evaluation：评价数据可信性建设

当前已完成：

1. `watchlist_evaluation.py` 是统一评价入口；
2. 支持 `range` 区间评价模式；
3. 支持 `daily` 每日 T+1 验证模式；
4. 支持 `diagnostics` 诊断层；
5. 支持 `--save-db` 写入 evaluation 专用表；
6. 已新增：

   * `watchlist_evaluation_result`
   * `watchlist_evaluation_summary`
7. 已修复 `as_of_date` 边界，避免未来函数；
8. 已新增 `evaluation_query.py` 只读查询工具；
9. 当前可以通过 `evaluation_query.py` 查询最近 daily/range 评价趋势。

当前阶段目标不是改策略，而是让评价链路逐渐变成可信、可追踪、可自动化的复盘模块。

---

## 一、本轮目标

本轮不要直接把 evaluation 接入 `entrypoint.sh`。

本轮只做：

1. 新增一个 evaluation 自动化预检查脚本；
2. 明确 daily evaluation 应该验证哪一天；
3. 明确 as-of 应该是哪一天；
4. 非交易日自动跳过；
5. 检查前一交易日是否存在 `stock_signal`；
6. 检查今日行情是否可用；
7. 检查是否已有同一组 daily evaluation 记录，避免重复；
8. 输出建议命令；
9. 不真正执行 watchlist_evaluation；
10. 不写数据库；
11. 不改 entrypoint；
12. 不改日报主链路。

本轮本质是：

> 自动化接入前的安全检查与运行计划生成。

---

## 二、允许新增 / 修改文件

允许新增：

```text
analysis/evaluation_scheduler_check.py
```

可选新增或修改文档：

```text
docs/V4-EVALUATION.md
```

---

## 三、禁止修改文件

禁止修改：

```text
entrypoint.sh
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/init_db.py
sql/schema.sql
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
data/config.py
```

本轮不改评价计算，不改落库逻辑，不改业务链路。

---

## 四、脚本定位

新增脚本：

```bash
python -m analysis.evaluation_scheduler_check
```

它只负责回答：

```text
今天是否应该跑 daily evaluation？
如果应该跑，signal-date 是哪天？
as-of-date 是哪天？
推荐执行什么命令？
是否已有评价记录？
是否存在必要数据？
```

它不负责真正跑：

```bash
python -m analysis.watchlist_evaluation ...
```

这样可以避免自动化一上来就污染 evaluation 表。

---

## 五、命令设计

支持：

```bash
python -m analysis.evaluation_scheduler_check
python -m analysis.evaluation_scheduler_check --as-of 20260529
python -m analysis.evaluation_scheduler_check --signal-date 20260528 --as-of 20260529
python -m analysis.evaluation_scheduler_check --json
```

默认行为：

```text
as_of_date = 今天
signal_date = as_of_date 的前一个交易日
```

如果暂时不好精确计算前一交易日，可以先从 `stock_signal` 表中取小于 `as_of_date` 的最大 `trade_date` 作为 signal_date。

推荐优先逻辑：

```text
1. 如果用户显式传 --signal-date，则使用用户传入值；
2. 否则从 stock_signal 中取小于 as_of_date 的最大 trade_date；
3. 如果取不到，则输出 SAFE STOP。
```

---

## 六、交易日判断

使用：

```python
from analysis.data_fetcher import is_trade_day
```

判断：

```text
如果 as_of_date 不是交易日：
    输出 [SKIP] as_of_date 非交易日，不建议运行 evaluation
    exit 0
```

不要在非交易日建议执行 watchlist_evaluation。

---

## 七、数据库检查项

只读检查数据库。

使用：

```python
from data.config import DATABASE_DSN
```

检查：

### 1. stock_signal 是否存在

如果不存在：

```text
[ERROR] stock_signal 表不存在，无法进行 evaluation 调度检查
```

### 2. signal_date 是否有信号

查询：

```sql
SELECT COUNT(*)
FROM stock_signal
WHERE trade_date = %s;
```

如果为 0：

```text
[SKIP] signal_date 无 stock_signal 数据，不建议运行 evaluation
```

### 3. watchlist_evaluation_summary 是否存在

如果不存在：

```text
[WARN] watchlist_evaluation_summary 表不存在，请先运行 python -m analysis.init_db
```

但不要崩溃。

### 4. 是否已有同一 daily evaluation

查询：

```sql
SELECT COUNT(*)
FROM watchlist_evaluation_summary
WHERE eval_mode = 'daily'
  AND signal_date = %s
  AND as_of_date = %s;
```

如果已有：

```text
[INFO] 已存在 daily evaluation 记录
```

并建议：

```text
如需刷新，可重新运行 watchlist_evaluation --save-db，upsert 会覆盖同一记录。
```

---

## 八、行情缓存健康检查

本轮不要真正调用 `get_stock_history` 批量拉行情。

只做轻量检查：

查询 `stock_hist_kline` 中是否存在 as_of_date 行情：

```sql
SELECT COUNT(DISTINCT code)
FROM stock_hist_kline
WHERE trade_date = %s;
```

同时查询 signal_date 的信号股票数：

```sql
SELECT COUNT(DISTINCT code)
FROM stock_signal
WHERE trade_date = %s;
```

再查询信号股票中已有 as_of 行情的数量：

```sql
SELECT COUNT(DISTINCT s.code)
FROM stock_signal s
JOIN stock_hist_kline h
  ON s.code = h.code
WHERE s.trade_date = %s
  AND h.trade_date = %s;
```

输出：

```text
signal 股票数：85
as_of 已缓存行情：81
缓存覆盖率：95.3%
```

如果缓存覆盖率低于 80%，输出 warning：

```text
[WARN] as_of 行情缓存覆盖率较低，watchlist_evaluation 可能触发大量 API 刷新。
```

注意：

```text
不要在本脚本中触发 API 刷新。
```

---

## 九、输出建议命令

如果检查通过，输出推荐命令：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529 --save-db
python -m analysis.evaluation_query --latest
```

如果 `--json`，输出 JSON：

```json
{
  "status": "ready|skip|warning|error",
  "signal_date": "20260528",
  "as_of_date": "20260529",
  "is_trade_day": true,
  "signal_count": 85,
  "existing_evaluation": true,
  "price_cache_coverage": 0.953,
  "warnings": [],
  "recommended_commands": [
    "python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529 --save-db",
    "python -m analysis.evaluation_query --latest"
  ]
}
```

---

## 十、状态规则

```text
error:
    数据库连接失败、stock_signal 表不存在

skip:
    as_of_date 非交易日
    或 signal_date 无 stock_signal 数据

warning:
    可以运行，但存在问题：
    - watchlist_evaluation_summary 表不存在
    - as_of 行情缓存覆盖率 < 80%
    - 已有 evaluation 记录

ready:
    可以运行 daily evaluation
```

如果已有 evaluation 记录，不一定是 error。可以是 warning 或 ready_with_existing。第一版可以统一为 warning。

---

## 十一、终端输出格式

示例：

```text
=== Evaluation Scheduler Check ===

as_of_date:    20260529
signal_date:   20260528
交易日检查:    OK
stock_signal:  85 条
已有评价记录:  是
行情缓存覆盖:  81/85 = 95.3%

状态: WARNING
原因:
- 已存在 daily evaluation 记录，重复运行将触发 upsert 覆盖

建议命令:
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529 --save-db
python -m analysis.evaluation_query --latest
```

---

## 十二、安全要求

1. 只读数据库；
2. 不 insert；
3. 不 update；
4. 不 delete；
5. 不调用 `watchlist_evaluation.py`；
6. 不调用 `get_stock_history`；
7. 不触发行情 API；
8. 不改 entrypoint；
9. 不改 pipeline；
10. 不发送邮件；
11. 不写 reports/daily。

---

## 十三、验收命令

执行：

```bash
python -m compileall analysis
python -m analysis.evaluation_scheduler_check --as-of 20260529
python -m analysis.evaluation_scheduler_check --signal-date 20260528 --as-of 20260529
python -m analysis.evaluation_scheduler_check --signal-date 20260528 --as-of 20260529 --json
```

如果今天是非交易日，也执行：

```bash
python -m analysis.evaluation_scheduler_check
```

检查是否能正确 skip。

---

## 十四、预期 diff

理想 diff：

```text
analysis/evaluation_scheduler_check.py
```

可选：

```text
docs/V4-EVALUATION.md
```

不应该出现：

```text
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/init_db.py
sql/schema.sql
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
entrypoint.sh
data/config.py
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十五、提交要求

如果验收通过：

```bash
git add analysis/evaluation_scheduler_check.py
git commit -m "chore: add evaluation scheduler check"
```

如果新增文档：

```bash
git add docs/V4-EVALUATION.md
git commit -m "docs: add evaluation scheduler check notes"
```

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/
```

---

## 十六、本轮通过标准

1. 新增 `analysis/evaluation_scheduler_check.py`；
2. 能自动推断 signal_date；
3. 能检查 as_of_date 是否交易日；
4. 能检查 stock_signal 是否存在数据；
5. 能检查是否已有 daily evaluation；
6. 能检查 stock_hist_kline 的 as_of 缓存覆盖率；
7. 能输出推荐命令；
8. 支持 `--json`；
9. 全程只读，不写数据库；
10. 不调用行情 API；
11. 不改 entrypoint；
12. 不改业务链路。

# V4-Evaluation 第 7 轮补充要求：评价检查邮件必须与日报邮件分离

## 新增边界

evaluation / 数据可信性检查相关邮件，必须和日报邮件分离。

不要把以下内容塞进现有日报邮件正文：

```text
evaluation_scheduler_check 结果
watchlist_evaluation daily 结果
evaluation_query 趋势摘要
分层倒挂诊断
风险提示兑现情况
数据覆盖率检查
price_fetch_failed 检查
```

原因：

```text
日报邮件用于发送当日复盘、观察池和风险提示；
evaluation 邮件用于发送系统评价、昨日兑现情况和数据可信性检查。
两者目的不同，不能混在一起。
```

---

## 本轮仍然不发邮件

第 7 轮只新增：

```text
analysis/evaluation_scheduler_check.py
```

它只做：

```text
1. 检查今天是否应该跑 evaluation；
2. 推断 signal_date / as_of_date；
3. 检查 stock_signal 是否存在；
4. 检查是否已有 evaluation 记录；
5. 检查 stock_hist_kline 缓存覆盖率；
6. 输出推荐命令；
7. 支持 --json。
```

第 7 轮禁止：

```text
发送邮件
修改 email_sender.py
把 evaluation 结果塞进日报邮件
修改 entrypoint.sh
自动执行 watchlist_evaluation
自动执行 evaluation_query
```

---

## 后续邮件设计方向

后续如需发送 evaluation 检查邮件，应新增独立模块：

```text
analysis/evaluation_email_sender.py
```

不要复用或修改现有日报邮件发送逻辑。

未来独立邮件建议命令：

```bash
python -m analysis.evaluation_email_sender --date 20260603
```

或：

```bash
python -m analysis.evaluation_email_sender --latest
```

邮件标题建议：

```text
【A股日报系统自检】观察池兑现与数据可信性检查 - YYYYMMDD
```

不要使用日报邮件标题。

---

## 独立 evaluation 邮件内容

未来 evaluation 邮件只包含：

```text
1. evaluation_scheduler_check 状态
2. latest daily evaluation 摘要
3. coverage_1d / coverage_3d
4. 分层倒挂 warning
5. 风险提示 warning
6. 弱表现策略 / 强表现策略
7. price_fetch_failed
8. 推荐后续动作
```

不包含：

```text
今日观察池明细
今日交易计划
日报正文
专业版日报附件
trade_plan 附件
```

---

## 邮件分离原则

最终形成两类邮件：

### 1. 日报邮件

由现有：

```text
analysis/email_sender.py
```

负责。

内容：

```text
当日复盘
观察池
风险提示
trade_plan
日报附件
```

### 2. Evaluation 自检邮件

未来由：

```text
analysis/evaluation_email_sender.py
```

负责。

内容：

```text
昨日观察池 T+1 兑现情况
evaluation 覆盖率
分层倒挂
风险提示有效性
数据可信性检查
```

两者互不调用，互不混入正文。

---

## 第 7 轮验收补充

第 7 轮完成后检查：

```bash
git diff --stat
```

理想 diff 仍然只包含：

```text
analysis/evaluation_scheduler_check.py
```

不应出现：

```text
analysis/email_sender.py
analysis/evaluation_email_sender.py
entrypoint.sh
reports/
```

本轮不做邮件发送，只做调度检查。
# V4-Evaluation 第 8 轮：独立 evaluation 自检邮件

## 当前项目背景

项目：`testStock`

当前阶段：

> V4-Evaluation：评价数据可信性建设

当前已完成：

1. `watchlist_evaluation.py` 已成为统一评价入口；
2. 支持 `range` 区间评价；
3. 支持 `daily` 每日 T+1 验证；
4. 支持 `diagnostics` 诊断层；
5. 支持 `--save-db` 写入 evaluation 专用表；
6. 已新增 evaluation 专用表：

   * `watchlist_evaluation_result`
   * `watchlist_evaluation_summary`
7. 已修复 `as_of_date` 边界，避免未来函数；
8. 已新增 `evaluation_query.py` 只读查询工具；
9. 已新增 `evaluation_scheduler_check.py` 调度检查工具；
10. 当前 evaluation 链路已经可以形成：

```text
evaluation_scheduler_check
  -> watchlist_evaluation --save-db
  -> evaluation_query
```

本轮目标：

> 新增独立 evaluation 自检邮件发送模块，用于发送“观察池兑现与数据可信性检查”邮件。

注意：

> evaluation 邮件必须和日报邮件分离。
> 不要修改现有 `email_sender.py`。
> 不要把 evaluation 内容塞进日报邮件。

---

## 一、本轮核心原则

当前系统未来应形成两条邮件链路：

### 1. 日报邮件链路

由现有模块负责：

```text
analysis/email_sender.py
```

内容：

```text
当日复盘
观察池
风险提示
trade_plan
日报附件
```

### 2. Evaluation 自检邮件链路

本轮新增：

```text
analysis/evaluation_email_sender.py
```

内容：

```text
昨日观察池 T+1 兑现情况
evaluation 调度检查状态
coverage_1d / coverage_3d
分层倒挂 warning
风险提示 warning
弱表现策略 / 强表现策略
price_fetch_failed
数据可信性提示
```

两者必须互不调用，互不混入正文。

---

## 二、本轮目标

本轮只做：

1. 新增 `analysis/evaluation_email_sender.py`；
2. 读取最近 evaluation summary；
3. 读取 `evaluation_scheduler_check` 的结果，或复用其检查逻辑；
4. 生成独立 evaluation 邮件正文；
5. 发送独立 evaluation 自检邮件；
6. 支持 `--dry-run`，只打印不发送；
7. 支持 `--latest`；
8. 支持 `--date YYYYMMDD`；
9. 支持 `--to` 可选覆盖收件人；
10. 不改日报邮件；
11. 不改 entrypoint；
12. 不改 selector；
13. 不改日报生成；
14. 不写数据库。

---

## 三、允许新增 / 修改文件

允许新增：

```text
analysis/evaluation_email_sender.py
```

可选修改：

```text
docs/V4-EVALUATION.md
```

仅用于追加“evaluation 自检邮件说明”，不要写长篇迭代日志。

---

## 四、禁止修改文件

禁止修改：

```text
analysis/email_sender.py
entrypoint.sh
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/init_db.py
sql/schema.sql
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
data/config.py
```

本轮不改业务链路，不改日报链路，不改 evaluation 计算逻辑。

---

## 五、命令设计

新增脚本支持：

```bash
python -m analysis.evaluation_email_sender --latest --dry-run
python -m analysis.evaluation_email_sender --latest
python -m analysis.evaluation_email_sender --date 20260529 --dry-run
python -m analysis.evaluation_email_sender --date 20260529
python -m analysis.evaluation_email_sender --latest --to user@example.com --dry-run
```

默认建议：

```bash
python -m analysis.evaluation_email_sender --latest --dry-run
```

---

## 六、参数说明

### `--latest`

读取最新一条 `watchlist_evaluation_summary` 中的 daily 记录。

等价于：

```sql
SELECT *
FROM watchlist_evaluation_summary
WHERE eval_mode = 'daily'
ORDER BY generated_at DESC
LIMIT 1;
```

### `--date YYYYMMDD`

按 `as_of_date` 查询 daily evaluation：

```sql
SELECT *
FROM watchlist_evaluation_summary
WHERE eval_mode = 'daily'
  AND as_of_date = %s
ORDER BY generated_at DESC
LIMIT 1;
```

### `--dry-run`

只打印邮件标题和正文，不发送 SMTP。

这是默认验收推荐方式。

### `--to`

可选覆盖收件人。
如果不传，则使用项目现有邮件配置中的默认收件人。

---

## 七、邮件标题

标题必须和日报邮件明显区分。

建议：

```text
【A股日报系统自检】观察池兑现与数据可信性检查 - YYYYMMDD
```

其中 `YYYYMMDD` 使用 `as_of_date`。

不要使用日报标题，例如：

```text
A股日报
每日复盘
交易计划
```

---

## 八、邮件正文结构

邮件正文建议：

```text
# 观察池兑现与数据可信性检查

检查日期：YYYYMMDD
信号日期：YYYYMMDD
评价模式：daily

## 1. 调度检查

- 状态：READY / WARNING / SKIP / ERROR
- 是否交易日：
- stock_signal 数量：
- 是否已有 evaluation 记录：
- 行情缓存覆盖率：

## 2. T+1 评价摘要

- 总信号数：
- 1 日实际评价：
- 1 日覆盖率：
- 平均次日收益：
- 次日胜率：
- 3 日实际评价：
- 3 日覆盖率：

## 3. 数据质量

- price_fetch_failed：
- missing reasons：
- confidence_level：
- conclusion_level：

## 4. 诊断结果

- 分层倒挂：
- 风险提示 warning：
- 弱表现策略：
- 强表现策略：
- 诊断消息：

## 5. 建议动作

- 如果 coverage_1d < 80%：
  行情覆盖不足，优先检查 stock_hist_kline 缓存。
- 如果连续分层倒挂：
  继续观察，不建议单日调参。
- 如果风险警告连续出现：
  后续进入风险分层复盘。
- 如果 status 正常：
  仅记录，无需操作。

> 本邮件是 evaluation 自检邮件，不是日报邮件。
> 本邮件不构成实盘买卖建议。
```

---

## 九、数据来源

只读读取：

```text
watchlist_evaluation_summary
```

读取字段：

```text
eval_mode
signal_date
as_of_date
total_signals
evaluated_1d
coverage_1d
evaluated_3d
coverage_3d
price_fetch_failed
avg_next_1d_return
win_rate_1d
avg_next_3d_return
win_rate_3d
confidence_level
conclusion_level
layer_inversion_warning
risk_warning
diagnostics_json
summary_json
generated_at
```

解析：

```text
diagnostics_json
summary_json
```

提取：

```text
underperforming_strategies
outperforming_strategies
diagnostic_messages
missing_reasons
```

如果 JSON 解析失败，不要崩溃，正文中显示 `N/A`。

---

## 十、调度检查结果

本轮可以有两种实现方式，优先推荐第一种。

### 推荐方式：复用 evaluation_scheduler_check 的纯函数

如果 `evaluation_scheduler_check.py` 已经有可复用函数，例如：

```python
run_check(...)
```

可以 import 并调用。

但禁止让它触发行情 API 或写库。

### 备选方式：只读取 latest summary，不强依赖 scheduler_check

如果现有 `evaluation_scheduler_check.py` 只有 CLI，不方便复用，本轮可以先不强行重构它。

邮件正文中的“调度检查”部分可以简化为：

```text
- 已有 evaluation 记录：是
- as_of_date：
- signal_date：
```

不要为了复用而大改 `evaluation_scheduler_check.py`。

---

## 十一、发送逻辑

优先复用项目现有 SMTP 配置。

可以参考 `analysis/email_sender.py` 中的发送函数，但不要修改 `email_sender.py`。

可选实现方式：

1. 在 `evaluation_email_sender.py` 中复制一个最小 SMTP 发送函数；
2. 或者如果项目已有公共发送函数，可以 import 使用。

要求：

```text
不要 import email_sender.main()
不要调用日报发送逻辑
不要发送日报附件
不要附加 daily_report / trade_plan
```

---

## 十二、附件要求

本轮默认不附加附件。

不要附加：

```text
daily_report
daily_report_pro
trade_plan
pipeline_check
日报 zip
```

如果未来要附加 evaluation Markdown，后续再做。

本轮只发送纯文本邮件。

---

## 十三、非交易日守卫

evaluation 邮件不应该在非交易日乱发。

规则：

1. 如果使用 `--date YYYYMMDD`：

   * 如果该日期非交易日，默认 skip；
   * 除非未来增加 `--force`，本轮不需要实现 force。

2. 如果使用 `--latest`：

   * 不用判断今天是否交易日；
   * 因为 latest 是已落库的 evaluation 记录；
   * 但邮件正文要显示其 `as_of_date`。

推荐第一版：

```text
--latest：允许发送 latest evaluation
--date：如果 date 非交易日则 skip
```

---

## 十四、错误处理

如果数据库连接失败：

```text
[ERROR] 数据库连接失败，无法发送 evaluation 自检邮件
```

如果没有 evaluation summary：

```text
[SKIP] 未找到 evaluation summary 记录
```

如果 SMTP 配置缺失：

```text
[ERROR] SMTP 配置缺失，无法发送邮件
```

`--dry-run` 不需要 SMTP 配置也能输出正文。

---

## 十五、验收命令

执行：

```bash
python -m compileall analysis
python -m analysis.evaluation_email_sender --latest --dry-run
python -m analysis.evaluation_email_sender --date 20260529 --dry-run
```

如果确认 SMTP 配置可用，再手动执行：

```bash
python -m analysis.evaluation_email_sender --latest
```

检查：

```bash
git diff --stat
git status --short --untracked-files=all
```

---

## 十六、验收重点

必须确认：

1. `--dry-run` 能打印邮件标题和正文；
2. 邮件标题与日报邮件明显不同；
3. 正文包含 evaluation summary；
4. 正文包含 diagnostics；
5. 不包含日报正文；
6. 不包含观察池明细；
7. 不包含 trade_plan；
8. 不附加日报附件；
9. 不调用 `email_sender.py`；
10. 不改 `email_sender.py`；
11. 不改 `entrypoint.sh`；
12. 不写数据库；
13. 不触发行情 API。

---

## 十七、预期 diff

理想 diff：

```text
analysis/evaluation_email_sender.py
```

可选：

```text
docs/V4-EVALUATION.md
```

不应该出现：

```text
analysis/email_sender.py
entrypoint.sh
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/init_db.py
sql/schema.sql
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十八、提交要求

如果验收通过：

```bash
git add analysis/evaluation_email_sender.py
git commit -m "chore: add evaluation email sender"
```

如果新增文档：

```bash
git add docs/V4-EVALUATION.md
git commit -m "docs: add evaluation email notes"
```

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/
```

---

## 十九、本轮通过标准

1. 新增独立 `evaluation_email_sender.py`；
2. 支持 `--latest`；
3. 支持 `--date`；
4. 支持 `--dry-run`；
5. 邮件标题明显区别于日报；
6. 邮件正文只包含 evaluation 自检内容；
7. 不包含日报正文；
8. 不包含 trade_plan；
9. 不附加日报附件；
10. 不改 `email_sender.py`；
11. 不改 `entrypoint.sh`；
12. 不写数据库；
13. 不触发行情 API；
14. 可手动发送 evaluation 自检邮件。

# V4-Evaluation 第 9 轮：evaluation 链路手动总验收

## 当前项目背景

项目：`testStock`

当前阶段：

> V4-Evaluation：评价数据可信性建设

当前已完成：

1. `watchlist_evaluation.py` 已成为统一评价入口；
2. 支持 `range` 区间评价；
3. 支持 `daily` 每日 T+1 验证；
4. 支持 `diagnostics` 诊断层；
5. 支持 `--save-db` 写入 evaluation 专用表；
6. 已新增 evaluation 专用表：

   * `watchlist_evaluation_result`
   * `watchlist_evaluation_summary`
7. 已修复 `as_of_date` 边界，避免未来函数；
8. 已修复 result 表唯一键，避免不同 range 区间互相覆盖；
9. 已新增 `evaluation_query.py` 只读查询工具；
10. 已新增 `evaluation_scheduler_check.py` 调度检查工具；
11. 已新增 `evaluation_email_sender.py` 独立 evaluation 自检邮件；
12. evaluation 邮件已与日报邮件完全分离。

当前 evaluation 链路为：

```text
evaluation_scheduler_check
  -> watchlist_evaluation --save-db
  -> evaluation_query
  -> evaluation_email_sender
```

日报链路仍然独立：

```text
entrypoint.sh
  -> daily_report
  -> email_sender
```

本轮目标：

> 不新增功能，不改业务逻辑，只做 evaluation 链路手动总验收。

---

## 一、本轮目标

本轮只做手动总验收，确认：

1. `evaluation_scheduler_check` 能正确判断是否应该运行 evaluation；
2. `watchlist_evaluation --save-db` 能按推荐命令运行；
3. `watchlist_evaluation` 重复运行不会重复插入；
4. `evaluation_query` 能查到最新 evaluation 记录；
5. `evaluation_email_sender --dry-run` 能生成正确独立自检邮件；
6. evaluation 链路不影响日报链路；
7. 不改 `entrypoint.sh`；
8. 不改 `email_sender.py`；
9. 不发送真实邮件；
10. 不提交 reports 运行产物。

---

## 二、本轮允许修改文件

原则上本轮不修改代码。

如果验收发现非常小的错误，只允许修改：

```text
analysis/evaluation_scheduler_check.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_email_sender.py
```

但如果没有 bug，不要为了“优化”而改代码。

---

## 三、本轮禁止修改文件

禁止修改：

```text
entrypoint.sh
analysis/email_sender.py
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/init_db.py
sql/schema.sql
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
data/config.py
```

本轮不改日报链路，不改数据库结构，不改 selector，不改邮件主链路。

---

## 四、验收日期

优先使用已经确认有数据的日期：

```text
signal_date = 20260528
as_of_date  = 20260529
```

原因：

```text
这组数据已知：
- stock_signal 有 85 条；
- 1d 可评价约 81 条；
- as_of 边界已验证；
- evaluation summary 已有落库记录；
- 适合做回归验收。
```

---

## 五、验收步骤 1：基础环境检查

执行：

```bash
git checkout dev
git pull origin dev
git status --short --untracked-files=all
python -m compileall analysis
```

验收标准：

```text
compileall 通过；
git status 中不要出现 reports / __pycache__ / .claude 被误跟踪；
如果 PRDs 有本地修改，先不要提交，单独处理。
```

---

## 六、验收步骤 2：调度检查

执行：

```bash
python -m analysis.evaluation_scheduler_check --as-of 20260529
```

预期：

```text
as_of_date = 20260529
signal_date = 20260528
交易日检查通过
stock_signal 数量约 85
行情缓存覆盖率约 95%
如果已有 evaluation 记录，状态可以是 WARNING
输出推荐命令
```

再执行 JSON 模式：

```bash
python -m analysis.evaluation_scheduler_check --signal-date 20260528 --as-of 20260529 --json
```

检查 JSON 至少包含：

```text
status
signal_date
as_of_date
signal_count
existing_evaluation
price_cache_coverage
recommended_commands
```

---

## 七、验收步骤 3：运行 daily evaluation 并落库

执行：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529 --save-db
```

验收标准：

```text
生成 daily_watchlist_evaluation_20260528_20260529.json/md；
summary + detail 写入 evaluation 表；
不会写 stock_signal；
不会写 signal_performance；
不会发送邮件；
不会写 reports/daily。
```

重点检查输出：

```text
total_signals ≈ 85
evaluated_1d ≈ 81
is_mature_3d 不应大面积为 true
missing_reason 中应有 insufficient_future_days_for_3d
diagnostics 存在
confidence_level = daily_observation 或合理等级
conclusion_level = observe_only
```

---

## 八、验收步骤 4：重复运行验证 upsert

再次执行：

```bash
python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529 --save-db
```

然后执行 SQL：

```sql
SELECT COUNT(*)
FROM watchlist_evaluation_result
WHERE eval_mode = 'daily'
  AND signal_trade_date = '20260528'
  AND as_of_date = '20260529';
```

预期：

```text
仍为 85 左右，不重复增长
```

再查重复：

```sql
SELECT eval_mode, eval_start_date, eval_end_date, signal_trade_date, signal_key, as_of_date, COUNT(*)
FROM watchlist_evaluation_result
GROUP BY eval_mode, eval_start_date, eval_end_date, signal_trade_date, signal_key, as_of_date
HAVING COUNT(*) > 1;
```

预期：

```text
0 行
```

---

## 九、验收步骤 5：查询 latest evaluation

执行：

```bash
python -m analysis.evaluation_query --latest
```

预期终端输出包含：

```text
daily
signal_date = 20260528
as_of_date = 20260529
total = 85
evaluated_1d = 81
coverage_1d 约 95%
layer_inversion_warning
risk_warning
conclusion_level = observe_only
```

再执行：

```bash
python -m analysis.evaluation_query --mode daily --days 10
```

预期：

```text
能输出趋势摘要；
能识别分层倒挂次数；
能识别风险警告次数；
能解析弱表现策略 / 强表现策略。
```

---

## 十、验收步骤 6：evaluation 自检邮件 dry-run

执行：

```bash
python -m analysis.evaluation_email_sender --latest --dry-run
```

预期：

```text
只打印邮件标题和正文；
不连接 SMTP；
不发送真实邮件；
不需要 SMTP 配置；
标题为：
【A股日报系统自检】观察池兑现与数据可信性检查 - YYYYMMDD
```

正文必须包含：

```text
评价模式
signal_date
as_of_date
total_signals
evaluated_1d
coverage_1d
price_fetch_failed
confidence_level
conclusion_level
分层倒挂
风险警告
弱表现策略
强表现策略
建议动作
```

正文不得包含：

```text
日报正文
今日观察池完整明细
trade_plan
daily_report 附件
日报 zip
```

再执行：

```bash
python -m analysis.evaluation_email_sender --date 20260529 --dry-run
```

预期与 latest 一致或能按 as_of_date 查询到记录。

非交易日测试：

```bash
python -m analysis.evaluation_email_sender --date 20260531 --dry-run
```

预期：

```text
非交易日 SKIP
```

---

## 十一、验收步骤 7：确认未影响日报链路

本轮不跑完整日报，但要确认代码没有改到日报链路：

```bash
git diff --stat
git status --short --untracked-files=all
```

如果本轮没有代码修复，理想情况：

```text
无业务代码 diff
仅 reports/evaluation 运行产物未跟踪
```

如果有代码修复，diff 只能出现在：

```text
analysis/evaluation_scheduler_check.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_email_sender.py
```

不应出现：

```text
entrypoint.sh
analysis/email_sender.py
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
sql/schema.sql
analysis/init_db.py
```

---

## 十二、运行产物处理

本轮运行可能产生：

```text
reports/evaluation/daily_watchlist_evaluation_20260528_20260529.json
reports/evaluation/daily_watchlist_evaluation_20260528_20260529.md
reports/evaluation/evaluation_query_*.md
```

这些是运行产物。

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/
```

如需保留本地查看，可以保留在工作区，但不要 `git add reports/`。

---

## 十三、通过标准

本轮通过标准：

1. `compileall` 通过；
2. `evaluation_scheduler_check` 能给出正确 signal/as_of；
3. `watchlist_evaluation --save-db` 能成功落库；
4. 重复运行不会重复插入；
5. `as_of` 边界仍然正确；
6. `evaluation_query --latest` 能查到最新结果；
7. `evaluation_email_sender --dry-run` 能输出独立自检邮件；
8. evaluation 邮件不混入日报内容；
9. 不发送真实邮件；
10. 不改 `entrypoint.sh`；
11. 不改 `email_sender.py`；
12. 不提交运行产物。

---

## 十四、如果验收中发现 bug

如果发现小 bug，可以修，但必须遵守：

```text
只修 evaluation 链路；
不改日报链路；
不改 selector；
不改数据库结构；
不新增功能。
```

提交信息建议：

```bash
git add analysis/evaluation_scheduler_check.py analysis/watchlist_evaluation.py analysis/evaluation_query.py analysis/evaluation_email_sender.py
git commit -m "fix: stabilize evaluation manual flow"
```

如果没有任何代码改动，则不需要提交。

---

## 十五、验收通过后的下一步

如果第 9 轮手动总验收通过，下一阶段再评估是否单独 cron：

```text
V4-Evaluation 第 10 轮：evaluation 独立 cron 设计
```

注意：

```text
evaluation cron 应该独立于日报 cron；
evaluation 邮件独立于日报邮件；
evaluation 失败不应影响日报生成和日报发送。
```
# V4-Evaluation 第 10 轮：evaluation 独立 cron 设计

## 当前项目背景

项目：`testStock`

当前阶段：

> V4-Evaluation：评价数据可信性建设

当前已完成：

1. `watchlist_evaluation.py` 已成为统一评价入口；
2. 支持 `range` 区间评价；
3. 支持 `daily` 每日 T+1 验证；
4. 支持 `diagnostics` 诊断层；
5. 支持 `--save-db` 写入 evaluation 专用表；
6. 已新增 evaluation 专用表：

   * `watchlist_evaluation_result`
   * `watchlist_evaluation_summary`
7. 已修复 `as_of_date` 边界，避免未来函数；
8. 已修复 result 表唯一键，避免不同 range 区间互相覆盖；
9. 已新增 `evaluation_query.py` 只读查询工具；
10. 已新增 `evaluation_scheduler_check.py` 调度检查工具；
11. 已新增 `evaluation_email_sender.py` 独立 evaluation 自检邮件；
12. 第 9 轮手动总验收已经通过；
13. evaluation 邮件已经和日报邮件分离；
14. 当前 evaluation 链路已经 push 到 dev。

当前 evaluation 手动链路为：

```text
evaluation_scheduler_check
  -> watchlist_evaluation --save-db
  -> evaluation_query
  -> evaluation_email_sender
```

本轮目标：

> 设计并实现 evaluation 独立 cron 入口脚本，但暂时不修改系统 cron，不修改 entrypoint，不接入日报链路。

---

## 一、本轮核心原则

evaluation 链路必须独立于日报链路。

### 日报链路

```text
entrypoint.sh
  -> daily_report
  -> email_sender
```

### Evaluation 链路

```text
evaluation_entrypoint.sh
  -> evaluation_scheduler_check
  -> watchlist_evaluation --save-db
  -> evaluation_query
  -> evaluation_email_sender
```

本轮禁止：

```text
修改 entrypoint.sh
修改 email_sender.py
把 evaluation 塞进日报邮件
让 evaluation 失败影响日报
让日报失败影响 evaluation
```

---

## 二、本轮目标

本轮只做：

1. 新增独立 shell 入口：

   * `scripts/evaluation_entrypoint.sh`
2. 支持外部传入：

   * `AS_OF_DATE=YYYYMMDD`
   * `SEND_EVAL_EMAIL=1/0`
3. 默认使用当天作为 as_of；
4. 先运行 `evaluation_scheduler_check`；
5. 非交易日自动 skip；
6. 没有 stock_signal 自动 skip；
7. scheduler check ready / warning 时，执行推荐的 watchlist evaluation；
8. watchlist evaluation 成功后，运行 evaluation_query；
9. 如果 `SEND_EVAL_EMAIL=1`，再发送 evaluation 自检邮件；
10. 默认不发送邮件；
11. 不改日报链路；
12. 不改数据库结构；
13. 不改 selector；
14. 不改日报生成；
15. 不改 email_sender。

---

## 三、允许新增 / 修改文件

允许新增：

```text
scripts/evaluation_entrypoint.sh
```

可选新增或修改文档：

```text
docs/V4-EVALUATION-CRON.md
```

如果项目没有 `scripts/` 目录，可以新增该目录。

---

## 四、禁止修改文件

禁止修改：

```text
entrypoint.sh
analysis/email_sender.py
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/init_db.py
sql/schema.sql
data/config.py
```

原则上也不要修改：

```text
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
```

除非发现独立入口无法调用的很小 bug。
如果需要改这些 Python 文件，必须说明原因，只做最小修复。

---

## 五、evaluation_entrypoint.sh 设计

新增：

```text
scripts/evaluation_entrypoint.sh
```

建议内容结构：

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

AS_OF_DATE="${AS_OF_DATE:-$(date +%Y%m%d)}"
SEND_EVAL_EMAIL="${SEND_EVAL_EMAIL:-0}"

echo "=== Evaluation EntryPoint ==="
echo "AS_OF_DATE=${AS_OF_DATE}"
echo "SEND_EVAL_EMAIL=${SEND_EVAL_EMAIL}"
```

注意：

```text
必须支持外部 AS_OF_DATE。
不能在脚本内部强制覆盖外部日期。
```

---

## 六、调度检查

先运行：

```bash
python -m analysis.evaluation_scheduler_check --as-of "$AS_OF_DATE" --json
```

为了简化第一版，可以同时输出 JSON 到临时文件：

```bash
CHECK_FILE="reports/evaluation/evaluation_scheduler_check_${AS_OF_DATE}.json"
mkdir -p reports/evaluation

python -m analysis.evaluation_scheduler_check --as-of "$AS_OF_DATE" --json > "$CHECK_FILE"
```

然后从 JSON 中解析：

```text
status
signal_date
as_of_date
recommended_commands
```

如果不想依赖 `jq`，可以用 Python 一行解析。

示例：

```bash
STATUS=$(python -c "import json; print(json.load(open('$CHECK_FILE', encoding='utf-8')).get('status',''))")
SIGNAL_DATE=$(python -c "import json; print(json.load(open('$CHECK_FILE', encoding='utf-8')).get('signal_date',''))")
```

---

## 七、状态处理规则

### status = skip

输出：

```text
[SKIP] evaluation scheduler check skipped.
```

然后：

```bash
exit 0
```

### status = error

输出：

```text
[ERROR] evaluation scheduler check failed.
```

然后：

```bash
exit 1
```

### status = ready 或 warning

继续执行。

注意：

```text
warning 不阻断。
例如已有 evaluation 记录，重复运行 watchlist_evaluation --save-db 会 upsert。
行情缓存覆盖率低也不阻断，但会提示。
```

---

## 八、运行 watchlist_evaluation

不要直接 eval recommended_commands。
第一版建议显式构造命令：

```bash
python -m analysis.watchlist_evaluation \
  --mode daily \
  --signal-date "$SIGNAL_DATE" \
  --as-of "$AS_OF_DATE" \
  --save-db
```

这样更安全。

如果 `SIGNAL_DATE` 为空：

```bash
echo "[ERROR] SIGNAL_DATE 为空，停止"
exit 1
```

---

## 九、运行 evaluation_query

watchlist_evaluation 成功后执行：

```bash
python -m analysis.evaluation_query --latest
```

如果需要生成 Markdown，可选：

```bash
python -m analysis.evaluation_query --latest --output-md
```

本轮建议默认只终端输出，不默认生成 query markdown，避免 reports 产物太多。

---

## 十、发送 evaluation 自检邮件

默认不发送邮件。

只有当：

```bash
SEND_EVAL_EMAIL=1
```

时执行：

```bash
python -m analysis.evaluation_email_sender --latest
```

否则只 dry-run 或完全不发送。

建议第一版：

```bash
if [ "$SEND_EVAL_EMAIL" = "1" ]; then
    python -m analysis.evaluation_email_sender --latest
else
    echo "[INFO] SEND_EVAL_EMAIL != 1，跳过 evaluation 邮件发送"
    python -m analysis.evaluation_email_sender --latest --dry-run
fi
```

也可以选择不跑 dry-run，只输出提示。
为了便于验收，建议保留 dry-run。

---

## 十一、非交易日行为

非交易日应由 `evaluation_scheduler_check` 返回 skip。

`scripts/evaluation_entrypoint.sh` 不需要重复调用 `is_trade_day`。

但脚本必须做到：

```text
as_of 非交易日时，最终 exit 0，不报错，不发送邮件，不跑 watchlist_evaluation。
```

---

## 十二、日志输出

脚本输出建议：

```text
=== Evaluation EntryPoint ===
AS_OF_DATE=20260529
SEND_EVAL_EMAIL=0

[1/4] Scheduler check
status=warning
signal_date=20260528

[2/4] Run watchlist_evaluation
...

[3/4] Query latest evaluation
...

[4/4] Evaluation email
dry-run only

[DONE] evaluation workflow completed.
```

---

## 十三、脚本权限

创建后设置可执行：

```bash
chmod +x scripts/evaluation_entrypoint.sh
```

如果 Windows 环境不能 chmod，可以至少保证脚本内容正确，后续服务器上执行 chmod。

---

## 十四、验收命令

执行：

```bash
python -m compileall analysis
bash scripts/evaluation_entrypoint.sh
```

指定日期：

```bash
AS_OF_DATE=20260529 bash scripts/evaluation_entrypoint.sh
```

非交易日：

```bash
AS_OF_DATE=20260531 bash scripts/evaluation_entrypoint.sh
```

预期：

```text
非交易日 SKIP
不运行 watchlist_evaluation
不发送邮件
exit 0
```

邮件 dry-run：

```bash
AS_OF_DATE=20260529 SEND_EVAL_EMAIL=0 bash scripts/evaluation_entrypoint.sh
```

真实发送邮件仅手动测试：

```bash
AS_OF_DATE=20260529 SEND_EVAL_EMAIL=1 bash scripts/evaluation_entrypoint.sh
```

如果 SMTP 配置未确认，不要执行真实发送。

---

## 十五、验收重点

必须确认：

1. `AS_OF_DATE=20260529` 能完整跑通；
2. `AS_OF_DATE=20260531` 非交易日 skip；
3. 默认不发送真实邮件；
4. `SEND_EVAL_EMAIL=1` 才发送真实 evaluation 邮件；
5. 不调用日报邮件；
6. 不改 `entrypoint.sh`；
7. 不改 `email_sender.py`;
8. 不影响日报链路；
9. watchlist_evaluation 重复运行仍 upsert；
10. 失败时有清晰日志。

---

## 十六、未来 cron 示例

本轮可以在文档里给出建议 cron，但不要自动安装。

示例：

```cron
# 每个交易日收盘后 17:30 运行 evaluation 链路
30 17 * * 1-5 cd /path/to/testStock && SEND_EVAL_EMAIL=1 bash scripts/evaluation_entrypoint.sh >> logs/evaluation_cron.log 2>&1
```

注意：

```text
这只是示例，不要在代码里写死。
实际是否配置 cron 由用户在服务器手动决定。
```

---

## 十七、预期 diff

理想 diff：

```text
scripts/evaluation_entrypoint.sh
```

可选：

```text
docs/V4-EVALUATION-CRON.md
```

不应该出现：

```text
entrypoint.sh
analysis/email_sender.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/init_db.py
sql/schema.sql
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十八、提交要求

如果验收通过：

```bash
git add scripts/evaluation_entrypoint.sh
git commit -m "chore: add evaluation entrypoint script"
git push origin dev
```

如果新增文档：

```bash
git add docs/V4-EVALUATION-CRON.md
git commit -m "docs: add evaluation cron notes"
git push origin dev
```

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/
logs/
```

---

## 十九、本轮通过标准

1. 新增独立 `scripts/evaluation_entrypoint.sh`；
2. 支持 `AS_OF_DATE`；
3. 支持 `SEND_EVAL_EMAIL`；
4. 非交易日 skip；
5. ready / warning 时运行 watchlist_evaluation --save-db；
6. 运行 evaluation_query；
7. 默认不发送真实邮件；
8. evaluation 邮件仍独立；
9. 不改 entrypoint；
10. 不改 email_sender；
11. 不改日报链路；
12. 不提交运行产物。


# V4-Data Hotfix：修复 stock_board_map 刷新逻辑 + 可靠性统计

## 当前问题背景

项目：`testStock`

日报邮件出现数据质量提示：

```text
可信度：70 / 100
- 个股板块映射 8 天未更新，可能不准确。
- 大量个股均线数据缺失，选股策略参考价值下降。
```

服务器 crontab 已配置每周一 9:00 执行板块映射任务：

```bash
0 9 * * 1 cd /root/stock-ai-system && flock -n /tmp/stock-mapper.lock docker compose run --rm stock-mapper >> /root/stock-ai-system/logs/mapper.log 2>&1
```

日志显示 cron 确实执行了，但大量输出：

```text
已存在，跳过
行业映射完成，本次写入 0 条
概念映射完成，本次写入 0 条
```

数据库检查：

```sql
SELECT MAX(updated_at), COUNT(*)
FROM stock_board_map;
```

结果：

```text
MAX(updated_at) = 2026-05-25 09:01:06.595
COUNT = 84217
```

说明：

```text
cron 任务执行了；
但 stock_board_map 没有刷新；
updated_at 停留在 2026-05-25；
日报提示“8 天未更新”是合理的。
```

根因判断：

```text
mapper 当前逻辑是：如果板块已存在，则跳过。
因此每周任务虽然运行，但不会刷新已有板块的成分股，也不会更新 updated_at。
```

---

## 一、本轮目标

本轮修复 mapper 刷新机制，并增强可靠性日志。

目标：

```text
stock-mapper 每周运行时，必须刷新 stock_board_map，而不是“已存在就跳过”。
```

本轮一次性完成：

```text
1. 不再因为板块已存在就跳过；
2. 对每个 board_type + board_name 刷新映射；
3. 刷新方式采用 delete old + insert latest；
4. 空成分股不删除旧数据；
5. 单个板块失败不影响整体任务；
6. 输出行业/概念/总耗时；
7. 输出成功刷新数、失败数、空数据跳过数；
8. 输出删除旧记录数、写入新记录数；
9. mapper 运行后 stock_board_map.updated_at 更新到本次运行时间。
```

---

## 二、允许修改文件范围

先定位 mapper 文件：

```bash
grep -R "已存在，跳过" -n .
grep -R "stock_board_map" -n analysis
grep -R "stock-mapper" -n .
```

允许修改 mapper 相关文件，例如：

```text
analysis/board_mapper.py
analysis/stock_board_mapper.py
analysis/board_mapping.py
analysis/update_stock_board_map.py
```

实际以 grep 结果为准。

如果 docker service 对应的入口脚本在其他文件，也可以小范围修改该 mapper 入口。

---

## 三、禁止修改文件

禁止修改：

```text
entrypoint.sh
analysis/email_sender.py
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
scripts/evaluation_entrypoint.sh
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
sql/schema.sql
analysis/init_db.py
data/config.py
```

本轮不改日报链路，不改 evaluation 链路，不改数据库表结构。

---

## 四、当前错误逻辑

当前日志显示：

```text
[1/496] 燃料电池 - 已存在，跳过
[51/496] 诊断服务 - 已存在，跳过
...
行业映射完成，本次写入 0 条

[1/486] 2026一季报预亏 - 已存在，跳过
[51/486] 昨日炸板 - 已存在，跳过
...
概念映射完成，本次写入 0 条
```

这类逻辑必须移除或改造：

```python
if board already exists in stock_board_map:
    skip
else:
    insert constituents
```

每周映射任务不能是 append-only，也不能是 board exists 就跳过。

---

## 五、目标刷新逻辑

推荐采用：

```text
按 board_type + board_name 删除旧记录，再插入最新成分股。
```

对每个行业/概念板块：

```text
1. 调用数据源获取该板块最新成分股；
2. 如果成分股为空，保留旧数据并跳过；
3. 如果成分股非空，开启事务；
4. DELETE FROM stock_board_map WHERE board_type = ? AND board_name = ?;
5. INSERT 最新成分股；
6. updated_at = NOW();
7. commit。
```

伪代码：

```python
def refresh_board_mapping(conn, board_type, board_name, constituents):
    if constituents is None or len(constituents) == 0:
        log warning
        return {
            "status": "empty_skipped",
            "deleted": 0,
            "inserted": 0,
        }

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM stock_board_map
                    WHERE board_type = %s AND board_name = %s
                    """,
                    (board_type, board_name),
                )
                deleted = cur.rowcount

                inserted = 0
                for stock in constituents:
                    cur.execute(
                        """
                        INSERT INTO stock_board_map
                        (code, name, board_type, board_name, source, updated_at)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                        """,
                        (code, name, board_type, board_name, source),
                    )
                    inserted += 1

        return {
            "status": "refreshed",
            "deleted": deleted,
            "inserted": inserted,
        }

    except Exception as e:
        rollback
        log error
        return {
            "status": "failed",
            "deleted": 0,
            "inserted": 0,
            "error": str(e),
        }
```

注意：字段名以当前表结构为准，不要臆造。如果 stock_board_map 字段不同，要按现有字段写。

---

## 六、空数据保护

必须增加空数据保护。

如果 API 返回：

```text
None
空 DataFrame
空 list
缺少股票代码列
```

则：

```text
不要 DELETE；
不要 INSERT；
保留旧记录；
记录 warning；
继续下一个板块。
```

日志示例：

```text
[WARN] 燃料电池 成分股为空，保留旧映射，跳过刷新
```

这个保护很重要，避免数据源临时异常导致某个板块被清空。

---

## 七、单板块失败保护

单个板块失败不能导致整个 mapper 崩溃。

要求：

```text
1. 单板块 try/except；
2. 失败时 rollback 当前板块；
3. 记录 failed_count；
4. 继续下一个板块；
5. 最终 summary 输出失败板块数。
```

日志示例：

```text
[ERROR] 燃料电池 刷新失败：xxx，已回滚该板块，继续下一个
```

---

## 八、统计与耗时要求

必须增加耗时统计。

建议使用：

```python
import time
start = time.time()
...
elapsed = time.time() - start
```

输出至少包括：

### 行业映射统计

```text
行业映射完成：
- 板块数：496
- 成功刷新板块数：xxx
- 空数据跳过板块数：x
- 失败板块数：x
- 删除旧记录数：xxxxx
- 写入新记录数：xxxxx
- 耗时：xx 分 xx 秒
```

### 概念映射统计

```text
概念映射完成：
- 板块数：486
- 成功刷新板块数：xxx
- 空数据跳过板块数：x
- 失败板块数：x
- 删除旧记录数：xxxxx
- 写入新记录数：xxxxx
- 耗时：xx 分 xx 秒
```

### 全部映射统计

```text
全部映射完成：
- 总板块数：xxx
- 成功刷新总数：xxx
- 空数据跳过总数：x
- 失败总数：x
- 删除旧记录总数：xxxxx
- 写入新记录总数：xxxxx
- 总耗时：xx 分 xx 秒
```

不要只输出：

```text
本次写入 0 条
```

---

## 九、进度日志要求

保留当前进度日志，但改为刷新语义。

当前类似：

```text
[1/496] 燃料电池 - 已存在，跳过
```

改为：

```text
[1/496] 燃料电池 - 刷新完成，删除 123 条，写入 125 条，用时 1.8s
```

空数据：

```text
[2/496] 诊断服务 - 空数据，保留旧映射，跳过
```

失败：

```text
[3/496] 某板块 - 刷新失败，已回滚，继续
```

为了避免日志过大，可以继续每 50 个板块输出一次进度，但每个失败和空数据必须输出。

---

## 十、性能预期

修复后第一次全量刷新会比之前慢很多。

当前板块规模：

```text
行业板块：约 496 个
概念板块：约 486 个
合计：约 982 个板块
```

如果每个板块平均请求 1-3 秒，整体可能耗时：

```text
15 - 60 分钟
```

接口慢或限流时可能更久。

因此本轮需要输出真实耗时，为后续决定 cron 时间提供依据。

---

## 十一、cron 时间建议

当前 crontab 是：

```cron
0 9 * * 1 ... stock-mapper ...
```

修复后全量刷新可能较慢，后续建议改到低峰期，例如：

```cron
# 每周日 03:00 刷新板块映射
0 3 * * 0 cd /root/stock-ai-system && flock -n /tmp/stock-mapper.lock docker compose run --rm stock-mapper >> /root/stock-ai-system/logs/mapper.log 2>&1
```

或者：

```cron
# 每周一 06:00，开盘前留足时间
0 6 * * 1 cd /root/stock-ai-system && flock -n /tmp/stock-mapper.lock docker compose run --rm stock-mapper >> /root/stock-ai-system/logs/mapper.log 2>&1
```

本轮不要求修改服务器 crontab，但可以在最终建议中提示。

---

## 十二、验收命令

先本地编译：

```bash
python -m compileall analysis
```

定位 docker service：

```bash
docker compose config --services | grep mapper
```

服务器执行：

```bash
cd /root/stock-ai-system
docker compose run --rm stock-mapper
```

查看日志：

```bash
tail -n 160 /root/stock-ai-system/logs/mapper.log
```

日志中不应大面积出现：

```text
已存在，跳过
```

应该出现：

```text
刷新完成
删除旧记录
写入新记录
耗时
成功刷新板块数
空数据跳过板块数
失败板块数
```

---

## 十三、数据库验收 SQL

执行：

```sql
SELECT MAX(updated_at), COUNT(*)
FROM stock_board_map;
```

预期：

```text
MAX(updated_at) 接近本次 mapper 运行时间；
COUNT 正常，不是 0。
```

查看日期分布：

```sql
SELECT updated_at::date, COUNT(*)
FROM stock_board_map
GROUP BY updated_at::date
ORDER BY updated_at::date DESC
LIMIT 5;
```

预期：

```text
最新日期应为本次运行日期；
该日期下有大量记录。
```

检查 board_type 分布：

```sql
SELECT board_type, COUNT(*), MAX(updated_at)
FROM stock_board_map
GROUP BY board_type
ORDER BY board_type;
```

预期：

```text
行业和概念都有记录；
MAX(updated_at) 均接近本次运行时间。
```

检查总量是否异常：

```sql
SELECT COUNT(*)
FROM stock_board_map;
```

当前历史参考：

```text
COUNT = 84217
```

修复后 count 可以变化，但不应异常变成很小，例如几千或 0。

---

## 十四、日报验证

mapper 修复并成功运行后，下一次日报中的数据质量提示应不再出现：

```text
个股板块映射 8 天未更新，可能不准确。
```

如果仍出现，需要检查日报中判断更新时间的字段来源。

但本轮不改日报，只先修 mapper 刷新。

---

## 十五、预期 diff

理想 diff 只包含 mapper 相关文件，例如：

```text
analysis/xxx_mapper.py
```

实际文件名以 grep 结果为准。

不应该出现：

```text
entrypoint.sh
analysis/email_sender.py
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
scripts/evaluation_entrypoint.sh
sql/schema.sql
analysis/init_db.py
reports/
logs/
__pycache__/
.claude/
PRDs/
```

---

## 十六、提交要求

如果验收通过：

```bash
git add <mapper相关文件>
git commit -m "fix: refresh stock board mapping instead of skipping existing boards"
git push origin dev
```

不要提交：

```text
reports/
logs/
__pycache__/
.claude/
.env
PRDs/
```

---

## 十七、本轮通过标准

1. 找到“已存在，跳过”的 mapper 逻辑；
2. 不再因板块已存在而跳过刷新；
3. 每个板块刷新时 delete old + insert latest；
4. 空成分股时不删除旧数据；
5. 单板块失败不影响整个 mapper；
6. 输出行业/概念/总耗时；
7. 输出成功、失败、空数据跳过、删除、写入统计；
8. mapper 运行后 `stock_board_map.MAX(updated_at)` 更新到本次运行时间；
9. 行业和概念映射都能刷新；
10. stock_board_map 总量保持合理；
11. 不改日报；
12. 不改 selector；
13. 不改 evaluation；
14. 不改 email_sender；
15. 不改 entrypoint。


# V4-Evaluation Hotfix：行情缓存不足时自动暂缓 evaluation

## 当前问题背景

项目：`testStock`

当前 evaluation 自检邮件出现：

```text
观察池兑现与数据可信性检查

检查日期: 20260603
信号日期: 20260602
评价模式: daily

总信号数: 27
1 日实际评价: 0
1 日覆盖率: 0.0%
3 日实际评价: 0
3 日覆盖率: 0.0%

缺失原因:
  not_mature_1d: 14
  not_mature_3d: 14
  entry_date_not_found: 13
```

进一步查询 `stock_hist_kline`：

```sql
SELECT trade_date, COUNT(DISTINCT code)
FROM stock_hist_kline
WHERE trade_date IN ('20260602', '20260603')
GROUP BY trade_date
ORDER BY trade_date;
```

结果显示：

```text
2026-06-02: 76
2026-06-03: 0
```

最近行情缓存分布：

```text
2026-06-02: 76
2026-06-01: 420
2026-05-29: 489
2026-05-28: 594
...
```

说明：

```text
stock_hist_kline 是被动缓存，不是全市场日线库；
20260603 的 as_of 行情没有入库；
evaluation 在行情未准备好时仍继续运行，并发送了 0% 覆盖率邮件。
```

这封自检邮件不是策略评价失败，而是行情缓存不足导致 evaluation 不具备评价条件。

---

## 一、本轮目标

本轮只修复 evaluation 调度安全边界：

```text
行情缓存不足时，evaluation 应自动暂缓，不运行 watchlist_evaluation，不发送自检邮件。
```

本轮目标：

1. `evaluation_scheduler_check.py` 增加 `defer` 状态；
2. 当 `price_cache_coverage < 80%` 时返回 `status = "defer"`；
3. `evaluation_entrypoint.sh` 遇到 `defer` 时 `exit 0`；
4. `defer` 时不运行 `watchlist_evaluation --save-db`；
5. `defer` 时不运行 `evaluation_email_sender`；
6. 保留 `skip` / `error` / `ready` / `warning` 语义；
7. 不改日报；
8. 不改 selector；
9. 不改 email_sender；
10. 不改 evaluation 计算逻辑；
11. 不触发行情 API。

---

## 二、允许修改文件

允许修改：

```text
analysis/evaluation_scheduler_check.py
scripts/evaluation_entrypoint.sh
```

可选修改：

```text
docs/V4-EVALUATION-CRON.md
```

如果需要记录 defer 语义，可以只在文档中追加简短说明。

---

## 三、禁止修改文件

禁止修改：

```text
entrypoint.sh
analysis/email_sender.py
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_email_sender.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
sql/schema.sql
analysis/init_db.py
data/config.py
```

本轮不改日报链路，不改 evaluation 计算逻辑，不改邮件正文，不改数据库结构。

---

## 四、当前错误行为

当前 `evaluation_scheduler_check.py` 对行情缓存覆盖率低的情况大概率只返回：

```text
status = warning
```

然后 `scripts/evaluation_entrypoint.sh` 对 `warning` 继续执行：

```text
watchlist_evaluation --save-db
evaluation_query --latest
evaluation_email_sender --latest / --dry-run
```

导致在 `as_of_date` 行情未入库时，仍然生成：

```text
1 日覆盖率 0.0%
insufficient_data
```

并发送 evaluation 自检邮件。

这会造成误解：

```text
看起来像昨日观察池没有兑现；
实际上是 as_of 行情还没准备好。
```

---

## 五、目标状态语义

`evaluation_scheduler_check.py` 应输出以下状态：

### ready

可以运行 evaluation。

条件示例：

```text
as_of_date 是交易日；
signal_date 有 stock_signal；
price_cache_coverage >= 80%；
没有明显阻断问题。
```

### warning

可以运行 evaluation，但存在非阻断提示。

例如：

```text
已有同一 daily evaluation 记录；
重复运行会 upsert 覆盖；
其他不影响评价有效性的轻微提示。
```

### defer

暂缓运行 evaluation，但不是错误。

触发条件：

```text
as_of_date 是交易日；
signal_date 有 stock_signal；
但 price_cache_coverage < 80%。
```

含义：

```text
行情缓存尚未准备好，稍后再跑。
```

### skip

无需运行 evaluation。

例如：

```text
as_of_date 非交易日；
signal_date 无 stock_signal 数据。
```

### error

系统异常。

例如：

```text
数据库连接失败；
stock_signal 表不存在；
必要表结构异常。
```

---

## 六、scheduler_check 修改要求

在 `analysis/evaluation_scheduler_check.py` 中增加缓存覆盖率阈值：

```python
MIN_PRICE_CACHE_COVERAGE = 0.8
```

当计算得到：

```python
price_cache_coverage < MIN_PRICE_CACHE_COVERAGE
```

时：

```python
status = "defer"
```

并输出 warning / reason：

```text
as_of 行情缓存覆盖率不足，暂缓 evaluation。
```

JSON 输出示例：

```json
{
  "status": "defer",
  "signal_date": "20260602",
  "as_of_date": "20260603",
  "is_trade_day": true,
  "signal_count": 27,
  "existing_evaluation": false,
  "price_cache_coverage": 0.0,
  "warnings": [
    "as_of 行情缓存覆盖率 0.0%，低于 80%，暂缓 evaluation"
  ],
  "recommended_commands": []
}
```

注意：

```text
defer 时 recommended_commands 应为空，或者只给检查命令；
不要给 watchlist_evaluation --save-db 命令。
```

---

## 七、entrypoint 修改要求

修改：

```text
scripts/evaluation_entrypoint.sh
```

当前逻辑可能只处理：

```bash
status=skip -> exit 0
status=error -> exit 1
ready/warning -> continue
```

需要新增：

```bash
if [ "$STATUS" = "defer" ]; then
    echo "[DEFER] Scheduler check returned defer, price cache not ready. Exiting without evaluation."
    exit 0
fi
```

最终状态处理应为：

```text
skip  -> exit 0
defer -> exit 0
error -> exit 1
ready -> continue
warning -> continue
```

重要：

```text
defer 时不得运行 watchlist_evaluation；
defer 时不得运行 evaluation_query；
defer 时不得运行 evaluation_email_sender；
defer 时不得发送自检邮件。
```

---

## 八、终端输出要求

当 `AS_OF_DATE=20260603` 且 20260603 行情缓存为 0 时，输出应类似：

```text
=== Evaluation EntryPoint ===
AS_OF_DATE=20260603
SEND_EVAL_EMAIL=1

[1/4] Scheduler check
status=defer
signal_date=20260602

[DEFER] as_of 行情缓存覆盖率不足，暂缓 evaluation。
[DONE] evaluation workflow deferred.
```

不应出现：

```text
[2/4] Run watchlist_evaluation
[3/4] Query latest evaluation
[4/4] Evaluation email
```

---

## 九、邮件行为要求

当 status = defer 时：

```text
不发送 evaluation 自检邮件。
```

原因：

```text
此时没有有效 evaluation 结果；
发送 0% 覆盖率邮件容易误导。
```

如果未来需要发送“调度暂缓通知”，可以单独设计，但本轮不做。

本轮只要求：

```text
defer 不发邮件。
```

---

## 十、验收命令

### 1. 编译

```bash
python -m compileall analysis
```

### 2. 直接检查 scheduler

以当前异常日期验证：

```bash
python -m analysis.evaluation_scheduler_check --as-of 20260603
python -m analysis.evaluation_scheduler_check --as-of 20260603 --json
```

预期：

```text
status = defer
signal_date = 20260602
price_cache_coverage = 0.0 或低于 80%
recommended_commands 为空或不包含 watchlist_evaluation --save-db
```

### 3. entrypoint 验证 defer

```bash
AS_OF_DATE=20260603 SEND_EVAL_EMAIL=1 bash scripts/evaluation_entrypoint.sh
```

预期：

```text
status=defer
exit 0
不运行 watchlist_evaluation
不运行 evaluation_email_sender
不发送邮件
```

### 4. 正常日期回归

使用已知正常日期：

```bash
AS_OF_DATE=20260529 SEND_EVAL_EMAIL=0 bash scripts/evaluation_entrypoint.sh
```

预期：

```text
status=ready 或 warning
watchlist_evaluation 正常运行
evaluation_query 正常运行
evaluation_email_sender dry-run
```

### 5. 非交易日回归

```bash
AS_OF_DATE=20260531 bash scripts/evaluation_entrypoint.sh
```

预期：

```text
status=skip
exit 0
不运行 evaluation
不发送邮件
```

---

## 十一、数据库验收

确认 defer 不新增新的 evaluation 记录：

```sql
SELECT COUNT(*)
FROM watchlist_evaluation_summary
WHERE eval_mode = 'daily'
  AND signal_date = '20260602'
  AND as_of_date = '20260603';
```

如果 hotfix 前已经生成过记录，数量不会增加。

如需更严谨，可先记录修复前 count，运行 defer 后再查 count，应保持不变。

---

## 十二、预期 diff

理想 diff：

```text
analysis/evaluation_scheduler_check.py
scripts/evaluation_entrypoint.sh
```

可选：

```text
docs/V4-EVALUATION-CRON.md
```

不应该出现：

```text
entrypoint.sh
analysis/email_sender.py
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_email_sender.py
sql/schema.sql
analysis/init_db.py
reports/
logs/
__pycache__/
.claude/
PRDs/
```

---

## 十三、提交要求

如果验收通过：

```bash
git add analysis/evaluation_scheduler_check.py scripts/evaluation_entrypoint.sh
git commit -m "fix: defer evaluation when price cache is not ready"
git push origin dev
```

如果新增或修改文档：

```bash
git add docs/V4-EVALUATION-CRON.md
git commit -m "docs: document evaluation defer behavior"
git push origin dev
```

不要提交：

```text
reports/
logs/
__pycache__/
.claude/
.env
PRDs/
```

---

## 十四、本轮通过标准

1. `price_cache_coverage < 80%` 时 scheduler 返回 `defer`；
2. `defer` 时不推荐运行 `watchlist_evaluation --save-db`；
3. `evaluation_entrypoint.sh` 遇到 `defer` 时 exit 0；
4. `defer` 时不运行 watchlist_evaluation；
5. `defer` 时不运行 evaluation_query；
6. `defer` 时不运行 evaluation_email_sender；
7. `defer` 时不发送自检邮件；
8. 非交易日 skip 行为不受影响；
9. 正常日期 ready/warning 行为不受影响；
10. 不改日报；
11. 不改 selector；
12. 不改 evaluation 计算逻辑；
13. 不改邮件正文；
14. 不改数据库结构。
