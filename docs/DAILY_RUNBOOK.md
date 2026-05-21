# 每日运行手册

## 运行顺序

| 顺序 | 命令 | 频率 | 条件 | 说明 |
|------|------|------|------|------|
| 1 | `python -m analysis.stock_board_mapper` | 每周一 | 无 | 更新个股-板块映射表，约30分钟 |
| 2 | `python -m analysis.board_history` | 每天 | 收盘后(15:00+) | 写入当日板块成交占比，积累历史数据 |
| 3 | `python -m analysis.daily_report --mode both --force` | 每天 | 收盘后(15:00+)，步骤2之后 | 一次生成两份报告+summary JSON+stock_signal |
| 4 | `python -m analysis.email_sender` | 每天 | 步骤3之后 | 邮件推送，自动读取summary JSON |

## 为什么是这个顺序

1. **stock_board_mapper 必须先跑**：board_history 和 daily_report 都依赖 stock_board_map 表来计算板块成交额和板块联动。空表时这些功能降级。
2. **board_history 在 daily_report 之前**：daily_report 需要读取 board_amount_ratio 的历史数据来展示成交占比变化。每多跑一天，可展示 3日/5日变化的数据就多一天。
3. **daily_report 收盘后跑**：开盘前 API 返回空数据，盘中数据不完整，收盘后数据最全。
4. **email_sender 最后**：依赖 daily_report 生成的 summary JSON 和 markdown 报告。

## Docker 方式（服务器）

```bash
# 每周一早 9:00
docker compose run --rm stock-mapper

# 每天 21:00
docker compose run --rm stock-report
```

crontab：
```
0 9 * * 1 cd /path/to/stock-ai-system && docker compose run --rm stock-mapper >> /var/log/stock-mapper.log 2>&1
0 21 * * * cd /path/to/stock-ai-system && docker compose run --rm stock-report >> /var/log/stock-report.log 2>&1
```

## entrypoint.sh 流程

```
init_db → board_history → daily_report --mode both --force → email_sender
```

## 数据积累周期

| 表 | 首次 | 之后 | 累积到正常的天数 |
|---|------|------|-----------------|
| stock_board_map | 全量回填 ~30min | 每周增量 | 首次即完整 |
| board_amount_ratio | 1天 | 每天+1条 | 3天后可看3日变化，5天后可看5日变化 |
| stock_hist_kline | 1200只回填 ~20min | 每天增量秒级 | 首次即覆盖候选池 |
| stock_signal | 每天25条 | 每天累积 | 首次即有数据 |

## 首次部署检查

```bash
python -m analysis.preflight_check    # 环境检查
python -m analysis.init_db            # 建表
python -m analysis.stock_board_mapper  # 回填板块映射
```

## 常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| 数据全0 | 还没开盘 | 等9:30后或收盘后重跑 |
| 板块只有100个 | 旧版无分页 | 已修复(496行业/486概念) |
| 数据库连接失败 | 长流程超时断开 | 已修复(自动重连) |
| 板块成交占比暂缺 | board_history 还没积累够天数 | 每天跑 board_history，3天后正常 |
| 均线大量缺失 | 全市场5000+只，只补1200只候选 | 正常，观察池覆盖率96%即可 |
