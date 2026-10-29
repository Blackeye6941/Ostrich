"""
Linux File Navigator
====================
Implementation of FileNavigator for Linux.
"""

from __future__ import annotations

import os

try:
    from ostrich.tools.file_tools.base import FileNavigator
except ImportError:
    from ostrich.tools.file_tools.base import FileNavigator


class LinuxFileNavigator(FileNavigator):
    """Linux implementation of FileNavigator."""

    def list_files(self, path: str) -> dict:
        try:
            files = os.listdir(path)
            return {"success": True, "files": files}
        except Exception as e:
            return {"success": False, "message": str(e), "files": []}
