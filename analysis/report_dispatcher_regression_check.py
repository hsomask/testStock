"""Regression checks for first-generation/rerender routing."""
from types import SimpleNamespace

from analysis import report_dispatcher as dispatcher
from analysis.report_rerender import replace_evaluation_section


def main():
    original_inspect = dispatcher.inspect_signal_set
    original_rerender = dispatcher.rerender_report
    calls = []
    try:
        dispatcher.inspect_signal_set = lambda _date: {"state": "complete"}
        dispatcher.rerender_report = lambda date: calls.append(("rerender", date)) or {"status": "success"}
        result = dispatcher.dispatch_report("20260825", executor=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("generator called")))
        assert result["route"] == "rerender" and calls == [("rerender", "20260825")]

        captured = {}
        dispatcher.inspect_signal_set = lambda _date: {"state": "missing"}
        def executor(command, **kwargs):
            captured.update(command=command, kwargs=kwargs)
            return SimpleNamespace(returncode=0)
        result = dispatcher.dispatch_report("20260824", executor=executor)
        assert result["route"] == "generate"
        assert captured["kwargs"]["env"]["TRADE_DATE"] == "20260824"
        assert captured["kwargs"]["env"]["SEND_DAILY_EMAIL"] == "0"

        dispatcher.inspect_signal_set = lambda _date: {"state": "incomplete", "signal_count": 1}
        try:
            dispatcher.dispatch_report("20260823", executor=executor)
            raise AssertionError("incomplete signals were regenerated")
        except RuntimeError as exc:
            assert "incomplete_existing_signal_set" in str(exc)
    finally:
        dispatcher.inspect_signal_set = original_inspect
        dispatcher.rerender_report = original_rerender

    source = "prefix\n## 1. 昨日观察池兑现复盘（T+1）\nold\n\n## 2. 市场与交易环境\nsuffix\n"
    rendered = replace_evaluation_section(source, {})
    assert rendered.startswith("prefix\n") and rendered.endswith("## 2. 市场与交易环境\nsuffix\n")
    assert "old" not in rendered
    assert replace_evaluation_section(rendered, {}) == rendered
    print("[OK] report dispatcher regression check")


if __name__ == "__main__":
    main()
