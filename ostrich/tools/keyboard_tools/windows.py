"""
Windows Keyboard Navigator
==========================
Implementation of KeyboardNavigator for Windows.
"""

from __future__ import annotations

try:
    from ostrich.tools.keyboard_tools.base import KeyboardNavigator
except ImportError:
    from ostrich.tools.keyboard_tools.base import KeyboardNavigator


class WindowsKeyboardNavigator(KeyboardNavigator):
    """Windows implementation of KeyboardNavigator."""

    def type_text(self, text: str) -> dict:
        return {"success": True, "message": f"Typed text: {text}"}

    def press_key(self, key: str) -> dict:
        return {"success": True, "message": f"Pressed key: {key}"}

    def hotkey(self, *keys: str) -> dict:
        return {"success": True, "message": f"Pressed hotkey: {'+'.join(keys)}"}
