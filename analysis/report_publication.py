"""Atomic public artifact bundles. Failed attempts never replace a published report."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import tempfile

from analysis.web_review_data import valid_date

ROOT = Path(__file__).resolve().parents[1] / "reports" / "daily"
PREFIXES = ("daily_summary", "trade_plan", "daily_intelligence")


def missing_as_null(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: missing_as_null(item) for key, item in value.items()}
    if isinstance(value, list):
        return [missing_as_null(item) for item in value]
    return value


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            handle.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.chmod(0o644)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def record_state(day, status, *, root=ROOT, stages=None):
    valid_date(day)
    atomic_json(Path(root) / f"publication_state_{day}.json", {
        "trade_date": day, "status": status,
        "updated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "failed_steps": [s["step"] for s in (stages or []) if s.get("status") in {"failed", "blocked"}],
    })


def publish(day, root=ROOT):
    from analysis.web_review_data import DailyArtifactReader
    valid_date(day)
    root = Path(root)
    artifacts = {}
    for prefix in PREFIXES:
        path = root / f"{prefix}_{day}.json"
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Publication artifact too large")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("trade_date") != day:
            raise ValueError("Publication artifact date mismatch")
        artifacts[prefix] = value
    # Validate the new files, not a previous published bundle.
    reader = DailyArtifactReader(root, published=False)
    daily = reader.daily(day)
    if daily["readiness"]["market"] != "complete" or daily["saved_plan_status"] != "canonical":
        raise ValueError("Publication requires complete core market facts and canonical plan")
    intelligence = artifacts["daily_intelligence"].get("market_read") or {}
    if intelligence.get("score") is not None and intelligence.get("score") != daily["market"]["score"]:
        raise ValueError("Publication market score mismatch")
    partial = artifacts["daily_summary"].get("quality", {}).get("board_data_unavailable") is True
    if partial and daily["new_recommendations_allowed"]:
        raise ValueError("Degraded report must disable new recommendations")
    status = "partial" if partial else "success"
    atomic_json(root / f"published_{day}.json", {"trade_date": day, "status": status, "artifacts": missing_as_null(artifacts)})
    record_state(day, status, root=root)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    print(publish(args.date))


if __name__ == "__main__":
    main()
