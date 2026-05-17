import pandas as pd
import numpy as np


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
