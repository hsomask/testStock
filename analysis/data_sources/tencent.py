"""
腾讯行情数据源
部分接口实现参考 simonlin1212/a-stock-data，License: Apache-2.0
Repository: https://github.com/simonlin1212/a-stock-data
"""
import numpy as np
import pandas as pd
import requests


_TENCENT_SESSION = None


def _session():
    global _TENCENT_SESSION
    if _TENCENT_SESSION is None:
        _TENCENT_SESSION = requests.Session()
        _TENCENT_SESSION.trust_env = False
        _TENCENT_SESSION.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://gu.qq.com/",
        })
    return _TENCENT_SESSION


def tencent_quote(codes):
    """
    获取腾讯实时行情
    codes: 如 ["sh000001", "sh000300", "sz399006"]
    返回 DataFrame
    """
    s = _session()
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    try:
        r = s.get(url, timeout=10)
        if r.status_code != 200 or not r.text.strip():
            return pd.DataFrame()

        results = []
        for line in r.text.strip().split("\n"):
            line = line.strip()
            if not line.startswith("v_"):
                continue
            # 格式: v_sh000001="1~上证指数~000001~..."
            name = line.split('"')[0].replace("v_", "")
            fields = line.split('"')[1].split("~")
            if len(fields) < 10:
                continue
            results.append({
                "code": fields[2],
                "name": fields[1],
                "close": fields[3],
                "pre_close": fields[4],
                "open": fields[5],
                "volume": fields[6],
                "high": fields[33] if len(fields) > 33 else np.nan,
                "low": fields[34] if len(fields) > 34 else np.nan,
                "amount": fields[37] if len(fields) > 37 else np.nan,
                "pct_chg": fields[32] if len(fields) > 32 else np.nan,
            })
        return pd.DataFrame(results)
    except Exception:
        return pd.DataFrame()


def fetch_index_spot_tencent():
    """获取三大指数行情（腾讯通道）"""
    codes = ["sh000001", "sh000300", "sz399006"]
    names = {"000001": "上证指数", "000300": "沪深300", "399006": "创业板指"}
    df = tencent_quote(codes)
    if df.empty:
        return []

    indices = []
    for _, row in df.iterrows():
        code = str(row.get("code", ""))
        indices.append({
            "name": names.get(code, row.get("name", "")),
            "close": row.get("close", np.nan),
            "pct_chg": row.get("pct_chg", np.nan),
            "amount": row.get("amount", np.nan),
            "high": row.get("high", np.nan),
            "low": row.get("low", np.nan),
            "open": row.get("open", np.nan),
        })
    return indices
