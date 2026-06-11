from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentops_assessment.backend.app import create_app
from agentops_assessment.backend.seed import seed_database


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


@pytest.fixture()
def db_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "assessment.sqlite"
    monkeypatch.setenv("ASSESSMENT_DB_PATH", str(path))
    monkeypatch.setenv("ASSESSMENT_FIXTURES_DIR", str(FIXTURES))
    seed_database(path, FIXTURES)
    return path


@pytest.fixture()
def client(db_path) -> TestClient:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def headers(user_id: str = "alice") -> dict[str, str]:
    return {"X-User-Id": user_id}


def create_task(client: TestClient, prompt: str | None = None, user_id: str = "alice") -> str:
    response = client.post(
        "/api/tasks",
        headers=headers(user_id),
        json={
            "title": "SKU-001 库存异常",
            "prompt": prompt
            or "分析 SKU-001 库存异常，结合 ERP、BI、知识库和供应商风险生成补货审批建议。",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def run_task_and_wait(client: TestClient, task_id: str, user_id: str = "alice") -> dict:
    run_response = client.post(f"/api/tasks/{task_id}/run", headers=headers(user_id))
    assert run_response.status_code == 202, run_response.text
    run_id = run_response.json()["run_id"]
    last = None
    for _ in range(20):
        detail = client.get(f"/api/runs/{run_id}", headers=headers(user_id))
        assert detail.status_code == 200, detail.text
        last = detail.json()
        if last["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert last is not None
    return last
