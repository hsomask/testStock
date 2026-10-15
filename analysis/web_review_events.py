"""Offline news cache. Collection is explicit, bounded, and outside web requests."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from analysis.web_review_data import valid_date


CN = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]


def valid_symbol(code):
    return isinstance(code, str) and len(code) == 6 and code.isascii() and code.isdigit()


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme in {"https", "http"} and parsed.hostname
                and not parsed.username and not parsed.password):
            return value
    except ValueError:
        pass
    return None


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("invalid_timestamp")
    result = datetime.fromisoformat(value)
    return result.replace(tzinfo=CN) if result.tzinfo is None else result.astimezone(CN)


def normalize_events(rows, code, day, collected_at):
    cutoff = datetime.strptime(valid_date(day), "%Y%m%d").replace(tzinfo=CN) + timedelta(days=1)
    seen = set()
    events = []
    collected = timestamp(collected_at)
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        title, url = row.get("新闻标题"), safe_url(row.get("新闻链接"))
        try:
            published = timestamp(row.get("发布时间"))
        except (ValueError, TypeError):
            continue
        if not isinstance(title, str) or not title.strip() or not url:
            continue
        if not cutoff - timedelta(days=7) <= published < cutoff or published > collected:
            continue
        identity = sha256(url.encode()).hexdigest()[:20]
        if identity in seen:
            continue
        seen.add(identity)
        events.append({"id": identity, "code": code, "title": title.strip()[:240],
                       "url": url, "source": str(row.get("文章来源") or "东方财富检索")[:100],
                       "published_at": published.isoformat(), "collected_at": collected.isoformat(),
                       "late_collected": collected >= cutoff,
                       "after_close": published.date() == (cutoff-timedelta(days=1)).date()
                                      and published.hour >= 15,
                       "association": "代码检索命中，尚未确认是价格变动原因"})
    return sorted(events, key=lambda e: e["published_at"], reverse=True)[:10]


class EventCache:
    def __init__(self, directory):
        self.root = Path(directory).resolve()

    def load(self, code, day):
        valid_date(day)
        if not valid_symbol(code):
            raise ValueError("invalid_symbol")
        path = self.root / f"{day}_{code}.json"
        try:
            if path.resolve().parent != self.root or path.stat().st_size > 1024*1024:
                return {"status": "invalid", "events": []}
            data = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("schema_version") != "review_events_v1"
                    or data.get("trade_date") != day or data.get("code") != code):
                return {"status": "invalid", "events": []}
            events = []
            for item in data.get("events", [])[:10]:
                if not isinstance(item, dict):
                    continue
                raw = {"新闻标题": item.get("title"), "新闻链接": item.get("url"),
                       "发布时间": item.get("published_at"), "文章来源": item.get("source")}
                events.extend(normalize_events([raw], code, day, item.get("collected_at", data["collected_at"])))
            status = data.get("status")
            return {"status": status if status in {"available", "empty", "failed"} else "invalid",
                    "events": events, "collected_at": data["collected_at"]}
        except FileNotFoundError:
            return {"status": "not_collected", "events": []}
        except (OSError, ValueError, TypeError, KeyError):
            return {"status": "invalid", "events": []}

    def save(self, code, day, events, status, collected_at):
        if not valid_symbol(code):
            raise ValueError("invalid_symbol")
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{valid_date(day)}_{code}.json"
        value = {"schema_version": "review_events_v1", "trade_date": day, "code": code,
                 "status": status, "collected_at": collected_at, "events": events}
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root,
                                         suffix=".tmp", delete=False) as handle:
            json.dump(value, handle, ensure_ascii=False)
            temp = Path(handle.name)
        try:
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def collect(code, day, cache, timeout=25):
    if not valid_symbol(code):
        raise ValueError("invalid_symbol")
    valid_date(day)
    now = datetime.now(CN).isoformat()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "analysis.web_review_events", "--fetch-one", code],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        rows = json.loads(result.stdout)
        events = normalize_events(rows, code, day, now)
        prior = {e["id"]: e for e in cache.load(code, day)["events"]}
        for item in events:
            if item["id"] in prior:
                item["collected_at"] = prior[item["id"]]["collected_at"]
                item["late_collected"] = prior[item["id"]]["late_collected"]
        status = "available" if events else "empty"
        cache.save(code, day, events, status, now)
        return {"code": code, "status": status, "count": len(events)}
    except (subprocess.SubprocessError, OSError, ValueError, TypeError):
        previous = cache.load(code, day)
        if not previous["events"]:
            cache.save(code, day, [], "failed", now)
        return {"code": code, "status": "failed", "retained": len(previous["events"])}


def main():
    parser = argparse.ArgumentParser(description="Collect bounded news references; never changes signals")
    parser.add_argument("--date")
    parser.add_argument("--codes", nargs="+")
    parser.add_argument("--fetch-one", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.fetch_one:
        if not valid_symbol(args.fetch_one):
            raise SystemExit(2)
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):
            import akshare as ak
            frame = ak.stock_news_em(symbol=args.fetch_one)
        print(frame[["新闻标题", "新闻链接", "发布时间", "文章来源"]].to_json(orient="records", force_ascii=False))
        return
    if not args.date or not args.codes or len(args.codes) > 20:
        parser.error("--date and 1 to 20 --codes are required")
    cache = EventCache(ROOT / "reports" / "events")
    for code in dict.fromkeys(args.codes):
        print(json.dumps(collect(code, args.date, cache), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
