"""
Keyboard Tools - Base Interface
===============================
Abstract base class and unified interface for keyboard interactions:
- type_text
- press_key
- hotkey
"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod

# Optional needle integration
try:
    import needle
    _HAS_NEEDLE = True
except ImportError:
    _HAS_NEEDLE = False


class KeyboardNavigator(ABC):
    """Abstract base class defining keyboard interaction interfaces."""

    @abstractmethod
    def type_text(self, text: str) -> dict:
        """Type given text string."""
        pass

    @abstractmethod
    def press_key(self, key: str) -> dict:
        """Press a specific key."""
        pass

    @abstractmethod
    def hotkey(self, *keys: str) -> dict:
        """Execute a key combination (e.g. 'ctrl', 'c')."""
        pass


# Platform-specific implementations
try:
    from ostrich.tools.keyboard_tools.windows import WindowsKeyboardNavigator
    from ostrich.tools.keyboard_tools.linux import LinuxKeyboardNavigator
except ImportError:
    from ostrich.tools.keyboard_tools.windows import WindowsKeyboardNavigator
    from ostrich.tools.keyboard_tools.linux import LinuxKeyboardNavigator


_keyboard_navigator_instance: KeyboardNavigator | None = None


def get_keyboard_navigator() -> KeyboardNavigator:
    """Return the KeyboardNavigator instance appropriate for the current OS."""

    global _keyboard_navigator_instance

    if _keyboard_navigator_instance is None:
        if platform.system().lower() == "windows":
            _keyboard_navigator_instance = WindowsKeyboardNavigator()
        elif platform.system().lower() == "linux":
            _keyboard_navigator_instance = LinuxKeyboardNavigator()
        else:
            raise NotImplementedError(
                f"Keyboard navigation is not supported on {platform.system()}"
            )

    return _keyboard_navigator_instance


# ---------------------------------------------------------
# Exported tool functions
# ---------------------------------------------------------

def keyboard_type_text(text: str) -> dict:
    """Type text into the currently focused application."""
    return get_keyboard_navigator().type_text(text)


def keyboard_press_key(key: str) -> dict:
    """Press a specific keyboard key."""
    return get_keyboard_navigator().press_key(key)


def keyboard_hotkey(*keys: str) -> dict:
    """Execute a keyboard shortcut."""
    return get_keyboard_navigator().hotkey(*keys)


# ---------------------------------------------------------
# Apply needle decorators if needle is available
# ---------------------------------------------------------

if _HAS_NEEDLE:
    keyboard_type_text = needle.tool(keyboard_type_text)
    keyboard_press_key = needle.tool(keyboard_press_key)
    keyboard_hotkey = needle.tool(keyboard_hotkey)