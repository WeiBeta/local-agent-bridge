"""Frozen task input snapshots (task contract v1, package A).

Imports one caller-authorized engineering input into a sealed snapshot root:
an exact Git commit file selection, a hash-pinned ZIP package, or a directory
adjudicated against a trusted per-file manifest. The canonical manifest and
its plain byte tree are the single input identity that later task packages
copy from, and re-reading always re-verifies the seal, the identity and the
tree.

The module is deliberately offline: no model, upstream CLI, credential,
network or shell access happens here. Only the caller-provided input roots
and a fresh snapshot root are touched; failures keep the dedicated staging
root with a failure label instead of publishing a manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
import unicodedata
import zipfile
from collections.abc import Iterator
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contract import BridgeContractError, decode_strict_json_bytes
from .paths import BridgePathError, _is_reparse, _run_git

__all__ = ["TaskInputError", "import_snapshot", "read_snapshot"]

_STREAM_CHUNK_BYTES = 1024 * 1024
_SHA256_TEXT = re.compile(r"[0-9a-f]{64}")
_COMMIT_TEXT = re.compile(r"[0-9a-f]{40}")
_FORBIDDEN_NAME_CHARS = frozenset('<>:"|?*')
_RESERVED_DOS_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
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
_DEFAULT_DEPTH_LIMIT = _LIMIT_CEILINGS["depth_limit"]
_DEFAULT_COMPONENT_CODEPOINTS = _LIMIT_CEILINGS["component_codepoints_limit"]


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
        if time.monotonic() > self.expires_at:
            raise TaskInputError("DeadlineExceeded", "the import exceeded its deadline")

    def remaining_seconds(self) -> float:
        return max(0.1, self.expires_at - time.monotonic())


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
    stem = component.split(".", 1)[0].upper()
    if stem in _RESERVED_DOS_NAMES:
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
    if not root.is_absolute():
        raise TaskInputError("InvalidSource", f"{label} must be an absolute path")
    if str(root).startswith("\\\\"):
        raise TaskInputError("PathRejected", f"{label} must not be a UNC path")
    if root == Path(root.anchor):
        raise TaskInputError("PathRejected", f"{label} must not be a drive root")
    if root in _broad_user_roots():
        raise TaskInputError("PathRejected", f"{label} is too broad to be a task input")


def _assert_plain_target(path: Path, *, label: str) -> None:
    """Reject a reparse point at the target itself or anywhere in its chain.

    Each call is a point-in-time check and does not close the race where the
    chain is swapped right afterwards; writes and publishes therefore re-run
    it at their own step instead of trusting an earlier verdict.
    """

    current = path
    while True:
        if _is_reparse(current):
            raise TaskInputError("PathRejected", f"{label} or its chain contains a reparse point")
        if current.parent == current:
            break
        current = current.parent


def _validate_absolute_directory(value: object, *, label: str) -> Path:
    text = _require_text(value, label, "InvalidSource")
    root = Path(text)
    _reject_broad_root(root, label)
    _assert_plain_target(root, label=label)
    if not root.is_dir():
        raise TaskInputError("InvalidSource", f"{label} is not an existing directory")
    return root


def _validate_absolute_file(value: object, *, label: str) -> Path:
    text = _require_text(value, label, "InvalidSource")
    path = Path(text)
    _reject_broad_root(path, label)
    _assert_plain_target(path, label=label)
    if not path.is_file():
        raise TaskInputError("InvalidSource", f"{label} is not an existing file")
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


def _selection_sha256(policy: _Policy) -> str:
    payload = {
        "source_paths": list(policy.source_paths),
        "excluded_paths": [
            {"path": path, "reason": reason} for path, reason in policy.excluded_paths
        ],
    }
    return _sha256_bytes(_canonical_json_bytes(payload))


def _parent_path(path: str) -> str | None:
    index = path.rfind("/")
    if index <= 0:
        return None
    return path[:index]


def _covers(prefix: str, path: str) -> bool:
    return prefix == path or path.startswith(prefix + "/")


def _check_collection_conflicts(files: dict[str, _PendingFile], directories: set[str]) -> None:
    if set(files) & directories:
        raise TaskInputError("PathConflict", "a path is declared as both a file and a directory")
    folded: dict[str, str] = {}
    for path in (*files, *directories):
        key = unicodedata.normalize("NFC", path).casefold()
        previous = folded.get(key)
        if previous is not None and previous != path:
            raise TaskInputError(
                "PathConflict", "distinct input names collide under NFC or Windows case folding"
            )
        folded[key] = path
    for path in files:
        parent = _parent_path(path)
        while parent is not None:
            if parent in files:
                raise TaskInputError(
                    "PathConflict", "a file entry is also a parent of another entry"
                )
            parent = _parent_path(parent)


def _zip_entry_name(info: zipfile.ZipInfo, policy: _Policy) -> tuple[str, bool]:
    original = getattr(info, "orig_filename", info.filename)
    if original != info.filename or "\x00" in original:
        raise TaskInputError("ZipEntryRejected", "an archive name hides text after a NUL")
    name = info.filename
    trailing_directory = name.endswith("/")
    if trailing_directory:
        name = name[:-1]
    if not name:
        return "", trailing_directory
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


def _plan_zip_members(
    archive: zipfile.ZipFile, source: dict[str, object], policy: _Policy
) -> tuple[dict[str, _PendingFile], set[str]]:
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
    if len(infos) > policy.entry_count_limit:
        raise TaskInputError("ResourceLimitExceeded", "the package exceeds the entry count limit")
    files: dict[str, _PendingFile] = {}
    directories: set[str] = set()
    for info in infos:
        name, trailing_directory = _zip_entry_name(info, policy)
        kind = "directory" if not name else _zip_entry_kind(info, trailing_directory)
        if not name:
            continue
        if strip_prefix is not None:
            if name == strip_prefix:
                if kind != "directory":
                    raise TaskInputError(
                        "StripPrefixMismatch", "the strip prefix entry is not a directory"
                    )
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
    _check_collection_conflicts(files, directories)
    return files, directories


def _verify_zip_package(source: dict[str, object], policy: _Policy) -> Path:
    package_path = _validate_absolute_file(source["path"], label="zip package path")
    declared_sha256 = _require_sha256(source["sha256"], "zip sha256", "InvalidSource")
    if package_path.stat().st_size > policy.package_bytes_limit:
        raise TaskInputError("ResourceLimitExceeded", "the package exceeds the package bytes limit")
    if _hash_file(package_path) != declared_sha256:
        raise TaskInputError("InputChanged", "the package hash differs from the declared value")
    return package_path


def _git_text(root: Path, *arguments: str) -> str:
    try:
        return _run_git(root, *arguments)
    except BridgePathError as error:
        raise TaskInputError("GitCommandFailed", "the bounded Git listing failed") from error


def _parse_git_listing(listing: str) -> dict[str, tuple[str, str, str]]:
    objects: dict[str, tuple[str, str, str]] = {}
    for record in listing.split("\x00"):
        if not record:
            continue
        header, separator, path = record.partition("\t")
        fields = header.split(" ") if separator else []
        if len(fields) != 3:
            raise TaskInputError(
                "GitCommandFailed", "the Git listing was not in the expected shape"
            )
        objects[path] = (fields[0], fields[1], fields[2])
    return objects


def _plan_git_selection(
    source: dict[str, object], policy: _Policy
) -> tuple[dict[str, _PendingFile], set[str], Path]:
    root = _validate_absolute_directory(source["root"], label="git root")
    commit = _require_text(source["commit"], "git commit", "InvalidSource")
    if not _COMMIT_TEXT.fullmatch(commit):
        raise TaskInputError("InvalidSource", "git commit must be an exact 40 character object id")
    raw_paths = source["paths"]
    if type(raw_paths) is not list:
        raise TaskInputError("InvalidSource", "git paths must be a list of exact files")
    selected: list[str] = []
    seen_paths: set[str] = set()
    for item in raw_paths:
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
    object_type = _git_text(root, "cat-file", "-t", commit).strip()
    if object_type != "commit":
        raise TaskInputError("GitSelectionInvalid", "the declared Git object is not a commit")
    objects = _parse_git_listing(_git_text(root, "ls-tree", "-rz", "--full-tree", commit))
    files: dict[str, _PendingFile] = {}
    for path in selected:
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
    _check_collection_conflicts(files, set())
    return files, set(), root


def _validate_directory_manifest(
    document: object,
) -> tuple[dict[str, tuple[int, str]], set[str]]:
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
        parent = _parent_path(path)
        while parent is not None:
            if parent not in directories:
                raise TaskInputError(
                    "InputManifestMismatch", "a manifest entry is missing an explicit parent"
                )
            parent = _parent_path(parent)
    return files, directories


def _scan_tree(
    root: Path, policy: _Policy, deadline: _Deadline
) -> tuple[dict[str, tuple[int, str]], set[str]]:
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
        for name in filenames:
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
            files[relative] = (information.st_size, _hash_file(child))
    return files, directories


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_STREAM_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plan_directory_tree(
    source: dict[str, object], policy: _Policy, deadline: _Deadline
) -> tuple[dict[str, _PendingFile], set[str]]:
    root = _validate_absolute_directory(source["root"], label="directory root")
    manifest_path = _validate_absolute_file(
        source["manifest_path"], label="directory manifest path"
    )
    declared_sha256 = _require_sha256(source["manifest_sha256"], "manifest sha256", "InvalidSource")
    raw = manifest_path.read_bytes()
    if _sha256_bytes(raw) != declared_sha256:
        raise TaskInputError(
            "InputManifestMismatch", "the directory manifest hash differs from the declared value"
        )
    document = decode_strict_json_bytes(raw, label="directory manifest")
    declared_files, declared_directories = _validate_directory_manifest(document)
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
    _check_collection_conflicts(files, set(actual_directories))
    return files, actual_directories


def _apply_selection(
    files: dict[str, _PendingFile], directories: set[str], policy: _Policy
) -> tuple[list[_PendingFile], list[str]]:
    excluded = policy.excluded_paths
    all_paths = (*files, *directories)
    for prefix, _reason in excluded:
        if not any(_covers(prefix, path) for path in all_paths):
            raise TaskInputError(
                "ExcludedPathUnknown", "an excluded path is not present in the input"
            )
    kept_files = {
        path: pending
        for path, pending in files.items()
        if not any(_covers(prefix, path) for prefix, _reason in excluded)
    }
    kept_directories = {
        path
        for path in directories
        if not any(_covers(prefix, path) for prefix, _reason in excluded)
    }
    for path in kept_files:
        parent = _parent_path(path)
        while parent is not None:
            if parent in files:
                raise TaskInputError("PathConflict", "a kept file sits under a file entry")
            kept_directories.add(parent)
            parent = _parent_path(parent)
    for prefix in policy.sensitive_paths:
        for path in kept_files:
            if _covers(prefix, path):
                raise TaskInputError(
                    "SensitivePathImported", "a declared sensitive path would enter the snapshot"
                )
    for declared in policy.source_paths:
        if declared in kept_files:
            continue
        if any(_covers(prefix, declared) for prefix, _reason in excluded):
            continue
        raise TaskInputError(
            "SourcePathUnaccounted", "a declared source path is neither imported nor excluded"
        )
    if len(kept_files) + len(kept_directories) > policy.entry_count_limit:
        raise TaskInputError("ResourceLimitExceeded", "the input exceeds the entry count limit")
    declared_total = sum(
        pending.declared_bytes if pending.declared_bytes is not None else 0
        for pending in kept_files.values()
    )
    if declared_total > policy.expanded_bytes_limit:
        raise TaskInputError("ResourceLimitExceeded", "the input exceeds the expanded bytes limit")
    return (
        sorted(kept_files.values(), key=lambda pending: _path_key(pending.path)),
        sorted(kept_directories, key=_path_key),
    )


def _utf16_length(value: str) -> int:
    return sum(2 if ord(char) > 0xFFFF else 1 for char in value)


def _check_physical_budget(path: Path, policy: _Policy) -> None:
    if _utf16_length(str(path)) > policy.physical_path_utf16_limit:
        raise TaskInputError(
            "PathBudgetExceeded", "a staging path exceeds the physical UTF-16 budget"
        )


def _ensure_directory(source_root: Path, relative: str, created: set[str], policy: _Policy) -> None:
    if relative in created:
        return
    parent = _parent_path(relative)
    if parent is not None:
        _ensure_directory(source_root, parent, created, policy)
    target = source_root.joinpath(*relative.split("/"))
    _check_physical_budget(target, policy)
    _assert_plain_target(target, label="a staging directory")
    os.mkdir(target)
    created.add(relative)


def _file_chunks(path: Path, deadline: _Deadline) -> Iterator[bytes]:
    _assert_plain_target(path, label="an adjudicated input file")
    information = path.lstat()
    if _is_reparse(path) or not stat.S_ISREG(information.st_mode):
        raise TaskInputError("InputChanged", "an adjudicated file changed shape before the copy")
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_STREAM_CHUNK_BYTES)
            if not chunk:
                break
            deadline.check()
            yield chunk


def _zip_chunks(archive: zipfile.ZipFile, member: str, deadline: _Deadline) -> Iterator[bytes]:
    with archive.open(member, "r") as reader:
        while True:
            chunk = reader.read(_STREAM_CHUNK_BYTES)
            if not chunk:
                break
            deadline.check()
            yield chunk


def _git_bytes(root: Path, arguments: list[str], deadline: _Deadline) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise TaskInputError("GitUnavailable", "git is not available on this host")
    try:
        completed = subprocess.run(
            [executable, "-C", str(root), *arguments],
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
    if completed.returncode != 0:
        raise TaskInputError("GitCommandFailed", "a bounded Git read failed")
    return completed.stdout


def _git_chunks(root: Path, blob_ref: str, policy: _Policy, deadline: _Deadline) -> Iterator[bytes]:
    size_text = _git_bytes(root, ["cat-file", "-s", blob_ref], deadline).decode("ascii").strip()
    if not size_text.isdigit() or int(size_text) > policy.file_bytes_limit:
        raise TaskInputError("ResourceLimitExceeded", "a Git blob exceeds the file bytes limit")
    raw = _git_bytes(root, ["cat-file", "blob", blob_ref], deadline)
    for start in range(0, len(raw), _STREAM_CHUNK_BYTES):
        deadline.check()
        yield raw[start : start + _STREAM_CHUNK_BYTES]


def _pending_chunks(
    pending: _PendingFile, context: _ImportContext, policy: _Policy, deadline: _Deadline
) -> Iterator[bytes]:
    if pending.disk_path is not None:
        yield from _file_chunks(pending.disk_path, deadline)
    elif pending.blob_ref is not None and context.git_root is not None:
        yield from _git_chunks(context.git_root, pending.blob_ref, policy, deadline)
    elif pending.zip_name is not None and context.archive is not None:
        yield from _zip_chunks(context.archive, pending.zip_name, deadline)
    else:
        raise TaskInputError("InvalidSource", "a pending file has no usable origin")


def _write_stream(
    target: Path,
    chunks: Iterator[bytes],
    policy: _Policy,
    deadline: _Deadline,
    expanded_before: int,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    _assert_plain_target(target, label="a staged file")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "wb") as handle:
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
            handle.write(chunk)
    return total, digest.hexdigest()


def _write_exclusive(target: Path, raw: bytes) -> None:
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)


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
    policy: _Policy,
    deadline: _Deadline,
    snapshot_root: Path,
    context: _ImportContext,
    source_kind: str,
    identity: str,
    selection_sha256: str,
) -> dict[str, object]:
    staging_root = snapshot_root.with_name(snapshot_root.name + ".staging")
    if os.path.lexists(staging_root):
        raise TaskInputError("SnapshotRootNotFresh", "a staging root already exists")
    source_root = staging_root / "source"
    for relative in (*(pending.path for pending in files), *directories):
        _check_physical_budget(source_root.joinpath(*relative.split("/")), policy)
    _assert_plain_target(staging_root, label="the staging root")
    os.mkdir(staging_root)
    try:
        os.mkdir(source_root)
        created_directories: set[str] = set()
        for relative in directories:
            _ensure_directory(source_root, relative, created_directories, policy)
        expanded_total = 0
        for pending in files:
            parent = _parent_path(pending.path)
            if parent is not None:
                _ensure_directory(source_root, parent, created_directories, policy)
            target = source_root.joinpath(*pending.path.split("/"))
            _check_physical_budget(target, policy)
            total, digest = _write_stream(
                target,
                _pending_chunks(pending, context, policy, deadline),
                policy,
                deadline,
                expanded_total,
            )
            expanded_total += total
            if pending.declared_bytes is not None and total != pending.declared_bytes:
                raise TaskInputError("InputChanged", "a staged file differs from its declared size")
            if pending.expected_sha256 is not None and digest != pending.expected_sha256:
                raise TaskInputError(
                    "InputChanged", "a staged file differs from its manifest digest"
                )
        actual_files, actual_directories = _scan_tree(source_root, policy, deadline)
        if actual_directories != set(directories):
            raise TaskInputError(
                "TreeMismatch", "the staged tree does not match the planned entries"
            )
        if set(actual_files) != {pending.path for pending in files}:
            raise TaskInputError(
                "TreeMismatch", "the staged tree does not match the planned entries"
            )
        entries: list[dict[str, object]] = [
            {"path": path, "kind": "directory", "bytes": 0, "sha256": None, "git_mode": None}
            for path in directories
        ]
        for pending in files:
            size, digest = actual_files[pending.path]
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
        for control_path, expected_digest in policy.trusted_control_files:
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
                {"path": path, "reason": reason} for path, reason in policy.excluded_paths
            ],
        }
        canonical = _canonical_json_bytes(manifest)
        _write_exclusive(staging_root / "manifest.json", canonical)
        _write_exclusive(
            staging_root / "SEALED", hashlib.sha256(canonical).hexdigest().encode("ascii")
        )
        _assert_plain_target(staging_root, label="the staging root")
        _assert_plain_target(snapshot_root, label="the snapshot output")
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

    Returns the sealed SnapshotManifest. The snapshot root must not exist;
    on failure the dedicated staging root is kept with a failure label and no
    manifest is published.
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
    if not isinstance(snapshot_root, Path) or not snapshot_root.is_absolute():
        raise TaskInputError("SnapshotRootInvalid", "snapshot_root must be an absolute path")
    validated_policy = _validate_policy(policy)
    deadline = _Deadline.starting_now(validated_policy.deadline_seconds)
    source_kind = _source_kind(source)
    if os.path.lexists(snapshot_root):
        raise TaskInputError("SnapshotRootNotFresh", "snapshot_root must not exist yet")
    parent = snapshot_root.parent
    if not parent.is_dir():
        raise TaskInputError("SnapshotRootInvalid", "the snapshot parent directory must exist")
    _assert_plain_target(parent, label="the snapshot output parent")
    selection = _selection_sha256(validated_policy)
    with ExitStack() as stack:
        context = _ImportContext()
        if source_kind == "git":
            files, directories, git_root = _plan_git_selection(source, validated_policy)
            context = _ImportContext(git_root=git_root)
            identity = _require_text(source["commit"], "git commit", "InvalidSource")
        elif source_kind == "zip":
            package_path = _verify_zip_package(source, validated_policy)
            archive = stack.enter_context(zipfile.ZipFile(package_path))
            context = _ImportContext(archive=archive)
            files, directories = _plan_zip_members(archive, source, validated_policy)
            identity = _require_sha256(source["sha256"], "zip sha256", "InvalidSource")
        else:
            files, directories = _plan_directory_tree(source, validated_policy, deadline)
            identity = _require_sha256(
                source["manifest_sha256"], "manifest sha256", "InvalidSource"
            )
        kept_files, kept_directories = _apply_selection(files, directories, validated_policy)
        return _stage_and_publish(
            files=kept_files,
            directories=kept_directories,
            policy=validated_policy,
            deadline=deadline,
            snapshot_root=snapshot_root,
            context=context,
            source_kind=source_kind,
            identity=identity,
            selection_sha256=selection,
        )


def _validate_snapshot_manifest(
    document: object,
) -> tuple[dict[str, tuple[int, str]], set[str]]:
    if type(document) is not dict or set(document) != _MANIFEST_KEYS:
        raise TaskInputError("InvalidManifest", "the snapshot manifest fields are not frozen")
    version = document["contract_version"]
    if type(version) is not int or version != 1:
        raise TaskInputError("InvalidManifest", "the snapshot manifest version must be 1")
    _require_sha256(document["snapshot_id"], "snapshot_id", "InvalidManifest")
    source = document["source"]
    if type(source) is not dict or set(source) != {"kind", "identity", "selection_sha256"}:
        raise TaskInputError("InvalidManifest", "the snapshot source fields are not frozen")
    if source["kind"] not in _SOURCE_KEYS:
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
            if git_mode is not None and git_mode not in _GIT_MODES:
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
    source_paths = document["source_paths"]
    if type(source_paths) is not list or len(set(source_paths)) != len(source_paths):
        raise TaskInputError("InvalidManifest", "source_paths must be a list of unique paths")
    for item in source_paths:
        _validate_relative_path(
            item,
            label="source path",
            code="InvalidManifest",
            depth_limit=_DEFAULT_DEPTH_LIMIT,
            component_codepoints_limit=_DEFAULT_COMPONENT_CODEPOINTS,
        )
    excluded_entries = document["excluded_paths"]
    if type(excluded_entries) is not list:
        raise TaskInputError("InvalidManifest", "excluded_paths must be a list")
    excluded_paths: list[str] = []
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
    for declared in source_paths:
        if declared in files:
            continue
        if any(_covers(prefix, declared) for prefix in excluded_paths):
            continue
        raise TaskInputError(
            "InvalidManifest", "a source path is neither a file entry nor excluded"
        )
    return files, directories


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
    _assert_plain_target(snapshot_root, label="the sealed snapshot")
    if not snapshot_root.is_dir():
        raise TaskInputError("SnapshotRootInvalid", "snapshot_root does not hold a sealed snapshot")
    raw = (snapshot_root / "manifest.json").read_bytes()
    document = decode_strict_json_bytes(raw, label="snapshot manifest")
    files, directories = _validate_snapshot_manifest(document)
    canonical = _canonical_json_bytes(document)
    if raw != canonical:
        raise TaskInputError(
            "ManifestNotCanonical", "manifest.json is not the canonical serialization"
        )
    sealed = (snapshot_root / "SEALED").read_bytes()
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
    _verify_tree_against_manifest(snapshot_root / "source", files, directories)
    return document
