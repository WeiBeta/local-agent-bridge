"""Offline role workspaces and byte-preserving collection for task contract v1.

Control files are Host records, not an OS sandbox. Collection records scope,
structure and evidence observations; it never accepts business quality or starts
a model. The retained control/snapshot uses A's existing sealed snapshot format.
"""

from __future__ import annotations

import os
from collections import Counter
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import task_input as inputs
from .contract import TASK_DEADLINE_MAX_SECONDS, BridgeContractError, decode_strict_json_bytes
from .paths import BridgePathError

__all__ = ["TaskWorkspaceError", "collect_task", "prepare_task", "verify_input_controls"]

_TASK_KEYS = {
    "contract_version",
    "task_id",
    "role",
    "snapshot_id",
    "snapshot_manifest_sha256",
    "instructions_sha256",
    "deployment_profile_id",
    "deployment_profile_sha256",
    "capabilities",
    "execution_boundary",
    "authorization_sha256",
    "read_roots",
    "write_roots",
    "protected_paths",
    "required_outputs",
    "acceptance_ids",
    "deadline_seconds",
    "source_output_bytes_limit",
}
_PROFILE_KEYS = {
    "contract_version",
    "id",
    "host",
    "receipt_sha256",
    "roles",
    "supported_capabilities",
    "execution_modes",
    "read_roots",
    "write_roots",
    "toolchain_refs",
    "enforcement",
}
_AUTH_KEYS = {
    "contract_version",
    "task_id",
    "grant_ref",
    "receipt_sha256",
    "capabilities",
    "execution_boundary",
    "read_roots",
    "write_roots",
    "web_scope",
    "dependency_scope",
    "input_control_bindings",
}
_PLAN_KEYS = {
    "contract_version",
    "task_id",
    "task_manifest_sha256",
    "deployment_receipt_sha256",
    "host",
    "route",
    "execution_boundary",
    "capabilities",
    "preflight_status",
    "blockers",
    "evidence_refs",
}
_RUN_KEYS = {
    "contract_version",
    "task_id",
    "plan_sha256",
    "transport_state",
    "launch_count",
    "capture_uid",
    "capture_state",
    "restore_state",
    "test_observations",
    "evidence_refs",
    "blockers",
}
_TEST_KEYS = {
    "test_run_id",
    "phase",
    "recipe_id",
    "toolchain_sha256",
    "source_tree_sha256",
    "exit_code",
    "start_utc",
    "end_utc",
    "evidence_refs",
    "origin",
}
_CAPABILITIES = {"execute", "web_reference", "prepare_dependencies"}
_MODES = {"declared_scope", "required_enforced"}
_ROLES = {"Coding", "Review"}
_ROOTS = {"control", "out", "scratch", "work"}
_GENERATED_NAMES = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "build"}
_GENERATED_CACHE_NAMES = _GENERATED_NAMES - {"build"}
_AUTO_CONTROL_NAMES = {"AGENTS.md", "GEMINI.md", "CLAUDE.md", ".cursorrules"}
_AUTO_CONTROL_PATHS = {".cursor/cli.json", ".gemini/settings.json", ".claude/settings.json"}


class TaskWorkspaceError(RuntimeError):
    """A stable, non-sensitive workspace failure; original causes stay chained."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fail(code: str = "InvalidTask") -> None:
    raise TaskWorkspaceError(code, "the frozen task workspace contract was not satisfied")


def _object(value: Any, keys: set[str], code: str = "InvalidTask") -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _fail(code)
    return value


def _version(value: dict[str, Any], code: str = "InvalidTask") -> None:
    if type(value["contract_version"]) is not int or value["contract_version"] != 1:
        _fail(code)


def _text(value: Any, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    inputs._require_text(value, "contract string", "InvalidTask")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise TaskWorkspaceError("InvalidTask", "a contract string is not UTF-8") from error


def _hash(value: Any, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    inputs._require_sha256(value, "contract digest", "InvalidTask")


def _enum(value: Any, choices: set[str]) -> None:
    if type(value) is not str or value not in choices:
        _fail()


def _integer(value: Any, minimum: int = 0, maximum: int | None = None) -> None:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        _fail()


def _path(value: Any) -> str:
    return inputs._validate_relative_path(
        value,
        label="contract path",
        code="InvalidTask",
        depth_limit=32,
        component_codepoints_limit=255,
    )


def _strings(value: Any) -> None:
    if type(value) is not list:
        _fail()
    for item in value:
        _text(item)
    if len(set(value)) != len(value):
        _fail()


def _paths(value: Any) -> None:
    _strings(value)
    for item in value:
        _path(item)
    if value != sorted(value, key=inputs._path_key):
        _fail()
    identities = [inputs._path_identity_key(item) for item in value]
    if len(set(identities)) != len(identities):
        _fail()


def _capabilities(value: Any) -> None:
    _object(value, _CAPABILITIES)
    if any(type(item) is not bool for item in value.values()):
        _fail()
    if value["prepare_dependencies"] and not value["execute"]:
        _fail()


def _evidence(value: Any) -> None:
    if type(value) is not list:
        _fail()
    for item in value:
        _object(item, {"ref", "sha256", "origin"})
        _text(item["ref"])
        _hash(item["sha256"], nullable=True)
        _enum(item["origin"], {"WorkerReported", "HostObserved"})


def _under(path: str, roots: list[str]) -> bool:
    return any(inputs._scope_covers(root, path) for root in roots)


def _task_shape(task: Any) -> None:
    _object(task, _TASK_KEYS)
    _version(task)
    for name in ("task_id", "deployment_profile_id"):
        _text(task[name])
    for name in (
        "snapshot_id",
        "snapshot_manifest_sha256",
        "instructions_sha256",
        "deployment_profile_sha256",
        "authorization_sha256",
    ):
        _hash(task[name])
    _enum(task["role"], _ROLES)
    _enum(task["execution_boundary"], _MODES)
    _capabilities(task["capabilities"])
    _integer(task["deadline_seconds"], 1, TASK_DEADLINE_MAX_SECONDS)
    _integer(task["source_output_bytes_limit"], 1)
    for name in ("read_roots", "write_roots", "protected_paths", "required_outputs"):
        _paths(task[name])
    _strings(task["acceptance_ids"])
    for root in task["read_roots"] + task["write_roots"]:
        if not _under(root, list(_ROOTS)):
            _fail("ScopeRejected")
    for path in task["protected_paths"]:
        if path not in {"task.json", "SEALED", ".cursor", ".cursor/cli.json"} and not _under(
            path, list(_ROOTS)
        ):
            _fail("ScopeRejected")
    if not _under("control", task["protected_paths"]) or not _under(
        "task.json", task["protected_paths"]
    ):
        _fail("ScopeRejected")
    for root in task["write_roots"]:
        if _under(root, task["protected_paths"]) or not _under(root, task["read_roots"]):
            _fail("ScopeRejected")
        if task["role"] == "Review" and not _under(root, ["out", "scratch"]):
            _fail("ScopeRejected")
    for path in task["required_outputs"]:
        if not path.startswith("out/") or not _under(path, task["write_roots"]):
            _fail("ScopeRejected")
        if _under(path, task["protected_paths"]):
            _fail("ScopeRejected")
    if "out/progress.json" not in task["required_outputs"]:
        _fail("InvalidTask")


def _profile_shape(profile: Any) -> None:
    _object(profile, _PROFILE_KEYS)
    _version(profile)
    _text(profile["id"])
    _enum(profile["host"], {"agy", "cursor"})
    _hash(profile["receipt_sha256"])
    _capabilities(profile["supported_capabilities"])
    for name, choices in (("roles", _ROLES), ("execution_modes", _MODES)):
        _strings(profile[name])
        if not profile[name]:
            _fail()
        for item in profile[name]:
            _enum(item, choices)
    for name in ("read_roots", "write_roots"):
        _paths(profile[name])
        if any(not _under(root, list(_ROOTS)) for root in profile[name]):
            _fail("ScopeRejected")
    _strings(profile["toolchain_refs"])
    enforcement = _object(
        profile["enforcement"], {"method", "file_scope", "network_scope", "evidence_refs"}
    )
    _text(enforcement["method"])
    for name in ("file_scope", "network_scope"):
        _enum(enforcement[name], {"Declared", "Enforced", "Unverified"})
    _evidence(enforcement["evidence_refs"])


def _authorization_shape(auth: Any) -> None:
    if type(auth) is dict and "input_control_bindings" not in auth:
        _fail("InputControlConflict")
    _object(auth, _AUTH_KEYS)
    _version(auth)
    for name in ("task_id", "grant_ref"):
        _text(auth[name])
    _hash(auth["receipt_sha256"])
    _capabilities(auth["capabilities"])
    _enum(auth["execution_boundary"], _MODES)
    for name in ("read_roots", "write_roots"):
        _paths(auth[name])
        if any(not _under(root, list(_ROOTS)) for root in auth[name]):
            _fail("ScopeRejected")
    for name in ("web_scope", "dependency_scope"):
        _text(auth[name], nullable=True)
    if auth["capabilities"]["web_reference"] and auth["web_scope"] is None:
        _fail("AuthorizationMismatch")
    if auth["capabilities"]["prepare_dependencies"] and auth["dependency_scope"] is None:
        _fail("AuthorizationMismatch")
    binding = _object(
        auth["input_control_bindings"], {"task_fields_sha256", "files"}, "InputControlConflict"
    )
    inputs._require_sha256(binding["task_fields_sha256"], "task projection", "InputControlConflict")
    if type(binding["files"]) is not dict:
        _fail("InputControlConflict")
    identities = set()
    for path, digest in binding["files"].items():
        _path(path)
        inputs._require_sha256(digest, "input rule digest", "InputControlConflict")
        identity = inputs._path_identity_key(path)
        if identity in identities:
            _fail("InputControlConflict")
        identities.add(identity)


def _rule_paths(paths: Any) -> set[str]:
    names = {inputs._path_identity_key(name) for name in _AUTO_CONTROL_NAMES}
    return {path for path in paths if inputs._path_identity_key(path.rsplit("/", 1)[-1]) in names}


def _validate_input_controls(
    task: Any,
    auth: Any,
    snapshot: Any,
    current_files: dict[str, tuple[int, str]],
    current_directories: set[str],
) -> None:
    """Verify a Host-supplied declaration, without interpreting instruction text."""
    binding = auth["input_control_bindings"]
    projection = {key: value for key, value in task.items() if key != "authorization_sha256"}
    if binding["task_fields_sha256"] != inputs._sha256_bytes(
        inputs._canonical_json_bytes(projection)
    ):
        _fail("InputControlConflict")
    baseline, directories, _ = inputs._validate_snapshot_manifest(snapshot)
    for path in (*baseline, *directories, *current_files, *current_directories):
        if any(inputs._scope_covers(control, path) for control in _AUTO_CONTROL_PATHS):
            _fail("InputControlConflict")
    expected = _rule_paths(baseline)
    declared = binding["files"]
    # Logical comparison discovers rule classes; membership remains exact raw names.
    if set(declared) != expected or _rule_paths(current_files) != expected:
        _fail("InputControlConflict")
    for path in expected:
        if (
            declared[path] != baseline[path][1]
            or current_files[path] != baseline[path]
            or not _under("work/" + path, task["protected_paths"])
        ):
            _fail("InputControlConflict")


def _validate_binding(task: Any, profile: Any, auth: Any, note: bytes, snapshot: Any) -> None:
    _task_shape(task)
    _profile_shape(profile)
    _authorization_shape(auth)
    baseline, directories, _ = inputs._validate_snapshot_manifest(snapshot)
    _validate_input_controls(task, auth, snapshot, baseline, directories)
    if type(note) is not bytes:
        _fail()
    bindings = (
        (task["instructions_sha256"], inputs._sha256_bytes(note)),
        (
            task["deployment_profile_sha256"],
            inputs._sha256_bytes(inputs._canonical_json_bytes(profile)),
        ),
        (task["authorization_sha256"], inputs._sha256_bytes(inputs._canonical_json_bytes(auth))),
        (task["snapshot_id"], snapshot["snapshot_id"]),
        (
            task["snapshot_manifest_sha256"],
            inputs._sha256_bytes(inputs._canonical_json_bytes(snapshot)),
        ),
        (task["deployment_profile_id"], profile["id"]),
        (task["task_id"], auth["task_id"]),
        (task["execution_boundary"], auth["execution_boundary"]),
    )
    if any(left != right for left, right in bindings):
        _fail("BindingMismatch")
    if (
        task["role"] not in profile["roles"]
        or task["execution_boundary"] not in profile["execution_modes"]
    ):
        _fail("DeploymentMismatch")
    if profile["host"] == "cursor" and not _under(".cursor/cli.json", task["protected_paths"]):
        _fail("ScopeRejected")
    for name, enabled in task["capabilities"].items():
        if enabled and (
            not profile["supported_capabilities"][name] or not auth["capabilities"][name]
        ):
            _fail("AuthorizationMismatch")
    for name in ("read_roots", "write_roots"):
        if any(
            not _under(root, profile[name]) or not _under(root, auth[name]) for root in task[name]
        ):
            _fail("AuthorizationMismatch")


def _root(root: Path, *, fresh: bool) -> None:
    if not isinstance(root, Path):
        _fail("RootInvalid")
    inputs._assert_plain_target(root, label="workspace root")
    if fresh:
        if os.path.lexists(root) or not root.parent.is_dir():
            _fail("RootNotFresh")
    elif not root.is_dir():
        _fail("RootInvalid")
    else:
        inputs._reject_broad_root(root, "workspace root")


def _separate(*roots: Path) -> None:
    for index, root in enumerate(roots):
        for other in roots[index + 1 :]:
            if root == other or root.is_relative_to(other) or other.is_relative_to(root):
                _fail("ScopeRejected")


def _budget(path: Path) -> None:
    if inputs._utf16_length(str(path)) > 240:
        _fail("PathBudgetExceeded")


def _mkdir(path: Path) -> None:
    inputs._assert_plain_target(path, label="workspace directory")
    _budget(path)
    path.mkdir()


def _write(path: Path, raw: bytes, deadline: inputs._Deadline) -> None:
    _budget(path)
    inputs._write_exclusive(path, raw, deadline)


def _copy(path: Path, target: Path, stamp: tuple[int, str], deadline: inputs._Deadline) -> None:
    """Use A's streaming writer; never link, decode or overwrite candidate bytes."""
    policy = inputs._default_verification_policy()
    policy = replace(
        policy,
        file_bytes_limit=max(policy.file_bytes_limit, stamp[0]),
        expanded_bytes_limit=max(policy.expanded_bytes_limit, stamp[0]),
    )
    _budget(target)
    copied = inputs._write_stream(target, inputs._file_chunks(path, deadline), policy, deadline, 0)
    if copied != stamp:
        _fail("InputChanged")


def _copy_snapshot(
    snapshot_root: Path, target: Path, snapshot: Any, deadline: inputs._Deadline
) -> None:
    _mkdir(target)
    _mkdir(target / "source")
    for item in snapshot["entries"]:
        deadline.check()
        destination = target / "source" / item["path"]
        if item["kind"] == "directory":
            _mkdir(destination)
        else:
            _copy(
                snapshot_root / "source" / item["path"],
                destination,
                (item["bytes"], item["sha256"]),
                deadline,
            )
    raw = inputs._canonical_json_bytes(snapshot)
    _write(target / "manifest.json", raw, deadline)
    _write(target / "SEALED", inputs._sha256_bytes(raw).encode("ascii"), deadline)
    inputs.read_snapshot(snapshot_root=target)


def _failure_label(staging: Path, code: str) -> None:
    with suppress(OSError, TaskInputError, BridgePathError):
        inputs._assert_plain_target(staging, label="failed workspace")
        label = staging / "WORKSPACE-FAILED"
        inputs._assert_plain_target(label, label="workspace failure label")
        with label.open("xb") as handle:
            handle.write(code.encode("ascii"))


# Keep this local alias solely for exception boundaries around reused A helpers.
TaskInputError = inputs.TaskInputError


def _map_error(error: Exception) -> TaskWorkspaceError:
    if isinstance(error, TaskInputError):
        return TaskWorkspaceError(error.code, "a frozen input or path check failed")
    if isinstance(error, BridgeContractError):
        return TaskWorkspaceError("InvalidJson", "a strict contract JSON check failed")
    if isinstance(error, BridgePathError):
        return TaskWorkspaceError("PathRejected", "a workspace path crossed its boundary")
    return TaskWorkspaceError("IoFailed", "a workspace file operation failed")


def prepare_task(
    *,
    snapshot_root: Path,
    task_manifest: dict[str, object],
    task_note: bytes,
    deployment_profile: dict[str, object],
    authorization: dict[str, object],
    task_root: Path,
) -> dict[str, object]:
    """Freeze control records and create an independent role source copy."""
    try:
        return _prepare(
            snapshot_root, task_manifest, task_note, deployment_profile, authorization, task_root
        )
    except TaskWorkspaceError:
        raise
    except (TaskInputError, BridgeContractError, BridgePathError, OSError) as error:
        raise _map_error(error) from error


def _prepare(
    snapshot_root: Path, task: Any, note: bytes, profile: Any, auth: Any, root: Path
) -> Any:
    _task_shape(task)
    deadline = inputs._Deadline.starting_now(task["deadline_seconds"])
    _root(root, fresh=True)
    staging = root.with_name(root.name + ".staging")
    _root(staging, fresh=True)
    _separate(snapshot_root, root, staging)
    snapshot = inputs.read_snapshot(snapshot_root=snapshot_root)
    _validate_binding(task, profile, auth, note, snapshot)
    if sum(item["bytes"] for item in snapshot["entries"]) > task["source_output_bytes_limit"]:
        _fail("ResourceLimitExceeded")
    try:
        _mkdir(staging)
        for name in ("control", "work", "out", "scratch"):
            _mkdir(staging / name)
        _copy_snapshot(snapshot_root, staging / "control" / "snapshot", snapshot, deadline)
        for item in snapshot["entries"]:
            target = staging / "work" / item["path"]
            if item["kind"] == "directory":
                _mkdir(target)
            else:
                _copy(
                    snapshot_root / "source" / item["path"],
                    target,
                    (item["bytes"], item["sha256"]),
                    deadline,
                )
        _write(staging / "control" / "TASK.md", note, deadline)
        _write(
            staging / "control" / "deployment-profile.json",
            inputs._canonical_json_bytes(profile),
            deadline,
        )
        _write(
            staging / "control" / "authorization.json", inputs._canonical_json_bytes(auth), deadline
        )
        raw = inputs._canonical_json_bytes(task)
        _write(staging / "task.json", raw, deadline)
        files, directories, _ = inputs._validate_snapshot_manifest(snapshot)
        inputs._verify_tree_against_manifest(staging / "work", files, directories)
        _verify_fixed_input_controls(staging, task, profile, auth, require_seal=False)
        _write(staging / "SEALED", inputs._sha256_bytes(raw).encode("ascii"), deadline)
        inputs.read_snapshot(snapshot_root=snapshot_root)
        inputs._assert_plain_target(staging, label="workspace staging")
        inputs._assert_plain_target(root, label="workspace final root")
        deadline.check()
        os.rename(staging, root)
        return decode_strict_json_bytes(raw, label="task manifest")
    except BaseException as error:
        _failure_label(staging, getattr(error, "code", "IoFailed"))
        raise


def _read(path: Path) -> bytes:
    inputs._assert_plain_target(path, label="contract file")
    information = path.lstat()
    if information.st_nlink > 1 or not path.is_file():
        _fail("PathRejected")
    return path.read_bytes()


def _json(path: Path, *, canonical: bool = False) -> Any:
    raw = _read(path)
    value = decode_strict_json_bytes(raw, label="workspace contract")
    if canonical and raw != inputs._canonical_json_bytes(value):
        _fail("ManifestNotCanonical")
    return value


def _inventory(
    root: Path, limit: int, deadline: inputs._Deadline
) -> tuple[dict[str, tuple[int, str]], set[str]]:
    inputs._assert_plain_target(root, label="workspace inventory")
    if not root.is_dir():
        _fail("ScopeRejected")
    policy = replace(inputs._default_verification_policy(), file_bytes_limit=limit)
    files, directories = inputs._scan_tree(root, policy, deadline)
    inputs._check_collection_conflicts(files, directories, deadline)
    if len(files) + len(directories) > policy.entry_count_limit:
        _fail("ResourceLimitExceeded")
    if sum(size for size, _ in files.values()) > limit:
        _fail("ResourceLimitExceeded")
    for relative in (*files, *directories):
        _budget(root / relative)
    return files, directories


def _verify_fixed_input_controls(
    root: Path, task: Any, profile: Any, auth: Any, *, require_seal: bool
) -> None:
    _root(root, fresh=False)
    _task_shape(task)
    _profile_shape(profile)
    _authorization_shape(auth)
    fixed_documents = {}
    for relative, expected in (
        ("task.json", task),
        ("control/deployment-profile.json", profile),
        ("control/authorization.json", auth),
    ):
        frozen_raw = inputs._canonical_json_bytes(expected)
        if inputs._canonical_json_bytes(_json(root / relative, canonical=True)) != frozen_raw:
            _fail("InputControlConflict")
        fixed_documents[relative] = frozen_raw
    if require_seal and (
        _read(root / "SEALED")
        != inputs._sha256_bytes(inputs._canonical_json_bytes(task)).encode("ascii")
        or os.path.lexists(root / "WORKSPACE-FAILED")
    ):
        _fail("TaskBindingMismatch")
    snapshot = inputs.read_snapshot(snapshot_root=root / "control" / "snapshot")
    _validate_binding(task, profile, auth, _read(root / "control" / "TASK.md"), snapshot)
    deadline = inputs._Deadline.starting_now(task["deadline_seconds"])
    files, directories = _inventory(root / "work", task["source_output_bytes_limit"], deadline)
    _validate_input_controls(task, auth, snapshot, files, directories)
    for relative, frozen_raw in fixed_documents.items():
        if _read(root / relative) != frozen_raw:
            _fail("InputControlConflict")
    if require_seal and _read(root / "SEALED") != inputs._sha256_bytes(
        inputs._canonical_json_bytes(task)
    ).encode("ascii"):
        _fail("TaskBindingMismatch")


def verify_input_controls(
    *,
    task_root: Path,
    task_manifest: dict[str, object],
    deployment_profile: dict[str, object],
    authorization: dict[str, object],
) -> None:
    """Read fixed Host copies and current rules; this does not grant execution authority."""
    try:
        _verify_fixed_input_controls(
            task_root, task_manifest, deployment_profile, authorization, require_seal=True
        )
    except TaskWorkspaceError:
        raise
    except (TaskInputError, BridgeContractError, BridgePathError, OSError) as error:
        raise _map_error(error) from error


def _stamp(stamp: tuple[int, str] | None) -> dict[str, Any] | None:
    return None if stamp is None else {"bytes": stamp[0], "sha256": stamp[1]}


def _changes(
    before: dict[str, tuple[int, str]], after: dict[str, tuple[int, str]]
) -> list[dict[str, Any]]:
    changes = []
    for path in sorted(before.keys() | after.keys(), key=inputs._path_key):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        kind = "added" if old is None else "deleted" if new is None else "modified"
        changes.append(
            {
                "path": path,
                "kind": kind,
                "before": _stamp(old),
                "after": _stamp(new),
                "rename_from": None,
            }
        )
    deleted = [item for item in changes if item["kind"] == "deleted"]
    added = [item for item in changes if item["kind"] == "added"]
    old_counts = Counter((item["before"]["bytes"], item["before"]["sha256"]) for item in deleted)
    new_counts = Counter((item["after"]["bytes"], item["after"]["sha256"]) for item in added)
    old_paths = {
        (item["before"]["bytes"], item["before"]["sha256"]): item["path"] for item in deleted
    }
    for item in added:
        identity = (item["after"]["bytes"], item["after"]["sha256"])
        if old_counts[identity] == new_counts[identity] == 1:
            item["rename_from"] = old_paths[identity]
    return changes


def _tree_sha(files: dict[str, tuple[int, str]], directories: set[str]) -> str:
    entries = [
        {"path": path, "kind": "directory", "bytes": 0, "sha256": None} for path in directories
    ]
    entries.extend({"path": path, "kind": "file", **_stamp(stamp)} for path, stamp in files.items())
    entries.sort(key=lambda item: inputs._path_key(item["path"]))
    return inputs._sha256_bytes(
        inputs._canonical_json_bytes({"contract_version": 1, "entries": entries})
    )


def _generated_work_roots(
    directories: set[str], baseline: dict[str, tuple[int, str]], baseline_dirs: set[str]
) -> list[str]:
    """Separate newly generated caches, preserving any frozen source at that name.

    A generic build directory is only an observation: it may contain newly
    authored source, so its contents must never be silently excluded.
    """
    return sorted(
        (
            path
            for path in directories
            if inputs._path_identity_key(path.rsplit("/", 1)[-1]) in _GENERATED_CACHE_NAMES
            and not any(inputs._scope_covers(path, old) for old in baseline.keys() | baseline_dirs)
        ),
        key=inputs._path_key,
    )


def _worker_identity(value: Any, keys: set[str], task: Any, *, snapshot: bool) -> None:
    _object(value, keys)
    _version(value)
    if value["task_id"] != task["task_id"] or (
        snapshot and value["snapshot_id"] != task["snapshot_id"]
    ):
        _fail("WorkerIdentityMismatch")


def _progress(root: Path, task: Any, blockers: list[str]) -> Any:
    try:
        value = _json(root / "out" / "progress.json")
        _worker_identity(
            value,
            {"contract_version", "task_id", "status", "summary", "remaining_paths"},
            task,
            snapshot=False,
        )
        _enum(value["status"], {"Completed", "Partial", "Blocked"})
        _text(value["summary"])
        _paths(value["remaining_paths"])
        if value["status"] == "Completed" and value["remaining_paths"]:
            blockers.append("ProgressIncomplete")
        return value
    except (TaskWorkspaceError, TaskInputError, BridgeContractError, OSError, BridgePathError):
        blockers.append("ProgressInvalid")
        return None


def _review(
    root: Path, task: Any, snapshot: Any, baseline: dict[str, tuple[int, str]], blockers: list[str]
) -> tuple[str, set[str]]:
    expected = {entry["path"] for entry in snapshot["entries"]}
    expected.update(item["path"] for item in snapshot["excluded_paths"])
    source_paths = set(snapshot["source_paths"])
    try:
        coverage = _json(root / "out" / "coverage.json")
        _worker_identity(
            coverage,
            {
                "contract_version",
                "task_id",
                "snapshot_id",
                "entries",
                "package_entry_count",
                "source_file_count",
            },
            task,
            snapshot=True,
        )
        _integer(coverage["package_entry_count"])
        _integer(coverage["source_file_count"])
        if coverage["package_entry_count"] != len(expected) or coverage["source_file_count"] != len(
            source_paths
        ):
            _fail("CoverageDenominatorMismatch")
        if type(coverage["entries"]) is not list:
            _fail()
        states = {}
        for item in coverage["entries"]:
            _object(item, {"path", "state", "reason"})
            path = _path(item["path"])
            _enum(item["state"], {"Analyzed", "Excluded", "Failed", "NotAnalyzed"})
            _text(item["reason"])
            if path not in expected or path in states:
                _fail("CoveragePathMismatch")
            states[path] = item["state"]
        if set(states) != expected:
            _fail("CoveragePathMismatch")
        findings = _json(root / "out" / "findings.json")
        _worker_identity(
            findings,
            {"contract_version", "task_id", "snapshot_id", "findings"},
            task,
            snapshot=True,
        )
        if type(findings["findings"]) is not list:
            _fail()
        ids = set()
        for finding in findings["findings"]:
            _object(finding, {"id", "severity", "file", "line", "evidence", "recommendation"})
            _text(finding["id"])
            _enum(finding["severity"], {"P0", "P1", "P2", "P3"})
            _path(finding["file"])
            _integer(finding["line"], 1)
            _text(finding["evidence"])
            _text(finding["recommendation"])
            if finding["id"] in ids or finding["file"] not in baseline:
                _fail("FindingLocationInvalid")
            ids.add(finding["id"])
            raw = _read(root / "control" / "snapshot" / "source" / finding["file"])
            try:
                lines = raw.decode("utf-8-sig").splitlines()
            except UnicodeDecodeError:
                blockers.append("FindingLocationUnverified")
                continue
            if finding["line"] > len(lines):
                _fail("FindingLocationInvalid")
        # Review outputs are UTF-8; the source bytes remain arbitrary.
        _read(root / "out" / "report.md").decode("utf-8", errors="strict")
        remaining = {path for path, state in states.items() if state in {"Failed", "NotAnalyzed"}}
        remaining.update(path for path in source_paths if states[path] != "Analyzed")
        if remaining:
            blockers.append("CoverageIncomplete")
            return "Incomplete", remaining
        return "Complete", set()
    except (
        TaskWorkspaceError,
        TaskInputError,
        BridgeContractError,
        OSError,
        UnicodeError,
        BridgePathError,
    ) as error:
        blockers.append(getattr(error, "code", "ReviewJsonOrEncodingInvalid"))
        blockers.append("ReviewOutputsInvalid")
        return "Invalid", set(snapshot["source_paths"])


def _tests(value: Any) -> None:
    if type(value) is not list:
        _fail("RunReceiptInvalid")
    ids = set()
    for item in value:
        _object(item, _TEST_KEYS)
        for name in ("test_run_id", "recipe_id"):
            _text(item[name])
        if item["test_run_id"] in ids:
            _fail("RunReceiptInvalid")
        ids.add(item["test_run_id"])
        _enum(item["phase"], {"reproduce", "regression", "build"})
        for name in ("toolchain_sha256", "source_tree_sha256"):
            _hash(item[name], nullable=True)
        if item["exit_code"] is not None and type(item["exit_code"]) is not int:
            _fail("RunReceiptInvalid")
        for name in ("start_utc", "end_utc"):
            _text(item[name], nullable=True)
        _evidence(item["evidence_refs"])
        _enum(item["origin"], {"WorkerReported", "HostObserved"})


def _plan(value: Any, task: Any, task_sha: str) -> None:
    from .layered_acceptance import CAPABILITIES, METHOD

    if (
        type(value) is dict
        and type(value.get("contract_version")) is int
        and value["contract_version"] == 2
    ):
        _object(value, _PLAN_KEYS | {"acceptance_method"})
        if value["acceptance_method"] != METHOD or value["host"] != "agy":
            _fail("PlanBindingMismatch")
        if value["preflight_status"] == "Ready" and (
            task["role"] != "Coding"
            or task["capabilities"] != CAPABILITIES
            or task["execution_boundary"] != "declared_scope"
        ):
            _fail("PlanBindingMismatch")
    else:
        _object(value, _PLAN_KEYS)
        _version(value)
    if value["task_id"] != task["task_id"] or value["task_manifest_sha256"] != task_sha:
        _fail("PlanBindingMismatch")
    _hash(value["deployment_receipt_sha256"])
    _enum(value["host"], {"agy", "cursor"})
    _object(value["route"], {"model", "effort"})
    _text(value["route"]["model"])
    _text(value["route"]["effort"], nullable=True)
    _enum(value["execution_boundary"], _MODES)
    _capabilities(value["capabilities"])
    if (
        value["execution_boundary"] != task["execution_boundary"]
        or value["capabilities"] != task["capabilities"]
    ):
        _fail("PlanBindingMismatch")
    _enum(value["preflight_status"], {"Ready", "Blocked"})
    _strings(value["blockers"])
    _evidence(value["evidence_refs"])


def _run_receipt(
    root: Path,
    run_root: Path | None,
    task: Any,
    task_sha: str,
    blockers: list[str],
    *,
    first_execution: dict | None = None,
) -> tuple[Any, str | None]:
    if run_root is None:
        return None, None
    try:
        _root(run_root, fresh=False)
        plan = _json(root / "control" / "plan.json", canonical=True)
        _plan(plan, task, task_sha)
        profile = _json(root / "control" / "deployment-profile.json", canonical=True)
        if (
            inputs._sha256_bytes(inputs._canonical_json_bytes(profile))
            != task["deployment_profile_sha256"]
        ):
            _fail("PlanBindingMismatch")
        if (
            plan["host"] != profile["host"]
            or plan["deployment_receipt_sha256"] != profile["receipt_sha256"]
        ):
            _fail("PlanBindingMismatch")
        plan_sha = inputs._sha256_bytes(inputs._canonical_json_bytes(plan))
        value = _json(run_root / "run.json", canonical=True)
        _object(value, _RUN_KEYS)
        _version(value)
        if value["task_id"] != task["task_id"] or value["plan_sha256"] != plan_sha:
            _fail("RunBindingMismatch")
        _enum(value["transport_state"], {"NotRun", "Completed", "Failed", "TimedOut"})
        launch_count = value["launch_count"]
        if launch_count is not None:
            _integer(launch_count, 0, 1)
        _text(value["capture_uid"], nullable=True)
        _enum(value["capture_state"], {"NotRun", "Sealed", "Incomplete"})
        _enum(value["restore_state"], {"NotRun", "Unchanged", "Restored", "Failed"})
        _tests(value["test_observations"])
        _evidence(value["evidence_refs"])
        _strings(value["blockers"])
        if launch_count is None and (
            value["transport_state"] != "Failed" or "LaunchUnverified" not in value["blockers"]
        ):
            _fail("RunReceiptInvalid")
        if value["transport_state"] == "NotRun":
            if (
                value["launch_count"] != 0
                or value["capture_state"] != "NotRun"
                or value["restore_state"] != "NotRun"
                or value["capture_uid"] is not None
                or value["test_observations"]
            ):
                _fail("RunReceiptInvalid")
        elif value["transport_state"] == "Completed" and value["launch_count"] != 1:
            _fail("RunReceiptInvalid")
        if value["capture_state"] == "Sealed" and value["capture_uid"] is None:
            _fail("RunReceiptInvalid")
        if first_execution is not None:
            from . import task_run

            try:
                task_run._verify_first_execution(first_execution, root, task, plan, run_root)
            except task_run.TaskRunError as error:
                _fail(error.code)
            if not any(
                item["ref"] == "first-execution.json"
                and item["origin"] == "HostObserved"
                and item["sha256"] == first_execution["sha256"]
                for item in value["evidence_refs"]
            ):
                _fail("FirstExecutionBindingMismatch")
        elif plan["preflight_status"] == "Blocked" and launch_count != 0:
            _fail("RunReceiptInvalid")
        receipt_path = root / "control" / "deployment-receipt.json"
        if receipt_path.exists():
            receipt = _json(receipt_path, canonical=True)
            if type(receipt) is dict and receipt.get("contract_version") == 6:
                from . import agy_host

                if (
                    inputs._sha256_bytes(inputs._canonical_json_bytes(receipt))
                    != profile["receipt_sha256"]
                ):
                    _fail("PlanBindingMismatch")
                try:
                    observation = agy_host.read_observation(
                        value, run_root, receipt["host_entry"]["path"]
                    )
                except (agy_host.AgyHostError, KeyError, TypeError) as error:
                    raise TaskWorkspaceError(
                        "AgyHostObservationInvalid", "host observation invalid"
                    ) from error
                if observation is not None and observation["compatibility"]["state"] != "Supported":
                    blockers.append(observation["compatibility"]["reason"] or "AgyHostUnverified")
        blockers.extend(value["blockers"])
        if value["transport_state"] in {"Failed", "TimedOut"}:
            blockers.append("Transport" + value["transport_state"])
        if value["restore_state"] == "Failed":
            blockers.append("RestoreFailed")
        if value["capture_state"] == "Incomplete":
            blockers.append("CaptureIncomplete")
        if value["transport_state"] == "Completed":
            if value["capture_state"] != "Sealed":
                blockers.append("CaptureNotSealed")
            if value["restore_state"] not in {"Unchanged", "Restored"}:
                blockers.append("RestoreUnverified")
        return value, plan_sha
    except (
        TaskWorkspaceError,
        TaskInputError,
        BridgeContractError,
        OSError,
        BridgePathError,
    ) as error:
        blockers.append(getattr(error, "code", "RunJsonOrIoInvalid"))
        blockers.append("RunReceiptInvalid")
        return None, None


def _parent_directories(root: Path, relative: str) -> None:
    current = root
    for component in relative.split("/")[:-1]:
        current /= component
        inputs._assert_plain_target(current, label="artifact parent")
        if not current.exists():
            _mkdir(current)
        elif not current.is_dir():
            _fail("ScopeRejected")


def _artifact(path: str, stamp: tuple[int, str], origin: str) -> dict[str, Any]:
    return {"path": path, "bytes": stamp[0], "sha256": stamp[1], "origin": origin}


def _host_artifact(
    root: Path, path: str, raw: bytes, artifacts: list[Any], deadline: inputs._Deadline
) -> None:
    _parent_directories(root, path)
    _write(root / path, raw, deadline)
    artifacts.append(_artifact(path, (len(raw), inputs._sha256_bytes(raw)), "HostValidation"))


def _verify_test_evidence(
    tests: list[Any],
    task_files: dict[str, tuple[int, str]],
    run_files: dict[str, tuple[int, str]],
    blockers: list[str],
    invalid_refs: set[str],
) -> set[str]:
    verified = set()
    for observation in tests:
        complete = observation["origin"] == "HostObserved" and all(
            observation[name] is not None
            for name in (
                "toolchain_sha256",
                "source_tree_sha256",
                "exit_code",
                "start_utc",
                "end_utc",
            )
        )
        refs = observation["evidence_refs"]
        complete &= bool(refs)
        for evidence in refs:
            try:
                ref = _path(evidence["ref"])
            except (TaskWorkspaceError, TaskInputError):
                complete = False
                continue
            matches = [files[ref] for files in (task_files, run_files) if ref in files]
            complete &= (
                evidence["origin"] == "HostObserved"
                and evidence["sha256"] is not None
                and len(matches) == 1
                and matches[0][1] == evidence["sha256"]
                and ref not in invalid_refs
            )
        if not complete:
            blockers.append("TestEvidenceUnverified")
        else:
            verified.add(observation["test_run_id"])
    return verified


def _receipt_files(
    run_root: Path,
    receipt: Any,
    task_files: dict[str, tuple[int, str]],
    limit: int,
    deadline: inputs._Deadline,
    blockers: list[str],
) -> tuple[dict[str, tuple[int, str]], list[dict[str, Any]], set[str]]:
    """Read only C's receipt and declared Host evidence, never its other files."""
    refs = list(receipt["evidence_refs"])
    refs.extend(
        evidence
        for observation in receipt["test_observations"]
        for evidence in observation["evidence_refs"]
    )
    paths = {"run.json"}
    for evidence in refs:
        if evidence["origin"] != "HostObserved" or evidence["sha256"] is None:
            continue
        try:
            path = _path(evidence["ref"])
        except (TaskWorkspaceError, TaskInputError):
            continue  # Opaque encrypted session references are not file paths.
        if path not in task_files:
            paths.add(path)
    files = {}
    total = 0
    for relative in sorted(paths, key=inputs._path_key):
        deadline.check()
        try:
            path = run_root / relative
            inputs._assert_plain_target(path, label="run evidence")
            information = path.lstat()
            if not path.is_file() or information.st_nlink > 1:
                _fail("PathRejected")
            total += information.st_size
            if total > limit:
                _fail("ResourceLimitExceeded")
            files[relative] = (information.st_size, inputs._hash_file(path, deadline))
        except (TaskWorkspaceError, TaskInputError, OSError, BridgePathError):
            blockers.append("RunEvidenceInvalid")
    checks = []
    invalid_refs = set()
    # Read each path once, but compare every declaration, including duplicate refs.
    for evidence in receipt["evidence_refs"]:
        ref = evidence["ref"]
        actual = None
        state = "Unverified"
        if evidence["origin"] == "HostObserved" and evidence["sha256"] is not None:
            try:
                _path(ref)
            except (TaskWorkspaceError, TaskInputError):
                pass  # An opaque reference does not identify readable file evidence.
            else:
                stamp = task_files.get(ref) if ref in task_files else files.get(ref)
                if stamp is None:
                    state = "Invalid"
                    invalid_refs.add(ref)
                    blockers.append("RunEvidenceInvalid")
                else:
                    actual = stamp[1]
                    state = "Match" if actual == evidence["sha256"] else "Mismatch"
                    if state == "Mismatch":
                        invalid_refs.add(ref)
                        blockers.append("RunEvidenceDigestMismatch")
        checks.append(
            {
                "ref": ref,
                "declared_sha256": evidence["sha256"],
                "actual_sha256": actual,
                "origin": evidence["origin"],
                "check": state,
            }
        )
    return files, checks, invalid_refs


def _control_observations(
    root: Path, task: Any, blockers: list[str]
) -> tuple[bool, dict[str, tuple[int, str]]]:
    """Bind C/D fixed additions to the profile frozen by prepare.

    C owns DeploymentReceipt schema and actual authorization/R validation.
    B checks its canonical digest and only the Cursor raw configuration digest
    named by approved proposal section 4; it does not create a grant.
    """
    valid = True
    files: dict[str, tuple[int, str]] = {}
    try:
        profile = _json(root / "control" / "deployment-profile.json", canonical=True)
        _profile_shape(profile)
        if (
            inputs._sha256_bytes(inputs._canonical_json_bytes(profile))
            != task["deployment_profile_sha256"]
        ):
            _fail("ControlChanged")
        receipt_path = root / "control" / "deployment-receipt.json"
        receipt = None
        receipt_present = os.path.lexists(receipt_path)
        if receipt_present:
            receipt = _json(receipt_path, canonical=True)
            raw = inputs._canonical_json_bytes(receipt)
            if inputs._sha256_bytes(raw) != profile["receipt_sha256"]:
                _fail("ControlChanged")
            files["control/deployment-receipt.json"] = (len(raw), inputs._sha256_bytes(raw))
        plan_path = root / "control" / "plan.json"
        plan_present = os.path.lexists(plan_path)
        # Pure prepare has neither record; a plan publication requires both.
        if receipt_present != plan_present or (plan_present and receipt is None):
            _fail("ControlChanged")
        if plan_present:
            plan = _json(plan_path, canonical=True)
            _plan(plan, task, inputs._sha256_bytes(inputs._canonical_json_bytes(task)))
            from .layered_acceptance import METHOD

            layered_receipt = (
                type(receipt.get("contract_version")) is int and receipt["contract_version"] == 3
            )
            if (plan["contract_version"] == 2) != layered_receipt or (
                layered_receipt and receipt.get("acceptance_method") != METHOD
            ):
                _fail("PlanBindingMismatch")
            if (
                plan["host"] != profile["host"]
                or plan["deployment_receipt_sha256"] != profile["receipt_sha256"]
            ):
                _fail("ControlChanged")
            raw = inputs._canonical_json_bytes(plan)
            files["control/plan.json"] = (len(raw), inputs._sha256_bytes(raw))
        cursor_root = root / ".cursor"
        if profile["host"] == "cursor" and receipt is not None and not os.path.lexists(cursor_root):
            _fail("ControlChanged")
        if os.path.lexists(cursor_root):
            if profile["host"] != "cursor" or receipt is None:
                _fail("ControlChanged")
            inputs._assert_plain_target(cursor_root, label="Cursor Host control")
            if {path.name for path in cursor_root.iterdir()} != {"cli.json"}:
                _fail("ControlChanged")
            if not _under(".cursor/cli.json", task["protected_paths"]):
                _fail("ControlChanged")
            # This exact digest location is explicitly frozen by proposal §4.
            try:
                expected = receipt["configuration"]["cursor_project"]["sha256"]
            except (KeyError, TypeError) as error:
                raise TaskWorkspaceError(
                    "ControlChanged", "the Cursor Host binding is missing"
                ) from error
            _hash(expected)
            raw = _read(cursor_root / "cli.json")
            if inputs._sha256_bytes(raw) != expected:
                _fail("ControlChanged")
            files[".cursor/cli.json"] = (len(raw), expected)
    except (TaskWorkspaceError, TaskInputError, BridgeContractError, OSError, BridgePathError):
        blockers.append("ControlChanged")
        valid = False
    return valid, files


def collect_task(
    *,
    task_root: Path,
    run_root: Path | None,
    result_root: Path,
    first_execution: dict | None = None,
) -> dict[str, object]:
    """Collect safe byte artifacts and observations without a business verdict."""
    try:
        return _collect(task_root, run_root, result_root, first_execution=first_execution)
    except TaskWorkspaceError:
        raise
    except (TaskInputError, BridgeContractError, BridgePathError, OSError) as error:
        raise _map_error(error) from error


def _collect(
    root: Path, run_root: Path | None, result_root: Path, *, first_execution: dict | None = None
) -> Any:
    if first_execution is not None and run_root is None:
        _fail("FirstExecutionBindingMismatch")
    _root(root, fresh=False)
    _root(result_root, fresh=True)
    staging = result_root.with_name(result_root.name + ".staging")
    _root(staging, fresh=True)
    if run_root is not None:
        _root(run_root, fresh=False)
    _separate(root, result_root, staging, *([] if run_root is None else [run_root]))
    _mkdir(staging)
    try:
        raw = _read(root / "task.json")
        task = decode_strict_json_bytes(raw, label="task manifest")
        _task_shape(task)
        task_sha = inputs._sha256_bytes(raw)
        if raw != inputs._canonical_json_bytes(task) or _read(root / "SEALED") != task_sha.encode(
            "ascii"
        ):
            _fail("TaskBindingMismatch")
        if os.path.lexists(root / "WORKSPACE-FAILED"):
            _fail("TaskBindingMismatch")
        deadline = inputs._Deadline.starting_now(task["deadline_seconds"])
        snapshot = inputs.read_snapshot(snapshot_root=root / "control" / "snapshot")
        if (
            snapshot["snapshot_id"] != task["snapshot_id"]
            or inputs._sha256_bytes(inputs._canonical_json_bytes(snapshot))
            != task["snapshot_manifest_sha256"]
        ):
            _fail("SnapshotBindingMismatch")
        baseline, baseline_dirs, _ = inputs._validate_snapshot_manifest(snapshot)
        limit = task["source_output_bytes_limit"]
        blockers: list[str] = []
        scope = "Pass"
        unavailable: set[str] = set()
        inventories: dict[str, tuple[dict[str, tuple[int, str]], set[str]]] = {}
        for name in ("work", "out", "scratch"):
            try:
                inventories[name] = _inventory(root / name, limit, deadline)
            except (TaskWorkspaceError, TaskInputError, BridgePathError, OSError) as error:
                scope = "Fail"
                blockers.append(getattr(error, "code", "IoFailed"))
                # No unsafe traversal or automatic correction. The original
                # tree remains the authoritative failed candidate at task_root.
                inventories[name] = ({}, set())
                unavailable.add(name)
        work, work_dirs = inventories["work"]
        out, _ = inventories["out"]
        exceeds_limit = (
            sum(stamp[0] for inventory, _ in inventories.values() for stamp in inventory.values())
            > limit
        )
        if exceeds_limit:
            scope = "Fail"
            blockers.append("ResourceLimitExceeded")
        changes = [] if "work" in unavailable else _changes(baseline, work)
        for change in changes:
            path = "work/" + change["path"]
            if (
                task["role"] == "Review"
                or not _under(path, task["write_roots"])
                or _under(path, task["protected_paths"])
            ):
                scope = "Fail"
                blockers.append("SourceScopeChanged")
        for path in set() if "work" in unavailable else baseline_dirs ^ work_dirs:
            logical = "work/" + path
            if (
                task["role"] == "Review"
                or not _under(logical, task["write_roots"])
                or _under(logical, task["protected_paths"])
            ):
                scope = "Fail"
                blockers.append("DirectoryScopeChanged")
        for name in ("out", "scratch"):
            files, directories = inventories[name]
            for relative in (*files, *directories):
                logical = name + "/" + relative
                if not _under(logical, task["write_roots"]) or _under(
                    logical, task["protected_paths"]
                ):
                    scope = "Fail"
                    blockers.append("OutputScopeChanged")
        frozen = {
            "control/TASK.md": task["instructions_sha256"],
            "control/deployment-profile.json": task["deployment_profile_sha256"],
            "control/authorization.json": task["authorization_sha256"],
        }
        observed_controls: dict[str, bytes] = {}
        for path, digest in frozen.items():
            try:
                contents = _read(root / path)
                observed_controls[path] = contents
                if inputs._sha256_bytes(contents) != digest:
                    _fail("ControlChanged")
            except (TaskWorkspaceError, TaskInputError, OSError, BridgePathError):
                scope = "Fail"
                blockers.append("ControlChanged")
        # The only additional control member is C's fixed plan; its binding
        # is checked separately. Unknown task/control entries are scope drift.
        for path in root.iterdir():
            if path.name not in {*_ROOTS, "task.json", "SEALED", ".cursor"}:
                scope = "Fail"
                blockers.append("TaskScopeChanged")
        for path in (root / "control").iterdir():
            if path.name not in {
                "TASK.md",
                "deployment-profile.json",
                "authorization.json",
                "snapshot",
                "plan.json",
                "deployment-receipt.json",
            }:
                scope = "Fail"
                blockers.append("ControlChanged")
        controls_valid, control_files = _control_observations(root, task, blockers)
        if not controls_valid:
            scope = "Fail"
        try:
            verify_input_controls(
                task_root=root,
                task_manifest=task,
                deployment_profile=_json(
                    root / "control" / "deployment-profile.json", canonical=True
                ),
                authorization=_json(root / "control" / "authorization.json", canonical=True),
            )
        except (TaskWorkspaceError, TaskInputError, BridgeContractError, OSError, BridgePathError):
            scope = "Fail"
            blockers.append("InputControlConflict")
        outputs = "Pass"
        for path in task["required_outputs"]:
            if path.removeprefix("out/") not in out:
                outputs = "Fail"
                blockers.append("RequiredOutputMissing")
        progress = _progress(root, task, blockers) if "progress.json" in out else None
        if progress is None or "ProgressIncomplete" in blockers:
            outputs = "Fail"
        coverage = "NotRequired"
        coverage_remaining: set[str] = set()
        if task["role"] == "Review":
            coverage, coverage_remaining = (
                _review(root, task, snapshot, baseline, blockers)
                if all(path in out for path in ("report.md", "coverage.json", "findings.json"))
                else ("Invalid", set(snapshot["source_paths"]))
            )
            if coverage == "Invalid":
                outputs = "Fail"
                blockers.append("ReviewOutputsInvalid")
        receipt, plan_sha = _run_receipt(
            root, run_root, task, task_sha, blockers, first_execution=first_execution
        )
        transport = (
            "NotRun"
            if run_root is None
            else "Failed"
            if receipt is None
            else receipt["transport_state"]
        )
        tests = [] if receipt is None else receipt["test_observations"]
        task_files = {
            name + "/" + path: stamp
            for name, (files, _) in inventories.items()
            for path, stamp in files.items()
        }
        run_files: dict[str, tuple[int, str]] = {}
        evidence_checks: list[dict[str, Any]] = []
        invalid_refs: set[str] = set()
        if run_root is not None and receipt is not None:
            run_files, evidence_checks, invalid_refs = _receipt_files(
                run_root, receipt, task_files, limit, deadline, blockers
            )
        verified_tests = _verify_test_evidence(tests, task_files, run_files, blockers, invalid_refs)
        generated_work_roots = _generated_work_roots(work_dirs, baseline, baseline_dirs)
        candidate_work = {
            path: stamp for path, stamp in work.items() if not _under(path, generated_work_roots)
        }
        candidate_dirs = {path for path in work_dirs if not _under(path, generated_work_roots)}
        changes = [] if "work" in unavailable else _changes(baseline, candidate_work)
        artifacts: list[Any] = []
        for name, (files, directories) in inventories.items():
            if exceeds_limit:
                continue
            prefix = "candidate" if name == "work" else name
            _mkdir(staging / prefix)
            for directory in sorted(
                directories, key=lambda item: (item.count("/"), inputs._path_key(item))
            ):
                relative = prefix + "/" + directory
                if name == "work" and _under(directory, generated_work_roots):
                    relative = "generated/work/" + directory
                _parent_directories(staging, relative + "/placeholder")
            for path, stamp in sorted(files.items(), key=lambda item: inputs._path_key(item[0])):
                relative = prefix + "/" + path
                generated_file = name == "work" and _under(path, generated_work_roots)
                if generated_file:
                    relative = "generated/work/" + path
                _parent_directories(staging, relative)
                _copy(root / name / path, staging / relative, stamp, deadline)
                origin = (
                    "CandidateTree" if name == "work" and not generated_file else "WorkerOutput"
                )
                artifacts.append(_artifact(relative, stamp, origin))
        for path, stamp in sorted(run_files.items(), key=lambda item: inputs._path_key(item[0])):
            relative = (
                "validation/current-run-evidence/" + path
                if path in invalid_refs and path != "run.json"
                else "run/" + path
            )
            _parent_directories(staging, relative)
            _copy(run_root / path, staging / relative, stamp, deadline)
            artifacts.append(_artifact(relative, stamp, "HostValidation"))
        for path in sorted(invalid_refs & task_files.keys(), key=inputs._path_key):
            relative = "validation/current-run-evidence/" + path
            _parent_directories(staging, relative)
            _copy(root / path, staging / relative, task_files[path], deadline)
            artifacts.append(_artifact(relative, task_files[path], "HostValidation"))
        if receipt is not None:
            check_raw = inputs._canonical_json_bytes(evidence_checks)
            if len(check_raw) > limit:
                _fail("ResourceLimitExceeded")
            _host_artifact(
                staging, "validation/run-evidence-checks.txt", check_raw, artifacts, deadline
            )
        for path, stamp in sorted(
            control_files.items(), key=lambda item: inputs._path_key(item[0])
        ):
            relative = "host/" + path
            _parent_directories(staging, relative)
            _copy(root / path, staging / relative, stamp, deadline)
            artifacts.append(_artifact(relative, stamp, "HostValidation"))
        generated = []
        for name, (files, _) in inventories.items():
            roots = {
                "/".join(path.split("/")[: index + 1])
                for path in files
                for index, part in enumerate(path.split("/")[:-1])
                if part in _GENERATED_NAMES
            }
            if name == "scratch":
                roots.add("")
            for prefix in sorted(roots, key=inputs._path_key):
                total = sum(
                    stamp[0]
                    for path, stamp in files.items()
                    if not prefix or inputs._covers(prefix, path)
                )
                generated.append(f"{name}/{prefix}\t{total} bytes")
        generated_note = (
            "Generated caches are separate WorkerOutput; "
            "generic build paths retain authored source.\n"
            + (
                "Byte copies withheld by the cumulative limit; originals retained at task_root.\n"
                if exceeds_limit
                else ""
            )
            + (
                "Rejected trees retained at task_root: " + ",".join(sorted(unavailable)) + "\n"
                if unavailable
                else ""
            )
            + "\n".join(generated)
        )
        _host_artifact(
            staging,
            "validation/generated-roots.txt",
            generated_note.encode("utf-8"),
            artifacts,
            deadline,
        )
        observations = {
            "transport_state": transport,
            "scope_status": scope,
            "outputs_status": outputs,
            "coverage_status": coverage,
            "test_observations": tests,
            "acceptance_observations": [
                {
                    "id": identity,
                    "result": "Unrun" if transport == "NotRun" else "Unverified",
                    "evidence_refs": [],
                }
                for identity in task["acceptance_ids"]
            ],
        }
        artifacts.sort(key=lambda item: inputs._path_key(item["path"]))
        artifact_raw = inputs._canonical_json_bytes(artifacts)
        candidate_sha = _tree_sha(candidate_work, candidate_dirs)
        blockers = list(dict.fromkeys(blockers))
        remaining = set([] if progress is None else progress["remaining_paths"])
        remaining.update(coverage_remaining)
        continuation = {
            "snapshot_id": task["snapshot_id"],
            "candidate_tree_sha256": candidate_sha,
            "artifact_manifest_sha256": inputs._sha256_bytes(artifact_raw),
            "task_manifest_sha256": task_sha,
            "remaining_acceptance_ids": list(task["acceptance_ids"]),
            "remaining_paths": sorted(remaining, key=inputs._path_key),
            "last_test_run_id": next(
                (
                    item["test_run_id"]
                    for item in reversed(tests)
                    if item["test_run_id"] in verified_tests
                ),
                None,
            ),
            "blocker": blockers[0] if blockers else None,
            "next_action": "Management review of collected evidence and any remaining requirements",
            "session_id": None if receipt is None else receipt["capture_uid"],
        }
        if (
            scope != "Pass"
            or exceeds_limit
            or unavailable
            or (receipt is not None and receipt["launch_count"] is None)
            or "RunReceiptInvalid" in blockers
        ):
            continuation = None
        result = {
            "contract_version": 1,
            "task_id": task["task_id"],
            "snapshot_id": task["snapshot_id"],
            "task_manifest_sha256": task_sha,
            "plan_sha256": plan_sha,
            "worker_status": None if progress is None else progress["status"],
            "host_observations": observations,
            "changes": changes,
            "artifacts": artifacts,
            "blockers": blockers,
            "continuation": continuation,
            "management_decision": None,
        }
        # Recheck bytes before publication. Failures leave all staged copies.
        for name, inventory in inventories.items():
            if name not in unavailable and _inventory(root / name, limit, deadline) != inventory:
                _fail("InputChanged")
        inputs.read_snapshot(snapshot_root=root / "control" / "snapshot")
        if _read(root / "task.json") != raw:
            _fail("TaskBindingMismatch")
        if _read(root / "SEALED") != task_sha.encode("ascii"):
            _fail("TaskBindingMismatch")
        for path, contents in observed_controls.items():
            if _read(root / path) != contents:
                _fail("ControlChanged")
        for path, stamp in control_files.items():
            contents = _read(root / path)
            if (len(contents), inputs._sha256_bytes(contents)) != stamp:
                _fail("ControlChanged")
        _write(staging / "changes.json", inputs._canonical_json_bytes(changes), deadline)
        _write(staging / "artifacts.json", artifact_raw, deadline)
        _write(staging / "result.json", inputs._canonical_json_bytes(result), deadline)
        inputs._assert_plain_target(staging, label="result staging")
        inputs._assert_plain_target(result_root, label="result final root")
        deadline.check()
        os.rename(staging, result_root)
        return result
    except BaseException as error:
        _failure_label(staging, getattr(error, "code", "IoFailed"))
        raise
