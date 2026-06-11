from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    prompt: str = Field(min_length=10, max_length=4000)


class TaskOut(BaseModel):
    id: str
    title: str
    prompt: str
    status: str
    created_by: str
    created_at: str
    updated_at: str


class RunCreateOut(BaseModel):
    run_id: str
    task_id: str
    status: Literal["queued", "running", "completed", "failed"]


class RunOut(BaseModel):
    id: str
    task_id: str
    requested_by: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    token_cost: int = 0
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=3, ge=1, le=10)


class KnowledgeCitation(BaseModel):
    doc_id: str
    title: str
    source_path: str
    chunk_id: str


class KnowledgeSearchResult(BaseModel):
    answer: str
    citations: list[KnowledgeCitation]
    filtered_doc_ids: list[str] = []

