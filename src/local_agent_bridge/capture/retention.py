"""File-length quota and whole sealed-bundle rolling for two isolated domains.

All cooperating writers take one Windows byte-range lock before measuring or
changing a domain. Unknown files and partial bundles count against the quota but
are never rolled. This is a file-length budget, not an NTFS allocation meter.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import msvcrt
import os
import stat
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

DEFAULT_LIMIT = 100 * 1024 * 1024
_LOCK_BYTES = b"\0"
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


class StorageError(RuntimeError):
    """A session domain cannot safely reserve or retain more bytes."""


def _canonical_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise StorageError("session reference ID is invalid") from error
    if str(parsed) != value:
        raise StorageError("session reference ID is not canonical")
    return value


def state_root(domain: str) -> Path:
    if domain not in {"sessions", "shadow"}:
        raise StorageError("unknown storage domain")
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise StorageError("LOCALAPPDATA is unavailable")
    return Path(local) / "LocalAgentBridge" / domain


def _plain_file_size(path: Path) -> int:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise StorageError("non-regular file in session storage")
    return info.st_size


def _require_plain_directory_chain(path: Path) -> None:
    current = path
    while True:
        if current.exists() or current.is_symlink() or current.is_junction():
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise StorageError("reparse or non-directory in session storage path")
        if current.parent == current:
            return
        current = current.parent


def _tree_bytes(root: Path) -> int:
    total = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            item = Path(base) / name
            info = item.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise StorageError("reparse directory in session storage")
        for name in files:
            total += _plain_file_size(Path(base) / name)
    return total


def peek_status(domain: str) -> dict[str, object]:
    """Read-only best-effort status; creates no directories or credential access."""
    root = state_root(domain)
    _require_plain_directory_chain(root)
    if not root.exists():
        return {
            "domain": domain,
            "limit_bytes": DEFAULT_LIMIT,
            "used_file_bytes": 0,
            "active_or_partial": 0,
            "partial_ids": [],
            "partial_ids_omitted": 0,
            "seal_markers": 0,
        }
    if root.is_symlink() or not root.is_dir():
        raise StorageError("session storage root is not a plain directory")
    used = _tree_bytes(root)
    active = sealed = 0
    partial_ids: list[str] = []
    for child in root.iterdir():
        if child.is_dir() and (child / "open.json").is_file():
            if (child / "seal.json").is_file():
                sealed += 1
            else:
                active += 1
                if len(partial_ids) < 32:
                    partial_ids.append(child.name)
    return {
        "domain": domain,
        "limit_bytes": DEFAULT_LIMIT,
        "used_file_bytes": used,
        "active_or_partial": active,
        "seal_markers": sealed,
        "partial_ids": sorted(partial_ids),
        "partial_ids_omitted": active - len(partial_ids),
    }


class RetentionDomain:
    """Cooperative writer API. A verifier is required before any bundle deletion."""

    def __init__(
        self,
        domain: str,
        *,
        root: Path | None = None,
        limit: int = DEFAULT_LIMIT,
        terminal_reserve: int = 4096,
        receipt_reserve: int = 4096,
        protect_directory: Callable[[Path], None] | None = None,
        verify_bundle: Callable[[Path], dict] | None = None,
    ) -> None:
        if domain not in {"sessions", "shadow"} or limit < 1:
            raise StorageError("invalid storage domain or limit")
        self.domain = domain
        self.root = root or state_root(domain)
        self.limit = limit
        self.terminal_reserve = terminal_reserve
        self.receipt_reserve = receipt_reserve
        self.protect_directory = protect_directory
        self.verify_bundle = verify_bundle
        self._root_ready = False
        with _PROCESS_LOCKS_GUARD:
            self._process_lock = _PROCESS_LOCKS.setdefault(
                str(self.root.resolve()), threading.RLock()
            )

    def _ensure_root(self) -> None:
        # The default user state root is the only production root. Tests inject a
        # separate path and never read or write the real user state.
        with self._process_lock:
            if self._root_ready:
                return
            _require_plain_directory_chain(self.root)
            if not self.root.parent.exists():
                self.root.parent.mkdir(parents=True, exist_ok=True)
            _require_plain_directory_chain(self.root)
            if self.protect_directory:
                self.protect_directory(self.root.parent)
            if not self.root.exists():
                self.root.mkdir(exist_ok=True)
            _require_plain_directory_chain(self.root)
            if self.protect_directory:
                self.protect_directory(self.root)
            self._root_ready = True

    @contextmanager
    def locked(self) -> Iterator[None]:
        self._ensure_root()
        _require_plain_directory_chain(self.root)
        with self._process_lock:
            lock_path = self.root / ".quota.lock"
            if lock_path.exists() or lock_path.is_symlink() or lock_path.is_junction():
                _plain_file_size(lock_path)
            with lock_path.open("a+b") as stream:
                if stream.tell() == 0 and lock_path.stat().st_size == 0:
                    stream.write(_LOCK_BYTES)
                    stream.flush()
                    os.fsync(stream.fileno())
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                except OSError as error:
                    raise StorageError("session quota lock unavailable") from error
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def used_bytes(self) -> int:
        with self.locked():
            return _tree_bytes(self.root)

    def _active_count(self) -> int:
        return sum(
            1
            for child in self.root.iterdir()
            if child.is_dir()
            and (child / "open.json").is_file()
            and not (child / "seal.json").exists()
        )

    def _eligible(
        self, protected_ids: frozenset[str] = frozenset()
    ) -> list[tuple[str, Path, dict]]:
        if self.verify_bundle is None:
            return []
        candidates = []
        for child in self.root.iterdir():
            if not child.is_dir() or not (child / "seal.json").is_file():
                continue
            if child.name in protected_ids or (self.root / "refs" / child.name).exists():
                continue
            try:
                _canonical_uuid(child.name)
                manifest = self.verify_bundle(child)
            except Exception:
                # A corrupt, unknown, or racing bundle remains protected.
                continue
            if manifest.get("session_id") != child.name:
                continue
            candidates.append((str(manifest["created_utc"]), child, manifest))
        return sorted(candidates)

    def _record_roll_intent(self, bundle: Path, manifest: dict) -> None:
        receipts = self.root / "receipts"
        receipts.mkdir(exist_ok=True)
        slot = int(hashlib.sha256(bundle.name.encode("ascii")).hexdigest(), 16) % 16
        target = receipts / f"roll-{slot:02d}.json"
        temporary = receipts / f"roll-{slot:02d}.tmp"
        document = {
            "schema_version": 1,
            "phase": "delete_intent",
            "session_id": bundle.name,
            "sealed_sha256": hashlib.sha256((bundle / "seal.json").read_bytes()).hexdigest(),
            "recorded_utc": datetime.now(UTC).isoformat(),
        }
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        # The temporary file counts before any deletion. If there is no room for
        # this receipt, the candidate is kept and the write fails closed.
        if _tree_bytes(self.root) + len(payload) > self.limit:
            raise StorageError("over_limit: no room for rolling receipt")
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)

    def _delete_verified_bundle(self, bundle: Path, manifest: dict) -> None:
        if bundle.resolve(strict=True).parent != self.root.resolve(strict=True):
            raise StorageError("bundle escaped its storage root")
        if self.verify_bundle is None or self.verify_bundle(bundle) != manifest:
            raise StorageError("bundle changed before rolling")
        # verify_bundle rejects unknown entries; delete exactly its allowlist.
        for name in [*manifest["files"], "seal.json"]:
            (bundle / name).unlink()
        bundle.rmdir()

    def reserve(
        self,
        additional: int,
        *,
        new_active: bool = False,
        release_active: bool = False,
        protected_ids: frozenset[str] = frozenset(),
    ) -> None:
        """Call only while locked, immediately before the corresponding write."""
        if additional < 0:
            raise StorageError("invalid storage reservation")
        active = self._active_count() + int(new_active) - int(release_active)
        if additional > self.limit - self.receipt_reserve - active * self.terminal_reserve:
            raise StorageError("over_limit: one write exceeds the available domain budget")
        while True:
            used = _tree_bytes(self.root)
            ceiling = self.limit - self.receipt_reserve - active * self.terminal_reserve
            if used + additional <= ceiling:
                return
            candidates = self._eligible(protected_ids)
            if not candidates:
                raise StorageError("over_limit: protected or partial session bytes fill quota")
            _created, bundle, manifest = candidates[0]
            self._record_roll_intent(bundle, manifest)
            self._delete_verified_bundle(bundle, manifest)

    def status(self) -> dict[str, int | str]:
        with self.locked():
            return {
                "domain": self.domain,
                "limit_bytes": self.limit,
                "used_file_bytes": _tree_bytes(self.root),
                "active_or_partial": self._active_count(),
                "sealed_candidates": len(self._eligible()),
            }

    def add_reference(self, session_id: str, reference_id: str) -> None:
        """Minimal protection hook for a later sealed shadow bundle."""
        _canonical_uuid(session_id)
        _canonical_uuid(reference_id)
        with self.locked():
            if not (self.root / session_id / "seal.json").is_file():
                raise StorageError("referenced session is not sealed")
            payload = (reference_id + "\n").encode("ascii")
            self.reserve(len(payload), protected_ids=frozenset({session_id}))
            folder = self.root / "refs" / session_id
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / f"{reference_id}.ref").open("xb") as stream:
                stream.write(payload)

    def remove_reference(self, session_id: str, reference_id: str) -> None:
        """Explicit caller action after its own shadow bundle is removed."""
        _canonical_uuid(session_id)
        _canonical_uuid(reference_id)
        with self.locked():
            _tree_bytes(self.root)
            folder = self.root / "refs" / session_id
            marker = folder / f"{reference_id}.ref"
            if _plain_file_size(marker) != 37 or marker.read_bytes() != (
                reference_id + "\n"
            ).encode("ascii"):
                raise StorageError("session reference marker differs")
            if folder.resolve(strict=True).parent != (self.root / "refs").resolve(strict=True):
                raise StorageError("session reference escaped its root")
            marker.unlink()
            with contextlib.suppress(OSError):
                folder.rmdir()
