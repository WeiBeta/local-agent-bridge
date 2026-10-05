"""Frozen task input snapshots (task contract v1, package A).

Imports one caller-authorized engineering input into a sealed snapshot root:
an exact Git commit file selection, a hash-pinned ZIP package, or a directory
adjudicated against a trusted per-file manifest. The canonical manifest and
its plain byte tree are the single input identity that later task packages
copy from, and re-reading always re-verifies the seal, the identity and the
tree.

The module is deliberately offline: no model, upstream CLI, credential,
network or shell access happens here. Only the caller-provided input roots
and a fresh snapshot root are touched; failures retain dedicated staging
and attempt a failure label instead of publishing the final root.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import shutil
import stat
import struct
import subprocess
import time
import unicodedata
import zipfile
import zlib
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, suppress
from copy import copy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .contract import BridgeContractError, decode_strict_json_bytes
from .paths import BridgePathError, _is_reparse

__all__ = ["TaskInputError", "import_snapshot", "read_snapshot"]

_STREAM_CHUNK_BYTES = 1024 * 1024
_SHA256_TEXT = re.compile(r"[0-9a-f]{64}")
_COMMIT_TEXT = re.compile(r"[0-9a-f]{40}")
_FORBIDDEN_NAME_CHARS = frozenset('<>:"|?*')
_SOURCE_KEYS = {
    "git": frozenset({"kind", "root", "commit", "paths"}),
    "zip": frozenset({"kind", "path", "sha256", "strip_prefix"}),
    "directory": frozenset({"kind", "root", "manifest_path", "manifest_sha256"}),
}
_LIMIT_CEILINGS: dict[str, int] = {
    "package_bytes_limit": 67108864,
    "entry_count_limit": 20000,
    "expanded_bytes_limit": 536870912,
    "file_bytes_limit": 67108864,
    "expansion_ratio_limit": 200,
    "depth_limit": 32,
    "component_codepoints_limit": 255,
    "physical_path_utf16_limit": 240,
    "deadline_seconds": 60,
}
_POLICY_LIST_KEYS = (
    "source_paths",
    "excluded_paths",
    "sensitive_paths",
    "trusted_control_files",
)
_MANIFEST_KEYS = frozenset(
    {"contract_version", "snapshot_id", "source", "entries", "source_paths", "excluded_paths"}
)
_ENTRY_KEYS = frozenset({"path", "kind", "bytes", "sha256", "git_mode"})
_GIT_MODES = frozenset({"100644", "100755"})
# refs/replace entries make a fixed object id read as another object while the
# recorded identity stays unchanged. Module A treats the original objects as
# the only source of truth, so every Git invocation passes Git's own
# --no-replace-objects global option instead of editing refs or configuration.
_NO_REPLACE_OBJECTS = "--no-replace-objects"
_DEFAULT_DEPTH_LIMIT = _LIMIT_CEILINGS["depth_limit"]
_DEFAULT_COMPONENT_CODEPOINTS = _LIMIT_CEILINGS["component_codepoints_limit"]
# APPNOTE 4.3.7/4.3.9/4.5.3. Only the missing local/descriptor checks
# live here; zipfile still parses the directory and reads/decompresses data.
_ZIP_LOCAL_HEADER = struct.Struct("<4s5H3I2H")
_ZIP_DESCRIPTOR_FLAG = 0x8
_ZIP64_SIZE_SENTINEL = 0xFFFFFFFF
_ZIP64_EXTRA_ID = 0x1
_ZIP_DESCRIPTOR_SIGNATURE = b"PK\x07\x08"


class TaskInputError(RuntimeError):
    """Task input failure carrying a stable, non-sensitive code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Deadline:
    expires_at: float

    @classmethod
    def starting_now(cls, seconds: int) -> _Deadline:
        return cls(time.monotonic() + seconds)

    def check(self) -> None:
        if time.monotonic() >= self.expires_at:
            raise TaskInputError("DeadlineExceeded", "the import exceeded its deadline")

    def remaining_seconds(self) -> float:
        remaining = self.expires_at - time.monotonic()
        if remaining <= 0:
            raise TaskInputError("DeadlineExceeded", "the import exceeded its deadline")
        return remaining


@dataclass(frozen=True)
class _Policy:
    package_bytes_limit: int
    entry_count_limit: int
    expanded_bytes_limit: int
    file_bytes_limit: int
    expansion_ratio_limit: int
    depth_limit: int
    component_codepoints_limit: int
    physical_path_utf16_limit: int
    deadline_seconds: int
    source_paths: tuple[str, ...]
    excluded_paths: tuple[tuple[str, str], ...]
    sensitive_paths: tuple[str, ...]
    trusted_control_files: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _PendingFile:
    """One file selected for the snapshot, before it is staged.

    Exactly one origin field is set: blob_ref holds a Git object id, zip_name
    the original archive member spelling, or disk_path an adjudicated
    directory file. declared_bytes and expected_sha256 carry the declared
    size and digest when the source provides one, and git_mode records the
    Git mode or stays None for other sources.
    """

    path: str
    declared_bytes: int | None
    expected_sha256: str | None
    git_mode: str | None
    blob_ref: str | None
    zip_name: str | None
    disk_path: Path | None


@dataclass(frozen=True)
class _ImportContext:
    """Open origin handles a staged copy needs; unused fields stay None."""

    git_root: Path | None = None
    archive: zipfile.ZipFile | None = None


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path_key(path: str) -> bytes:
    return path.encode("utf-8")


def _require_text(value: object, label: str, code: str) -> str:
    if type(value) is not str or not value:
        raise TaskInputError(code, f"{label} must be a non-empty string")
    return value


def _require_sha256(value: object, label: str, code: str) -> str:
    text = _require_text(value, label, code)
    if not _SHA256_TEXT.fullmatch(text):
        raise TaskInputError(code, f"{label} must be a lowercase SHA-256 digest")
    return text


def _validate_absolute_path(value: str | Path, *, label: str) -> Path:
    """Check the supplied spelling before Path can fold any components.

    A supplied Path has already folded dot components; only its remaining
    spelling is available. No resolve, abspath, trimming or renaming happens
    here, so the original reparse chain remains available to the next check.
    """

    text = str(value)
    if text.startswith(("\\\\", "//")):
        raise TaskInputError("PathRejected", f"{label} must use a local drive path")
    if not re.match(r"^[A-Za-z]:[\\/]", text):
        raise TaskInputError("InvalidSource", f"{label} must be drive-absolute")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise TaskInputError("PathRejected", f"{label} must be encodable as UTF-8") from error
    # Empty parts are redundant separators, not names; Windows Path preserves
    # their meaning. Check raw non-anchor names before constructing the Path.
    components = [component for component in re.split(r"[\\/]", text[3:]) if component]
    if not components:
        raise TaskInputError("PathRejected", f"{label} must not be a drive root")
    for component in components:
        _validate_name_component(
            component,
            label=label,
            code="PathRejected",
            codepoints_limit=_DEFAULT_COMPONENT_CODEPOINTS,
        )
    return Path(text)


def _validate_name_component(
    component: str, *, label: str, code: str, codepoints_limit: int
) -> None:
    if component in {"", ".", ".."}:
        raise TaskInputError(code, f"{label} has an empty, dot or parent component")
    if component != component.rstrip(" ."):
        raise TaskInputError(code, f"{label} has a trailing dot or space")
    for char in component:
        if char in _FORBIDDEN_NAME_CHARS or ord(char) < 0x20 or ord(char) == 0x7F:
            raise TaskInputError(code, f"{label} has a character a Windows name cannot hold")
    if ntpath.isreserved(component):
        raise TaskInputError(code, f"{label} uses a reserved Windows device name")
    if len(component) > codepoints_limit:
        raise TaskInputError(
            "ResourceLimitExceeded", f"{label} exceeds the component code point limit"
        )


def _validate_relative_path(
    value: object,
    *,
    label: str,
    code: str,
    depth_limit: int,
    component_codepoints_limit: int,
    backslash_separator: bool = False,
) -> str:
    """Return the canonical forward-slash spelling of a contract path P."""

    if type(value) is not str or not value:
        raise TaskInputError(code, f"{label} must be a non-empty relative path")
    if "\x00" in value:
        raise TaskInputError(code, f"{label} contains a NUL character")
    if backslash_separator:
        normalized = value.replace("\\", "/")
    else:
        if "\\" in value:
            raise TaskInputError(code, f"{label} must use forward slash separators")
        normalized = value
    if normalized.startswith("/"):
        raise TaskInputError(code, f"{label} must not start at a root")
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as error:
        raise TaskInputError(code, f"{label} must be encodable as UTF-8") from error
    components = normalized.split("/")
    if len(components) > depth_limit:
        raise TaskInputError("ResourceLimitExceeded", f"{label} exceeds the depth limit")
    for component in components:
        _validate_name_component(
            component,
            label=label,
            code=code,
            codepoints_limit=component_codepoints_limit,
        )
    return normalized


def _broad_user_roots() -> set[Path]:
    home = Path.home()
    return {home, home.parent, home / "Desktop", home / "Documents", home / "Downloads"}


def _reject_broad_root(root: Path, label: str) -> None:
    """Reject exact forbidden roots after the caller checks the plain chain.

    stat identity catches alternate spellings without enumerating root contents.
    Only a missing forbidden root is skipped; permission and other I/O failures
    must propagate rather than being treated as proof of a different identity.
    """

    forbidden_roots = {Path(root.anchor), *_broad_user_roots()}
    if root in forbidden_roots:
        raise TaskInputError("PathRejected", f"{label} is too broad to be a task input")
    root_information = root.stat()
    if not stat.S_ISDIR(root_information.st_mode):
        return
    for forbidden in sorted(forbidden_roots, key=str):
        try:
            forbidden_information = forbidden.stat()
        except FileNotFoundError:
            continue
        if os.path.samestat(root_information, forbidden_information):
            raise TaskInputError("PathRejected", f"{label} has a forbidden root identity")


def _assert_plain_target(path: Path, *, label: str) -> None:
    """Reject a reparse point at the target itself or anywhere in its chain.

    Each call is a point-in-time check and does not close the race where the
    chain is swapped right afterwards; writes and publishes therefore re-run
    it at their own step instead of trusting an earlier verdict.
    """

    current = _validate_absolute_path(path, label=label)
    while True:
        if _is_reparse(current):
            raise TaskInputError("PathRejected", f"{label} or its chain contains a reparse point")
        if current.parent == current:
            break
        current = current.parent


def _validate_absolute_directory(value: object, *, label: str) -> Path:
    text = _require_text(value, label, "InvalidSource")
    root = _validate_absolute_path(text, label=label)
    _assert_plain_target(root, label=label)
    if not root.is_dir():
        raise TaskInputError("InvalidSource", f"{label} is not an existing directory")
    _reject_broad_root(root, label)
    return root


def _validate_absolute_file(value: object, *, label: str) -> Path:
    text = _require_text(value, label, "InvalidSource")
    path = _validate_absolute_path(text, label=label)
    _assert_plain_target(path, label=label)
    if not path.is_file():
        raise TaskInputError("InvalidSource", f"{label} is not an existing file")
    _reject_broad_root(path, label)
    return path


def _validate_policy(policy: object) -> _Policy:
    if type(policy) is not dict:
        raise TaskInputError("InvalidPolicy", "policy must be a JSON object")
    allowed_keys = _LIMIT_CEILINGS.keys() | set(_POLICY_LIST_KEYS)
    if set(policy) - allowed_keys:
        raise TaskInputError("InvalidPolicy", "policy contains unknown keys")
    limits: dict[str, int] = {}
    for key, ceiling in _LIMIT_CEILINGS.items():
        value = policy.get(key, ceiling)
        if type(value) is not int or not 1 <= value <= ceiling:
            raise TaskInputError(
                "InvalidPolicy",
                f"policy limit {key} must be a positive int within the frozen ceiling",
            )
        limits[key] = value
    for key in _POLICY_LIST_KEYS:
        if key not in policy:
            raise TaskInputError("InvalidPolicy", f"policy field {key} is required")

    def checked_path(value: object, label: str) -> str:
        return _validate_relative_path(
            value,
            label=label,
            code="InvalidPolicy",
            depth_limit=limits["depth_limit"],
            component_codepoints_limit=limits["component_codepoints_limit"],
        )

    source_values = policy["source_paths"]
    if type(source_values) is not list:
        raise TaskInputError("InvalidPolicy", "source_paths must be a list of paths")
    source_paths: list[str] = []
    seen_paths: set[str] = set()
    for item in source_values:
        path = checked_path(item, "source path")
        if path in seen_paths:
            raise TaskInputError("InvalidPolicy", "source_paths contains a duplicate path")
        seen_paths.add(path)
        source_paths.append(path)

    excluded_values = policy["excluded_paths"]
    if type(excluded_values) is not list:
        raise TaskInputError("InvalidPolicy", "excluded_paths must be a list")
    excluded_paths: list[tuple[str, str]] = []
    seen_excluded: set[str] = set()
    for item in excluded_values:
        if type(item) is not dict or set(item) != {"path", "reason"}:
            raise TaskInputError(
                "InvalidPolicy", "each excluded path needs exactly path and reason"
            )
        path = checked_path(item["path"], "excluded path")
        reason = _require_text(item["reason"], "excluded reason", "InvalidPolicy")
        if path in seen_excluded:
            raise TaskInputError("InvalidPolicy", "excluded_paths contains a duplicate path")
        seen_excluded.add(path)
        excluded_paths.append((path, reason))
    excluded_paths.sort(key=lambda item: _path_key(item[0]))

    sensitive_values = policy["sensitive_paths"]
    if type(sensitive_values) is not list:
        raise TaskInputError("InvalidPolicy", "sensitive_paths must be a list of paths")
    sensitive_paths: list[str] = []
    seen_sensitive: set[str] = set()
    for item in sensitive_values:
        path = checked_path(item, "sensitive path")
        if path in seen_sensitive:
            raise TaskInputError("InvalidPolicy", "sensitive_paths contains a duplicate path")
        seen_sensitive.add(path)
        sensitive_paths.append(path)

    trusted_values = policy["trusted_control_files"]
    if type(trusted_values) is not dict:
        raise TaskInputError("InvalidPolicy", "trusted_control_files must be an object")
    trusted_control: list[tuple[str, str]] = []
    for key, value in trusted_values.items():
        path = checked_path(key, "trusted control path")
        digest = _require_sha256(value, "trusted control hash", "InvalidPolicy")
        trusted_control.append((path, digest))
    trusted_control.sort(key=lambda item: _path_key(item[0]))

    return _Policy(
        **limits,
        source_paths=tuple(source_paths),
        excluded_paths=tuple(excluded_paths),
        sensitive_paths=tuple(sensitive_paths),
        trusted_control_files=tuple(trusted_control),
    )


def _source_kind(source: object) -> str:
    if type(source) is not dict:
        raise TaskInputError("InvalidSource", "source must be a JSON object")
    kind = source.get("kind")
    if type(kind) is not str or kind not in _SOURCE_KEYS:
        raise TaskInputError("InvalidSource", "source kind must be git, zip or directory")
    if set(source) != _SOURCE_KEYS[kind]:
        raise TaskInputError("InvalidSource", "source fields do not match the declared kind")
    return kind


def _selection_digest(
    source_paths: Sequence[str], excluded_paths: Sequence[tuple[str, str]]
) -> str:
    payload = {
        "source_paths": list(source_paths),
        "excluded_paths": [{"path": path, "reason": reason} for path, reason in excluded_paths],
    }
    return _sha256_bytes(_canonical_json_bytes(payload))


def _parent_path(path: str) -> str | None:
    index = path.rfind("/")
    if index <= 0:
        return None
    return path[:index]


def _covers(prefix: str, path: str) -> bool:
    return prefix == path or path.startswith(prefix + "/")


def _completed_directories(
    files: Mapping[str, object], directories: set[str], deadline: _Deadline | None = None
) -> set[str]:
    """Return the explicit directories plus every implicit parent directory.

    The result is a validation view only: callers keep their original
    explicit registry for exclusion accounting and staging, so completed
    parents never become registered input entries by themselves.
    """

    completed = set(directories)
    for path in (*files, *directories):
        if deadline is not None:
            deadline.check()
        parent = _parent_path(path)
        while parent is not None:
            completed.add(parent)
            parent = _parent_path(parent)
    return completed


def _most_specific_exclusion(
    path: str, excluded: tuple[tuple[str, str], ...], deadline: _Deadline
) -> tuple[str, str] | None:
    """Return the covering exclusion with the longest prefix for one path.

    Distinct exclusions that cover one path are prefixes of each other, so the
    longest match is unique and does not depend on declaration order.
    """

    best: tuple[str, str] | None = None
    best_length = -1
    for prefix, reason in excluded:
        deadline.check()
        if len(prefix) > best_length and _covers(prefix, path):
            best_length = len(prefix)
            best = (prefix, reason)
    return best


def _check_collection_conflicts(
    files: Mapping[str, object],
    directories: set[str],
    deadline: _Deadline | None = None,
    *,
    code: str = "PathConflict",
) -> None:
    def check_budget() -> None:
        if deadline is not None:
            deadline.check()

    check_budget()
    if set(files) & directories:
        raise TaskInputError(code, "a path is declared as both a file and a directory")
    folded: dict[str, str] = {}
    for path in (*files, *directories):
        check_budget()
        key = unicodedata.normalize("NFC", path).casefold()
        previous = folded.get(key)
        if previous is not None and previous != path:
            raise TaskInputError(
                code, "distinct input names collide under NFC or Windows case folding"
            )
        folded[key] = path
    for path in files:
        check_budget()
        parent = _parent_path(path)
        while parent is not None:
            if parent in files:
                raise TaskInputError(code, "a file entry is also a parent of another entry")
            parent = _parent_path(parent)
    check_budget()


def _zip_entry_name(info: zipfile.ZipInfo, policy: _Policy) -> tuple[str, bool]:
    original = getattr(info, "orig_filename", info.filename)
    # CPython truncates a raw name at its first NUL and, where the host
    # separator is a backslash, rewrites that backslash as a slash. A real
    # NUL, or a difference beyond that separator rewrite, means the parsed
    # filename hides part of the original spelling.
    if "\x00" in original or original.replace("\\", "/") != info.filename.replace("\\", "/"):
        raise TaskInputError("ZipEntryRejected", "an archive name hides text after a NUL")
    # Judge the complete original name before a trailing separator, a strip
    # prefix or an empty-output step can reduce it: an empty or root-anchored
    # original is rejected as an input instead of silently dropping the entry.
    if not original:
        raise TaskInputError("ZipEntryRejected", "an archive entry name must not be empty")
    if original.startswith(("/", "\\")):
        raise TaskInputError("ZipEntryRejected", "an archive entry name must not start at a root")
    name = info.filename
    trailing_directory = name.endswith("/")
    if trailing_directory:
        name = name[:-1]
    normalized = _validate_relative_path(
        name,
        label="archive entry",
        code="ZipEntryRejected",
        depth_limit=policy.depth_limit,
        component_codepoints_limit=policy.component_codepoints_limit,
        backslash_separator=True,
    )
    return normalized, trailing_directory


def _zip_entry_kind(info: zipfile.ZipInfo, trailing_directory: bool) -> str:
    if info.flag_bits & 0x1:
        raise TaskInputError("ZipEntryRejected", "encrypted archive entries are not accepted")
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise TaskInputError("ZipEntryRejected", "only stored and deflate entries are accepted")
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    looks_like_directory = trailing_directory or bool(info.external_attr & 0x10)
    if file_type == stat.S_IFDIR or (not file_type and looks_like_directory):
        kind = "directory"
    elif file_type in (0, stat.S_IFREG):
        kind = "file"
    elif file_type == stat.S_IFLNK:
        raise TaskInputError("ZipEntryRejected", "symbolic link entries are not accepted")
    else:
        raise TaskInputError("ZipEntryRejected", "device, fifo and socket entries are not accepted")
    if info.external_attr & 0x400:
        raise TaskInputError(
            "ZipEntryRejected", "entries with a reparse attribute are not accepted"
        )
    if kind == "directory":
        if info.file_size:
            raise TaskInputError("ZipEntryRejected", "directory entries must not declare content")
    elif trailing_directory:
        raise TaskInputError("ZipEntryRejected", "a file entry must not end with a separator")
    return kind


def _check_zip_file_declared(info: zipfile.ZipInfo, policy: _Policy, name: str) -> None:
    if info.file_size > policy.file_bytes_limit:
        raise TaskInputError("ResourceLimitExceeded", f"archive file {name} exceeds the file limit")
    if info.compress_size == 0 and info.file_size > 0:
        raise TaskInputError(
            "ZipEntryRejected", "an entry declares content without compressed bytes"
        )
    if info.file_size > policy.expansion_ratio_limit * info.compress_size:
        raise TaskInputError(
            "ResourceLimitExceeded", f"archive file {name} exceeds the expansion ratio limit"
        )


def _zip_record_bytes(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, offset: int, size: int, deadline: _Deadline
) -> bytes:
    deadline.check()
    # CPython has already computed each member's next-header/directory bound.
    # Use that bound instead of inventing another central-directory parser.
    if offset < info.header_offset or offset + size > info._end_offset:
        raise TaskInputError("ZipEntryRejected", "an archive record crosses its member boundary")
    archive.fp.seek(offset)
    deadline.check()
    raw = archive.fp.read(size)
    deadline.check()
    if len(raw) != size:
        raise TaskInputError("ZipEntryRejected", "an archive record is truncated")
    return raw


def _zip_local_sizes(
    extra: bytes, compressed: int, expanded: int, deadline: _Deadline
) -> tuple[int, int, bool]:
    """Resolve the two local ZIP64 sizes; leave unrelated extra fields alone."""

    zip64_sizes: tuple[int, int] | None = None
    position = 0
    while position < len(extra):
        deadline.check()
        if len(extra) - position < 4:
            raise TaskInputError("ZipEntryRejected", "a local extra field is truncated")
        field_id, size = struct.unpack_from("<HH", extra, position)
        position += 4
        if position + size > len(extra):
            raise TaskInputError("ZipEntryRejected", "a local extra field is truncated")
        if field_id == _ZIP64_EXTRA_ID:
            if zip64_sizes is not None or size < 16:
                raise TaskInputError(
                    "ZipEntryRejected", "local ZIP64 sizes are missing or repeated"
                )
            # Local ZIP64 includes both sizes, in expanded/compressed order.
            zip64_sizes = struct.unpack_from("<QQ", extra, position)
        position += size
    needs_zip64 = _ZIP64_SIZE_SENTINEL in (compressed, expanded)
    if needs_zip64 and zip64_sizes is None:
        raise TaskInputError("ZipEntryRejected", "a local ZIP64 size has no extended value")
    if expanded == _ZIP64_SIZE_SENTINEL:
        expanded = zip64_sizes[0]
    if compressed == _ZIP64_SIZE_SENTINEL:
        compressed = zip64_sizes[1]
    return compressed, expanded, zip64_sizes is not None


def _check_zip_descriptor(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    offset: int,
    zip64: bool,
    deadline: _Deadline,
) -> None:
    layout = struct.Struct("<IQQ" if zip64 else "<III")
    available = info._end_offset - offset
    raw = _zip_record_bytes(archive, info, offset, min(layout.size + 4, available), deadline)
    # A descriptor can omit its signature. Try the unsigned interpretation
    # first, including the valid case where the CRC equals the signature.
    starts = (0, 4) if raw.startswith(_ZIP_DESCRIPTOR_SIGNATURE) else (0,)
    expected = (info.CRC, info.compress_size, info.file_size)
    for start in starts:
        if len(raw) >= start + layout.size and layout.unpack_from(raw, start) == expected:
            return
    raise TaskInputError("ZipEntryRejected", "the data descriptor differs from the directory")


def _check_zip_local_record(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, deadline: _Deadline
) -> None:
    raw = _zip_record_bytes(archive, info, info.header_offset, _ZIP_LOCAL_HEADER.size, deadline)
    (
        signature,
        _version,
        flags,
        method,
        _time,
        _date,
        crc,
        compressed,
        expanded,
        name_size,
        extra_size,
    ) = _ZIP_LOCAL_HEADER.unpack(raw)
    if signature != b"PK\x03\x04" or flags != info.flag_bits or method != info.compress_type:
        raise TaskInputError("ZipEntryRejected", "local and directory entry metadata differ")
    extra_offset = info.header_offset + _ZIP_LOCAL_HEADER.size + name_size
    extra = _zip_record_bytes(archive, info, extra_offset, extra_size, deadline)
    compressed, expanded, zip64 = _zip_local_sizes(extra, compressed, expanded, deadline)
    if flags & _ZIP_DESCRIPTOR_FLAG:
        # Streaming writers use zero placeholders (also inside ZIP64 extra).
        # Writers that know the values may repeat the directory values.
        matching = (
            crc in (0, info.CRC)
            and compressed in (0, info.compress_size)
            and expanded in (0, info.file_size)
        )
    else:
        matching = (crc, compressed, expanded) == (info.CRC, info.compress_size, info.file_size)
    if not matching:
        raise TaskInputError("ZipEntryRejected", "local and directory CRC or sizes differ")
    if method == zipfile.ZIP_STORED and info.compress_size != info.file_size:
        raise TaskInputError("ZipEntryRejected", "a stored entry declares unequal byte lengths")
    data_end = extra_offset + extra_size + info.compress_size
    if data_end > info._end_offset:
        raise TaskInputError("ZipEntryRejected", "archive data crosses its member boundary")
    if flags & _ZIP_DESCRIPTOR_FLAG:
        _check_zip_descriptor(archive, info, data_end, zip64, deadline)
    deadline.check()


def _plan_zip_members(
    archive: zipfile.ZipFile, source: dict[str, object], policy: _Policy, deadline: _Deadline
) -> tuple[dict[str, _PendingFile], set[str]]:
    deadline.check()
    strip_prefix = source["strip_prefix"]
    if strip_prefix is not None:
        strip_prefix = _validate_relative_path(
            strip_prefix,
            label="strip prefix",
            code="InvalidSource",
            depth_limit=policy.depth_limit,
            component_codepoints_limit=policy.component_codepoints_limit,
        )
    infos = archive.infolist()
    deadline.check()
    if len(infos) > policy.entry_count_limit:
        raise TaskInputError("ResourceLimitExceeded", "the package exceeds the entry count limit")
    files: dict[str, _PendingFile] = {}
    directories: set[str] = set()
    for info in infos:
        deadline.check()
        name, trailing_directory = _zip_entry_name(info, policy)
        kind = _zip_entry_kind(info, trailing_directory)
        _check_zip_local_record(archive, info, deadline)
        if kind == "directory":
            # Directory entries have no staged file, so validate their empty
            # stream here rather than bypassing real deflate EOF/CRC checks.
            for chunk in _zip_chunks(archive, info.filename, deadline):
                if chunk:
                    raise TaskInputError("ZipEntryRejected", "an archive directory has content")
        deadline.check()
        if not name:
            continue
        if strip_prefix is not None:
            if name == strip_prefix:
                if kind != "directory":
                    raise TaskInputError(
                        "StripPrefixMismatch", "the strip prefix entry is not a directory"
                    )
                # The strip-prefix root passed the same name, kind and record
                # checks as every entry above; only its output row is omitted.
                continue
            if not name.startswith(strip_prefix + "/"):
                raise TaskInputError(
                    "StripPrefixMismatch", "an archive entry is outside the strip prefix"
                )
            name = name[len(strip_prefix) + 1 :]
        if name in files or name in directories:
            raise TaskInputError("PathConflict", "an archive entry path is declared twice")
        if kind == "directory":
            directories.add(name)
            continue
        _check_zip_file_declared(info, policy, name)
        files[name] = _PendingFile(
            path=name,
            declared_bytes=info.file_size,
            expected_sha256=None,
            git_mode=None,
            blob_ref=None,
            zip_name=info.filename,
            disk_path=None,
        )
    _check_collection_conflicts(
        files, _completed_directories(files, directories, deadline), deadline
    )
    return files, directories


def _verify_zip_package(source: dict[str, object], policy: _Policy, deadline: _Deadline) -> Path:
    deadline.check()
    package_path = _validate_absolute_file(source["path"], label="zip package path")
    declared_sha256 = _require_sha256(source["sha256"], "zip sha256", "InvalidSource")
    if package_path.stat().st_size > policy.package_bytes_limit:
        raise TaskInputError("ResourceLimitExceeded", "the package exceeds the package bytes limit")
    deadline.check()
    if _hash_file(package_path, deadline) != declared_sha256:
        raise TaskInputError("InputChanged", "the package hash differs from the declared value")
    return package_path


def _git_text(root: Path, deadline: _Deadline, *arguments: str) -> str:
    try:
        raw = _git_bytes(root, list(arguments), deadline)
    except TaskInputError as error:
        if error.code != "GitUnavailable":
            raise
        raise TaskInputError("GitCommandFailed", "the bounded Git listing failed") from error
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise TaskInputError("GitCommandFailed", "the bounded Git listing failed") from error
    deadline.check()
    return text


def _parse_git_listing(listing: str, deadline: _Deadline) -> dict[str, tuple[str, str, str]]:
    deadline.check()
    objects: dict[str, tuple[str, str, str]] = {}
    for record in listing.split("\x00"):
        deadline.check()
        if not record:
            continue
        header, separator, path = record.partition("\t")
        fields = header.split(" ") if separator else []
        if len(fields) != 3:
            raise TaskInputError(
                "GitCommandFailed", "the Git listing was not in the expected shape"
            )
        objects[path] = (fields[0], fields[1], fields[2])
    deadline.check()
    return objects


def _plan_git_selection(
    source: dict[str, object], policy: _Policy, deadline: _Deadline
) -> tuple[dict[str, _PendingFile], set[str], Path]:
    deadline.check()
    root = _validate_absolute_directory(source["root"], label="git root")
    deadline.check()
    commit = _require_text(source["commit"], "git commit", "InvalidSource")
    if not _COMMIT_TEXT.fullmatch(commit):
        raise TaskInputError("InvalidSource", "git commit must be an exact 40 character object id")
    raw_paths = source["paths"]
    if type(raw_paths) is not list:
        raise TaskInputError("InvalidSource", "git paths must be a list of exact files")
    selected: list[str] = []
    seen_paths: set[str] = set()
    for item in raw_paths:
        deadline.check()
        path = _validate_relative_path(
            item,
            label="git path",
            code="InvalidSource",
            depth_limit=policy.depth_limit,
            component_codepoints_limit=policy.component_codepoints_limit,
        )
        if path in seen_paths:
            raise TaskInputError("InvalidSource", "git paths contains a duplicate path")
        seen_paths.add(path)
        selected.append(path)
    object_type = _git_text(root, deadline, "cat-file", "-t", commit).strip()
    if object_type != "commit":
        raise TaskInputError("GitSelectionInvalid", "the declared Git object is not a commit")
    objects = _parse_git_listing(
        _git_text(root, deadline, "ls-tree", "-rz", "--full-tree", commit), deadline
    )
    files: dict[str, _PendingFile] = {}
    for path in selected:
        deadline.check()
        record = objects.get(path)
        if record is None:
            raise TaskInputError(
                "GitSelectionInvalid", "a selected path is missing from the commit"
            )
        mode, object_kind, blob_ref = record
        if object_kind == "tree":
            raise TaskInputError(
                "GitSelectionInvalid", "a selected path is a directory; select exact files"
            )
        if mode in {"120000", "160000"} or object_kind != "blob" or mode not in _GIT_MODES:
            raise TaskInputError(
                "GitSelectionInvalid", "links, submodules and unusual modes are not accepted"
            )
        files[path] = _PendingFile(
            path=path,
            declared_bytes=None,
            expected_sha256=None,
            git_mode=mode,
            blob_ref=blob_ref,
            zip_name=None,
            disk_path=None,
        )
    _check_collection_conflicts(files, _completed_directories(files, set(), deadline), deadline)
    return files, set(), root


def _validate_directory_manifest(
    document: object, deadline: _Deadline
) -> tuple[dict[str, tuple[int, str]], set[str]]:
    deadline.check()
    if type(document) is not dict or set(document) != {"contract_version", "entries"}:
        raise TaskInputError(
            "InputManifestMismatch", "the directory manifest fields are not frozen"
        )
    version = document["contract_version"]
    if type(version) is not int or version != 1:
        raise TaskInputError("InputManifestMismatch", "the directory manifest version must be 1")
    raw_entries = document["entries"]
    if type(raw_entries) is not list:
        raise TaskInputError(
            "InputManifestMismatch", "the directory manifest entries must be a list"
        )
    files: dict[str, tuple[int, str]] = {}
    directories: set[str] = set()
    for item in raw_entries:
        deadline.check()
        if type(item) is not dict or set(item) != {"path", "kind", "bytes", "sha256"}:
            raise TaskInputError("InputManifestMismatch", "a manifest entry has unknown fields")
        path = _validate_relative_path(
            item["path"],
            label="manifest entry",
            code="InputManifestMismatch",
            depth_limit=_DEFAULT_DEPTH_LIMIT,
            component_codepoints_limit=_DEFAULT_COMPONENT_CODEPOINTS,
        )
        kind = item["kind"]
        size = item["bytes"]
        digest = item["sha256"]
        if type(size) is not int or size < 0:
            raise TaskInputError(
                "InputManifestMismatch", "a manifest entry has an invalid byte count"
            )
        if kind == "file":
            if type(digest) is not str or not _SHA256_TEXT.fullmatch(digest):
                raise TaskInputError("InputManifestMismatch", "a file entry needs a SHA-256 digest")
            if path in files or path in directories:
                raise TaskInputError("InputManifestMismatch", "a manifest path is declared twice")
            files[path] = (size, digest)
        elif kind == "directory":
            if size != 0 or digest is not None:
                raise TaskInputError(
                    "InputManifestMismatch", "a directory entry must have zero bytes and no digest"
                )
            if path in files or path in directories:
                raise TaskInputError("InputManifestMismatch", "a manifest path is declared twice")
            directories.add(path)
        else:
            raise TaskInputError(
                "InputManifestMismatch", "a manifest entry kind must be file or directory"
            )
    for path in (*files, *directories):
        deadline.check()
        parent = _parent_path(path)
        while parent is not None:
            if parent not in directories:
                raise TaskInputError(
                    "InputManifestMismatch", "a manifest entry is missing an explicit parent"
                )
            parent = _parent_path(parent)
    deadline.check()
    return files, directories


def _scan_tree(
    root: Path, policy: _Policy, deadline: _Deadline
) -> tuple[dict[str, tuple[int, str]], set[str]]:
    deadline.check()
    if _is_reparse(root):
        raise TaskInputError("PathRejected", "the tree root is a reparse point")

    def on_error(error: OSError) -> None:
        raise TaskInputError("IoFailed", "reading a tree failed") from error

    files: dict[str, tuple[int, str]] = {}
    directories: set[str] = set()
    for directory, subdirectories, filenames in os.walk(root, topdown=True, onerror=on_error):
        deadline.check()
        current = Path(directory)
        for name in subdirectories:
            deadline.check()
            child = current / name
            if _is_reparse(child):
                raise TaskInputError("PathRejected", "a tree directory is a reparse point")
            relative = child.relative_to(root).as_posix()
            _validate_relative_path(
                relative,
                label="tree directory",
                code="PathRejected",
                depth_limit=policy.depth_limit,
                component_codepoints_limit=policy.component_codepoints_limit,
            )
            directories.add(relative)
            deadline.check()
        for name in filenames:
            deadline.check()
            child = current / name
            information = child.lstat()
            if _is_reparse(child):
                raise TaskInputError("PathRejected", "a tree file is a reparse point")
            if not stat.S_ISREG(information.st_mode):
                raise TaskInputError("PathRejected", "a tree entry is not a regular file")
            if information.st_nlink > 1:
                raise TaskInputError("PathRejected", "a tree file is linked more than once")
            relative = child.relative_to(root).as_posix()
            _validate_relative_path(
                relative,
                label="tree file",
                code="PathRejected",
                depth_limit=policy.depth_limit,
                component_codepoints_limit=policy.component_codepoints_limit,
            )
            if information.st_size > policy.file_bytes_limit:
                raise TaskInputError(
                    "ResourceLimitExceeded", "a tree file exceeds the file bytes limit"
                )
            deadline.check()
            files[relative] = (information.st_size, _hash_file(child, deadline))
    deadline.check()
    return files, directories


def _hash_file(path: Path, deadline: _Deadline) -> str:
    deadline.check()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        deadline.check()
        while True:
            deadline.check()
            chunk = handle.read(_STREAM_CHUNK_BYTES)
            deadline.check()
            if not chunk:
                break
            digest.update(chunk)
            deadline.check()
    deadline.check()
    return digest.hexdigest()


def _plan_directory_tree(
    source: dict[str, object], policy: _Policy, deadline: _Deadline
) -> tuple[dict[str, _PendingFile], set[str]]:
    deadline.check()
    root = _validate_absolute_directory(source["root"], label="directory root")
    manifest_path = _validate_absolute_file(
        source["manifest_path"], label="directory manifest path"
    )
    declared_sha256 = _require_sha256(source["manifest_sha256"], "manifest sha256", "InvalidSource")
    deadline.check()
    raw = manifest_path.read_bytes()
    deadline.check()
    actual_sha256 = _sha256_bytes(raw)
    deadline.check()
    if actual_sha256 != declared_sha256:
        raise TaskInputError(
            "InputManifestMismatch", "the directory manifest hash differs from the declared value"
        )
    document = decode_strict_json_bytes(raw, label="directory manifest")
    deadline.check()
    declared_files, declared_directories = _validate_directory_manifest(document, deadline)
    actual_files, actual_directories = _scan_tree(root, policy, deadline)
    if actual_directories != declared_directories or actual_files != declared_files:
        raise TaskInputError("InputChanged", "the directory tree differs from its manifest")
    files = {
        path: _PendingFile(
            path=path,
            declared_bytes=size,
            expected_sha256=digest,
            git_mode=None,
            blob_ref=None,
            zip_name=None,
            disk_path=root.joinpath(*path.split("/")),
        )
        for path, (size, digest) in actual_files.items()
    }
    _check_collection_conflicts(
        files, _completed_directories(files, actual_directories, deadline), deadline
    )
    return files, actual_directories


def _apply_selection(
    files: dict[str, _PendingFile], directories: set[str], policy: _Policy, deadline: _Deadline
) -> tuple[list[_PendingFile], list[str], list[tuple[str, str]]]:
    """Split the planned input into kept entries and explicit exclusions.

    Every planned input path that an exclusion removes is recorded with the
    reason of its most specific covering exclusion, so the manifest keeps one
    denominator row per logical input path instead of collapsing whole
    subtrees into a single prefix record.
    """

    deadline.check()
    excluded = policy.excluded_paths
    all_paths = (*files, *directories)
    for prefix, _reason in excluded:
        deadline.check()
        if not any(_covers(prefix, path) for path in all_paths):
            raise TaskInputError(
                "ExcludedPathUnknown", "an excluded path is not present in the input"
            )
    excluded_records: list[tuple[str, str]] = []
    for path in sorted(all_paths, key=_path_key):
        deadline.check()
        covering = _most_specific_exclusion(path, excluded, deadline)
        if covering is not None:
            excluded_records.append((path, covering[1]))
    excluded_path_set = {path for path, _reason in excluded_records}
    kept_files: dict[str, _PendingFile] = {}
    kept_directories: set[str] = set()
    for path, pending in files.items():
        deadline.check()
        if path not in excluded_path_set:
            kept_files[path] = pending
    for path in directories:
        deadline.check()
        if path not in excluded_path_set:
            kept_directories.add(path)
    for path in kept_files:
        deadline.check()
        parent = _parent_path(path)
        while parent is not None:
            if parent in files:
                raise TaskInputError("PathConflict", "a kept file sits under a file entry")
            kept_directories.add(parent)
            parent = _parent_path(parent)
    for prefix in policy.sensitive_paths:
        deadline.check()
        for path in kept_files:
            deadline.check()
            if _covers(prefix, path):
                raise TaskInputError(
                    "SensitivePathImported", "a declared sensitive path would enter the snapshot"
                )
    for declared in policy.source_paths:
        deadline.check()
        if declared in kept_files or declared in excluded_path_set:
            continue
        raise TaskInputError(
            "SourcePathUnaccounted", "a declared source path is neither imported nor excluded"
        )
    if len(kept_files) + len(kept_directories) + len(excluded_records) > policy.entry_count_limit:
        raise TaskInputError("ResourceLimitExceeded", "the input exceeds the entry count limit")
    declared_total = sum(
        pending.declared_bytes if pending.declared_bytes is not None else 0
        for pending in kept_files.values()
    )
    if declared_total > policy.expanded_bytes_limit:
        raise TaskInputError("ResourceLimitExceeded", "the input exceeds the expanded bytes limit")
    result = (
        sorted(kept_files.values(), key=lambda pending: _path_key(pending.path)),
        sorted(kept_directories, key=_path_key),
        excluded_records,
    )
    deadline.check()
    return result


def _utf16_length(value: str) -> int:
    return sum(2 if ord(char) > 0xFFFF else 1 for char in value)


def _check_physical_budget(path: Path, policy: _Policy) -> None:
    if _utf16_length(str(path)) > policy.physical_path_utf16_limit:
        raise TaskInputError(
            "PathBudgetExceeded", "a staging path exceeds the physical UTF-16 budget"
        )


def _ensure_directory(
    source_root: Path, relative: str, created: set[str], policy: _Policy, deadline: _Deadline
) -> None:
    deadline.check()
    if relative in created:
        return
    parent = _parent_path(relative)
    if parent is not None:
        _ensure_directory(source_root, parent, created, policy, deadline)
    target = source_root.joinpath(*relative.split("/"))
    _check_physical_budget(target, policy)
    _assert_plain_target(target, label="a staging directory")
    deadline.check()
    os.mkdir(target)
    deadline.check()
    created.add(relative)


def _file_chunks(path: Path, deadline: _Deadline) -> Iterator[bytes]:
    deadline.check()
    _assert_plain_target(path, label="an adjudicated input file")
    information = path.lstat()
    if _is_reparse(path) or not stat.S_ISREG(information.st_mode):
        raise TaskInputError("InputChanged", "an adjudicated file changed shape before the copy")
    deadline.check()
    with path.open("rb") as handle:
        deadline.check()
        while True:
            deadline.check()
            chunk = handle.read(_STREAM_CHUNK_BYTES)
            deadline.check()
            if not chunk:
                break
            yield chunk
    deadline.check()


def _zip_chunks(archive: zipfile.ZipFile, member: str, deadline: _Deadline) -> Iterator[bytes]:
    deadline.check()
    info = archive.getinfo(member)
    reading_info = copy(info)
    # ZipExtFile clips output to file_size and can mark EOF before zlib EOF.
    # One extra byte detects an understated declaration without unbounded
    # expansion; keep the original directory record and CRC unchanged.
    reading_info.file_size += 1
    total = 0
    with archive.open(reading_info, "r") as reader:
        deadline.check()
        while True:
            deadline.check()
            try:
                chunk = reader.read(_STREAM_CHUNK_BYTES)
            except zlib.error as error:
                # CPython's decompressor surfaces corrupt deflate data as
                # zlib.error; keep the stable stream-copy rejection code and
                # preserve the original exception as the cause.
                raise TaskInputError(
                    "InputChanged", "an archive stream failed to decompress"
                ) from error
            deadline.check()
            if not chunk:
                break
            total += len(chunk)
            if total > info.file_size:
                raise TaskInputError("InputChanged", "an archive stream exceeds its declared size")
            yield chunk
        if total != info.file_size or reader._compress_left != 0:
            raise TaskInputError(
                "InputChanged", "an archive stream differs from its declared sizes"
            )
        if info.compress_type == zipfile.ZIP_DEFLATED:
            decompressor = reader._decompressor
            if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
                raise TaskInputError("InputChanged", "the declared deflate stream is not complete")
    deadline.check()


def _git_bytes(root: Path, arguments: list[str], deadline: _Deadline) -> bytes:
    deadline.check()
    executable = shutil.which("git")
    deadline.check()
    if executable is None:
        raise TaskInputError("GitUnavailable", "git is not available on this host")
    try:
        completed = subprocess.run(
            [executable, "-C", str(root), _NO_REPLACE_OBJECTS, *arguments],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=deadline.remaining_seconds(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise TaskInputError(
            "DeadlineExceeded", "a bounded Git read exceeded the import deadline"
        ) from error
    deadline.check()
    if completed.returncode != 0:
        raise TaskInputError("GitCommandFailed", "a bounded Git read failed")
    return completed.stdout


def _prefetch_git_sizes(
    files: list[_PendingFile], root: Path, policy: _Policy, deadline: _Deadline
) -> list[_PendingFile]:
    """Declare only retained original blobs, before staging consumes space."""

    declared: list[_PendingFile] = []
    total = 0
    for pending in files:
        deadline.check()
        size_raw = _git_bytes(root, ["cat-file", "-s", pending.blob_ref], deadline).strip()
        if not size_raw.isdigit():
            raise TaskInputError(
                "GitCommandFailed", "a Git blob size was not in the expected shape"
            )
        size = int(size_raw)
        if size > policy.file_bytes_limit:
            raise TaskInputError("ResourceLimitExceeded", "a Git blob exceeds the file bytes limit")
        total += size
        if total > policy.expanded_bytes_limit:
            raise TaskInputError(
                "ResourceLimitExceeded", "the input exceeds the expanded bytes limit"
            )
        declared.append(replace(pending, declared_bytes=size))
    deadline.check()
    return declared


def _git_chunks(root: Path, blob_ref: str, deadline: _Deadline) -> Iterator[bytes]:
    raw = _git_bytes(root, ["cat-file", "blob", blob_ref], deadline)
    for start in range(0, len(raw), _STREAM_CHUNK_BYTES):
        deadline.check()
        yield raw[start : start + _STREAM_CHUNK_BYTES]
    deadline.check()


def _pending_chunks(
    pending: _PendingFile, context: _ImportContext, deadline: _Deadline
) -> Iterator[bytes]:
    if pending.disk_path is not None:
        yield from _file_chunks(pending.disk_path, deadline)
    elif pending.blob_ref is not None and context.git_root is not None:
        yield from _git_chunks(context.git_root, pending.blob_ref, deadline)
    elif pending.zip_name is not None and context.archive is not None:
        yield from _zip_chunks(context.archive, pending.zip_name, deadline)
    else:
        raise TaskInputError("InvalidSource", "a pending file has no usable origin")


def _check_disk_space(parent: Path, required_bytes: int, deadline: _Deadline) -> None:
    """Check current output-volume free bytes, without reserving or guessing overhead."""

    deadline.check()
    free_bytes = shutil.disk_usage(parent).free
    deadline.check()
    if free_bytes < required_bytes:
        raise TaskInputError(
            "ResourceLimitExceeded", "the output volume has insufficient free space"
        )


def _write_stream(
    target: Path,
    chunks: Iterator[bytes],
    policy: _Policy,
    deadline: _Deadline,
    expanded_before: int,
) -> tuple[int, str]:
    deadline.check()
    digest = hashlib.sha256()
    total = 0
    _assert_plain_target(target, label="a staged file")
    deadline.check()
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "wb") as handle:
        deadline.check()
        for chunk in chunks:
            deadline.check()
            total += len(chunk)
            if total > policy.file_bytes_limit:
                raise TaskInputError(
                    "ResourceLimitExceeded", "a staged file exceeds the file bytes limit"
                )
            if expanded_before + total > policy.expanded_bytes_limit:
                raise TaskInputError(
                    "ResourceLimitExceeded", "the staged tree exceeds the expanded bytes limit"
                )
            digest.update(chunk)
            _check_disk_space(target.parent, len(chunk), deadline)
            handle.write(chunk)
            deadline.check()
            # Flush this file's Python buffer before the next free-space query;
            # otherwise small chunks could remain invisible to the volume API.
            handle.flush()
            deadline.check()
    deadline.check()
    return total, digest.hexdigest()


def _write_exclusive(target: Path, raw: bytes, deadline: _Deadline) -> None:
    deadline.check()
    _assert_plain_target(target, label="snapshot metadata")
    _check_disk_space(target.parent, len(raw), deadline)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "wb") as handle:
        deadline.check()
        handle.write(raw)
        deadline.check()
    deadline.check()


def _write_failure_label(staging_root: Path, code: str) -> None:
    if not staging_root.is_dir():
        return
    with suppress(OSError, TaskInputError):
        target = staging_root / "IMPORT-FAILED"
        _assert_plain_target(target, label="the failure label")
        if not target.exists():
            target.write_text(code + "\n", encoding="ascii")


def _failure_code(error: BaseException) -> str:
    """Map any import failure to the public code its label should record."""

    if isinstance(error, TaskInputError):
        return error.code
    if isinstance(error, BridgePathError):
        return "PathRejected"
    if isinstance(error, BridgeContractError):
        return "InvalidManifest"
    if isinstance(error, zipfile.BadZipFile):
        return "InputChanged"
    if isinstance(error, OSError):
        return "IoFailed"
    return "ImportFailed"


def _stage_and_publish(
    *,
    files: list[_PendingFile],
    directories: list[str],
    excluded_records: list[tuple[str, str]],
    policy: _Policy,
    deadline: _Deadline,
    snapshot_root: Path,
    context: _ImportContext,
    origin_stack: ExitStack,
    source_kind: str,
    identity: str,
    selection_sha256: str,
) -> dict[str, object]:
    deadline.check()
    staging_root = snapshot_root.with_name(snapshot_root.name + ".staging")
    if os.path.lexists(staging_root):
        raise TaskInputError("SnapshotRootNotFresh", "a staging root already exists")
    source_root = staging_root / "source"
    for relative in (*(pending.path for pending in files), *directories):
        deadline.check()
        _check_physical_budget(source_root.joinpath(*relative.split("/")), policy)
    _assert_plain_target(staging_root, label="the staging root")
    declared_total = sum(pending.declared_bytes for pending in files)
    _check_disk_space(snapshot_root.parent, declared_total, deadline)
    deadline.check()
    try:
        os.mkdir(staging_root)
        deadline.check()
        _assert_plain_target(source_root, label="the staging source root")
        deadline.check()
        os.mkdir(source_root)
        deadline.check()
        created_directories: set[str] = set()
        for relative in directories:
            _ensure_directory(source_root, relative, created_directories, policy, deadline)
        expanded_total = 0
        # Fingerprints observed while each staged copy was written. They are the
        # import's content identity; the final scan must observe them again.
        copied_files: dict[str, tuple[int, str]] = {}
        for pending in files:
            deadline.check()
            parent = _parent_path(pending.path)
            if parent is not None:
                _ensure_directory(source_root, parent, created_directories, policy, deadline)
            target = source_root.joinpath(*pending.path.split("/"))
            _check_physical_budget(target, policy)
            total, digest = _write_stream(
                target,
                _pending_chunks(pending, context, deadline),
                policy,
                deadline,
                expanded_total,
            )
            expanded_total += total
            copied_files[pending.path] = (total, digest)
            if pending.declared_bytes is not None and total != pending.declared_bytes:
                raise TaskInputError("InputChanged", "a staged file differs from its declared size")
            if pending.expected_sha256 is not None and digest != pending.expected_sha256:
                raise TaskInputError(
                    "InputChanged", "a staged file differs from its manifest digest"
                )
        # Origin handles are no longer needed once the byte copy is complete.
        # Close them inside the staging failure domain, before verification,
        # metadata or publication can make the final root acceptable.
        deadline.check()
        origin_stack.close()
        deadline.check()
        actual_files, actual_directories = _scan_tree(source_root, policy, deadline)
        deadline.check()
        if actual_directories != set(directories):
            raise TaskInputError(
                "TreeMismatch", "the staged tree does not match the planned entries"
            )
        if set(actual_files) != set(copied_files):
            raise TaskInputError(
                "TreeMismatch", "the staged tree does not match the planned entries"
            )
        for path, copied_fingerprint in copied_files.items():
            deadline.check()
            if actual_files[path] != copied_fingerprint:
                raise TaskInputError(
                    "InputChanged", "a staged file differs from the bytes copied from its source"
                )
        entries: list[dict[str, object]] = [
            {"path": path, "kind": "directory", "bytes": 0, "sha256": None, "git_mode": None}
            for path in directories
        ]
        for pending in files:
            deadline.check()
            size, digest = copied_files[pending.path]
            entries.append(
                {
                    "path": pending.path,
                    "kind": "file",
                    "bytes": size,
                    "sha256": digest,
                    "git_mode": pending.git_mode,
                }
            )
        entries.sort(key=lambda entry: _path_key(entry["path"]))
        deadline.check()
        for control_path, expected_digest in policy.trusted_control_files:
            deadline.check()
            actual = actual_files.get(control_path)
            if actual is None or actual[1] != expected_digest:
                raise TaskInputError(
                    "InputControlConflict", "a trusted control file is missing or changed"
                )
        identity_entries = [
            {
                "path": entry["path"],
                "kind": entry["kind"],
                "bytes": entry["bytes"],
                "sha256": entry["sha256"],
            }
            for entry in entries
        ]
        snapshot_id = _sha256_bytes(
            _canonical_json_bytes({"contract_version": 1, "entries": identity_entries})
        )
        deadline.check()
        manifest: dict[str, object] = {
            "contract_version": 1,
            "snapshot_id": snapshot_id,
            "source": {
                "kind": source_kind,
                "identity": identity,
                "selection_sha256": selection_sha256,
            },
            "entries": entries,
            "source_paths": list(policy.source_paths),
            "excluded_paths": [
                {"path": path, "reason": reason} for path, reason in excluded_records
            ],
        }
        canonical = _canonical_json_bytes(manifest)
        deadline.check()
        _write_exclusive(staging_root / "manifest.json", canonical, deadline)
        deadline.check()
        _write_exclusive(
            staging_root / "SEALED", hashlib.sha256(canonical).hexdigest().encode("ascii"), deadline
        )
        deadline.check()
        _assert_plain_target(staging_root, label="the staging root")
        _assert_plain_target(snapshot_root, label="the snapshot output")
        deadline.check()
        # Successful rename is the commit point. The cooperative budget was
        # checked immediately above; this OS operation cannot be preempted.
        # A successful late return stays committed, with no fallible origin
        # cleanup or deadline check left to turn success into failure.
        os.rename(staging_root, snapshot_root)
        return manifest
    except BaseException as error:
        _write_failure_label(staging_root, _failure_code(error))
        raise


def _default_verification_policy() -> _Policy:
    return _Policy(
        **_LIMIT_CEILINGS,
        source_paths=(),
        excluded_paths=(),
        sensitive_paths=(),
        trusted_control_files=(),
    )


def import_snapshot(
    *, source: dict[str, object], policy: dict[str, object], snapshot_root: Path
) -> dict[str, object]:
    """Import one frozen input into a fresh, sealed snapshot root.

    Returns the sealed SnapshotManifest. The snapshot root must not exist.
    Pre-publication failures retain staging and attempt a failure label; they
    never publish the final root. One absolute cooperative deadline covers
    origin reads/close, verification and metadata, and is checked immediately
    before rename. Successful rename commits even if it returns late; no
    post-commit timing or origin cleanup can reclassify it as failure.
    """

    try:
        return _import_snapshot(source=source, policy=policy, snapshot_root=snapshot_root)
    except TaskInputError:
        raise
    except BridgePathError as error:
        raise TaskInputError("PathRejected", "an input path crossed a boundary") from error
    except BridgeContractError as error:
        raise TaskInputError("InvalidManifest", "an input manifest was rejected") from error
    except zipfile.BadZipFile as error:
        raise TaskInputError(
            "InputChanged", "the ZIP package failed its structural check"
        ) from error
    except OSError as error:
        raise TaskInputError("IoFailed", "an input or staging file operation failed") from error


def _import_snapshot(
    *, source: dict[str, object], policy: dict[str, object], snapshot_root: Path
) -> dict[str, object]:
    started_at = time.monotonic()
    if not isinstance(snapshot_root, Path) or not snapshot_root.is_absolute():
        raise TaskInputError("SnapshotRootInvalid", "snapshot_root must be an absolute path")
    snapshot_root = _validate_absolute_path(snapshot_root, label="snapshot_root")
    validated_policy = _validate_policy(policy)
    deadline = _Deadline(started_at + validated_policy.deadline_seconds)
    deadline.check()
    source_kind = _source_kind(source)
    if os.path.lexists(snapshot_root):
        raise TaskInputError("SnapshotRootNotFresh", "snapshot_root must not exist yet")
    parent = snapshot_root.parent
    if not parent.is_dir():
        raise TaskInputError("SnapshotRootInvalid", "the snapshot parent directory must exist")
    _assert_plain_target(parent, label="the snapshot output parent")
    deadline.check()
    with ExitStack() as stack:
        context = _ImportContext()
        if source_kind == "git":
            files, directories, git_root = _plan_git_selection(source, validated_policy, deadline)
            context = _ImportContext(git_root=git_root)
            identity = _require_text(source["commit"], "git commit", "InvalidSource")
        elif source_kind == "zip":
            package_path = _verify_zip_package(source, validated_policy, deadline)
            deadline.check()
            archive = stack.enter_context(zipfile.ZipFile(package_path))
            deadline.check()
            context = _ImportContext(archive=archive)
            files, directories = _plan_zip_members(archive, source, validated_policy, deadline)
            identity = _require_sha256(source["sha256"], "zip sha256", "InvalidSource")
        else:
            files, directories = _plan_directory_tree(source, validated_policy, deadline)
            identity = _require_sha256(
                source["manifest_sha256"], "manifest sha256", "InvalidSource"
            )
        kept_files, kept_directories, excluded_records = _apply_selection(
            files, directories, validated_policy, deadline
        )
        if context.git_root is not None:
            kept_files = _prefetch_git_sizes(
                kept_files, context.git_root, validated_policy, deadline
            )
        selection = _selection_digest(validated_policy.source_paths, excluded_records)
        deadline.check()
        return _stage_and_publish(
            files=kept_files,
            directories=kept_directories,
            excluded_records=excluded_records,
            policy=validated_policy,
            deadline=deadline,
            snapshot_root=snapshot_root,
            context=context,
            origin_stack=stack,
            source_kind=source_kind,
            identity=identity,
            selection_sha256=selection,
        )


def _validate_snapshot_manifest(
    document: object,
) -> tuple[dict[str, tuple[int, str]], set[str], list[tuple[str, str]]]:
    if type(document) is not dict or set(document) != _MANIFEST_KEYS:
        raise TaskInputError("InvalidManifest", "the snapshot manifest fields are not frozen")
    version = document["contract_version"]
    if type(version) is not int or version != 1:
        raise TaskInputError("InvalidManifest", "the snapshot manifest version must be 1")
    _require_sha256(document["snapshot_id"], "snapshot_id", "InvalidManifest")
    source = document["source"]
    if type(source) is not dict or set(source) != {"kind", "identity", "selection_sha256"}:
        raise TaskInputError("InvalidManifest", "the snapshot source fields are not frozen")
    source_kind = source["kind"]
    if type(source_kind) is not str or source_kind not in _SOURCE_KEYS:
        raise TaskInputError("InvalidManifest", "the snapshot source kind is unknown")
    _require_text(source["identity"], "source identity", "InvalidManifest")
    _require_sha256(source["selection_sha256"], "selection_sha256", "InvalidManifest")
    entries = document["entries"]
    if type(entries) is not list:
        raise TaskInputError("InvalidManifest", "the manifest entries must be a list")
    files: dict[str, tuple[int, str]] = {}
    directories: set[str] = set()
    previous_key: bytes | None = None
    for entry in entries:
        if type(entry) is not dict or set(entry) != _ENTRY_KEYS:
            raise TaskInputError("InvalidManifest", "a manifest entry has unknown fields")
        path = _validate_relative_path(
            entry["path"],
            label="manifest entry",
            code="InvalidManifest",
            depth_limit=_DEFAULT_DEPTH_LIMIT,
            component_codepoints_limit=_DEFAULT_COMPONENT_CODEPOINTS,
        )
        current_key = _path_key(path)
        if previous_key is not None and current_key <= previous_key:
            raise TaskInputError("InvalidManifest", "the manifest entries are not uniquely sorted")
        previous_key = current_key
        kind = entry["kind"]
        size = entry["bytes"]
        digest = entry["sha256"]
        git_mode = entry["git_mode"]
        if type(size) is not int or size < 0:
            raise TaskInputError("InvalidManifest", "a manifest entry has an invalid byte count")
        if kind == "file":
            if type(digest) is not str or not _SHA256_TEXT.fullmatch(digest):
                raise TaskInputError("InvalidManifest", "a file entry needs a SHA-256 digest")
            if git_mode is not None and (type(git_mode) is not str or git_mode not in _GIT_MODES):
                raise TaskInputError("InvalidManifest", "a file entry has an unknown Git mode")
            if path in files or path in directories:
                raise TaskInputError("InvalidManifest", "a manifest path is declared twice")
            files[path] = (size, digest)
        elif kind == "directory":
            if size != 0 or digest is not None or git_mode is not None:
                raise TaskInputError(
                    "InvalidManifest", "a directory entry must be empty and unhashed"
                )
            if path in files or path in directories:
                raise TaskInputError("InvalidManifest", "a manifest path is declared twice")
            directories.add(path)
        else:
            raise TaskInputError(
                "InvalidManifest", "a manifest entry kind must be file or directory"
            )
    for path in (*files, *directories):
        parent = _parent_path(path)
        while parent is not None:
            if parent not in directories:
                raise TaskInputError(
                    "InvalidManifest", "a manifest entry is missing an explicit parent"
                )
            parent = _parent_path(parent)
    _check_collection_conflicts(files, directories, code="InvalidManifest")
    source_paths = document["source_paths"]
    if type(source_paths) is not list:
        raise TaskInputError("InvalidManifest", "source_paths must be a list of unique paths")
    seen_source_paths: set[str] = set()
    for item in source_paths:
        path = _validate_relative_path(
            item,
            label="source path",
            code="InvalidManifest",
            depth_limit=_DEFAULT_DEPTH_LIMIT,
            component_codepoints_limit=_DEFAULT_COMPONENT_CODEPOINTS,
        )
        if path in seen_source_paths:
            raise TaskInputError("InvalidManifest", "source_paths must be a list of unique paths")
        seen_source_paths.add(path)
    excluded_entries = document["excluded_paths"]
    if type(excluded_entries) is not list:
        raise TaskInputError("InvalidManifest", "excluded_paths must be a list")
    excluded_paths: list[str] = []
    excluded_records: list[tuple[str, str]] = []
    previous_excluded: bytes | None = None
    for item in excluded_entries:
        if type(item) is not dict or set(item) != {"path", "reason"}:
            raise TaskInputError("InvalidManifest", "an excluded entry has unknown fields")
        path = _validate_relative_path(
            item["path"],
            label="excluded path",
            code="InvalidManifest",
            depth_limit=_DEFAULT_DEPTH_LIMIT,
            component_codepoints_limit=_DEFAULT_COMPONENT_CODEPOINTS,
        )
        _require_text(item["reason"], "excluded reason", "InvalidManifest")
        current_excluded = _path_key(path)
        if previous_excluded is not None and current_excluded <= previous_excluded:
            raise TaskInputError("InvalidManifest", "excluded_paths must be sorted and unique")
        previous_excluded = current_excluded
        excluded_paths.append(path)
        excluded_records.append((path, item["reason"]))
    excluded_set = set(excluded_paths)
    entry_paths = set(files) | directories
    if excluded_set & entry_paths:
        raise TaskInputError("InvalidManifest", "an excluded path is also a manifest entry")
    for prefix in excluded_paths:
        if any(_covers(prefix, path) for path in entry_paths):
            raise TaskInputError("InvalidManifest", "an excluded path covers a kept manifest entry")
    for declared in source_paths:
        if declared in files or declared in excluded_set:
            continue
        raise TaskInputError(
            "InvalidManifest", "a source path is neither a file entry nor excluded"
        )
    return files, directories, excluded_records


def _verify_tree_against_manifest(
    source_root: Path, files: dict[str, tuple[int, str]], directories: set[str]
) -> None:
    policy = _default_verification_policy()
    deadline = _Deadline.starting_now(policy.deadline_seconds)
    actual_files, actual_directories = _scan_tree(source_root, policy, deadline)
    if actual_directories != directories or actual_files != files:
        raise TaskInputError("TreeMismatch", "the sealed tree does not match the manifest")


def read_snapshot(*, snapshot_root: Path) -> dict[str, object]:
    """Re-verify a sealed snapshot and return its SnapshotManifest."""

    try:
        return _read_snapshot(snapshot_root=snapshot_root)
    except TaskInputError:
        raise
    except BridgePathError as error:
        raise TaskInputError("PathRejected", "the snapshot path crossed a boundary") from error
    except BridgeContractError as error:
        raise TaskInputError(
            "InvalidManifest", "the snapshot manifest JSON was rejected"
        ) from error
    except OSError as error:
        raise TaskInputError("IoFailed", "a snapshot file operation failed") from error


def _read_snapshot(*, snapshot_root: Path) -> dict[str, object]:
    if not isinstance(snapshot_root, Path) or not snapshot_root.is_absolute():
        raise TaskInputError("SnapshotRootInvalid", "snapshot_root must be an absolute path")
    snapshot_root = _validate_absolute_path(snapshot_root, label="snapshot_root")
    _assert_plain_target(snapshot_root, label="the sealed snapshot")
    if not snapshot_root.is_dir():
        raise TaskInputError("SnapshotRootInvalid", "snapshot_root does not hold a sealed snapshot")
    _reject_broad_root(snapshot_root, "the sealed snapshot")
    if os.path.lexists(snapshot_root / "IMPORT-FAILED"):
        raise TaskInputError("InvalidManifest", "the snapshot records a failed import")
    manifest_path = snapshot_root / "manifest.json"
    _assert_plain_target(manifest_path, label="snapshot manifest")
    raw = manifest_path.read_bytes()
    document = decode_strict_json_bytes(raw, label="snapshot manifest")
    files, directories, excluded_records = _validate_snapshot_manifest(document)
    canonical = _canonical_json_bytes(document)
    if raw != canonical:
        raise TaskInputError(
            "ManifestNotCanonical", "manifest.json is not the canonical serialization"
        )
    seal_path = snapshot_root / "SEALED"
    _assert_plain_target(seal_path, label="snapshot seal")
    sealed = seal_path.read_bytes()
    if sealed != hashlib.sha256(canonical).hexdigest().encode("ascii"):
        raise TaskInputError("SealedMismatch", "SEALED does not match the manifest digest")
    identity_entries = [
        {
            "path": entry["path"],
            "kind": entry["kind"],
            "bytes": entry["bytes"],
            "sha256": entry["sha256"],
        }
        for entry in document["entries"]
    ]
    recomputed = _sha256_bytes(
        _canonical_json_bytes({"contract_version": 1, "entries": identity_entries})
    )
    if recomputed != document["snapshot_id"]:
        raise TaskInputError("IdentityMismatch", "snapshot_id does not match the canonical entries")
    recomputed_selection = _selection_digest(document["source_paths"], excluded_records)
    if recomputed_selection != document["source"]["selection_sha256"]:
        raise TaskInputError(
            "InvalidManifest", "selection_sha256 does not match the recorded selection"
        )
    _verify_tree_against_manifest(snapshot_root / "source", files, directories)
    return document
