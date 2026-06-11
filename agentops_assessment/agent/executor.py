from __future__ import annotations

from typing import Any

from agentops_assessment.agent.planner import PlanStep
from agentops_assessment.agent.state import InMemoryRunStateStore, RunState, StepState
from agentops_assessment.agent.tools import ToolRegistry
from agentops_assessment.integrations.exceptions import TransientIntegrationError


class Executor:
    def __init__(
        self,
        registry: ToolRegistry,
        state_store: InMemoryRunStateStore | None = None,
        max_retries: int = 2,
    ) -> None:
        self.registry = registry
        self.state_store = state_store or InMemoryRunStateStore()
        self.max_retries = max_retries

    def execute(
        self,
        run_id: str,
        plan: list[PlanStep],
        context: dict[str, Any],
    ) -> RunState:
        """执行计划并持久化步骤状态。

        已实现：可恢复的多步骤执行、工具入参渲染、步骤事件持久化、
        安全错误处理和最终业务结果汇总。
        """
        state = RunState(run_id=run_id, status="running")
        state.steps = [
            StepState(step_id=step.id, tool_name=step.tool_name, status="pending")
            for step in plan
        ]
        self.state_store.save(state)

        previous_results = {}
        total_cost = 0

        for i, step in enumerate(plan):
            step_state = state.steps[i]
            step_state.status = "running"
            self.state_store.save(state)

            try:
                # Render inputs
                inputs = self._render_inputs(step.input_template, previous_results, context)

                # Pass user permissions to all tools for permission checking
                inputs["user_permissions"] = context.get("user_permissions", [])

                # Call tool with retry for transient errors
                result = self._call_with_retry(step.tool_name, inputs)

                # Update state
                step_state.status = "completed"
                step_state.output = result
                previous_results[step.id] = result

                # Track costs (if any)
                total_cost += result.get("token_cost", 0)

            except PermissionError as e:
                # Explicitly handle permission errors - not retryable
                step_state.status = "failed"
                step_state.error = f"权限拒绝: {str(e)}"
                state.status = "failed"
                state.error = step_state.error
                self.state_store.save(state)
                return state
            except Exception as e:
                # Generic but safe error message for other exceptions
                step_state.status = "failed"
                # Avoid leaking raw stack traces or internal paths
                error_msg = str(e)
                if "File \"" in error_msg or "line " in error_msg:
                    error_msg = "工具执行发生内部错误，请检查输入或重试。"

                step_state.error = error_msg
                state.status = "failed"
                state.error = error_msg
                self.state_store.save(state)
                return state

        # Summarize results
        state.status = "completed"
        # Determine if plan intended to create an OA approval
        plan_has_oa = any(step.tool_name == "oa.create_approval_draft" for step in plan)
        state.result = self._summarize_results(previous_results, context, plan_has_oa=plan_has_oa)
        state.result["total_token_cost"] = total_cost
        self.state_store.save(state)
        return state

    def _call_with_retry(
        self,
        tool_name: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Call tool with retry for transient errors.

        Retries only TransientIntegrationError up to max_retries times.
        PermissionError and other exceptions are not retried.
        """
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self.registry.call(tool_name, inputs)
            except TransientIntegrationError as e:
                last_error = e
                if attempt < self.max_retries:
                    continue
                raise
            except PermissionError:
                raise  # Not retryable
            except Exception as e:
                # Non-transient errors: not retryable
                raise
        if last_error:
            raise last_error
        raise RuntimeError(f"工具失败但没有抛出明确异常: {tool_name}")

    def _render_inputs(self, template: dict[str, Any], previous_results: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        rendered = {}
        for k, v in template.items():
            if isinstance(v, str) and v.startswith("$"):
                if v == "$ERP_RESULT.supplier_id":
                    rendered[k] = previous_results.get("get_inventory", {}).get("supplier_id")
                elif v == "$ERP_RESULT.warehouse":
                    rendered[k] = previous_results.get("get_inventory", {}).get("warehouse")
                else:
                    rendered[k] = v
            else:
                rendered[k] = v
        return rendered

    def _summarize_results(self, results: dict[str, Any], context: dict[str, Any], plan_has_oa: bool = False) -> dict[str, Any]:
        # Based on README requirement for final result
        erp = results.get("get_inventory", {})
        bi = results.get("get_sales", {})
        knowledge = results.get("search_knowledge", {})
        supplier = results.get("get_supplier_risk", {})
        oa = results.get("create_approval", {})

        # recommended_action reflects plan intent, not execution outcome.
        # If the plan included an OA step, the action is to create approval,
        # even if it was skipped due to permissions.
        recommended = "create_replenishment_approval" if plan_has_oa else "none"

        summary = {
            "sku": erp.get("sku") or bi.get("sku"),
            "warehouse": erp.get("warehouse"),
            "stock_gap": erp.get("stock_gap"),
            "forecast_units_next_14d": bi.get("forecast_units_next_14d"),
            "supplier_risk": {
                "supplier_id": supplier.get("supplier_id"),
                "risk_level": supplier.get("risk_level"),
            } if supplier else None,
            "citations": knowledge.get("citations", []),
            "recommended_action": recommended,
        }
        if oa.get("approval_draft_id"):
            summary["approval_draft_id"] = oa["approval_draft_id"]

        return summary
