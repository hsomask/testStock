# V4-Report Display Polish Pack：日报展示优化，不改调度、不改策略

## 0. 本轮目标

本轮只做**日报展示优化**，不做调度调整，不接入 evaluation T+1，不改底层策略。

核心目标：

```text
1. 只保留一份主日报 daily_report_YYYYMMDD.md；
2. 取消小白版 / 专业版双报告展示；
3. 优化日报可读性，让报告从“模块拼接”变成“可读复盘”；
4. 修复资金流向中概念标签混乱的问题；
5. 修复主线分析过于粗糙的问题；
6. 修复赚钱效应口径冲突；
7. 修复观察池重复展示；
8. 降级过度自信的模式标签；
9. 优化机会观察和风险提示；
10. 明确每个展示项的取值方式、降级规则和数据边界；
11. 不改 selector、trade_plan、evaluation、mapper、entrypoint、crontab、数据库结构。
```

本轮不做：

```text
1. 不调整调度；
2. 不让 evaluation 先于日报运行；
3. 不在日报中重新计算 T+1；
4. 不接 watchlist_evaluation_summary；
5. 不改 crontab；
6. 不改 evaluation_entrypoint；
7. 不新增数据库表；
8. 不新增行情 API 调用；
9. 不改变股票池；
10. 不改变 trade_plan 仓位。
```

后续第二步再做：

```text
调度调整：evaluation 先跑并落库，日报读取 T+1 摘要，最后发送日报邮件。
```

---

## 1. 当前日报主要展示问题

基于 `daily_report_20260604.md`，当前日报已经完成了单报告结构，但展示仍有这些问题：

```text
1. 概念 3日流入/流出 TOP5 里混入大量动态标签、指数标签、风格标签；
2. “昨日高振幅 / 东方财富热股 / 最近多板 / 近期新高 / 百日新高”被放在概念资金流入中，读者看不懂；
3. “机构重仓 / HS300_ / 权重股 / 中盘成长 / 上证180_”被放在概念资金流出中，也不是产业概念；
4. 主线分析直接写“今日无明显主线方向”，但行业资金流向中其实有电子、半导体、数字芯片设计、光学光电子等局部方向；
5. 短线情绪阶段写“过热”，但交易环境判断写“赚钱效应：弱”，容易口径冲突；
6. 弱市不做检查表达偏技术化，可读性一般；
7. 观察池里同一股票重复出现，例如同一只股票同时出现在“一次起爆”和“短线强势”；
8. 滚雪球趋势单独成节，与观察池重复，且章节编号不连续；
9. 多只 N字异动直接标成“龙回头候选”，标签可能过度自信；
10. 机会观察写“暂无明确主线方向”，但观察池和资金流向并非完全无方向；
11. 风险提示偏短，没有和板块、观察池、资金流出方向联动；
12. 数据可信度已有改善，但“全市场均线缺失”和“观察池均线覆盖正常”的影响范围还可以写得更清楚。
```

---

## 2. 硬边界

### 2.1 允许修改

```text
analysis/report_renderer.py
analysis/report_insights.py
analysis/daily_report.py
analysis/email_sender.py
```

如需做展示层主线分流，可小范围修改：

```text
analysis/theme_detector.py
```

如 pipeline 仍依赖 pro report，可小范围修改：

```text
analysis/pipeline_check.py
analysis/report_regression_check.py
```

但只允许改：

```text
daily_report_pro 不再作为 critical 产物。
```

### 2.2 禁止修改

```text
analysis/selector.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
analysis/stock_board_mapper.py
analysis/init_db.py
sql/schema.sql
entrypoint.sh
scripts/evaluation_entrypoint.sh
docker-compose.yml
Dockerfile
crontab
```

本轮禁止改变：

```text
1. 股票池生成逻辑；
2. 观察池分层逻辑；
3. trade_plan 生成逻辑；
4. evaluation 计算逻辑；
5. mapper 刷新逻辑；
6. 数据库结构；
7. pipeline 执行顺序；
8. 邮件调度顺序。
```

---

## 3. 本轮改动范围

### 3.1 report_insights.py

职责：

```text
纯展示解释层。
```

允许做：

```text
1. 概念标签分流；
2. 动态标签分类；
3. 赚钱效应降级解释；
4. 弱市不做可读化解释；
5. 主线分层展示；
6. 观察池展示去重辅助；
7. 模式标签降级；
8. 明日验证清单生成；
9. 数据可信度影响范围解释。
```

禁止做：

```text
1. 不写数据库；
2. 不调行情 API；
3. 不改变股票池；
4. 不改变 trade_plan；
5. 不改变 evaluation；
6. 不改变 selector 输出。
```

建议文件头加注释：

```python
"""
Presentation-only helpers for daily report rendering.

This module must not:
- mutate database records
- change stock selection
- change trade_plan
- call market data APIs
- write evaluation results
"""
```

### 3.2 report_renderer.py

职责：

```text
重构 Markdown 展示结构和章节内容。
```

允许做：

```text
1. 调整章节顺序；
2. 调整表格展示；
3. 合并重复观察池记录；
4. 增强本段结论；
5. 调整标题名称；
6. 减少长表格；
7. 把动态标签从产业概念表中分流。
```

禁止做：

```text
1. 不重写 market / board / watchlist / trade_plan 的计算逻辑；
2. 不重新筛选股票；
3. 不重新计算买入价/目标价/止损；
4. 不重新决定仓位；
5. 不重新计算 evaluation。
```

### 3.3 daily_report.py

职责：

```text
兼容旧 mode 参数，但统一生成一份主日报。
```

要求：

```text
--mode both / beginner / pro 继续可用；
内部统一生成 daily_report_YYYYMMDD.md；
不再默认生成 daily_report_YYYYMMDD_pro.md；
如果暂时保留 pro，必须为 legacy，不默认发送。
```

### 3.4 email_sender.py

职责：

```text
减少附件，邮件正文改摘要。
```

默认附件：

```text
daily_report_YYYYMMDD.md
board_trend_tracker_YYYYMMDD.xlsx
```

可选附件：

```text
board_mapping_quality_YYYYMMDD.md
```

不默认发送：

```text
daily_report_YYYYMMDD_pro.md
board_mapping_quality_YYYYMMDD.json
board_alias_report_YYYYMMDD.md
```

---

# 4. 展示优化取值规则

本轮日报展示优化必须明确每个展示项的取值来源、计算方式和降级规则。

总原则：

```text
有现成字段就读取；
能轻量计算就计算；
字段不足就 N/A / 数据不足；
不新增 API；
不新增数据库字段；
不改变 selector / trade_plan / evaluation。
```

---

## 4.1 概念资金流向分流取值规则

### 输入来源

从现有板块资金数据读取：

```text
board_ratio_changes
board_trend_summary
report_context.boards
```

或当前报告已经用于生成：

```text
行业 3日流入 TOP5
行业 3日流出 TOP5
概念 3日流入 TOP5
概念 3日流出 TOP5
```

的数据源。

本轮不新增数据源。

### 分流逻辑

原始概念列表按名称分成四类：

```text
产业概念
动态情绪标签
指数/风格标签
资金/机构属性标签
```

#### 动态情绪标签

匹配以下关键词或完整名称：

```text
东方财富热股
昨日涨停
昨日首板
昨日连板
昨日高振幅
最近多板
近期新高
百日新高
历史新高
```

#### 指数/风格标签

匹配以下关键词或完整名称：

```text
HS300_
上证180_
中证500
中盘成长
权重股
创业板综
ST板块
```

#### 资金/机构属性标签

匹配以下关键词或完整名称：

```text
机构重仓
QFII重仓
融资融券
MSCI中国
富时罗素
```

#### 产业概念

不属于上述三类的概念，暂时归为产业概念。

示例：

```text
CPO
芯片概念
5G
光纤概念
数据中心
AI PC
先进封装
商业航天
机器人
算力
光通信
半导体概念
```

### 展示规则

原来的：

```text
概念 3日流入 TOP5
概念 3日流出 TOP5
```

改为：

```text
产业概念 3日流入 TOP5
产业概念 3日流出 TOP5
动态/风格标签变化 TOP5
```

排序规则：

```text
产业概念流入：按 3日变化值从高到低；
产业概念流出：按 3日变化值从低到高；
动态/风格标签变化：按变化绝对值从高到低。
```

如果产业概念不足 5 个：

```text
展示实际数量，不要用动态标签补位。
```

如果产业概念为 0：

```text
显示：过滤动态标签后，暂无明确产业概念流入。
```

---

## 4.2 主线分析取值规则

### 输入来源

主线分析只使用：

```text
行业资金流入/流出
产业概念资金流入/流出
theme_detector 已有结果
report_context.themes
```

不使用：

```text
昨日高振幅
东方财富热股
最近多板
HS300_
机构重仓
权重股
```

作为有效主线。

### 有效主线 / 观察主线判断

如果某个行业或产业概念满足：

```text
3日资金变化 > 0
且成交占比有明显提升
且不是动态/风格/机构属性标签
```

则可进入：

```text
观察主线
```

如果同时满足：

```text
3日资金变化 > 0
5日资金变化 > 0
板块涨幅为正
且有观察池个股归属该方向
```

则可进入：

```text
有效主线 / 强主线
```

如果缺少 5日数据，则不要写“强主线”，最多写：

```text
观察主线
```

### 退潮方向判断

如果某个行业或产业概念满足：

```text
3日资金变化 < 0
或成交占比明显下降
```

则进入：

```text
退潮方向
```

展示：

```text
方向 | 依据 | 说明
```

示例：

```text
通信网络设备及器件 | 3日资金流出 | 相关标的不追高，只看回调确认
```

### 主线结论生成

不要简单写：

```text
今日无明显主线方向。
```

优先按以下模板生成：

```text
今日没有全市场级别主线，但存在局部结构方向：A、B、C。
由于市场宽度偏弱，这些方向只作为观察主线，不宜扩散到普买。
```

只有当行业流入和产业概念流入均不足时，才写：

```text
今日暂无明确产业主线，热点偏分散。
```

---

## 4.3 赚钱效应取值规则

### 输入来源

使用现有 market 字段：

```text
up_count
down_count
limit_up
limit_down
flat_count
amount
market_status
sentiment_score
sentiment_stage
```

当前没有以下数据：

```text
炸板率
连板高度
昨日涨停今日表现
```

这些统一显示：

```text
N/A / 数据不足
```

### 轻量判断规则

计算：

```text
涨跌比 = up_count / down_count
涨跌停比 = limit_up / max(limit_down, 1)
绿盘占比 = down_count / (up_count + down_count + flat_count)
```

判断：

```text
如果 涨跌停比 > 3 且 绿盘占比 > 60%：
    赚钱效应 = 分化偏弱
    解释 = 短线涨停活跃，但多数个股下跌，赚钱效应集中在少数方向。

如果 涨跌停比 > 3 且 绿盘占比 <= 60%：
    赚钱效应 = 尚可 / 活跃

如果 涨跌停比 <= 1：
    赚钱效应 = 弱

如果 涨跌比 < 0.5 且 绿盘占比 > 70%：
    赚钱效应 = 分化偏弱 / 宽度偏弱
```

不要直接用：

```text
赚钱效应：弱
```

与：

```text
短线情绪：过热
```

并列而不解释。

推荐写法：

```text
赚钱效应：分化偏弱
说明：涨停家数和涨跌停比显示短线仍活跃，但绿盘占比高、涨跌比偏弱，说明赚钱效应集中在少数方向。
```

必须保留降级提示：

```text
由于缺少昨日涨停表现、连板高度、炸板率，本结论为降级判断。
```

---

## 4.4 弱市不做取值规则

### 输入来源

现有可计算项：

```text
绿盘占比
涨跌停比
```

当前不可计算项：

```text
昨日涨停今表现
3板以上数量
量能持续萎缩
```

### 展示规则

不要写成完整：

```text
触发 x/5
```

应该写：

```text
可计算项 2 项，触发 x 项；3 项数据不足。
```

展示表：

```text
检查项 | 当前值 | 触发 | 解读
```

结论生成：

```text
如果 绿盘占比 > 60% 且 涨跌停比 > 3：
    结论 = 部分触发。不是全面弱市，而是结构分化；只看核心方向，不普买。

如果 绿盘占比 > 70% 且 涨跌停比 <= 1：
    结论 = 弱市信号较强，原则上只观察或极轻仓。

如果 绿盘占比 <= 60% 且 涨跌停比 > 1：
    结论 = 未触发明显弱市，可正常观察。
```

---

## 4.5 观察池去重取值规则

### 输入来源

使用当前观察池已有数据：

```text
watchlist
strategy
risk_level
action_signal
layer
stock_code
stock_name
buy_price
target_price
stop_loss
position
```

不改变原始 watchlist / stock_signal。

### 去重规则

只做展示层去重。

同一股票多次出现时：

```text
stock_code 相同视为同一股票；
如果 stock_code 缺失，则用 stock_name 兜底。
```

策略来源合并：

```text
一次起爆 / 短线强势
N字异动 / 板块联动
```

层级选择：

```text
如果同一股票同时出现在可观察和谨慎观察：
    展示在谨慎观察。

如果同一股票同时出现在谨慎观察和高风险复盘：
    展示在高风险复盘。

展示层级优先级：
高风险复盘 > 谨慎观察 > 可观察
```

价格字段选择：

```text
优先使用更保守层级的记录；
如果层级相同，优先使用第一条出现的记录；
不要重新计算买入价、目标价、止损。
```

新增展示列：

```text
策略来源
```

---

## 4.6 滚雪球趋势取值规则

### 当前问题

滚雪球趋势如果已经出现在观察池，不要重复开独立大节。

### 新规则

把：

```text
滚雪球趋势
```

作为：

```text
策略来源
```

合并到观察池表中。

如果需要保留解释，放在观察池后面：

```text
滚雪球趋势说明：
趋势跟随策略：MACD 回踩零轴附近后金叉，站上 MA20，量比温和放大。相关个股已合并展示在观察池中，不重复列出。
```

---

## 4.7 模式标签取值规则

### 标签范围

第一版只允许以下标签：

```text
高风险复盘
强势回调候选
龙回头待确认
待确认
```

可选：

```text
板块龙头
主线核心
```

暂不使用或谨慎使用：

```text
龙回头候选
打板质量较高
涨停启明星候选
守株待兔候选
```

除非字段非常明确。

### 标签规则

```text
如果 risk_level 为 high / 高风险 / 回避：
    模式标签 = 高风险复盘

如果 strategy 包含 N字异动 / 二次起爆 / 短线强势，且有近期回调字段：
    模式标签 = 强势回调候选

如果已有字段能证明“前期龙头 + 回调 + 未破关键结构”：
    模式标签 = 龙回头待确认

否则：
    模式标签 = 待确认
```

注意：

```text
不要大面积标“龙回头候选”。
“龙回头候选”只有在市场地位、回调结构、时间窗口等条件较充分时才使用。
```

---

## 4.8 机会观察取值规则

### 输入来源

使用：

```text
观察主线
退潮方向
产业概念流入
行业资金流入
观察池策略来源
trade_plan 仓位
```

### 生成规则

如果存在观察主线：

```text
机会观察 = 局部结构机会
```

模板：

```text
今日没有全市场级别主线，但存在局部结构机会：

1. A / B / C
   资金流入明显，作为观察主线；但市场宽度偏弱，不适合扩散到普买。

2. D
   有资金流入，需观察持续性和板块承接。

3. 退潮方向
   短期资金流出，相关个股只做回调确认，不追高。

4. 所有机会均限制在 trade_plan 总仓位上限内。
```

如果没有观察主线：

```text
机会观察 = 暂无明确产业主线，以观察为主。
```

---

## 4.9 风险提示取值规则

### 市场风险

来自：

```text
绿盘占比
涨跌比
market_status
```

规则：

```text
如果 绿盘占比 > 60%：
    增加风险：多数个股下跌，指数表现不能代表全市场赚钱效应。

如果 涨跌比 < 0.5：
    增加风险：市场宽度明显偏弱。
```

### 板块风险

来自：

```text
行业资金流出 TOP
产业概念资金流出 TOP
退潮方向
```

规则：

```text
流出方向写入板块风险；
相关个股降低追高优先级。
```

### 观察池风险

来自：

```text
观察池策略来源
谨慎观察数量
N字异动 / 二次起爆 数量
```

规则：

```text
如果 N字异动 / 二次起爆 候选较多：
    增加风险：一旦市场宽度继续走弱，容易冲高回落。

如果谨慎观察数量较多：
    增加风险：谨慎观察层不应和可观察层同等对待。
```

### 数据风险

来自：

```text
data_confidence
quality
均线缺失比例
观察池均线覆盖率
```

规则：

```text
如果全市场均线缺失高：
    写明影响全市场筛选广度和部分策略评分。

如果观察池均线覆盖正常：
    写明当前观察池买入价、止损、均线判断可参考。
```

---

## 4.10 数据可信度影响范围取值规则

如果出现：

```text
全市场均线缺失比例高
观察池均线覆盖率正常
```

展示为：

```text
全市场均线缺失：
影响全市场筛选广度和部分策略评分。

观察池均线覆盖：
当前已入选观察池的买入价、止损、均线判断可参考。
```

影响范围模板：

```text
市场和板块判断：影响较小；
全市场选股广度：受影响；
个股观察池排序：可能受影响；
当前观察池买入价/止损/均线判断：可参考。
```

---

## 4.11 缺数据降级规则

所有新增展示字段都必须支持缺数据降级。

统一规则：

```text
字段不存在：N/A
字段为空：N/A
字段为 None：N/A
除数为 0：N/A 或使用 max(x, 1) 的安全分母
数据不足：显示“数据不足（当前数据源未覆盖）”
```

禁止：

```text
因为字段缺失导致日报生成失败；
因为字段缺失临时调用外部 API；
因为字段缺失新增数据库字段；
因为字段缺失改变 selector 结果。
```

---

# 5. 重点优化一：概念资金流向分流

## 5.1 当前问题

当前日报中“概念 3日流入 TOP5”示例：

```text
昨日高振幅
东方财富热股
最近多板
近期新高
百日新高
```

当前日报中“概念 3日流出 TOP5”示例：

```text
机构重仓
HS300_
权重股
中盘成长
上证180_
```

这些不是产业概念，而是：

```text
动态情绪标签
指数成分标签
风格标签
资金属性标签
```

所以不能直接放在“概念流入/流出 TOP5”里，否则读者会误以为这些是主线方向。

## 5.2 新展示结构

把原来的：

```text
概念 3日流入 TOP5
概念 3日流出 TOP5
```

改为：

```text
产业概念 3日流入 TOP5
产业概念 3日流出 TOP5
动态/风格标签变化 TOP5
```

## 5.3 新展示示例

```markdown
### 产业概念 3日流入 TOP5

| 概念 | 涨幅 | 成交占比 | 变化 |
|------|------|----------|------|
| 芯片概念 | +x.xx% | xx.xx% | +x.xx个百分点 |
| 共封装光学(CPO) | +x.xx% | xx.xx% | +x.xx个百分点 |
| 数据中心(AIDC) | +x.xx% | xx.xx% | +x.xx个百分点 |

> 过滤动态标签后，产业概念显示实际数量；不足 5 个不强行补位。

### 产业概念 3日流出 TOP5

| 概念 | 涨幅 | 成交占比 | 变化 |
|------|------|----------|------|
| DeepSeek概念 | -x.xx% | xx.xx% | -x.xx个百分点 |
| AI应用 | -x.xx% | xx.xx% | -x.xx个百分点 |

### 动态/风格标签变化

| 标签 | 类型 | 成交占比 | 变化 | 解读 |
|------|------|----------|------|------|
| 昨日高振幅 | 动态情绪标签 | 34.88% | +13.65个百分点 | 短线波动增强，不作为主线 |
| 东方财富热股 | 热度标签 | 18.36% | +6.48个百分点 | 热点集中，不作为产业方向 |
| HS300_ | 指数成分标签 | 26.49% | -2.19个百分点 | 指数权重标签，不作为概念主线 |
```

---

# 6. 重点优化二：主线分析分层

## 6.1 当前问题

当前报告直接写：

```text
今日无明显主线方向，热点较为分散。
```

但资金流向中已经出现：

```text
电子
半导体
数字芯片设计
光学光电子
机械设备
```

所以“无明显主线”过于粗糙。

## 6.2 新展示结构

改为：

```markdown
## 6. 主线分析

### 6.1 有效主线 / 观察主线

| 方向 | 强度 | 依据 | 风险 |
|------|------|------|------|
| 电子 | 观察主线 | 3日资金流入，成交占比提升 | 市场宽度偏弱 |
| 半导体 | 观察主线 | 行业资金流入，板块表现相对强 | 持续性待确认 |
| 数字芯片设计 | 观察方向 | 资金流入 | 板块容量较小 |
| 光学光电子 | 观察方向 | 资金流入 | 与通信链条分化 |

### 6.2 退潮方向

| 方向 | 依据 | 说明 |
|------|------|------|
| 通信网络设备及器件 | 3日资金流出 | 相关标的不追高，只等回调确认 |
| 传媒 | 资金流出 | 退潮观察 |
| 计算机 | 资金流出 | AI软件端偏弱 |

### 6.3 动态标签

| 标签 | 类型 | 说明 |
|------|------|------|
| 昨日高振幅 | 动态情绪标签 | 不作为主线 |
| 东方财富热股 | 热度标签 | 不作为主线 |
| 最近多板 | 短线情绪标签 | 不作为主线 |

**主线结论：**
今日没有全市场级别主线，但存在局部结构方向：电子、半导体、数字芯片设计、光学光电子。由于市场宽度偏弱，这些方向只作为观察主线，不宜扩散到普买。
```

---

# 7. 重点优化三：赚钱效应口径调整

## 7.1 当前问题

日报里同时出现：

```text
短线情绪阶段：过热
赚钱效应：弱
```

这两个结论读起来容易冲突。

实际上当前数据更适合表达为：

```text
短线活跃，但赚钱效应分化偏弱。
```

原因：

```text
涨停家数较多；
涨跌停比强；
但绿盘占比高；
涨跌比很弱；
多数个股下跌。
```

## 7.2 新口径

把：

```text
赚钱效应：弱
```

改为：

```text
赚钱效应：分化偏弱
```

解释：

```text
涨停家数和涨跌停比显示短线仍活跃，但绿盘占比高、涨跌比偏弱，说明赚钱效应集中在少数方向，多数个股亏钱。
```

如缺少炸板率、连板高度、昨日涨停表现，则继续保留：

```text
由于缺少昨日涨停表现、连板高度、炸板率，本结论为降级判断。
```

---

# 8. 重点优化四：弱市不做表达更直观

当前表达：

```text
已计算 2 项，触发 1 项；3 项数据不足。→ 非典型弱市，可正常观察。
```

建议改为：

```markdown
**弱市不做：部分触发**

可计算项中，绿盘占比已触发弱市信号，但涨跌停比仍显示短线活跃。  
结论：不是全面弱市，而是结构分化；只看核心方向，不普买。

| 类别 | 数量 |
|------|------|
| 可计算项 | 2 |
| 已触发 | 1 |
| 数据不足 | 3 |
```

---

# 9. 重点优化五：观察池展示去重

## 9.1 当前问题

同一股票可能因为多个策略来源重复出现，例如：

```text
铜峰电子：一次起爆 / 短线强势
华源控股：一次起爆 / 短线强势
XD红星发：一次起爆 / 短线强势
肯特催化：二次起爆 / 短线强势
```

这会造成阅读重复，也会让候选数显得虚高。

## 9.2 新展示规则

只做展示层去重，不改底层 `stock_signal`。

规则：

```text
同一股票在同一层级中只展示一次；
方向 / 策略来源合并；
买入价、目标价、止损等字段优先使用原先主记录；
如果同一股票跨层级出现，以更保守层级为准；
例如同时出现在可观察和谨慎观察，则展示在谨慎观察。
```

新增列：

```text
策略来源
```

示例：

```markdown
| 股票 | 策略来源 | 模式标签 | 买入价 | 目标价 | 止损逻辑 | 仓位 | 能买 | 不能买 |
|------|----------|----------|--------|--------|----------|------|------|--------|
| 铜峰电子 | 一次起爆 / 短线强势 | 待确认 | 11.98~12.46 | 13.44 | 跌破11.61 | ≤1成 | 确认信号 | 盲目追高 |
```

---

# 10. 重点优化六：滚雪球趋势合并进观察池

## 10.1 当前问题

当前报告出现：

```text
10.1 可观察
10.2 谨慎观察
10.4 滚雪球趋势
```

问题：

```text
1. 编号不连续；
2. 滚雪球趋势和可观察重复；
3. 新筑股份在可观察中已经出现，又在滚雪球趋势单独出现。
```

## 10.2 新规则

建议取消独立的“10.4 滚雪球趋势”章节。

把滚雪球趋势作为：

```text
策略来源
```

或作为观察池中的补充说明。

如果必须保留说明，可放在观察池表格后：

```markdown
**滚雪球趋势说明：**
趋势跟随策略：MACD 回踩零轴附近后金叉，站上 MA20，量比温和放大。相关个股已合并展示在观察池中，不重复列出。
```

---

# 11. 重点优化七：模式标签降级

## 11.1 当前问题

大量 N字异动被标为：

```text
龙回头候选
```

但“龙回头”严格要求较高，需要：

```text
真正市场龙头；
主升阶段换手充分；
回调空间足够；
市场环境正常；
3-5天时间窗口。
```

当前字段不足时，直接标“龙回头候选”过度自信。

## 11.2 新标签规则

第一版统一降级：

```text
龙回头候选 → 强势回调候选 / 龙回头待确认
```

推荐标签：

```text
强势回调候选
N字回调候选
龙回头待确认
高风险复盘
待确认
```

只有在字段明确支持时，才使用：

```text
龙回头候选
```

如果数据不足，默认：

```text
待确认
```

---

# 12. 重点优化八：机会观察改成局部方向

## 12.1 当前问题

当前机会观察写：

```text
暂无明确主线方向，以观察为主。
```

但报告中已经出现：

```text
电子
半导体
数字芯片设计
光学光电子
观察池若干个股
```

所以不能简单写“暂无明确主线方向”。

## 12.2 新写法

```markdown
## 9. 机会观察

今日没有全市场级别主线，但存在局部结构机会：

1. 电子 / 半导体 / 数字芯片设计  
   资金流入明显，作为观察主线；但市场宽度偏弱，不适合扩散到普买。

2. 光学光电子  
   有资金流入，需观察持续性和板块承接。

3. 通信网络设备及器件  
   短期资金流出，相关个股只做回调确认，不追高。

4. 所有机会均限制在 trade_plan 总仓位上限内。当前总仓位上限：1成。
```

---

# 13. 重点优化九：风险提示更具体

## 13.1 当前问题

当前风险提示偏短，主要是：

```text
多数个股下跌，亏钱效应较强
数据风险
```

建议增加：

```text
板块风险
观察池风险
情绪风险
```

## 13.2 新结构

```markdown
## 8. 风险提示

### 8.1 市场风险
- 绿盘占比高，多数个股下跌，指数表现不能代表全市场赚钱效应。

### 8.2 板块风险
- 通信网络设备、传媒、计算机、消费电子短期资金流出，相关个股降低追高优先级。
- 电子 / 半导体虽有资金流入，但市场宽度偏弱，持续性仍需验证。

### 8.3 观察池风险
- 多只候选来自 N字异动 / 二次起爆，一旦市场宽度继续走弱，容易冲高回落。
- 谨慎观察层股票不应和可观察层同等对待。

### 8.4 数据风险
- 赚钱效应为降级判断，缺少连板高度、炸板率、昨日涨停表现。
- 全市场均线缺失比例较高，部分策略评分需降低权重。
```

---

# 14. 重点优化十：数据可信度影响范围更明确

当前已有：

```text
全市场均线缺失 79%
观察池均线覆盖率 100%
```

建议明确写：

```text
全市场均线缺失 79%：
影响全市场筛选广度和部分策略评分。

观察池均线覆盖 100%：
当前已入选观察池的买入价、止损、均线判断可参考。
```

展示示例：

```markdown
**影响范围：**
- 市场和板块判断：影响较小；
- 全市场选股广度：受影响；
- 个股观察池排序：可能受影响；
- 当前观察池买入价/止损/均线判断：可参考，因为观察池均线覆盖率 100%。
```

---

# 15. 本轮不做的事项

本轮明确不做：

```text
1. 不接 evaluation T+1；
2. 不新增“昨日观察池兑现复盘”模块；
3. 不调整 crontab；
4. 不新增 report_with_evaluation_entrypoint.sh；
5. 不改变 email/evaluation 调度顺序；
6. 不新增炸板率数据源；
7. 不新增连板高度数据源；
8. 不新增昨日涨停表现数据源；
9. 不修改 selector；
10. 不修改 trade_plan。
```

这些放到后续“调度调整 / evaluation 接入日报”阶段再做。

---

# 16. 验收标准

## 16.1 编译

```bash
python -m compileall analysis
```

## 16.2 生成历史日报

```bash
TRADE_DATE=20260604 bash entrypoint.sh
```

或容器：

```bash
TRADE_DATE=20260604 docker compose run --rm stock-report
```

## 16.3 检查日报内容

重点检查：

```text
1. 只有一份主日报用于阅读；
2. 概念资金流向不再直接显示昨日高振幅、东方财富热股、最近多板作为产业概念；
3. 动态标签被放到“动态/风格标签变化”；
4. 主线分析不再简单写“无明显主线”，而是分为观察主线、退潮方向、动态标签；
5. 赚钱效应不再写“弱”与“过热”打架，而是“分化偏弱”；
6. 弱市不做表达更直观；
7. 观察池同一股票不重复展示；
8. 滚雪球趋势不再重复开节；
9. 龙回头候选降级为强势回调候选 / 龙回头待确认；
10. 机会观察能对应资金流向；
11. 风险提示能对应市场、板块、观察池、数据；
12. 数据可信度说明影响范围。
```

## 16.4 逻辑不变检查

本轮不应影响：

```text
stock_signal 数量
trade_plan 仓位
观察池入选逻辑
evaluation
mapper
entrypoint
crontab
数据库结构
```

如果出现以下变化，需要回滚检查：

```text
股票池数量异常变化；
总仓位上限变化；
可观察/谨慎观察/高风险分层变化；
evaluation 运行异常；
mapper 行为变化；
日报重复发送。
```

---

# 17. 预期 diff

理想 diff：

```text
analysis/report_insights.py
analysis/report_renderer.py
analysis/daily_report.py
analysis/email_sender.py
```

可选：

```text
analysis/theme_detector.py
analysis/pipeline_check.py
analysis/report_regression_check.py
```

不应出现：

```text
analysis/selector.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
analysis/stock_board_mapper.py
analysis/init_db.py
sql/schema.sql
entrypoint.sh
scripts/evaluation_entrypoint.sh
docker-compose.yml
Dockerfile
```

---

# 18. 提交建议

如果验收通过：

```bash
git add analysis/report_insights.py analysis/report_renderer.py analysis/daily_report.py analysis/email_sender.py
```

如果修改了 theme_detector：

```bash
git add analysis/theme_detector.py
```

如果修改了 pipeline_check / regression_check：

```bash
git add analysis/pipeline_check.py analysis/report_regression_check.py
```

提交：

```bash
git commit -m "refactor: polish unified daily report display"
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

# 19. 本轮通过标准

本轮完成后，日报应达到：

```text
1. 一份主日报更清晰；
2. 资金流向能看懂；
3. 产业概念和动态标签分开；
4. 主线分析和资金流向一致；
5. 赚钱效应口径不冲突；
6. 观察池不重复；
7. 模式标签不过度自信；
8. 机会观察和风险提示更贴近当天数据；
9. 数据可信度解释更明确；
10. 底层策略和调度完全不变。
```

# V4-Report Display Polish Hotfix：展示口径修补与验收标准

## 0. 本轮目标

本轮是在 `V4-Report Display Polish Pack` 基础上的展示口径 hotfix。

当前本地日报已经完成了大部分展示优化，包括：

```text
1. 产业概念 / 动态标签初步分流；
2. 主线分析从“无明显主线”改为观察主线 + 退潮方向；
3. 赚钱效应不再与情绪阶段明显冲突；
4. 观察池已开始去重并合并策略来源；
5. 滚雪球趋势已并入观察池；
6. 模式标签已从“龙回头候选”整体降级；
7. 风险提示和数据可信度结构已有改善。
```

但当前本地生成的 `daily_report_20260604.md` 仍有若干展示口径问题，需要继续修补。

本轮只修日报展示层，不做以下事项：

```text
不改 selector
不改 trade_plan
不改 watchlist_evaluation
不改 mapper
不改 entrypoint
不改 crontab
不改数据库结构
不新增行情 API
不接 evaluation T+1
不改变 stock_signal 原始结果
```

---

## 1. 当前仍需修补的问题

基于本地生成的 `daily_report_20260604.md`，主要问题如下：

```text
1. “产业概念 3日流出 TOP5”仍混入证金持股、中盘股、大盘价值等非产业概念；
2. 主线分析里的 3日变化单位显示错误，如 +2.56个百分点 被写成 +0.03个百分点；
3. 市场宽度口径前后冲突：摘要写宽度偏强，主线结论又写宽度偏弱；
4. 专精特新仍被放入产业主线第一梯队，但它更像属性标签；
5. 风险提示没有充分体现“短线情绪高潮”后的分歧风险；
6. 赚钱效应虽然写成“尚可/活跃”，但还需要明确“高潮阶段不宜追高”；
7. 产业概念、风格标签、资金属性标签需要进一步彻底分流。
```

---

## 2. 硬边界

### 2.1 允许修改

```text
analysis/report_insights.py
analysis/report_renderer.py
analysis/daily_report.py
analysis/email_sender.py
analysis/pipeline_check.py
```

其中：

```text
report_insights.py：只做展示解释层；
report_renderer.py：只改 Markdown 展示结构与文案；
daily_report.py：只保持 unified report 兼容入口；
email_sender.py：只保持单日报附件口径；
pipeline_check.py：只处理 daily_report_pro 不再 expected / critical。
```

### 2.2 禁止修改

```text
analysis/selector.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
analysis/stock_board_mapper.py
analysis/init_db.py
sql/schema.sql
entrypoint.sh
scripts/evaluation_entrypoint.sh
docker-compose.yml
Dockerfile
crontab
```

禁止改变：

```text
1. 股票池生成逻辑；
2. 观察池分层逻辑；
3. trade_plan 生成逻辑；
4. evaluation 计算逻辑；
5. mapper 刷新逻辑；
6. 数据库结构；
7. pipeline 执行顺序；
8. 邮件调度顺序。
```

---

## 3. 优化点一：产业概念过滤继续加强

### 3.1 当前问题

当前日报中“产业概念 3日流出 TOP5”仍出现：

```text
证金持股
中盘股
大盘价值
```

这些不是产业概念，而是资金属性、持股属性、市值风格或风格标签。

正确分类应为：

```text
算力概念 → 产业概念
证金持股 → 资金/持股属性标签
中盘股 → 市值风格标签
大盘价值 → 风格标签
```

### 3.2 需要补充过滤名单

以下标签不得进入：

```text
产业概念 3日流入 TOP
产业概念 3日流出 TOP
有效主线 / 观察主线
```

#### 动态情绪标签

```text
东方财富热股
昨日涨停
昨日首板
昨日连板
昨日高振幅
最近多板
近期新高
百日新高
历史新高
```

#### 资金 / 持股属性标签

```text
证金持股
机构重仓
基金重仓
社保重仓
QFII重仓
融资融券
MSCI中国
富时罗素
```

#### 指数 / 市值 / 风格标签

```text
HS300_
上证180_
中证500
创业板综
中盘股
大盘股
小盘股
大盘价值
大盘成长
中盘价值
中盘成长
小盘价值
小盘成长
权重股
```

#### 属性标签

```text
专精特新
央企
国企改革
高送转
预盈预增
参股金融
```

说明：

```text
这些标签不要删除，只是不能进入“产业概念”和“有效主线”。
可以进入“动态/风格/属性标签变化”表。
```

---

## 4. 优化点二：产业概念表只保留真正产业方向

产业概念表中优先保留真正产业方向，例如：

```text
半导体概念
算力概念
CPO
光通信
芯片概念
AI PC
数据中心
机器人
商业航天
先进封装
光纤概念
5G
东数西算
新能源车
储能
锂电池
光伏
医药
创新药
军工
低空经济
电力
有色金属
稀土
煤炭
油气
```

如果过滤后产业概念不足 5 个，则展示实际数量，并提示：

```text
过滤动态/风格/属性标签后，产业概念仅 X 个，不强行补位。
```

如果过滤后没有产业概念，则显示：

```text
过滤动态/风格/属性标签后，暂无明确产业概念流入。
```

---

## 5. 优化点三：动态/风格/属性标签单独展示

建议将当前的：

```text
动态/风格标签变化 TOP5
```

进一步改为：

```text
动态/风格/属性标签变化 TOP5
```

或者分成两张表：

```text
动态情绪标签变化 TOP5
风格/属性标签变化 TOP5
```

推荐第一版先用一张表，增加“类型”列：

```markdown
### 动态/风格/属性标签变化 TOP5

| 标签 | 类型 | 变化 | 解读 |
|------|------|------|------|
| 昨日高振幅 | 动态情绪 | +13.65个百分点 | 不作为产业主线 |
| 东方财富热股 | 动态情绪 | +6.48个百分点 | 不作为产业主线 |
| 证金持股 | 资金属性 | -1.48个百分点 | 不作为产业主线 |
| 中盘股 | 市值风格 | -1.18个百分点 | 不作为产业主线 |
| 大盘价值 | 风格标签 | -1.01个百分点 | 不作为产业主线 |
```

类型建议：

```text
动态情绪
资金属性
市值风格
指数成分
属性标签
其他标签
```

---

## 6. 优化点四：主线分析变化值单位修复

### 6.1 当前问题

资金流向表显示：

```text
半导体概念 +2.56个百分点
电子 +2.29个百分点
专精特新 +1.64个百分点
```

但主线分析写成：

```text
+0.03个百分点
+0.02个百分点
```

这是单位显示错误。

原因大概率是：

```text
ratio_change = 0.0256
```

展示时没有乘以 100。

### 6.2 修正规则

所有“变化”展示统一为：

```text
ratio_change * 100
```

格式：

```text
{ratio_change * 100:+.2f}个百分点
```

示例：

```text
0.0256 → +2.56个百分点
-0.0148 → -1.48个百分点
```

需要修复位置：

```text
1. 资金流向表；
2. 主线分析；
3. 退潮方向；
4. 机会观察；
5. 风险提示中涉及变化值的地方。
```

验收时必须确保：

```text
资金流向表和主线分析中的变化值单位一致。
```

---

## 7. 优化点五：市场宽度口径统一

### 7.1 当前冲突

日报摘要写：

```text
市场宽度偏强，赚钱效应相对活跃。
```

但主线结论写：

```text
由于市场宽度偏弱，这些方向只作为观察主线。
```

这两个结论冲突。

### 7.2 2026-06-04 口径判断

当前数据：

```text
上涨家数：3317
下跌家数：2079
涨跌比：1.60
绿盘占比：37.7%
涨跌停比：8.1
```

因此不应写：

```text
市场宽度偏弱
```

应写：

```text
市场宽度尚可
市场宽度较好
短线活跃
```

但由于短线情绪阶段为“高潮”，仍需提示：

```text
情绪高潮后的分歧风险
不宜盲目追高
适合等待分歧低吸
```

### 7.3 主线结论建议模板

将主线结论改为：

```text
今日没有全市场级别主线，但存在局部结构方向：半导体概念、电子、半导体、数字芯片设计。市场宽度尚可，但短线情绪处于高潮，相关方向只适合分歧低吸，不宜追高扩散。
```

如果未来出现宽度偏弱，则可以写：

```text
市场宽度偏弱，局部方向只适合观察，不宜扩散到普买。
```

---

## 8. 优化点六：专精特新不要直接作为产业主线

### 8.1 当前问题

当前主线中出现：

```text
专精特新
```

但它不是产业方向，更像属性标签或政策属性。

### 8.2 处理方式

不要把 `专精特新` 放入产业主线第一梯队。

可放到：

```text
动态/风格/属性标签变化
```

或者在主线分析里作为补充说明：

```text
专精特新成交占比提升，说明资金偏好中小成长 / 细分龙头属性，但不单独作为产业主线。
```

### 8.3 产业主线优先级

主线分析优先使用：

```text
行业方向：
电子
半导体
数字芯片设计
光学光电子
机械设备

产业概念：
半导体概念
算力概念
CPO
光通信
芯片概念
AI PC
数据中心
机器人
```

不要把以下标签作为有效主线：

```text
专精特新
证金持股
机构重仓
中盘股
大盘价值
权重股
东方财富热股
昨日高振幅
最近多板
```

---

## 9. 优化点七：风险提示补充“情绪高潮”风险

### 9.1 当前问题

当前风险提示写：

```text
当前市场风险信号未明显触发。
```

但日报中的短线情绪阶段是：

```text
高潮
```

这本身就是风险信号。

### 9.2 修正建议

当 `sentiment_stage` 为：

```text
高潮
过热
```

风险提示必须包含：

```text
- 市场宽度尚可，但短线情绪处于高潮，需警惕高潮后分歧。
- 涨停家数较多，短线活跃，但不宜在高潮阶段盲目追高。
- 若次日强势股开始冲高回落，应降低追涨优先级。
```

不要只写：

```text
当前市场风险信号未明显触发。
```

更稳妥的写法：

```text
当前市场宽度和涨跌停结构尚可，但短线情绪已经处于高潮区，主要风险不在当日宽度，而在次日分歧和强势股兑现。
```

---

## 10. 优化点八：赚钱效应与情绪阶段联动

当前写法：

```text
赚钱效应：尚可/活跃
短线情绪阶段：高潮
```

这个不冲突，但需要补充解释：

```text
短线活跃不等于适合追高；高潮阶段更适合等分歧低吸。
```

建议交易环境判断中写：

```text
赚钱效应：尚可/活跃
解释：涨跌停比显示短线活跃，市场宽度正常；但情绪处于高潮，追高性价比下降。
```

如果未来出现：

```text
涨跌停比 > 3
绿盘占比 > 60%
```

则应写：

```text
赚钱效应：分化偏弱
解释：涨停仍活跃，但多数个股下跌，赚钱效应集中在少数方向。
```

---

## 11. 优化点九：观察池去重保持当前效果

当前本地日报已经实现策略来源合并，例如：

```text
达实智能 | 一次起爆 / 短线强势
```

这个方向是正确的，继续保持。

验收要求：

```text
1. 同一股票只展示一次；
2. 策略来源合并展示；
3. 跨层级时展示在更保守层级；
4. 不改变 stock_signal 原始结果；
5. 不改变 selector 输出；
6. 不恢复独立 10.4 滚雪球趋势。
```

观察池表头必须包含：

```text
股票
策略来源
模式标签
买入价
目标价
止损逻辑
仓位
能买
不能买
```

---

## 12. 优化点十：模式标签保持降级口径

当前本地日报中模式标签主要是：

```text
强势回调候选
龙回头待确认
待确认
```

这个方向正确。

继续保持：

```text
不要大面积使用“龙回头候选”；
不要轻易使用“板块龙头”；
除非字段能证明前期龙头、回调结构、时间窗口、市场地位，否则只写“龙回头待确认”或“强势回调候选”。
```

推荐标签：

```text
强势回调候选
龙回头待确认
待确认
高风险复盘
主线相关
```

谨慎使用：

```text
龙回头候选
板块龙头
打板质量较高
涨停启明星候选
守株待兔候选
```

---

## 13. 优化点十一：数据可信度展示保持当前方向

当前本地日报已经区分：

```text
全市场均线缺失 81%
观察池均线覆盖率 100%
```

并写明影响范围：

```text
市场和板块判断：影响较小；
全市场选股广度：受影响；
当前观察池买入价/止损/均线判断：可参考。
```

这块可以保留。

建议继续保持：

```text
1. 不只写一个可信度分数；
2. 必须写主要扣分项；
3. 必须写影响范围；
4. 必须区分“全市场数据缺失”和“观察池数据覆盖”。
```

---

## 14. pipeline_check 修补

如果已经取消 pro report，则 `pipeline_check.py` 中不应再把：

```text
daily_report_{}_pro.md
```

放入 `EXPECTED_FILES`。

否则每天都会出现：

```text
daily_report_YYYYMMDD_pro.md 非关键缺失
```

这会继续干扰邮件和日志阅读。

修正规则：

```text
1. 从 EXPECTED_FILES 移除 daily_report_{}_pro.md；
2. CRITICAL 中也不得包含 daily_report_{}_pro.md；
3. pipeline_check 不应再提示 pro report 缺失。
```

---

## 15. email_sender 附件口径验收

日报邮件默认附件只应包含：

```text
daily_report_YYYYMMDD.md
board_trend_tracker_YYYYMMDD.xlsx
```

可选：

```text
board_mapping_quality_YYYYMMDD.md
```

不应默认附：

```text
daily_report_YYYYMMDD_pro.md
board_mapping_quality_YYYYMMDD.json
board_alias_report_YYYYMMDD.md
```

邮件正文可以提示缺失的当天文件，但不应提示：

```text
daily_report_YYYYMMDD_pro.md 缺失
```

---

# 验收标准

## A. 编译验收

执行：

```bash
python -m compileall analysis
```

必须通过。

---

## B. 生成日报验收

使用历史日期：

```bash
TRADE_DATE=20260604 bash entrypoint.sh
```

或容器：

```bash
TRADE_DATE=20260604 docker compose run --rm stock-report
```

检查输出：

```bash
ls reports/daily/*20260604*
```

必须存在：

```text
daily_report_20260604.md
daily_summary_20260604.json
trade_plan_20260604.md
trade_plan_20260604.json
```

不应再默认要求：

```text
daily_report_20260604_pro.md
```

---

## C. 产业概念展示验收

日报中必须出现：

```text
产业概念 3日流入
产业概念 3日流出
动态/风格/属性标签变化
```

产业概念表中不得出现：

```text
昨日高振幅
东方财富热股
最近多板
近期新高
百日新高
机构重仓
证金持股
中盘股
大盘价值
权重股
HS300_
上证180_
中证500
融资融券
MSCI中国
富时罗素
专精特新
```

如果过滤后产业概念不足 5 个，必须显示：

```text
过滤动态/风格/属性标签后，产业概念仅 X 个，不强行补位。
```

---

## D. 主线分析验收

主线分析不能简单写：

```text
今日无明显主线方向
```

如果行业或产业概念有流入，应展示：

```text
观察主线
退潮方向
动态/风格/属性标签
```

有效主线 / 观察主线不得包含：

```text
昨日高振幅
东方财富热股
最近多板
证金持股
机构重仓
中盘股
大盘价值
权重股
专精特新
```

---

## E. 单位显示验收

主线分析中的变化值必须与资金流向表一致。

例如资金流向表：

```text
半导体概念 +2.56个百分点
```

主线分析不能显示：

```text
+0.03个百分点
```

必须显示：

```text
+2.56个百分点
```

验收规则：

```text
所有 ratio_change 展示时乘以 100；
保留两位小数；
统一写“个百分点”。
```

---

## F. 市场宽度口径验收

如果满足：

```text
涨跌比 > 1.2
绿盘占比 < 50%
```

则不允许写：

```text
市场宽度偏弱
```

应写：

```text
市场宽度尚可
市场宽度较好
```

如果短线情绪为：

```text
高潮
过热
```

则风险提示必须包含：

```text
短线情绪处于高潮/过热，需警惕高潮后分歧。
```

---

## G. 赚钱效应验收

如果满足：

```text
涨跌停比 > 3
绿盘占比 < 60%
涨跌比 > 1
```

可以写：

```text
赚钱效应：尚可/活跃
```

但必须补充：

```text
情绪处于高潮时，不宜盲目追高，更适合分歧低吸。
```

如果满足：

```text
涨跌停比 > 3
绿盘占比 > 60%
```

应写：

```text
赚钱效应：分化偏弱
```

不能直接写：

```text
赚钱效应：弱
```

---

## H. 观察池验收

观察池必须满足：

```text
1. 同一股票在日报中只展示一次；
2. 策略来源可以合并；
3. 跨层级时进入更保守层级；
4. 不改变底层 stock_signal；
5. 不改变原始 selector 输出。
```

观察池表头必须包含：

```text
股票
策略来源
模式标签
买入价
目标价
止损逻辑
仓位
能买
不能买
```

不得恢复单独：

```text
10.4 滚雪球趋势
```

---

## I. 模式标签验收

日报中不应大面积出现：

```text
龙回头候选
板块龙头
```

优先使用：

```text
强势回调候选
龙回头待确认
待确认
高风险复盘
主线相关
```

除非字段很充分，否则不要直接写：

```text
龙回头候选
```

---

## J. 风险提示验收

风险提示必须分层：

```text
市场风险
板块风险
观察池风险
数据风险
```

至少包含：

```text
情绪高潮/过热后的分歧风险
资金流出方向的追高风险
N字异动/二次起爆候选的冲高回落风险
数据缺失带来的降级判断
```

如果短线情绪为高潮，不允许只写：

```text
当前市场风险信号未明显触发
```

---

## K. 数据可信度验收

必须区分：

```text
全市场均线缺失影响
观察池均线覆盖影响
```

推荐展示：

```text
全市场均线缺失：
影响全市场筛选广度和部分策略评分。

观察池均线覆盖：
当前已入选观察池的买入价、止损、均线判断可参考。
```

---

## L. 文件边界验收

本轮不应修改：

```text
analysis/selector.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
analysis/stock_board_mapper.py
analysis/init_db.py
sql/schema.sql
entrypoint.sh
scripts/evaluation_entrypoint.sh
docker-compose.yml
Dockerfile
```

允许修改：

```text
analysis/report_insights.py
analysis/report_renderer.py
analysis/daily_report.py
analysis/email_sender.py
analysis/pipeline_check.py
```

---

## M. 最终通过标准

本轮完成后，应达到：

```text
1. 产业概念和动态/风格/属性标签彻底分开；
2. 产业概念流出表不再出现证金持股、中盘股、大盘价值、专精特新；
3. 主线分析中的变化值单位正确；
4. 市场宽度表述和实际涨跌家数一致；
5. 情绪高潮风险有明确提示；
6. 观察池无重复股票；
7. 滚雪球不再重复开节；
8. 模式标签不过度自信；
9. 数据可信度解释清楚；
10. pipeline_check 不再提示 pro report 缺失；
11. 不改底层策略、不改调度、不改数据库。
```

---

## N. 提交建议

验收通过后提交：

```bash
git add analysis/report_insights.py analysis/report_renderer.py analysis/daily_report.py analysis/email_sender.py analysis/pipeline_check.py
git commit -m "fix: polish daily report display taxonomy and validation wording"
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



# V4-Report Display Alignment Hotfix：日报展示与 trade_plan 对齐

## 0. 本轮目标

本轮是在 `V4-Report Display Polish Pack` 基础上的最后一轮展示对齐 hotfix。

当前 dev 代码和本地生成日报已经完成大部分展示优化，但仍有 5 个关键问题需要修：

```text
1. 日报观察池与 trade_plan 不一致；
2. email_sender --date 模式下 trade_plan 文件名日期格式错误；
3. 主线 / 机会 / 风险里仍有“市场宽度偏弱”的硬编码；
4. --mode both 仍会重复生成同一份日报并重复写 DB；
5. detect_main_themes 结果没有真正进入日报主线展示。
```

本轮仍然只做展示层和入口兼容修补，不改底层策略。

不做以下事项：

```text
不改 selector
不改 trade_plan 生成逻辑
不改 watchlist_evaluation
不改 mapper
不改 entrypoint
不改 crontab
不改数据库结构
不新增行情 API
不接 evaluation T+1
不改变 stock_signal 原始结果
```

---

## 1. 当前阻塞问题

### 1.1 日报观察池与 trade_plan 不一致

当前 `trade_plan_20260604.md` 中明确显示：

```text
光迅科技：不可交易过滤，原因：价格227.58 > 200.0
```

但 `daily_report_20260604.md` 中，光迅科技仍然出现在：

```text
10.1 可观察
```

这会造成严重误导。

另外，`trade_plan` 中部分股票属于：

```text
交易条件不满足
```

例如接近涨停，不适合作为低吸候选，但日报仍将它们放进“可观察”。

这说明当前日报观察池仍主要从 `selector_result` 原始池渲染，而不是以 `trade_plan` 的最终分层为准。

---

### 1.2 email_sender --date 模式存在日期格式 bug

当前逻辑中，`email_sender.py` 读取 summary 后会把：

```text
20260604
```

转成：

```text
2026-06-04
```

然后又用带横杠的日期去找：

```text
trade_plan_2026-06-04.json
```

但真实文件是：

```text
trade_plan_20260604.json
```

这会导致 `--date` 模式下无法读取当天 trade_plan 摘要。

---

### 1.3 市场宽度文案仍有硬编码冲突

当前日报市场宽度数据为：

```text
涨跌比：1.55
绿盘占比：38.3%
涨跌停比：5.3
```

说明市场宽度较好。

但主线 / 机会 / 板块风险里仍出现：

```text
市场宽度偏弱，持续性待确认
市场宽度偏弱，不适合扩散到普买
```

这是硬编码造成的口径冲突。

---

### 1.4 --mode both 重复生成同一份日报

当前 `daily_report.py` 仍有：

```python
modes = ["beginner", "pro"] if mode == "both" else [mode]
```

但现在系统已经只生成一份主日报：

```text
daily_report_YYYYMMDD.md
```

所以 `--mode both` 会导致：

```text
1. 同一份日报渲染两次；
2. 同一文件保存两次；
3. daily_report 表写入两条内容高度重复的记录；
4. 日志输出重复。
```

这不符合“只保留一份主日报”的目标。

---

### 1.5 detect_main_themes 结果没有真正进入日报主线展示

`daily_report.py` 中已经计算：

```python
themes = detect_main_themes(...)
```

但 `render_unified_report()` 没有接收 `themes` 参数，`render_daily_report()` 虽然接收了 `themes`，但没有继续传入 `render_unified_report()`。

结果是：

```text
summary JSON 中的 themes 和日报主线分析可能不一致。
```

例如 summary 中有：

```text
面板
光学光电子
昨日涨停
```

其中：

```text
面板、光学光电子 → 可以作为有效主线参考
昨日涨停 → 应作为动态标签分流
```

但当前日报主线主要从 `board_ratio_changes` 重新取方向，没有充分使用 `detect_main_themes()` 的结果。

---

## 2. 本轮允许修改文件

允许修改：

```text
analysis/report_renderer.py
analysis/report_insights.py
analysis/daily_report.py
analysis/email_sender.py
```

可选小改：

```text
analysis/pipeline_check.py
```

但 `pipeline_check.py` 目前已移除 `daily_report_pro`，如无必要不要再动。

禁止修改：

```text
analysis/selector.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
analysis/stock_board_mapper.py
analysis/init_db.py
sql/schema.sql
entrypoint.sh
scripts/evaluation_entrypoint.sh
docker-compose.yml
Dockerfile
crontab
```

---

# 3. 修复点一：日报观察池必须对齐 trade_plan

## 3.1 修复目标

日报 `## 10. 观察池` 必须以 `trade_plan` 最终分层为准。

也就是说，日报中不能再出现：

```text
trade_plan 里被过滤 / 条件不满足 / 不可交易的股票，却在日报里显示为可观察。
```

尤其是：

```text
不可交易过滤
交易条件不满足
高风险回避
```

必须从正常“可观察”中移出。

---

## 3.2 推荐展示结构

将日报观察池改成与 trade_plan 一致的结构：

```markdown
## 10. 观察池

### 10.1 候选低吸

### 10.2 只观察

### 10.3 交易条件不满足

### 10.4 高风险回避

### 10.5 不可交易过滤
```

其中：

```text
候选低吸 → 可以进入正常观察表
只观察 → 只观察，不作为优先低吸候选
交易条件不满足 → 明确说明不能买原因
高风险回避 → 只复盘不参与
不可交易过滤 → 明确过滤原因
```

如果希望保留原来的“可观察 / 谨慎观察”名称，也可以，但必须映射为：

```text
可观察 = trade_plan.候选低吸
谨慎观察 = trade_plan.只观察
交易条件不满足 = 单独表
不可交易过滤 = 单独表
高风险回避 = 单独表
```

---

## 3.3 取值来源

优先使用 `trade_plan` 对象，而不是直接从 `selector_result` 分层。

trade_plan 中通常已有这些字段或可从 markdown/json 结构中取得：

```text
market_restrictions
summary
候选低吸
只观察
交易条件不满足
高风险回避
不可交易过滤
```

如果当前 `trade_plan` 是 dict，优先从 dict 中读取结构化字段。

如果结构化字段不完整，可以保留 selector_result 作为兜底，但必须用 trade_plan 的过滤名单进行排除。

---

## 3.4 关键规则

### 规则 A：不可交易过滤优先级最高

如果某股票在 trade_plan 中属于：

```text
不可交易过滤
```

则不得出现在：

```text
候选低吸
只观察
可观察
谨慎观察
```

只能出现在：

```text
不可交易过滤
```

示例：

```text
光迅科技 | N字异动 | 价格227.58 > 200.0 | 不可交易
```

---

### 规则 B：交易条件不满足不能放入可观察

如果某股票在 trade_plan 中属于：

```text
交易条件不满足
```

则不得显示在：

```text
可观察 / 候选低吸
```

只能显示在：

```text
交易条件不满足
```

并展示原因，例如：

```text
今日涨幅10.0%接近涨停，不适合作为低吸候选
换手率39%≥30
```

---

### 规则 C：跨层级按更保守层级展示

展示优先级：

```text
不可交易过滤 > 高风险回避 > 交易条件不满足 > 只观察 > 候选低吸
```

如果同一股票同时出现在多个策略或层级中，只展示在更保守层级。

策略来源合并：

```text
三孚股份 | N字异动 / 二次起爆
泰和新材 | N字异动 / 二次起爆
```

---

### 规则 D：保留用户需要的直观字段

正常观察表中保留：

```text
股票
策略来源
模式标签
买入价
目标价
止损逻辑
仓位
能买
不能买
```

对于 `交易条件不满足 / 不可交易过滤`，表格可以简化为：

```text
股票
策略来源
当前状态
原因
处理
```

示例：

```markdown
### 10.3 交易条件不满足

| 股票 | 策略来源 | 当前状态 | 原因 | 处理 |
|------|----------|----------|------|------|
| 顺络电子 | 板块联动 | 不适合低吸 | 今日涨幅10.0%接近涨停 | 不追高，只观察 |
| 达实智能 | 一次起爆 | 不适合低吸 | 换手率39%≥30；接近涨停 | 不追高，只观察 |

### 10.5 不可交易过滤

| 股票 | 策略来源 | 原因 | 处理 |
|------|----------|------|------|
| 光迅科技 | N字异动 | 价格227.58 > 200.0 | 不纳入观察池 |
```

---

## 3.5 验收标准

以 `20260604` 为例：

```text
光迅科技不得出现在 10.1 可观察 / 候选低吸；
光迅科技必须出现在 不可交易过滤；
顺络电子、皖维高新、中大力德、光洋股份等“交易条件不满足”的股票，不得出现在候选低吸；
三孚股份、泰和新材等多策略股票只展示一次，策略来源合并。
```

---

# 4. 修复点二：修复 email_sender --date 日期格式 bug

## 4.1 当前问题

当前代码混用了：

```text
date_key = 20260604
date_display = 2026-06-04
```

导致读取文件时用了 `date_display`。

---

## 4.2 修复方案

在 `email_sender.py` 中明确分离两个变量：

```python
date_key = to_ymd(args.date) if args.date else get_trade_date()
date_display = f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:]}"
```

文件路径一律使用：

```python
date_key
```

例如：

```python
daily_report_{date_key}.md
daily_summary_{date_key}.json
trade_plan_{date_key}.json
board_trend_tracker_{date_key}.xlsx
board_mapping_quality_{date_key}.md
pipeline_check_{date_key}.json
```

邮件标题和正文展示使用：

```python
date_display
```

例如：

```python
subject = f"【A股每日复盘】{date_display}"
```

如果从 summary 中读取 trade_date，也同样维护两个变量：

```python
summary_date_key = data.get("trade_date", date_key)
summary_date_display = f"{summary_date_key[:4]}-{summary_date_key[4:6]}-{summary_date_key[6:]}"
```

---

## 4.3 验收标准

运行：

```bash
python -m analysis.email_sender --date 20260604
```

应查找：

```text
daily_report_20260604.md
daily_summary_20260604.json
trade_plan_20260604.json
board_trend_tracker_20260604.xlsx
board_mapping_quality_20260604.md
pipeline_check_20260604.json
```

不应查找：

```text
trade_plan_2026-06-04.json
daily_summary_2026-06-04.json
pipeline_check_2026-06-04.json
```

---

# 5. 修复点三：市场宽度文案不能硬编码“偏弱”

## 5.1 当前问题

主线分析、机会观察、板块风险里仍硬编码：

```text
市场宽度偏弱
```

但 20260604 的实际市场宽度是：

```text
涨跌比 1.55
绿盘占比 38.3%
```

应为：

```text
市场宽度较好 / 尚可
```

---

## 5.2 修复规则

定义：

```python
width_ok = width["adv_ratio"] > 1.2 and width["green_ratio"] < 0.5
width_weak = width["green_ratio"] > 0.6 or width["adv_ratio"] < 0.5
```

文案规则：

### 宽度较好时

```text
市场宽度尚可，但短线情绪处于高潮，持续性仍需确认。
```

机会观察中写：

```text
资金流入明显，作为观察主线；市场宽度尚可，但短线情绪处于高潮，不宜追高扩散。
```

板块风险中写：

```text
虽有局部方向资金流入，但短线情绪处于高潮，需警惕次日分歧。
```

### 宽度偏弱时

```text
市场宽度偏弱，相关方向只作观察，不宜扩散到普买。
```

机会观察中写：

```text
资金流入明显，作为观察主线；但市场宽度偏弱，不适合扩散到普买。
```

---

## 5.3 需要替换的位置

```text
主线分析风险列；
主线结论；
机会观察；
板块风险；
纪律或风险提示中涉及市场宽度的文案。
```

---

## 5.4 验收标准

以 `20260604` 为例，日报不应再出现：

```text
市场宽度偏弱，持续性待确认
市场宽度偏弱，不适合扩散到普买
```

应出现类似：

```text
市场宽度尚可，但短线情绪处于高潮，持续性仍需确认
市场宽度尚可，但不宜追高扩散
```

---

# 6. 修复点四：--mode both 只生成一次 unified report

## 6.1 当前问题

当前逻辑：

```python
modes = ["beginner", "pro"] if mode == "both" else [mode]
```

在统一日报模式下会导致重复生成。

---

## 6.2 修复方案

兼容旧命令参数，但内部只生成一次：

```python
mode_arg = args.mode
report_mode = "unified"

modes = ["unified"]
```

或者：

```python
if mode in ("beginner", "pro", "both"):
    modes = ["unified"]
```

调用时：

```python
generate_report_mode(..., mode="unified", ...)
```

数据库写入时：

```python
report_mode = "unified"
```

如果不想改数据库字段口径，也可以用：

```python
report_mode = "beginner"
```

但不建议再写两条。

---

## 6.3 验收标准

运行：

```bash
python -m analysis.daily_report --mode both --date 20260604
```

必须满足：

```text
只生成一次 daily_report_20260604.md；
控制台只打印一次完整日报；
daily_report 表只写入一条当前日期新记录；
不生成 daily_report_20260604_pro.md。
```

---

# 7. 修复点五：render_unified_report 接入 themes

## 7.1 当前问题

`daily_report.py` 已计算：

```python
themes = detect_main_themes(...)
```

但 `render_unified_report()` 没有接收 `themes`，导致日报主线没有充分使用 detect_main_themes 的结果。

---

## 7.2 修复方案

修改函数签名：

```python
def render_unified_report(
    trade_date, data_status, quality, market, industry, concept,
    sentiment, selectors, board_ratio_changes=None,
    trade_plan=None, board_trend_summary=None, report_context=None,
    themes=None,
):
```

`render_daily_report()` 中传入：

```python
return render_unified_report(
    ...,
    themes=themes,
)
```

---

## 7.3 使用规则

主线分析数据来源合并：

```text
1. detect_main_themes 结果；
2. 行业 3日流入；
3. 产业概念 3日流入；
4. 动态标签分流结果。
```

其中：

```text
detect_main_themes 中的产业/行业主题 → 可以进入观察主线；
detect_main_themes 中的动态标签 → 进入动态标签，不作为主线。
```

示例：

```text
面板 → 有效主线 / 观察主线
光学光电子 → 有效主线 / 观察主线
昨日涨停 → 动态标签，不作为主线
```

---

## 7.4 去重规则

如果 `themes` 和 `board_ratio_changes` 都包含同一方向：

```text
只展示一次；
依据可以合并。
```

例如：

```text
光学光电子 | detect_main_themes 强主线；行业3日成交占比提升 +0.93个百分点
```

---

## 7.5 验收标准

以 `daily_summary_20260604.json` 为例：

```text
面板、光学光电子 应进入主线参考；
昨日涨停 应进入动态标签，不得作为有效主线；
日报主线和 daily_summary themes 不应明显冲突。
```

---

# 8. 保留项

以下已完成的优化继续保留，不要回退：

```text
1. 概念 / 动态 / 风格 / 属性标签分流；
2. 产业概念变化值乘以 100，显示“个百分点”；
3. 风险提示中包含情绪高潮风险；
4. 观察池策略来源合并；
5. 滚雪球不单独开 10.4；
6. 数据可信度区分全市场和观察池影响范围；
7. pipeline_check 不再期待 daily_report_pro。
```

---

# 9. 验收命令

## 9.1 编译

```bash
python -m compileall analysis
```

必须通过。

---

## 9.2 生成日报

```bash
TRADE_DATE=20260604 bash entrypoint.sh
```

或容器：

```bash
TRADE_DATE=20260604 docker compose run --rm stock-report
```

检查：

```bash
ls reports/daily/*20260604*
```

必须有：

```text
daily_report_20260604.md
daily_summary_20260604.json
trade_plan_20260604.md
trade_plan_20260604.json
```

不应默认生成或要求：

```text
daily_report_20260604_pro.md
```

---

## 9.3 both 模式验收

```bash
python -m analysis.daily_report --mode both --date 20260604
```

必须满足：

```text
只生成一次主日报；
不生成 pro.md；
不重复写 DB；
不重复打印两份日报。
```

---

## 9.4 邮件 dry-run / 日期文件验收

如果有 dry-run：

```bash
python -m analysis.email_sender --date 20260604 --dry-run
```

如果没有 dry-run，则至少本地检查日志，确认它查找的是：

```text
trade_plan_20260604.json
```

而不是：

```text
trade_plan_2026-06-04.json
```

---

# 10. 内容验收标准

## 10.1 trade_plan 对齐验收

以 `20260604` 为例：

```text
光迅科技必须在“不可交易过滤”；
光迅科技不得在“候选低吸 / 可观察”；
顺络电子、皖维高新、中大力德、光洋股份等交易条件不满足票，不得在候选低吸；
三孚股份、泰和新材多策略来源必须合并；
候选低吸数量应与 trade_plan 摘要一致。
```

---

## 10.2 市场宽度验收

以 `20260604` 为例，报告中不应出现：

```text
市场宽度偏弱，持续性待确认
市场宽度偏弱，不适合扩散到普买
```

应出现：

```text
市场宽度尚可 / 宽度较好
短线情绪处于高潮，需警惕分歧
不宜追高扩散
```

---

## 10.3 themes 验收

日报主线中应参考 `detect_main_themes`：

```text
面板
光学光电子
```

`昨日涨停` 应作为动态标签，不得作为有效主线。

---

## 10.4 观察池表头验收

候选低吸 / 只观察表头保留：

```text
股票
策略来源
模式标签
买入价
目标价
止损逻辑
仓位
能买
不能买
```

交易条件不满足 / 不可交易过滤表头可以为：

```text
股票
策略来源
当前状态
原因
处理
```

---

# 11. 文件 diff 预期

理想 diff：

```text
analysis/report_renderer.py
analysis/report_insights.py
analysis/daily_report.py
analysis/email_sender.py
```

不应出现：

```text
analysis/selector.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
analysis/stock_board_mapper.py
analysis/init_db.py
sql/schema.sql
entrypoint.sh
scripts/evaluation_entrypoint.sh
docker-compose.yml
Dockerfile
```

---

# 12. 提交建议

验收通过后：

```bash
git add analysis/report_renderer.py analysis/report_insights.py analysis/daily_report.py analysis/email_sender.py
git commit -m "fix: align daily report display with trade plan"
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

# 13. 最终通过标准

本轮完成后，必须达到：

```text
1. 日报观察池与 trade_plan 完全一致；
2. 不可交易过滤不再出现在可观察；
3. 交易条件不满足不再出现在候选低吸；
4. email_sender --date 正确读取 YYYYMMDD 文件；
5. 市场宽度文案不再硬编码偏弱；
6. --mode both 只生成一次 unified report；
7. detect_main_themes 结果进入日报主线；
8. 动态标签仍然不作为有效主线；
9. 不改策略、不改调度、不改数据库。
```

# V4-Report Display Final Polish：最后展示修补方案

## 0. 本轮目标

本轮是 `V4-Report Display Polish Pack` 的最后展示修补，不再扩大范围。

当前日报已经完成了大部分核心修复：

```text
1. 产业概念 / 动态风格属性标签已经分流；
2. 观察池已经基本对齐 trade_plan；
3. 光迅科技已经从候选低吸移入不可交易过滤；
4. 交易条件不满足已经单独展示；
5. 滚雪球趋势不再单独开节；
6. 数据可信度影响范围已经较清楚；
7. 情绪高潮风险已经进入风险提示。
```

本轮只修最后几个展示口径问题：

```text
1. “动态/风格/属性标签变化 TOP5”名称不够直观；
2. 标签表“解读”列过于笼统，全部写“不作为产业主线”，用户看不懂；
3. 主线分析里仍有“市场宽度偏弱”硬编码；
4. 机会观察和板块风险里仍有宽度表述冲突；
5. “板块龙头”标签过度自信，需要降级；
6. 交易条件不满足中同一股票跨策略重复出现，需要继续合并；
7. 观察池编号从 10.3 跳到 10.5，需要补齐或顺延。
```

本轮仍然不做：

```text
不改 selector
不改 trade_plan 生成逻辑
不改 watchlist_evaluation
不改 mapper
不改 entrypoint
不改 crontab
不改数据库结构
不新增行情 API
不接 evaluation T+1
不改变 stock_signal 原始结果
```

---

## 1. 修复点一：重命名“动态/风格/属性标签变化 TOP5”

### 当前问题

当前标题是：

```text
动态/风格/属性标签变化 TOP5
```

这个名字太长，也不够直观。用户看到“昨日高振幅、东方财富热股、最近多板、近期新高、机构重仓”时，不知道这些标签到底是什么意思。

### 修改建议

将标题改为：

```text
短线情绪/风格标签变化 TOP5
```

并在标题下增加一句解释：

```text
这些不是产业主线，只反映短线情绪、市场热度、交易风格或资金属性的变化。
```

最终展示示例：

```markdown
### 短线情绪/风格标签变化 TOP5

> 这些不是产业主线，只反映短线情绪、市场热度、交易风格或资金属性的变化。

| 标签 | 类型 | 变化 | 看法 |
|------|------|------|------|
| 昨日高振幅 | 短线波动 | +13.65个百分点 | 短线波动增强，资金博弈激烈 |
| 东方财富热股 | 市场热度 | +6.48个百分点 | 热门股成交占比上升 |
| 最近多板 | 强势接力 | +3.93个百分点 | 连板/强势股活跃 |
| 近期新高 | 趋势风格 | +3.10个百分点 | 趋势新高股活跃 |
| 机构重仓 | 机构属性 | -2.84个百分点 | 机构属性股票成交占比下降 |
```

---

## 2. 修复点二：标签“解读”列按标签类型生成

### 当前问题

目前“解读”列基本都是：

```text
不作为产业主线
```

这句话是对的，但用户看不懂每个标签本身的意义。

### 修改规则

不要每行都统一写“不作为产业主线”，而是按标签类型解释。

建议新增一个函数：

```python
def explain_non_industrial_label(name, category, change):
    ...
```

### 标签解释规则

#### 动态情绪类

```text
昨日高振幅 → 短线波动增强，资金博弈激烈
东方财富热股 → 热门股成交占比上升
最近多板 → 连板/强势股活跃
近期新高 → 趋势新高股活跃
百日新高 → 中期趋势股活跃
昨日涨停 → 涨停股延续活跃
昨日首板 → 首板股延续活跃
昨日连板 → 连板接力情绪活跃
```

#### 风格 / 市值类

```text
中盘股 → 中盘风格成交占比变化
大盘股 → 大盘风格成交占比变化
小盘股 → 小盘风格成交占比变化
大盘价值 → 价值风格成交占比变化
大盘成长 → 大盘成长风格变化
中盘成长 → 中盘成长风格变化
权重股 → 权重股成交占比变化
```

#### 资金属性类

```text
机构重仓 → 机构属性股票成交占比变化
证金持股 → 证金/国家队属性股票成交占比变化
基金重仓 → 基金重仓股成交占比变化
社保重仓 → 社保重仓股成交占比变化
融资融券 → 两融标的成交占比变化
MSCI中国 → 外资指数成分股成交占比变化
富时罗素 → 外资指数成分股成交占比变化
```

#### 指数成分类

```text
HS300_ → 沪深300成分股成交占比变化
上证180_ → 上证180成分股成交占比变化
中证500 → 中证500成分股成交占比变化
创业板综 → 创业板相关成分股成交占比变化
```

#### 属性标签类

```text
专精特新 → 专精特新属性股票成交占比变化
国企改革 → 国企改革属性股票成交占比变化
央企 → 央企属性股票成交占比变化
预盈预增 → 业绩预增属性股票成交占比变化
```

### 补充说明

如果无法匹配具体标签，则兜底：

```text
该类市场标签成交占比变化，不作为产业主线。
```

---

## 3. 修复点三：主线分析风险列不要再写“市场宽度偏弱”

### 当前问题

20260604 的市场宽度数据是：

```text
涨跌比 1.55
绿盘占比 38.3%
涨跌停比 5.3
```

这应判断为：

```text
市场宽度较好 / 尚可
```

但主线分析表中仍出现：

```text
市场宽度偏弱，持续性待确认
```

这和前文市场宽度冲突。

### 修改规则

在 `report_renderer.py` 中统一生成宽度文案：

```python
width_ok = width["adv_ratio"] > 1.2 and width["green_ratio"] < 0.5
width_weak = width["green_ratio"] > 0.6 or width["adv_ratio"] < 0.5
sentiment_hot = s_stage in ("高潮", "过热")
```

主线风险列文案：

```python
if width_ok and sentiment_hot:
    risk_text = "市场宽度尚可，但情绪高潮，持续性待确认"
elif width_ok:
    risk_text = "市场宽度尚可，关注持续性"
elif width_weak:
    risk_text = "市场宽度偏弱，只作观察"
else:
    risk_text = "市场宽度一般，持续性待确认"
```

### 验收标准

20260604 日报中不应再出现：

```text
市场宽度偏弱，持续性待确认
```

应该出现：

```text
市场宽度尚可，但情绪高潮，持续性待确认
```

---

## 4. 修复点四：机会观察文案与市场宽度保持一致

### 当前问题

机会观察里已经基本改成：

```text
市场宽度尚可，但短线情绪处于高潮，不宜追高扩散。
```

这个方向是对的，需要确保所有机会观察项统一使用这个动态文案，不要残留：

```text
市场宽度偏弱，不适合扩散到普买
```

### 修改规则

机会观察文案使用同一套函数：

```python
def market_width_advice(width, sentiment_stage):
    if width_ok and sentiment_hot:
        return "市场宽度尚可，但短线情绪处于高潮，不宜追高扩散。"
    elif width_ok:
        return "市场宽度尚可，可观察持续性，但仍不追高。"
    elif width_weak:
        return "市场宽度偏弱，只适合观察，不宜扩散到普买。"
    else:
        return "市场宽度一般，优先观察核心方向。"
```

### 验收标准

20260604 机会观察中应使用：

```text
市场宽度尚可，但短线情绪处于高潮，不宜追高扩散。
```

---

## 5. 修复点五：板块风险文案消除语病

### 当前问题

当前风险提示中有一句：

```text
虽有局部方向资金流入，但市场宽度尚可，但短线情绪处于高潮，需警惕次日分歧。
```

这里连续两个“但”，读起来不顺。

### 修改建议

改为：

```text
虽有局部方向资金流入，且市场宽度尚可，但短线情绪处于高潮，需警惕次日分歧。
```

或者更简洁：

```text
局部方向仍有资金流入，但短线情绪处于高潮，需警惕次日分歧。
```

推荐使用第二句。

---

## 6. 修复点六：“板块龙头”标签降级

### 当前问题

日报观察池中仍出现：

```text
板块龙头
```

例如：

```text
彩虹股份
海格通信
胜利精密
盛路通信
五方光电
```

但当前规则无法严格证明这些股票是板块龙头。这个标签容易让用户误以为它们是强确定性核心票。

### 修改建议

将：

```text
板块龙头
```

降级为：

```text
主线相关
```

或：

```text
板块联动
```

推荐统一用：

```text
主线相关
```

### 代码规则

在 `assign_pattern_tag()` 中，不要再返回：

```python
return "板块龙头"
```

改为：

```python
return "主线相关"
```

或者更保守：

```python
return "待确认"
```

建议：

```text
如果 pct > 5 且 themes 存在有效产业主题：
    return "主线相关"
```

### 验收标准

日报中不应大面积出现：

```text
板块龙头
```

可以出现：

```text
主线相关
强势回调候选
龙回头待确认
待确认
高风险复盘
```

---

## 7. 修复点七：交易条件不满足中重复股票继续合并

### 当前问题

在 `交易条件不满足` 中，`泰和新材` 和 `三孚股份` 分别出现了两次：

```text
泰和新材 | N字异动
泰和新材 | 二次起爆

三孚股份 | N字异动
三孚股份 | 二次起爆
```

这说明交易条件不满足表还没有完全做展示层去重。

### 修改规则

所有观察池分层都要去重，包括：

```text
候选低吸
只观察
交易条件不满足
高风险回避
不可交易过滤
```

同一股票合并策略来源：

```text
泰和新材 | N字异动 / 二次起爆
三孚股份 | N字异动 / 二次起爆
```

原因合并：

```text
如果原因相同，只保留一次；
如果原因不同，用“；”拼接。
```

### 展示示例

```markdown
| 泰和新材 | N字异动 / 二次起爆 | 不适合低吸 | 今日涨幅10.0%接近涨停，不适合作为低吸候选 | 不追高，只观察 |
| 三孚股份 | N字异动 / 二次起爆 | 不适合低吸 | 今日涨幅10.0%接近涨停，不适合作为低吸候选 | 不追高，只观察 |
```

### 验收标准

20260604 日报中：

```text
泰和新材 只能出现一次；
三孚股份 只能出现一次；
策略来源合并为 N字异动 / 二次起爆。
```

---

## 8. 修复点八：观察池编号不要跳号

### 当前问题

当前日报有：

```text
10.1 候选低吸
10.2 只观察
10.3 交易条件不满足
10.5 不可交易过滤
```

中间缺少 `10.4`。

### 修改建议

即使高风险回避为 0，也显示：

```markdown
### 10.4 高风险回避（0只）

暂无
```

然后：

```markdown
### 10.5 不可交易过滤（1只）
```

或者如果不想展示空表，则顺延编号：

```text
10.4 不可交易过滤
```

推荐保留空节，因为和 trade_plan 对齐：

```text
10.4 高风险回避（0只）
10.5 不可交易过滤（1只）
```

### 验收标准

观察池章节编号必须连续：

```text
10.1
10.2
10.3
10.4
10.5
```

---

## 9. 修复点九：弱市不做文案去掉病句

### 当前问题

当前弱市不做写：

```text
可计算项中，但涨跌停比仍显示短线活跃。
```

这句话有语病。

### 修改建议

当 `weak_triggers == 0`：

```text
可计算项中，绿盘占比和涨跌停比均未触发弱市信号。
```

当 `weak_triggers >= 1`：

```text
可计算项中，部分指标触发弱市信号，但涨跌停比仍显示短线活跃。
```

### 验收标准

不再出现：

```text
可计算项中，但涨跌停比仍显示短线活跃。
```

---

## 10. 修复点十：数据可信度与“资金流向可用”表述要一致

### 当前问题

日报资金流向已经成功展示行业/概念成交占比变化，但数据可信度里又写：

```text
缺少板块成交占比历史数据，无法展示成交占比变化。
```

这看起来矛盾。

### 判断

如果当前资金流向确实来自可用的 `board_ratio_changes`，则不应再写“无法展示成交占比变化”。

如果这是因为数据库连接失败但文件缓存仍可用，则文案应改成：

```text
数据库连接失败，部分板块历史数据依赖缓存；若缓存缺失，成交占比变化可能不完整。
```

### 修改建议

数据风险中区分：

```text
完全不可用：
缺少板块成交占比历史数据，无法展示成交占比变化。

部分可用：
板块成交占比变化来自缓存或降级数据，完整性需谨慎。
```

### 验收标准

如果日报已经展示了“行业 3日流入/流出”和“产业概念 3日流入/流出”，则不要再写：

```text
无法展示成交占比变化
```

可写：

```text
板块成交占比变化来自缓存或降级数据，完整性需谨慎。
```

---

## 11. 验收命令

### 编译

```bash
python -m compileall analysis
```

### 生成 20260604 日报

```bash
TRADE_DATE=20260604 bash entrypoint.sh
```

或：

```bash
TRADE_DATE=20260604 docker compose run --rm stock-report
```

### 检查文件

```bash
ls reports/daily/*20260604*
```

必须有：

```text
daily_report_20260604.md
daily_summary_20260604.json
trade_plan_20260604.md
trade_plan_20260604.json
```

不应默认要求：

```text
daily_report_20260604_pro.md
```

---

## 12. 最终验收标准

### 12.1 标签表验收

日报中应出现：

```text
短线情绪/风格标签变化 TOP5
```

标题下应有说明：

```text
这些不是产业主线，只反映短线情绪、市场热度、交易风格或资金属性的变化。
```

解读列不得全部是：

```text
不作为产业主线
```

应根据标签写具体含义，例如：

```text
昨日高振幅 → 短线波动增强，资金博弈激烈
东方财富热股 → 热门股成交占比上升
最近多板 → 连板/强势股活跃
近期新高 → 趋势新高股活跃
机构重仓 → 机构属性股票成交占比下降
```

---

### 12.2 市场宽度验收

20260604 不应再出现：

```text
市场宽度偏弱，持续性待确认
市场宽度偏弱，不适合扩散到普买
```

应出现：

```text
市场宽度尚可，但情绪高潮，持续性待确认
市场宽度尚可，但短线情绪处于高潮，不宜追高扩散
```

---

### 12.3 模式标签验收

日报中不应大面积出现：

```text
板块龙头
```

应改为：

```text
主线相关
```

或更保守：

```text
待确认
```

---

### 12.4 交易条件不满足去重验收

20260604 中：

```text
泰和新材 只出现一次；
三孚股份 只出现一次；
策略来源合并为 N字异动 / 二次起爆。
```

---

### 12.5 观察池编号验收

观察池编号连续：

```text
10.1 候选低吸
10.2 只观察
10.3 交易条件不满足
10.4 高风险回避
10.5 不可交易过滤
```

---

### 12.6 弱市不做语句验收

不再出现：

```text
可计算项中，但涨跌停比仍显示短线活跃。
```

应根据触发情况显示：

```text
可计算项中，绿盘占比和涨跌停比均未触发弱市信号。
```

或：

```text
可计算项中，部分指标触发弱市信号，但涨跌停比仍显示短线活跃。
```

---

### 12.7 数据可信度验收

如果资金流向表已经正常展示，则不应再写：

```text
缺少板块成交占比历史数据，无法展示成交占比变化。
```

改为：

```text
板块成交占比变化来自缓存或降级数据，完整性需谨慎。
```

---

## 13. 文件 diff 预期

理想修改文件：

```text
analysis/report_renderer.py
analysis/report_insights.py
```

可能涉及：

```text
analysis/daily_report.py
analysis/email_sender.py
```

不应涉及：

```text
analysis/selector.py
analysis/watchlist_evaluation.py
analysis/evaluation_query.py
analysis/evaluation_scheduler_check.py
analysis/evaluation_email_sender.py
analysis/stock_board_mapper.py
analysis/init_db.py
sql/schema.sql
entrypoint.sh
scripts/evaluation_entrypoint.sh
docker-compose.yml
Dockerfile
crontab
```

---

## 14. 提交建议

验收通过后：

```bash
git add analysis/report_renderer.py analysis/report_insights.py analysis/daily_report.py analysis/email_sender.py
git commit -m "fix: polish final daily report display wording"
git push origin dev
```

如果只改了 renderer / insights：

```bash
git add analysis/report_renderer.py analysis/report_insights.py
git commit -m "fix: polish final daily report display wording"
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

## 15. 最终通过标准

本轮完成后，应达到：

```text
1. 标签表能看懂，不再只有“不作为产业主线”；
2. 主线/机会/风险里的市场宽度口径一致；
3. 不再滥用“板块龙头”；
4. 交易条件不满足不重复列股票；
5. 观察池编号连续；
6. 弱市不做没有语病；
7. 数据可信度与实际展示不矛盾；
8. 不改策略、不改调度、不改数据库。
```


# V4 Email Attachment Scope：日报邮件附件收敛

## 0. 目标

本轮只调整**邮件附件范围**，不减少日报流程每天生成的文件。

也就是说：

```text
所有日报相关产物照常生成；
邮件里只附两个核心文件。
```

---

## 1. 每天仍然照常生成的文件

以下文件每天仍然要生成，不要删除、不停产、不改 pipeline：

```text
daily_report_YYYYMMDD.md
daily_summary_YYYYMMDD.json

trade_plan_YYYYMMDD.md
trade_plan_YYYYMMDD.json

board_trend_report_YYYYMMDD.md
board_trend_summary_YYYYMMDD.json
board_trend_tracker_YYYYMMDD.xlsx

board_mapping_quality_YYYYMMDD.md
board_mapping_quality_YYYYMMDD.json

board_alias_report_YYYYMMDD.md

pipeline_check_YYYYMMDD.json
```

这些文件仍然用于：

```text
日报渲染
交易计划展示
板块趋势追踪
板块映射质量检查
pipeline 自检
后续 evaluation 接入
```

不要因为邮件附件收敛而停止生成这些文件。

---

## 2. 邮件默认只附两个文件

日报邮件默认附件只保留：

```text
1. daily_report_YYYYMMDD.md
2. board_trend_tracker_YYYYMMDD.xlsx
```

原因：

```text
daily_report_YYYYMMDD.md 是每天主报告；
board_trend_tracker_YYYYMMDD.xlsx 是板块趋势结构化明细，适合后续筛选和复盘。
```

---

## 3. 不再默认附的文件

以下文件仍然生成，但不再默认作为邮件附件：

```text
trade_plan_YYYYMMDD.md
trade_plan_YYYYMMDD.json

board_trend_report_YYYYMMDD.md
board_trend_summary_YYYYMMDD.json

board_mapping_quality_YYYYMMDD.md
board_mapping_quality_YYYYMMDD.json

board_alias_report_YYYYMMDD.md

pipeline_check_YYYYMMDD.json
```

说明：

```text
trade_plan 内容已经体现在 daily_report 的观察池和交易计划摘要中；
board_trend_report 是文字版趋势报告，daily_report + xlsx 已覆盖主要用途；
mapping_quality / alias_report 是维护和质检文件，仅在异常时查看；
json 文件主要给程序使用，不适合邮件阅读。
```

---

## 4. 附件缺失处理

### 4.1 daily_report 缺失

如果：

```text
daily_report_YYYYMMDD.md
```

缺失，则日报邮件不应正常发送，应该明确报错或在日志中提示：

```text
主日报缺失，跳过邮件发送。
```

原因：

```text
daily_report 是主附件，缺失说明日报流程异常。
```

### 4.2 board_trend_tracker 缺失

如果：

```text
board_trend_tracker_YYYYMMDD.xlsx
```

缺失，可以继续发送日报邮件，但正文中提示：

```text
board_trend_tracker_YYYYMMDD.xlsx 未生成，板块趋势明细附件缺失。
```

第一版不需要自动改附 `board_trend_report_YYYYMMDD.md`，避免附件范围又变复杂。

---

## 5. email_sender 修改要求

在 `analysis/email_sender.py` 中，附件列表只加入：

```python
daily_report_{date_key}.md
board_trend_tracker_{date_key}.xlsx
```

不要加入：

```python
trade_plan_{date_key}.md
board_trend_report_{date_key}.md
board_mapping_quality_{date_key}.md
board_alias_report_{date_key}.md
*.json
```

伪代码：

```python
attachments = []

daily_report = REPORTS_DIR / f"daily_report_{date_key}.md"
if daily_report.exists():
    attachments.append(daily_report)
else:
    print(f"[邮件] 主日报缺失：{daily_report}，跳过发送")
    return

tracker = REPORTS_DIR / f"board_trend_tracker_{date_key}.xlsx"
if tracker.exists():
    attachments.append(tracker)
else:
    body += f"\n\n---\n板块趋势明细附件缺失：{tracker.name}\n"
```

---

## 6. 邮件正文仍可提示异常

虽然邮件附件只保留两个，但正文仍可以提示：

```text
pipeline_check 关键缺失
board_mapping_quality 异常
数据可信度下降
mapper 映射过期
```

但这些提示来自读取文件或 summary，不代表要把对应文件作为附件。

---

## 7. 验收标准

以 `20260605` 为例，日报流程跑完后：

### 7.1 文件生成验收

以下文件仍应存在：

```text
daily_report_20260605.md
daily_summary_20260605.json
trade_plan_20260605.md
trade_plan_20260605.json
board_trend_report_20260605.md
board_trend_summary_20260605.json
board_trend_tracker_20260605.xlsx
board_mapping_quality_20260605.md
board_mapping_quality_20260605.json
board_alias_report_20260605.md
pipeline_check_20260605.json
```

### 7.2 邮件附件验收

邮件附件只能包含：

```text
daily_report_20260605.md
board_trend_tracker_20260605.xlsx
```

不得包含：

```text
trade_plan_20260605.md
board_trend_report_20260605.md
board_mapping_quality_20260605.md
board_alias_report_20260605.md
任何 json 文件
```

### 7.3 日志验收

如果 `board_trend_tracker_20260605.xlsx` 缺失，邮件仍可发送，但正文或日志应提示：

```text
板块趋势明细附件缺失：board_trend_tracker_20260605.xlsx
```

如果 `daily_report_20260605.md` 缺失，邮件应跳过发送并提示：

```text
主日报缺失，跳过邮件发送。
```

---

## 8. 不允许的改动

本轮不允许为了减少邮件附件而改动：

```text
entrypoint.sh
daily_report.py 的产物生成逻辑
board_trend_tracker 生成逻辑
board_mapping_quality 生成逻辑
board_alias_report 生成逻辑
pipeline_check 生成逻辑
数据库结构
crontab
```

本轮只允许修改：

```text
analysis/email_sender.py
```

---

## 9. 提交建议

```bash
git add analysis/email_sender.py
git commit -m "fix: limit daily email attachments"
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