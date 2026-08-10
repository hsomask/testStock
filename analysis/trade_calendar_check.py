"""CLI gate for distinguishing open, closed, and unavailable calendars."""
from __future__ import annotations

import argparse

from analysis.trade_calendar import cli_check_date


def main():
    parser = argparse.ArgumentParser(description="Check canonical exchange-calendar status")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    raise SystemExit(cli_check_date(args.date))


if __name__ == "__main__":
    main()
