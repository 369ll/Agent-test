from __future__ import annotations

import re
from pathlib import Path


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    metadata: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
    return metadata, parts[2].strip()


def load_markdown_documents(directory: str | Path) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for path in sorted(Path(directory).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        metadata, body = _parse_frontmatter(text)
        docs.append(
            {
                "doc_id": metadata.get("doc_id", path.stem),
                "title": metadata.get("title", path.stem.replace("-", " ").title()),
                "permission": metadata.get("permission", "knowledge:read"),
                "source_path": str(path),
                "content": body,
            }
        )
    return docs


def split_document(document: dict[str, str], max_chars: int = 700) -> list[dict[str, str]]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", document["content"]) if p.strip()]
    chunks: list[dict[str, str]] = []
    current = ""
    index = 1
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(
                {
                    "id": f"{document['doc_id']}:{index}",
                    "content": current,
                }
            )
            index += 1
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip()
    if current:
        chunks.append({"id": f"{document['doc_id']}:{index}", "content": current})
    return chunks

