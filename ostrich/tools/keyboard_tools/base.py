"""
Keyboard Tools - Base Interface
===============================
Abstract base class defining keyboard interaction interfaces.
(Placeholder / Extensible interface)
"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod


class KeyboardNavigator(ABC):
    """Abstract base class defining keyboard interaction interfaces."""

    @abstractmethod
    def type_text(self, text: str) -> dict:
        """Type given text string."""
        pass

    @abstractmethod
    def press_key(self, key: str) -> dict:
        """Press a specific key or key combination."""
        pass

    @abstractmethod
    def hotkey(self, *keys: str) -> dict:
        """Execute a key combination (e.g. 'ctrl', 'c')."""
        pass


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
        else:
            _keyboard_navigator_instance = LinuxKeyboardNavigator()
    return _keyboard_navigator_instance
