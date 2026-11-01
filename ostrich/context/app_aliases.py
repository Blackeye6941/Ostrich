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



"""App name resolution: alias table first, then installed .desktop entries.

resolve_app_name(raw)  -> str            (kept: alias or the raw name)
find_desktop_entry(raw)-> (entry, tier)  match against installed .desktop files
launch_app(raw)        -> dict           resolve and start the app, never via a shell
"""
import configparser
import difflib
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional

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


# --------------------------------------------------------------------------
# .desktop index
# --------------------------------------------------------------------------
def _desktop_dirs():
    home = Path.home()
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    dirs = [data_home / "applications"]
    dirs += [Path(d) / "applications" for d in data_dirs if d]
    dirs += [
        Path("/var/lib/flatpak/exports/share/applications"),
        home / ".local/share/flatpak/exports/share/applications",
        Path("/var/lib/snapd/desktop/applications"),
    ]
    seen, out = set(), []
    for d in dirs:                      # earlier dirs win (user overrides system)
        if d not in seen and d.is_dir():
            seen.add(d)
            out.append(d)
    return out


def _parse(path: Path, base: Path) -> Optional[dict]:
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str                # keep key case (Name vs name)
    try:
        cp.read(path, encoding="utf-8")
        e = cp["Desktop Entry"]
    except (configparser.Error, KeyError, UnicodeDecodeError, OSError):
        return None
    if e.get("Type") != "Application":
        return None
    if e.get("NoDisplay", "").lower() == "true" or e.get("Hidden", "").lower() == "true":
        return None
    if not e.get("Exec") or not e.get("Name"):
        return None
    desktop_id = str(path.relative_to(base))[: -len(".desktop")].replace("/", "-")
    return {
        "id": desktop_id,
        "name": e["Name"],
        "generic": e.get("GenericName", ""),
        "keywords": [k.strip().lower() for k in e.get("Keywords", "").split(";") if k.strip()],
        "exec": e["Exec"],
        "path": str(path),
    }


_index: Optional[dict] = None


def load_index(refresh: bool = False) -> dict:
    """{desktop_id: entry}. Cached; pass refresh=True after installing apps."""
    global _index
    if _index is not None and not refresh:
        return _index
    idx: dict = {}
    for base in _desktop_dirs():
        for path in base.rglob("*.desktop"):
            entry = _parse(path, base)
            if entry and entry["id"] not in idx:
                idx[entry["id"]] = entry
    _index = idx
    return idx


# --------------------------------------------------------------------------
# Matching (most trustworthy tier first; stop at the first tier that hits)
# --------------------------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def find_desktop_entry(raw: str, fuzzy_cutoff: float = 0.85):
    """Return (entry, tier) for a unique match, (list_of_entries, tier) when
    several tie, or (None, None). Tiers: id, name, alias, token, fuzzy."""
    idx = load_index()
    q = _norm(re.sub(r"\.(exe|desktop)$", "", raw.strip().lower()))
    if not q:
        return None, None

    def pick(hits, tier):
        if not hits:
            return None
        return (hits[0] if len(hits) == 1 else hits), tier

    # 1. exact desktop id (org.gnome.Calculator, google-chrome, ...)
    hits = [e for e in idx.values() if _norm(e["id"]) == q or _norm(e["id"].split(".")[-1]) == q]
    if (r := pick(hits, "id")):
        return r
    # 2. exact display name or generic name ("Calculator", "Web Browser")
    hits = [e for e in idx.values() if _norm(e["name"]) == q or _norm(e["generic"]) == q]
    if (r := pick(hits, "name")):
        return r
    # 3. alias table, whose target may be a desktop id or a binary name
    target = _norm(resolve_app_name(raw))
    if target and target != q:
        hits = [e for e in idx.values()
                if _norm(e["id"]) == target or _norm(e["id"].split(".")[-1]) == target
                or _norm(os.path.basename(shlex.split(e["exec"])[0])) == target]
        if (r := pick(hits, "alias")):
            return r
    # 4. all query tokens appear in name or keywords
    toks = set(q.split())
    hits = [e for e in idx.values()
            if toks <= set(_norm(e["name"]).split()) | set(k for kw in e["keywords"] for k in _norm(kw).split())]
    if (r := pick(hits, "token")):
        return r
    # 5. fuzzy on name (typos, STT errors); high cutoff, best match only
    names = {_norm(e["name"]): e for e in idx.values()}
    close = difflib.get_close_matches(q, list(names), n=2, cutoff=fuzzy_cutoff)
    if close:
        best = names[close[0]]
        runner = difflib.SequenceMatcher(None, q, close[1]).ratio() if len(close) > 1 else 0
        if runner < difflib.SequenceMatcher(None, q, close[0]).ratio() - 0.05:
            return best, "fuzzy"
        return [names[c] for c in close], "fuzzy"
    return None, None


# --------------------------------------------------------------------------
# Launch (argv list, never shell=True: a misheard word can't become a command)
# --------------------------------------------------------------------------
_FIELD_CODES = re.compile(r"%[fFuUdDnNickvm]")


def _exec_argv(exec_line: str) -> list:
    argv = shlex.split(_FIELD_CODES.sub("", exec_line).replace("%%", "%"))
    return [a for a in argv if a]


def launch_entry(entry: dict) -> dict:
    gtk = shutil.which("gtk-launch")
    try:
        if gtk:
            cmd = [gtk, entry["id"]]
        else:
            cmd = _exec_argv(entry["exec"])
            if not cmd or not shutil.which(cmd[0]):
                return {"ok": False, "reason": f"executable not found: {cmd[:1]}"}
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return {"ok": True, "app": entry["name"], "id": entry["id"], "cmd": cmd}
    except OSError as exc:
        return {"ok": False, "reason": str(exc)}


def launch_app(raw: str) -> dict:
    """Resolve and start. Ambiguous matches are returned, not guessed."""
    entry, tier = find_desktop_entry(raw)
    if entry is None:
        # last resort: the alias or raw name as a binary on PATH
        name = resolve_app_name(raw)
        if shutil.which(name):
            subprocess.Popen([name], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return {"ok": True, "app": name, "tier": "path"}
        return {"ok": False, "reason": "not found", "query": raw}
    if isinstance(entry, list):
        return {"ok": False, "reason": "ambiguous", "tier": tier,
                "candidates": [e["name"] for e in entry]}
    result = launch_entry(entry)
    result["tier"] = tier
    return result
