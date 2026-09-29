"""Narrow Git and path primitives for the local agent bridge (extracted subset).

Extracted from ``ask_ai_mcp.code_review_workspace`` (frozen source 725333c2) with the
review logic removed: the bounded Git read, the reparse and escape boundary checks,
the relative-path spelling check and the secret-bearing name pattern only. No review
snapshot, sanitization or patch-staging behaviour is carried over.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

_REPARSE_POINT = 0x400
_SECRET_NAME = re.compile(
    r"(?i)(^|/)(\.env(?:\.|$)|.*(?:secret|credential|private[_-]?key|token).*)"
)


class BridgePathError(RuntimeError):
    """Raised when a requested path crosses a configured boundary."""


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_reparse(path: Path) -> bool:
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return False
    return bool(getattr(stat, "st_file_attributes", 0) & _REPARSE_POINT) or path.is_symlink()


def _assert_no_reparse_escape(path: Path, root: Path) -> None:
    current = path
    while True:
        if _is_reparse(current):
            raise BridgePathError("reparse points are not accepted in review inputs")
        if current == root:
            break
        if not _is_within(current, root):
            raise BridgePathError("review input escaped its allow-listed root")
        current = current.parent


def _validate_relative(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or ":" in path.parts[0]
    ):
        raise BridgePathError("diff contains a non-relative path")
    return path.as_posix()


def _run_git(root: Path, *arguments: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise BridgePathError("Git is unavailable")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        [git, "-C", str(root), *arguments],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=60,
        creationflags=creationflags,
    )
    if completed.returncode != 0:
        raise BridgePathError("bounded Git snapshot command failed")
    try:
        return completed.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise BridgePathError("Git snapshot output was not UTF-8") from error
