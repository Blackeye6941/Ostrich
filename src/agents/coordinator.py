"""
Two-Agent UI Automation System Orchestrator and Agent Runner Thread.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any

from agents.ui_selection_agent import UIElementSelectionAgent
from agents.function_selection_agent import FunctionSelectionAgent
from agents.executor import ActionExecutor

log = logging.getLogger("ui_automation_system")


class UIAutomationSystem:
    """Orchestrates Agent 1 (UI Element Selection), Agent 2 (Function Selection), and Action Execution."""

    def __init__(
        self,
        needle_model: Any | None = None,
        execute_actions: bool = False,
        dry_run: bool = False,
    ):
        self.execute_actions = execute_actions
        self.agent1 = UIElementSelectionAgent(needle_model=needle_model)
        self.agent2 = FunctionSelectionAgent(needle_model=needle_model)
        self.executor = ActionExecutor(dry_run=dry_run)

    def process_instruction(
        self,
        instruction: str,
        active_window: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Execute the two-agent workflow for a given user instruction.

        Parameters
        ----------
        instruction : str
            The user command / request.
        active_window : dict[str, Any] | None
            Thread-safe snapshot of the current active window context.

        Returns
        -------
        dict[str, Any]
            Execution summary containing status, selected_element, selected_function,
            arguments, and action execution report.
        """
        inst = instruction.strip()
        if not inst:
            return {"status": "error", "message": "Instruction is empty"}

        log.info("Processing instruction: '%s'", inst)

        # Agent 1: UI Element Selection (Grounding + Deterministic Pruning + LLM selection)
        selected_element = None
        if active_window and active_window.get("nodes"):
            selected_element = self.agent1.select_element(inst, active_window)

        # Agent 2: Function Selection (Needle model tool / action selection)
        fn_result = self.agent2.select_function(
            instruction=inst,
            selected_element=selected_element,
            active_window=active_window,
        )

        if not fn_result:
            return {
                "status": "error",
                "message": "Failed to determine function for instruction",
                "instruction": inst,
                "selected_element": selected_element,
                "selected_function": None,
                "arguments": {},
            }

        func_name = fn_result.get("function")
        arguments = fn_result.get("arguments", {})

        # Action Execution
        execution_report = None
        if self.execute_actions:
            execution_report = self.executor.execute(func_name, arguments)
            log.info("Execution report for %s: %s", func_name, execution_report)

        return {
            "status": "success",
            "instruction": inst,
            "selected_element": selected_element,
            "selected_function": func_name,
            "arguments": arguments,
            "execution": execution_report,
        }


def run_agent_worker(
    get_active_window_fn: Any,
    task_queue: queue.Queue,
    result_queue: queue.Queue,
    stop_event: threading.Event,
    needle_model: Any | None = None,
    execute_actions: bool = False,
    dry_run: bool = False,
):
    """Background worker thread executing both agents with shared access to active_window.

    Runs in a separate thread from run_atspi and never calls any Atspi methods directly.
    """
    log.info("Agent worker thread started")
    system = UIAutomationSystem(
        needle_model=needle_model,
        execute_actions=execute_actions,
        dry_run=dry_run,
    )

    while not stop_event.is_set():
        try:
            instruction = task_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        if instruction is None:
            break

        # Thread-safe read of shared active_window
        window_snapshot = get_active_window_fn()

        try:
            res = system.process_instruction(instruction, window_snapshot)
        except Exception as exc:
            log.exception("Error during agent workflow execution: %s", exc)
            res = {"status": "error", "message": str(exc)}

        result_queue.put(res)
        task_queue.task_done()

    log.info("Agent worker thread stopped")
