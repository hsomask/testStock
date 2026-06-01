# V3-Stabilization M2：报告口径与展示一致性收敛包

## 当前项目背景

项目：`testStock`

当前阶段：

> V3-Stabilization：日报系统口径统一与稳定性收敛

目前已完成：

| 阶段      | 内容                                        | 状态   |
| ------- | ----------------------------------------- | ---- |
| 第 0 轮   | 结构占位                                      | done |
| 第 1 轮   | report_context 最小接入                       | done |
| 第 2 轮   | pipeline_check + email 联动                 | done |
| 第 3 轮   | selector 安全边界                             | done |
| 第 4 轮   | 代码框架梳理                                    | done |
| 第 5 轮   | 数据真实性与产物链一致性 review                       | done |
| 第 6 轮   | report_context 最小填充                       | done |
| 第 7 轮   | report_context 填充结果 review                | done |
| 第 8/9 轮 | report_regression_check 第一版 + 真实 error 修复 | done |

当前 `report_regression_check` 已能跑通，并已修复：

* `old_terms`：旧词“市场情绪评分”；
* `high_risk_duplicate`：高风险票重复展示。

现在进入一个中等批量收敛包：

> M2：报告口径与展示一致性收敛

本轮可以改代码，但只收敛“报告表达与展示一致性”，不要改策略和主链路。

---

## 一、本轮目标

本轮目标是一次性检查并收敛以下内容：

1. 小白版、专业版、邮件正文中的字段名称是否一致；
2. `market_score` 是否统一展示为“市场综合评分”；
3. `sentiment_score` 是否统一展示为“短线情绪周期评分”；
4. `market_status` 是否统一展示为“市场综合状态”；
5. 板块相关名称是否区分：

   * 原始板块名；
   * 归一后的板块名；
   * 主线类型；
   * 主线强度；
6. 观察池分层是否统一：

   * 可观察；
   * 谨慎观察；
   * 高风险复盘；
   * 回避；
   * 不可交易；
7. trend_summary 缺失时，小白版和专业版提示是否一致；
8. board_mapping_quality 缺失或降级时，报告和邮件是否有明确提示；
9. 邮件正文是否和日报口径一致；
10. `report_regression_check.py` 是否需要补充对应检查。

---

## 二、本轮允许修改的文件

本轮允许修改：

```text
analysis/report_renderer.py
analysis/email_sender.py
analysis/explainer.py
analysis/context/field_dictionary.py
analysis/report_regression_check.py
```

如果发现字段口径是在 `daily_report.py` 中组装时产生的，可以小范围修改：

```text
analysis/daily_report.py
```

但仅允许做字段命名、传参、文案口径修正，不允许改业务逻辑。

---

## 三、本轮禁止修改的文件

禁止修改：

```text
analysis/selector.py
analysis/pipeline_check.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_trend_tracker.py
analysis/board_mapping_quality.py
analysis/context/report_context.py
entrypoint.sh
```

除非发现一个明确的文案常量在这些文件中，且只做纯文案替换，否则不要改。

---

## 四、本轮禁止事项

禁止做：

```text
新增策略
修改策略阈值
修改观察池入池逻辑
修改高风险判定逻辑
修改 market_score 计算
修改 sentiment_score 计算
修改 pipeline_check 规则
修改 entrypoint 主链路
拆分 report_renderer.py
大规模重构 daily_report.py
让 renderer 开始消费 report_context
提交 reports 产物
提交 __pycache__
提交 .claude 本地配置
提交 PRDs/V3-Stabilization.md
```

本轮是“报告口径和展示一致性收敛”，不是策略优化，不是结构重构。

---

## 五、先确认当前状态

执行：

```bash
git checkout dev
git pull origin dev
git status --short
git log -5 --oneline
```

允许：

```text
M PRDs/V3-Stabilization.md
```

这是用户本地迭代日志，不提交。

如果出现其他文件，例如：

```text
analysis/*.py
reports/
__pycache__/
.claude/
```

请先停止，说明污染项。

---

## 六、检查字段命名残留

执行：

```bash
grep -R "市场情绪评分\|市场宽度评分\|市场综合评分\|短线情绪周期评分\|市场综合状态" -n analysis
```

要求：

1. `market_score` 统一叫：

```text
市场综合评分
```

2. `sentiment_score` 统一叫：

```text
短线情绪周期评分
```

3. `market_status` 统一叫：

```text
市场综合状态
```

4. 不应再把 `market_score` 叫成：

```text
市场情绪评分
市场宽度评分
```

5. 如果“市场宽度评分”确实表示单独的宽度指标，必须确认字段是 `market_width_score`，不能混用 `market_score`。

---

## 七、检查 field_dictionary.py

查看：

```bash
sed -n '1,220p' analysis/context/field_dictionary.py
```

确认至少包含：

```python
FIELD_LABELS = {
    "market_score": "市场综合评分",
    "market_status": "市场综合状态",
    "market_width_score": "市场宽度评分",
    "hotspot_score": "热点活跃评分",
    "sentiment_score": "短线情绪周期评分",
    "sentiment_stage": "短线情绪周期阶段",
    "raw_board_name": "原始板块名",
    "board_display_name": "归一后的板块名",
    "theme_type": "主线类型",
    "theme_strength": "主线强度",
    "watchlist_layer": "观察池分层",
}
```

如果字段缺失，可以补充。
不要删除已有字段。

---

## 八、检查小白版 / 专业版口径

查看：

```bash
grep -n "市场综合评分\|市场情绪评分\|短线情绪周期评分\|市场综合状态\|可观察\|谨慎观察\|高风险复盘\|回避\|不可交易" analysis/report_renderer.py
```

检查：

1. 小白版是否使用“市场综合评分”；
2. 专业版是否使用“市场综合评分”；
3. 小白版是否使用“短线情绪周期评分”；
4. 专业版是否使用“短线情绪周期评分”；
5. 观察池分层名称是否一致；
6. 高风险票是否只出现在高风险复盘；
7. 不可交易 / 不可买提示是否清晰；
8. trend_summary 缺失提示是否明确；
9. 小白版和专业版对缺失数据的提示是否一致。

---

## 九、检查邮件正文口径

查看：

```bash
grep -n "市场综合评分\|市场情绪评分\|短线情绪周期评分\|市场综合状态\|流程检查\|关键缺失\|非关键缺失" analysis/email_sender.py
```

检查：

1. 邮件正文是否使用“市场综合评分”；
2. 邮件正文是否使用“短线情绪周期评分”；
3. 邮件正文是否和日报用词一致；
4. pipeline_check 的缺失提示是否清晰；
5. 邮件正文是否仍可能出现“市场情绪评分”；
6. 邮件是否把缺失文件提示为“成功”或“正常”。

---

## 十、检查 AI 文案 / explainer

查看：

```bash
grep -n "市场综合评分\|市场情绪评分\|短线情绪周期评分\|市场宽度评分\|AI\|prompt\|提示" analysis/explainer.py analysis/report_renderer.py analysis/daily_report.py 2>/dev/null
```

检查：

1. AI 文案里是否还把 `market_score` 叫成“市场情绪评分”；
2. AI 文案是否会把市场综合评分、短线情绪、市场宽度混在一起；
3. 如果只是 prompt 文案错误，只修文案；
4. 不改 AI 逻辑；
5. 不改评分逻辑。

---

## 十一、缺失数据提示统一

检查以下缺失情况在报告里是否有明确提示：

```text
board_trend_summary 缺失
board_mapping_quality 降级
pipeline_check critical_missing
数据质量异常
```

要求：

1. 小白版不要静默隐藏关键缺失；
2. 专业版可以更详细；
3. 邮件正文要有简短提示；
4. 缺失提示不要误写成“正常”；
5. 不要新增复杂逻辑，只统一提示表达。

---

## 十二、report_regression_check 增强

如果本轮修正文案或展示口径，请同步增强 `analysis/report_regression_check.py`。

建议新增或确认以下检查：

1. `market_score` 不得出现旧名“市场情绪评分”；
2. 小白版和专业版都不得出现旧名；
3. 邮件正文如果可检查，则不得出现旧名；
4. 高风险票不得和可观察 / 谨慎观察重复；
5. trend_summary 缺失但报告无提示时 warning；
6. 板块重复层级仍为 warning。

注意：

不要把回归检查写得太复杂。
宁可第一版简单可靠，不要误报太多。

---

## 十三、运行检查

完成修改后执行：

```bash
python -m compileall analysis
python -m analysis.report_regression_check --date 20260528
cat reports/daily/report_regression_check_20260528.json
git diff --stat
git status --short --untracked-files=all
```

如果本地数据完整，可以重新生成日报：

```bash
python -m analysis.daily_report --mode both --date 20260528
python -m analysis.report_regression_check --date 20260528
```

注意：

```text
reports/daily/report_regression_check_20260528.json
reports/daily/daily_report_20260528.md
reports/daily/daily_report_20260528_pro.md
```

都是运行产物，不要提交。

---

## 十四、预期 diff

本轮理想 diff 可能包含：

```text
analysis/report_renderer.py
analysis/email_sender.py
analysis/explainer.py
analysis/context/field_dictionary.py
analysis/report_regression_check.py
```

可选包含：

```text
analysis/daily_report.py
```

不应该出现：

```text
analysis/selector.py
analysis/pipeline_check.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_trend_tracker.py
analysis/board_mapping_quality.py
analysis/context/report_context.py
entrypoint.sh
reports/
__pycache__/
.claude/
PRDs/V3-Stabilization.md
```

---

## 十五、提交要求

如果验收通过，提交：

```bash
git add analysis/report_renderer.py \
        analysis/email_sender.py \
        analysis/explainer.py \
        analysis/context/field_dictionary.py \
        analysis/report_regression_check.py \
        analysis/daily_report.py

git commit -m "fix: align report terminology and display consistency"
```

没有修改的文件会自动忽略。

不要提交：

```text
PRDs/V3-Stabilization.md
reports/
__pycache__/
.claude/
```

不要 push。

提交后发回：

```bash
git log -3 --oneline
git status --short
git diff HEAD~1 --stat
python -m analysis.report_regression_check --date 20260528
```

---

## 十六、本轮通过标准

本轮通过标准：

1. `compileall` 通过；
2. `report_regression_check` 为 ok，或只有可解释 warning；
3. 不再出现错误的“市场情绪评分”；
4. 市场综合评分 / 短线情绪周期评分 / 市场综合状态用词一致；
5. 小白版、专业版、邮件正文口径一致；
6. 高风险票展示不重复；
7. 缺失提示不静默；
8. 不改 selector 策略逻辑；
9. 不改 pipeline 主逻辑；
10. 不改 entrypoint；
11. 无 reports / pycache / local config 进入 Git。

# V3-Stabilization M3：report_context 消费闭环 Review + 最小接入方案

## 当前项目背景

项目：`testStock`

当前阶段：

> V3-Stabilization：日报系统口径统一与稳定性收敛

当前已完成：

| 阶段      | 内容                                        | 状态   |
| ------- | ----------------------------------------- | ---- |
| 第 0 轮   | 结构占位                                      | done |
| 第 1 轮   | report_context 最小接入                       | done |
| 第 2 轮   | pipeline_check + email 联动                 | done |
| 第 3 轮   | selector 安全边界                             | done |
| 第 4 轮   | 代码框架梳理                                    | done |
| 第 5 轮   | 数据真实性与产物链一致性 review                       | done |
| 第 6 轮   | report_context 最小填充                       | done |
| 第 7 轮   | report_context 填充结果 review                | done |
| 第 8/9 轮 | report_regression_check 第一版 + 真实 error 修复 | done |
| M2      | 报告口径与展示一致性收敛                              | done |

当前状态：

* `report_regression_check` 已经能跑通；
* 回归检查结果为 `ok: 0 errors / 0 warnings`；
* `report_context` 当前已经填入 `market / sentiment / quality`；
* 但 `report_context` 仍然是旁路对象，没有被 renderer / email 正式消费。

本轮进入：

> M3：report_context 消费闭环 Review + 最小接入方案

---

## 一、本轮目标

本轮目标是让 `report_context` 从“旁路对象”逐步变成“统一数据源”。

但不要一次性改所有渲染。

本轮重点：

1. 梳理当前 `report_context` 已经包含哪些字段；
2. 梳理当前小白版、专业版、邮件正文分别从哪里取 market / sentiment / quality；
3. 找一个最低风险消费点；
4. 优先设计让该消费点读取 `report_context`；
5. 不改变日报输出内容；
6. 不改变观察池逻辑；
7. 不改变邮件附件逻辑；
8. 不改变 pipeline 逻辑；
9. 不大改 `report_renderer.py`。

---

## 二、本轮建议策略

本轮采用“两步走”。

### Step 1：先 Review

先判断以下哪个消费点最适合第一版接入：

```text
A. email_sender.py 的邮件摘要
B. report_renderer.py 的市场/情绪标题区域
C. daily_summary_YYYYMMDD.json 的 market/sentiment 字段
D. 暂时不消费，只保存 context debug
```

优先级建议：

```text
优先 A 或 C
暂缓 B
不建议 D
```

原因：

* 邮件摘要和 daily_summary 较轻，风险相对低；
* 小白版/专业版完整 renderer 改动范围大，暂缓；
* 保存 context debug 会新增产物，当前暂缓。

---

## 三、本轮禁止事项

本轮禁止：

```text
重构 report_renderer.py
拆分 renderer
让小白版和专业版同时大规模改为读取 report_context
修改 selector
修改策略阈值
修改观察池分层
修改 pipeline_check
修改 entrypoint
修改数据源
新增 reports 产物
提交 reports 产物
提交 __pycache__
提交 .claude 本地配置
提交 PRDs/V3-Stabilization.md
提交 PRDs/V3-StabilizationM2.md
```

---

## 四、本轮允许查看的文件

请查看：

```bash
sed -n '1,260p' analysis/context/report_context.py
sed -n '1,360p' analysis/daily_report.py
sed -n '1,320p' analysis/report_renderer.py
sed -n '1,320p' analysis/email_sender.py
```

并搜索：

```bash
grep -R "report_context\|build_report_context\|market_result\|sentiment_result\|quality" -n analysis
grep -R "市场综合评分\|短线情绪周期评分\|市场综合状态" -n analysis
```

---

## 五、Review 重点

请回答以下问题。

### 1. report_context 当前字段

输出：

```markdown
| 字段 | 当前是否填充 | 来源 | 是否稳定 | 是否适合被消费 |
|---|---|---|---|---|
| trade_date |  |  |  |  |
| market |  |  |  |  |
| sentiment |  |  |  |  |
| quality |  |  |  |  |
| boards |  |  |  |  |
| themes |  |  |  |  |
| watchlists |  |  |  |  |
| trade_plan |  |  |  |  |
| pipeline |  |  |  |  |
```

---

### 2. 当前消费路径

请梳理：

```markdown
| 输出位置 | 当前数据来源 | 是否与 context 重复 | 风险 |
|---|---|---|---|
| 小白版市场摘要 |  |  |  |
| 专业版市场摘要 |  |  |  |
| 邮件正文市场摘要 |  |  |  |
| daily_summary JSON |  |  |  |
```

---

### 3. 最小接入点选择

请判断第一版最适合哪个方案：

```text
方案 A：email_sender.py 读取 daily_summary 中的 context-like 字段
方案 B：daily_report.py 在生成 daily_summary 时加入 context.market / context.sentiment / context.quality
方案 C：report_renderer.py 的市场/情绪小段读取 report_context
方案 D：暂不接入，继续旁路
```

推荐优先考虑：

```text
方案 B：daily_summary 先承载 context 的 market/sentiment/quality
```

原因：

* `daily_summary_YYYYMMDD.json` 已经是正式产物；
* email_sender 已经读取 daily_summary；
* 不需要新增 report_context JSON 产物；
* 不需要立即重构 renderer；
* 以后 email 和 renderer 都可以逐步从 daily_summary/context 取数。

---

## 六、如果进入代码修改，最小方案建议

如果 review 后确认可改，建议只做这个最小闭环：

### 修改目标

让 `daily_summary_YYYYMMDD.json` 中增加一个字段：

```json
{
  "report_context": {
    "market": {},
    "sentiment": {},
    "quality": {}
  }
}
```

或者更轻量：

```json
{
  "context": {
    "market": {},
    "sentiment": {},
    "quality": {}
  }
}
```

推荐使用：

```text
report_context
```

理由：名称和代码一致。

---

### 修改范围

只允许修改：

```text
analysis/daily_report.py
analysis/context/report_context.py
```

可选修改：

```text
analysis/report_regression_check.py
```

用于确认 `daily_summary_YYYYMMDD.json` 中存在 `report_context.market / sentiment / quality`。

---

### 不修改

```text
analysis/report_renderer.py
analysis/email_sender.py
analysis/selector.py
analysis/pipeline_check.py
entrypoint.sh
```

---

## 七、注意事项

如果给 `daily_summary` 增加 `report_context` 字段，必须满足：

1. 不删除原有字段；
2. 不改原有字段名；
3. 不影响 email_sender 当前读取逻辑；
4. 不影响 pipeline_check；
5. 不影响报告 Markdown；
6. 不保存单独 `report_context_YYYYMMDD.json`；
7. 不引入 fallback/latest；
8. 不放入大体量 DataFrame；
9. 只放轻量摘要。

---

## 八、运行检查

如果本轮只是 review，则执行：

```bash
git status --short
```

如果本轮进入代码修改，则执行：

```bash
python -m compileall analysis
python -m analysis.daily_report --mode both --date 20260528
python -m analysis.report_regression_check --date 20260528
cat reports/daily/daily_summary_20260528.json
git diff --stat
git status --short --untracked-files=all
```

注意：

```text
reports/daily/*.json
reports/daily/*.md
```

是运行产物，不要提交。

---

## 九、Review 输出格式

请先按以下格式输出 review 结果：

```markdown
# V3-Stabilization M3 Review：report_context 消费闭环

## 1. 总体结论

是否建议进入代码修改：
推荐最小接入点：
是否会影响现有输出：

## 2. report_context 当前字段

| 字段 | 当前是否填充 | 来源 | 是否稳定 | 是否适合消费 |
|---|---|---|---|---|

## 3. 当前输出消费路径

| 输出位置 | 当前来源 | 与 context 是否重复 | 风险 |
|---|---|---|---|

## 4. 最小接入方案

说明选择 A / B / C / D 哪个方案。

## 5. 建议修改文件

| 文件 | 修改内容 | 风险 |
|---|---|---|

## 6. 不建议修改的文件

列出并说明原因。

## 7. 验收方式

说明需要运行哪些命令。

## 8. 是否进入代码修改

是 / 否
```

---

## 十、如果 review 结论明确，可以直接进入最小代码修改

如果确认选择：

```text
方案 B：daily_summary 增加 report_context.market/sentiment/quality
```

可以直接实施，不需要再等下一轮。

提交要求：

```bash
git add analysis/daily_report.py analysis/context/report_context.py analysis/report_regression_check.py
git commit -m "chore: expose report context in daily summary"
```

未修改的文件会自动忽略。

不要提交：

```text
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
reports/
__pycache__/
.claude/
```

提交后返回：

```bash
git log -3 --oneline
git status --short
git diff HEAD~1 --stat
python -m analysis.report_regression_check --date 20260528
```

---

## 十一、本轮通过标准

本轮通过标准：

1. 明确 `report_context` 当前字段；
2. 明确第一个消费点；
3. 如果改代码，只改 `daily_summary` 暴露 context；
4. 不改 renderer；
5. 不改 email_sender；
6. 不改 selector；
7. 不改 pipeline_check；
8. 不新增独立 report_context 产物；
9. 回归检查仍为 ok；
10. 无 reports / pycache / local config 进入 Git。

# V3-Stabilization M4：email_sender 消费 daily_summary.report_context

## 当前项目背景

项目：`testStock`

当前阶段：

> V3-Stabilization：日报系统口径统一与稳定性收敛

当前已完成：

| 阶段      | 内容                                                       | 状态   |
| ------- | -------------------------------------------------------- | ---- |
| 第 0 轮   | 结构占位                                                     | done |
| 第 1 轮   | report_context 最小接入                                      | done |
| 第 2 轮   | pipeline_check + email 联动                                | done |
| 第 3 轮   | selector 安全边界                                            | done |
| 第 4 轮   | 代码框架梳理                                                   | done |
| 第 5 轮   | 数据真实性与产物链一致性 review                                      | done |
| 第 6 轮   | report_context 最小填充                                      | done |
| 第 7 轮   | report_context 填充结果 review                               | done |
| 第 8/9 轮 | report_regression_check 第一版 + 真实 error 修复                | done |
| M2      | 报告口径与展示一致性收敛                                             | done |
| M3      | daily_summary 暴露 report_context.market/sentiment/quality | done |

当前状态：

* `daily_summary_YYYYMMDD.json` 已新增 `report_context.market / sentiment / quality`；
* `report_regression_check` 结果为 `0 errors / 0 warnings`；
* `report_context` 已进入正式产物链；
* 但 `email_sender.py` 目前还未明确消费 `daily_summary.report_context`。

本轮目标：

> 让 `email_sender.py` 优先从 `daily_summary.report_context` 读取 market / sentiment / quality，用于邮件正文摘要。

这是第一个真正的 `report_context` 消费闭环。

---

## 一、本轮目标

本轮做一个中等但边界清楚的改动：

```text id="p3er35"
daily_report.py
  -> daily_summary_YYYYMMDD.json
      -> report_context.market / sentiment / quality
          -> email_sender.py
```

具体目标：

1. `email_sender.py` 读取 `daily_summary_YYYYMMDD.json`；
2. 如果其中存在 `report_context.market / sentiment / quality`，优先使用这些字段；
3. 如果不存在，兼容旧结构，不报错；
4. 邮件正文口径继续保持：

   * 市场综合评分；
   * 市场综合状态；
   * 短线情绪周期评分；
   * 短线情绪周期阶段；
5. 不改变附件逻辑；
6. 不改变 pipeline_check 读取逻辑；
7. 不改变 daily_report 输出；
8. 不改 selector；
9. 不改 report_renderer；
10. 不接入 entrypoint。

---

## 二、本轮允许修改的文件

本轮允许修改：

```text id="jofr1m"
analysis/email_sender.py
analysis/report_regression_check.py
```

如果发现 `daily_summary.report_context` 字段结构有明显缺口，可以小范围修改：

```text id="e9bv6f"
analysis/daily_report.py
```

但原则上本轮优先只改 `email_sender.py`。

---

## 三、本轮禁止修改的文件

禁止修改：

```text id="f8q9tv"
analysis/selector.py
analysis/pipeline_check.py
analysis/report_renderer.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_trend_tracker.py
analysis/board_mapping_quality.py
entrypoint.sh
```

---

## 四、本轮禁止事项

禁止做：

```text id="l13tpq"
新增策略
修改观察池逻辑
修改 selector 阈值
修改 pipeline_check 规则
修改附件收集逻辑
修改 zip 逻辑
修改小白版/专业版报告渲染
让 report_renderer 消费 report_context
修改 entrypoint
新增独立 report_context JSON 产物
提交 reports 产物
提交 __pycache__
提交 .claude 本地配置
提交 PRDs/V3-Stabilization.md
提交 PRDs/V3-StabilizationM2.md
```

---

## 五、先确认当前状态

执行：

```bash id="b8z7d9"
git checkout dev
git pull origin dev
git status --short
git log -5 --oneline
```

允许：

```text id="u69xje"
M PRDs/V3-Stabilization.md
M PRDs/V3-StabilizationM2.md
```

这是用户本地迭代日志，不提交。

如果出现其他文件，请先停止并说明。

---

## 六、查看 daily_summary 当前结构

执行：

```bash id="mcvgn3"
python -m analysis.daily_report --mode both --date 20260528
cat reports/daily/daily_summary_20260528.json
```

确认里面是否包含：

```json id="04yexh"
{
  "report_context": {
    "market": {},
    "sentiment": {},
    "quality": {}
  }
}
```

如果没有，先停止，不要强行改 email_sender。

---

## 七、email_sender.py 修改要求

查看：

```bash id="paibmb"
sed -n '1,360p' analysis/email_sender.py
grep -n "daily_summary\|market\|sentiment\|市场综合评分\|短线情绪周期评分\|pipeline_check" analysis/email_sender.py
```

请做最小改造：

### 1. 增加读取 context 的辅助函数

建议增加：

```python id="q49ckh"
def get_report_context_from_summary(summary: dict) -> dict:
    context = summary.get("report_context") or {}
    if not isinstance(context, dict):
        return {}
    return context
```

或者直接在现有 summary 读取逻辑里处理。

---

### 2. 优先使用 report_context

如果当前邮件正文用的是：

```python id="s4odnk"
summary.get("market_score")
summary.get("sentiment_score")
```

则改为优先：

```python id="e1ab2g"
context = summary.get("report_context", {})
market = context.get("market", {})
sentiment = context.get("sentiment", {})
quality = context.get("quality", {})
```

并兼容旧字段：

```python id="wa8jlp"
market_score = market.get("score", summary.get("market_score"))
market_status = market.get("status", summary.get("market_status"))

sentiment_score = sentiment.get("score", summary.get("sentiment_score"))
sentiment_stage = sentiment.get("stage", summary.get("sentiment_stage"))
```

注意：字段名按当前实际 `daily_summary` 结构调整。

---

### 3. 邮件正文显示名称必须统一

邮件正文中必须使用：

```text id="wrek1y"
市场综合评分
市场综合状态
短线情绪周期评分
短线情绪周期阶段
```

不得使用：

```text id="lqqvc4"
市场情绪评分
```

---

### 4. 兼容旧 daily_summary

如果旧 summary 没有 `report_context`，邮件仍然可以发送，不报错。

不要因为缺失 `report_context` 阻断邮件。

---

### 5. 不改变 pipeline_check 逻辑

保留当前：

```text id="et0ak5"
email_sender 读取 pipeline_check_YYYYMMDD.json
邮件正文提示 critical / non-critical 缺失
```

不要修改这一段，除非只是调整位置或保持文案一致。

---

## 八、report_regression_check 增强要求

可以小幅增强：

```text id="58h1b7"
检查 daily_summary_YYYYMMDD.json 中是否存在 report_context.market / sentiment / quality
```

建议检查名：

```text id="o9fp47"
summary_context
```

等级：

```text id="w4wyxl"
warning
```

规则：

1. 如果 `daily_summary_YYYYMMDD.json` 不存在，已有其他检查负责；
2. 如果存在但没有 `report_context`，warning；
3. 如果有 `report_context` 但缺 `market / sentiment / quality`，warning；
4. 不作为 error，避免影响旧产物兼容。

---

## 九、运行检查

修改完成后执行：

```bash id="lyd7cb"
python -m compileall analysis

python -m analysis.daily_report --mode both --date 20260528
python -m analysis.report_regression_check --date 20260528
cat reports/daily/report_regression_check_20260528.json

git diff --stat
git status --short --untracked-files=all
```

如果可以测试邮件但不想真实发送，可以只确认 `email_sender.py` 的正文生成函数。
如果当前脚本没有 dry-run，不要为了本轮新增复杂 dry-run。

---

## 十、预期 diff

理想 diff：

```text id="xsb9s7"
analysis/email_sender.py
analysis/report_regression_check.py
```

可选：

```text id="78v0t5"
analysis/daily_report.py
```

不应该出现：

```text id="6p21yr"
analysis/report_renderer.py
analysis/selector.py
analysis/pipeline_check.py
analysis/context/report_context.py
entrypoint.sh
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十一、提交要求

如果验收通过，提交：

```bash id="sa5x8n"
git add analysis/email_sender.py analysis/report_regression_check.py analysis/daily_report.py
git commit -m "chore: consume report context in email summary"
```

未修改文件会自动忽略。

不要提交：

```text id="8e9fsr"
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
reports/
__pycache__/
.claude/
```

不要 push。

提交后发回：

```bash id="6wg2t8"
git log -3 --oneline
git status --short
git diff HEAD~1 --stat
python -m analysis.report_regression_check --date 20260528
```

---

## 十二、本轮通过标准

本轮通过标准：

1. `email_sender.py` 优先消费 `daily_summary.report_context.market/sentiment/quality`；
2. 兼容旧 summary；
3. 邮件正文口径不变或更统一；
4. 不改附件逻辑；
5. 不改 pipeline_check 逻辑；
6. 不改 report_renderer；
7. 不改 selector；
8. `report_regression_check` 保持 ok 或只有合理 warning；
9. 无 reports / pycache / local config 进入 Git。

# V3-Stabilization M5：report_renderer 局部消费 report_context

## 当前项目背景

项目：`testStock`

当前阶段：

> V3-Stabilization：日报系统口径统一与稳定性收敛

当前已完成：

| 阶段      | 内容                                           | 状态   |
| ------- | -------------------------------------------- | ---- |
| 第 0 轮   | 结构占位                                         | done |
| 第 1 轮   | report_context 最小接入                          | done |
| 第 2 轮   | pipeline_check + email 联动                    | done |
| 第 3 轮   | selector 安全边界                                | done |
| 第 4 轮   | 代码框架梳理                                       | done |
| 第 5 轮   | 数据真实性与产物链一致性 review                          | done |
| 第 6 轮   | report_context 最小填充                          | done |
| 第 7 轮   | report_context 填充结果 review                   | done |
| 第 8/9 轮 | report_regression_check 第一版 + 真实 error 修复    | done |
| M2      | 报告口径与展示一致性收敛                                 | done |
| M3      | daily_summary 暴露 report_context              | done |
| M4      | email_sender 消费 daily_summary.report_context | done |

当前状态：

* `daily_summary_YYYYMMDD.json` 已包含 `report_context.market / sentiment / quality`；
* `email_sender.py` 已消费 `daily_summary.report_context`；
* `report_regression_check` 为 `0 errors / 0 warnings`；
* 小白版 / 专业版 `report_renderer.py` 还没有正式消费 `report_context`。

本轮目标：

> 让 `report_renderer.py` 的“市场摘要 / 情绪摘要”局部开始消费 `report_context`，形成日报渲染层的最小闭环。

---

## 一、本轮目标

本轮只做一个局部改造：

```text
小白版 / 专业版中的市场摘要与情绪摘要
优先从 report_context.market / report_context.sentiment 取值
```

但不改变报告整体结构。

具体目标：

1. 小白版市场摘要优先使用 `report_context.market`；
2. 小白版情绪摘要优先使用 `report_context.sentiment`；
3. 专业版市场摘要优先使用 `report_context.market`；
4. 专业版情绪摘要优先使用 `report_context.sentiment`；
5. 如果 `report_context` 不存在或字段为空，兼容旧参数 / 旧字段；
6. 报告文案保持当前口径：

   * 市场综合评分；
   * 市场综合状态；
   * 短线情绪周期评分；
   * 短线情绪周期阶段；
7. 不改观察池；
8. 不改高风险展示；
9. 不改板块趋势表；
10. 不改 AI 策略解释逻辑。

---

## 二、本轮允许修改的文件

本轮允许修改：

```text
analysis/report_renderer.py
analysis/daily_report.py
analysis/report_regression_check.py
```

说明：

* `report_renderer.py`：局部接入 `report_context`；
* `daily_report.py`：如果需要把 `report_context` 传给 renderer，可做最小传参；
* `report_regression_check.py`：如果需要补充检查，可小幅增强。

---

## 三、本轮禁止修改的文件

禁止修改：

```text
analysis/selector.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_trend_tracker.py
analysis/board_mapping_quality.py
entrypoint.sh
```

除非发现明确文案常量，但本轮原则上不要碰。

---

## 四、本轮禁止事项

禁止做：

```text
新增策略
修改选股逻辑
修改观察池分层
修改高风险判定
修改邮件逻辑
修改 pipeline_check
修改 entrypoint
拆分 report_renderer.py
大规模重构 renderer
改变报告章节结构
改变 daily_summary 结构
新增 report_context JSON 产物
提交 reports 产物
提交 __pycache__
提交 .claude 本地配置
提交 PRDs/V3-Stabilization.md
提交 PRDs/V3-StabilizationM2.md
```

本轮是“局部消费 context”，不是重构 renderer。

---

## 五、先确认当前状态

执行：

```bash
git checkout dev
git pull origin dev
git status --short
git log -5 --oneline
```

允许：

```text
M PRDs/V3-Stabilization.md
M PRDs/V3-StabilizationM2.md
```

这是用户本地迭代日志，不提交。

如果出现其他文件，请先停止并说明。

---

## 六、查看当前 renderer 调用方式

执行：

```bash
grep -R "render_.*report\|report_renderer\|build_report_context\|report_context" -n analysis/daily_report.py analysis/report_renderer.py
```

并查看相关函数：

```bash
sed -n '1,260p' analysis/report_renderer.py
sed -n '260,560p' analysis/report_renderer.py
```

请先判断：

1. 小白版渲染函数叫什么；
2. 专业版渲染函数叫什么；
3. 当前市场评分和情绪评分从哪里传入；
4. `daily_report.py` 是否已经持有 `report_context`；
5. 是否可以只增加一个可选参数 `report_context=None`。

---

## 七、推荐实现方式

### 1. 不改变原函数调用的兼容性

如果当前函数类似：

```python
render_beginner_report(..., market_result, sentiment_result, ...)
render_pro_report(..., market_result, sentiment_result, ...)
```

不要破坏原调用。

可以增加可选参数：

```python
report_context: dict | None = None
```

例如：

```python
def render_beginner_report(..., report_context: dict | None = None):
    ...
```

如果项目 Python 版本或风格不适合 `dict | None`，使用：

```python
from typing import Optional

def render_beginner_report(..., report_context: Optional[dict] = None):
    ...
```

---

### 2. 增加小工具函数提取 market/sentiment

可以在 `report_renderer.py` 内部增加轻量函数：

```python
def _get_context_section(report_context: dict | None, name: str) -> dict:
    if not isinstance(report_context, dict):
        return {}
    section = report_context.get(name) or {}
    return section if isinstance(section, dict) else {}
```

然后：

```python
market_context = _get_context_section(report_context, "market")
sentiment_context = _get_context_section(report_context, "sentiment")
```

---

### 3. 优先 context，兼容旧字段

示例逻辑：

```python
market_score = market_context.get("score", old_market_score)
market_status = market_context.get("status", old_market_status)

sentiment_score = sentiment_context.get("score", old_sentiment_score)
sentiment_stage = sentiment_context.get("stage", old_sentiment_stage)
```

字段名必须按当前 `daily_summary.report_context` 实际结构调整。

---

### 4. daily_report.py 只做最小传参

如果当前已经有：

```python
report_context = build_report_context(...)
```

则在调用 renderer 时传入：

```python
report_context=report_context
```

不要在 `daily_report.py` 里重组新的 dict。

---

## 八、不能改变的输出

本轮不应改变这些内容：

```text
观察池股票列表
高风险复盘池
谨慎观察池
可观察池
板块趋势表
交易计划
pipeline_check
email 正文
附件逻辑
```

允许的输出变化只限于：

```text
市场摘要 / 情绪摘要取值来源变为 report_context
```

但由于 context 目前来自同一批变量，理论上文本应保持一致。

---

## 九、report_regression_check 增强

可以小幅增强：

1. 检查小白版和专业版都出现：

   * 市场综合评分；
   * 短线情绪周期评分；
2. 检查不出现：

   * 市场情绪评分；
3. 继续保持 old_terms 检查；
4. 不要写复杂 Markdown 解析。

如果当前已有相关检查，则不要重复增加。

---

## 十、运行检查

修改完成后执行：

```bash
python -m compileall analysis

python -m analysis.daily_report --mode both --date 20260528
python -m analysis.report_regression_check --date 20260528

cat reports/daily/report_regression_check_20260528.json

git diff --stat
git status --short --untracked-files=all
```

如果可以，请额外检查：

```bash
grep -n "市场综合评分\|短线情绪周期评分\|市场情绪评分" reports/daily/daily_report_20260528.md
grep -n "市场综合评分\|短线情绪周期评分\|市场情绪评分" reports/daily/daily_report_20260528_pro.md
```

---

## 十一、预期 diff

理想 diff：

```text
analysis/report_renderer.py
analysis/daily_report.py
```

可选：

```text
analysis/report_regression_check.py
```

不应该出现：

```text
analysis/selector.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/context/report_context.py
entrypoint.sh
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十二、提交要求

如果验收通过，提交：

```bash
git add analysis/report_renderer.py analysis/daily_report.py analysis/report_regression_check.py
git commit -m "chore: consume report context in report renderer"
```

未修改文件会自动忽略。

不要提交：

```text
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
reports/
__pycache__/
.claude/
```

不要 push。

提交后发回：

```bash
git log -3 --oneline
git status --short
git diff HEAD~1 --stat
python -m analysis.report_regression_check --date 20260528
```

---

## 十三、本轮通过标准

本轮通过标准：

1. `report_renderer.py` 局部支持 `report_context`；
2. 小白版市场 / 情绪摘要优先从 context 取值；
3. 专业版市场 / 情绪摘要优先从 context 取值；
4. 兼容旧参数；
5. 不改观察池；
6. 不改策略；
7. 不改 email；
8. 不改 pipeline；
9. 回归检查为 ok，或只有合理 warning；
10. 无 reports / pycache / local config 进入 Git。

# M5-fix：补齐 report_renderer 真正消费 report_context 的调用链

## 当前问题

上一轮 M5 没有真正完成。

当前代码里已经有：

```python
def _get_context_section(report_context, name):
    ...
```

但这只是辅助函数。

实际问题是：

```text
report_context 没有从 daily_report.py 传到 report_renderer.py
render_daily_report 没有 report_context 参数
render_beginner_report 没有 report_context 参数
render_pro_report 没有 report_context 参数
市场/情绪摘要也没有实际从 report_context 取值
```

所以当前 M5 只是“准备动作”，没有形成真正消费闭环。

本轮只补齐这条调用链，不做其他优化。

---

## 一、本轮目标

必须完成下面 5 件事：

```text
1. daily_report.generate_report_mode 增加 report_context=None 参数
2. main() 调用 generate_report_mode(...) 时传入 report_context=report_context
3. render_daily_report 增加 report_context=None 参数
4. render_daily_report 调用 render_beginner_report / render_pro_report 时继续传 report_context
5. render_beginner_report / render_pro_report 增加 report_context=None 参数，并在市场/情绪摘要处优先使用 context
```

完成后必须能证明：

```text
report_context 已经从 daily_report.py 传入 report_renderer.py
```

---

## 二、允许修改文件

只允许修改：

```text
analysis/daily_report.py
analysis/report_renderer.py
```

可选修改：

```text
analysis/report_regression_check.py
```

仅用于增加检查，确认 renderer 已出现正确口径。

---

## 三、禁止修改文件

禁止修改：

```text
analysis/selector.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_trend_tracker.py
analysis/board_mapping_quality.py
entrypoint.sh
```

---

## 四、daily_report.py 必须改动点

### 1. 修改 generate_report_mode 函数签名

找到：

```python
def generate_report_mode(..., trade_plan=None, board_trend_summary=None):
```

改为类似：

```python
def generate_report_mode(..., trade_plan=None, board_trend_summary=None, report_context=None):
```

### 2. render_daily_report 调用必须传入 report_context

找到：

```python
report = render_daily_report(
    ...
    board_trend_summary=board_trend_summary,
)
```

必须改为：

```python
report = render_daily_report(
    ...
    board_trend_summary=board_trend_summary,
    report_context=report_context,
)
```

### 3. main() 调用 generate_report_mode 必须传入 report_context

找到：

```python
generate_report_mode(
    ...
    board_trend_summary=board_trend_summary,
)
```

必须改为：

```python
generate_report_mode(
    ...
    board_trend_summary=board_trend_summary,
    report_context=report_context,
)
```

---

## 五、report_renderer.py 必须改动点

### 1. render_daily_report 增加 report_context 参数

找到：

```python
def render_daily_report(..., board_trend_summary=None):
```

改为：

```python
def render_daily_report(..., board_trend_summary=None, report_context=None):
```

### 2. render_daily_report 分发时继续传

专业版：

```python
return render_pro_report(
    ...
    board_trend_summary=board_trend_summary,
    report_context=report_context,
)
```

小白版：

```python
return render_beginner_report(
    ...
    board_trend_summary=board_trend_summary,
    report_context=report_context,
)
```

### 3. render_beginner_report 增加 report_context 参数

找到：

```python
def render_beginner_report(..., board_trend_summary=None):
```

改为：

```python
def render_beginner_report(..., board_trend_summary=None, report_context=None):
```

### 4. render_pro_report 增加 report_context 参数

找到：

```python
def render_pro_report(..., board_trend_summary=None):
```

改为：

```python
def render_pro_report(..., board_trend_summary=None, report_context=None):
```

---

## 六、必须实际消费 context

在 `render_beginner_report` 和 `render_pro_report` 内部，靠近函数开头处增加：

```python
market_context = _get_context_section(report_context, "market")
sentiment_context = _get_context_section(report_context, "sentiment")

market_score = market_context.get("score", market.get("score"))
market_status = market_context.get("status", market.get("status"))
market_summary = market_context.get("summary", market.get("summary", ""))

sentiment_score = sentiment_context.get("score", sentiment.get("score"))
sentiment_stage = sentiment_context.get("stage", sentiment.get("stage"))
```

然后至少在市场/情绪摘要显示处使用这些变量。

要求：

```text
市场综合评分 使用 market_score
市场综合状态 使用 market_status
市场简评/一句话总结 使用 market_summary
短线情绪周期评分 使用 sentiment_score
短线情绪周期阶段 使用 sentiment_stage
```

不要只定义变量不用。

---

## 七、不要改这些内容

本轮不要改：

```text
观察池股票列表
可观察池 / 谨慎观察池 / 高风险复盘池
板块趋势表
trade_plan
email_sender
pipeline_check
selector
AI 调用逻辑
报告章节结构
```

输出理论上应该基本不变，因为 context 来自同一批 market_result / sentiment_result。

---

## 八、验收命令

修改后执行：

```bash
python -m compileall analysis
python -m analysis.daily_report --mode both --date 20260528
python -m analysis.report_regression_check --date 20260528

grep -R "report_context" -n analysis/daily_report.py analysis/report_renderer.py

git diff --stat
git status --short --untracked-files=all
```

`grep` 结果必须能看到：

```text
daily_report.py 中 generate_report_mode 传 report_context
report_renderer.py 中 render_daily_report 接收 report_context
report_renderer.py 中 render_beginner_report 接收 report_context
report_renderer.py 中 render_pro_report 接收 report_context
```

---

## 九、预期 diff

理想 diff 只包含：

```text
analysis/daily_report.py
analysis/report_renderer.py
```

可选：

```text
analysis/report_regression_check.py
```

不应该出现：

```text
analysis/selector.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/context/report_context.py
entrypoint.sh
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十、提交要求

如果验收通过，提交：

```bash
git add analysis/daily_report.py analysis/report_renderer.py analysis/report_regression_check.py
git commit -m "fix: pass report context into report renderer"
```

不要提交：

```text
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
reports/
__pycache__/
.claude/
```

不要 push。

提交后返回：

```bash
git log -3 --oneline
git status --short
git diff HEAD~1 --stat
python -m analysis.report_regression_check --date 20260528
grep -R "report_context" -n analysis/daily_report.py analysis/report_renderer.py
```

---

## 十一、本轮通过标准

本轮通过标准：

```text
1. report_context 从 daily_report.py 传到 render_daily_report
2. render_daily_report 传到 render_beginner_report / render_pro_report
3. beginner/pro 内部实际读取 market_context / sentiment_context
4. 市场/情绪摘要实际使用 context 优先值
5. 不改 selector / email / pipeline
6. 回归检查 0 errors / 0 warnings
```

# V3-Stabilization M6：日期一致性与 pipeline_check 结构收敛包

## 当前项目背景

项目：`testStock`

当前阶段：

> V3-Stabilization：日报系统口径统一与稳定性收敛

当前已完成：

| 阶段      | 内容                                        | 状态   |
| ------- | ----------------------------------------- | ---- |
| 第 0 轮   | 结构占位                                      | done |
| 第 1 轮   | report_context 最小接入                       | done |
| 第 2 轮   | pipeline_check + email 联动                 | done |
| 第 3 轮   | selector 安全边界                             | done |
| 第 4 轮   | 代码框架梳理                                    | done |
| 第 5 轮   | 数据真实性与产物链一致性 review                       | done |
| 第 6 轮   | report_context 最小填充                       | done |
| 第 7 轮   | report_context 填充结果 review                | done |
| 第 8/9 轮 | report_regression_check 第一版 + 真实 error 修复 | done |
| M2      | 报告口径与展示一致性收敛                              | done |
| M3      | daily_summary 暴露 report_context           | done |
| M4      | email_sender 消费 report_context            | done |
| M5      | report_renderer 局部消费 report_context       | done |

当前 `report_context` 已形成闭环：

```text
daily_report 构建 report_context
  -> daily_summary 暴露 report_context
  -> email_sender 消费 report_context
  -> report_renderer 局部消费 report_context
```

现在进入：

> M6：日期一致性与 pipeline_check 结构收敛包

---

## 一、本轮目标

本轮只处理两个遗留问题：

### 问题 1：pipeline_check JSON 结构不够稳定

当前 `pipeline_check.py` 中：

```python
critical_missing = False
```

最终 JSON 中 `critical_missing` 是 bool。

但后续 email / regression_check 更适合读取稳定列表结构：

```json
{
  "critical_missing": [],
  "non_critical_missing": [],
  "has_critical_missing": false,
  "status": "ok"
}
```

本轮要把 `pipeline_check_YYYYMMDD.json` 结构收敛成更清晰的结构。

---

### 问题 2：selector 板块联动 DB 查询使用 MAX(trade_date)

当前 `selector.py` 的 `_select_board_linkage_db()` 查询强势板块时使用：

```sql
WHERE trade_date = (SELECT MAX(trade_date) FROM board_amount_ratio)
```

这会导致在指定 `--date` 或历史回测时，可能读取数据库最新日期，而不是当前日报日期。

本轮目标：

```text
让板块联动尽量使用当前 trade_date 对应的 board_amount_ratio。
```

---

## 二、本轮允许修改的文件

允许修改：

```text
analysis/pipeline_check.py
analysis/email_sender.py
analysis/report_regression_check.py
analysis/selector.py
analysis/daily_report.py
```

说明：

* `pipeline_check.py`：整理输出结构；
* `email_sender.py`：适配新的 `critical_missing / non_critical_missing` 列表结构；
* `report_regression_check.py`：适配新的 pipeline_check 结构，并增加 board linkage 日期风险检查；
* `selector.py`：让板块联动函数接收 `trade_date`；
* `daily_report.py`：把 `trade_date` 传入 selector。

---

## 三、本轮禁止修改的文件

禁止修改：

```text
analysis/report_renderer.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_trend_tracker.py
analysis/board_mapping_quality.py
entrypoint.sh
```

除非发现明显纯文案错误，否则不要碰。

---

## 四、本轮禁止事项

禁止做：

```text
新增策略
删除策略
修改策略阈值
修改观察池分层
修改高风险判定
修改 report_renderer
修改 report_context 结构
修改邮件附件逻辑
修改 entrypoint 主链路
新增 report_context 独立产物
提交 reports 产物
提交 __pycache__
提交 .claude 本地配置
提交 PRDs/V3-Stabilization.md
提交 PRDs/V3-StabilizationM2.md
```

---

# Part A：pipeline_check 结构收敛

## 五、pipeline_check.py 修改要求

当前保留：

```text
EXPECTED_FILES
CRITICAL
```

但将运行结果改成：

```json
{
  "trade_date": "20260528",
  "status": "ok",
  "ok_files": [],
  "missing_files": [],
  "critical_missing": [],
  "non_critical_missing": [],
  "has_critical_missing": false,
  "warnings": [],
  "generated_at": "..."
}
```

### status 规则

```text
critical_missing 非空：status = "critical"
critical_missing 为空但 non_critical_missing 非空：status = "warning"
两者都为空：status = "ok"
```

### 字段要求

* `critical_missing` 必须是列表；
* `non_critical_missing` 必须是列表；
* `has_critical_missing` 必须是 bool；
* `missing_files` 继续保留，用于兼容旧逻辑；
* `ok_files` 继续保留；
* `warnings` 继续保留。

---

## 六、email_sender.py 适配要求

当前 email_sender 会读取：

```text
pipeline_check_YYYYMMDD.json
```

本轮要兼容新旧两种结构。

### 新结构优先

如果存在：

```python
pc.get("critical_missing")
pc.get("non_critical_missing")
```

则直接使用这两个列表。

### 旧结构兼容

如果 `critical_missing` 是 bool，或者没有 `non_critical_missing`，则继续用 `missing_files` 兼容生成。

### 邮件正文展示

保持：

```text
流程检查：
- 关键缺失：无 / xxx
- 非关键缺失：无 / xxx
```

不改变附件逻辑，不改变发送逻辑。

---

## 七、report_regression_check.py 适配要求

当前 `_check_pipeline_critical()` 需要适配新结构：

```python
critical_missing = data.get("critical_missing", [])
```

如果是列表：

```text
非空 -> failed
空 -> ok
```

如果是 bool：

```text
True -> failed
False -> ok
```

这样兼容旧 JSON。

---

# Part B：selector 板块联动日期一致性

## 八、selector.py 修改要求

当前：

```python
def run_all_selectors(stock_df, industry_df=None, concept_df=None, market_score=None):
    ...
```

如果当前签名不同，请按实际代码处理。

目标是增加可选参数：

```python
trade_date=None
```

示例：

```python
def run_all_selectors(stock_df, industry_df=None, concept_df=None, market_score=None, trade_date=None):
    ...
```

然后传给板块联动：

```python
select_board_linkage(..., trade_date=trade_date)
```

相关函数也增加可选参数：

```python
def select_board_linkage(..., trade_date=None):
def _select_board_linkage_db(..., trade_date=None):
```

---

## 九、board_amount_ratio 查询要求

当前 SQL：

```sql
WHERE trade_date = (SELECT MAX(trade_date) FROM board_amount_ratio)
```

改成：

### 如果 trade_date 存在

优先使用：

```sql
WHERE trade_date = %s
```

参数传入当前 `trade_date`。

### 如果 trade_date 不存在

可以保留旧逻辑作为兼容：

```sql
WHERE trade_date = (SELECT MAX(trade_date) FROM board_amount_ratio)
```

### 如果指定日期没有 board_amount_ratio

不要 fallback 到旧日期悄悄通过。

建议行为：

```text
指定 trade_date 但无当天 board_amount_ratio：
_select_board_linkage_db 返回 None
然后走 fallback 逻辑
```

但 fallback 逻辑必须明确仍是“降级版板块联动”，不应伪装成真实板块资金联动。

---

## 十、daily_report.py 修改要求

当前调用：

```python
selector_result = run_all_selectors(
    stock_df=stock_df,
    industry_df=industry_df,
    concept_df=concept_df,
    market_score=market_score,
)
```

改为：

```python
selector_result = run_all_selectors(
    stock_df=stock_df,
    industry_df=industry_df,
    concept_df=concept_df,
    market_score=market_score,
    trade_date=trade_date,
)
```

不要改其他逻辑。

---

## 十一、report_regression_check 可选增强

可以增加一个简单检查：

```text
检查 selector.py 中是否仍存在：
WHERE trade_date = (SELECT MAX(trade_date) FROM board_amount_ratio)
```

但这类检查更偏静态源码检查，第一版可以不加。
如果要加，作为 warning，不作为 error。

更建议本轮只适配 pipeline JSON。

---

## 十二、运行检查

完成后执行：

```bash
python -m compileall analysis

python -m analysis.pipeline_check --date 20260528
cat reports/daily/pipeline_check_20260528.json

python -m analysis.daily_report --mode both --date 20260528
python -m analysis.report_regression_check --date 20260528
cat reports/daily/report_regression_check_20260528.json

git diff --stat
git status --short --untracked-files=all
```

注意：

```text
reports/daily/*.json
reports/daily/*.md
reports/daily/*.xlsx
```

都是运行产物，不要提交。

---

## 十三、预期 diff

理想 diff：

```text
analysis/pipeline_check.py
analysis/email_sender.py
analysis/report_regression_check.py
analysis/selector.py
analysis/daily_report.py
```

不应该出现：

```text
analysis/report_renderer.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_trend_tracker.py
analysis/board_mapping_quality.py
entrypoint.sh
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十四、提交要求

如果验收通过，提交：

```bash
git add analysis/pipeline_check.py \
        analysis/email_sender.py \
        analysis/report_regression_check.py \
        analysis/selector.py \
        analysis/daily_report.py

git commit -m "fix: align pipeline structure and selector trade date"
```

未修改文件会自动忽略。

不要提交：

```text
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
reports/
__pycache__/
.claude/
```

不要 push。

提交后返回：

```bash
git log -3 --oneline
git status --short
git diff HEAD~1 --stat
python -m analysis.report_regression_check --date 20260528
cat reports/daily/pipeline_check_20260528.json
```

---

## 十五、本轮通过标准

本轮通过标准：

1. `pipeline_check_YYYYMMDD.json` 中：

   * `critical_missing` 是列表；
   * `non_critical_missing` 是列表；
   * `has_critical_missing` 是 bool；
   * `status` 正确；
2. `email_sender.py` 兼容新旧 pipeline JSON；
3. `report_regression_check.py` 兼容新旧 pipeline JSON；
4. `run_all_selectors` 接收 `trade_date`；
5. 板块联动 DB 查询优先使用当前 `trade_date`；
6. 指定日期无 board_amount_ratio 时不悄悄 fallback 到旧日期；
7. 不改策略阈值；
8. 不改 renderer；
9. 不改 entrypoint；
10. 回归检查为 ok 或只有合理 warning；
11. 无 reports / pycache / local config 进入 Git。


# M6 补充验收：防止形式修改

本轮重点不是“加参数”或“加字段”，而是必须完成实质收敛。

## 1. selector 日期一致性验收

修改后必须执行：

```bash
grep -R "MAX(trade_date).*board_amount_ratio\|SELECT MAX(trade_date)" -n analysis/selector.py
```

验收标准：

* 如果 `trade_date` 明确传入，不能再使用 `MAX(trade_date)`；
* `MAX(trade_date)` 只允许存在于 `trade_date is None` 的兼容分支；
* `_select_board_linkage_db(..., trade_date=trade_date)` 必须实际使用 `%s` 参数查询当天数据。

必须确认 SQL 逻辑类似：

```python
if trade_date:
    sql_hot = """
    SELECT board_type, board_name, pct_chg, amount_ratio
    FROM board_amount_ratio
    WHERE trade_date = %s
    """
    hot_df = pd.read_sql(sql_hot, conn, params=[trade_date])
else:
    sql_hot = """
    SELECT board_type, board_name, pct_chg, amount_ratio
    FROM board_amount_ratio
    WHERE trade_date = (SELECT MAX(trade_date) FROM board_amount_ratio)
    """
    hot_df = pd.read_sql(sql_hot, conn)
```

如果指定日期无数据，`hot_df.empty` 时应返回 `None`，让后续 fallback 明确降级，不要偷偷用旧日期替代。

## 2. pipeline_check JSON 结构验收

修改后必须执行：

```bash
python -m analysis.pipeline_check --date 20260528
cat reports/daily/pipeline_check_20260528.json
```

验收标准：

```json
{
  "critical_missing": [],
  "non_critical_missing": [],
  "has_critical_missing": false
}
```

其中类型必须是：

```text
critical_missing: list
non_critical_missing: list
has_critical_missing: bool
```

不接受：

```json
"critical_missing": false
```

## 3. email_sender 兼容验收

`email_sender.py` 必须兼容两种结构：

新结构：

```json
{
  "critical_missing": [],
  "non_critical_missing": []
}
```

旧结构：

```json
{
  "critical_missing": false,
  "missing_files": []
}
```

邮件正文仍然输出：

```text
流程检查：
- 关键缺失：无 / xxx
- 非关键缺失：无 / xxx
```

不要修改附件逻辑。

## 4. report_regression_check 验收

执行：

```bash
python -m analysis.report_regression_check --date 20260528
```

结果必须是：

```text
0 errors
```

允许合理 warning，但如果 warning 来自本轮新结构误判，需要修复。

## 5. 预期 diff

理想 diff 只包含：

```text
analysis/pipeline_check.py
analysis/email_sender.py
analysis/report_regression_check.py
analysis/selector.py
analysis/daily_report.py
```

不应出现：

```text
analysis/report_renderer.py
analysis/context/report_context.py
entrypoint.sh
reports/
__pycache__/
.claude/
PRDs/
```

# V3-Stabilization M7：部署前收口与总验收准备

## 当前项目背景

项目：`testStock`

当前阶段：

> V3-Stabilization：日报系统口径统一与稳定性收敛

当前已完成：

| 阶段      | 内容                                       | 状态   |
| ------- | ---------------------------------------- | ---- |
| V3.3    | 基本可用日报版本                                 | done |
| 第 0-9 轮 | 结构、pipeline、selector、regression_check 收敛 | done |
| M2      | 报告口径与展示一致性收敛                             | done |
| M3      | daily_summary 暴露 report_context          | done |
| M4      | email_sender 消费 report_context           | done |
| M5      | report_renderer 局部消费 report_context      | done |
| M6      | 日期一致性与 pipeline_check 结构收敛               | done |
| 非交易日守卫  | entrypoint 非交易日跳过全部流程                    | done |

当前系统已经基本进入部署前收口阶段。

本轮目标：

> 不再新增功能，不再改业务逻辑，只做部署前收口与总验收准备。

---

## 一、本轮目标

本轮只做三件事：

1. 修复 `entrypoint.sh` 覆盖外部 `TRADE_DATE` 的问题；
2. 建立一份部署前总验收命令清单；
3. 跑一轮基础验收，确认当前 `dev` 可准备合 main。

---

## 二、问题说明

当前 `entrypoint.sh` 里如果是：

```bash
TRADE_DATE=$(date +%Y%m%d)
```

会覆盖手动传入的日期。

例如：

```bash
TRADE_DATE=20260528 bash entrypoint.sh
```

会被脚本内部重新覆盖成当天日期。

这会影响历史日期验收和指定日期回归。

本轮需要改为：

```bash
TRADE_DATE=${TRADE_DATE:-$(date +%Y%m%d)}
```

这样：

* 如果外部传了 `TRADE_DATE`，优先使用外部日期；
* 如果外部没传，才使用系统当天日期。

---

## 三、本轮允许修改的文件

本轮只允许修改：

```text
entrypoint.sh
```

可选新增文档：

```text
docs/V3-STABILIZATION-ACCEPTANCE.md
```

如果新增文档，内容只写部署前验收命令清单，不写长篇开发日志。

---

## 四、本轮禁止修改的文件

禁止修改：

```text
analysis/daily_report.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/selector.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_trend_tracker.py
analysis/board_mapping_quality.py
data/config.py
```

---

## 五、本轮禁止事项

禁止做：

```text
新增策略
修改策略阈值
修改观察池逻辑
修改 report_context 结构
修改 report_renderer
修改 email_sender
修改 pipeline_check
修改 regression_check
修改 selector
修改数据源
修改数据库结构
接入新推送渠道
提交 reports 产物
提交 __pycache__
提交 .claude 本地配置
提交本地 PRD 迭代日志
```

本轮是“部署前收口”，不是功能开发。

---

## 六、entrypoint.sh 修改要求

找到：

```bash
TRADE_DATE=$(date +%Y%m%d)
```

改成：

```bash
TRADE_DATE=${TRADE_DATE:-$(date +%Y%m%d)}
```

保留非交易日守卫：

```bash
python -c "from analysis.data_fetcher import is_trade_day; import sys; sys.exit(0 if is_trade_day('$TRADE_DATE') else 1)" || {
    echo "$TRADE_DATE 非交易日，跳过全部任务"
    exit 0
}
```

不要改变 pipeline 顺序。

当前顺序应保持：

```text
init_db
board_history
board_mapping_quality
board_trend_tracker
daily_report
pipeline_check
signal_tracker
backtest_report
email_sender
```

---

## 七、可选文档：部署前总验收清单

如果新增：

```text
docs/V3-STABILIZATION-ACCEPTANCE.md
```

建议内容如下：

````markdown
# V3-Stabilization 部署前总验收清单

## 1. 拉取 dev

```bash
git checkout dev
git pull origin dev
git status --short
git log -8 --oneline
````

## 2. 编译检查

```bash
python -m compileall analysis
```

## 3. 指定日期全流程验收

```bash
TRADE_DATE=20260528 bash entrypoint.sh
```

## 4. pipeline 检查

```bash
python -m analysis.pipeline_check --date 20260528
cat reports/daily/pipeline_check_20260528.json
```

验收标准：

```text
status = ok 或 warning
critical_missing = []
has_critical_missing = false
```

## 5. regression 检查

```bash
python -m analysis.report_regression_check --date 20260528
cat reports/daily/report_regression_check_20260528.json
```

验收标准：

```text
errors = []
最好 warnings = []
```

## 6. 关键产物检查

```bash
ls -lh reports/daily/*20260528*
```

至少包含：

```text
daily_report_20260528.md
daily_report_20260528_pro.md
daily_summary_20260528.json
trade_plan_20260528.md
trade_plan_20260528.json
board_trend_summary_20260528.json
board_mapping_quality_20260528.json
pipeline_check_20260528.json
report_regression_check_20260528.json
```

## 7. Git 污染检查

```bash
git status --short --untracked-files=all
```

不得提交：

```text
reports/
__pycache__/
.claude/
.env
本地 PRD 迭代日志
```

## 8. 合 main 前建议

```bash
git checkout main
git pull origin main
git merge dev
python -m compileall analysis
git push origin main
```

````

注意：文档内容不要太长，保持验收清单即可。

---

## 八、运行检查

完成后执行：

```bash
python -m compileall analysis
````

然后检查 entrypoint 日期是否不会覆盖：

```bash
grep -n "TRADE_DATE=" entrypoint.sh
```

预期看到：

```bash
TRADE_DATE=${TRADE_DATE:-$(date +%Y%m%d)}
```

如果本地数据允许，执行：

```bash
TRADE_DATE=20260528 bash entrypoint.sh
python -m analysis.report_regression_check --date 20260528
cat reports/daily/report_regression_check_20260528.json
```

如果不方便跑全流程，至少执行：

```bash
python -m analysis.pipeline_check --date 20260528
python -m analysis.report_regression_check --date 20260528
```

---

## 九、预期 diff

理想 diff：

```text
entrypoint.sh
```

可选：

```text
docs/V3-STABILIZATION-ACCEPTANCE.md
```

不应该出现：

```text
analysis/
data/
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十、提交要求

如果只改 `entrypoint.sh`：

```bash
git add entrypoint.sh
git commit -m "fix: preserve external trade date in entrypoint"
```

如果新增验收文档：

```bash
git add entrypoint.sh docs/V3-STABILIZATION-ACCEPTANCE.md
git commit -m "chore: add V3 stabilization acceptance checklist"
```

不要提交：

```text
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
reports/
__pycache__/
.claude/
.env
```

提交后返回：

```bash
git log -3 --oneline
git status --short
git diff HEAD~1 --stat
grep -n "TRADE_DATE=" entrypoint.sh
python -m analysis.report_regression_check --date 20260528
```

---

## 十一、本轮通过标准

本轮通过标准：

1. `entrypoint.sh` 不再覆盖外部 `TRADE_DATE`；
2. 非交易日守卫保留；
3. pipeline 顺序不变；
4. `compileall` 通过；
5. `report_regression_check` 为 ok 或无 errors；
6. 不改业务代码；
7. 不提交 reports / pycache / local config；
8. 如果新增文档，文档只包含部署前验收清单。
