---
doc_id: inventory_policy
title: 库存异常处理规则
permission: knowledge:internal
---

当当前库存低于安全库存，且未来 14 天预测需求大于可用库存时，Agent 应将该 SKU 判定为补货风险。

对于补货风险，如果库存缺口至少为 30 件，或预计销售影响超过 5000 美元，应创建 OA 审批草稿。

建议必须包含 SKU、仓库、库存缺口、预测需求、供应商风险，以及用于决策的准确规则引用。

