from ostrich.tools.ui_tools import (
    open_app,
    list_windows,
    switch_window,
    maximize_window,
    minimize_window,
    split_screen,
)
from ostrich.tools.mouse_tools import (
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_select,
)
import needle

tools = [
    open_app,
    list_windows,
    switch_window,
    maximize_window,
    minimize_window,
    split_screen,
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_select,
]

nav_agent = needle.Needle(tools=tools)
