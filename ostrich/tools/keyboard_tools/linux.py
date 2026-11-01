"""
Linux Keyboard Navigator
========================
Implementation of KeyboardNavigator for Linux.
"""

from __future__ import annotations

try:
    from ostrich.tools.keyboard_tools.base import KeyboardNavigator
except ImportError:
    from ostrich.tools.keyboard_tools.base import KeyboardNavigator


import subprocess

class LinuxKeyboardNavigator(KeyboardNavigator):
    """Linux implementation of KeyboardNavigator using ydotool."""

    def _execute(self, *args: str) -> dict:
        try:
            result = subprocess.run(
                ["ydotool", *args],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )

            return {
                "success": True,
                "message": result.stdout.strip() or "Keyboard action executed",
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": "Keyboard action timed out",
            }

        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "message": e.stderr.strip() or str(e),
            }

        except FileNotFoundError:
            return {
                "success": False,
                "message": "ydotool is not installed or not in PATH",
            }

        except Exception as e:
            return {
                "success": False,
                "message": str(e),
            }

    def type_text(self, text: str) -> dict:
        """Type text into the currently focused application."""
        result = self._execute("type", "--", text)

        if result["success"]:
            result["message"] = f"Typed text: {text}"

        return result

    def press_key(self, key: str) -> dict:
        """Press a single key."""
        result = self._execute("key", key)

        if result["success"]:
            result["message"] = f"Pressed key: {key}"

        return result

    def hotkey(self, *keys: str) -> dict:
        """Press a keyboard combination."""
        if not keys:
            return {
                "success": False,
                "message": "No keys provided",
            }

        key_combination = "+".join(keys)

        result = self._execute("key", key_combination)

        if result["success"]:
            result["message"] = f"Pressed hotkey: {key_combination}"

        return result
