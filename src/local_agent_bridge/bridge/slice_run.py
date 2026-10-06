"""One local run of a regenerated ag_slice_workspace plan (offline entry, no MCP).

``run`` consumes the plan that the bridge slice workspace regenerates from one frozen
task root and drives exactly one host run. Without `--execute` it is a read-only
preflight: the plan, the executable identity and the settings shape are re-verified,
the intended run is explained, nothing is written and nothing is started. With
`--execute` it performs the verified configuration lifecycle (original-byte backup
with owner-only access, exact insertion of this plan's file rules, restore in a
`finally`), launches the CLI exactly once with `cwd` fixed to the plan work directory,
captures encrypted stdout/stderr, and writes the run receipt under a new dedicated run
root that is never reused.

The plan is always regenerated here; the caller cannot pass an argv, a model or
permission rules. The executable is bound to one explicit absolute path plus its
expected SHA-256, and an unknown executable is never started. Configuration
semantics reuse the tested strict JSON helpers ``decode_strict_json_bytes`` and
``deep_equal_strict``: duplicate keys never parse, and only a difference that strict
JSON can express as layout (JSON-legal whitespace or escape spelling) counts as
drift without meaning change. A concurrent semantic change is never overwritten;
the restore reports blocked and the run is not a success. Real permission
behaviour stays host-side: this tool is not an OS sandbox.

Exit codes: 0 means the run lifecycle completed with a verified restore - the
model result is reported separately and exit 0 is never a Coding success claim;
2 means refused before any configuration change and any launch, including a
pre-launch environment failure (a minimal structured refusal is printed on
stdout and no file receipt is written); 3 means the lifecycle did not complete,
an unsafe restore was reported, or an evidence receipt could not be persisted.
An unpersisted receipt is never claimed: stdout then reports
receipt_persisted=false with a fixed stage label and the exception type, and no
exception text, command line or configuration content is emitted.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import msvcrt
import ntpath
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT.parent))

from local_agent_bridge.bridge import slice_workspace  # noqa: E402
from local_agent_bridge.bridge.contract import (  # noqa: E402
    BridgeContractError,
    decode_strict_json_bytes,
    deep_equal_strict,
)
from local_agent_bridge.bridge.paths import _is_reparse, _is_within  # noqa: E402
from local_agent_bridge.bridge.winjob import (  # noqa: E402
    LaunchLifecycle,
    _close_child_pipes,
    spawn_suspended_in_job,
)
from local_agent_bridge.capture.keys import SessionKeyError, load_key  # noqa: E402
from local_agent_bridge.capture.retention import StorageError  # noqa: E402
from local_agent_bridge.capture.session import (  # noqa: E402
    FRAME_MAX_PLAINTEXT,
    SessionError,
    SessionStore,
    SessionStream,
)

RUN_SCHEMA_VERSION = 2
PRIVATE_HELPER = PACKAGE_ROOT / "resources" / "ag_slice_run_private.ps1"
PWSH_CANDIDATES = (r"C:\Program Files\PowerShell\7\pwsh.exe",)
ARGV_ELEMENT_COUNT = 11
FIXED_ARGV_TAIL = [
    "--model",
    "gemini-3.8-flash-high",
    "--effort",
    "high",
    "--output-format",
    "stream-json",
    "--disable-slash-commands",
    "--print-timeout",
    "15m",
]
READ_CHUNK_BYTES = FRAME_MAX_PLAINTEXT
HASH_CHUNK_BYTES = 1_048_576
OBSERVATION_TIMEOUT_SECONDS = 1020.0
KILL_GRACE_SECONDS = 30.0
CAPTURE_JOIN_SECONDS = 30.0
AUTO_UPDATE_VARIABLE = "AGY_CLI_DISABLE_AUTO_UPDATE"
AUTO_UPDATE_VALUE = "true"
EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_LIFECYCLE_FAILED = 3
EXIT_LABELS = {
    EXIT_OK: "lifecycle_completed_restore_verified",
    EXIT_REFUSED: "refused_before_launch",
    EXIT_LIFECYCLE_FAILED: "lifecycle_not_completed_or_unsafe_restore",
}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_DRIVE_PATTERN = re.compile(r"[A-Za-z]:")
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
_KERNEL = ctypes.WinDLL("kernel32", use_last_error=True)
_KERNEL.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
_KERNEL.CreateFileW.restype = wintypes.HANDLE
_KERNEL.CloseHandle.argtypes = [wintypes.HANDLE]
_KERNEL.CloseHandle.restype = wintypes.BOOL


class SliceRunError(RuntimeError):
    """Raised when a run request is refused or cannot be completed."""


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    if isinstance(path, SessionStream):
        return path.sha256
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_plain_chain(path: Path) -> None:
    current = path
    while True:
        if _is_reparse(current):
            raise SliceRunError(f"reparse point refused in chain: {current}")
        if current.parent == current:
            return
        current = current.parent


def _require_plain_file(path: Path, label: str) -> os.stat_result:
    if not path.is_absolute():
        raise SliceRunError(f"{label} must be an absolute path: {path}")
    _require_plain_chain(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & (
        stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise SliceRunError(f"{label} is not a plain regular file: {path}")
    return info


def _verify_executable(raw: str, expected_sha256: str) -> dict[str, object]:
    """Identity binding for exactly one CLI executable file; unknown never starts."""
    if _SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise SliceRunError("expected executable sha256 must be 64 lowercase hex")
    path = Path(raw)
    info = _require_plain_file(path, "executable")
    digest = _sha256_file(path)
    if digest != expected_sha256:
        raise SliceRunError(f"executable sha256 mismatch: {digest}")
    return {"path": str(path), "size_bytes": info.st_size, "sha256": digest}


def _read_settings(path: Path) -> tuple[bytes, dict[str, object]]:
    _require_plain_file(path, "settings")
    payload = path.read_bytes()
    try:
        value = decode_strict_json_bytes(payload, label="settings")
    except BridgeContractError as error:
        raise SliceRunError(f"settings is not one strict JSON document: {path}") from error
    if not isinstance(value, dict):
        raise SliceRunError(f"settings must be a JSON object: {path}")
    if "permissions" in value:
        raise SliceRunError(f"settings already carries a permissions key: {path}")
    return payload, value


def _require_new_run_root(raw: str, task_root: Path) -> Path:
    if ntpath.normpath(raw) != raw or _DRIVE_PATTERN.fullmatch(ntpath.splitdrive(raw)[0]) is None:
        raise SliceRunError("run root must be a normalized absolute Windows path: " + raw)
    root = Path(raw)
    for part in root.parts[1:]:
        if (
            part in {".", ".."}
            or ":" in part
            or ntpath.isreserved(part)
            or part.endswith((".", " "))
        ):
            raise SliceRunError("run root holds a reserved or ambiguous segment: " + raw)
    _require_plain_chain(root)
    if not root.parent.is_dir():
        raise SliceRunError("the run root parent must already exist: " + str(root.parent))
    if root.exists():
        raise SliceRunError("the run root already exists and is never reused: " + raw)
    if _is_within(root, task_root) or _is_within(root, PACKAGE_ROOT):
        raise SliceRunError(
            "the run root must stay outside the task root and the installed package directory: "
            + raw
        )
    return root


def _verify_plan_shape(plan: dict[str, object]) -> None:
    """Independent gate: the regenerated plan must keep the frozen invocation shape."""
    argv = plan.get("argv")
    if plan.get("schema_version") != 1 or plan.get("execution_authorized") is not False:
        raise SliceRunError("plan shape refused: schema or authorization marker")
    if plan.get("model") != "gemini-3.8-flash-high" or plan.get("effort") != "high":
        raise SliceRunError("plan shape refused: model or effort")
    if not isinstance(argv, list) or len(argv) != ARGV_ELEMENT_COUNT or argv[0] != "--print":
        raise SliceRunError("plan shape refused: argv head or element count")
    if argv[2:] != FIXED_ARGV_TAIL:
        raise SliceRunError("plan shape refused: fixed flags")
    if plan.get("cwd") != str(plan.get("task_root")) + "/work":
        raise SliceRunError("plan shape refused: cwd")
    rules = plan.get("permission_rules")
    read_paths = plan.get("read_file")
    write_paths = plan.get("write_file")
    if (
        not isinstance(rules, dict)
        or not isinstance(read_paths, list)
        or not isinstance(write_paths, list)
    ):
        raise SliceRunError("plan shape refused: rules or path lists")
    read_rules = rules.get("read_file")
    write_rules = rules.get("write_file")
    counts = rules.get("counts")
    if (
        not isinstance(read_rules, list)
        or not isinstance(write_rules, list)
        or not isinstance(counts, dict)
    ):
        raise SliceRunError("plan shape refused: rule lists")
    if counts.get("command") != 0 or counts.get("read_file") != len(read_rules):
        raise SliceRunError("plan shape refused: rule counts")
    if counts.get("write_file") != len(write_rules) or len(write_rules) != len(write_paths):
        raise SliceRunError("plan shape refused: write count")
    if len(read_rules) != len(read_paths) or not set(write_paths) <= set(read_paths):
        raise SliceRunError("plan shape refused: path relation")
    if not read_paths or read_paths[0] != str(plan.get("cwd")) + "/TASK.md":
        raise SliceRunError("plan shape refused: task note entry")
    for rule in [*read_rules, *write_rules]:
        if not isinstance(rule, str) or "*" in rule:
            raise SliceRunError("plan shape refused: rule text")
        if not rule.startswith(("read_file(", "write_file(")) or not rule.endswith(")"):
            raise SliceRunError("plan shape refused: rule syntax")


def _pwsh_path() -> str:
    found = shutil.which("pwsh")
    if found is not None:
        return found
    for candidate in PWSH_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise SliceRunError("pwsh is unavailable for owner-only file access")


def _run_directory_acl_helper(path: Path, mode: str) -> None:
    """Apply or verify the fixed owner-only ACL without exposing helper output."""
    completed = subprocess.run(
        [
            _pwsh_path(),
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(PRIVATE_HELPER),
            "-Path",
            str(path),
            "-Kind",
            "Directory",
            "-Mode",
            mode,
        ],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        action = "helper" if mode == "Protect" else "verification"
        raise SliceRunError(f"owner-only directory ACL {action} failed for {path}")


def _protect_directory(path: Path) -> None:
    """Protect a directory that this operation just created."""
    _run_directory_acl_helper(path, "Protect")


def _verify_directory(path: Path) -> None:
    """Check an existing directory without rewriting its ACL."""
    _run_directory_acl_helper(path, "Verify")


def _session_store() -> SessionStore:
    # Key loading is deliberately read-only. The user must run the separate,
    # explicit session-key-init command before the first execute.
    return SessionStore(
        load_key(), protect_directory=_protect_directory, verify_directory=_verify_directory
    )


def _capture_input(writer, task_root: Path, request: str, manifest_sha256: str) -> bool:
    note_path = task_root / "work" / "TASK.md"
    _require_plain_file(note_path, "task note")
    with note_path.open("rb") as source:
        for chunk in iter(lambda: source.read(READ_CHUNK_BYTES), b""):
            if not writer.append("task", chunk):
                return False
    manifest_path = task_root / "manifest.json"
    _require_plain_file(manifest_path, "task manifest")
    manifest_bytes = manifest_path.read_bytes()
    if _sha256_hex(manifest_bytes) != manifest_sha256:
        raise SessionError("task manifest changed before capture")
    manifest = decode_strict_json_bytes(manifest_bytes, label="task manifest")
    expected_note = manifest["task_note"]
    if (
        writer._lengths["task"] != expected_note["bytes"]
        or writer._hashes["task"].hexdigest() != expected_note["sha256"]
    ):
        raise SessionError("task input differs from the frozen manifest")
    encoded = request.encode("utf-8")
    for offset in range(0, len(encoded), READ_CHUNK_BYTES):
        if not writer.append("request", encoded[offset : offset + READ_CHUNK_BYTES]):
            return False
    return True


def _open_exclusive_rw(path: Path):
    """Exclusive read/write handle, following the coding snapshot native-open pattern."""
    handle = _KERNEL.CreateFileW(
        str(path), _GENERIC_READ | _GENERIC_WRITE, 0, None, _OPEN_EXISTING, 0, None
    )
    if handle == _INVALID_HANDLE_VALUE or handle is None:
        raise SliceRunError(f"exclusive settings open failed (winerror {ctypes.get_last_error()})")
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except BaseException:
        _KERNEL.CloseHandle(handle)
        raise
    return os.fdopen(descriptor, "r+b")


def _parse_or_none(payload: bytes) -> object:
    try:
        return decode_strict_json_bytes(payload, label="settings")
    except BridgeContractError:
        return None


def _build_patched_settings(before_bytes: bytes, rules: list[str]) -> bytes:
    """Insert exactly this plan's allow list, then verify semantics did not move."""
    before_value = decode_strict_json_bytes(before_bytes, label="settings")
    if not isinstance(before_value, dict) or "permissions" in before_value:
        raise SliceRunError("settings shape changed before the patch was built")
    text = before_bytes.decode("utf-8")
    brace = text.find("{")
    if brace < 0:
        raise SliceRunError("settings object opening brace missing")
    permissions = (
        '  "permissions": {\n    "allow": [\n'
        + ",\n".join("      " + json.dumps(rule) for rule in rules)
        + "\n    ]\n  }"
    )
    rest = text[brace + 1 :]
    separator = "" if rest.strip() in {"", "}"} else ",\n"
    patched = (text[: brace + 1] + "\n" + permissions + separator + rest).encode("utf-8")
    patched_value = _parse_or_none(patched)
    if not isinstance(patched_value, dict):
        raise SliceRunError("patched settings is not one strict JSON document")
    if set(patched_value) != set(before_value) | {"permissions"}:
        raise SliceRunError("patched settings changed the key set")
    for key in before_value:
        if not deep_equal_strict(patched_value[key], before_value[key]):
            raise SliceRunError(f"patched settings changed the value of {key}")
    if not deep_equal_strict(patched_value["permissions"], {"allow": list(rules)}):
        raise SliceRunError("patched settings permissions do not match the plan rules")
    return patched


def _apply_settings_patch(settings_path: Path, before_bytes: bytes, patched_bytes: bytes) -> None:
    with _open_exclusive_rw(settings_path) as stream:
        current = stream.read()
        if current != before_bytes:
            raise SliceRunError("settings changed between verification and write")
        stream.seek(0)
        stream.write(patched_bytes)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
    if _sha256_file(settings_path) != _sha256_hex(patched_bytes):
        raise SliceRunError("settings patch write could not be verified")


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def _canonical_json(document: object) -> bytes:
    return json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _write_json_new(path: Path, document: object) -> None:
    _write_new(path, _canonical_json(document) + b"\n")


def _save_drift_scene(private_dir: Path, payload: bytes) -> str:
    scene = private_dir / "settings.drift-01.bin"
    _write_new(scene, payload)
    return str(scene)


def _restore_settings(
    settings_path: Path, before_bytes: bytes, patched_bytes: bytes, private_dir: Path
) -> dict[str, object]:
    """Restore the original bytes; a concurrent semantic change is never overwritten."""
    before_sha = _sha256_hex(before_bytes)
    patched_sha = _sha256_hex(patched_bytes)
    record: dict[str, object] = {
        "status": "not_attempted",
        "restored_original_bytes": False,
        "before_sha256": before_sha,
        "patched_sha256": patched_sha,
    }
    classification = "patched_bytes"
    try:
        with _open_exclusive_rw(settings_path) as stream:
            current = stream.read()
            current_sha = _sha256_hex(current)
            record["observed_sha256"] = current_sha
            if current_sha == patched_sha:
                classification = "patched_bytes"
            elif current_sha == before_sha:
                classification = "already_original"
            else:
                record["drift_scene"] = _save_drift_scene(private_dir, current)
                current_value = _parse_or_none(current)
                if current_value is None or not deep_equal_strict(
                    current_value, decode_strict_json_bytes(patched_bytes, label="settings")
                ):
                    classification = "semantic_or_invalid_drift"
                else:
                    classification = "json_legal_layout_drift"
                record["drift_classification"] = classification
            if classification == "semantic_or_invalid_drift":
                record["status"] = "restore_blocked_semantic_or_invalid_drift"
                return record
            stream.seek(0)
            stream.write(before_bytes)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, SliceRunError) as error:
        record["status"] = "restore_failed"
        record["error"] = (
            type(error).__name__ if isinstance(error, OSError) else "exclusive_open_failed"
        )
        return record
    try:
        final_sha = _sha256_file(settings_path)
    except OSError as error:
        record["status"] = "restore_failed"
        record["error"] = type(error).__name__
        return record
    record["final_sha256"] = final_sha
    if final_sha != before_sha:
        record["status"] = "restore_failed"
        return record
    record["restored_original_bytes"] = True
    record["status"] = {
        "patched_bytes": "restored",
        "already_original": "restored_already_original",
        "json_legal_layout_drift": "restored_json_legal_layout_drift",
    }[classification]
    return record


def _drain_stream(stream, destination: SessionStream) -> dict[str, object]:
    """Encrypt each raw chunk; on storage failure continue draining the pipe."""
    kept = 0
    read_total = 0
    while True:
        chunk = stream.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        read_total += len(chunk)
        if destination.append(chunk):
            kept += len(chunk)
    return {"bytes_read": read_total, "bytes_kept": kept, "truncated": read_total != kept}


def _launch_and_capture(
    exe: str,
    argv: list[str],
    cwd: str,
    stdout_path: SessionStream,
    stderr_path: SessionStream,
    *,
    timeout_seconds: float = OBSERVATION_TIMEOUT_SECONDS,
    on_spawn: Callable[[int], None] | None = None,
    lifecycle: LaunchLifecycle | None = None,
) -> dict[str, object]:
    """Exactly one bounded launch; post-spawn failures are reported, never hidden.

    The caller and native spawner share one execution fact, including failures
    before a process is returned. The callback remains a post-return observer.
    Interrupts propagate unchanged after cleanup. Stalled readers get no hash.
    """
    if isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= OBSERVATION_TIMEOUT_SECONDS:
        raise SliceRunError("observation deadline is outside the fixed limit")
    started = time.monotonic()
    started_utc = datetime.now(UTC).isoformat()
    lifecycle = lifecycle if lifecycle is not None else LaunchLifecycle()
    process = spawn_suspended_in_job(argv, cwd, lifecycle=lifecycle)
    statistics: dict[str, dict[str, object]] = {}
    readers: list[threading.Thread] = []
    capture_error: str | None = None
    launch_error: BaseException | None = None
    join_deadline: float | None = None
    timed_out = False

    def collect(stream, destination: SessionStream, prefix: str) -> None:
        try:
            statistics[prefix] = _drain_stream(stream, destination)
        except Exception as error:  # reader threads cannot raise to the caller
            statistics[prefix] = {"error": type(error).__name__}

    try:
        lifecycle.stage = "capture_start"
        if on_spawn is not None:
            on_spawn(process.pid)
        for prefix, stream, destination in (
            ("stdout", process.stdout, stdout_path),
            ("stderr", process.stderr, stderr_path),
        ):
            reader = threading.Thread(
                target=collect, args=(stream, destination, prefix), daemon=True
            )
            readers.append(reader)
            reader.start()
        try:
            lifecycle.stage = "capture_wait"
            process.wait(timeout=timeout_seconds)
            lifecycle.child_exit_observed = True
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate_once()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=KILL_GRACE_SECONDS)
                lifecycle.child_exit_observed = True
        join_deadline = time.monotonic() + CAPTURE_JOIN_SECONDS
        for reader in readers:
            reader.join(timeout=max(0.0, join_deadline - time.monotonic()))
        if any(reader.is_alive() for reader in readers):
            capture_error = "reader_join_timeout"
    except BaseException as error:  # includes interrupts after confirmed resume
        launch_error = error
        capture_error = capture_error or type(error).__name__
        with contextlib.suppress(BaseException):
            process.terminate_once()
        with contextlib.suppress(BaseException):
            process.wait(timeout=KILL_GRACE_SECONDS)
            lifecycle.child_exit_observed = True
        if not isinstance(error, Exception):
            raise
    finally:
        cleanup_error: BaseException | None = None
        try:
            closed = process.close_job()
            lifecycle.job_closed = closed if type(closed) is bool else None
            if closed is False:
                capture_error = capture_error or "job_close_failed"
        except BaseException as error:
            cleanup_error = error
        if join_deadline is None:
            join_deadline = time.monotonic() + CAPTURE_JOIN_SECONDS
        try:
            for reader in readers:
                if reader.ident is not None:
                    reader.join(timeout=max(0.0, join_deadline - time.monotonic()))
            if not any(reader.is_alive() for reader in readers):
                lifecycle.pipes_closed = _close_child_pipes(process)
                if lifecycle.pipes_closed is False:
                    capture_error = capture_error or "pipe_close_failed"
        except BaseException as error:
            cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            capture_error = capture_error or type(cleanup_error).__name__
            if launch_error is None and not isinstance(cleanup_error, Exception):
                raise cleanup_error
    for prefix in ("stdout", "stderr"):
        error = statistics.get(prefix, {}).get("error")
        if error and capture_error is None:
            capture_error = str(error)
    if stdout_path.writer.incomplete_reason or stderr_path.writer.incomplete_reason:
        capture_error = capture_error or stdout_path.writer.incomplete_reason
    record: dict[str, object] = {
        **lifecycle.record(),
        "capture_state": "complete" if capture_error is None else "incomplete",
        "capture_error": capture_error,
        "timed_out": timed_out,
        "started_utc": started_utc,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "observation_timeout_seconds": timeout_seconds,
        "exit_code": process.returncode,
    }
    if capture_error is not None:
        return record
    stdout_stats = statistics.get("stdout", {})
    stderr_stats = statistics.get("stderr", {})
    try:
        final_capture = {
            "stdout_bytes": stdout_path.stat().st_size,
            "stdout_sha256": stdout_path.sha256,
            "stdout_truncated": bool(stdout_stats.get("truncated", False)),
            "stderr_bytes": stderr_path.stat().st_size,
            "stderr_sha256": stderr_path.sha256,
            "stderr_truncated": bool(stderr_stats.get("truncated", False)),
        }
    except Exception as error:
        record["capture_state"] = "incomplete"
        record["capture_error"] = type(error).__name__
        return record
    record.update(final_capture)
    return record


def _event_lines(chunks):
    pending = bytearray()
    discarding = False
    for chunk in chunks:
        for segment in chunk.split(b"\n")[:-1]:
            if discarding:
                discarding = False
                pending.clear()
                continue
            pending.extend(segment)
            if len(pending) > 32 * 1024 * 1024:
                yield None
            else:
                yield bytes(pending).rstrip(b"\r")
            pending.clear()
        tail = chunk.rsplit(b"\n", 1)[-1]
        if b"\n" in chunk and discarding:
            discarding = False
        if not discarding:
            pending.extend(tail)
            if len(pending) > 32 * 1024 * 1024:
                yield None
                pending.clear()
                discarding = True
    if pending and not discarding:
        yield bytes(pending)


def _scan_stream(
    stdout_path: Path | SessionStream,
) -> tuple[set[str], str | None, bool, bool, bool]:
    """Scan the CLI's wrapped stream events and the older flat test format."""
    statuses: set[str] = set()
    last_status: str | None = None
    denied = False
    error_seen = False
    malformed = False
    # Production reads authenticated frames without making a second plaintext
    # file. The Path case is retained only for the narrow parser unit tests.
    chunks = (
        (stdout_path.read_bytes(),) if isinstance(stdout_path, Path) else stdout_path.iter_chunks()
    )
    for line in _event_lines(chunks):
        if line is None:
            malformed = True
            continue
        value = _parse_or_none(line)
        if not isinstance(value, dict):
            malformed = True
            continue
        if "event" in value:
            event = value["event"]
            if (
                "type" in value
                or not isinstance(event, str)
                or event not in {"init", "step_update", "result"}
            ):
                malformed = True
                continue
            payload = value.get(event)
            if not isinstance(payload, dict):
                malformed = True
                continue
        else:
            event = value.get("type")
            if not isinstance(event, str):
                malformed = True
                continue
            payload = value
        if event == "result":
            status = payload.get("status")
            if isinstance(status, str):
                statuses.add(status)
                last_status = status
            else:
                malformed = True
        for record in (value, payload):
            denied = denied or bool(record.get("denied_actions"))
            error_seen = error_seen or bool(record.get("error"))
    return statuses, last_status, denied, error_seen, malformed


def _classify_coding(
    stdout_path: Path | SessionStream, launch_record: dict[str, object]
) -> dict[str, object]:
    """The model result is judged separately from the process exit code.

    provider_completed needs a complete capture, a zero process exit and exactly
    one distinct terminal status without denied actions or error flags, so
    repeated identical terminal lines still count as one status. It still never
    accepts the candidate, and every other combination keeps its own label.
    """
    if launch_record.get("capture_state") != "complete":
        return {"outcome": "capture_incomplete", "result_status": None}
    if launch_record.get("timed_out"):
        return {"outcome": "observation_timeout", "result_status": None}
    if launch_record.get("stdout_truncated") or launch_record.get("stderr_truncated"):
        return {"outcome": "capture_truncated", "result_status": None}
    if launch_record.get("exit_code") != 0:
        return {"outcome": "nonzero_exit", "result_status": None}
    statuses, last_status, denied, error_seen, malformed = _scan_stream(stdout_path)
    if malformed:
        return {"outcome": "stream_malformed", "result_status": None}
    if denied:
        return {"outcome": "denied_actions", "result_status": last_status}
    distinct = sorted(statuses)
    if len(distinct) > 1:
        return {"outcome": "conflicting_terminal_states", "result_status": None}
    if not distinct:
        return {"outcome": "result_missing", "result_status": None}
    status = distinct[0]
    if status == "SUCCESS" and not error_seen:
        return {"outcome": "provider_completed", "result_status": status}
    if status == "ERROR" or error_seen:
        return {"outcome": "model_error", "result_status": status}
    return {"outcome": "model_terminal_other", "result_status": status}


def _emit_json(document: dict[str, object]) -> None:
    payload = _canonical_json(document) + b"\n"
    stream = getattr(sys.stdout, "buffer", None)
    sys.stdout.flush()
    if stream is None:
        sys.stdout.write(payload.decode("utf-8"))
        return
    stream.write(payload)


def command_run(arguments: argparse.Namespace) -> int:
    try:
        plan = slice_workspace.build_plan(arguments.task_root)
    except slice_workspace.SliceWorkspaceError as error:
        raise SliceRunError(str(error)) from error
    _verify_plan_shape(plan)
    task_root = Path(str(plan["task_root"]))
    executable = _verify_executable(arguments.exe, arguments.exe_sha256)
    settings_path = Path(arguments.settings)
    settings_bytes, settings_value = _read_settings(settings_path)
    run_root = _require_new_run_root(arguments.run_root, task_root)
    plan_bytes = _canonical_json(plan)
    rules = [*plan["permission_rules"]["read_file"], *plan["permission_rules"]["write_file"]]
    if not arguments.execute:
        _emit_json(
            {
                "schema_version": 1,
                "mode": "preflight",
                "execute": False,
                "task_root": str(task_root),
                "run_root_would_create": str(run_root),
                "plan": {
                    "manifest_sha256": plan["manifest_sha256"],
                    "source_commit": plan["source_commit"],
                    "read_file": len(plan["read_file"]),
                    "write_file": len(plan["write_file"]),
                },
                "executable": executable,
                "settings": {
                    "path": str(settings_path),
                    "size_bytes": len(settings_bytes),
                    "sha256": _sha256_hex(settings_bytes),
                    "permissions_absent": "permissions" not in settings_value,
                },
                "observation": {
                    "timeout_seconds": OBSERVATION_TIMEOUT_SECONDS,
                    "session_domain_limit_bytes": 100 * 1024 * 1024,
                },
                "note": "preflight only: no configuration change and no process",
            }
        )
        return EXIT_OK

    try:
        patched_bytes = _build_patched_settings(settings_bytes, rules)
    except SliceRunError:
        raise
    except Exception as error:
        raise SliceRunError(
            f"settings patch could not be constructed: {type(error).__name__}"
        ) from error
    store = _session_store()
    private_dir = run_root / "private"
    capture_dir = run_root / "capture"
    setup_steps = (
        ("run root creation", run_root.mkdir),
        ("private directory creation", private_dir.mkdir),
        ("capture directory creation", capture_dir.mkdir),
        ("private directory protection", lambda: _protect_directory(private_dir)),
        ("capture directory protection", lambda: _protect_directory(capture_dir)),
        (
            "plan receipt write",
            lambda: _write_json_new(
                run_root / "plan.json",
                {
                    "schema_version": 1,
                    "plan_sha256": _sha256_hex(plan_bytes),
                    "manifest_sha256": plan["manifest_sha256"],
                    "source_commit": plan["source_commit"],
                    "argv_elements": len(plan["argv"]),
                },
            ),
        ),
        (
            "original settings backup",
            lambda: _write_new(private_dir / "settings.original.bin", settings_bytes),
        ),
        (
            "patched settings backup",
            lambda: _write_new(private_dir / "settings.patched.bin", patched_bytes),
        ),
    )
    for setup_stage, setup_step in setup_steps:
        try:
            setup_step()
        except SliceRunError:
            raise
        except Exception as error:
            # Environment failure before any configuration change and any launch:
            # a controlled refusal with a minimal structured receipt on stdout.
            _emit_json(
                {
                    "schema_version": RUN_SCHEMA_VERSION,
                    "mode": "execute",
                    "task_root": str(task_root),
                    "run_root": str(run_root),
                    "setup_stage": setup_stage,
                    "setup_error": type(error).__name__,
                    "receipt_persisted": False,
                    "exit_code": EXIT_REFUSED,
                    "exit_code_label": EXIT_LABELS[EXIT_REFUSED],
                    "note": (
                        "refused before any configuration change and before any launch; "
                        "no file receipt was written"
                    ),
                }
            )
            return EXIT_REFUSED
    try:
        writer = store.start()
        if not _capture_input(
            writer, task_root, str(plan["argv"][1]), str(plan["manifest_sha256"])
        ):
            if writer.incomplete_reason == "over_limit":
                raise StorageError("over_limit: input exceeds session storage budget")
            raise SessionError("encrypted input capture is unavailable")
    except (OSError, StorageError, SessionError, SliceRunError, BridgeContractError) as error:
        reason = (
            "over_limit"
            if isinstance(error, StorageError) and str(error).startswith("over_limit")
            else "capture_unavailable"
        )
        _emit_json(
            {
                "schema_version": RUN_SCHEMA_VERSION,
                "mode": "execute",
                "run_root": str(run_root),
                "setup_stage": "encrypted session input capture",
                "setup_error": type(error).__name__,
                "setup_reason": reason,
                "receipt_persisted": False,
                "capture_state": "incomplete",
                "exit_code": EXIT_REFUSED,
                "exit_code_label": EXIT_LABELS[EXIT_REFUSED],
            }
        )
        return EXIT_REFUSED
    stdout_sink = writer.stream("stdout")
    stderr_sink = writer.stream("stderr")
    patch_record = {
        "before_sha256": _sha256_hex(settings_bytes),
        "patched_sha256": _sha256_hex(patched_bytes),
        "before_size": len(settings_bytes),
        "patched_size": len(patched_bytes),
        "rules": rules,
        "rule_counts": {
            "read_file": len(plan["permission_rules"]["read_file"]),
            "write_file": len(plan["permission_rules"]["write_file"]),
            "command": 0,
        },
        "only_permissions_added": True,
    }
    process_argv = [str(executable["path"]), *plan["argv"]]
    launch_record = None
    launch_attempted = False
    lifecycle = LaunchLifecycle()
    lifecycle_exception = None
    interrupted: BaseException | None = None
    evidence_write_failures: list[dict[str, str]] = []

    def write_evidence(stage: str, path: Path, document: object) -> None:
        """Record one failed attempt; finish other writes before propagating interrupts."""
        nonlocal interrupted
        try:
            _write_json_new(path, document)
        except BaseException as error:
            evidence_write_failures.append({"stage": stage, "error": type(error).__name__})
            if interrupted is None and not isinstance(error, Exception):
                interrupted = error

    try:
        _apply_settings_patch(settings_path, settings_bytes, patched_bytes)
        _write_json_new(run_root / "config-patch.json", patch_record)
        previous_auto_update = os.environ.get(AUTO_UPDATE_VARIABLE)
        os.environ[AUTO_UPDATE_VARIABLE] = AUTO_UPDATE_VALUE
        try:
            launch_attempted = True
            launch_record = _launch_and_capture(
                str(executable["path"]),
                process_argv,
                str(plan["cwd"]),
                stdout_sink,
                stderr_sink,
                lifecycle=lifecycle,
            )
        finally:
            if previous_auto_update is None:
                os.environ.pop(AUTO_UPDATE_VARIABLE, None)
            else:
                os.environ[AUTO_UPDATE_VARIABLE] = previous_auto_update
    except BaseException as error:
        lifecycle_exception = type(error).__name__
        if not isinstance(error, Exception):
            interrupted = error
    finally:
        try:
            restore_record = _restore_settings(
                settings_path, settings_bytes, patched_bytes, private_dir
            )
        except BaseException as error:
            # No observed restore result: retain failure, never infer restored bytes.
            restore_record = {
                "status": "restore_failed",
                "restored_original_bytes": False,
                "final_sha256": None,
                "before_sha256": _sha256_hex(settings_bytes),
                "patched_sha256": _sha256_hex(patched_bytes),
                "error": type(error).__name__,
            }
            lifecycle_exception = lifecycle_exception or type(error).__name__
            if interrupted is None and not isinstance(error, Exception):
                interrupted = error
        write_evidence("config-restore.json", run_root / "config-restore.json", restore_record)
    if launch_record is None or lifecycle.launch_count != 1:
        coding = {"outcome": "launch_failed", "result_status": None}
    else:
        try:
            if writer.incomplete_reason is not None:
                launch_record["capture_state"] = "incomplete"
                launch_record["capture_error"] = writer.incomplete_reason
            coding = _classify_coding(stdout_sink, launch_record)
        except BaseException as error:
            lifecycle_exception = lifecycle_exception or type(error).__name__
            if interrupted is None and not isinstance(error, Exception):
                interrupted = error
            launch_record["capture_state"] = "incomplete"
            launch_record["capture_error"] = type(error).__name__
            for key in (
                "stdout_bytes",
                "stdout_sha256",
                "stdout_truncated",
                "stderr_bytes",
                "stderr_sha256",
                "stderr_truncated",
            ):
                launch_record.pop(key, None)
            coding = {"outcome": "capture_incomplete", "result_status": None}
    restored = bool(restore_record["restored_original_bytes"])
    capture_complete = bool(
        launch_record
        and launch_record.get("capture_state") == "complete"
        and lifecycle.launch_count == 1
        and interrupted is None
    )
    if capture_complete:
        try:
            writer.seal(
                {
                    "plan_sha256": _sha256_hex(plan_bytes),
                    "executable_sha256": executable["sha256"],
                    "settings_before_sha256": _sha256_hex(settings_bytes),
                    "settings_final_sha256": restore_record.get("final_sha256"),
                    "process_exit_code": launch_record.get("exit_code"),
                    "coding_outcome": coding["outcome"],
                    "restore_status": restore_record["status"],
                }
            )
        except BaseException as error:
            lifecycle_exception = lifecycle_exception or type(error).__name__
            if not isinstance(error, Exception):
                interrupted = error
            capture_complete = False
            launch_record["capture_state"] = "incomplete"
            launch_record["capture_error"] = type(error).__name__
            coding = {"outcome": "capture_incomplete", "result_status": None}
    receipt = {
        "schema_version": RUN_SCHEMA_VERSION,
        "mode": "execute",
        "task_root": str(task_root),
        "run_root": str(run_root),
        "plan_sha256": _sha256_hex(plan_bytes),
        "manifest_sha256": plan["manifest_sha256"],
        "source_commit": plan["source_commit"],
        "executable": executable,
        "settings": {
            "path": str(settings_path),
            "before_sha256": _sha256_hex(settings_bytes),
            "patched_sha256": _sha256_hex(patched_bytes),
            "final_sha256": restore_record.get("final_sha256"),
        },
        "launches": lifecycle.launch_count,
        "spawn_state": (
            "confirmed"
            if lifecycle.execution_state == "confirmed"
            else ("not_confirmed" if launch_attempted else "not_attempted")
        ),
        "launch_attempts": 1 if launch_attempted else 0,
        "launch": launch_record if launch_record is not None else lifecycle.record(),
        "cwd": plan["cwd"],
        "argv_elements": len(plan["argv"]),
        "coding": coding,
        "session": {
            "session_id": writer.session_id,
            "sealed": writer.sealed,
            "capture_complete": capture_complete,
            "storage_root": str(store.domain.root),
        },
        "restore": {
            "status": restore_record["status"],
            "restored_original_bytes": restored,
            "drift_classification": restore_record.get("drift_classification"),
        },
        "lifecycle_exception": lifecycle_exception,
        "evidence_write_failures": list(evidence_write_failures),
    }
    receipt_persisted = True
    try:
        _write_json_new(run_root / "run.json", receipt)
    except BaseException as error:
        receipt_persisted = False
        evidence_write_failures.append({"stage": "run.json", "error": type(error).__name__})
        if interrupted is None and not isinstance(error, Exception):
            interrupted = error
    exit_code = (
        EXIT_OK
        if lifecycle_exception is None
        and lifecycle.launch_count == 1
        and interrupted is None
        and restored
        and capture_complete
        and not evidence_write_failures
        else EXIT_LIFECYCLE_FAILED
    )
    document = {
        "schema_version": RUN_SCHEMA_VERSION,
        "mode": "execute",
        "task_root": str(task_root),
        "run_root": str(run_root),
        "launches": receipt["launches"],
        "spawn_state": receipt["spawn_state"],
        "coding": coding,
        "session": receipt["session"],
        "restore": receipt["restore"],
        "lifecycle_exception": lifecycle_exception,
        "evidence_write_failures": list(evidence_write_failures),
        "receipt_persisted": receipt_persisted,
        "exit_code": exit_code,
        "exit_code_label": EXIT_LABELS[exit_code],
        "run_receipt": str(run_root / "run.json") if receipt_persisted else None,
        "note": (
            "exit 0 covers the run lifecycle and a verified restore only; "
            "provider_completed is not candidate acceptance"
        ),
    }
    try:
        _emit_json(document)
    except BaseException:
        if interrupted is None:
            raise
    if interrupted is not None:
        raise interrupted
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-agent-bridge",
        description=(
            "Run one regenerated ag_slice_workspace plan locally. Preflight by default; "
            "--execute is the separate opt-in for the real configuration lifecycle and launch. "
            "One fixed local CLI invocation only: no arbitrary command, model, URL or path."
        ),
        epilog=(
            "examples:\n"
            "  uv run local-agent-bridge run --task-root <root> --run-root <new dir>\n"
            "      --exe <absolute agy.exe path> --exe-sha256 <64 hex>\n"
            "      --settings <absolute settings.json>\n"
            "  uv run local-agent-bridge run ... --execute"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="preflight (default) or execute one plan")
    run.add_argument("--task-root", required=True)
    run.add_argument("--run-root", required=True)
    run.add_argument("--exe", required=True)
    run.add_argument("--exe-sha256", required=True)
    run.add_argument("--settings", required=True)
    run.add_argument("--execute", action="store_true")
    run.set_defaults(handler=command_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        return arguments.handler(arguments)
    except (SliceRunError, SessionKeyError, StorageError, SessionError) as error:
        print("local-agent-bridge: " + str(error), file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
