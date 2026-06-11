from __future__ import annotations

import json
from pathlib import Path

from agentops_assessment.integrations.exceptions import TransientIntegrationError


class SupplierRiskClient:
    def __init__(self, data_path: str | Path, fail_first: bool = False) -> None:
        self.data_path = Path(data_path)
        self._rows = json.loads(self.data_path.read_text(encoding="utf-8"))
        self.fail_first = fail_first
        self._call_count = 0

    def get_supplier_risk(self, supplier_id: str) -> dict:
        self._call_count += 1
        if self.fail_first and self._call_count == 1:
            raise TransientIntegrationError("供应商 API 临时超时。")
        for row in self._rows:
            if row["supplier_id"] == supplier_id:
                return dict(row)
        raise KeyError(f"供应商不存在: {supplier_id}")
