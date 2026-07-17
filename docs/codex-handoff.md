# Codex 交接同步文件

## 项目信息

- 项目名称：stock-ai-system
- 本地路径：D:\code\stock-ai-system
- 服务器路径：/root/stock-ai-system
- 开发分支：dev
- 部署分支：main
- 主要技术栈：Python / Docker / MySQL
- 最近提交：4a6c2cf 完善纠偏效果统计与日报展示

## 当前目标

- 日报系统持续优化：观察池、T+1 evaluation、纠偏效果、学习样本，为后续 ML 做准备。

## 本轮改动范围

- 修改模块：
  -
- 新增模块：
  -
- 删除或废弃模块：
  -
- 是否涉及 SQL：否 / 是，脚本：
- 是否涉及 crontab：否 / 是，说明：

## 当前状态

- 本地分支：
- 是否已推送 dev：
- 是否已合并 main：
- 服务器是否已 pull：
- 今日是否已跑日报：
- 当前做到哪里：
- 是否有未提交改动：

## 已完成

-

## 正在处理

-

## 待处理

-

## 待验证

-

## 数据与表结构

- 新增表：
- 修改表：
- 需要手动执行 SQL：
- 关键数据文件：
  - reports/daily/
  - reports/evaluation/
  - reports/ml_dataset/

## 关键文件

- analysis/daily_report.py
- analysis/report_renderer.py
- analysis/trade_plan.py
- analysis/correction_effectiveness.py
- analysis/ml_dataset_builder.py
- scripts/report_with_evaluation_entrypoint.sh
- scripts/evaluation_entrypoint.sh

## 关键命令

### 本地验证

```bash
python -m analysis.correction_regression_check
python -m analysis.trade_plan_regression_check
python -m analysis.correction_effectiveness_regression_check
python -m analysis.ml_dataset_builder --as-of YYYYMMDD --min-coverage 0.9
```

### 查看最近 evaluation

```bash
python -m analysis.evaluation_query --days 5
```

### 服务器日报链路

```bash
cd /root/stock-ai-system
docker compose run --rm --entrypoint /bin/bash -e EVAL_TIME_BUDGET=1800 -e EVAL_DEEP=1 stock-report scripts/report_with_evaluation_entrypoint.sh
```

### 单独跑 evaluation 检查

```bash
cd /root/stock-ai-system
docker compose run --rm --entrypoint python -e EVAL_TIME_BUDGET=1800 -e EVAL_DEEP=1 stock-report -m analysis.evaluation_scheduler_check --as-of $(date +%Y%m%d) --time-budget 1800 --deep --json
```

### Git 同步

```bash
git status -sb
git log -1 --oneline
git pull origin dev
git push origin dev
```

## 环境说明

- Python：
- Docker：
- 数据库：
- 服务器 cron：
- 其他依赖：

## 验证结论

- 最近日报日期：
- T+1 覆盖率：
- 学习样本状态：
- 纠偏效果：
- 是否可用于日报阅读：
- 是否可用于 ML 样本：

## 已知问题

-

## 注意事项

- 不要直接在 main 开发。
- 服务器只部署 main，dev 测试通过后再合并。
- 观察池、evaluation、ML 数据要看覆盖率，不要只看是否生成文件。
- 报告里的旧快照可能滞后，必要时以 DB 最新 evaluation 为准。
- 本文件只记录接手必需信息，不写完整开发流水账。

## 下次 Codex 接手入口

1. 先读本文件。
2. 再看最近日报：C:\Users\hsoluo\Downloads\daily_report_YYYYMMDD.md
3. 再跑：

```bash
git status -sb
git log -1 --oneline
python -m analysis.evaluation_query --days 5
```

4. 如果要改代码，优先看：
   - analysis/daily_report.py
   - analysis/report_renderer.py
   - analysis/trade_plan.py
   - analysis/correction_effectiveness.py
   - analysis/ml_dataset_builder.py

## 更新时间

- 更新时间：
- 更新电脑：
- 更新人：
