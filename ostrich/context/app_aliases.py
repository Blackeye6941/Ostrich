"""App name alias resolution."""
import re

_ALIASES = {
    "chrome": "google-chrome",
    "calculator": "gnome-calculator",
    "calc": "gnome-calculator",
    "terminal": "gnome-terminal",
    "files": "nautilus",
    "code": "code",
    "vscode": "code",
}

def resolve_app_name(raw: str) -> str:
    normalised = raw.strip().lower()
    without_exe = re.sub(r"\.exe$", "", normalised)
    return _ALIASES.get(normalised) or _ALIASES.get(without_exe) or raw
