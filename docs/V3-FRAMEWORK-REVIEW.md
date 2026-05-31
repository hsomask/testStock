# V3-Stabilization 第 4 轮 Review：代码框架梳理

## 1. 总体结论

当前框架基本清楚，主链路、数据流、产物链已闭环。不建议立即大重构。

## 2. 当前目录结构

```
analysis/
  ├── 主链路 (10 个文件)
  │   ├── daily_report.py          ← 主入口 (~400行)
  │   ├── report_renderer.py       ← 报告渲染 (~900行)
  │   ├── selector.py              ← 6 策略 + 过滤
  │   ├── email_sender.py          ← 邮件推送
  │   ├── pipeline_check.py        ← 流程检查
  │   ├── board_history.py         ← 板块成交占比
  │   ├── board_trend_tracker.py   ← 板块趋势追踪 (~800行)
  │   ├── board_mapping_quality.py ← 映射质量检查
  │   ├── market.py                ← 市场评分
  │   └── theme_detector.py        ← 主线判断
  ├── 数据层
  │   ├── data_fetcher.py          ← 行情/历史K线 (~700行)
  │   ├── data_quality.py          ← 数据质量检查
  │   └── data_sources/            ← 腾讯/同花顺适配
  ├── 业务模块
  │   ├── trade_plan.py            ← 交易计划
  │   ├── account_filter.py        ← 账户过滤
  │   ├── board_alias*.py          ← 板块名称归一
  │   ├── stock_board_mapper.py    ← 个股-板块映射
  │   ├── signal_tracker.py        ← 信号追踪
  │   └── backtest_report.py       ← 回测报告
  ├── 工具
  │   ├── utils.py                 ← 格式化+日期转换
  │   └── init_db.py               ← 数据库初始化
  ├── context/                     ← V3-Stabilization 新建
  ├── renderers/                   ← 占位
  └── common/                      ← 占位
```

## 3. 当前主链路

```
entrypoint.sh
 → analysis.init_db
 → analysis.board_history --date
 → analysis.board_mapping_quality --date
 → analysis.board_trend_tracker --date
 → analysis.daily_report --mode both --date
 → analysis.pipeline_check --date
 → analysis.signal_tracker
 → analysis.backtest_report
 → analysis.email_sender --date
```

## 4. 核心文件职责表

| 文件 | 职责 | 主链路 | 行数 | 建议 |
|------|------|--------|------|------|
| daily_report.py | 数据获取→分析→选股→报告生成 | ✅ | ~400 | 拆分数据获取和报告协调 |
| report_renderer.py | 小白版+专业版+AI提示词+板块表 | ✅ | ~900 | 拆 beginner/pro 渲染器 |
| selector.py | 6策略+公共过滤 | ✅ | ~600 | 可接受，不动 |
| email_sender.py | 邮件组装+发送+附件收集 | ✅ | ~300 | 可接受，不动 |
| pipeline_check.py | 11项文件完整性检查 | ✅ | ~70 | 可接受，不动 |
| board_trend_tracker.py | 趋势追踪+生命周期+MD+Excel+JSON | ✅ | ~800 | 拆 metrics 计算和渲染输出 |
| board_mapping_quality.py | 板块映射质量检查+alias报告 | ✅ | ~250 | 可接受，不动 |
| board_history.py | 板块成交占比写入DB | ✅ | ~330 | 可接受，不动 |
| market.py | 市场综合评分+宽度状态 | ✅ | ~100 | 可接受，不动 |
| theme_detector.py | 主线三分+风险方向 | ✅ | ~250 | 可接受，不动 |
| data_fetcher.py | 个股行情+历史K线+MACD+板块 | ✅ | ~700 | 拆 history/spot/indicators |
| utils.py | fmt_num/pct + to_ymd/to_date_display | - | ~40 | 移到 common/ |

## 5. 数据流

```
东方财富 push2delay → data_fetcher.py → analyze market/board/sentiment
                                          ↓
                    board_history.py → board_amount_ratio (DB)
                                          ↓
                    board_mapping_quality.py → quality MD/JSON
                    board_trend_tracker.py → trend MD/Excel/JSON
                                          ↓
                    selector.py → 观察池 + stock_signal (DB)
                                          ↓
                    theme_detector.py → 主线判断
                                          ↓
                    daily_report.py → beginner/pro MD + summary JSON
                                          ↓
                    trade_plan.py → trade_plan JSON/MD
                                          ↓
                    pipeline_check.py → pipeline JSON
                                          ↓
                    email_sender.py → 邮件(含附件)
```

## 6. 产物流

| 产物 | 生成模块 | 消费模块 | critical |
|------|---------|---------|----------|
| daily_report_YYYYMMDD.md | daily_report | email_sender, 用户 | ✅ |
| daily_report_YYYYMMDD_pro.md | daily_report | email_sender, 用户 | ✅ |
| daily_summary_YYYYMMDD.json | daily_report | email_sender | ✅ |
| trade_plan_YYYYMMDD.md | trade_plan | email_sender | ✅ |
| trade_plan_YYYYMMDD.json | trade_plan | email_sender | ✅ |
| board_trend_report_YYYYMMDD.md | board_trend_tracker | 用户 | - |
| board_trend_tracker_YYYYMMDD.xlsx | board_trend_tracker | email_sender | - |
| board_trend_summary_YYYYMMDD.json | board_trend_tracker | daily_report | ✅ |
| board_mapping_quality_YYYYMMDD.md | board_mapping_quality | email_sender | ✅ |
| board_mapping_quality_YYYYMMDD.json | board_mapping_quality | email_sender | ✅ |
| board_alias_report_YYYYMMDD.md | board_mapping_quality | email_sender | - |
| pipeline_check_YYYYMMDD.json | pipeline_check | email_sender | ✅ |

## 7. 职责边界问题

| 边界 | 判断 | 问题 |
|------|------|------|
| entrypoint 是否只负责调度 | ✅ | 清晰，11步顺序明确 |
| daily_report 是否过重 | ⚠️ | 含数据获取/分析/选股/报告/DB写入 |
| report_renderer 是否只负责渲染 | ⚠️ | 含AI提示词、板块表、观察池、N种格式 |
| selector 是否只负责观察池 | ✅ | 6策略 + 公共过滤，范围可控 |
| pipeline_check 是否只负责检查 | ✅ | 11项文件检查，职责单一 |
| email_sender 是否只负责发送 | ✅ | 组装+附件+发送，不含业务逻辑 |
| utils 是否变成杂物间 | ⚠️ | fmt_num/pct + to_ymd/to_date_display 杂混 |
| board_trend_tracker 是否过重 | ⚠️ | 指标计算+6状态+生命周期+MD+Excel+JSON |

## 8. 后续优化优先级

### P0：无（当前无阻断性 bug）

### P1：结构收敛（建议下一轮开始）
- daily_report.py 过重：拆出数据获取协调层
- report_renderer.py 过重：拆 beginner_renderer / pro_renderer
- data_fetcher.py 过重：拆 history_cache / spot / indicators
- utils.py 杂物化：fmt 移到 common/

### P2：以后再做
- board_trend_tracker 拆 metrics / renderer
- PRD 归档
- report_context 真正消费
- 报告可读性优化

## 9. 目标架构建议（暂不迁移）

```
analysis/
  │
  ├── context/              ← field_dictionary + report_context
  ├── data_sources/         ← 腾讯/同花顺/未来数据源适配
  ├── boards/               ← board_history, board_trend_tracker, board_mapping_quality
  ├── selectors/            ← selector, trade_plan, account_filter
  ├── renderers/            ← beginner_report, pro_report, email_body
  ├── common/               ← 日期/文件/fmt 工具
  │
  ├── daily_report.py       ← 协调层（变薄）
  ├── pipeline_check.py     ← 产物检查
  └── email_sender.py       ← 邮件发送
```

## 10. 下一轮建议

优先做 P1-1：**daily_report.py 提取公共函数**，把 ~400 行减到 ~200 行，不改输出。
