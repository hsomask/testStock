#!/bin/bash
set -e

echo "=== 初始化数据库 ==="
python -m analysis.init_db

echo "=== 更新板块成交占比 ==="
python -m analysis.board_history

echo "=== 生成小白版报告 ==="
python -m analysis.daily_report --mode beginner --force

echo "=== 生成专业版报告 ==="
python -m analysis.daily_report --mode pro --force

echo "=== 推送飞书消息 ==="
python -m analysis.feishu_sender

echo "=== 完成 ==="
