"""Use a patched SQLite on Windows CPython installations with compatible wheels."""

import platform
import sys

WINDOWS_WAL = (
    sys.platform == "win32"
    and sys.implementation.name == "cpython"
    and platform.machine() in {"AMD64", "x86"}
)
if WINDOWS_WAL:
    import pysqlite3 as sqlite3

    # The standard Windows 3.11/3.12 runners ship older, affected SQLite builds.
    if sqlite3.sqlite_version_info < (3, 51, 3):
        raise RuntimeError("Windows coordination needs SQLite with the WAL reset fix")
else:
    import sqlite3

__all__ = ["WINDOWS_WAL", "sqlite3"]
