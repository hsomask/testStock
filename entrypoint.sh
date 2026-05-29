#!/bin/bash
set -e

TRADE_DATE=$(date +%Y%m%d)
echo "=== 交易日：$TRADE_DATE ==="

echo "=== 初始化数据库 ==="
python -m analysis.init_db

echo "=== 更新板块成交占比 ==="
python -m analysis.board_history --date "$TRADE_DATE"

echo "=== 板块映射质量检查 ==="
python -m analysis.board_mapping_quality --date "$TRADE_DATE" || echo "[警告] 板块映射质量检查失败"

echo "=== 板块资金趋势追踪 ==="
python -m analysis.board_trend_tracker --date "$TRADE_DATE" || echo "[警告] 资金趋势追踪失败"

echo "=== 生成报告 ==="
python -m analysis.daily_report --mode both --date "$TRADE_DATE"

echo "=== 流程检查 ==="
python -m analysis.pipeline_check --date "$TRADE_DATE" || echo "[警告] 部分流程文件缺失"

echo "=== 更新信号表现 ==="
python -m analysis.signal_tracker || echo "[警告] 信号表现更新失败"

echo "=== 生成策略统计 ==="
python -m analysis.backtest_report || echo "[警告] 策略统计生成失败"

echo "=== 推送消息 ==="

if [ "$PUSH_CHANNEL" = "email" ]; then
    python -m analysis.email_sender --date "$TRADE_DATE" || echo "[警告] 邮件推送失败，但报告已生成"
elif [ "$PUSH_CHANNEL" = "feishu" ]; then
    python -m analysis.feishu_sender || echo "[警告] 飞书推送失败，但报告已生成"
else
    echo "PUSH_CHANNEL=$PUSH_CHANNEL，跳过推送"
fi

echo "=== 完成 ==="
