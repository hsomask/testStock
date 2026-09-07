"""Regression checks for compact main report + full audit appendix delivery."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from analysis import daily_report, email_sender
from analysis.report_renderer import render_compact_daily_report


def main():
    market = {
        "score": 72, "status": "偏强", "summary": "主线活跃但不宜追高。",
        "up_count": 3000, "down_count": 1800, "flat_count": 100,
        "limit_up": 50, "limit_down": 5,
        "limitup_stats": {"status": "ok", "yesterday_limit_up_avg_return": 1.2,
                          "three_board_plus_count": 3, "max_consecutive_limit_up": 5,
                          "failed_limit_up_rate": 0.2},
    }
    trade_plan = {
        "market_restrictions": {"max_position_pct": 5, "single_stock_pct": 1},
        "decision": {
            "mode": {"name": "试错"},
            "execution": {"summary": "只做确认后的主线机会。"},
            "plans": {
                "候选低吸": [{"name": "示例A", "strategy": "板块联动",
                              "observe_low": 10, "observe_high": 10.5, "invalid_price": 9.5}],
                "只观察": [{"name": "示例B", "strategy": "短线强势",
                            "observe_low": 20, "observe_high": 21, "invalid_price": 19}],
                "交易条件不满足": [{"name": "示例D", "strategy": "N字异动",
                                   "observe_low": 30, "observe_high": 31,
                                   "pressure_price": 35, "invalid_price": 29,
                                   "display_reason": "策略反馈偏弱，等待重新转强"}],
                "高风险回避": [{"name": "示例C", "strategy": "N字异动",
                                "risk_reasons": "位置偏高"}],
            },
        },
    }
    render_args = (
        "20260828", {}, {"confidence_score": 100}, market, None, None,
        {"score": 70, "stage": "高潮"}, {},
    )
    render_options = {
        "trade_plan": trade_plan,
        "t1_data": {
            "available": True, "status": "ok",
            "evaluated_1d": 25, "total_signals": 25,
            "avg_return_1d": -0.0088, "win_rate_1d": 0.28,
            "top_winners": [{"name": "兑现样本", "ret": 0.035}],
            "top_losers": [{"name": "失效样本", "ret": -0.021}],
        },
    }
    report = render_compact_daily_report(
        *render_args, mode="unified", **render_options,
    )
    assert render_compact_daily_report(*render_args, **render_options) == report
    assert render_compact_daily_report(
        *render_args, mode="beginner", **render_options,
    ) == report
    assert render_compact_daily_report(
        *render_args, mode="pro", **render_options,
    ) == report
    required = [
        "明天怎么做", "昨日观察池兑现复盘", "明日观察池",
        "可以考虑", "只观察", "暂不行动", "明确回避",
        "市场与主线", "风险与失效", "数据与学习状态",
        "daily_report_20260828_appendix.md",
    ]
    assert all(item in report for item in required)
    assert "完成度：** 25/25" in report
    assert "兑现样本" in report and "失效样本" in report
    assert "学习状态" in report
    assert "示例D" in report and "策略反馈偏弱" in report
    assert "完整市场指标" not in report
    sections = email_sender.parse_report_sections(report)
    mail_body = email_sender.build_email_body(sections)
    assert "明天怎么做" in mail_body and "明日观察池" in mail_body
    assert email_sender.extract_date(report) == "2026-08-28"

    with TemporaryDirectory() as temp:
        root = Path(temp)
        main_path = root / "daily_report_20260828.md"
        appendix_path = root / "daily_report_20260828_appendix.md"

        def save_main(content, _date, _mode):
            main_path.write_text(content, encoding="utf-8")
            return main_path

        def save_appendix(content, _date):
            appendix_path.write_text(content, encoding="utf-8")
            return appendix_path

        with (
            patch.object(daily_report, "load_t1_evaluation_summary", return_value={"available": False, "status": "missing"}),
            patch.object(daily_report, "load_correction_effectiveness_summary", return_value=None),
            patch.object(daily_report, "save_report", side_effect=save_main),
            patch.object(daily_report, "save_report_appendix", side_effect=save_appendix),
            patch.object(daily_report, "_get_db_conn", return_value=None),
        ):
            generated = daily_report.generate_report_mode(
                "20260828", "unified", {}, market, None, None,
                {"score": 70, "stage": "高潮"}, {}, {},
                {"confidence_score": 100}, [], trade_plan=trade_plan,
            )
        assert generated == main_path.read_text(encoding="utf-8")
        assert "明天怎么做" in generated
        assert (root / "daily_intelligence_20260828.json").exists()
        assert "市场与交易环境" in appendix_path.read_text(encoding="utf-8")

        captured = {}
        with (
            patch.object(email_sender, "REPORTS_DIR", root),
            patch("analysis.trade_calendar.is_trade_day", return_value=True),
            patch.object(email_sender, "send_email", side_effect=lambda s, b, a: captured.update(attachments=a) or "success"),
        ):
            # Avoid source/data fallback by supplying the explicit date path.
            with patch("sys.argv", ["email_sender", "--date", "20260828"]):
                email_sender._main()
        names = [Path(item).name for item in captured["attachments"]]
        assert names[:2] == [main_path.name, appendix_path.name], names

        with (
            patch.object(email_sender, "REPORTS_DIR", root),
            patch("analysis.trade_calendar.is_trade_day", return_value=True),
            patch("sys.argv", ["email_sender", "--date", "20260829"]),
        ):
            assert email_sender._main() == "skipped_report_missing"
    print("[OK] report bundle regression check")


if __name__ == "__main__":
    main()
