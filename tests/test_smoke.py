from __future__ import annotations

from tests.conftest import headers


def test_healthcheck_and_seeded_user(client):
    assert client.get("/health").json() == {"status": "ok"}
    response = client.post(
        "/api/tasks",
        headers=headers("alice"),
        json={"title": "环境检查任务", "prompt": "分析 SKU-001 库存异常，确认环境可用。"},
    )
    assert response.status_code == 201
    assert response.json()["created_by"] == "alice"
