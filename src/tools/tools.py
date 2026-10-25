"""
Desktop Navigator Tools
=======================
A cross-platform collection of tools for interacting with the desktop environment.
Delegates to the active platform's desktop navigator (Windows / Linux).
"""

from tools.desktop_navigation import (
    DesktopNavigator,
    WindowsDesktopNavigator,
    LinuxDesktopNavigator,
    get_desktop_navigator,
    open_app,
    list_windows,
    switch_window,
    maximize_window,
    minimize_window,
    split_screen,
)

__all__ = [
    "DesktopNavigator",
    "WindowsDesktopNavigator",
    "LinuxDesktopNavigator",
    "get_desktop_navigator",
    "open_app",
    "list_windows",
    "switch_window",
    "maximize_window",
    "minimize_window",
    "split_screen",
]
