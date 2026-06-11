---
doc_id: approval_policy
title: OA 审批权限规则
permission: knowledge:internal
---

只有具备 `oa:approval:write` 权限的用户可以创建 OA 审批草稿。

分析师可以准备分析结论，但除非同时具备明确的审批写入权限，否则不得创建审批草稿。

每一份审批草稿都必须写入审计日志，日志中应包含操作者、SKU、审批类型和脱敏后的载荷。

