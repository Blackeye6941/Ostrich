"""
Desktop Navigation Tools
========================
Provides cross-platform desktop navigation capabilities for Windows and Linux.

- DesktopNavigator: Abstract base class defining navigation interfaces.
- WindowsDesktopNavigator: Implementation for Windows using PowerShell and Win32 APIs.
- LinuxDesktopNavigator: Implementation for Linux using gdbus (GNOME Shell / Extensions / Introspect)
  with support for window ID, process ID, and window title matching, plus wmctrl fallback.
"""

from __future__ import annotations

import ast
import json
import os
import platform
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Any

# Optional needle integration
try:
    import needle
    _HAS_NEEDLE = True
except ImportError:
    _HAS_NEEDLE = False

# Import app naming context resolution
try:
    from context import resolve_app_name
except ImportError:
    try:
        from src.context import resolve_app_name
    except ImportError:
        def resolve_app_name(raw: str) -> str:
            return raw


# ===========================================================================
# Base Desktop Navigator
# ===========================================================================

class DesktopNavigator(ABC):
    """Abstract base class for desktop navigation operations."""

    @abstractmethod
    def launch_app(self, app_name: str, args: list[str] | None = None) -> dict:
        """Launch an application by name or path with optional arguments."""
        pass

    @abstractmethod
    def maximize_app(self, app_name: str | int) -> dict:
        """Maximize an application window matched by name, title, PID, or window ID."""
        pass

    @abstractmethod
    def minimize_app(self, app_name: str | int) -> dict:
        """Minimize an application window matched by name, title, PID, or window ID."""
        pass

    @abstractmethod
    def list_windows(self) -> dict:
        """List currently open/visible application windows."""
        pass

    @abstractmethod
    def switch_window(self, target: str | int) -> dict:
        """Bring an application window to the foreground by name, title, PID, or window ID."""
        pass

    @abstractmethod
    def split_screen(
        self,
        left_target: str | int | None = None,
        right_target: str | int | None = None,
    ) -> dict:
        """Tile windows to the left and right halves of the screen."""
        pass

    # Aliases matching tools.py naming
    def open_app(self, app_name: str, args: list[str] | None = None) -> dict:
        return self.launch_app(app_name, args)

    def maximize_window(self, target: str | int) -> dict:
        return self.maximize_app(target)

    def minimize_window(self, target: str | int) -> dict:
        return self.minimize_app(target)

    def switch_app(self, target: str | int) -> dict:
        return self.switch_window(target)


# ===========================================================================
# Windows Desktop Navigator
# ===========================================================================

# Inline C# types loaded into PowerShell for Win32 API calls
_WIN32_TYPE = """
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
}
'@
"""

_SW_MINIMIZE = 6
_SW_MAXIMIZE = 3
_SW_RESTORE  = 9


class WindowsDesktopNavigator(DesktopNavigator):
    """Windows implementation using PowerShell and Win32 user32 APIs."""

    def _run_ps(self, command: str, timeout: int = 10) -> tuple[bool, str, str]:
        """Execute a command in a non-interactive PowerShell session."""
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
        except FileNotFoundError:
            return False, "", "PowerShell not found."
        except subprocess.TimeoutExpired:
            return False, "", "PowerShell command timed out."
        except OSError as exc:
            return False, "", str(exc)

    def _start_process(self, app_name: str, args: list[str] | None = None) -> dict:
        """Run Start-Process directly via PowerShell."""
        arg_fragment = ""
        if args:
            quoted = ", ".join(f'"{a}"' for a in args)
            arg_fragment = f" -ArgumentList {quoted}"

        ps_command = (
            f"$p = Start-Process {app_name}{arg_fragment} -PassThru; "
            f"Write-Output $p.Id"
        )

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_command],
                capture_output=True,
                text=True,
                timeout=15,
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or f"Exit code {result.returncode}"
                return {
                    "success": False,
                    "message": f"Start-Process failed for '{app_name}': {error_msg}",
                    "pid": None,
                }

            pid_str = result.stdout.strip()
            pid = int(pid_str) if pid_str.isdigit() else None
            return {
                "success": True,
                "message": f"Launched '{app_name}' via Start-Process"
                           + (f" (PID {pid})." if pid else "."),
                "pid": pid,
            }

        except FileNotFoundError:
            return {
                "success": False,
                "message": "PowerShell not found. Cannot use Start-Process.",
                "pid": None,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": f"Start-Process timed out while launching '{app_name}'.",
                "pid": None,
            }
        except OSError as exc:
            return {"success": False, "message": str(exc), "pid": None}

    def _show_window(self, target: str | int, nCmdShow: int, action_label: str) -> dict:
        """Find a window by title or PID and call ShowWindow(handle, nCmdShow)."""
        target_str = str(target).strip()

        # Build PowerShell filter supporting PID and title
        if target_str.isdigit():
            filter_clause = (
                f"($_.Id -eq {target_str}) -or "
                f"($_.MainWindowTitle -like '*{target_str}*')"
            )
        else:
            filter_clause = f"$_.MainWindowTitle -like '*{target_str}*'"

        ps_command = (
            f"{_WIN32_TYPE}"
            f"$w = Get-Process | "
            f"Where-Object {{ {filter_clause} }} | "
            f"Select-Object -First 1; "
            f"if (-not $w) {{ Write-Error 'NO_MATCH'; exit 1 }}; "
            f"[Win32]::ShowWindow($w.MainWindowHandle, {nCmdShow}) | Out-Null; "
            f"Write-Output \"$($w.Id)|$($w.MainWindowTitle)\""
        )

        ok, stdout, stderr = self._run_ps(ps_command, timeout=10)

        if not ok:
            if "NO_MATCH" in stderr:
                return {
                    "success": False,
                    "message": f"No open window found matching '{target}'.",
                    "pid": None,
                }
            return {
                "success": False,
                "message": stderr or f"Failed to {action_label} window '{target}'.",
                "pid": None,
            }

        pid, matched_title = (stdout.split("|", 1) + [""])[:2]
        return {
            "success": True,
            "message": f"{action_label.capitalize()}d window '{matched_title}' (PID {pid}).",
            "pid": int(pid) if pid.isdigit() else None,
        }

    def launch_app(self, app_name: str, args: list[str] | None = None) -> dict:
        """Open a desktop application by name on Windows."""
        canonical_name = resolve_app_name(app_name)
        return self._start_process(canonical_name, args or [])

    def list_windows(self) -> dict:
        """Return a list of all currently visible desktop windows on Windows."""
        ps_command = (
            "Get-Process | "
            "Where-Object { $_.MainWindowTitle -ne '' } | "
            "Select-Object Id, ProcessName, MainWindowTitle | "
            "ConvertTo-Json -Compress"
        )

        ok, stdout, stderr = self._run_ps(ps_command)

        if not ok:
            return {"success": False, "windows": [], "message": stderr or "Failed to list windows."}

        if not stdout:
            return {"success": True, "windows": [], "message": "No open windows found."}

        try:
            raw = json.loads(stdout)
            if isinstance(raw, dict):
                raw = [raw]
            windows = [
                {
                    "pid": entry["Id"],
                    "name": entry["ProcessName"],
                    "title": entry["MainWindowTitle"],
                }
                for entry in raw
            ]
            return {
                "success": True,
                "windows": windows,
                "message": f"Found {len(windows)} open window(s).",
            }
        except Exception as e:
            return {"success": False, "windows": [], "message": f"Failed to parse windows output: {e}"}

    def switch_window(self, target: str | int) -> dict:
        """Bring a desktop window to foreground by matching title or PID."""
        target_str = str(target).strip()
        if target_str.isdigit():
            filter_clause = (
                f"($_.Id -eq {target_str}) -or "
                f"($_.MainWindowTitle -like '*{target_str}*')"
            )
        else:
            filter_clause = f"$_.MainWindowTitle -like '*{target_str}*'"

        ps_command = (
            f"{_WIN32_TYPE}"
            f"$w = Get-Process | "
            f"Where-Object {{ {filter_clause} }} | "
            f"Select-Object -First 1; "
            f"if (-not $w) {{ Write-Error 'NO_MATCH'; exit 1 }}; "
            f"[Win32]::ShowWindow($w.MainWindowHandle, {_SW_RESTORE}) | Out-Null; "
            f"[Win32]::SetForegroundWindow($w.MainWindowHandle) | Out-Null; "
            f"Write-Output \"$($w.Id)|$($w.MainWindowTitle)\""
        )

        ok, stdout, stderr = self._run_ps(ps_command, timeout=10)

        if not ok:
            if "NO_MATCH" in stderr:
                return {
                    "success": False,
                    "message": f"No open window found matching '{target}'.",
                    "pid": None,
                }
            return {
                "success": False,
                "message": stderr or f"Failed to switch to window '{target}'.",
                "pid": None,
            }

        pid, matched_title = (stdout.split("|", 1) + [""])[:2]
        return {
            "success": True,
            "message": f"Activated window '{matched_title}' (PID {pid}).",
            "pid": int(pid) if pid.isdigit() else None,
        }

    def maximize_app(self, app_name: str | int) -> dict:
        """Maximize a desktop window by matching title or PID."""
        return self._show_window(app_name, _SW_MAXIMIZE, "maximize")

    def minimize_app(self, app_name: str | int) -> dict:
        """Minimize a desktop window by matching title or PID."""
        return self._show_window(app_name, _SW_MINIMIZE, "minimize")

    def split_screen(
        self,
        left_target: str | int | None = None,
        right_target: str | int | None = None,
    ) -> dict:
        """Position two windows side-by-side using Win32 MoveWindow."""
        # Query open windows
        wins_info = self.list_windows()
        windows = wins_info.get("windows", [])
        if not windows:
            return {"success": False, "message": "No open windows found to split."}

        # Resolve left and right target windows
        left_win = None
        right_win = None

        if left_target is not None:
            l_str = str(left_target).lower()
            left_win = next(
                (w for w in windows if l_str in w["title"].lower() or str(w["pid"]) == l_str),
                None,
            )
        if right_target is not None:
            r_str = str(right_target).lower()
            right_win = next(
                (w for w in windows if r_str in w["title"].lower() or str(w["pid"]) == r_str),
                None,
            )

        # Fallback to first two windows if targets are not specified
        if not left_win and windows:
            left_win = windows[0]
        if not right_win and len(windows) > 1:
            candidates = [w for w in windows if w != left_win]
            if candidates:
                right_win = candidates[0]

        ps_script_parts = [_WIN32_TYPE]
        ps_script_parts.append(
            "$w = [Win32]::GetSystemMetrics(0); "
            "$h = [Win32]::GetSystemMetrics(1); "
            "$half = [math]::Floor($w / 2);"
        )

        actions = []
        if left_win:
            ps_script_parts.append(
                f"$pLeft = Get-Process -Id {left_win['pid']} -ErrorAction SilentlyContinue; "
                f"if ($pLeft) {{ "
                f"[Win32]::ShowWindow($pLeft.MainWindowHandle, {_SW_RESTORE}) | Out-Null; "
                f"[Win32]::MoveWindow($pLeft.MainWindowHandle, 0, 0, $half, $h, $true) | Out-Null; "
                f"}}"
            )
            actions.append(f"Left: '{left_win['title']}' (PID {left_win['pid']})")

        if right_win and right_win != left_win:
            ps_script_parts.append(
                f"$pRight = Get-Process -Id {right_win['pid']} -ErrorAction SilentlyContinue; "
                f"if ($pRight) {{ "
                f"[Win32]::ShowWindow($pRight.MainWindowHandle, {_SW_RESTORE}) | Out-Null; "
                f"[Win32]::MoveWindow($pRight.MainWindowHandle, $half, 0, $half, $h, $true) | Out-Null; "
                f"}}"
            )
            actions.append(f"Right: '{right_win['title']}' (PID {right_win['pid']})")

        ok, _, stderr = self._run_ps(" ".join(ps_script_parts))
        if not ok:
            return {"success": False, "message": stderr or "Failed to split screen on Windows."}

        return {
            "success": True,
            "message": f"Split screen positioned: {', '.join(actions)}.",
            "left": left_win,
            "right": right_win,
        }


# ===========================================================================
# Linux Desktop Navigator (gdbus with window ID / PID support)
# ===========================================================================

# Common Linux app alias mapping
_LINUX_APP_ALIASES: dict[str, str] = {
    "chrome": "google-chrome",
    "google chrome": "google-chrome",
    "google-chrome": "google-chrome",
    "chromium": "chromium",
    "chromium-browser": "chromium-browser",
    "firefox": "firefox",
    "calc": "gnome-calculator",
    "calculator": "gnome-calculator",
    "gnome-calc": "gnome-calculator",
    "terminal": "gnome-terminal",
    "gedit": "gedit",
    "text editor": "gedit",
    "editor": "gedit",
    "files": "nautilus",
    "nautilus": "nautilus",
    "code": "code",
    "vscode": "code",
    "vs code": "code",
}


class LinuxDesktopNavigator(DesktopNavigator):
    """Linux implementation using gdbus to communicate with GNOME Shell and window manager.

    Supports querying and manipulating windows by:
    - Window ID (winid)
    - Process ID (PID)
    - Application name / window title / wm_class
    """

    def __init__(self) -> None:
        self.gnome_windows_dest = "org.gnome.Shell"
        self.gnome_windows_path = "/org/gnome/Shell/Extensions/Windows"
        self.gnome_windows_iface = "org.gnome.Shell.Extensions.Windows"

    def _call_gdbus(
        self,
        method: str,
        args: list[str] | None = None,
        dest: str | None = None,
        path: str | None = None,
        iface: str | None = None,
        timeout: int = 10,
    ) -> tuple[bool, str, str]:
        """Call a method via gdbus CLI."""
        target_dest = dest or self.gnome_windows_dest
        target_path = path or self.gnome_windows_path
        target_iface = iface or self.gnome_windows_iface

        cmd = [
            "gdbus", "call", "--session",
            "--dest", target_dest,
            "--object-path", target_path,
            "--method", f"{target_iface}.{method}",
        ]
        if args:
            cmd.extend(str(a) for a in args)

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
        except FileNotFoundError:
            return False, "", "gdbus executable not found."
        except subprocess.TimeoutExpired:
            return False, "", "gdbus call timed out."
        except OSError as e:
            return False, "", str(e)

    def _get_screen_size(self) -> tuple[int, int]:
        """Fetch screen dimensions via gdbus org.gnome.Shell.Introspect ScreenSize."""
        cmd = [
            "gdbus", "call", "--session",
            "--dest", "org.gnome.Shell.Introspect",
            "--object-path", "/org/gnome/Shell/Introspect",
            "--method", "org.freedesktop.DBus.Properties.Get",
            "org.gnome.Shell.Introspect", "ScreenSize",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                nums = re.findall(r"\d+", res.stdout)
                if len(nums) >= 2:
                    return int(nums[0]), int(nums[1])
        except Exception:
            pass

        # Fallback to xrandr or default 1920x1080
        try:
            res = subprocess.run(["xrandr"], capture_output=True, text=True, timeout=5)
            match = re.search(r"current\s+(\d+)\s*x\s*(\d+)", res.stdout)
            if match:
                return int(match.group(1)), int(match.group(2))
        except Exception:
            pass

        return 1920, 1080

    def _list_windows_gdbus(self) -> list[dict]:
        """Query open windows from the GNOME Shell Windows extension via gdbus."""
        ok, stdout, _ = self._call_gdbus("List")
        if not ok or not stdout:
            return []

        try:
            val = ast.literal_eval(stdout)
            raw_json = val[0] if isinstance(val, (tuple, list)) else val
            windows = json.loads(raw_json)
            normalized = []
            for w in windows:
                # Filter out background desktop icons if present
                is_desktop = w.get("frame_type") == 7 or w.get("window_type") == 1
                normalized.append({
                    "id": w.get("id"),
                    "pid": w.get("pid"),
                    "name": w.get("wm_class_instance") or w.get("wm_class") or "",
                    "wm_class": w.get("wm_class", ""),
                    "wm_class_instance": w.get("wm_class_instance", ""),
                    "title": w.get("title", ""),
                    "focus": w.get("focus", False),
                    "is_desktop": is_desktop,
                })
            return normalized
        except Exception:
            return []

    def _list_windows_wmctrl(self) -> list[dict]:
        """Fallback to wmctrl -lp when gdbus is unavailable or on non-GNOME desktops."""
        try:
            res = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=5)
            if res.returncode != 0:
                return []
            windows = []
            for line in res.stdout.strip().splitlines():
                parts = line.split(None, 4)
                if len(parts) >= 5:
                    win_id_hex, ws, pid_str, host, title = parts
                    pid = int(pid_str) if pid_str.isdigit() else None
                    try:
                        win_id = int(win_id_hex, 16)
                    except ValueError:
                        win_id = win_id_hex
                    windows.append({
                        "id": win_id,
                        "pid": pid,
                        "name": title,
                        "wm_class": "",
                        "wm_class_instance": "",
                        "title": title,
                        "focus": False,
                        "is_desktop": ws == "-1",
                    })
            return windows
        except Exception:
            return []

    def list_windows(self) -> dict:
        """Return a list of all currently visible desktop windows on Linux."""
        windows = self._list_windows_gdbus()
        if not windows:
            windows = self._list_windows_wmctrl()

        return {
            "success": True,
            "windows": windows,
            "message": f"Found {len(windows)} open window(s).",
        }

    def _find_window(self, target: str | int) -> dict | None:
        """Find a window matching window ID, process ID, title, or application name."""
        win_list = self.list_windows().get("windows", [])
        if not win_list:
            return None

        target_str = str(target).strip()
        is_num = target_str.isdigit()

        # 1. Match Window ID directly
        if is_num:
            target_int = int(target_str)
            for w in win_list:
                if w.get("id") == target_int:
                    return w

        # 2. Match Process ID (PID) directly
        if is_num:
            target_int = int(target_str)
            for w in win_list:
                if w.get("pid") == target_int:
                    return w

        # 3. Match by canonical alias
        alias_name = _LINUX_APP_ALIASES.get(target_str.lower(), target_str.lower())

        # Exact / Substring match on wm_class, wm_class_instance, or title
        target_lower = target_str.lower()
        for w in win_list:
            wm_class = (w.get("wm_class") or "").lower()
            wm_instance = (w.get("wm_class_instance") or "").lower()
            title = (w.get("title") or "").lower()
            name = (w.get("name") or "").lower()

            if (
                target_lower in title
                or target_lower in wm_class
                or target_lower in wm_instance
                or target_lower in name
                or alias_name in wm_class
                or alias_name in wm_instance
            ):
                return w

        return None

    def launch_app(self, app_name: str, args: list[str] | None = None) -> dict:
        """Launch an application on Linux using non-blocking subprocess with alias resolution."""
        raw_name = app_name.strip()
        canonical_cmd = _LINUX_APP_ALIASES.get(raw_name.lower(), raw_name)

        # Check if binary is in PATH, otherwise try gtk-launch
        cmd_path = shutil.which(canonical_cmd) or shutil.which(raw_name)

        launch_args = args or []
        try:
            if cmd_path:
                proc = subprocess.Popen(
                    [cmd_path] + launch_args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return {
                    "success": True,
                    "message": f"Launched '{canonical_cmd}' (PID {proc.pid}).",
                    "pid": proc.pid,
                }

            # If gtk-launch exists, try launching by desktop name
            if shutil.which("gtk-launch"):
                proc = subprocess.Popen(
                    ["gtk-launch", raw_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return {
                    "success": True,
                    "message": f"Launched '{raw_name}' via gtk-launch (PID {proc.pid}).",
                    "pid": proc.pid,
                }

            # Direct fallback execution attempt
            proc = subprocess.Popen(
                [raw_name] + launch_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return {
                "success": True,
                "message": f"Launched '{raw_name}' (PID {proc.pid}).",
                "pid": proc.pid,
            }

        except FileNotFoundError:
            return {
                "success": False,
                "message": f"Application or command '{app_name}' not found.",
                "pid": None,
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"Failed to launch '{app_name}': {exc}",
                "pid": None,
            }

    def switch_window(self, target: str | int) -> dict:
        """Bring a desktop window to the foreground by window ID, PID, or title."""
        win = self._find_window(target)
        if not win:
            return {
                "success": False,
                "message": f"No open window found matching '{target}'.",
                "pid": None,
                "id": None,
            }

        win_id = win.get("id")
        win_pid = win.get("pid")
        title = win.get("title", "")

        # Try gdbus Activate
        if win_id is not None:
            ok, _, stderr = self._call_gdbus("Activate", [str(win_id)])
            if ok:
                return {
                    "success": True,
                    "message": f"Activated window '{title}' (PID {win_pid}, ID {win_id}).",
                    "pid": win_pid,
                    "id": win_id,
                }

        # Fallback to wmctrl
        if win_id is not None:
            try:
                hex_id = hex(win_id) if isinstance(win_id, int) else str(win_id)
                res = subprocess.run(["wmctrl", "-ia", hex_id], capture_output=True, text=True)
                if res.returncode == 0:
                    return {
                        "success": True,
                        "message": f"Activated window '{title}' via wmctrl (PID {win_pid}, ID {win_id}).",
                        "pid": win_pid,
                        "id": win_id,
                    }
            except Exception:
                pass

        return {
            "success": False,
            "message": f"Failed to activate window '{title}'.",
            "pid": win_pid,
            "id": win_id,
        }

    def maximize_app(self, app_name: str | int) -> dict:
        """Maximize an application window using gdbus by window ID, PID, or title."""
        win = self._find_window(app_name)
        if not win:
            return {
                "success": False,
                "message": f"No open window found matching '{app_name}'.",
                "pid": None,
                "id": None,
            }

        win_id = win.get("id")
        win_pid = win.get("pid")
        title = win.get("title", "")

        # Try gdbus Maximize
        if win_id is not None:
            ok, _, stderr = self._call_gdbus("Maximize", [str(win_id)])
            if ok:
                return {
                    "success": True,
                    "message": f"Maximized window '{title}' (PID {win_pid}, ID {win_id}).",
                    "pid": win_pid,
                    "id": win_id,
                }

        # Fallback to wmctrl
        if win_id is not None:
            try:
                hex_id = hex(win_id) if isinstance(win_id, int) else str(win_id)
                res = subprocess.run(
                    ["wmctrl", "-ir", hex_id, "-b", "add,maximized_horz,maximized_vert"],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    return {
                        "success": True,
                        "message": f"Maximized window '{title}' via wmctrl (PID {win_pid}, ID {win_id}).",
                        "pid": win_pid,
                        "id": win_id,
                    }
            except Exception:
                pass

        return {
            "success": False,
            "message": f"Failed to maximize window '{title}'.",
            "pid": win_pid,
            "id": win_id,
        }

    def minimize_app(self, app_name: str | int) -> dict:
        """Minimize an application window using gdbus by window ID, PID, or title."""
        win = self._find_window(app_name)
        if not win:
            return {
                "success": False,
                "message": f"No open window found matching '{app_name}'.",
                "pid": None,
                "id": None,
            }

        win_id = win.get("id")
        win_pid = win.get("pid")
        title = win.get("title", "")

        # Try gdbus Minimize
        if win_id is not None:
            ok, _, stderr = self._call_gdbus("Minimize", [str(win_id)])
            if ok:
                return {
                    "success": True,
                    "message": f"Minimized window '{title}' (PID {win_pid}, ID {win_id}).",
                    "pid": win_pid,
                    "id": win_id,
                }

        # Fallback to xdotool / wmctrl
        if win_id is not None and shutil.which("xdotool"):
            try:
                res = subprocess.run(
                    ["xdotool", "windowminimize", str(win_id)],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    return {
                        "success": True,
                        "message": f"Minimized window '{title}' via xdotool (PID {win_pid}, ID {win_id}).",
                        "pid": win_pid,
                        "id": win_id,
                    }
            except Exception:
                pass

        return {
            "success": False,
            "message": f"Failed to minimize window '{title}'.",
            "pid": win_pid,
            "id": win_id,
        }

    def split_screen(
        self,
        left_target: str | int | None = None,
        right_target: str | int | None = None,
    ) -> dict:
        """Split and tile two windows side-by-side using gdbus MoveResize."""
        win_list = [w for w in self.list_windows().get("windows", []) if not w.get("is_desktop")]
        if not win_list:
            return {"success": False, "message": "No open application windows found to split."}

        left_win = None
        right_win = None

        if left_target is not None:
            left_win = self._find_window(left_target)
        if right_target is not None:
            right_win = self._find_window(right_target)

        # Default to first two windows if not explicitly given
        if not left_win and win_list:
            left_win = win_list[0]
        if not right_win and len(win_list) > 1:
            remaining = [w for w in win_list if w.get("id") != (left_win.get("id") if left_win else None)]
            if remaining:
                right_win = remaining[0]

        screen_w, screen_h = self._get_screen_size()
        half_w = screen_w // 2

        results = []

        # Position Left Window: (x=0, y=0, width=half_w, height=screen_h)
        if left_win and left_win.get("id") is not None:
            lid = left_win["id"]
            self._call_gdbus("Unmaximize", [str(lid)])
            ok_move, _, _ = self._call_gdbus("MoveResize", [str(lid), "0", "0", str(half_w), str(screen_h)])
            self._call_gdbus("Activate", [str(lid)])
            results.append(f"Left: '{left_win.get('title')}' (ID {lid}, PID {left_win.get('pid')})")

        # Position Right Window: (x=half_w, y=0, width=half_w, height=screen_h)
        if right_win and right_win.get("id") is not None and right_win != left_win:
            rid = right_win["id"]
            self._call_gdbus("Unmaximize", [str(rid)])
            ok_move, _, _ = self._call_gdbus("MoveResize", [str(rid), str(half_w), "0", str(half_w), str(screen_h)])
            self._call_gdbus("Activate", [str(rid)])
            results.append(f"Right: '{right_win.get('title')}' (ID {rid}, PID {right_win.get('pid')})")

        if not results:
            return {"success": False, "message": "Could not arrange windows for split screen."}

        return {
            "success": True,
            "message": f"Split screen positioned: {', '.join(results)}.",
            "left": left_win,
            "right": right_win,
        }


# ===========================================================================
# Factory and Global Dispatcher
# ===========================================================================

_navigator_instance: DesktopNavigator | None = None


def get_desktop_navigator() -> DesktopNavigator:
    """Return the DesktopNavigator instance appropriate for the current OS."""
    global _navigator_instance
    if _navigator_instance is None:
        if platform.system().lower() == "windows":
            _navigator_instance = WindowsDesktopNavigator()
        else:
            _navigator_instance = LinuxDesktopNavigator()
    return _navigator_instance


# ===========================================================================
# Needle Tool Wrappers (Exported tools compatible with agent execution)
# ===========================================================================

def open_app(app_name: str, args: list[str] | None = None) -> dict:
    """Open or launch a desktop application by name.

    Parameters
    ----------
    app_name : str
        The application to open (e.g. "notepad", "calc", "chrome", "code", "terminal").
        Human-friendly names like "Google Chrome" or "Calculator" are accepted
        and resolved across platforms.
    args : list[str] | None
        Optional CLI arguments to pass to the application.

    Returns
    -------
    dict
        {"success": bool, "message": str, "pid": int | None}

    Examples
    --------
    >>> open_app("chrome")
    {'success': True, 'message': "Launched 'google-chrome' (PID 1234).", 'pid': 1234}
    """
    return get_desktop_navigator().launch_app(app_name, args)


def list_windows() -> dict:
    """Return a list of all currently visible desktop windows.

    Returns
    -------
    dict
        {"success": bool, "windows": list[dict], "message": str}

        Each window entry includes:
        - pid   (int)  - process ID
        - id    (int)  - window ID (Linux/X11)
        - name  (str)  - process or application name
        - title (str)  - window title bar text

    Examples
    --------
    >>> list_windows()
    {'success': True, 'windows': [{'pid': 1234, 'title': 'Google Chrome'}], 'message': 'Found 1 open window(s).'}
    """
    return get_desktop_navigator().list_windows()


def switch_window(title: str) -> dict:
    """Bring a desktop window to the foreground by matching its title, PID, or window ID.

    The match is case-insensitive and partial.

    Parameters
    ----------
    title : str
        A substring of the window title, application name, PID, or window ID.

    Returns
    -------
    dict
        {"success": bool, "message": str, "pid": int | None}

    Examples
    --------
    >>> switch_window("Notepad")
    {'success': True, 'message': "Activated window 'Untitled - Notepad' (PID 1234).", 'pid': 1234}
    """
    return get_desktop_navigator().switch_window(title)


def maximize_window(title: str) -> dict:
    """Maximize a desktop window by matching its title, PID, or window ID.

    Parameters
    ----------
    title : str
        A substring of the window title, application name, PID, or window ID.

    Returns
    -------
    dict
        {"success": bool, "message": str, "pid": int | None}

    Examples
    --------
    >>> maximize_window("Chrome")
    {'success': True, 'message': "Maximized window 'Google Chrome' (PID 5678).", 'pid': 5678}
    """
    return get_desktop_navigator().maximize_app(title)


def minimize_window(title: str) -> dict:
    """Minimize a desktop window to the taskbar/dock by matching its title, PID, or window ID.

    Parameters
    ----------
    title : str
        A substring of the window title, application name, PID, or window ID.

    Returns
    -------
    dict
        {"success": bool, "message": str, "pid": int | None}

    Examples
    --------
    >>> minimize_window("Chrome")
    {'success': True, 'message': "Minimized window 'Google Chrome' (PID 5678).", 'pid': 5678}
    """
    return get_desktop_navigator().minimize_app(title)


def split_screen(
    left_target: str | None = None,
    right_target: str | None = None,
) -> dict:
    """Tile desktop windows side-by-side to split the screen into left and right halves.

    Parameters
    ----------
    left_target : str | None
        Window title, PID, or app name for the left half. If None, the first active window is used.
    right_target : str | None
        Window title, PID, or app name for the right half. If None, the second active window is used.

    Returns
    -------
    dict
        {"success": bool, "message": str, "left": dict | None, "right": dict | None}

    Examples
    --------
    >>> split_screen("code", "chrome")
    {'success': True, 'message': "Split screen positioned: Left: 'code', Right: 'chrome'."}
    """
    return get_desktop_navigator().split_screen(left_target, right_target)


# Apply needle decorators if needle is available
if _HAS_NEEDLE:
    open_app = needle.tool(open_app)
    list_windows = needle.tool(list_windows)
    switch_window = needle.tool(switch_window)
    maximize_window = needle.tool(maximize_window)
    minimize_window = needle.tool(minimize_window)
    split_screen = needle.tool(split_screen)
