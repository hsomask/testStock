# V3-Stabilization：日报系统口径统一与稳定性收敛

## 1. 当前阶段目标

V3-Stabilization 的目标是对 A 股日报系统进行口径统一和稳定性收敛。

当前系统已经从 V3.3 的问题修复阶段进入稳定化阶段。后续重点不是继续堆新策略，而是让日报系统在字段命名、报告上下文、流程检查、邮件提示和回归检查方面更加稳定。

## 2. 当前阶段不做的事情

本阶段暂时不做：

- 不新增选股策略；
- 不重写主链路；
- 不移动主链路文件；
- 不改变日报输出逻辑；
- 不改变观察池生成逻辑；
- 不把系统定位为自动交易决策系统。

## 3. 后续收敛顺序

建议按以下顺序推进：

1. report_context：建立统一日报上下文；
2. pipeline_check + email：统一流程检查和邮件缺失提示；
3. selector 安全边界：只做风险收敛，不新增策略；
4. report_regression_check：建立固定回归检查脚本；
5. 报告可读性：统一小白版、专业版和邮件正文表达。

## 4. 系统定位

当前系统定位为：

自动化复盘 + 风险提示 + 观察池生成

当前系统不能定位为：

自动交易决策系统


# V3-Stabilization 第 1 轮：report_context 最小接入

## 当前项目背景

我们继续 `testStock` 项目。

当前阶段是：

> V3-Stabilization：日报系统口径统一与稳定性收敛

上一轮已经完成：

* 清理 `__pycache__` 版本污染；
* 更新 `.gitignore`；
* 新增 `PRDs/V3-Stabilization.md`；
* 新增结构占位目录；
* 提交记录为：`763778 chore: add V3 stabilization structure placeholders`；
* 当前 `git status --short` 为空。

本轮只做 **report_context 最小接入方案**。

---

## 一、本轮目标

本轮目标不是重构日报，也不是改变输出，而是建立 `report_context` 的最小闭环。

具体目标：

1. 保持现有日报输出完全不变；
2. 不改 selector；
3. 不改 pipeline；
4. 不改 email_sender；
5. 不改 entrypoint.sh；
6. 只在 `daily_report.py` 中旁路生成 `report_context`；
7. 先让 `report_context` 能被构建、能打印/保存调试信息，但不作为正式渲染来源。

---

## 二、禁止事项

本轮禁止做以下事情：

* 不新增任何选股策略；
* 不修改观察池筛选逻辑；
* 不修改 `analysis/selector.py`；
* 不修改 `analysis/email_sender.py`；
* 不修改 `analysis/pipeline_check.py`；
* 不修改 `entrypoint.sh`；
* 不重写 `analysis/daily_report.py`；
* 不拆分 `analysis/report_renderer.py`；
* 不移动任何主链路文件；
* 不改变现有日报 Markdown 输出内容；
* 不改变现有 JSON 输出结构；
* 不引入旧日期 fallback；
* 不修改历史 PRD 文件。

---

## 三、允许修改的文件

本轮只允许修改：

```text
analysis/context/report_context.py
analysis/context/field_dictionary.py
analysis/daily_report.py
```

如确实需要，也可以新增：

```text
tests/test_report_context.py
```

但不要为了测试而大改业务代码。

---

## 四、report_context 最小结构要求

请在 `analysis/context/report_context.py` 中保留并扩展当前函数。

目标结构为：

```python
report_context = {
    "trade_date": trade_date,
    "market": {},
    "sentiment": {},
    "boards": {},
    "themes": {},
    "watchlists": {},
    "trade_plan": {},
    "quality": {},
    "pipeline": {},
}
```

本轮只要求做到：

1. `build_empty_report_context(trade_date)` 保持可用；
2. 新增 `build_report_context(...)` 函数；
3. `build_report_context(...)` 可以先接收已有数据对象作为可选参数；
4. 如果暂时没有数据，就填空 dict；
5. 不要强行改造 daily_report 的内部变量结构。

建议函数形式：

```python
from __future__ import annotations

from typing import Any


def build_empty_report_context(trade_date: str) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "market": {},
        "sentiment": {},
        "boards": {},
        "themes": {},
        "watchlists": {},
        "trade_plan": {},
        "quality": {},
        "pipeline": {},
    }


def build_report_context(
    trade_date: str,
    market: dict[str, Any] | None = None,
    sentiment: dict[str, Any] | None = None,
    boards: dict[str, Any] | None = None,
    themes: dict[str, Any] | None = None,
    watchlists: dict[str, Any] | None = None,
    trade_plan: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    pipeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = build_empty_report_context(trade_date)
    context["market"] = market or {}
    context["sentiment"] = sentiment or {}
    context["boards"] = boards or {}
    context["themes"] = themes or {}
    context["watchlists"] = watchlists or {}
    context["trade_plan"] = trade_plan or {}
    context["quality"] = quality or {}
    context["pipeline"] = pipeline or {}
    return context
```

---

## 五、daily_report.py 接入要求

在 `analysis/daily_report.py` 中，只做最小接入：

```python
from analysis.context.report_context import build_report_context
```

然后在已有 `trade_date` 已经确定之后，旁路生成：

```python
report_context = build_report_context(trade_date=trade_date)
```

如果当前代码里已经有现成的 market、sentiment、boards、themes、watchlists 等对象，可以逐步传入，但不要为了传入它们而重写业务逻辑。

本轮允许先只生成空结构：

```python
report_context = build_report_context(trade_date=trade_date)
```

然后可选保存一个调试文件：

```text
reports/daily/report_context_YYYYMMDD.json
```

但注意：

1. 如果保存调试文件，必须使用当前 `--date` 对应日期；
2. 文件名必须带日期；
3. 不允许 fallback 到旧日期；
4. 不允许影响现有日报输出。

如果担心影响主流程，可以先不保存，只构建对象。

---

## 六、字段口径要求

`analysis/context/field_dictionary.py` 中必须保持以下字段：

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

本轮不要在报告里大规模替换文案，只确认字段字典存在并可 import。

---

## 七、验收命令

修改完成后执行：

```bash
python -m compileall analysis
git diff --stat
git status --short
```

如果本地有可用数据，再执行：

```bash
TRADE_DATE=20260528 bash entrypoint.sh
```

然后检查：

```bash
ls -lh reports/daily/*20260528*
```

---

## 八、预期 diff

理想情况下，本轮 diff 只包括：

```text
analysis/context/report_context.py
analysis/context/field_dictionary.py
analysis/daily_report.py
```

可选包括：

```text
tests/test_report_context.py
```

不应该出现：

```text
analysis/selector.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_renderer.py
entrypoint.sh
analysis/__pycache__/
data/__pycache__/
reports/backtest/
旧 PRD 文件
```

---

## 九、提交要求

如果验收通过，提交：

```bash
git add analysis/context/report_context.py analysis/context/field_dictionary.py analysis/daily_report.py
git add tests/test_report_context.py 2>/dev/null || true
git commit -m "chore: add minimal report context builder"
```

不要 push。

提交后发回：

```bash
git log -1 --oneline
git status --short
git diff HEAD~1 --stat
```

---

## 十、本轮判断标准

本轮通过的标准是：

1. 代码能编译；
2. 日报原有输出不变；
3. `report_context` 能被构建；
4. 没有改动 selector、email、pipeline；
5. 没有新增策略；
6. 没有旧日期 fallback；
7. 没有 pycache 或报告产物进入 Git。

# V3-Stabilization 第 1 轮 Review：检查 report_context 最小接入是否合格

## 当前项目背景

项目：`testStock`

当前阶段：

> V3-Stabilization：日报系统口径统一与稳定性收敛

当前 `dev` 已经 push 到远端，最新两次提交为：

```bash
6ef7c47 docs: update V3 stabilization plan
c46de81 chore: add minimal report context builder
```

本轮任务是 **review**，不是继续开发。

---

## 一、本轮 Review 目标

检查 `report_context` 最小接入是否合格。

重点确认：

1. `report_context` 是否只是旁路接入；
2. 是否没有改变现有日报输出逻辑；
3. 是否没有修改 selector / email / pipeline；
4. 是否没有新增策略；
5. 是否没有引入旧日期 fallback；
6. 是否没有把报告产物、pycache、本地配置提交进仓库；
7. 是否符合 V3-Stabilization 的收敛方向。

---

## 二、本轮禁止事项

本轮禁止修改任何文件。

不要执行：

```bash
git add
git commit
git push
```

不要修改：

```text
analysis/daily_report.py
analysis/context/report_context.py
analysis/context/field_dictionary.py
analysis/selector.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_renderer.py
entrypoint.sh
PRDs/V3-Stabilization.md
```

本轮只做检查、总结和给出建议。

---

## 三、先确认工作区和提交状态

请执行：

```bash
git checkout dev
git pull origin dev
git status --short
git log -3 --oneline
```

预期：

```text
git status --short 为空
```

最新提交应该包含：

```text
6ef7c47 docs: update V3 stabilization plan
c46de81 chore: add minimal report context builder
```

如果工作区不干净，先停止 review，说明有哪些未提交文件。

---

## 四、检查本轮提交范围

执行：

```bash
git show --stat c46de81
git show --stat 6ef7c47
git diff c46de81~1..6ef7c47 --stat
```

重点判断是否只涉及以下文件：

```text
analysis/context/report_context.py
analysis/context/field_dictionary.py
analysis/daily_report.py
PRDs/V3-Stabilization.md
```

允许存在：

```text
analysis/context/__init__.py
analysis/common/__init__.py
analysis/renderers/__init__.py
config/.gitkeep
tests/.gitkeep
PRDs/archive/.gitkeep
.gitignore
```

不应出现：

```text
analysis/selector.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_renderer.py
entrypoint.sh
analysis/__pycache__/
data/__pycache__/
reports/
.claude/settings.local.json
旧 PRD 文件大规模修改
```

---

## 五、检查 report_context.py

请查看：

```bash
sed -n '1,220p' analysis/context/report_context.py
```

检查点：

1. 是否存在 `build_empty_report_context(trade_date)`；
2. 是否存在 `build_report_context(...)`；
3. 返回结构是否包含：

```python
{
    "trade_date": trade_date,
    "market": {},
    "sentiment": {},
    "boards": {},
    "themes": {},
    "watchlists": {},
    "trade_plan": {},
    "quality": {},
    "pipeline": {},
}
```

4. 是否只是构建 dict；
5. 是否没有读取旧日期文件；
6. 是否没有扫描 `reports/daily` 最新文件；
7. 是否没有调用 selector；
8. 是否没有调用 email_sender；
9. 是否没有改变业务逻辑；
10. 是否没有引入外部依赖。

---

## 六、检查 field_dictionary.py

请查看：

```bash
sed -n '1,200p' analysis/context/field_dictionary.py
```

必须确认字段字典至少包含：

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

检查点：

1. `market_score` 是否明确叫“市场综合评分”；
2. 是否没有把 `market_score` 叫成“市场情绪评分”；
3. 是否没有把 `market_score` 混叫为“市场宽度评分”；
4. 是否没有删除原有字段；
5. 是否没有加入与本轮无关的新策略字段。

---

## 七、检查 daily_report.py 的接入是否最小化

请执行：

```bash
git diff c46de81~1..c46de81 -- analysis/daily_report.py
```

重点检查：

1. 是否只是 import 了 `build_report_context`；
2. 是否只是在 `trade_date` 确定后构建了 `report_context`；
3. 是否没有改变原有报告生成顺序；
4. 是否没有改变小白版、专业版 markdown 渲染逻辑；
5. 是否没有改变 `daily_summary_YYYYMMDD.json` 结构；
6. 是否没有改变 trade_plan 生成逻辑；
7. 是否没有改变文件读取路径；
8. 是否没有新增 latest/fallback/glob 旧日期逻辑；
9. 是否没有新增策略筛选逻辑；
10. 是否没有把 `report_context` 强行作为正式渲染来源。

本轮合格标准是：

```text
report_context 可以被构建，但不影响现有输出。
```

---

## 八、检查是否有禁止改动

执行：

```bash
git diff c46de81~1..6ef7c47 --name-only
```

如果出现以下文件，标记为风险：

```text
analysis/selector.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/report_renderer.py
entrypoint.sh
analysis/board_history.py
analysis/board_mapping_quality.py
analysis/board_trend_tracker.py
analysis/theme_detector.py
analysis/market.py
```

除非只是上一轮已确认的结构占位，否则本轮不应该改这些。

---

## 九、运行基础检查

执行：

```bash
python -m compileall analysis
```

如果本地有 20260528 数据，再执行：

```bash
TRADE_DATE=20260528 bash entrypoint.sh
```

如果没有完整数据，至少执行：

```bash
python -m analysis.daily_report --mode both --date 20260528
```

如果缺数据导致失败，请说明失败原因是数据缺失还是代码错误。

---

## 十、检查产物和缓存是否污染 Git

执行：

```bash
git status --short --untracked-files=all
```

预期为空。

如果出现以下内容，标记为不合格：

```text
analysis/__pycache__/
data/__pycache__/
reports/
.claude/
*.pyc
```

---

## 十一、Review 输出格式

请按下面格式输出 review 结果：

```markdown
# V3-Stabilization 第 1 轮 Review 结果

## 1. 总体结论

通过 / 暂缓通过 / 不通过

## 2. 提交范围检查

- c46de81:
- 6ef7c47:
- 是否出现越界文件：

## 3. report_context.py 检查

- build_empty_report_context:
- build_report_context:
- 是否读取旧日期:
- 是否影响业务逻辑:

## 4. field_dictionary.py 检查

- market_score 命名:
- sentiment_score 命名:
- watchlist_layer 命名:
- 是否存在口径混乱:

## 5. daily_report.py 接入检查

- 是否旁路接入:
- 是否改变原输出:
- 是否改变 summary/trade_plan:
- 是否引入 fallback/latest/glob:

## 6. 编译和运行检查

- compileall:
- daily_report:
- entrypoint:
- 失败原因，如有:

## 7. Git 污染检查

- pycache:
- reports:
- local config:
- git status:

## 8. 风险点

列出需要后续处理但本轮不阻断的问题。

## 9. 下一步建议

只给下一步建议，不要直接改代码。
```

---

## 十二、本轮通过标准

本轮可以判定通过的条件：

1. `git status --short` 为空；
2. `python -m compileall analysis` 通过；
3. `report_context` 只是旁路构建；
4. `daily_report.py` 没有改变现有输出逻辑；
5. 没有改 selector；
6. 没有改 email_sender；
7. 没有改 pipeline_check；
8. 没有改 report_renderer；
9. 没有引入旧日期 fallback；
10. 没有 pycache、reports、本地配置进入 Git。

如果以上任一核心项不满足，请判定为“暂缓通过”或“不通过”，不要继续开发。

# V3-Stabilization 第 2 轮：pipeline_check + email 联动方案 Review

## 当前项目背景

项目：`testStock`

当前阶段：

> V3-Stabilization：日报系统口径统一与稳定性收敛

已完成：

1. V3.3 基本收敛；
2. 第 0 轮：结构占位完成；
3. 第 1 轮：`report_context` 最小接入完成；
4. `report_context` 当前只是旁路构建，不改变日报输出；
5. 不再新增策略，当前重点是稳定性收敛。

本轮只 review 和设计：

> pipeline_check + email_sender 的缺失项联动方案

本轮不要直接改代码。

---

## 一、本轮目标

本轮目标是检查当前 `pipeline_check.py` 和 `email_sender.py` 的职责边界，并给出最小改造方案。

重点目标：

1. 明确 `pipeline_check.py` 应该检查哪些文件；
2. 明确哪些缺失属于 `critical_missing`；
3. 明确哪些缺失属于 `non_critical_missing`；
4. 明确 `pipeline_check_YYYYMMDD.json` 的稳定结构；
5. 明确 `email_sender.py` 如何读取同日期的 `pipeline_check_YYYYMMDD.json`；
6. 明确邮件正文如何提示缺失项；
7. 不改变现有邮件发送逻辑；
8. 不改变日报生成逻辑；
9. 不引入 latest/fallback 旧日期风险。

---

## 二、本轮禁止事项

本轮禁止修改任何文件。

不要执行：

```bash
git add
git commit
git push
```

不要修改：

```text
analysis/pipeline_check.py
analysis/email_sender.py
analysis/daily_report.py
analysis/report_renderer.py
analysis/selector.py
entrypoint.sh
```

本轮只做 review、分析和输出方案。

---

## 三、先确认当前状态

请执行：

```bash
git checkout dev
git pull origin dev
git status --short
git log -5 --oneline
```

要求：

```text
git status --short 为空
```

如果不为空，先停止 review，说明有哪些未提交文件。

---

## 四、查看当前 pipeline_check.py

请执行：

```bash
sed -n '1,240p' analysis/pipeline_check.py
```

重点检查：

1. 是否支持 `--date YYYYMMDD`；
2. 是否生成 `reports/daily/pipeline_check_YYYYMMDD.json`；
3. 是否区分 critical 和 non-critical；
4. 是否检查同日期文件；
5. 是否有 latest/fallback/glob 旧日期风险；
6. JSON 结构是否稳定；
7. 缺失项是否能被 email_sender 读取；
8. 是否只是检查产物，不做业务生成；
9. 是否有 hard-coded 日期；
10. 是否有异常吞掉的问题。

---

## 五、查看当前 email_sender.py

请执行：

```bash
sed -n '1,280p' analysis/email_sender.py
```

重点检查：

1. 是否支持 `--date YYYYMMDD`；
2. 是否只读取同日期日报和 trade_plan；
3. 是否还存在 latest trade_plan 覆盖当天文件的风险；
4. 是否读取 `pipeline_check_YYYYMMDD.json`；
5. 如果没读取，应该如何最小接入；
6. 邮件正文是否提示 critical 缺失；
7. 邮件正文是否提示 non-critical 缺失；
8. 附件是否只包含当天日期文件；
9. 是否会把旧日期报告打包进 zip；
10. 是否有 silent failure。

---

## 六、确认每日主链路顺序

请查看：

```bash
sed -n '1,120p' entrypoint.sh
```

确认当前顺序是否符合：

```text
1. init_db
2. board_history
3. board_mapping_quality
4. board_trend_tracker
5. daily_report
6. pipeline_check
7. signal_tracker
8. backtest_report
9. email_sender
```

检查点：

1. `pipeline_check` 是否在 `daily_report` 之后；
2. `email_sender` 是否在 `pipeline_check` 之后；
3. `daily_report`、`pipeline_check`、`email_sender` 是否都接收同一个 `TRADE_DATE`；
4. 是否仍有未传 `--date` 的关键模块。

---

## 七、建议的 pipeline_check JSON 目标结构

请基于当前实现，评估是否需要向下面结构收敛：

```json
{
  "trade_date": "20260528",
  "status": "ok",
  "critical_missing": [],
  "non_critical_missing": [],
  "checked_files": {
    "daily_report": "reports/daily/daily_report_20260528.md",
    "daily_report_pro": "reports/daily/daily_report_20260528_pro.md",
    "daily_summary": "reports/daily/daily_summary_20260528.json",
    "trade_plan_md": "reports/daily/trade_plan_20260528.md",
    "trade_plan_json": "reports/daily/trade_plan_20260528.json",
    "board_trend_summary": "reports/daily/board_trend_summary_20260528.json",
    "board_mapping_quality_json": "reports/daily/board_mapping_quality_20260528.json"
  },
  "warnings": [],
  "generated_at": "YYYY-MM-DD HH:MM:SS"
}
```

如果当前结构不同，请说明：

1. 当前结构是什么；
2. 是否足够稳定；
3. 是否需要调整；
4. 最小调整方案是什么。

---

## 八、critical / non-critical 缺失标准

请按以下标准 review：

### critical_missing

以下缺失属于关键缺失：

```text
daily_report_YYYYMMDD.md
daily_report_YYYYMMDD_pro.md
daily_summary_YYYYMMDD.json
trade_plan_YYYYMMDD.md
trade_plan_YYYYMMDD.json
board_trend_summary_YYYYMMDD.json
board_mapping_quality_YYYYMMDD.json
```

### non_critical_missing

以下缺失属于非关键缺失：

```text
board_trend_tracker_YYYYMMDD.xlsx
board_alias_report_YYYYMMDD.md
其他附加报告
```

检查当前 `pipeline_check.py` 是否已经符合这个标准。

---

## 九、email_sender 最小接入目标

请评估下一轮如果要改代码，是否可以做到：

1. `email_sender.py` 在 `--date` 模式下读取：

```text
reports/daily/pipeline_check_YYYYMMDD.json
```

2. 如果文件存在，在邮件正文中增加一段：

```text
流程检查：
- 关键缺失：无 / 列出 critical_missing
- 非关键缺失：无 / 列出 non_critical_missing
```

3. 如果 `pipeline_check_YYYYMMDD.json` 不存在，不使用旧日期文件，而是在邮件正文中提示：

```text
流程检查文件缺失：pipeline_check_YYYYMMDD.json 未生成
```

4. 不阻断邮件发送；
5. 不改变附件收集逻辑；
6. 不读取 latest pipeline_check；
7. 不 fallback 到旧日期。

---

## 十、运行检查

如果本地数据允许，请执行：

```bash
TRADE_DATE=20260528 bash entrypoint.sh
```

然后检查：

```bash
ls -lh reports/daily/*20260528*
cat reports/daily/pipeline_check_20260528.json
```

如果数据不完整，可以只执行：

```bash
python -m analysis.pipeline_check --date 20260528
```

并说明结果。

---

## 十一、Review 输出格式

请按以下格式输出：

```markdown
# V3-Stabilization 第 2 轮 Review：pipeline_check + email 联动

## 1. 总体结论

通过 / 暂缓通过 / 不通过

## 2. 当前主链路顺序

- entrypoint 顺序：
- date 传递情况：
- 是否存在顺序风险：

## 3. pipeline_check.py 当前状态

- 是否支持 --date：
- 是否生成同日期 json：
- 当前 JSON 结构：
- critical_missing：
- non_critical_missing：
- 是否存在 fallback/latest 风险：

## 4. email_sender.py 当前状态

- 是否支持 --date：
- 是否读取同日期 trade_plan：
- 是否读取 pipeline_check：
- 附件是否只取同日期：
- 是否存在旧日期风险：

## 5. 缺口列表

列出本轮发现的问题，按优先级排序。

## 6. 最小改造方案

只提出下一轮应该怎么改，不要直接改代码。

## 7. 不阻断项

列出可以以后再处理的问题。

## 8. 下一轮建议

明确下一轮是否可以进入代码修改。
```

---

## 十二、本轮通过标准

本轮 review 可以通过的标准：

1. 当前问题被完整识别；
2. pipeline_check 和 email_sender 的职责边界清楚；
3. 没有直接修改代码；
4. 下一轮最小改造范围明确；
5. 没有引入新策略；
6. 没有扩大到 report_renderer、selector、market 等无关模块。

如果发现 `pipeline_check.py` 和 `email_sender.py` 已经基本符合要求，可以建议下一轮只做小修；如果差距较大，下一轮仍然只做最小接入，不做大重构。


# V3-Stabilization 第 2 轮代码修改：pipeline_check + email 缺失项联动

## 当前项目背景

项目：`testStock`

当前阶段：

> V3-Stabilization：日报系统口径统一与稳定性收敛

上一轮 review 结论：

系统已经具备基本联动能力：

* `entrypoint.sh` 顺序正确；
* `pipeline_check` 在 `daily_report` 之后；
* `email_sender` 在 `pipeline_check` 之后；
* 所有关键模块统一接收 `--date "$TRADE_DATE"`；
* `pipeline_check.py` 支持 `--date`；
* `email_sender.py` 支持 `--date`；
* 当前无 latest/fallback 旧日期风险。

但仍有一个闭环缺口：

> `email_sender.py` 目前不读取 `pipeline_check_YYYYMMDD.json`，所以即使有关键文件缺失，邮件正文也不会提示。

本轮进入代码修改，但只做最小改造。

---

## 一、本轮目标

本轮只做：

1. 扩展 `pipeline_check.py` 的 critical / non-critical 缺失分类；
2. 在 `pipeline_check_YYYYMMDD.json` 中增加稳定状态字段；
3. 让 `email_sender.py` 在 `--date` 模式下读取同日期 `pipeline_check_YYYYMMDD.json`；
4. 在邮件正文中追加“流程检查”提示段；
5. 不阻断邮件发送；
6. 不改变现有附件收集逻辑；
7. 不引入任何 latest/fallback 旧日期逻辑。

---

## 二、本轮允许修改的文件

本轮只允许修改：

```text
analysis/pipeline_check.py
analysis/email_sender.py
```

如确实需要更新文档，可追加：

```text
PRDs/V3-Stabilization.md
```

但本轮优先不改文档。

---

## 三、本轮禁止事项

禁止修改：

```text
analysis/daily_report.py
analysis/report_renderer.py
analysis/selector.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_mapping_quality.py
analysis/board_trend_tracker.py
entrypoint.sh
```

禁止做：

```text
新增策略
修改观察池逻辑
修改报告渲染逻辑
修改日报生成逻辑
修改附件筛选逻辑
移动文件
重构 email_sender
重构 pipeline_check
使用 latest 文件
fallback 到旧日期文件
提交 reports 产物
提交 __pycache__
提交 .claude 本地配置
```

---

## 四、pipeline_check.py 修改要求

### 1. 扩展 critical_missing 文件清单

当前 `CRITICAL` 只有：

```python
["daily_report_{}.md", "daily_summary_{}.json"]
```

请扩展为 7 个关键文件：

```python
CRITICAL = [
    "daily_report_{}.md",
    "daily_report_{}_pro.md",
    "daily_summary_{}.json",
    "trade_plan_{}.md",
    "trade_plan_{}.json",
    "board_trend_summary_{}.json",
    "board_mapping_quality_{}.json",
]
```

注意：如果当前代码里文件名格式不是这个形式，请保持当前项目已有命名风格，但语义必须覆盖以上 7 类文件。

---

### 2. 增加 non_critical_missing

将非关键文件单独归类，例如：

```python
NON_CRITICAL = [
    "board_trend_tracker_{}.xlsx",
    "board_alias_report_{}.md",
]
```

如果当前 pipeline_check 已经检查更多附加报告，可以继续保留，但要放入 `non_critical_missing`，不要混入 `critical_missing`。

---

### 3. 增加 status 字段

目标 JSON 至少包含：

```json
{
  "trade_date": "20260528",
  "status": "ok",
  "ok_files": [],
  "missing_files": [],
  "critical_missing": [],
  "non_critical_missing": [],
  "warnings": []
}
```

`status` 规则：

```text
critical_missing 非空：status = "critical"
critical_missing 为空但 non_critical_missing 非空：status = "warning"
两者都为空：status = "ok"
```

如果当前字段名已有 `ok_files`、`missing_files`、`critical_missing`，请尽量兼容保留，不要删除旧字段。

---

### 4. 保持同日期检查

`pipeline_check.py` 必须只检查当前 `--date` 对应文件，例如：

```text
reports/daily/daily_report_20260528.md
reports/daily/trade_plan_20260528.md
reports/daily/pipeline_check_20260528.json
```

禁止：

```text
glob latest
按修改时间取最新
fallback 到旧日期
扫描其他日期替代
```

---

## 五、email_sender.py 修改要求

### 1. 只在同日期读取 pipeline_check

在 `--date YYYYMMDD` 模式下，读取：

```text
reports/daily/pipeline_check_YYYYMMDD.json
```

如果文件不存在，不要 fallback 到旧日期，直接在邮件正文中提示：

```text
流程检查：pipeline_check_YYYYMMDD.json 未生成
```

不阻断邮件发送。

---

### 2. 邮件正文追加“流程检查”段

在现有邮件正文后追加一段，格式可以简洁：

```text
流程检查：
- 状态：ok / warning / critical
- 关键缺失：无 / xxx, xxx
- 非关键缺失：无 / xxx, xxx
```

如果 `pipeline_check_YYYYMMDD.json` 不存在：

```text
流程检查：
- 状态：未检查
- 提示：pipeline_check_YYYYMMDD.json 未生成
```

---

### 3. 兼容旧 JSON 结构

考虑当前 JSON 可能只有：

```json
{
  "trade_date": "...",
  "ok_files": [],
  "missing_files": [],
  "critical_missing": []
}
```

所以 email_sender 读取时要用 `.get()`，避免 KeyError：

```python
critical_missing = pipeline_check.get("critical_missing", [])
non_critical_missing = pipeline_check.get("non_critical_missing", [])
status = pipeline_check.get("status", "unknown")
```

---

### 4. 不改变附件逻辑

不要修改当前附件筛选逻辑。

尤其不要重新引入：

```text
latest trade_plan
latest report
glob 所有日期
按修改时间取最新
zip 混入旧日期文件
```

---

## 六、建议实现方式

### pipeline_check.py

建议增加一个小函数：

```python
def classify_status(critical_missing: list[str], non_critical_missing: list[str]) -> str:
    if critical_missing:
        return "critical"
    if non_critical_missing:
        return "warning"
    return "ok"
```

---

### email_sender.py

建议增加一个小函数：

```python
def load_pipeline_check(trade_date: str) -> dict:
    path = Path("reports/daily") / f"pipeline_check_{trade_date}.json"
    if not path.exists():
        return {
            "status": "missing",
            "critical_missing": [],
            "non_critical_missing": [],
            "warnings": [f"{path.name} 未生成"],
        }

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
```

再增加一个格式化函数：

```python
def format_pipeline_check_section(pipeline_check: dict) -> str:
    status = pipeline_check.get("status", "unknown")
    critical_missing = pipeline_check.get("critical_missing", [])
    non_critical_missing = pipeline_check.get("non_critical_missing", [])
    warnings = pipeline_check.get("warnings", [])

    lines = ["", "流程检查：", f"- 状态：{status}"]
    lines.append("- 关键缺失：" + ("无" if not critical_missing else ", ".join(critical_missing)))
    lines.append("- 非关键缺失：" + ("无" if not non_critical_missing else ", ".join(non_critical_missing)))

    if warnings:
        lines.append("- 提示：" + "；".join(warnings))

    return "\n".join(lines)
```

注意：以上只是建议，实际请根据现有 `email_sender.py` 结构做最小接入，不要大重构。

---

## 七、验收命令

修改完成后执行：

```bash
python -m compileall analysis
git diff --stat
git status --short
```

如果本地有 20260528 数据，执行：

```bash
python -m analysis.pipeline_check --date 20260528
cat reports/daily/pipeline_check_20260528.json
```

如果可以跑完整流程，再执行：

```bash
TRADE_DATE=20260528 bash entrypoint.sh
```

---

## 八、验收重点

请确认：

1. `pipeline_check_20260528.json` 中存在：

   * `status`
   * `critical_missing`
   * `non_critical_missing`
   * `warnings`

2. `critical_missing` 覆盖 7 类关键文件：

   * 日报小白版；
   * 日报专业版；
   * daily_summary；
   * trade_plan md；
   * trade_plan json；
   * board_trend_summary；
   * board_mapping_quality json。

3. `email_sender.py` 读取的是同日期：

```text
pipeline_check_YYYYMMDD.json
```

4. 邮件正文能出现“流程检查”段；

5. 不读取 latest；

6. 不 fallback 到旧日期；

7. 不修改附件逻辑；

8. 不修改 selector / daily_report / report_renderer / entrypoint。

---

## 九、预期 diff

理想 diff 只包含：

```text
analysis/pipeline_check.py
analysis/email_sender.py
```

不应该出现：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/market.py
analysis/theme_detector.py
entrypoint.sh
reports/
analysis/__pycache__/
data/__pycache__/
.claude/
```

---

## 十、提交要求

如果验收通过，提交：

```bash
git add analysis/pipeline_check.py analysis/email_sender.py
git commit -m "fix: include pipeline check summary in email"
```

不要 push。

提交后发回：

```bash
git log -1 --oneline
git status --short
git diff HEAD~1 --stat
```

# V3-Stabilization 第 2 轮收尾 Review：pipeline_check + email 联动

当前已经完成 commit：

```bash
15e7aaa fix: pipeline_check + email联动，CRITICAL扩至7项，email读pipeline JSON
```

`git diff HEAD~1 --stat` 显示本轮修改了：

```text
PRDs/V3-Stabilization.md
analysis/email_sender.py
analysis/pipeline_check.py
```

代码范围基本符合要求。

但是当前 `git status --short` 仍显示：

```text
M PRDs/V3-Stabilization.md
```

说明 PRD 文件还有未提交修改。

## 一、本轮任务

只做收尾检查和状态清理，不要继续开发新功能。

---

## 二、先处理 PRD 残留

请先执行：

```bash
git diff PRDs/V3-Stabilization.md
```

判断这次未提交修改是否只是补充第 2 轮 pipeline_check + email 联动说明。

如果只是合理文档补充，则提交：

```bash
git add PRDs/V3-Stabilization.md
git commit -m "docs: update pipeline email linkage notes"
```

如果是重复内容、无关内容、旧 PRD 内容或不需要保留，则撤回：

```bash
git checkout -- PRDs/V3-Stabilization.md
```

处理后执行：

```bash
git status --short
```

要求为空。

---

## 三、检查代码改动范围

执行：

```bash
git diff HEAD~1 --stat
git diff HEAD~1 --name-only
```

确认代码层面只涉及：

```text
analysis/pipeline_check.py
analysis/email_sender.py
```

不应该出现：

```text
analysis/daily_report.py
analysis/selector.py
analysis/report_renderer.py
analysis/market.py
analysis/theme_detector.py
entrypoint.sh
reports/
analysis/__pycache__/
data/__pycache__/
.claude/
```

---

## 四、检查 pipeline_check.py

执行：

```bash
sed -n '1,240p' analysis/pipeline_check.py
```

确认：

1. `CRITICAL` 已扩展到 7 类关键文件；
2. 存在 `non_critical_missing`；
3. 输出 JSON 中存在 `status`；
4. 输出 JSON 中存在 `warnings`；
5. `status` 规则为：

   * 有 critical 缺失：`critical`
   * 无 critical 但有 non-critical 缺失：`warning`
   * 都无缺失：`ok`
6. 只检查 `--date` 指定日期文件；
7. 没有 latest；
8. 没有 fallback 到旧日期；
9. 没有业务生成逻辑。

---

## 五、检查 email_sender.py

执行：

```bash
sed -n '1,320p' analysis/email_sender.py
```

确认：

1. `--date` 模式下读取同日期：

```text
reports/daily/pipeline_check_YYYYMMDD.json
```

2. 如果文件不存在，不 fallback 到旧日期；
3. 邮件正文追加“流程检查”段；
4. 能显示：

   * 状态；
   * 关键缺失；
   * 非关键缺失；
   * warnings；
5. 不阻断邮件发送；
6. 不改变附件收集逻辑；
7. 不重新引入 latest trade_plan；
8. 不读取旧日期报告。

---

## 六、运行检查

执行：

```bash
python -m compileall analysis
```

然后执行：

```bash
python -m analysis.pipeline_check --date 20260528
cat reports/daily/pipeline_check_20260528.json
```

如果本地数据完整，再执行：

```bash
TRADE_DATE=20260528 bash entrypoint.sh
```

如果数据不完整，请说明是数据缺失还是代码错误。

---

## 七、检查 Git 污染

执行：

```bash
git status --short --untracked-files=all
```

不应该出现：

```text
analysis/__pycache__/
data/__pycache__/
reports/
.claude/
*.pyc
```

如果出现 reports 产物，不要提交。

---

## 八、Review 输出格式

请按下面格式输出：

```markdown
# V3-Stabilization 第 2 轮收尾 Review 结果

## 1. 总体结论

通过 / 暂缓通过 / 不通过

## 2. PRD 残留处理

- 是否还有未提交 PRD 修改：
- 处理方式：提交 / 撤回 / 暂停

## 3. 改动范围

- 修改文件：
- 是否越界：

## 4. pipeline_check.py 检查

- CRITICAL 是否扩至 7 项：
- non_critical_missing：
- status：
- warnings：
- 是否存在 latest/fallback 风险：

## 5. email_sender.py 检查

- 是否读取同日期 pipeline_check：
- pipeline_check 缺失时是否不阻断：
- 邮件正文是否追加流程检查段：
- 附件逻辑是否未改变：
- 是否存在旧日期风险：

## 6. 运行检查

- compileall：
- pipeline_check --date：
- entrypoint，如有：

## 7. Git 污染检查

- pycache：
- reports：
- local config：
- git status：

## 8. 下一步建议

是否可以 push origin dev。
```

---

## 九、通过标准

本轮通过标准：

1. `git status --short` 为空；
2. `compileall` 通过；
3. `pipeline_check.py` 输出包含 `status / critical_missing / non_critical_missing / warnings`；
4. `email_sender.py` 读取同日期 pipeline_check；
5. 邮件正文能提示流程检查；
6. pipeline_check 缺失时不阻断邮件；
7. 不引入 latest/fallback；
8. 不改变附件收集逻辑；
9. 无 pycache / reports / local config 污染。


# V3-Stabilization 第 3 轮 Review：selector 安全边界

## 当前项目背景

项目：`testStock`

当前阶段：

> V3-Stabilization：日报系统口径统一与稳定性收敛

当前已经完成：

1. 第 0 轮：结构占位 ✅
2. 第 1 轮：`report_context` 最小接入 ✅
3. 第 2 轮：`pipeline_check + email` 联动 ✅

当前 `dev` 已 push，最新提交为：

```bash
d096132 docs: update pipeline email linkage notes
4574e53 fix: pipeline_check status规则修正 critical/warning/ok
15e7aaa fix: pipeline_check + email联动，CRITICAL扩至7项，email读pipeline JSON
```

本轮进入：

> selector 安全边界 review

本轮只做 review，不直接改代码。

---

## 一、本轮目标

检查当前 selector / 观察池生成逻辑是否存在风险边界缺口。

重点检查：

1. N 开头新股是否会进入普通观察池；
2. 创业板 / 科创板 / 北交所是否按账户权限过滤；
3. N字异动 / 二次起爆是否有 `pct_20d <= 60` 高位上限；
4. 缺 MA / 缺 volume_ratio 是否会默认通过；
5. 低价值板块是否会作为板块联动理由；
6. 高风险票是否会进入可观察 / 谨慎观察池；
7. 高风险票是否只进入高风险复盘池；
8. 小白版观察池是否可能出现账户不可买市场。

---

## 二、本轮禁止事项

本轮禁止修改任何文件。

不要执行：

```bash
git add
git commit
git push
```

不要修改：

```text
analysis/selector.py
analysis/risk_engine.py
analysis/daily_report.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/market.py
analysis/theme_detector.py
entrypoint.sh
```

本轮只做检查、梳理和给出最小改造建议。

---

## 三、先确认当前状态

请执行：

```bash
git checkout dev
git pull origin dev
git status --short
git log -5 --oneline
```

要求：

```text
git status --short 为空
```

如果工作区不干净，先停止 review，说明未提交文件。

---

## 四、重点查看 selector 相关文件

请执行：

```bash
sed -n '1,320p' analysis/selector.py
```

如果存在以下文件，也请查看：

```bash
sed -n '1,320p' analysis/risk_engine.py
sed -n '1,260p' analysis/stock_board_mapper.py
sed -n '1,260p' analysis/report_renderer.py
```

如果某些文件不存在，请说明不存在，不要创建。

---

## 五、检查账户权限过滤

请搜索：

```bash
grep -R "ALLOW_CHINEXT\|ALLOW_STAR\|ALLOW_BSE" -n analysis
grep -R "创业板\|科创板\|北交所\|688\|689\|300\|301\|8" -n analysis/selector.py analysis/risk_engine.py 2>/dev/null
```

检查点：

1. 是否存在 `ALLOW_CHINEXT`；
2. 是否存在 `ALLOW_STAR`；
3. 是否存在 `ALLOW_BSE`；
4. 创业板股票是否按权限过滤；
5. 科创板股票是否按权限过滤；
6. 北交所股票是否按权限过滤；
7. 过滤是否只作用于普通观察池；
8. 高风险复盘池是否可以保留但明确标记不可买；
9. 小白版可观察 / 谨慎观察是否会出现账户不可买市场。

---

## 六、检查 N 开头新股过滤

请搜索：

```bash
grep -R "N开头\|新股\|startswith('N')\|startswith(\"N\")\|name.startswith" -n analysis
```

检查点：

1. 股票名称以 `N` 开头是否被识别；
2. N 开头新股是否会进入普通观察池；
3. N 开头新股是否只允许进入高风险复盘池或直接回避；
4. 是否有清晰原因提示；
5. 是否只按股票代码判断而漏掉名称判断。

---

## 七、检查 N字异动 / 二次起爆高位限制

请搜索：

```bash
grep -R "N字\|二次起爆\|pct_20d\|20d\|涨幅" -n analysis
```

检查点：

1. 是否存在 N字异动策略；
2. 是否存在二次起爆策略；
3. 是否已经限制 `pct_20d <= 60`；
4. 如果没有限制，是否可能把高位股放入普通观察池；
5. 是否应该在下一轮只加安全上限，不改策略本身。

本轮目标不是优化策略，只判断是否需要补安全边界。

---

## 八、检查缺 MA / 缺 volume_ratio 的处理

请搜索：

```bash
grep -R "ma5\|ma10\|ma20\|volume_ratio\|量比\|均线" -n analysis/selector.py analysis/risk_engine.py 2>/dev/null
```

检查点：

1. 缺少 MA 数据时是否默认通过；
2. 缺少 `volume_ratio` 时是否默认通过；
3. 是否有降级提示；
4. 是否有“数据不足，不进入可观察池”的处理；
5. 是否会因为字段缺失导致异常；
6. 是否会因为字段缺失反而放宽条件。

---

## 九、检查低价值板块是否作为联动理由

请搜索：

```bash
grep -R "低价值\|弱板块\|板块联动\|board\|theme" -n analysis/selector.py analysis/theme_detector.py analysis/report_renderer.py 2>/dev/null
```

检查点：

1. 是否有低价值板块定义；
2. 低价值板块是否会作为推荐理由；
3. 是否存在“个股被低质量板块误增强”的情况；
4. 是否需要在下一轮把低价值板块从 board-linkage reason 中排除；
5. 是否只在报告提示中保留，不作为加分逻辑。

---

## 十、检查高风险票分层

请搜索：

```bash
grep -R "高风险\|谨慎观察\|可观察\|回避\|不可交易\|watchlist_layer\|risk" -n analysis
```

检查点：

1. 是否存在高风险池；
2. 高风险票是否可能同时进入可观察池；
3. 高风险票是否可能进入谨慎观察池；
4. 是否有去重逻辑；
5. 小白版是否重复展示高风险票；
6. 高风险票是否只进入高风险复盘池；
7. 是否有明确 reason 标注。

---

## 十一、检查报告层是否有二次放大风险

请查看 `report_renderer.py` 相关逻辑：

```bash
grep -n "可观察\|谨慎观察\|高风险\|回避\|不可交易" analysis/report_renderer.py
```

检查点：

1. selector 已经分层后，renderer 是否又重新拼池；
2. renderer 是否会把高风险票重复展示到小白版主观察池；
3. renderer 是否会遗漏“不可交易”提示；
4. renderer 是否会把账户不可买股票写成可观察。

---

## 十二、Review 输出格式

请按以下格式输出：

```markdown
# V3-Stabilization 第 3 轮 Review：selector 安全边界

## 1. 总体结论

通过 / 暂缓通过 / 不通过

## 2. 当前 selector 相关文件

- selector.py:
- risk_engine.py:
- stock_board_mapper.py:
- report_renderer.py:

## 3. 账户权限过滤

- ALLOW_CHINEXT:
- ALLOW_STAR:
- ALLOW_BSE:
- 创业板过滤：
- 科创板过滤：
- 北交所过滤：
- 是否存在小白版不可买股票风险：

## 4. N 开头新股

- 是否识别：
- 是否进入普通观察池：
- 当前处理：
- 风险判断：

## 5. N字异动 / 二次起爆

- 是否存在策略：
- 是否有 pct_20d <= 60：
- 是否存在高位入池风险：

## 6. 缺 MA / 缺 volume_ratio

- 缺 MA 是否默认通过：
- 缺 volume_ratio 是否默认通过：
- 是否有降级提示：
- 风险判断：

## 7. 低价值板块联动

- 是否定义低价值板块：
- 是否作为推荐理由：
- 是否存在误增强风险：

## 8. 高风险票分层

- 是否有高风险池：
- 是否会进入可观察：
- 是否会进入谨慎观察：
- 是否重复展示：
- 当前风险：

## 9. 报告层二次风险

- renderer 是否重新拼池：
- 是否可能放大风险：
- 小白版展示是否安全：

## 10. 缺口列表

按优先级列出：

- P0:
- P1:
- P2:

## 11. 最小改造建议

下一轮如果改代码，只允许做安全边界，不新增策略。

## 12. 是否建议进入代码修改

是 / 否
```

---

## 十三、本轮通过标准

本轮 review 通过标准：

1. 明确 selector 当前风险边界；
2. 找出是否存在 P0 安全缺口；
3. 不直接修改代码；
4. 不新增策略；
5. 不扩大到 report_context / pipeline / email；
6. 下一轮代码修改范围清楚；
7. 如果发现高风险票进入普通观察池，应标记为 P0；
8. 如果发现账户不可买股票进入小白版可观察池，应标记为 P0。


# V3-Stabilization 第 3 轮代码修改：selector 安全边界 P0 修复

## 当前项目背景

项目：`testStock`

当前阶段：

> V3-Stabilization：日报系统口径统一与稳定性收敛

当前已完成：

1. 第 0 轮：结构占位 ✅
2. 第 1 轮：`report_context` 最小接入 ✅
3. 第 2 轮：`pipeline_check + email` 联动 ✅
4. 第 3 轮 review：selector 安全边界检查完成，结论为“暂缓通过”

本轮进入代码修改，但只修 P0 安全边界，不新增策略，不重构 selector。

---

## 一、本轮目标

只修两个 P0 问题：

### P0-1：N字异动 / 二次起爆缺少 `pct_20d` 高位上限

当前问题：

```text
N字异动：pct_20d >= 8，但无上限；
二次起爆：pct_20d >= 10，但无上限；
```

风险：

```text
pct_20d = 100%、200% 的高位股也可能进入普通观察池。
```

本轮目标：

```text
N字异动 / 二次起爆都增加 pct_20d <= 60 的安全上限。
```

---

### P0-2：缺 volume_ratio 时静默通过

当前问题：

```text
_vr_ge(df, threshold) 在缺 volume_ratio 时返回 pd.Series(True)
_vr_val(df) 在缺 volume_ratio 时返回 pd.Series(1.0)
```

风险：

```text
无 volume_ratio 数据时，所有股票默认通过量比筛选。
```

本轮目标：

```text
缺 volume_ratio 时不能默认通过。
```

最小修复：

```text
_vr_ge(df, threshold) 缺 volume_ratio 时返回 False；
_vr_val(df) 可以继续返回 1.0 作为展示降级值，但不能影响筛选通过。
```

---

## 二、本轮允许修改的文件

本轮只允许修改：

```text
analysis/selector.py
```

如确实需要补充文档，可追加：

```text
PRDs/V3-Stabilization.md
```

但优先不改文档。

---

## 三、本轮禁止事项

禁止修改：

```text
analysis/daily_report.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_mapping_quality.py
analysis/board_trend_tracker.py
entrypoint.sh
```

禁止做：

```text
新增策略
删除策略
重构 selector
改观察池分层规则
改报告渲染逻辑
改邮件逻辑
改 pipeline 逻辑
移动文件
修改主链路
提交 reports 产物
提交 __pycache__
提交 .claude 本地配置
```

---

## 四、修改要求 1：N字异动 / 二次起爆增加 pct_20d 上限

请在 `analysis/selector.py` 中定位：

```text
select_n_latent
select_n_breakout
```

或者对应的：

```text
N字异动
二次起爆
```

当前逻辑大概率类似：

```python
df["pct_20d"].fillna(0) >= 8
```

和：

```python
df["pct_20d"].fillna(0) >= 10
```

请改为：

```python
(df["pct_20d"].fillna(0) >= 8) & (df["pct_20d"].fillna(0) <= 60)
```

以及：

```python
(df["pct_20d"].fillna(0) >= 10) & (df["pct_20d"].fillna(0) <= 60)
```

注意：

1. 只加上限；
2. 不改其他条件；
3. 不调参数；
4. 不新增策略；
5. 不改变策略名称；
6. 不改变输出字段结构。

---

## 五、修改要求 2：缺 volume_ratio 不默认通过

请定位：

```text
_vr_ge(df, threshold)
_vr_val(df)
```

当前问题是：

```python
_vr_ge(...) 缺 volume_ratio 时返回 True
```

请改成：

```python
_vr_ge(...) 缺 volume_ratio 时返回 False
```

建议逻辑：

```python
def _vr_ge(df, threshold):
    if "volume_ratio" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["volume_ratio"].fillna(0) >= threshold
```

如果当前代码还兼容其他字段名，例如：

```text
volume_ratio
量比
```

请保持原有兼容逻辑，但最终原则必须是：

```text
没有可用量比字段时，不允许默认通过筛选。
```

`_vr_val(df)` 可以继续用于展示降级，例如缺失时返回 1.0，但不能用于让筛选通过。

---

## 六、MA 缺失问题本轮处理原则

review 中也指出 MA 缺失时存在：

```text
fillna(df["close"])
fillna(0)
```

这可能存在风险，但 MA 逻辑可能分散在多个策略里。

本轮不要大改 MA 逻辑。

本轮只要求：

1. 不扩大 MA 改动；
2. 不重写所有均线条件；
3. 如果发现某一处 MA 缺失明显导致默认通过，可以加注释或轻量修复；
4. 更完整的 MA 缺失处理放到后续 `report_regression_check` 或 selector 第二轮安全收敛。

也就是说，本轮必须修 volume_ratio，不强制全面修 MA。

---

## 七、运行检查

修改完成后执行：

```bash
python -m compileall analysis
```

然后执行：

```bash
git diff --stat
git diff -- analysis/selector.py
git status --short
```

如本地有数据，可以执行：

```bash
python -m analysis.daily_report --mode both --date 20260528
```

如果数据不完整导致失败，请说明是数据缺失还是代码错误。

---

## 八、重点检查

请确认：

1. `select_n_latent` 已增加 `pct_20d <= 60`；
2. `select_n_breakout` 已增加 `pct_20d <= 60`；
3. `_vr_ge` 缺 `volume_ratio` 时不再返回全 True；
4. 没有修改其他策略逻辑；
5. 没有修改观察池分层；
6. 没有修改报告渲染；
7. 没有修改邮件和 pipeline；
8. 没有引入 pycache / reports 产物。

---

## 九、预期 diff

理想 diff 只包含：

```text
analysis/selector.py
```

可选包含：

```text
PRDs/V3-Stabilization.md
```

不应该出现：

```text
analysis/daily_report.py
analysis/report_renderer.py
analysis/email_sender.py
analysis/pipeline_check.py
analysis/market.py
analysis/theme_detector.py
entrypoint.sh
reports/
analysis/__pycache__/
data/__pycache__/
.claude/
```

---

## 十、提交要求

如果验收通过，提交：

```bash
git add analysis/selector.py
git commit -m "fix: tighten selector safety boundaries"
```

如果也更新了 PRD，则单独提交：

```bash
git add PRDs/V3-Stabilization.md
git commit -m "docs: update selector safety notes"
```

不要 push。

提交后发回：

```bash
git log -2 --oneline
git status --short
git diff HEAD~1 --stat
```

---

## 十一、本轮通过标准

本轮通过标准：

1. 只改 `analysis/selector.py`；
2. `compileall` 通过；
3. N字异动增加 `pct_20d <= 60`；
4. 二次起爆增加 `pct_20d <= 60`；
5. 缺 volume_ratio 时不再默认通过；
6. 没有新增策略；
7. 没有改报告渲染；
8. 没有改 email / pipeline；
9. 没有 pycache / reports / local config 污染。


---

## 十一、本轮通过标准

本轮通过标准：

1. 只改两个文件；
2. `compileall` 通过；
3. `pipeline_check` JSON 结构更稳定；
4. `email_sender` 能读取同日期 pipeline_check；
5. 邮件正文能提示关键缺失和非关键缺失；
6. pipeline_check 缺失时不阻断邮件；
7. 不引入旧日期 fallback；
8. 不改变附件收集逻辑；
9. 没有 pycache / reports 产物进入 Git。
