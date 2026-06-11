from __future__ import annotations

import sqlite3
from collections import Counter

from agentops_assessment.backend import database


def build_dashboard(conn: sqlite3.Connection) -> dict:
    task_count = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
    run_count = conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()["c"]
    failed_count = conn.execute(
        "SELECT COUNT(*) AS c FROM runs WHERE status = 'failed'"
    ).fetchone()["c"]
    completed_count = conn.execute(
        "SELECT COUNT(*) AS c FROM runs WHERE status = 'completed'"
    ).fetchone()["c"]
    token_cost = conn.execute("SELECT COALESCE(SUM(token_cost), 0) AS c FROM runs").fetchone()[
        "c"
    ]
    events = conn.execute("SELECT tool_name FROM run_events WHERE tool_name IS NOT NULL").fetchall()
    tool_counts = Counter(row["tool_name"] for row in events)

    # Average duration for completed runs
    # Note: SQLite's julianday can be used for date calculations
    avg_duration_row = conn.execute(
        """
        SELECT AVG((julianday(finished_at) - julianday(started_at)) * 86400.0) AS avg_dur
        FROM runs
        WHERE status = 'completed' AND finished_at IS NOT NULL AND started_at IS NOT NULL
        """
    ).fetchone()
    avg_duration = avg_duration_row["avg_dur"] or 0

    # Recent failures - desensitize error messages
    recent_failures_rows = conn.execute(
        """
        SELECT id, task_id, error, finished_at
        FROM runs
        WHERE status = 'failed'
        ORDER BY finished_at DESC
        LIMIT 5
        """
    ).fetchall()
    recent_failures = []
    for row in recent_failures_rows:
        fail = dict(row)
        error_msg = fail.get("error", "")
        # Strip internal paths, stack traces, and sensitive keywords
        if "File \"" in error_msg or "line " in error_msg or "Traceback" in error_msg:
            fail["error"] = "任务执行发生内部错误"
        for kw in ["vendor_secret", "unit_cost_usd", "credential", "token"]:
            if kw in error_msg:
                fail["error"] = "任务执行失败（敏感信息已隐藏）"
                break
        recent_failures.append(fail)

    # Queue health
    queued_count = conn.execute("SELECT COUNT(*) AS c FROM runs WHERE status = 'queued'").fetchone()["c"]
    running_count = conn.execute("SELECT COUNT(*) AS c FROM runs WHERE status = 'running'").fetchone()["c"]

    return {
        "task_count": task_count,
        "run_count": run_count,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "failure_rate": failed_count / run_count if run_count else 0,
        "average_run_seconds": avg_duration,
        "token_cost": token_cost,
        "tool_call_counts": dict(tool_counts),
        "recent_failures": recent_failures,
        "queue_health": {
            "queued": queued_count,
            "running": running_count,
        },
        "generated_at": database.now_iso(),
    }
