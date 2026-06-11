from __future__ import annotations

import hashlib


class FakeLLM:
    """确定性的 LLM 替身。

    候选人不需要为本测评准备外部 API Key。凡是需要稳定模型响应或
    token 估算的地方，都可以使用这个类。
    """

    def complete(self, prompt: str) -> dict:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        return {
            "text": f"fake-llm-response:{digest}",
            "prompt_tokens": max(1, len(prompt.split())),
            "completion_tokens": 24,
        }
