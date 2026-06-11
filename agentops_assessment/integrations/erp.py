from __future__ import annotations

import json
from pathlib import Path


class ERPClient:
    def __init__(self, data_path: str | Path) -> None:
        self.data_path = Path(data_path)
        self._rows = json.loads(self.data_path.read_text(encoding="utf-8"))

    def get_inventory(self, sku: str) -> dict:
        for row in self._rows:
            if row["sku"] == sku:
                result = dict(row)
                result["stock_gap"] = row["safety_stock"] - row["current_stock"]
                return result
        raise KeyError(f"ERP 样例数据中不存在 SKU: {sku}")
