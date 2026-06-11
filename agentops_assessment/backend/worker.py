from __future__ import annotations

from typing import Any

from agentops_assessment.backend import database
from agentops_assessment.agent.planner import Planner
from agentops_assessment.agent.executor import Executor
from agentops_assessment.agent.tools import SENSITIVE_KEYS, ToolRegistry


def _desensitize(data: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive and internal debug fields from a dict."""
    if not isinstance(data, dict):
        return data
    return {k: v for k, v in data.items() if k not in SENSITIVE_KEYS}


def execute_run(run_id: str) -> None:
    """后台执行入口。

    完整的 Planner -> Executor 流程。更新 running/completed/failed 状态，
    持久化步骤事件，通过 ToolRegistry 调用工具（含脱敏和安全校验），
    记录 token 成本，并保存最终业务结果。
    """
    with database.connect() as conn:
        database.init_db(conn)

        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            return

        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (run["task_id"],)).fetchone()
        if not task:
            return

        user = conn.execute("SELECT * FROM users WHERE id = ?", (run["requested_by"],)).fetchone()
        if not user:
            return
        user_permissions = database.decode_json(user["permissions_json"], [])

        now = database.now_iso()
        conn.execute(
            "UPDATE runs SET status = ?, started_at = ? WHERE id = ?",
            ("running", now, run_id),
        )
        conn.commit()

    try:
        planner = Planner()
        plan = planner.create_plan(task["prompt"])

        registry = ToolRegistry.with_default_clients()
        executor = Executor(registry)

        context = {
            "user_id": user["id"],
            "user_permissions": user_permissions,
        }

        # Wrap registry.call to persist tool events and audit logs
        original_call = registry.call

        def wrapped_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
            safe_args = _desensitize(args)

            # Prompt injection check on tool inputs
            from agentops_assessment.rag.security import detect_prompt_injection
            for val in args.values():
                if isinstance(val, str) and detect_prompt_injection(val):
                    raise RuntimeError(f"检测到工具输入中存在提示词注入: {name}")

            try:
                result = original_call(name, args)
                safe_result = _desensitize(result)

                with database.connect() as event_conn:
                    database.insert_run_event(
                        event_conn,
                        run_id,
                        "tool.call",
                        {"input": safe_args, "output": safe_result},
                        tool_name=name,
                    )
                    if name == "oa.create_approval_draft" and result.get("approval_draft_id"):
                        database.insert_audit_log(
                            event_conn,
                            actor_id=user["id"],
                            action="approval.draft.create",
                            resource=result["approval_draft_id"],
                            payload={
                                "sku": args.get("sku"),
                                "title": args.get("title"),
                                "approval_type": result.get("approval_type"),
                            },
                            decision="allow",
                        )
                return result
            except PermissionError:
                # Permission denied: per README, skipped OA write must NOT record
                # a successful oa.create_approval_draft event.
                # We do NOT record a tool.call event for skipped operations,
                # to avoid polluting the standard event trail with non-executed tools.
                # Audit log still records the denial for traceability.
                with database.connect() as event_conn:
                    database.insert_audit_log(
                        event_conn,
                        actor_id=user["id"],
                        action="tool.call",
                        resource=name,
                        payload={"reason": "permission_denied", "tool": name},
                        decision="deny",
                    )
                # Return empty result so executor can continue
                return {}
            except Exception as e:
                # Avoid leaking raw stack traces in events
                error_msg = str(e)
                if "File \"" in error_msg or "line " in error_msg or "Traceback" in error_msg:
                    error_msg = "工具执行发生内部错误"
                # Record as tool.call with error status to comply with event contract
                with database.connect() as event_conn:
                    database.insert_run_event(
                        event_conn,
                        run_id,
                        "tool.call",
                        {"input": safe_args, "error": error_msg},
                        tool_name=name,
                    )
                raise

        registry.call = wrapped_call

        state = executor.execute(run_id, plan, context)

        # Final update - desensitize result before persisting
        with database.connect() as final_conn:
            if state.status == "completed":
                safe_result = _desensitize(state.result)
                final_conn.execute(
                    """
                    UPDATE runs
                    SET status = ?, result_json = ?, token_cost = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (
                        "completed",
                        database.encode_json(safe_result),
                        safe_result.get("total_token_cost", 0),
                        database.now_iso(),
                        run_id,
                    ),
                )
                final_conn.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    ("completed", database.now_iso(), task["id"]),
                )
            else:
                # Desensitize error message too
                error_msg = state.steps[-1].error if state.steps else "Unknown error"
                if "File \"" in error_msg or "line " in error_msg or "Traceback" in error_msg:
                    error_msg = "任务执行发生内部错误"
                final_conn.execute(
                    """
                    UPDATE runs
                    SET status = ?, error = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    ("failed", error_msg, database.now_iso(), run_id),
                )
                final_conn.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    ("failed", database.now_iso(), task["id"]),
                )
            final_conn.commit()

    except Exception as e:
        error_msg = str(e)
        if "File \"" in error_msg or "line " in error_msg or "Traceback" in error_msg:
            error_msg = "任务执行发生内部错误"
        with database.connect() as error_conn:
            error_conn.execute(
                """
                UPDATE runs
                SET status = ?, error = ?, finished_at = ?
                WHERE id = ?
                """,
                ("failed", error_msg, database.now_iso(), run_id),
            )
            error_conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                ("failed", database.now_iso(), task["id"]),
            )
            error_conn.commit()
