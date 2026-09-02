"""Regression checks for immutable-snapshot report recovery."""
from analysis.report_recovery import render_recovery_bundle


def main():
    row = {
        "signal_id": "sig-1", "source_run_id": "run-1", "code": "600000",
        "name": "样本股", "strategy": "板块联动", "canonical_final_layer": "候选低吸",
        "primary_direction": "通信", "market_status": "震荡", "market_score": 55,
        "trade_mode": "观察", "position_cap": 1, "sentiment_score": 60,
        "sentiment_stage": "分歧", "data_confidence": 100, "close_price": 10,
        "pct_chg": 1.2, "observe_low": 9.8, "observe_high": 10,
        "invalid_price": 9.5, "feature_json": {"plan": {"display_reason": "等待承接"}},
    }
    main_report, appendix = render_recovery_bundle(
        "20260902", [row], {"available": False, "status": "missing"},
    )
    assert "未重新运行选股" in main_report
    assert "样本股" in main_report and "daily_report_20260902_appendix.md" in main_report
    assert "sig-1" in appendix and "信号表写入：0" in appendix
    assert "## 2. 市场与交易环境" in appendix
    assert "recovery_mode: immutable_snapshot" in main_report
    assert "recovery_mode: immutable_snapshot_audit" in appendix
    print("[OK] report recovery regression check")


if __name__ == "__main__":
    main()
