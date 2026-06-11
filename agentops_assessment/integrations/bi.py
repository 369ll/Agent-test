from __future__ import annotations

import json
from pathlib import Path


class BIClient:
    def __init__(self, data_path: str | Path) -> None:
        self.data_path = Path(data_path)
        self._rows = json.loads(self.data_path.read_text(encoding="utf-8"))

    def get_sales(self, sku: str) -> dict:
        for row in self._rows:
            if row["sku"] == sku:
                return dict(row)
        raise KeyError(f"BI 样例数据中不存在 SKU: {sku}")
