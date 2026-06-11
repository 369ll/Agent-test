from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class OAClient:
    def __init__(self, rules_path: str | Path) -> None:
        self.rules_path = Path(rules_path)
        self.rules = json.loads(self.rules_path.read_text(encoding="utf-8"))

    def create_approval_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        sku = payload.get("sku", "UNKNOWN")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:8]
        return {
            "approval_draft_id": f"OA-DRAFT-{sku}-{digest}",
            "status": "draft",
            "approval_type": payload.get("approval_type", "inventory_replenishment"),
            "required_approver_role": self.rules.get("inventory_replenishment", {}).get(
                "required_approver_role", "ops_manager"
            ),
        }

