# V3-Stabilization 部署前总验收清单

## 1. 拉取 dev

```bash
git checkout dev
git pull origin dev
git status --short
git log -8 --oneline
```

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
- status = ok 或 warning
- critical_missing = []
- has_critical_missing = false

## 5. regression 检查

```bash
python -m analysis.report_regression_check --date 20260528
cat reports/daily/report_regression_check_20260528.json
```

验收标准：
- errors = []
- 最好 warnings = []

## 6. 关键产物检查

```bash
ls -lh reports/daily/*20260528*
```

至少包含：
- daily_report_20260528.md
- daily_report_20260528_pro.md
- daily_summary_20260528.json
- trade_plan_20260528.md
- trade_plan_20260528.json
- board_trend_summary_20260528.json
- board_mapping_quality_20260528.json
- pipeline_check_20260528.json
- report_regression_check_20260528.json

## 7. Git 污染检查

```bash
git status --short --untracked-files=all
```

不得提交：
- reports/
- __pycache__/
- .claude/
- .env
- 本地 PRD 迭代日志

## 8. 合 main

```bash
git checkout main
git pull origin main
git merge dev
python -m compileall analysis
git push origin main
```
