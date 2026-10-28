"""Opt-in operational notice, separate from daily report delivery."""
import argparse
import os

from analysis.web_review_data import valid_date


def notify(day):
    valid_date(day)
    if os.getenv("REPORT_FAILURE_EMAIL", "0") != "1":
        return "disabled"
    import psycopg2
    from data.config import DATABASE_DSN
    from analysis.email_sender import send_email
    from analysis.task_ledger import start_task, finish_task
    # The pipeline's existing flock serializes attempts; successful notices are not repeated.
    with psycopg2.connect(DATABASE_DSN, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT EXISTS(SELECT 1 FROM job_run_log WHERE trade_date=%s "
                        "AND job_name='report_failure_notice' AND status='success')", (day,))
            if cur.fetchone()[0]:
                return "already_sent"
    run = start_task("report_failure_notice", day)
    try:
        result = send_email(f"【复盘任务异常】{day}",
                            f"{day} 的复盘任务未完整完成。请检查服务器任务日志及网页更新状态。\n"
                            "本通知不是当日日报；页面可能仍展示上一份已发布报告，请核对日期。")
    except Exception:
        finish_task(run, "failed")
        raise
    finish_task(run, "success" if result == "success" else "failed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    result = notify(args.date)
    print(result)
    if result not in {"success", "already_sent", "disabled"}:
        raise SystemExit(1)
