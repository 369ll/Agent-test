from __future__ import annotations

from tests.conftest import headers


def test_public_task_run_contract(client):
    task_response = client.post(
        "/api/tasks",
        headers=headers("alice"),
        json={
            "title": "公开契约任务",
            "prompt": "分析 SKU-001 库存异常，并返回可查询的运行记录。",
        },
    )
    assert task_response.status_code == 201
    task = task_response.json()
    assert {"id", "title", "prompt", "status", "created_by", "created_at", "updated_at"} <= set(task)

    run_response = client.post(f"/api/tasks/{task['id']}/run", headers=headers("alice"))
    assert run_response.status_code == 202
    run = run_response.json()
    assert {"run_id", "task_id", "status"} <= set(run)

    detail_response = client.get(f"/api/runs/{run['run_id']}", headers=headers("alice"))
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["id"] == run["run_id"]
    assert detail["status"] in {"queued", "running", "completed", "failed"}

    events_response = client.get(f"/api/runs/{run['run_id']}/events", headers=headers("alice"))
    assert events_response.status_code == 200
    assert isinstance(events_response.json()["events"], list)


def test_public_knowledge_and_admin_contract(client):
    search_response = client.post(
        "/api/knowledge/search",
        headers=headers("alice"),
        json={"query": "库存异常审批规则", "top_k": 2},
    )
    assert search_response.status_code == 200
    assert {"answer", "citations", "filtered_doc_ids"} <= set(search_response.json())

    dashboard_response = client.get("/api/admin/dashboard", headers=headers("alice"))
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert {"task_count", "run_count", "failure_rate", "token_cost", "tool_call_counts"} <= set(
        dashboard
    )


def test_public_permission_contract(client):
    denied_response = client.post(
        "/api/tasks",
        headers=headers("mallory"),
        json={"title": "无权限任务", "prompt": "尝试创建一个没有权限的任务。"},
    )
    assert denied_response.status_code == 403
    assert "missing_permissions" in denied_response.text

