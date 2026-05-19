#!/bin/bash
set -e

echo "=== 初始化数据库 ==="
python -m analysis.init_db

echo "=== 更新板块成交占比 ==="
python -m analysis.board_history

echo "=== 生成报告 ==="
python -m analysis.daily_report --mode both --force

echo "=== 推送消息 ==="

if [ "$PUSH_CHANNEL" = "email" ]; then
    python -m analysis.email_sender || echo "[警告] 邮件推送失败，但报告已生成"
elif [ "$PUSH_CHANNEL" = "feishu" ]; then
    python -m analysis.feishu_sender || echo "[警告] 飞书推送失败，但报告已生成"
else
    echo "PUSH_CHANNEL=$PUSH_CHANNEL，跳过推送"
fi

echo "=== 完成 ==="
