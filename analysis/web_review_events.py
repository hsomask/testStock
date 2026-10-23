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
from time import monotonic
from urllib.parse import urlsplit

from analysis.web_review_data import DailyArtifactReader, valid_date


CN = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]


def valid_symbol(code):
    return isinstance(code, str) and len(code) == 6 and code.isascii() and code.isdigit()


def valid_subject(code):
    return code == "market" or valid_symbol(code)


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
    if not isinstance(rows, list):
        raise ValueError("invalid_event_rows")
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
                       "association": "市场资讯，不代表已确认的行情驱动原因" if code == "market" else
                                      "代码检索命中，尚未确认是价格变动原因"})
    return sorted(events, key=lambda e: e["published_at"], reverse=True)[:50 if code == "market" else 10]


class EventCache:
    def __init__(self, directory):
        self.root = Path(directory).resolve()

    def cleanup(self, today=None):
        """Delete only dated news files inside this directory; keep today plus six days."""
        today = today or datetime.now(CN).strftime("%Y%m%d")
        cutoff = (datetime.strptime(valid_date(today), "%Y%m%d") - timedelta(days=6)).strftime("%Y%m%d")
        removed, failed = 0, 0
        for path in self.root.glob("*.json"):
            parts = path.stem.split("_")
            if len(parts) != 2 or not valid_subject(parts[1]):
                continue
            try:
                day = valid_date(parts[0])
            except (TypeError, ValueError):
                continue
            if day >= cutoff or path.is_symlink() or path.resolve().parent != self.root:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                failed += 1
        return {"removed": removed, "failed": failed}

    def load(self, code, day):
        valid_date(day)
        if not valid_subject(code):
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
            for item in data.get("events", [])[:50 if code == "market" else 10]:
                if not isinstance(item, dict):
                    continue
                raw = {"新闻标题": item.get("title"), "新闻链接": item.get("url"),
                       "发布时间": item.get("published_at"), "文章来源": item.get("source")}
                events.extend(normalize_events([raw], code, day, item.get("collected_at", data["collected_at"])))
            status = data.get("status")
            return {"status": status if status in {"available", "empty", "failed"} else "invalid",
                    "events": events, "collected_at": data["collected_at"]}
        except FileNotFoundError:
            cutoff = (datetime.now(CN) - timedelta(days=6)).strftime("%Y%m%d")
            return {"status": "expired" if day < cutoff else "not_collected", "events": []}
        except (OSError, ValueError, TypeError, KeyError):
            return {"status": "invalid", "events": []}

    def save(self, code, day, events, status, collected_at):
        if not valid_subject(code):
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
            # Public link metadata must be readable by the separate non-root web container.
            temp.chmod(0o644)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def collect(code, day, cache, timeout=25):
    if not valid_subject(code):
        raise ValueError("invalid_symbol")
    valid_date(day)
    now = datetime.now(CN).isoformat()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "analysis.web_review_events"] +
            (["--fetch-market"] if code == "market" else ["--fetch-one", code]),
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
        if not events and prior:
            return {"code": code, "status": "empty", "retained": len(prior)}
        status = "available" if events else "empty"
        cache.save(code, day, events, status, now)
        return {"code": code, "status": status, "count": len(events)}
    except (subprocess.SubprocessError, OSError, ValueError, TypeError):
        previous = cache.load(code, day)
        if not previous["events"]:
            try:
                cache.save(code, day, [], "failed", now)
            except OSError:
                return {"code": code, "status": "cache_unwritable", "retained": 0}
        return {"code": code, "status": "failed", "retained": len(previous["events"])}


def collect_batch(codes, day, cache, time_budget=120, per_code_timeout=25):
    """Bound the whole enrichment job, including skipped symbols in its result."""
    valid_date(day)
    codes = list(dict.fromkeys(codes))
    if (not 1 <= len(codes) <= 20 or not all(valid_symbol(c) for c in codes)
            or not 1 <= time_budget <= 600 or not 1 <= per_code_timeout <= 60):
        raise ValueError("invalid_collection_budget_or_codes")
    deadline = monotonic() + time_budget
    results = []
    for code in codes:
        remaining = deadline - monotonic()
        if remaining <= 0:
            results.append({"code": code, "status": "budget_exhausted"})
        else:
            results.append(collect(code, day, cache, timeout=min(per_code_timeout, remaining)))
    return results


def collect_plan(day, daily_dir, cache, time_budget=120):
    """Use the saved canonical plan, preserving its order without reselecting stocks."""
    data = DailyArtifactReader(daily_dir).daily(day)
    if data["sources"]["trade_plan"] != "available" or data["decision_status"] != "canonical":
        return {"status": "skipped", "reason": "canonical_plan_unavailable", "results": []}
    codes = list(dict.fromkeys(row["code"] for row in data["candidates"]
                              if row["board_scope"] in {"main_board", "research_only"}))[:20]
    if not 1 <= time_budget <= 600:
        raise ValueError("invalid_time_budget")
    started = monotonic()
    market = collect("market", day, cache, timeout=min(25, time_budget))
    remaining = time_budget - (monotonic() - started)
    results = ([] if not codes else [{"code": c, "status": "budget_exhausted"} for c in codes] if remaining < 1 else
               collect_batch(codes, day, cache, time_budget=remaining))
    results.insert(0, market)
    degraded = any(row["status"] not in {"available", "empty"} for row in results)
    return {"status": "deferred" if degraded else "success", "trade_date": day,
            "selected_count": len(codes), "results": results}


def main():
    parser = argparse.ArgumentParser(description="Collect bounded news references; never changes signals")
    parser.add_argument("--date")
    parser.add_argument("--codes", nargs="+")
    parser.add_argument("--time-budget", type=int, default=120)
    parser.add_argument("--from-plan", action="store_true")
    parser.add_argument("--fetch-one", help=argparse.SUPPRESS)
    parser.add_argument("--fetch-market", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.fetch_market:
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):
            import akshare as ak
            frame = ak.stock_info_global_em()
        frame = frame.rename(columns={"标题": "新闻标题", "链接": "新闻链接"})
        frame["文章来源"] = "东方财富财经快讯"
        print(frame[["新闻标题", "新闻链接", "发布时间", "文章来源"]].to_json(orient="records", force_ascii=False))
        return
    if args.fetch_one:
        if not valid_symbol(args.fetch_one):
            raise SystemExit(2)
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):
            import akshare as ak
            frame = ak.stock_news_em(symbol=args.fetch_one)
        print(frame[["新闻标题", "新闻链接", "发布时间", "文章来源"]].to_json(orient="records", force_ascii=False))
        return
    if args.from_plan:
        if not args.date or args.codes:
            parser.error("--from-plan requires --date and cannot be combined with --codes")
    elif not args.date or not args.codes or len(args.codes) > 20:
        parser.error("--date and 1 to 20 --codes are required")
    valid_date(args.date)
    cache = EventCache(ROOT / "reports" / "events")
    cleanup = cache.cleanup()
    print(json.dumps({"news_cleanup": cleanup}), file=sys.stderr, flush=True)
    cutoff = (datetime.now(CN) - timedelta(days=6)).strftime("%Y%m%d")
    if args.date < cutoff:
        print(json.dumps({"status": "skipped", "reason": "news_cache_expired"}), flush=True)
        raise SystemExit(3)
    if args.from_plan:
        result = collect_plan(args.date, ROOT / "reports" / "daily", cache, args.time_budget)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        raise SystemExit({"success": 0, "deferred": 2, "skipped": 3}[result["status"]])
    for result in collect_batch(args.codes, args.date, cache, time_budget=args.time_budget):
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
