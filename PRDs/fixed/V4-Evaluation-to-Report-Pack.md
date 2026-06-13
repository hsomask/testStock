# V4 Evaluation-to-Report Pack：将昨日观察池 T+1 兑现复盘接入日报

## 0. 本轮目标

本轮目标是把：

```text
昨日观察池兑现复盘（T+1）
```

接入主日报 `daily_report_YYYYMMDD.md`。

核心原则：

```text
evaluation 负责计算；
daily_report 只负责读取和展示；
不在 daily_report 中重新计算 T+1；
不改变 selector；
不改变 trade_plan；
不改变 evaluation 计算逻辑；
不改变数据库结构。
```

最终日报阅读顺序变成：

```text
0. 今日摘要
1. 昨日观察池兑现复盘（T+1）
2. 交易环境判断
3. 市场状态
...
```

---

## 1. 为什么要先调度再接日报

当前如果仍然是：

```text
21:00 日报生成并发送
21:30 evaluation 运行
```

那么日报生成时，今天的 T+1 evaluation 结果还没有生成，日报无法展示：

```text
昨日观察池 → 今日表现
```

因此本轮需要调整为：

```text
先生成今日基础数据
再运行 evaluation
再重新渲染日报
最后发送日报邮件
```

---

## 2. 新调度顺序

目标顺序：

```text
[1] 跑日报主链路，但先不发邮件
[2] 跑 evaluation，生成 T+1 结果并落库
[3] 重新渲染日报，让日报读取 evaluation 结果
[4] 发送日报邮件
```

具体流程：

```text
entrypoint.sh（SEND_DAILY_EMAIL=0）
→ scripts/evaluation_entrypoint.sh（SEND_EVAL_EMAIL=0）
→ python -m analysis.daily_report --date YYYYMMDD --mode both
→ python -m analysis.email_sender --date YYYYMMDD
```

说明：

```text
--mode both 仍可传入，但 daily_report 内部已经统一生成 unified report。
```

---

## 3. 需要改动的文件

允许修改：

```text
entrypoint.sh
scripts/report_with_evaluation_entrypoint.sh
analysis/daily_report.py
analysis/report_renderer.py
analysis/evaluation_query.py 或新增只读 helper
analysis/email_sender.py
```

尽量不改：

```text
analysis/watchlist_evaluation.py
analysis/evaluation_entrypoint.py
analysis/selector.py
analysis/trade_plan.py
sql/schema.sql
data/config.py
```

禁止修改：

```text
selector 选股逻辑
trade_plan 分层逻辑
evaluation 计算逻辑
数据库结构
mapper 逻辑
```

---

# 4. 第一步：entrypoint.sh 增加 SEND_DAILY_EMAIL 开关

## 4.1 目标

当前 `entrypoint.sh` 会在日报主流程结束后直接发送日报邮件。

本轮需要支持：

```bash
SEND_DAILY_EMAIL=0 bash entrypoint.sh
```

这样可以：

```text
日报主产物照常生成；
trade_plan 照常生成；
board_trend 相关文件照常生成；
pipeline_check 照常生成；
但先不发日报邮件。
```

## 4.2 修改要求

在 `entrypoint.sh` 中，原来发送日报邮件的位置改为：

```bash
if [ "${SEND_DAILY_EMAIL:-1}" = "1" ]; then
    echo "[INFO] Sending daily email..."
    python -m analysis.email_sender --date "$TRADE_DATE"
else
    echo "[INFO] SEND_DAILY_EMAIL=0, skip daily email"
fi
```

默认值保持：

```text
SEND_DAILY_EMAIL=1
```

所以旧 cron 不受影响。

## 4.3 验收

执行：

```bash
SEND_DAILY_EMAIL=0 TRADE_DATE=20260605 bash entrypoint.sh
```

必须满足：

```text
1. daily_report_20260605.md 正常生成；
2. trade_plan_20260605.md/json 正常生成；
3. board_trend_tracker_20260605.xlsx 正常生成；
4. pipeline_check_20260605.json 正常生成；
5. 不发送日报邮件；
6. 日志出现 SEND_DAILY_EMAIL=0, skip daily email。
```

---

# 5. 第二步：新增统一调度脚本

新增文件：

```text
scripts/report_with_evaluation_entrypoint.sh
```

## 5.1 脚本职责

它是新的统一日报调度入口：

```text
先跑基础日报；
再跑 evaluation；
再重渲染日报；
最后发邮件。
```

## 5.2 推荐脚本

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=================================================="
echo "Daily Report With Evaluation"
echo "=================================================="

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TRADE_DATE="${TRADE_DATE:-$(date +%Y%m%d)}"
export TRADE_DATE

echo "TRADE_DATE=$TRADE_DATE"
echo "=================================================="

echo "[1/4] Run daily pipeline without email"
SEND_DAILY_EMAIL=0 TRADE_DATE="$TRADE_DATE" bash entrypoint.sh

echo ""
echo "[2/4] Run evaluation without email"
set +e
AS_OF_DATE="$TRADE_DATE" SEND_EVAL_EMAIL=0 bash scripts/evaluation_entrypoint.sh
EVAL_STATUS=$?
set -e

if [ "$EVAL_STATUS" -ne 0 ]; then
    echo "[WARN] evaluation_entrypoint failed or deferred, continue daily report rendering."
fi

echo ""
echo "[3/4] Re-render daily report with evaluation summary"
python -m analysis.daily_report --date "$TRADE_DATE" --mode both

echo ""
echo "[4/4] Send daily email"
python -m analysis.email_sender --date "$TRADE_DATE"

echo ""
echo "[DONE] daily report with evaluation completed."
```

## 5.3 关键规则

```text
evaluation defer 不阻断日报；
evaluation 报错不阻断日报；
日报生成失败才阻断；
邮件发送失败按 email_sender 原逻辑处理。
```

原因：

```text
T+1 复盘是增强模块，不应该因为 evaluation 暂缓导致主日报不发。
```

---

# 6. 第三步：daily_report 读取 evaluation 结果

## 6.1 不允许重新计算

`daily_report.py` 不允许：

```text
重新取行情；
重新评价昨日股票；
重新写 evaluation 表；
重新调用 watchlist_evaluation 计算逻辑。
```

只允许：

```text
读取已经落库或已生成文件的 evaluation summary/result。
```

---

## 6.2 读取目标

日报需要读取：

```text
signal_date = 上一个交易日
as_of_date = 当前 trade_date
mode = daily
```

例如：

```text
当前日报日期：20260605
昨日信号日期：20260604
应读取 evaluation:
signal_date = 20260604
as_of_date = 20260605
mode = daily
```

---

## 6.3 推荐新增只读 helper

可以新增：

```text
analysis/evaluation_report_reader.py
```

职责：

```text
只读 evaluation 结果；
不计算；
不写库；
不调行情 API。
```

推荐函数：

```python
def load_t1_evaluation_summary(as_of_date: str) -> dict:
    """
    读取当前 as_of_date 对应的昨日观察池 T+1 evaluation 摘要。

    返回：
    {
        "available": True/False,
        "status": "ok" / "defer" / "missing" / "error",
        "signal_date": "YYYYMMDD",
        "as_of_date": "YYYYMMDD",
        "total_signals": int,
        "evaluated_1d": int,
        "coverage_1d": float,
        "avg_return_1d": float or None,
        "win_rate_1d": float or None,
        "inversion": bool,
        "risk_warning": bool,
        "confidence_level": str,
        "conclusion_level": str,
        "top_winners": list,
        "top_losers": list,
        "messages": list,
    }
    """
```

优先读取数据库。

如果数据库读取失败，可以降级读取：

```text
reports/evaluation/evaluation_summary_*.json
reports/evaluation/*.json
```

具体以现有 evaluation 文件命名为准。

---

## 6.4 查询规则

如果 evaluation 表有 summary 表，按以下条件取最新：

```sql
WHERE mode = 'daily'
  AND as_of_date = 当前 trade_date
ORDER BY created_at DESC
LIMIT 1
```

如果表里有 signal_date，则校验：

```text
signal_date 应等于当前 trade_date 的上一个交易日
```

如果无法确认上一个交易日，也至少展示 evaluation 自身返回的 signal_date。

---

## 6.5 缺失 / defer 降级

如果查不到：

```text
今日 T+1 复盘尚未生成。
```

如果 scheduler defer：

```text
今日 T+1 复盘因行情缓存不足暂缓。
```

如果 evaluation 失败：

```text
今日 T+1 复盘读取失败，仅展示今日日报主体。
```

这些都不阻断日报。

---

# 7. 第四步：日报新增 T+1 模块

## 7.1 模块位置

放在今日摘要后面：

```text
## 0. 今日摘要

## 1. 昨日观察池兑现复盘（T+1）

## 2. 交易环境判断
```

原后续章节编号顺延。

---

## 7.2 模块名称

不要叫：

```text
昨日推荐复盘
```

建议叫：

```text
昨日观察池兑现复盘（T+1）
```

原因：

```text
系统定位是自动化复盘 + 风险提示 + 观察池生成，不是荐股系统。
```

---

## 7.3 有数据时展示

推荐展示：

```markdown
## 1. 昨日观察池兑现复盘（T+1）

| 项目 | 结果 |
|------|------|
| 信号日期 | 2026-06-04 |
| 评价日期 | 2026-06-05 |
| 昨日观察池数量 | 27 |
| 实际评价数量 | 25 |
| 1日覆盖率 | 92.6% |
| 平均次日收益 | +1.23% |
| 次日胜率 | 56.0% |
| 分层倒挂 | 否 |
| 风险提示有效 | 是 |
| 结论等级 | daily_observation |

**本段结论：**
昨日观察池 T+1 整体表现尚可，但仍存在分化；强势集中在主线相关方向，非核心票继续降低追高优先级。
```

---

## 7.4 表现明细只展示 Top/Bottom

不要把所有股票都塞进日报。

最多展示：

```text
表现较好 3 只
表现较弱 3 只
```

示例：

```markdown
### 表现较好

| 股票 | 昨日层级 | 今日涨跌 | 量价 | 结果 |
|------|----------|----------|------|------|
| 亨通光电 | 候选低吸 | +7.04% | 健康放量 | ✅ 大涨 |
| 华特气体 | 候选低吸 | +15.50% | 健康放量 | ✅ 暴涨 |
| 模塑科技 | 只观察 | +7.36% | 放量上涨 | ✅ 兑现 |

### 表现较弱

| 股票 | 昨日层级 | 今日涨跌 | 量价 | 结果 |
|------|----------|----------|------|------|
| 迅捷兴 | 只观察 | -3.34% | 缩量下跌 | ❌ 失败 |
| 源杰科技 | 候选低吸 | -2.21% | 冲高回落 | ⚠️ 分歧 |
| 国机精工 | 只观察 | -1.40% | 放量分歧 | ⚠️ 分歧 |
```

---

## 7.5 没有数据时展示

如果 evaluation 尚未生成：

```markdown
## 1. 昨日观察池兑现复盘（T+1）

今日 T+1 复盘尚未生成。  
本模块将在 evaluation 链路完成后自动展示，不影响今日日报主体。
```

如果 defer：

```markdown
## 1. 昨日观察池兑现复盘（T+1）

今日 T+1 复盘因行情缓存不足暂缓。  
当前不对昨日观察池表现下结论。
```

如果读取失败：

```markdown
## 1. 昨日观察池兑现复盘（T+1）

今日 T+1 复盘读取失败。  
请检查 evaluation 输出或数据库连接。
```

---

# 8. 第五步：email_sender 保持两个附件

本轮接入 T+1 模块后，邮件附件仍然只保留：

```text
daily_report_YYYYMMDD.md
board_trend_tracker_YYYYMMDD.xlsx
```

不要因为 evaluation 接入日报而新增：

```text
evaluation_summary.json
evaluation_report.md
evaluation 自检邮件附件
```

T+1 结果只进入日报正文/主附件。

---

# 9. 第六步：crontab 调整

## 9.1 当前旧结构

当前可能是：

```cron
0 21 * * 1-5 ... docker compose run --rm stock-report ...
30 21 * * 1-5 ... evaluation_entrypoint ...
```

这会导致日报先发，evaluation 后跑。

---

## 9.2 新结构

改成一条统一链路：

```cron
0 21 * * 1-5 cd /root/stock-ai-system && flock -n /tmp/stock-report.lock docker compose run --rm --entrypoint /bin/bash stock-report scripts/report_with_evaluation_entrypoint.sh >> logs/cron.log 2>&1
```

原 21:30 独立 evaluation cron 先注释掉：

```cron
# 30 21 * * 1-5 ...
```

避免：

```text
重复跑 evaluation；
重复发 evaluation 邮件；
日报内 T+1 与独立邮件口径重复。
```

---

# 10. 验收标准

## 10.1 编译

```bash
python -m compileall analysis
```

必须通过。

---

## 10.2 基础日报无邮件验收

```bash
SEND_DAILY_EMAIL=0 TRADE_DATE=20260605 bash entrypoint.sh
```

必须满足：

```text
日报相关产物正常生成；
日报邮件不发送；
日志显示 skip daily email。
```

---

## 10.3 evaluation 验收

```bash
AS_OF_DATE=20260605 SEND_EVAL_EMAIL=0 bash scripts/evaluation_entrypoint.sh
```

允许出现：

```text
status=defer
```

但不能导致主日报链路失败。

---

## 10.4 统一调度脚本验收

```bash
TRADE_DATE=20260605 bash scripts/report_with_evaluation_entrypoint.sh
```

必须满足：

```text
1. 基础日报生成；
2. evaluation 尝试运行；
3. 日报重新渲染；
4. 日报邮件发送一次；
5. 附件只有 daily_report_20260605.md 和 board_trend_tracker_20260605.xlsx；
6. 如果 evaluation 有结果，日报包含“昨日观察池兑现复盘（T+1）”；
7. 如果 evaluation defer，日报显示 T+1 暂缓，不阻断邮件。
```

---

## 10.5 日报内容验收

日报必须出现：

```text
## 1. 昨日观察池兑现复盘（T+1）
```

有结果时必须展示：

```text
信号日期
评价日期
昨日观察池数量
实际评价数量
1日覆盖率
平均次日收益
次日胜率
分层倒挂
风险提示有效
结论等级
```

没有结果时必须展示降级说明。

---

## 10.6 邮件附件验收

邮件附件仍然只能包含：

```text
daily_report_YYYYMMDD.md
board_trend_tracker_YYYYMMDD.xlsx
```

不得包含：

```text
evaluation json
evaluation md
trade_plan md
board_trend_report md
mapping quality md
alias report md
任何 json 文件
```

---

# 11. 不允许的结果

本轮不允许出现：

```text
daily_report 重新计算 T+1；
evaluation 失败导致日报不发送；
日报邮件发送两次；
evaluation 自检邮件和日报重复发送；
附件重新变多；
crontab 保留旧日报 cron + 新统一 cron 双跑；
观察池 T+1 模块叫“昨日推荐复盘”。
```

---

# 12. 提交建议

建议拆成两个 commit。

## Commit 1：调度支持

```bash
git add entrypoint.sh scripts/report_with_evaluation_entrypoint.sh
git commit -m "feat: run evaluation before daily email"
```

## Commit 2：日报接入 T+1 模块

```bash
git add analysis/daily_report.py analysis/report_renderer.py analysis/evaluation_report_reader.py analysis/email_sender.py
git commit -m "feat: show t1 evaluation summary in daily report"
```

如果只做一个 commit：

```bash
git add entrypoint.sh scripts/report_with_evaluation_entrypoint.sh analysis/daily_report.py analysis/report_renderer.py analysis/evaluation_report_reader.py analysis/email_sender.py
git commit -m "feat: add t1 evaluation recap to daily report"
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

本轮完成后，系统应变成：

```text
1. 每晚只跑一条统一日报链路；
2. evaluation 在日报邮件发送前运行；
3. 日报包含“昨日观察池兑现复盘（T+1）”；
4. daily_report 只读 evaluation，不重新计算；
5. evaluation defer 不阻断日报；
6. 日报邮件只发一次；
7. 邮件附件仍然只有 daily_report.md + board_trend_tracker.xlsx；
8. 原始 selector / trade_plan / evaluation 计算逻辑不变。
```

# V4 T+1 Evaluation Recap Hotfix：修复 T+1 复盘展示口径

## 0. 本轮目标

本轮是在 `dfb3fb1 feat: add T+1 evaluation recap to daily report` 之后的 hotfix。

当前 T+1 模块已经接入日报，但还有 4 个展示口径问题需要修：

```text
1. 不要用 coverage_1d < 0.8 直接判断 defer；
2. renderer 需要根据 t1_data.status 分支展示；
3. “风险提示有效”改成“风险预警：有/无”；
4. 修正新增 T+1 模块后的章节小标题编号。
```

本轮不做：

```text
不改 selector
不改 trade_plan
不改 evaluation 计算逻辑
不改数据库结构
不改 mapper
不改 email_sender 附件逻辑
不改 crontab
不新增行情 API
不重新计算 T+1
```

---

## 1. 问题一：coverage_1d < 0.8 不应直接判 defer

### 1.1 当前问题

当前 `analysis/evaluation_report_reader.py` 中类似逻辑为：

```python
cov1d = row.get("coverage_1d") or 0
if cov1d < 0.8:
    status = "defer"
    msg = "今日 T+1 复盘因行情缓存不足暂缓。"
else:
    status = "ok"
    msg = None
```

这个判断不准确。

`coverage_1d` 低不一定表示 evaluation 被 scheduler defer。

例如：

```text
coverage_1d = 50%
```

可能只是：

```text
样本不足
部分股票未成熟
部分价格缺失
部分股票没有可评价数据
```

这时更应该展示：

```text
T+1 覆盖率偏低，结果仅供观察。
```

而不是：

```text
T+1 复盘因行情缓存不足暂缓。
```

---

### 1.2 新状态分类

`load_t1_evaluation_summary(as_of_date)` 返回的 `status` 建议分为：

```text
ok            覆盖率正常，可以展示完整 T+1 摘要
partial       有评价结果，但覆盖率偏低，只能观察
insufficient  evaluated_1d = 0，完全不能下结论
defer         evaluation 明确暂缓
missing       未找到 evaluation 结果
error         读取失败
```

---

### 1.3 新判断规则

不要用 `coverage_1d < 0.8` 直接判 `defer`。

建议改成：

```python
evaluated_1d = row.get("evaluated_1d") or 0
coverage_1d = row.get("coverage_1d") or 0
confidence_level = str(row.get("confidence_level", ""))
conclusion_level = str(row.get("conclusion_level", ""))

# 只有明确发现 defer 标记时才是 defer
is_defer = (
    str(row.get("status", "")).lower() == "defer"
    or "defer" in confidence_level.lower()
    or "defer" in conclusion_level.lower()
)

if is_defer:
    status = "defer"
    msg = "今日 T+1 复盘因行情缓存不足暂缓。"
elif evaluated_1d == 0:
    status = "insufficient"
    msg = "今日 T+1 复盘覆盖不足，暂不下结论。"
elif coverage_1d < 0.8:
    status = "partial"
    msg = "今日 T+1 覆盖率偏低，结果仅供观察。"
else:
    status = "ok"
    msg = None
```

如果 `evaluation` 的 diagnostics 中存在明确信息：

```text
price cache not ready
defer
insufficient_data
not_mature_1d
```

可以辅助判断，但不要把所有低覆盖率都归为 defer。

---

### 1.4 reader 返回结构

`evaluation_report_reader.py` 应返回：

```python
{
    "available": True,
    "status": "ok" | "partial" | "insufficient" | "defer" | "missing" | "error",
    "message": "...",
    "signal_date": "...",
    "as_of_date": "...",
    "total_signals": ...,
    "evaluated_1d": ...,
    "coverage_1d": ...,
    "avg_return_1d": ...,
    "win_rate_1d": ...,
    "inversion": ...,
    "risk_warning": ...,
    "confidence_level": "...",
    "conclusion_level": "...",
    "top_winners": [...],
    "top_losers": [...],
    "messages": [...],
}
```

如果查不到结果：

```python
{
    "available": False,
    "status": "missing",
    "message": "今日 T+1 复盘尚未生成。"
}
```

如果读取失败：

```python
{
    "available": False,
    "status": "error",
    "message": "今日 T+1 复盘读取失败。"
}
```

---

## 2. 问题二：renderer 需要根据 t1_data.status 分支展示

### 2.1 当前问题

当前 `report_renderer.py` 中只判断：

```python
if t1_data and t1_data.get("available"):
    展示完整表格
else:
    展示尚未生成
```

这会导致：

```text
status = defer / partial / insufficient
```

时也被当作完整 T+1 结果展示。

---

### 2.2 新展示规则

在 `render_unified_report()` 的 T+1 模块中，按 `status` 分支。

推荐逻辑：

```python
status = (t1_data or {}).get("status", "missing")

if not t1_data or not t1_data.get("available"):
    展示 missing/error message

elif status == "defer":
    展示暂缓说明，不展示胜率/平均收益结论

elif status == "insufficient":
    展示覆盖不足说明，不展示胜率/平均收益结论

elif status == "partial":
    展示摘要表，但增加醒目提示：
    “覆盖率偏低，结果仅供观察。”
    可以展示 evaluated_1d、coverage_1d、top/bottom，但结论不要写得太强

elif status == "ok":
    展示完整摘要
```

---

### 2.3 missing 展示模板

```markdown
## 1. 昨日观察池兑现复盘（T+1）

今日 T+1 复盘尚未生成。  
本模块将在 evaluation 链路完成后自动展示，不影响今日日报主体。
```

---

### 2.4 defer 展示模板

```markdown
## 1. 昨日观察池兑现复盘（T+1）

今日 T+1 复盘因行情缓存不足暂缓。  
当前不对昨日观察池表现下结论。
```

---

### 2.5 insufficient 展示模板

```markdown
## 1. 昨日观察池兑现复盘（T+1）

今日 T+1 复盘覆盖不足，暂不下结论。

| 项目 | 结果 |
|------|------|
| 信号日期 | 2026-06-04 |
| 评价日期 | 2026-06-05 |
| 昨日观察池数量 | 27 |
| 实际评价数量 | 0 |
| 1日覆盖率 | 0.0% |

> 覆盖不足时不展示胜率、平均收益和强结论。
```

---

### 2.6 partial 展示模板

```markdown
## 1. 昨日观察池兑现复盘（T+1）

> T+1 覆盖率偏低，结果仅供观察，不作为稳定结论。

| 项目 | 结果 |
|------|------|
| 信号日期 | 2026-06-04 |
| 评价日期 | 2026-06-05 |
| 昨日观察池数量 | 27 |
| 实际评价数量 | 12 |
| 1日覆盖率 | 44.4% |
| 平均次日收益 | +1.20% |
| 次日胜率 | 58.3% |
| 分层倒挂 | 否 |
| 风险预警 | 无 |
| 结论等级 | observe_only |
```

`partial` 可以展示 Top/Bottom，但最好加一句：

```text
样本覆盖不足，个股表现仅作为局部参考。
```

---

### 2.7 ok 展示模板

```markdown
## 1. 昨日观察池兑现复盘（T+1）

| 项目 | 结果 |
|------|------|
| 信号日期 | 2026-06-04 |
| 评价日期 | 2026-06-05 |
| 昨日观察池数量 | 27 |
| 实际评价数量 | 25 |
| 1日覆盖率 | 92.6% |
| 平均次日收益 | +1.23% |
| 次日胜率 | 56.0% |
| 分层倒挂 | 否 |
| 风险预警 | 无 |
| 结论等级 | daily_observation |
```

---

## 3. 问题三：“风险提示有效”改成“风险预警”

### 3.1 当前问题

当前日报中 T+1 表格写：

```text
风险提示有效：是 / 否
```

但这个口径不准确。

当前字段：

```python
risk_warning
```

更像是：

```text
evaluation 是否发现风险警告
```

不是：

```text
风险提示是否有效
```

`risk_warning=False` 不能说明“风险提示有效”。
`risk_warning=True` 也不能说明“风险提示无效”。

---

### 3.2 修改建议

将表格行：

```markdown
| 风险提示有效 | 是 |
```

改成：

```markdown
| 风险预警 | 无 |
```

或：

```markdown
| 风险预警 | **有** |
```

代码：

```python
lines.append(f"| 风险预警 | {'**有**' if td.get('risk_warning') else '无'} |")
```

不要再写：

```python
'是' if not risk_warning else '**否**'
```

---

### 3.3 验收标准

日报 T+1 模块中不应再出现：

```text
风险提示有效
```

应出现：

```text
风险预警
```

取值为：

```text
无
**有**
```

---

## 4. 问题四：修正章节小标题编号

### 4.1 当前问题

新增 T+1 模块后，主章节已经顺延：

```text
## 3. 市场状态
```

但内部小标题仍然可能是：

```text
### 2.1 大盘指数
### 2.2 市场宽度
```

这会让日报编号不一致。

---

### 4.2 修改规则

新增 T+1 模块后，所有后续主章节顺延，内部小标题也必须同步顺延。

例如：

```markdown
## 3. 市场状态

### 3.1 大盘指数
### 3.2 市场宽度
```

而不是：

```markdown
## 3. 市场状态

### 2.1 大盘指数
### 2.2 市场宽度
```

---

### 4.3 需要检查的章节

请全局检查 `report_renderer.py` 中所有硬编码章节号。

重点检查：

```text
市场状态
弱市不做检查
市场资金流向
短线情绪周期
主线分析
风险提示
机会观察
观察池
交易计划摘要
明日验证清单
数据可信度
```

如果主章节已经从：

```text
2 → 3
3 → 4
4 → 5
...
```

内部小标题也要同步。

---

### 4.4 验收标准

日报中不能出现这种错位：

```text
## 3. 市场状态
### 2.1 大盘指数
```

应为：

```text
## 3. 市场状态
### 3.1 大盘指数
```

同理：

```text
## 9. 风险提示
### 9.1 市场风险
### 9.2 板块风险
### 9.3 观察池风险
### 9.4 数据风险
```

---

## 5. 允许修改文件

本轮只允许修改：

```text
analysis/evaluation_report_reader.py
analysis/report_renderer.py
```

如果确实需要，也可以小改：

```text
analysis/daily_report.py
```

但原则上这轮不需要动：

```text
entrypoint.sh
scripts/report_with_evaluation_entrypoint.sh
analysis/email_sender.py
analysis/watchlist_evaluation.py
analysis/selector.py
analysis/trade_plan.py
sql/schema.sql
```

---

## 6. 不允许的改动

本轮不允许：

```text
重新计算 T+1
修改 evaluation 计算逻辑
修改 evaluation 表结构
修改 selector
修改 trade_plan
修改邮件附件逻辑
调整 crontab
新增行情 API
改变日报观察池分层
```

---

## 7. 验收命令

### 7.1 编译

```bash
python -m compileall analysis
```

必须通过。

---

### 7.2 跑统一链路

```bash
TRADE_DATE=20260605 bash scripts/report_with_evaluation_entrypoint.sh
```

必须满足：

```text
1. entrypoint.sh 正常生成基础产物；
2. evaluation_entrypoint.sh 尝试运行；
3. daily_report.py 重新渲染；
4. email_sender.py 只发送一次；
5. 邮件附件仍只有 daily_report_20260605.md 和 board_trend_tracker_20260605.xlsx。
```

---

### 7.3 T+1 模块验收

日报必须出现：

```text
## 1. 昨日观察池兑现复盘（T+1）
```

根据 evaluation 状态：

```text
missing → 显示“尚未生成”
defer → 显示“行情缓存不足暂缓”
insufficient → 显示“覆盖不足，暂不下结论”
partial → 显示“覆盖率偏低，结果仅供观察”
ok → 显示完整 T+1 摘要
```

---

### 7.4 口径验收

日报中不应出现：

```text
coverage_1d < 80% 就直接写“暂缓”
风险提示有效
```

应出现：

```text
覆盖率偏低，结果仅供观察
风险预警
```

---

### 7.5 编号验收

日报中不应出现：

```text
## 3. 市场状态
### 2.1 大盘指数
```

应为：

```text
## 3. 市场状态
### 3.1 大盘指数
```

---

## 8. 提交建议

```bash
git add analysis/evaluation_report_reader.py analysis/report_renderer.py
git commit -m "fix: refine t1 evaluation recap status display"
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

## 9. 最终通过标准

本轮完成后，T+1 模块应达到：

```text
1. 不把低覆盖率误判为 defer；
2. defer / insufficient / partial / ok 展示口径清楚；
3. partial 结果只作为观察，不给强结论；
4. evaluated_1d = 0 时不展示胜率和平均收益；
5. 风险字段改为“风险预警”；
6. 章节编号一致；
7. 不影响日报主体生成；
8. 不影响邮件附件收敛；
9. 不改 evaluation 计算逻辑。
```


# V4 Evaluation Cache Readiness Hotfix：按观察池覆盖率判断 T+1 是否可评价

## 0. 背景

当前 `evaluation_entrypoint.sh` 在 scheduler check 阶段返回：

```text
status=defer
signal_date=20260604
price cache not ready
```

进一步检查发现：

```sql
SELECT trade_date, COUNT(DISTINCT code)
FROM stock_hist_kline
WHERE trade_date IN ('20260604','20260605')
GROUP BY trade_date;
```

结果类似：

```text
2026-06-04    188
2026-06-05     19
```

这说明 `stock_hist_kline` 不是全市场日线缓存，而是部分股票的历史 K 线缓存。

查看 `analysis/data_fetcher.py` 后确认：

```python
get_stock_history(code, days=80)
```

是**单只股票级缓存逻辑**：

```text
1. 先从 stock_hist_kline 查单只股票历史 K 线；
2. 不够再从新浪/腾讯 API 拉该股票历史；
3. 拉到后写入 stock_hist_kline；
4. stock_hist_kline 只会保存被访问过的股票。
```

因此，不能用 `stock_hist_kline` 的全市场覆盖率来判断 T+1 evaluation 是否可运行。

---

## 1. 本轮目标

将 `evaluation_scheduler_check` 的 price cache readiness 口径从：

```text
全市场 stock_hist_kline 覆盖率
```

改为：

```text
昨日观察池股票的 K 线覆盖率
```

也就是说：

```text
T+1 复盘只要求昨日观察池股票有 signal_date 和 as_of_date 的价格；
不要求全市场几千只股票都在 stock_hist_kline 里。
```

---

## 2. 允许修改文件

允许修改：

```text
analysis/evaluation_scheduler_check.py
analysis/evaluation_report_reader.py
scripts/evaluation_entrypoint.sh
```

如有必要，可以小改：

```text
analysis/data_fetcher.py
```

但原则上优先复用现有：

```python
get_stock_history(code, days=80)
```

不允许修改：

```text
analysis/watchlist_evaluation.py
analysis/selector.py
analysis/trade_plan.py
sql/schema.sql
entrypoint.sh
scripts/report_with_evaluation_entrypoint.sh
analysis/email_sender.py
```

---

## 3. 核心设计

### 3.1 readiness 判断对象

从 `stock_signal` 中读取 `signal_date` 的观察池股票。

优先读取：

```sql
SELECT DISTINCT code
FROM stock_signal
WHERE trade_date = %(signal_date)s
```

如果 stock_signal 有分层字段，可以过滤掉不可交易 / 高风险回避，但第一版可以先用所有 signal_date 的 stock_signal 股票。

如果 stock_signal 没有数据，则返回：

```text
status=defer
reason=no_signal_pool
message=未找到昨日观察池，T+1 复盘暂缓。
```

---

### 3.2 readiness 判断所需价格

对每只观察池股票，需要检查：

```text
signal_date 的 close
as_of_date 的 close
```

即至少要在 `stock_hist_kline` 中有：

```sql
(code, signal_date)
(code, as_of_date)
```

如果两天都有，则该股票可评价。

---

### 3.3 缺失时主动补 K 线

如果某些观察池股票缺少 K 线，不要立即 defer。

应该先调用：

```python
from analysis.data_fetcher import get_stock_history
```

对缺失股票逐只补：

```python
get_stock_history(code, days=80)
```

因为 `get_stock_history` 已经会：

```text
查缓存；
API 拉取；
保存到 stock_hist_kline。
```

补完后重新查 `stock_hist_kline` 覆盖率。

---

### 3.4 覆盖率阈值

定义：

```python
total_signals = len(signal_codes)
covered_signals = number of codes having both signal_date and as_of_date close
coverage = covered_signals / total_signals
```

判断：

```python
if total_signals == 0:
    status = "defer"
    reason = "no_signal_pool"

elif covered_signals == 0:
    status = "defer"
    reason = "no_price_coverage"

elif coverage >= 0.8:
    status = "ready"
    reason = "observer_pool_price_ready"

else:
    status = "defer"
    reason = "observer_pool_price_not_ready"
```

这里的 0.8 可以作为默认阈值。

---

## 4. 保留全市场覆盖率作为 diagnostic

可以继续计算全市场 `stock_hist_kline` 覆盖率，但只用于诊断展示，不作为 blocking condition。

例如 scheduler_check 输出：

```json
{
  "status": "ready",
  "signal_date": "20260604",
  "as_of_date": "20260605",
  "price_cache_coverage": 0.92,
  "coverage_scope": "signal_pool",
  "full_market_cache_coverage": 0.01,
  "total_signals": 25,
  "covered_signals": 23,
  "missing_codes": ["xxxxxx", "yyyyyy"]
}
```

注意：

```text
price_cache_coverage 现在应指 observation pool 覆盖率；
full_market_cache_coverage 仅诊断，不阻断。
```

---

## 5. defer 时必须写 status 文件

当前 evaluation defer 时没有写 DB，也没有生成文件，导致日报只能显示：

```text
今日 T+1 复盘尚未生成。
```

本轮需要在 scheduler_check 返回 defer 时生成：

```text
reports/evaluation/evaluation_status_YYYYMMDD.json
```

例如：

```text
reports/evaluation/evaluation_status_20260605.json
```

内容示例：

```json
{
  "available": false,
  "status": "defer",
  "as_of_date": "20260605",
  "signal_date": "20260604",
  "reason": "observer_pool_price_not_ready",
  "message": "今日 T+1 复盘因观察池价格覆盖不足暂缓。",
  "coverage_scope": "signal_pool",
  "price_cache_coverage": 0.42,
  "total_signals": 25,
  "covered_signals": 10,
  "missing_codes": ["xxxxxx", "yyyyyy"]
}
```

---

## 6. evaluation_report_reader 读取 status 文件

`evaluation_report_reader.py` 的读取顺序改为：

```text
1. DB summary；
2. 正式 evaluation result JSON；
3. reports/evaluation/evaluation_status_YYYYMMDD.json；
4. 都没有才 missing。
```

如果读到 status 文件：

```json
{
  "available": false,
  "status": "defer",
  "message": "今日 T+1 复盘因观察池价格覆盖不足暂缓。"
}
```

则 reader 返回：

```python
{
    "available": False,
    "status": "defer",
    "message": "今日 T+1 复盘因观察池价格覆盖不足暂缓。",
    ...
}
```

日报显示 defer，而不是 missing。

---

## 7. evaluation_entrypoint 行为

如果 scheduler_check 返回：

```text
status=ready
```

继续执行 evaluation。

如果 scheduler_check 返回：

```text
status=defer
```

则：

```text
1. 写 evaluation_status_YYYYMMDD.json；
2. 打印 defer 原因；
3. 正常退出 0；
4. 不发送 evaluation 邮件；
5. 不阻断 report_with_evaluation_entrypoint.sh。
```

---

## 8. 日报显示口径

如果 status 文件显示：

```text
reason=observer_pool_price_not_ready
```

日报 T+1 模块显示：

```markdown
## 1. 昨日观察池兑现复盘（T+1）

今日 T+1 复盘因观察池价格覆盖不足暂缓。  
当前不对昨日观察池表现下结论。
```

如果 reason 是：

```text
no_signal_pool
```

显示：

```markdown
未找到昨日观察池，今日 T+1 复盘暂缓。
```

---

## 9. 验收命令

### 9.1 编译

```bash
python -m compileall analysis
```

---

### 9.2 单跑 scheduler/evaluation

```bash
AS_OF_DATE=20260605 SEND_EVAL_EMAIL=0 bash scripts/evaluation_entrypoint.sh
```

期望：

```text
如果观察池价格覆盖率 >= 80%，status=ready，并继续 evaluation；
如果覆盖率不足，status=defer，并生成 evaluation_status_20260605.json。
```

---

### 9.3 检查 status 文件

```bash
cat reports/evaluation/evaluation_status_20260605.json
```

应该包含：

```text
status
as_of_date
signal_date
reason
message
coverage_scope
price_cache_coverage
total_signals
covered_signals
missing_codes
```

---

### 9.4 检查是否补齐观察池 K 线

```sql
SELECT trade_date, COUNT(DISTINCT code)
FROM stock_hist_kline
WHERE trade_date IN ('20260604','20260605')
GROUP BY trade_date
ORDER BY trade_date;
```

这里不要求达到全市场几千只，但应该比之前的 188 / 19 增加，至少覆盖昨日观察池股票。

进一步检查观察池覆盖：

```sql
SELECT COUNT(DISTINCT s.code) AS total_signals
FROM stock_signal s
WHERE s.trade_date = '20260604';

SELECT COUNT(DISTINCT s.code) AS covered_signals
FROM stock_signal s
JOIN stock_hist_kline k1
  ON s.code = k1.code AND k1.trade_date = '2026-06-04'
JOIN stock_hist_kline k2
  ON s.code = k2.code AND k2.trade_date = '2026-06-05'
WHERE s.trade_date = '20260604';
```

注意：如果 `stock_signal.trade_date` 是 `YYYYMMDD`，而 `stock_hist_kline.trade_date` 是 `YYYY-MM-DD`，SQL 中要对应处理。

---

### 9.5 统一链路验收

```bash
TRADE_DATE=20260605 bash scripts/report_with_evaluation_entrypoint.sh
```

必须满足：

```text
1. entrypoint 产物生成；
2. evaluation 不再因为全市场 cache 少而直接 defer；
3. 如果观察池覆盖够，evaluation 落库；
4. daily_report 显示 T+1 摘要；
5. 如果观察池覆盖仍不够，daily_report 显示“观察池价格覆盖不足暂缓”；
6. 邮件只发一次；
7. 附件仍只有 daily_report_YYYYMMDD.md 和 board_trend_tracker_YYYYMMDD.xlsx。
```

---

## 10. 不允许的结果

本轮不允许：

```text
1. 因全市场 stock_hist_kline 覆盖不足直接 defer；
2. defer 后没有 status 文件；
3. daily_report 仍显示“尚未生成”，但实际是 scheduler defer；
4. daily_report 重新计算 T+1；
5. evaluation 失败阻断日报；
6. 邮件附件重新变多；
7. 改动 selector / trade_plan / evaluation 计算逻辑。
```

---

## 11. 提交建议

```bash
git add analysis/evaluation_scheduler_check.py analysis/evaluation_report_reader.py scripts/evaluation_entrypoint.sh
git commit -m "fix: evaluate t1 readiness by signal pool coverage"
git push origin dev
```

如果额外改了 data_fetcher：

```bash
git add analysis/data_fetcher.py
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

## 12. 最终通过标准

本轮完成后，应达到：

```text
1. T+1 readiness 按昨日观察池覆盖率判断；
2. stock_hist_kline 不需要全市场完整缓存；
3. 缺失观察池股票会尝试 get_stock_history(code) 补齐；
4. 覆盖率够则 evaluation 正常跑；
5. 覆盖率不够则 defer，并写 status 文件；
6. 日报能准确显示 ready / defer / missing；
7. 不改变 evaluation 实际评价算法。
```


# V4 T+1 Recap Three-Tier Fallback：正式复盘 / 快照复盘 / 暂缓

## 0. 本轮目标

当前 T+1 evaluation 已经接入日报，但由于 `stock_hist_kline` 不是全市场日线缓存，而是单股按需缓存，部分股票上游 K 线只更新到较早日期，导致正式 T+1 evaluation 经常因 K 线覆盖不足 defer。

本轮目标是将 T+1 复盘改成三档：

```text
A. 正式复盘：
   stock_hist_kline 覆盖率 ≥ 80%
   输出胜率、平均收益、Top/Bottom

B. 快照复盘：
   K 线覆盖率不足，但当日快照覆盖率 ≥ 80%
   输出股票今日涨跌、量价、结果
   标记为“降级口径，仅供观察”

C. 暂缓：
   K 线和快照都不足
   不输出胜率，不下结论
```

核心原则：

```text
正式 evaluation 仍然只用 stock_hist_kline；
快照复盘只用于日报展示降级；
快照复盘不写入正式 evaluation 统计；
快照复盘不改变 selector / trade_plan / watchlist_evaluation 计算逻辑；
```

---

## 1. 当前问题

当前流程是：

```text
evaluation_scheduler_check
→ 检查昨日观察池股票在 stock_hist_kline 中 signal_date / as_of_date 的价格覆盖
→ 覆盖率不足则 defer
→ daily_report 显示 T+1 暂缓
```

这个逻辑是严格的，但会造成：

```text
如果 K 线上游滞后，T+1 完全没有结果。
```

但实际上日报当天已经能拿到当日行情快照，包括：

```text
close
pct_chg
amount
volume_ratio
turnover
```

所以在正式 K 线不足时，可以用当日快照做一个“降级复盘”。

---

## 2. 三档状态设计

### A. 正式复盘

触发条件：

```text
stock_hist_kline 中昨日观察池股票覆盖率 ≥ 80%
```

展示内容：

```text
胜率
平均次日收益
表现较好 Top 3
表现较弱 Bottom 3
分层倒挂
风险预警
结论等级
```

状态字段建议：

```json
{
  "available": true,
  "status": "ok",
  "recap_mode": "official",
  "message": null
}
```

日报标题建议：

```markdown
## 1. 昨日观察池兑现复盘（T+1）
```

---

### B. 快照复盘

触发条件：

```text
stock_hist_kline 覆盖率 < 80%
但当日行情快照覆盖率 ≥ 80%
```

展示内容：

```text
股票
昨日层级
今日涨跌
量价表现
结果
```

明确标注：

```text
降级口径，仅供观察
```

状态字段建议：

```json
{
  "available": true,
  "status": "snapshot",
  "recap_mode": "snapshot",
  "message": "K线覆盖不足，使用当日行情快照生成降级复盘，仅供观察。"
}
```

日报标题仍然用：

```markdown
## 1. 昨日观察池兑现复盘（T+1）
```

但模块开头必须提示：

```markdown
> K 线覆盖率不足，本段使用当日行情快照生成降级复盘，仅供观察，不计入正式 evaluation 统计。
```

---

### C. 暂缓

触发条件：

```text
stock_hist_kline 覆盖率 < 80%
且当日快照覆盖率 < 80%
```

展示内容：

```text
不输出胜率
不输出平均收益
不输出强结论
只说明暂缓原因和覆盖率
```

状态字段建议：

```json
{
  "available": false,
  "status": "defer",
  "recap_mode": "defer",
  "reason": "price_coverage_not_ready",
  "message": "今日 T+1 复盘因价格覆盖不足暂缓。"
}
```

---

## 3. 快照复盘的数据来源

快照复盘优先读取当天已生成的数据，不新增外部 API。

优先级：

```text
1. daily_summary_YYYYMMDD.json 中的候选/市场快照字段；
2. stock_signal 中 as_of_date 的行情字段；
3. data_fetcher 当日全市场行情快照；
4. 如果以上都不足，则 defer。
```

建议第一版优先用数据库中已有的 `stock_signal` 或当日行情快照。

需要字段：

```text
code
name
close
pct_chg
amount
volume_ratio
turnover
```

如果 `volume_ratio` 缺失，则量价表现可以降级为：

```text
量价数据不足
```

---

## 4. 快照复盘的匹配对象

快照复盘评价对象仍然是：

```text
signal_date 的昨日观察池股票
```

不要评价今天新生成的观察池。

读取对象：

```sql
SELECT DISTINCT code, name, layer, strategy
FROM stock_signal
WHERE trade_date = %(signal_date)s
```

如果有 trade_plan 分层结果，也可以优先使用昨日 trade_plan 的分层：

```text
候选低吸
只观察
交易条件不满足
高风险回避
不可交易过滤
```

第一版可以只取昨日 `stock_signal` 的 layer / risk_level / action_signal 映射。

---

## 5. 快照覆盖率判断

定义：

```python
snapshot_total = len(signal_codes)
snapshot_covered = number of signal_codes found in as_of_date snapshot with pct_chg not null
snapshot_coverage = snapshot_covered / snapshot_total
```

判断：

```python
if kline_coverage >= 0.8:
    recap_mode = "official"

elif snapshot_coverage >= 0.8:
    recap_mode = "snapshot"

else:
    recap_mode = "defer"
```

---

## 6. 快照复盘结果分类规则

快照复盘不计算正式收益，只展示当日表现。

可以基于 `pct_chg` 给结果标签：

```python
if pct_chg >= 10:
    result = "✅ 暴涨"
elif pct_chg >= 5:
    result = "✅ 大涨"
elif pct_chg >= 2:
    result = "✅ 走强"
elif pct_chg > -2:
    result = "➖ 震荡"
elif pct_chg > -5:
    result = "⚠️ 走弱"
else:
    result = "❌ 大跌"
```

量价表现建议：

```python
if volume_ratio is None:
    volume_note = "量价数据不足"
elif volume_ratio >= 3:
    volume_note = f"{volume_ratio:.1f}x放量过强"
elif volume_ratio >= 1.3:
    volume_note = f"{volume_ratio:.1f}x健康放量"
elif volume_ratio >= 0.8:
    volume_note = f"{volume_ratio:.1f}x正常"
else:
    volume_note = f"{volume_ratio:.1f}x缩量"
```

如果今日涨幅大但量比极高，可以显示：

```text
涨停但放量过强
```

如果今日涨幅为负且量比高，可以显示：

```text
放量分歧
```

---

## 7. 快照复盘展示样式

建议展示成：

```markdown
## 1. 昨日观察池兑现复盘（T+1）

> K 线覆盖率不足，本段使用当日行情快照生成降级复盘，仅供观察，不计入正式 evaluation 统计。

| 项目 | 结果 |
|------|------|
| 信号日期 | 2026-06-04 |
| 评价日期 | 2026-06-05 |
| 昨日观察池数量 | 56 |
| 快照覆盖数量 | 52 |
| 快照覆盖率 | 92.9% |
| K线覆盖率 | 68.0% |
| 复盘口径 | 快照复盘（降级） |

### 表现较好

| 股票 | 昨日层级 | 今日涨跌 | 量价 | 结果 |
|------|----------|----------|------|------|
| 亨通光电 | 候选低吸 | +7.04% | 1.5x健康放量 | ✅ 大涨 |
| 华特气体 | 候选低吸 | +15.50% | 1.6x健康放量 | ✅ 暴涨 |
| 模塑科技 | 只观察 | +7.36% | 1.8x健康放量 | ✅ 大涨 |

### 表现较弱

| 股票 | 昨日层级 | 今日涨跌 | 量价 | 结果 |
|------|----------|----------|------|------|
| 迅捷兴 | 只观察 | -3.34% | 1.2x正常 | ⚠️ 走弱 |
| 源杰科技 | 候选低吸 | -2.21% | 0.9x正常 | ⚠️ 走弱 |
| 国机精工 | 只观察 | -1.40% | 1.4x健康放量 | ➖ 震荡 |
```

---

## 8. 注意：快照复盘不要输出正式胜率

快照复盘可以展示：

```text
表现较好数量
表现较弱数量
快照覆盖率
```

但不建议第一版输出：

```text
正式胜率
平均次日收益
正式结论等级
```

如果要展示类似胜率，也必须叫：

```text
快照走强占比
```

不要叫：

```text
次日胜率
```

推荐第一版不放胜率，避免和正式 evaluation 混淆。

---

## 9. 推荐新增 helper

可以新增：

```text
analysis/evaluation_snapshot_recap.py
```

职责：

```text
在正式 evaluation 不可用时，读取昨日观察池和今日行情快照，生成降级复盘数据。
```

函数：

```python
def build_snapshot_t1_recap(signal_date: str, as_of_date: str) -> dict:
    """
    返回：
    {
        "available": True/False,
        "status": "snapshot" / "missing",
        "recap_mode": "snapshot",
        "signal_date": "...",
        "as_of_date": "...",
        "total_signals": int,
        "snapshot_covered": int,
        "snapshot_coverage": float,
        "kline_coverage": float or None,
        "top_winners": [...],
        "top_losers": [...],
        "message": "...",
    }
    """
```

`evaluation_report_reader.py` 可以这样用：

```python
official = load_official_evaluation(...)
if official available:
    return official

status = load_evaluation_status(...)
if status reason is kline coverage insufficient:
    snapshot = build_snapshot_t1_recap(...)
    if snapshot available and snapshot_coverage >= 0.8:
        return snapshot
    return status

return missing
```

---

## 10. evaluation_status 文件建议保留

即使走快照复盘，也保留 evaluation status 文件，用于说明正式复盘为什么没有跑：

```json
{
  "status": "defer",
  "reason": "observer_pool_price_not_ready",
  "price_cache_coverage": 0.68,
  "message": "正式 T+1 复盘因 K 线覆盖不足暂缓。"
}
```

日报中可以展示：

```text
正式 T+1 复盘因 K 线覆盖不足暂缓，以下为快照复盘。
```

---

## 11. 不允许的改动

本轮不允许：

```text
1. 降低正式 evaluation 的 80% K 线覆盖率阈值；
2. 用快照数据写入正式 evaluation 表；
3. 把快照复盘当作正式胜率；
4. 修改 selector；
5. 修改 trade_plan；
6. 修改 watchlist_evaluation 的正式计算逻辑；
7. 修改数据库结构。
```

---

## 12. 允许修改文件

允许新增：

```text
analysis/evaluation_snapshot_recap.py
```

允许修改：

```text
analysis/evaluation_report_reader.py
analysis/report_renderer.py
```

如果需要读取更多字段，可小改：

```text
analysis/evaluation_scheduler_check.py
```

但不要改正式 evaluation 计算逻辑。

---

## 13. 验收场景

### 场景 A：正式复盘

条件：

```text
K 线覆盖率 ≥ 80%
```

日报显示：

```text
正式 T+1 摘要
次日胜率
平均次日收益
表现较好 / 表现较弱
```

### 场景 B：快照复盘

条件：

```text
K 线覆盖率 < 80%
快照覆盖率 ≥ 80%
```

日报显示：

```text
K 线覆盖不足，本段使用当日行情快照生成降级复盘，仅供观察。
```

并展示：

```text
股票
昨日层级
今日涨跌
量价
结果
```

不得展示为正式胜率。

### 场景 C：暂缓

条件：

```text
K 线覆盖率 < 80%
快照覆盖率 < 80%
```

日报显示：

```text
今日 T+1 复盘因价格覆盖不足暂缓。
当前不对昨日观察池表现下结论。
```

---

## 14. 验收命令

```bash
python -m compileall analysis
```

单独跑 evaluation：

```bash
AS_OF_DATE=20260605 SEND_EVAL_EMAIL=0 bash scripts/evaluation_entrypoint.sh
```

重渲染日报：

```bash
python -m analysis.daily_report --date 20260605 --mode both
```

完整链路：

```bash
TRADE_DATE=20260605 bash scripts/report_with_evaluation_entrypoint.sh
```

在服务器上请用 Docker 运行：

```bash
TRADE_DATE=20260605 docker compose run --rm --entrypoint /bin/bash stock-report scripts/report_with_evaluation_entrypoint.sh
```

---

## 15. 最终通过标准

本轮完成后，T+1 模块应满足：

```text
1. K 线足够时，输出正式复盘；
2. K 线不足但快照足够时，输出快照复盘；
3. 快照复盘明确标记“降级口径，仅供观察”；
4. 快照复盘不写正式 evaluation 表；
5. 快照复盘不输出正式胜率；
6. K 线和快照都不足时，明确暂缓；
7. 日报不再因为 K 线源滞后而完全没有 T+1 信息；
8. 不改变 selector / trade_plan / 正式 evaluation 计算逻辑。
```
