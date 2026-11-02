"""Offline date-split baseline and ridge experiment; never changes recommendations."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

FEATURES = ["market_score", "sentiment_score", "data_confidence", "pct_chg",
            "pct_5d", "pct_20d", "volume_ratio", "turnover"]


def prepare(frame):
    frame = frame.copy()
    for col in ("trade_date", "as_of_date"):
        frame[col] = pd.to_datetime(frame[col].astype(str), format="%Y%m%d")
    frame = frame[(frame.train_eligible == 1) & frame.next_1d_return.notna()]
    # A stock appearing in several strategies gets one observation and one vote.
    numeric = FEATURES + ["decision_score", "next_1d_return"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    frame["original_candidate"] = frame.base_layer.eq("候选低吸")
    frame["corrected_candidate"] = frame.final_layer.eq("候选低吸")
    rules = {c: "mean" for c in numeric}
    rules.update(as_of_date="max", original_candidate="max", corrected_candidate="max")
    return frame.groupby(["trade_date", "code"], as_index=False).agg(rules)


def fixed_comparison(frame):
    rows = []
    for day, group in frame.groupby("trade_date"):
        original = group[group.original_candidate]
        corrected = group[group.corrected_candidate]
        rows.append({"date": day.strftime("%Y%m%d"),
                     "original_count": len(original), "corrected_count": len(corrected),
                     "original_mean": float(original.next_1d_return.mean()) if len(original) else None,
                     "corrected_mean": float(corrected.next_1d_return.mean()) if len(corrected) else None})
    return {"interpretation": "descriptive_only_not_causal_or_tradable_returns", "dates": rows}


def fit_predict(train, test, alpha=10.0):
    x = train[FEATURES].to_numpy(float)
    z = test[FEATURES].to_numpy(float)
    medians = pd.DataFrame(x).median().fillna(0).to_numpy()
    x = np.where(np.isfinite(x), x, medians)
    z = np.where(np.isfinite(z), z, medians)
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale == 0] = 1
    x, z = (x - mean) / scale, (z - mean) / scale
    y = train.next_1d_return.to_numpy(float)
    center = y.mean()
    coef = np.linalg.solve(x.T @ x + alpha * np.eye(len(FEATURES)), x.T @ (y - center))
    return z @ coef + center


def experiment(frame, min_train_dates=20, test_dates=5, top_k=10):
    dates = sorted(frame.trade_date.unique())
    predictions, folds = [], []
    for start in range(min_train_dates, len(dates), test_dates):
        block = dates[start:start + test_dates]
        # Labels must have matured strictly before this test block begins.
        train = frame[(frame.trade_date < block[0]) & (frame.as_of_date < block[0])]
        test = frame[frame.trade_date.isin(block)].copy()
        if train.trade_date.nunique() < min_train_dates:
            continue
        test["prediction"] = fit_predict(train, test)
        predictions.append(test)
        folds.append({"train_dates": int(train.trade_date.nunique()),
                      "latest_train_label": train.as_of_date.max().strftime("%Y%m%d"),
                      "test_start": pd.Timestamp(block[0]).strftime("%Y%m%d"),
                      "test_end": pd.Timestamp(block[-1]).strftime("%Y%m%d")})
    if not predictions:
        return {"status": "insufficient_dates", "folds": []}, pd.DataFrame()
    scored = pd.concat(predictions, ignore_index=True)
    daily = []
    for day, group in scored.groupby("trade_date"):
        # Identical universe and count; ties resolved by code, never by outcomes.
        group = group.sort_values("code", kind="stable")
        model = group.sort_values("prediction", ascending=False, kind="stable").head(top_k)
        baseline = group.sort_values("decision_score", ascending=False, kind="stable").head(top_k)
        daily.append({"date": day.strftime("%Y%m%d"), "count": len(model),
                      "model_mean": float(model.next_1d_return.mean()),
                      "rule_mean": float(baseline.next_1d_return.mean())})
    return {"status": "shadow_only", "model": "ridge_alpha_10",
            "baseline": "frozen_decision_score_including_existing_correction",
            "protocol": {"min_train_dates": min_train_dates, "test_dates": test_dates,
                         "top_k": top_k, "label": "next_1d_return", "alpha": 10.0},
            "features": FEATURES, "folds": folds, "daily": daily,
            "promotion": "disabled",
            "limitations": ["not_executable_returns", "no_cost_or_slippage_model",
                            "historical_snapshot_provenance_requires_audit",
                            "no_claim_of_statistical_or_causal_improvement"]}, scored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    source = Path(args.input)
    frame = prepare(pd.read_csv(source, dtype={"code": str}))
    result, predictions = experiment(frame)
    result["input_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    result["source"] = str(source)
    result["fixed_comparison"] = fixed_comparison(frame)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "experiment.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    predictions.to_csv(out / "shadow_predictions.csv", index=False)
    print(json.dumps({"status": result["status"], "rows": len(frame), "folds": len(result["folds"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
