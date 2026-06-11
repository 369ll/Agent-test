from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agentops_assessment.agent.fake_llm import FakeLLM


@dataclass(frozen=True)
class PlanStep:
    id: str
    tool_name: str
    description: str
    input_template: dict[str, Any] = field(default_factory=dict)


class Planner:
    def __init__(self, llm: FakeLLM | None = None) -> None:
        self.llm = llm or FakeLLM()

    def create_plan(self, prompt: str, context: dict[str, Any] | None = None) -> list[PlanStep]:
        """为业务请求生成多步骤工具计划。

        根据任务意图生成确定性工具链：erp -> bi -> knowledge -> supplier -> oa(可选)。
        OA 步骤仅在存在写操作意图且非纯分析任务时加入计划。
        """
        # Extract SKU - preserve original case to support hidden/non-standard SKUs
        sku_match = re.search(r"SKU-\d+", prompt, re.IGNORECASE)
        sku = sku_match.group(0) if sku_match else None

        # Intent analysis based on README rules:
        # - "只分析"/"仅分析" 类任务不得产生 OA 写入副作用
        # - 包含审批/补货/创建/生成建议等动作时，需要 OA 草稿（除非明确排除）
        prompt_lower = prompt.lower()

        # Explicit exclusion patterns: user says "don't create OA" or "analysis only"
        exclusive_patterns = [
            r"只分析", r"仅分析", r"不.*创建.*审批", r"不.*生成.*审批",
            r"no approval", r"analysis only", r"just analyze", r"don't create",
            r"不需要.*审批", r"无需.*审批",
        ]
        is_exclusive_analysis = any(re.search(p, prompt_lower) for p in exclusive_patterns)

        # Write-action patterns: user wants to create approval/draft/replenishment
        write_action_patterns = [
            r"审批", r"补货", r"创建.*建议", r"生成.*审批", r"生成.*建议",
            r"approval", r"replenishment", r"create.*draft", r"create.*approval",
        ]
        has_write_action = any(re.search(p, prompt_lower) for p in write_action_patterns)

        # OA step: only when there is a write action intent and NOT explicitly excluded
        should_create_oa = has_write_action and not is_exclusive_analysis

        plan = []

        # Standard tool chain per README:
        # erp.get_inventory -> bi.get_sales -> knowledge.search -> supplier.get_risk -> oa.create_approval_draft
        if sku:
            plan.append(PlanStep(
                id="get_inventory",
                tool_name="erp.get_inventory",
                description=f"获取 {sku} 的库存数据",
                input_template={"sku": sku},
            ))

            plan.append(PlanStep(
                id="get_sales",
                tool_name="bi.get_sales",
                description=f"获取 {sku} 的销售和预测数据",
                input_template={"sku": sku},
            ))

            plan.append(PlanStep(
                id="search_knowledge",
                tool_name="knowledge.search",
                description=f"查询 {sku} 的库存处理规则",
                input_template={
                    "query": f"{sku} 库存异常处理规则",
                    "top_k": 3,
                },
            ))

            plan.append(PlanStep(
                id="get_supplier_risk",
                tool_name="supplier.get_risk",
                description="查询供应商风险评估",
                input_template={"supplier_id": "$ERP_RESULT.supplier_id"},
            ))

            if should_create_oa:
                plan.append(PlanStep(
                    id="create_approval",
                    tool_name="oa.create_approval_draft",
                    description=f"创建 {sku} 的补货审批草稿",
                    input_template={
                        "sku": sku,
                        "title": f"{sku} 自动补货审批",
                        "content": f"基于 {sku} 的库存缺口和预测数据生成的审批建议。",
                    },
                ))
        else:
            # No SKU identified: fallback to knowledge search
            plan.append(PlanStep(
                id="general_search",
                tool_name="knowledge.search",
                description="查询通用库存政策",
                input_template={"query": prompt, "top_k": 3},
            ))

        return plan
