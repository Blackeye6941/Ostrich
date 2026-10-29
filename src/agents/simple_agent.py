"""
Simple Tool Agent Module
========================
A lightweight agent that:
1. Takes a collection of tools (defaults to system tools).
2. Takes user input and uses needle `model.complete` to resolve the exact tool and arguments.
3. Provides an executor function that executes the resolved tool with arguments.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable

try:
    import needle
    _HAS_NEEDLE = True
except ImportError:
    _HAS_NEEDLE = False

try:
    from models.model import load_needle_model, system_tools, tools as all_tools
except ImportError:
    from src.models.model import load_needle_model, system_tools, tools as all_tools

log = logging.getLogger("simple_agent")


def execute_tool(
    tool_or_call: str | dict[str, Any],
    args: dict[str, Any] | None = None,
    tools_map: dict[str, Callable] | None = None,
) -> dict[str, Any]:
    """Execute a target tool by name with arguments.

    Supports two invocation formats:
    1. Separate parameters:
       execute_tool("set_volume", {"level": 50}, tools_map=...)
    2. Agent output dict:
       execute_tool({"tool": "set_volume", "args": {"level": 50}}, tools_map=...)
    """
    if isinstance(tool_or_call, dict):
        tool_name = tool_or_call.get("tool") or tool_or_call.get("function")
        call_args = dict(tool_or_call.get("args") or tool_or_call.get("arguments") or {})
        if args:
            call_args.update(args)
    else:
        tool_name = str(tool_or_call)
        call_args = dict(args or {})

    if not tool_name:
        return {
            "success": False,
            "tool": None,
            "error": "No tool name specified for execution.",
        }

    # If tools_map is not provided, build one from default system tools
    if tools_map is None:
        tools_map = {
            getattr(fn, "__name__", str(fn)): fn
            for fn in system_tools
        }

    if tool_name not in tools_map:
        return {
            "success": False,
            "tool": tool_name,
            "args": call_args,
            "error": f"Tool '{tool_name}' not found in registered tools ({list(tools_map.keys())}).",
        }

    fn = tools_map[tool_name]

    # Filter arguments to match target function signature if necessary
    try:
        sig = inspect.signature(fn)
        has_varkw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in sig.parameters.values()
        )
        if not has_varkw:
            valid_params = set(sig.parameters.keys())
            filtered_args = {k: v for k, v in call_args.items() if k in valid_params}
        else:
            filtered_args = call_args
    except Exception:
        filtered_args = call_args

    log.info("Executing %s(**%s)", tool_name, filtered_args)

    try:
        result = fn(**filtered_args)
        return {
            "success": True,
            "tool": tool_name,
            "args": filtered_args,
            "result": result,
        }
    except Exception as exc:
        log.exception("Execution error in %s: %s", tool_name, exc)
        return {
            "success": False,
            "tool": tool_name,
            "args": filtered_args,
            "error": str(exc),
        }


class SimpleAgent:
    """Simple Tool Calling Agent.

    Parameters
    ----------
    tools : list[Callable] | None
        List of callable tools to expose to the model. Defaults to system_tools.
    model : Any | None
        Pre-initialized Needle model or None to initialize from tools.
    """

    def __init__(
        self,
        tools: list[Callable] | None = None,
        model: Any | None = None,
    ):
        self.tools = list(tools) if tools is not None else list(system_tools)
        self.tools_map: dict[str, Callable] = {
            getattr(fn, "__name__", str(fn)): fn
            for fn in self.tools
        }

        if model is not None:
            self.model = model
        else:
            self.model = load_needle_model(custom_tools=self.tools)

    def predict(self, user_input: str) -> dict[str, Any]:
        """Use model.complete on user input to extract the exact tool and args."""
        if not user_input or not user_input.strip():
            return {
                "success": False,
                "tool": None,
                "args": {},
                "error": "Empty user input provided.",
            }

        input_clean = user_input.strip()

        try:
            response = self.model.complete(input_clean)
        except Exception as exc:
            log.exception("Model completion failed: %s", exc)
            return {
                "success": False,
                "tool": None,
                "args": {},
                "error": f"Model completion error: {exc}",
            }

        calls = response.get("function_calls") or []
        if not calls:
            calls = response.get("suppressed_calls") or []

        if not calls:
            return {
                "success": False,
                "tool": None,
                "args": {},
                "message": "No matching tool identified for instruction.",
                "raw_response": response,
            }

        chosen = calls[0]
        tool_name = chosen.get("name")
        args = dict(chosen.get("arguments") or {})

        return {
            "success": True,
            "tool": tool_name,
            "args": args,
            "raw_response": response,
        }

    def execute(
        self,
        tool_or_call: str | dict[str, Any],
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the tool with args using the agent's tool registry."""
        return execute_tool(tool_or_call, args, tools_map=self.tools_map)

    def run(self, user_input: str) -> dict[str, Any]:
        """End-to-end: take user input, predict tool and args, and execute it."""
        prediction = self.predict(user_input)
        if not prediction.get("success") or not prediction.get("tool"):
            return {
                "success": False,
                "input": user_input,
                "tool": None,
                "args": {},
                "error": prediction.get("error") or prediction.get("message") or "Tool selection failed",
                "prediction": prediction,
            }

        exec_res = self.execute(prediction)

        return {
            "success": exec_res.get("success", False),
            "input": user_input,
            "tool": prediction["tool"],
            "args": prediction["args"],
            "result": exec_res.get("result"),
            "error": exec_res.get("error"),
        }
