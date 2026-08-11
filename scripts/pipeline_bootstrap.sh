#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Initialize database schema ==="
python -m analysis.init_db

echo "=== Ensure persistent exchange calendar ==="
python -m analysis.trade_calendar_sync --ensure --future-days 400 --apply
