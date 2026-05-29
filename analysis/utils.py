import pandas as pd
import numpy as np


def to_ymd(date_str):
    """任意格式日期 → YYYYMMDD"""
    if not date_str:
        return ""
    s = str(date_str).strip().replace("-", "").replace("/", "").replace(".", "")
    return s[:8]


def to_date_display(date_str):
    """YYYYMMDD → YYYY-MM-DD"""
    s = to_ymd(date_str)
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def safe_numeric(df, cols):
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fmt_num(x, digits=2):
    if pd.isna(x):
        return "-"
    return f"{x:.{digits}f}"


def fmt_pct(x, digits=2):
    if pd.isna(x):
        return "-"
    return f"{x:+.{digits}f}%"


def fmt_yi(x, digits=1):
    if pd.isna(x):
        return "-"
    return f"{x:.{digits}f}亿"
