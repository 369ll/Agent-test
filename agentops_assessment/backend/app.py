from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status

from agentops_assessment.admin.metrics import build_dashboard
from agentops_assessment.backend import database
from agentops_assessment.backend.auth import get_current_user, require_permissions
from agentops_assessment.backend.schemas import (
    KnowledgeSearchRequest,
    RunCreateOut,
    RunOut,
    TaskCreate,
    TaskOut,
)
from agentops_assessment.backend.worker import execute_run
from agentops_assessment.rag.search import KnowledgeIndex


def _task_from_row(row) -> TaskOut:
    return TaskOut(**dict(row))


def _run_from_row(row) -> RunOut:
    data = dict(row)
    data["result"] = database.decode_json(data.pop("result_json"), None)
    return RunOut(**data)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with database.connect() as conn:
            database.init_db(conn)
        yield

    app = FastAPI(
        title="AgentOps 迷你测评服务",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
    def create_task(
        body: TaskCreate,
        user: dict = Depends(require_permissions("tasks:create")),
    ) -> TaskOut:
        from agentops_assessment.rag.security import detect_prompt_injection
        
        # Prompt injection check
        injections = detect_prompt_injection(body.prompt)
        if injections:
            with database.connect() as conn:
                database.init_db(conn)
                database.insert_audit_log(
                    conn,
                    actor_id=user["id"],
                    action="task.rejected",
                    resource="NEW_TASK",
                    payload={"reason": "prompt_injection_detected", "injections": injections},
                    decision="deny"
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "prompt_injection_detected",
                    "message": f"检测到潜在的提示词注入: {', '.join(injections)}"
                }
            )

        task_id = str(uuid.uuid4())
        now = database.now_iso()
        with database.connect() as conn:
            database.init_db(conn)
            conn.execute(
                """
                INSERT INTO tasks (id, created_by, title, prompt, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, user["id"], body.title, body.prompt, "created", now, now),
            )
            database.insert_audit_log(
                conn,
                actor_id=user["id"],
                action="task.create",
                resource=task_id,
                payload={"title": body.title},
            )
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_from_row(row)

    @app.post(
        "/api/tasks/{task_id}/run",
        response_model=RunCreateOut,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def run_task(
        task_id: str,
        background_tasks: BackgroundTasks,
        user: dict = Depends(require_permissions("tasks:run")),
    ) -> RunCreateOut:
        from agentops_assessment.agent.planner import Planner
        
        run_id = str(uuid.uuid4())
        now = database.now_iso()
        with database.connect() as conn:
            database.init_db(conn)
            task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not task:
                raise HTTPException(status_code=404, detail="任务不存在。")

            # Pre-check tool-level permissions based on the plan
            planner = Planner()
            plan = planner.create_plan(task["prompt"])
            
            tool_permissions = {
                "erp.get_inventory": "erp:read",
                "bi.get_sales": "bi:read",
                "oa.create_approval_draft": "oa:approval:write",
                "supplier.get_risk": "supplier:read",
                "knowledge.search": "knowledge:read",
            }
            
            for step in plan:
                required_perm = tool_permissions.get(step.tool_name)
                if required_perm and required_perm not in user["permissions"]:
                    database.insert_audit_log(
                        conn,
                        actor_id=user["id"],
                        action="run.rejected",
                        resource=task_id,
                        payload={"reason": "insufficient_tool_permissions", "tool": step.tool_name, "permission": required_perm},
                        decision="deny"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"权限不足：缺少执行工具 {step.tool_name} 所需的权限 {required_perm}"
                    )

            conn.execute(
                """
                INSERT INTO runs (id, task_id, requested_by, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, task_id, user["id"], "queued", now),
            )
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                ("queued", now, task_id),
            )
            database.insert_audit_log(
                conn,
                actor_id=user["id"],
                action="run.create",
                resource=run_id,
                payload={"task_id": task_id},
            )
        background_tasks.add_task(execute_run, run_id)
        return RunCreateOut(run_id=run_id, task_id=task_id, status="queued")

    @app.get("/api/runs/{run_id}", response_model=RunOut)
    def get_run(run_id: str, user: dict = Depends(get_current_user)) -> RunOut:
        with database.connect() as conn:
            database.init_db(conn)
            row = conn.execute(
                """
                SELECT r.*, t.created_by as task_created_by
                FROM runs r
                JOIN tasks t ON r.task_id = t.id
                WHERE r.id = ?
                """,
                (run_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="运行记录不存在。")

            is_admin = "admin:read" in user["permissions"]
            if not (is_admin or row["requested_by"] == user["id"] or row["task_created_by"] == user["id"]):
                database.insert_audit_log(
                    conn,
                    actor_id=user["id"],
                    action="run.read.denied",
                    resource=run_id,
                    payload={"reason": "insufficient_permissions"},
                    decision="deny"
                )
                raise HTTPException(status_code=403, detail="没有权限访问此运行记录。")

            database.insert_audit_log(
                conn,
                actor_id=user["id"],
                action="run.read",
                resource=run_id,
                payload={},
            )
        return _run_from_row(row)

    @app.get("/api/runs/{run_id}/events")
    def get_run_events(run_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
        with database.connect() as conn:
            database.init_db(conn)
            row = conn.execute(
                """
                SELECT r.*, t.created_by as task_created_by
                FROM runs r
                JOIN tasks t ON r.task_id = t.id
                WHERE r.id = ?
                """,
                (run_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="运行记录不存在。")

            is_admin = "admin:read" in user["permissions"]
            if not (is_admin or row["requested_by"] == user["id"] or row["task_created_by"] == user["id"]):
                database.insert_audit_log(
                    conn,
                    actor_id=user["id"],
                    action="run.events.read.denied",
                    resource=run_id,
                    payload={"reason": "insufficient_permissions"},
                    decision="deny"
                )
                raise HTTPException(status_code=403, detail="没有权限访问此运行记录的事件。")

            rows = conn.execute(
                """
                SELECT seq, type, tool_name, payload_json, created_at
                FROM run_events
                WHERE run_id = ?
                ORDER BY seq ASC
                """,
                (run_id,),
            ).fetchall()
            database.insert_audit_log(
                conn,
                actor_id=user["id"],
                action="run.events.read",
                resource=run_id,
                payload={},
            )
        return {
            "run_id": run_id,
            "events": [
                {
                    "seq": row["seq"],
                    "type": row["type"],
                    "tool_name": row["tool_name"],
                    "payload": database.decode_json(row["payload_json"], {}),
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
        }

    @app.post("/api/knowledge/search")
    def search_knowledge(
        body: KnowledgeSearchRequest,
        user: dict = Depends(require_permissions("knowledge:read")),
    ) -> dict[str, Any]:
        index = KnowledgeIndex()
        result = index.search(
            body.query,
            user_permissions=user["permissions"],
            top_k=body.top_k,
        )
        return result

    @app.get("/api/admin/dashboard")
    def admin_dashboard(user: dict = Depends(require_permissions("admin:read"))) -> dict[str, Any]:
        with database.connect() as conn:
            database.init_db(conn)
            database.insert_audit_log(
                conn,
                actor_id=user["id"],
                action="admin.dashboard.read",
                resource="dashboard",
                payload={},
            )
            return build_dashboard(conn)

    @app.get("/api/admin/audit-logs")
    def admin_audit_logs(user: dict = Depends(require_permissions("admin:read"))) -> dict[str, Any]:
        with database.connect() as conn:
            database.init_db(conn)
            rows = conn.execute(
                """
                SELECT actor_id, action, resource, decision, payload_json, created_at
                FROM audit_logs
                ORDER BY id DESC
                LIMIT 100
                """
            ).fetchall()
        return {
            "logs": [
                {
                    "actor_id": row["actor_id"],
                    "action": row["action"],
                    "resource": row["resource"],
                    "decision": row["decision"],
                    "payload": database.decode_json(row["payload_json"], {}),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        }

    return app


app = create_app()
