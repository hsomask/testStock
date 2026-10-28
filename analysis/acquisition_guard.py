"""Bounded optional board acquisition and explicit degradation checks."""
import argparse
from datetime import datetime, timedelta, timezone
import logging
from io import StringIO
from pathlib import Path
import subprocess
import sys
import time

import pandas as pd

CN = timezone(timedelta(hours=8))
BOARD_COLUMNS = ["board_name", "board_code", "pct_chg", "turnover", "leader_pct_chg",
                 "up_count", "down_count", "amount"]


def fetch_board_snapshot(kind):
    if kind not in {"industry", "concept"}:
        raise ValueError("invalid board kind")
    result = subprocess.run([sys.executable, "-m", "analysis.acquisition_guard", "--fetch", kind],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, encoding="utf-8", timeout=90, check=True)
    return pd.read_json(StringIO(result.stdout), orient="split")


def require_live_day(day, now=None):
    now = now or datetime.now(CN)
    if day != now.strftime("%Y%m%d") or now.hour < 15:
        raise RuntimeError("Live quotes cannot generate a historical or pre-close daily report")


def board_frame(fetch):
    try:
        frame = fetch()
        if frame is None or frame.empty or "pct_chg" not in frame or "board_name" not in frame:
            raise ValueError("missing_board_quotes")
        if pd.to_numeric(frame["pct_chg"], errors="coerce").isna().any():
            raise ValueError("incomplete_board_quotes")
        return frame, True
    except Exception as exc:
        logging.getLogger(__name__).warning("Board quotes unavailable: %s", type(exc).__name__)
        return pd.DataFrame(columns=BOARD_COLUMNS), False


def board_history_current(conn, day):
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT board_type FROM board_amount_ratio WHERE trade_date=%s AND amount_ratio IS NOT NULL",
                    (datetime.strptime(day, "%Y%m%d").date(),))
        return {row[0] for row in cur.fetchall()} >= {"行业", "概念"}


def prepare(day, budget=240, execute=subprocess.run, clock=time.monotonic, sleep=time.sleep):
    require_live_day(day)
    deadline = clock() + budget
    for attempt in range(2):
        remaining = deadline - clock()
        if remaining <= 0:
            break
        try:
            result = execute([sys.executable, "-m", "analysis.board_history", "--date", day],
                             timeout=remaining, check=False)
            if result.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        if attempt == 0 and deadline - clock() > 5:
            sleep(5)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date")
    parser.add_argument("--fetch", choices=["industry", "concept"])
    args = parser.parse_args()
    if args.fetch:
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):
            from analysis.data_fetcher import fetch_industry_boards, fetch_concept_boards
            frame = (fetch_industry_boards if args.fetch == "industry" else fetch_concept_boards)()
        sys.stdout.reconfigure(encoding="utf-8")
        print(frame.to_json(orient="split", force_ascii=False))
        return
    if not args.date:
        parser.error("--date is required")
    if not prepare(args.date):
        print("[WARN] Board acquisition unavailable; dependent analysis must be disabled", flush=True)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
