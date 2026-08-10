"""Shared EastMoney push2delay transport with bounded pagination."""

import time

import pandas as pd


PUSH2DELAY_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"


def _session():
    import requests

    session = requests.Session()
    session.trust_env = False
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    })
    return session


def fetch_paginated(
    fs_filter,
    fields,
    pz=100,
    *,
    fid="f3",
    timeout=30,
    retries=2,
    max_pages=200,
    max_empty_pages=2,
    session_factory=_session,
):
    """Fetch a complete EastMoney result set or fail without returning partial data."""
    session = session_factory()
    all_rows = []
    total = None
    empty_pages = 0

    for page in range(1, max_pages + 1):
        params = {
            "pn": str(page),
            "pz": str(pz),
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": fid,
            "fs": fs_filter,
            "fields": fields,
        }
        last_error = None
        payload = None
        for attempt in range(retries + 1):
            try:
                response = session.get(PUSH2DELAY_URL, params=params, timeout=timeout)
                status_code = getattr(response, "status_code", 200)
                if status_code >= 400:
                    raise RuntimeError(f"EastMoney HTTP {status_code}")
                payload = response.json()
                data = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(data, dict):
                    raise RuntimeError("EastMoney response has no data object")
                break
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(0.2 * (attempt + 1))
        if payload is None or not isinstance(payload.get("data"), dict):
            raise RuntimeError(
                f"EastMoney page {page} failed after {retries + 1} attempts: {last_error}"
            )

        data = payload["data"]
        if total is None:
            total = int(data.get("total") or 0)
        rows = data.get("diff") or []
        if not isinstance(rows, list):
            raise RuntimeError(f"EastMoney page {page} diff is not a list")
        if rows:
            all_rows.extend(rows)
            empty_pages = 0
        else:
            empty_pages += 1

        if len(all_rows) >= total:
            return pd.DataFrame(all_rows)
        if empty_pages >= max_empty_pages:
            raise RuntimeError(
                f"EastMoney pagination stalled: total={total}, received={len(all_rows)}"
            )

    raise RuntimeError(
        f"EastMoney pagination exceeded max_pages={max_pages}: total={total}, received={len(all_rows)}"
    )
