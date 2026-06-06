# V4-Report Unified Daily Pack：取消双版本日报，只保留一份主日报，并增强交易环境展示

## 0. 本轮目标

项目：`testStock`

本轮目标是一次性收口日报展示层，不再拆成很多小轮。

核心目标：

```text
1. 取消“小白版 / 专业版”双日报。
2. 只保留一份主日报：daily_report_YYYYMMDD.md。
3. 重构日报结构，使其更像一份可读复盘，而不是模块输出合集。
4. 参考用户提供的盘面分析 Markdown 文件的结构。
5. 把“弱市不做、赚钱效应、情绪周期、龙头、跟风、龙回头、守株待兔、仓位管理”等理念融入日报展示。
6. 保留观察池中用户认为直观的字段：买入价、目标价、止损逻辑、能买、不能买、仓位。
7. 新增交易环境判断、弱市不做检查、情绪周期解释、主线结构分层、观察池模式标签、明日验证清单。
8. 邮件附件减少，不再默认发送 pro report、json、alias report。
9. 本轮只做展示层增强，不改变选股结果、策略计算、数据库结构、evaluation、mapper、entrypoint、crontab。
```

本轮属于：

```text
presentation-layer refactor
```

不是：

```text
strategy refactor
selector refactor
database refactor
evaluation refactor
pipeline refactor
```

---

## 1. 当前问题

当前系统每天生成：

```text
daily_report_YYYYMMDD.md
daily_report_YYYYMMDD_pro.md
```

主要问题：

```text
1. 小白版和专业版重合度太高；
2. 两份报告都在重复讲市场、板块、观察池、风险；
3. 邮件附件过多，阅读成本高；
4. 两套模板容易产生口径冲突；
5. 日报结构像模块输出拼接，不像给人读的复盘报告；
6. 数据质量、板块趋势、主线、观察池、风险提示的顺序不符合阅读习惯；
7. 动态标签如“东方财富热股 / 昨日涨停”可能被误放进主线；
8. 仓位口径可能出现前后不一致；
9. 市场综合评分、短线情绪评分等术语可能混用；
10. 交易理念没有系统转化成日报中的判断表和模式标签。
```

用户明确要求：

```text
不要小白版和专业版。
只做一个日报。
内容参考用户提供的 2026-06-03 盘面分析 md 文件。
把弱市不做、赚钱效应、情绪周期、龙头、跟风、龙回头、守株待兔、仓位管理等理念融入日报展示。
但不要大幅改底层逻辑，不要改崩系统。
```

---

## 2. 硬边界

### 2.1 允许修改文件

允许修改：

```text
analysis/daily_report.py
analysis/report_renderer.py
analysis/email_sender.py
```

如果必须做主线动态标签过滤，可小范围修改：

```text
analysis/theme_detector.py
```

如果需要新增纯展示辅助函数，允许新增：

```text
analysis/report_insights.py
```

但 `report_insights.py` 只能做：

```text
1. 读取已有 report_context / daily_summary / trade_plan / watchlist 数据；
2. 生成日报展示用的判断标签；
3. 渲染 Markdown 文本；
4. 不写数据库；
5. 不改 stock_signal；
6. 不改 selector；
7. 不改 trade_plan；
8. 不调行情 API。
```

### 2.2 禁止修改文件

禁止修改：

```text
entrypoint.sh
scripts/evaluation_entrypoint.sh
analysis/selector.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
analysis/stock_board_mapper.py
analysis/init_db.py
sql/schema.sql
data/config.py
docker-compose.yml
Dockerfile
```

原则上不改：

```text
选股逻辑
观察池入选逻辑
策略评分逻辑
trade_plan 生成逻辑
evaluation 逻辑
mapper 逻辑
数据库结构
pipeline 顺序
crontab
```

如必须调整 `pipeline_check.py` 或 `report_regression_check.py`，只允许做：

```text
daily_report_pro 不再作为 critical 产物。
```

不要扩展其他功能。

---

## 3. 产物目标

### 3.1 默认只生成一份主日报

最终默认生成：

```text
reports/daily/daily_report_YYYYMMDD.md
```

日报标题：

```text
# A股每日复盘 | YYYY-MM-DD（周X）
```

不再默认生成：

```text
daily_report_YYYYMMDD_pro.md
```

### 3.2 兼容旧参数

为了不打断旧调用，`daily_report.py` 暂时仍兼容：

```bash
python -m analysis.daily_report --mode both --date YYYYMMDD
python -m analysis.daily_report --mode beginner --date YYYYMMDD
python -m analysis.daily_report --mode pro --date YYYYMMDD
```

但内部行为调整为：

```text
beginner / pro / both 都生成同一份主日报 daily_report_YYYYMMDD.md。
不再默认生成 daily_report_YYYYMMDD_pro.md。
如果暂时保留 pro 旧文件生成，必须标记为 legacy，并且 email_sender 不默认发送。
```

推荐第一阶段：

```text
代码兼容旧 mode 参数；
实际只生成并发送主日报；
不彻底删除旧参数，避免 entrypoint 或其他脚本报错。
```

---

## 4. 新主日报总结构

主日报参考用户提供的盘面分析 md 的阅读顺序：

```text
先摘要
再交易环境
再市场
再弱市不做
再情绪
再资金
再主线
再风险
再机会
再观察池
再明日验证
最后纪律和数据可信度
```

目标结构：

```markdown
---
date: YYYY-MM-DD
weekday: 周X
market_score: xx.x
market_status: xxx
sentiment_score: xx.x
sentiment_stage: xxx
position_cap: x成
data_confidence: xx/100
tags: [A股复盘, 结构分化, 观察池]
---

# A股每日复盘 | YYYY-MM-DD（周X）

## 0. 今日摘要

## 1. 交易环境判断

## 2. 市场状态

## 3. 弱市不做检查

## 4. 情绪周期与赚钱效应

## 5. 资金流向

## 6. 主线分析

## 7. 弱市例外扫描

## 8. 风险提示

## 9. 机会观察

## 10. 观察池

## 11. 明日验证清单

## 12. 纪律

## 13. 数据可信度

## 附录
```

---

## 5. 指标字典与取值规则

本节是硬规则，避免实现时自由发挥。

### 5.1 市场综合评分 `market_score`

```text
含义：
用于概括当日市场整体状态的综合评分。

显示名称：
市场综合评分

禁止写法：
情绪评分
市场情绪评分

取值来源：
优先从 daily_summary.json / report_context.market.market_score / 现有 market 字段读取。

展示方式：
xx.x / 100

解释方式：
不是单独的短线情绪分，而是市场综合状态，包括指数、宽度、成交额、涨跌停、风险等综合结果。
```

判断标签建议：

```text
>= 80：市场偏强
65 - 80：结构活跃 / 可观察
50 - 65：震荡分化
35 - 50：偏弱
< 35：弱市 / 退潮
```

如果系统已有 `market_status`，优先使用已有状态，不重新硬算。

---

### 5.2 市场状态 `market_status`

```text
含义：
对市场综合环境的文字描述。

取值来源：
优先使用 report_context.market.market_status 或 daily_summary 中已有 market_status。

展示示例：
宽度偏弱
结构分化
震荡修复
市场偏强
退潮
弱市
```

不能只根据指数涨跌判断。

如果指数上涨但下跌家数明显多于上涨家数，应写：

```text
指数偏强，但个股宽度偏弱，属于结构分化。
```

---

### 5.3 短线情绪评分 `sentiment_score`

```text
含义：
短线赚钱效应与情绪周期评分。

显示名称：
短线情绪评分

取值来源：
report_context.sentiment.sentiment_score
或 daily_summary.sentiment_score
或现有情绪模块输出。

展示方式：
xx.x / 100
```

必须和 `market_score` 区分：

```text
market_score = 市场综合评分
sentiment_score = 短线情绪评分
```

---

### 5.4 短线情绪阶段 `sentiment_stage`

```text
含义：
短线市场处于什么情绪阶段。

取值来源：
优先用现有 sentiment_stage。
如果没有，可根据 sentiment_score 映射。
```

建议映射：

```text
>= 80：高潮
65 - 80：过热
50 - 65：升温
35 - 50：平衡 / 分歧
20 - 35：退潮
< 20：冰点
```

日报展示时应写：

```text
短线情绪阶段：升温
```

而不是只写一个分数。

---

### 5.5 赚钱效应 `profit_effect`

```text
含义：
追涨资金是否能赚钱，热点是否有持续性。

取值来源：
用现有数据轻量判断，不新增复杂策略。
```

可参考指标：

```text
昨日涨停今日表现
昨日涨停上涨率
涨停家数
连板高度
3板及以上数量
炸板率
成交额趋势
主线板块持续性
```

建议显示：

```text
赚钱效应：强 / 尚可 / 分化 / 弱 / 退潮
```

建议规则：

```text
强：
涨停家数较多，昨日涨停表现好，连板高度打开，炸板率不高。

尚可：
涨停家数正常，昨日涨停仍有溢价，但市场宽度一般。

分化：
少数主线赚钱，其他方向亏钱。

弱：
昨日涨停表现差，炸板率高，连板高度下降。

退潮：
强势股补跌，昨日涨停大面积低开低走，连板数量明显减少。
```

缺数据时：

```text
赚钱效应：数据不足，仅参考涨停家数和市场宽度。
```

---

### 5.6 弱市不做触发数 `weak_market_trigger_count`

```text
含义：
判断今天是否属于“不适合操作”的弱市环境。

展示方式：
弱市不做：触发 x/5
```

建议 5 个检查项：

| 检查项     | 取值方式           | 触发条件                |
| ------- | -------------- | ------------------- |
| 绿盘占比    | 下跌家数 / 全市场家数   | > 60%               |
| 涨跌停比    | 涨停家数 / 跌停家数    | < 1                 |
| 昨日涨停表现差 | 昨涨停今日上涨率或平均涨幅  | 上涨率 < 40% 或平均涨幅 < 0 |
| 连板高度弱   | 最高连板 / 3板以上数量  | 3板以上极少或为 0          |
| 量能萎缩    | 今日成交额 vs 近3日均值 | 明显缩量，例如 < -5%       |

判断结论：

```text
0-1 条：非弱市，可正常观察
2 条：结构分化，轻仓观察
3 条：偏弱，谨慎或极轻仓
4-5 条：弱市，原则上不做
```

注意：

```text
弱市不做只影响日报展示和风险提示；
本轮不直接修改 selector 或 trade_plan。
```

---

### 5.7 绿盘占比 `green_ratio`

```text
含义：
全市场下跌股票占比。

计算：
下跌家数 / (上涨家数 + 下跌家数 + 平盘家数)

展示：
绿盘占比：66.45%

判断：
> 60%：多数个股下跌，宽度偏弱
> 70%：亏钱效应较强
> 80%：极弱
```

如果没有平盘家数，可以用：

```text
下跌家数 / (上涨家数 + 下跌家数)
```

并在代码注释里说明是近似口径。

---

### 5.8 涨跌比 `up_down_ratio`

```text
含义：
上涨家数和下跌家数的比例，用于判断市场宽度。

计算：
上涨家数 / 下跌家数

展示：
涨跌比：0.48

判断：
> 1.2：宽度较好
0.8 - 1.2：均衡
0.5 - 0.8：偏弱
< 0.5：明显偏弱
```

---

### 5.9 涨跌停比 `limit_up_down_ratio`

```text
含义：
涨停和跌停的力量对比。

计算：
涨停家数 / max(跌停家数, 1)

展示：
涨跌停比：6.6

判断：
> 3：短线仍有活跃度
1 - 3：正常
< 1：跌停压过涨停，弱市信号
```

---

### 5.10 炸板率 `failed_limit_ratio`

```text
含义：
涨停封板失败比例，反映高位分歧和追涨风险。

取值来源：
优先使用现有炸板率字段。
如果没有，不新增复杂计算，显示 N/A。

展示：
炸板率：50%

判断：
< 25%：封板质量较好
25% - 40%：正常分歧
40% - 60%：分歧偏大
> 60%：追涨风险高
```

---

### 5.11 成交额趋势 `amount_trend_3d`

```text
含义：
市场量能是否持续放大或萎缩。

取值来源：
已有 market turnover / amount 数据。
优先用全市场成交额。

计算方式建议：
(today_amount - avg(amount of previous 3 trading days)) / avg(previous 3 trading days)

展示：
成交额：31531亿
3日成交额趋势：-5.62%

判断：
> +5%：放量
-5% 到 +5%：平量
< -5%：缩量
```

展示解释：

```text
放量：资金活跃度增强
缩量：资金活跃度下降，仓位不宜放大
```

---

### 5.12 主线强度 `theme_strength`

```text
含义：
某个板块/概念是否能作为有效主线。

取值来源：
现有 board_trend_summary / theme_detector / board_amount_ratio / report_context.themes。
```

判断应结合：

```text
3日资金流入
5日资金流入
涨幅表现
板块内龙头活跃度
是否动态标签
是否低价值标签
```

展示标签：

```text
强主线
观察主线
辅助题材
动态标签
退潮方向
```

基本规则：

```text
强主线：
3日和5日资金均流入，且板块涨幅/龙头表现较强。

观察主线：
短期流入，但持续性不足或情绪偏热。

辅助题材：
能给个股加分，但不单独作为主线。

动态标签：
昨日涨停、东方财富热股、近期新高等，不作为主线。

退潮方向：
3日/5日资金流出，或热点明显降温。
```

---

### 5.13 动态标签 `dynamic_labels`

以下标签不得进入有效主线：

```text
东方财富热股
昨日涨停
昨日首板
昨日连板
昨日高振幅
最近多板
近期新高
历史新高
融资融券
QFII重仓
MSCI中国
富时罗素
创业板综
中证500
HS300_
ST板块
```

展示方式：

```text
动态标签：仅用于识别短线热度，不作为主线方向。
```

---

### 5.14 模式标签 `pattern_tag`

```text
含义：
给观察池个股加上“它属于哪种交易模式”的解释标签。
```

注意：

```text
第一版只做展示标签，不作为硬筛选策略。
不要改变股票池。
```

可用标签：

```text
龙头确认
板块龙头
超强势股
跟风补涨
龙回头候选
守株待兔候选
涨停启明星候选
打板质量较高
高风险复盘
待确认
```

轻量判定建议：

```text
龙头确认：
板块强 + 个股涨幅/成交额/辨识度靠前 + 有带动性描述。

跟风补涨：
同主线内低位、涨幅较低，但板块龙头赚钱效应仍在。

龙回头候选：
前期强势股 / 龙头股，出现回调，未破关键结构。

守株待兔候选：
前期有大阳或涨停，回调缩量，仍在热点范围内。

涨停启明星候选：
弱市/退潮环境下仍能连板或逆势涨停。

打板质量较高：
涨停强度、换手、量能、股性较好。
```

如果字段不足，不要强行判断，写：

```text
模式标签：待确认
```

---

### 5.15 仓位上限 `position_cap`

```text
含义：
明日总仓位上限。

取值来源：
只能来自 trade_plan。
不得由日报展示层重新计算覆盖。
```

展示：

```text
总仓位上限：1成
单票上限：1成
```

硬规则：

```text
日报全文所有仓位数字不得超过 trade_plan 上限。
如果 trade_plan 总仓位为 1成，观察池里不能出现 2成、3成、3-5成。
```

允许写：

```text
仓位：不超过计划上限
仓位：0.5-1成
```

---

### 5.16 数据可信度 `data_confidence`

```text
含义：
本日报数据基础是否可靠。

取值来源：
已有 quality / data_quality / report_context.quality 字段。

展示：
报告可信度：80 / 100
```

解释必须写清楚影响范围：

```text
主要扣分：
- 部分均线数据缺失
- 个别行情缓存不足

影响范围：
- 市场和板块判断：影响较小
- 个股观察池排序：可能受影响
```

不要只写一个分数。

---

### 5.17 明日验证清单 `tomorrow_validation_items`

```text
含义：
把今天日报里的判断转成明天要验证的问题。

生成方式：
基于今日主线、风险、观察池、市场状态生成 3-5 条。
```

示例：

```text
1. CPO / 光通信能否继续承接；
2. 市场宽度能否修复；
3. 资源品高潮后是否回落；
4. 今日强势股是否出现亏钱效应；
5. 高风险复盘层是否继续强于可观察层。
```

要求：

```text
不要超过 5 条。
要能被第二天 evaluation 或人工复盘验证。
```

---

## 6. 主日报各模块详细要求

### 6.1 今日摘要

日报第一屏必须直接给结论。

建议格式：

```markdown
## 0. 今日摘要

| 项目 | 结论 |
|------|------|
| 市场综合评分 | xx.x / 100 |
| 市场状态 | 宽度偏弱 / 结构分化 / 升温 / 退潮 |
| 短线情绪阶段 | 升温 / 平衡 / 过热 / 退潮 |
| 明日操作态度 | 只观察 / 轻仓试错 / 谨慎参与 |
| 总仓位上限 | x成 |
| 数据可信度 | xx / 100 |

**一句话结论：**
指数和成交额偏强，但个股宽度偏弱；资金集中在 CPO / 光通信 / AI硬件等方向，明日适合在计划仓位内观察主线分歧承接，不适合盲目追高。
```

要求：

```text
1. 第一屏不要放完整数据质量表；
2. 第一屏不要放长表格；
3. 先告诉用户今天市场该怎么理解；
4. market_score 必须叫“市场综合评分”，不能叫“情绪评分”。
```

---

### 6.2 交易环境判断

把理念文档转成直观判断，不写长篇理论。

```markdown
## 1. 交易环境判断

| 维度 | 当前状态 | 解释 |
|------|----------|------|
| 赚钱效应 | 升温 / 平衡 / 退潮 | 追涨是否仍有溢价 |
| 弱市不做 | 触发 x/5 | 是否应该空仓或极轻仓 |
| 市场量能 | 放量 / 缩量 | 资金活跃度 |
| 主线集中度 | 集中 / 分散 | 是否只有少数方向赚钱 |
| 仓位边界 | x成 | 来自 trade_plan |

**本段结论：**
今日不是普涨行情，而是结构分化行情。只有主线方向存在赚钱效应，其他方向以观察为主。
```

实现要求：

```text
只使用已有数据做解释；
不要新增策略计算；
不要改变 trade_plan；
仓位只展示 trade_plan 已经给出的上限。
```

---

### 6.3 市场状态

展示指数、成交额、涨跌家数等基础信息。

```markdown
## 2. 市场状态

### 2.1 大盘指数

| 指数 | 收盘 | 涨跌幅 | 备注 |
|------|------|--------|------|
| 上证指数 | xxx | +x.xx% | xxx |
| 深证成指 | xxx | +x.xx% | xxx |
| 创业板指 | xxx | +x.xx% | xxx |

### 2.2 市场宽度

| 指标 | 数值 | 判断 |
|------|------|------|
| 上涨家数 | xxx | xxx |
| 下跌家数 | xxx | xxx |
| 涨停家数 | xxx | xxx |
| 跌停家数 | xxx | xxx |
| 炸板率 | xx% | xxx |
| 绿盘占比 | xx% | xxx |
| 成交额 | xxxx亿 | xxx |

**本段结论：**
指数表现与个股宽度是否一致；如果指数强但下跌家数多，必须明确写“指数强不代表赚钱效应普遍”。
```

要求：

```text
避免简单写“市场整体偏强”掩盖宽度偏弱。
如果上涨家数明显少于下跌家数，要明确提示结构分化。
```

---

### 6.4 弱市不做检查

固定检查表，每天出现。

```markdown
## 3. 弱市不做检查

| 检查项 | 当前值 | 是否触发 | 解读 |
|--------|--------|----------|------|
| 绿盘占比 > 60% | xx% | ✅/❌ | 多数个股是否下跌 |
| 涨跌停比 < 1 | xx | ✅/❌ | 跌停是否压过涨停 |
| 昨日涨停表现差 | xx | ✅/❌ | 追涨是否亏钱 |
| 3板以上稀少 | x只 | ✅/❌ | 情绪高度是否消失 |
| 量能持续萎缩 | xx | ✅/❌ | 资金是否撤离 |

**结论：**
触发 x/5 条件 → 非典型弱市 / 弱市 / 结构分化 / 可轻仓观察。

**操作边界：**
总仓位不超过 trade_plan 上限。
```

要求：

```text
弱市不做只是展示判断，不直接改策略。
如果触发较多条件，要提示空仓或极轻仓。
如果只有部分触发，要提示结构分化。
```

---

### 6.5 情绪周期与赚钱效应

解释 sentiment_score，不只给分数。

```markdown
## 4. 情绪周期与赚钱效应

| 指标 | 当前值 | 信号 |
|------|--------|------|
| 短线情绪评分 | xx.x / 100 | 升温 / 平衡 / 过热 / 退潮 |
| 昨日涨停今日表现 | xx | 赚钱效应强弱 |
| 连板高度 | x板 | 高度是否打开 |
| 3板以上数量 | x只 | 情绪高度 |
| 涨停家数 | x家 | 活跃度 |
| 炸板率 | xx% | 分歧程度 |
| 成交额趋势 | +x% / -x% | 量能趋势 |

**本段结论：**
赚钱效应是否存在？是普遍赚钱效应，还是集中在少数主线？
```

要求：

```text
sentiment_score 才能叫短线情绪评分；
market_score 不能叫情绪评分。
```

---

### 6.6 资金流向

参考用户 md 的资金流向结构，但不要过长。

默认主日报只展示 TOP5，完整 TOP10 / TOP20 放附录或 debug。

```markdown
## 5. 资金流向

### 5.1 行业资金流入 TOP5

| 行业 | 3日变化 | 5日变化 | 判断 |
|------|---------|---------|------|

### 5.2 行业资金流出 TOP5

| 行业 | 3日变化 | 5日变化 | 判断 |
|------|---------|---------|------|

### 5.3 概念资金流入 TOP5

| 概念 | 3日变化 | 5日变化 | 判断 |
|------|---------|---------|------|

### 5.4 概念资金流出 TOP5

| 概念 | 3日变化 | 5日变化 | 判断 |
|------|---------|---------|------|

### 5.5 跷跷板结论

1. xxx → xxx
2. xxx → xxx
3. xxx → xxx

**本段结论：**
资金正在从哪些方向撤出，又流向哪些方向。
```

要求：

```text
主日报不要堆过多表格；
表格后必须有本段结论；
动态标签不得混入主线判断。
```

---

### 6.7 主线分析

主线必须分层：

```markdown
## 6. 主线分析

### 6.1 有效主线

| 主线 | 强度 | 依据 | 风险 |
|------|------|------|------|
| CPO / 光通信 | 强主线 | 资金3日/5日共振，龙头活跃 | 情绪偏热 |
| 通信设备 | 强主线 | 行业资金持续流入 | 不追高 |
| 半导体 / 先进封装 | 观察主线 | 龙虎榜与资金共振 | 内部分化 |

### 6.2 辅助题材

| 题材 | 作用 | 说明 |
|------|------|------|
| 央企 | 辅助加分 | 不单独作为主线 |
| 业绩增长 | 辅助加分 | 配合主线更有效 |

### 6.3 动态标签

以下只作为热度标签，不作为主线：

| 标签 | 说明 |
|------|------|
| 昨日涨停 | 动态标签 |
| 东方财富热股 | 动态标签 |
| 最近多板 | 动态标签 |

**主线结论：**
当前真正可跟踪的是 xxx；xxx 只是动态标签，不进入主线排名。
```

必须过滤出“有效主线”的标签：

```text
东方财富热股
昨日涨停
昨日首板
昨日连板
昨日高振幅
最近多板
近期新高
历史新高
融资融券
QFII重仓
MSCI中国
富时罗素
创业板综
中证500
HS300_
ST板块
```

这些只能放“动态标签 / 辅助标签”，不能进入：

```text
今日主线
强主线
观察主线
上涨主线
```

---

### 6.8 弱市例外扫描

这个模块不必每天写很长，只做简短判断。

```markdown
## 7. 弱市例外扫描

### 7.1 涨停启明星

| 条件 | 当前值 | 是否满足 |
|------|--------|----------|
| 连续2天普跌 | 是/否 | ✅/❌ |
| 3板以上稀少 | 是/否 | ✅/❌ |
| 逆势连板股存在 | 是/否 | ✅/❌ |
| 大盘止跌信号 | 是/否 | ✅/❌ |

结论：暂未满足 / 出现候选，仅观察。

### 7.2 转势灵魂板

如果无明显候选，写：

今日暂无明确转势灵魂板候选。
```

要求：

```text
不要把启明星当作新策略强推；
只作为弱市环境下的例外扫描。
```

---

### 6.9 风险提示

风险分层写，不要混成一段。

```markdown
## 8. 风险提示

### 8.1 市场风险

- xxx

### 8.2 板块风险

- xxx

### 8.3 情绪风险

- xxx

### 8.4 数据风险

- xxx
```

风险语言可以使用：

```text
赚钱效应弱化
亏钱效应蔓延
强势股补跌
持筹者兑现压力
持币者承接不足
量能萎缩
高潮后不追
```

---

### 6.10 机会观察

用户希望保留直观字段：

```text
买入价
目标价
止损逻辑
能买
不能买
仓位
```

因此不要强行改成“观察条件 / 失效条件”。

但模块名称不要叫：

```text
推荐买入
强烈买入
必买
```

建议叫：

```text
机会观察
观察池明细
重点观察标的
```

示例：

```markdown
## 9. 机会观察

### 9.1 AI硬件 / CPO

- 逻辑：资金从 AI 软件端流出，转向硬件端；
- 观察重点：CPO / 光通信 / 光芯片 / 先进封装；
- 风险：通信设备情绪偏热，不追高。

### 9.2 资源品

- 逻辑：资金短期流入明显；
- 风险：油气 / 煤炭 / 小金属可能进入高潮；
- 策略：不追高，等回调。
```

---

### 6.11 观察池

观察池保留用户喜欢的字段，但新增“模式标签”。

```markdown
## 10. 观察池

### 10.1 可观察

| 股票 | 方向 | 模式标签 | 买入价 | 目标价 | 止损逻辑 | 仓位 | 能买 | 不能买 |
|------|------|----------|--------|--------|----------|------|------|--------|

### 10.2 谨慎观察

| 股票 | 方向 | 模式标签 | 买入价 | 目标价 | 止损逻辑 | 仓位 | 能买 | 不能买 |
|------|------|----------|--------|--------|----------|------|------|--------|

### 10.3 高风险复盘

| 股票 | 方向 | 模式标签 | 高风险原因 | 只复盘不买原因 |
|------|------|----------|------------|----------------|

### 10.4 过滤 / 不可交易

| 股票 | 原因 |
|------|------|
```

模式标签可包括：

```text
龙头确认
板块龙头
超强势股
跟风补涨
龙回头候选
守株待兔候选
涨停启明星候选
打板质量较高
高风险复盘
待确认
```

模式标签第一版只基于已有字段做轻量判断，不作为硬策略筛选。

仓位要求：

```text
观察池中的任何仓位不得超过 trade_plan 给出的总仓位上限和单票上限。
如果 trade_plan 总仓位上限为 1成，则日报全文不得出现 2成、3成、3-5成等超过上限的仓位数字。
```

---

### 6.12 明日验证清单

这个模块非常重要，用于和 evaluation 形成闭环。

```markdown
## 11. 明日验证清单

1. CPO / 光通信能否继续承接；
2. 市场宽度能否修复；
3. 资源品高潮后是否回落；
4. 今日强势股是否出现亏钱效应；
5. 高风险复盘层是否继续强于可观察层。
```

要求：

```text
3-5 条即可；
不要写太长；
这些点第二天可由 evaluation 或人工复盘验证。
```

---

### 6.13 纪律

```markdown
## 12. 纪律

- 不追高；
- 总仓位不超过 trade_plan 上限；
- 弱市不做，结构分化只做核心方向；
- 高风险复盘票只复盘，不作为正常买入候选；
- 数据可信度不足时，只观察不下结论；
- 本报告用于自动化复盘、风险提示和观察池生成，不构成实盘买卖建议。
```

---

### 6.14 数据可信度

数据质量放后面，不抢第一屏。

```markdown
## 13. 数据可信度

| 项目 | 状态 | 说明 |
|------|------|------|
| 报告可信度 | xx / 100 | 可参考 / 谨慎参考 |
| 板块映射 | 正常 / 警告 | updated_at 是否本周 |
| 板块成交占比 | 正常 / 警告 | actual_board_date 是否当日 |
| 均线数据 | 正常 / 警告 | 缺失是否影响观察池 |
| 行情缓存 | 正常 / 警告 | 是否影响 evaluation |

**影响范围：**
- 不影响：xxx
- 可能影响：xxx
```

---

## 7. 邮件策略

### 7.1 邮件正文

邮件正文只放摘要，不粘完整日报。

结构：

```text
【A股每日复盘】YYYY-MM-DD

今日结论：
xxx

明日操作边界：
- 是否允许实盘：
- 总仓位上限：
- 单票上限：
- 操作态度：

主线方向：
- xxx
- xxx
- xxx

主要风险：
- xxx
- xxx

数据可信度：
- xx / 100
- 主要扣分项：

详细内容见附件。
```

### 7.2 默认附件

只默认发送：

```text
daily_report_YYYYMMDD.md
board_trend_tracker_YYYYMMDD.xlsx
```

可选发送：

```text
board_mapping_quality_YYYYMMDD.md
```

不默认发送：

```text
daily_report_YYYYMMDD_pro.md
board_mapping_quality_YYYYMMDD.json
board_alias_report_YYYYMMDD.md
report_debug_YYYYMMDD.md
```

---

## 8. pipeline_check / regression_check 兼容

如果当前 `pipeline_check.py` 或 `report_regression_check.py` 仍把 `daily_report_YYYYMMDD_pro.md` 当成关键产物，本轮可以小范围修改它们的检查口径，但不要扩展功能。

新口径：

```text
critical:
daily_report_YYYYMMDD.md
daily_summary_YYYYMMDD.json
trade_plan_YYYYMMDD.md/json
board_trend_summary_YYYYMMDD.json
board_mapping_quality_YYYYMMDD.json
pipeline_check_YYYYMMDD.json

non-critical:
board_trend_tracker_YYYYMMDD.xlsx
board_alias_report_YYYYMMDD.md
legacy pro report
```

如果修改 pipeline_check / regression_check，必须只改：

```text
pro report 不再 critical
```

不要做其他逻辑改造。

---

## 9. 缺数据降级规则

如果现有字段缺失，不要临时发明复杂算法。

统一规则：

```text
1. 有字段 → 展示和解释；
2. 字段不完整 → 显示 N/A 或“数据不足”；
3. 数据不足时说明影响范围；
4. 不为了展示指标去大改数据获取；
5. 不新增数据库字段；
6. 不调额外行情 API；
7. 不改变 selector / trade_plan / evaluation。
```

示例：

```text
炸板率：N/A
说明：当前数据源未提供炸板率，本节仅参考涨停家数和连板高度。
```

---

## 10. 验收命令

### 10.1 编译

```bash
python -m compileall analysis
```

### 10.2 历史日期回归

```bash
TRADE_DATE=20260603 bash entrypoint.sh
```

或容器：

```bash
TRADE_DATE=20260603 docker compose run --rm stock-report
```

### 10.3 检查输出

```bash
ls reports/daily/*20260603*
```

重点确认：

```text
daily_report_20260603.md 存在
daily_report_20260603.md 是新结构
daily_report_20260603_pro.md 不再默认生成，或不再默认发送
daily_summary_20260603.json 存在
trade_plan_20260603.md/json 存在
```

### 10.4 检查邮件附件

如果支持 dry-run：

```bash
python -m analysis.email_sender --date 20260603 --dry-run
```

如果没有 dry-run 参数，则用当前项目已有方式验证附件列表。

邮件默认附件应只有：

```text
daily_report_20260603.md
board_trend_tracker_20260603.xlsx
```

可选：

```text
board_mapping_quality_20260603.md
```

不应默认附：

```text
daily_report_20260603_pro.md
board_mapping_quality_20260603.json
board_alias_report_20260603.md
```

---

## 11. 内容验收标准

主日报必须满足：

```text
1. 只有一份主日报；
2. 不再区分“小白版 / 专业版”；
3. 第一屏是今日摘要；
4. 数据质量不在第一屏；
5. 有交易环境判断；
6. 有弱市不做检查；
7. 有情绪周期与赚钱效应解释；
8. 有资金流向本段结论；
9. 主线分为有效主线 / 辅助题材 / 动态标签；
10. 动态标签不得进入有效主线；
11. 观察池保留买入价 / 目标价 / 能买 / 不能买；
12. 观察池新增模式标签；
13. 仓位全文不超过 trade_plan 上限；
14. 有明日验证清单；
15. 有纪律和免责声明；
16. 数据可信度放后面，并说明影响范围；
17. market_score 必须叫市场综合评分；
18. sentiment_score 必须叫短线情绪评分；
19. 不得出现总仓位 1成但局部写 3-5成的冲突；
20. 不得把“东方财富热股 / 昨日涨停 / 最近多板”等写入有效主线。
```

---

## 12. 逻辑不变验收标准

本轮必须验证没有改到底层逻辑。

对同一日期运行前后对比：

```text
stock_signal 数量不应因为本轮变化而改变；
trade_plan 结果不应因为本轮变化而改变；
daily_summary 核心字段不应因为本轮变化而改变；
watchlist_evaluation 不受影响；
stock_board_mapper 不受影响；
entrypoint 执行顺序不变；
crontab 不变。
```

如发现：

```text
股票池数量变化
trade_plan 仓位变化
evaluation 结果变化
mapper 行为变化
entrypoint 顺序变化
```

说明动到底层逻辑，需要回滚检查。

---

## 13. 预期 diff

理想 diff：

```text
analysis/daily_report.py
analysis/report_renderer.py
analysis/email_sender.py
```

可选：

```text
analysis/report_insights.py
analysis/theme_detector.py
analysis/pipeline_check.py
analysis/report_regression_check.py
```

其中：

```text
report_insights.py 只能做展示层判断；
theme_detector.py 只允许做动态标签展示过滤；
pipeline_check.py / report_regression_check.py 只允许调整 pro report 不再 critical。
```

不应该出现：

```text
entrypoint.sh
scripts/evaluation_entrypoint.sh
analysis/selector.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
analysis/stock_board_mapper.py
analysis/init_db.py
sql/schema.sql
data/config.py
docker-compose.yml
Dockerfile
reports/
logs/
__pycache__/
.env
```

---

## 14. 提交建议

如果验收通过：

```bash
git add analysis/daily_report.py analysis/report_renderer.py analysis/email_sender.py
```

如果新增展示辅助文件：

```bash
git add analysis/report_insights.py
```

如果小改 theme detector：

```bash
git add analysis/theme_detector.py
```

如果调整 pro report 不再 critical：

```bash
git add analysis/pipeline_check.py analysis/report_regression_check.py
```

提交：

```bash
git commit -m "refactor: consolidate daily report into unified template"
git push origin dev
```

不要提交：

```text
reports/
logs/
__pycache__/
.env
.claude/
临时验证脚本
```

---

## 15. 本轮通过标准

本轮完成后，系统应达到：

```text
1. 每天只需要读一份 daily_report_YYYYMMDD.md；
2. 邮件不再默认附 pro report；
3. 日报第一屏清晰；
4. 弱市不做、赚钱效应、情绪周期、仓位管理等理念以判断表形式出现；
5. 龙头、跟风、龙回头、守株待兔等理念以观察池模式标签出现；
6. 买入价 / 目标价 / 能买 / 不能买保留；
7. 仓位不冲突；
8. 动态标签不再误判为主线；
9. 数据质量后置但不缺失；
10. evaluation / mapper / selector / entrypoint / crontab 均不受影响；
11. 日报从“模块输出合集”变成“可读复盘报告”。
```
