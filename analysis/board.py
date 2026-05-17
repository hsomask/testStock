import numpy as np
import pandas as pd


def add_board_strength(df):
    df = df.copy()

    for col in ["pct_chg", "turnover", "leader_pct_chg", "up_count", "down_count"]:
        if col not in df.columns:
            df[col] = np.nan

    total_members = df["up_count"].fillna(0) + df["down_count"].fillna(0)
    df["up_ratio"] = df["up_count"].fillna(0) / total_members.replace(0, np.nan)
    df["up_ratio"] = df["up_ratio"].fillna(0)

    df["strength_score"] = (
        df["pct_chg"].fillna(0) * 0.45
        + df["turnover"].fillna(0) * 0.20
        + df["leader_pct_chg"].fillna(0) * 0.20
        + df["up_ratio"].fillna(0) * 10 * 0.15
    )

    return df


def analyze_boards(board_df, board_type="行业"):
    df = add_board_strength(board_df)

    top_gain = df.sort_values("pct_chg", ascending=False).head(10)
    top_loss = df.sort_values("pct_chg", ascending=True).head(10)
    top_strength = df.sort_values("strength_score", ascending=False).head(10)

    top_hot = df.sort_values(["turnover", "pct_chg"], ascending=False).head(10)
    top_cold = df.sort_values(["pct_chg", "turnover"], ascending=True).head(10)

    active_boards = top_strength["board_name"].head(5).tolist()
    weak_boards = top_loss["board_name"].head(5).tolist()

    return {
        "board_type": board_type,
        "top_gain": top_gain,
        "top_loss": top_loss,
        "top_strength": top_strength,
        "top_hot": top_hot,
        "top_cold": top_cold,
        "active_boards": active_boards,
        "weak_boards": weak_boards,
    }
