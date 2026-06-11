from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from agentops_assessment.backend import database
from agentops_assessment.rag.documents import load_markdown_documents, split_document

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES_DIR = ROOT_DIR / "fixtures"


def fixtures_dir() -> Path:
    return Path(os.getenv("ASSESSMENT_FIXTURES_DIR", str(DEFAULT_FIXTURES_DIR)))


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def seed_database(db_path: str | Path | None = None, fixture_root: str | Path | None = None) -> Path:
    root = Path(fixture_root) if fixture_root else fixtures_dir()
    path = Path(db_path) if db_path else database.get_db_path()
    with database.connect(path) as conn:
        database.init_db(conn)
        database.reset_tables(conn)

        for user in _read_json(root / "users.json"):
            conn.execute(
                """
                INSERT INTO users (id, name, roles_json, permissions_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user["id"],
                    user["name"],
                    database.encode_json(user["roles"]),
                    database.encode_json(user["permissions"]),
                ),
            )

        for doc in load_markdown_documents(root / "knowledge"):
            for chunk in split_document(doc):
                conn.execute(
                    """
                    INSERT INTO knowledge_chunks
                    (id, doc_id, source_path, title, permission, content, embedding_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["id"],
                        doc["doc_id"],
                        doc["source_path"],
                        doc["title"],
                        doc["permission"],
                        chunk["content"],
                        None,
                    ),
                )
        conn.commit()
    return path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    path = seed_database()
    print(f"已初始化测评数据库: {path}")


if __name__ == "__main__":
    main()
