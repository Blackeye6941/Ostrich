"""
Desktop Navigation Compatibility Layer
======================================
Re-exports DesktopNavigator from tools.ui_tools for backward compatibility.
"""

from tools.ui_tools import (
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
