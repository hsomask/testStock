"""Regression checks for completely missing Evaluation repair."""

from unittest.mock import patch

from analysis import evaluation_backfill_low_coverage as backfill


def _target(missing):
    return {
        "signal_date": "20260731",
        "as_of_date": "20260803",
        "total_signals": 24,
        "evaluated_1d": 0 if missing else 21,
        "coverage_1d": 0.0 if missing else 0.875,
        "missing_evaluation": missing,
    }


def _coverage(*_args, **_kwargs):
    return {
        "status": "ready",
        "coverage": 0.875,
        "coverage_level": "low_weight",
        "quality_weight": 0.5,
    }


def main():
    commands = []
    with (
        patch.object(backfill, "_fetch_targets", return_value=[_target(True), _target(False)]) as fetch_targets,
        patch.object(backfill, "ensure_signal_kline_coverage", side_effect=_coverage),
        patch.object(
            backfill,
            "_run_module",
            side_effect=lambda module, args: commands.append((module, tuple(args))) or {"returncode": 0},
        ),
        patch.object(backfill, "_write_report", return_value=None),
    ):
        result = backfill.backfill_low_coverage(execute=True)

    missing, existing = result["items"]
    errors = []
    with patch.object(
        backfill,
        "resolve_evaluation_horizons",
        return_value={
            "t1_mature": True, "t3_mature": True,
            "t1_date": "20260821", "t3_date": "20260825",
        },
    ):
        horizon, state = backfill._select_repair_horizon(
            signal_date="20260820", run_as_of="20260826", signal_count=26,
            evaluated_1d=26, coverage_1d=1.0,
            evaluated_3d=18, coverage_3d=18 / 26,
        )
    if horizon != "t3" or state.get("reason_code") != "mature_low_coverage":
        errors.append("mature low-coverage T+3 was not selected for repair")
    if missing["effective_rerun_coverage"] != 0.80:
        errors.append("completely missing Evaluation does not use the formal 80% threshold")
    if missing["action"] != "rerun_evaluation":
        errors.append("87.5% completely missing Evaluation was not repaired")
    if existing["effective_rerun_coverage"] != 0.90:
        errors.append("existing low-coverage Evaluation lost its conservative 90% threshold")
    if existing["action"] != "keep_low_weight":
        errors.append("existing 87.5% Evaluation should remain low-weight without rewrite")
    evaluation_runs = [item for item in commands if item[0] == "analysis.watchlist_evaluation"]
    if len(evaluation_runs) != 1:
        errors.append(f"expected one formal Evaluation repair, got {len(evaluation_runs)}")
    if fetch_targets.call_args.kwargs.get("exclude_signal_date") is not None:
        errors.append("default backfill unexpectedly excludes a signal date")

    failed_commands = []
    with (
        patch.object(backfill, "_fetch_targets", return_value=[_target(True)]),
        patch.object(backfill, "ensure_signal_kline_coverage", side_effect=_coverage),
        patch.object(
            backfill,
            "_run_module",
            side_effect=lambda module, args: failed_commands.append(module) or {"returncode": 1},
        ),
        patch.object(backfill, "_write_report", return_value=None),
    ):
        failed_result = backfill.backfill_low_coverage(execute=True)
    if failed_result.get("status") != "failed":
        errors.append("formal Evaluation repair failure was swallowed")
    if failed_commands != ["analysis.watchlist_evaluation"]:
        errors.append("sidecars ran after formal Evaluation repair failed")

    if errors:
        print("[FAIL] Evaluation gap regression check")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("[OK] Evaluation gap regression check")


if __name__ == "__main__":
    main()
