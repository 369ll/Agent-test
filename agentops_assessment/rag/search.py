from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from agentops_assessment.backend import database
from agentops_assessment.rag.security import PROMPT_INJECTION_PATTERNS

# Pre-compiled patterns for secret detection in knowledge chunks
_SECRET_PATTERNS = [
    re.compile(r"vendor_secret\s*[:=]", re.IGNORECASE),
    re.compile(r"unit_cost[_usd]*\s*[:=]", re.IGNORECASE),
    re.compile(r"ACME-TIER-\d+-REBATE", re.IGNORECASE),
    re.compile(r"BETA-PRICE-FLOOR", re.IGNORECASE),
    re.compile(r"泄露.*(机密|凭证|令牌|密钥)", re.IGNORECASE),
    re.compile(r"reveal.*(secret|credential)", re.IGNORECASE),
]


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9-]+|[\u4e00-\u9fff]", text.lower())


def cosine_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    q = Counter(query_tokens)
    d = Counter(doc_tokens)
    dot = sum(q[token] * d[token] for token in q.keys() & d.keys())
    q_norm = math.sqrt(sum(v * v for v in q.values()))
    d_norm = math.sqrt(sum(v * v for v in d.values()))
    if not q_norm or not d_norm:
        return 0.0
    return dot / (q_norm * d_norm)


def _sanitize_chunk_content(content: str) -> str:
    """Strip injection patterns, secrets, and malicious instructions from chunk text.

    Knowledge base content is treated as untrusted data. Any text that attempts
    to override system policies, leak secrets, or inject instructions must be
    filtered out before being included in the answer.
    """
    # Remove lines containing injection patterns
    lines = content.split("\n")
    safe_lines = []
    for line in lines:
        is_injection = any(p.search(line) for p in PROMPT_INJECTION_PATTERNS)
        # Filter obvious secret-leaking content using pre-compiled patterns
        # to avoid false positives on common words like "token" in legitimate context
        has_secret = any(p.search(line) for p in _SECRET_PATTERNS)
        if not is_injection and not has_secret:
            safe_lines.append(line)
    return "\n".join(safe_lines).strip()


class KnowledgeIndex:
    """轻量级本地检索索引。

    权限感知检索、答案生成、引用溯源和被过滤文档报告。
    文档正文视为不可信数据，注入攻击文本和机密信息在生成 answer 前被过滤。
    """

    def search(
        self,
        query: str,
        user_permissions: list[str],
        top_k: int = 3,
    ) -> dict[str, Any]:
        with database.connect() as conn:
            database.init_db(conn)
            rows = conn.execute(
                """
                SELECT id, doc_id, source_path, title, permission, content
                FROM knowledge_chunks
                """
            ).fetchall()

        # Identify documents the user does NOT have permission to see
        all_doc_ids = {row["doc_id"] for row in rows}
        visible_doc_ids = {
            row["doc_id"]
            for row in rows
            if row["permission"] in user_permissions
        }
        filtered_doc_ids = sorted(list(all_doc_ids - visible_doc_ids))

        # Filter chunks the user CAN see
        visible_chunks = [
            row for row in rows if row["permission"] in user_permissions
        ]

        # Calculate scores
        query_tokens = tokenize(query)
        scored_chunks = []
        for row in visible_chunks:
            doc_tokens = tokenize(row["content"])
            score = cosine_score(query_tokens, doc_tokens)
            if score > 0:
                scored_chunks.append((score, row))

        # Sort and take top_k
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        top_chunks = scored_chunks[:top_k]

        # Generate answer and citations
        citations = []
        seen_citations = set()

        if not top_chunks:
            answer = "根据您目前的权限，未在知识库中找到与该查询相关的公开或受授权内容。"
        else:
            # Sanitize content before building answer
            safe_chunks = []
            for score, row in top_chunks:
                safe_content = _sanitize_chunk_content(row["content"])
                if safe_content:
                    safe_chunks.append((score, row, safe_content))

            if not safe_chunks:
                answer = "检索到的知识库内容包含安全风险，已自动过滤。"
            else:
                primary = safe_chunks[0]
                answer = f"根据《{primary[1]['title']}》等知识库文档：{primary[2]}"

                supporting = [
                    c[2] for c in safe_chunks[1:]
                    if c[2][:20] not in primary[2]
                ]
                if supporting:
                    answer += " 此外，相关规则还提到：" + " ".join(supporting)

            for score, row, _ in safe_chunks:
                citation_key = (row["doc_id"], row["id"])
                if citation_key not in seen_citations:
                    citations.append({
                        "doc_id": row["doc_id"],
                        "title": row["title"],
                        "source_path": row["source_path"],
                        "chunk_id": row["id"],
                    })
                    seen_citations.add(citation_key)

        return {
            "answer": answer,
            "citations": citations,
            "filtered_doc_ids": filtered_doc_ids,
        }
