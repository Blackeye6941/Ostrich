# Tools Module Architecture & Specification (`src/tools`)

This document provides a comprehensive technical overview of the `src/tools` module in Ostrich. It details the directory structure, modular subpackages, class hierarchies, OS-specific implementations, dispatch mechanisms, and tool exposure patterns.

---

## 1. Directory Structure

```
src/tools/
├── __init__.py                     # Package re-exports for all navigator interfaces & factories
├── tools.py                        # Central re-exporter of needle tools and navigators for agent execution
├── README.md                       # Architecture & design documentation
│
├── ui_tools/                       # Window management and application launching
│   ├── __init__.py                 # Re-exports DesktopNavigator, platform implementations & tools
│   ├── base.py                     # DesktopNavigator ABC, OS factory, and needle tool wrappers
│   ├── windows.py                  # WindowsDesktopNavigator (Win32 API & PowerShell)
│   └── linux.py                    # LinuxDesktopNavigator (gdbus, GNOME Shell, wmctrl, xdotool)
│
├── mouse_tools/                    # Mouse interactions (click, double click, select, move)
│   ├── __init__.py                 # Re-exports MouseNavigator, platform implementations & tools
│   ├── base.py                     # MouseNavigator ABC, OS factory, and needle tool wrappers
│   ├── windows.py                  # WindowsMouseNavigator (ctypes user32 SetCursorPos/mouse_event)
│   └── linux.py                    # LinuxMouseNavigator (xdotool / ydotool)
│
├── keyboard_tools/                 # Keyboard typing & hotkey execution
│   ├── __init__.py                 # Re-exports KeyboardNavigator & factory
│   ├── base.py                     # KeyboardNavigator ABC and OS factory
│   ├── windows.py                  # WindowsKeyboardNavigator
│   └── linux.py                    # LinuxKeyboardNavigator
│
├── system_tools/                   # System environment details
│   ├── __init__.py                 # Re-exports SystemNavigator & factory
│   ├── base.py                     # SystemNavigator ABC and OS factory
│   ├── windows.py                  # WindowsSystemNavigator
│   └── linux.py                    # LinuxSystemNavigator
│
├── file_tools/                     # Filesystem interaction
│   ├── __init__.py                 # Re-exports FileNavigator & factory
│   ├── base.py                     # FileNavigator ABC and OS factory
│   ├── windows.py                  # WindowsFileNavigator
│   └── linux.py                    # LinuxFileNavigator
│
└── desktop_navigation/             # Backward-compatibility alias package forwarding to ui_tools
    ├── __init__.py
    ├── base.py
    ├── windows.py
    └── linux.py
```

---

## 2. High-Level Design Pattern

Each tool category adheres to the **Abstract Base Class + Strategy + Factory Dispatcher** pattern:

```mermaid
flowchart TD
    Consumer["Agent / Application"] --> ToolsEntry["src.tools.tools"]
    ToolsEntry --> Category["Tool Category Subpackage\n(ui_tools, mouse_tools, keyboard_tools, system_tools, file_tools)"]
    
    Category --> Factory["Factory Function\nget_<category>_navigator()"]
    Factory -->|platform.system() == 'Windows'| WinImpl["Windows Implementation\n(e.g., WindowsMouseNavigator)"]
    Factory -->|platform.system() == 'Linux'| LinImpl["Linux Implementation\n(e.g., LinuxMouseNavigator)"]
    
    WinImpl -.->|implements| BaseABC["Category ABC\n(e.g., MouseNavigator)"]
    LinImpl -.->|implements| BaseABC
```

---

## 3. Module Specifications

### 3.1 `ui_tools` (Desktop Navigation)
- **Base Class**: `DesktopNavigator`
- **Methods**:
  - `launch_app(app_name, args=None) -> dict`
  - `list_windows() -> dict`
  - `switch_window(target) -> dict`
  - `maximize_app(app_name) -> dict`
  - `minimize_app(app_name) -> dict`
  - `split_screen(left_target=None, right_target=None) -> dict`
- **Windows**: PowerShell + Win32 `user32.dll` (`ShowWindow`, `MoveWindow`, `SetForegroundWindow`).
- **Linux**: GNOME Shell D-Bus (`gdbus org.gnome.Shell.Extensions.Windows`), `wmctrl`, `xrandr`.

### 3.2 `mouse_tools` (Mouse Control)
- **Base Class**: `MouseNavigator`
- **Methods**:
  - `move(x, y) -> dict`
  - `click(x=None, y=None, button="left") -> dict`
  - `double_click(x=None, y=None, button="left") -> dict`
  - `select(start_x, start_y, end_x, end_y) -> dict`
- **Exported Needle Tools**: `mouse_move`, `mouse_click`, `mouse_double_click`, `mouse_select`.
- **Windows**: `ctypes.windll.user32` (`SetCursorPos`, `mouse_event`).
- **Linux**: `xdotool` (primary) and `ydotool` (Wayland fallback).

### 3.3 `keyboard_tools`
- **Base Class**: `KeyboardNavigator`
- **Methods**: `type_text(text)`, `press_key(key)`, `hotkey(*keys)`.

### 3.4 `system_tools`
- **Base Class**: `SystemNavigator`
- **Methods**:
  - `get_system_info() -> dict`: Comprehensive OS, CPU count, RAM usage, disk usage, and hostname.
  - `get_volume() -> dict`: Current volume (0-100) and mute state.
  - `set_volume(level: int) -> dict`: Set master audio volume (0-100).
  - `set_mute(mute: bool | None = None) -> dict`: Mute, unmute, or toggle mute state.
  - `get_brightness() -> dict`: Current display brightness (0-100).
  - `set_brightness(level: int) -> dict`: Set display brightness percentage (0-100).
  - `get_wifi_status() -> dict`: Wi-Fi power, connected SSID, signal strength, device interface.
  - `set_wifi(enabled: bool) -> dict`: Turn Wi-Fi radio on/off.
  - `scan_wifi() -> dict`: Scan and list available networks in range.
  - `connect_wifi(ssid: str, password: str | None = None) -> dict`: Connect to a Wi-Fi network.
  - `disconnect_wifi() -> dict`: Disconnect from current Wi-Fi.
  - `get_bluetooth_status() -> dict`: Bluetooth power status and connected devices.
  - `set_bluetooth(enabled: bool) -> dict`: Turn Bluetooth radio on/off.
  - `get_battery_status() -> dict`: Battery percentage, charging state, AC power plug status.
  - `lock_screen() -> dict`: Lock user desktop session.
- **Exported Needle Tools**: `get_system_info`, `get_volume`, `set_volume`, `set_mute`, `mute_volume`, `get_brightness`, `set_brightness`, `get_wifi_status`, `set_wifi`, `scan_wifi`, `connect_wifi`, `disconnect_wifi`, `get_bluetooth_status`, `set_bluetooth`, `get_battery_status`, `lock_screen`.
- **Windows**: Windows CoreAudio via PowerShell C#, WMI `WmiMonitorBrightness`, `netsh wlan`, PowerShell `Get-PnpDevice`, WMI `Win32_Battery`, `LockWorkStation`.
- **Linux**: PipeWire (`wpctl`), PulseAudio (`pactl`), ALSA (`amixer`), GNOME SettingsDaemon (`gdbus`), `brightnessctl`, NetworkManager (`nmcli`), `rfkill`, `bluetoothctl`, sysfs (`/sys/class/power_supply`, `/sys/class/backlight`), `/proc/meminfo`, `loginctl`.

### 3.5 `file_tools`
- **Base Class**: `FileNavigator`
- **Methods**: `list_files(path)`.
