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
