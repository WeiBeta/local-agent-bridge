"""One fixed Cursor CLI call over the existing encrypted capture pipeline.

This entry reuses the frozen slice contract and the encrypted session store and
adds exactly one fixed launcher invocation. It never parses model events, never
patches or restores a settings file, and never accepts caller-supplied argv,
models, URLs or extra paths.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from local_agent_bridge.bridge import slice_workspace
from local_agent_bridge.bridge.contract import decode_strict_json_bytes
from local_agent_bridge.bridge.slice_run import (
    CAPTURE_JOIN_SECONDS,
    EXIT_LABELS,
    EXIT_LIFECYCLE_FAILED,
    EXIT_OK,
    EXIT_REFUSED,
    KILL_GRACE_SECONDS,
    OBSERVATION_TIMEOUT_SECONDS,
    SliceRunError,
    _canonical_json,
    _emit_json,
    _launch_and_capture,
    _protect_directory,
    _pwsh_path,
    _require_new_run_root,
    _require_plain_file,
    _session_store,
    _sha256_file,
    _sha256_hex,
    _verify_executable,
    _write_json_new,
)
from local_agent_bridge.capture.keys import SessionKeyError
from local_agent_bridge.capture.retention import StorageError
from local_agent_bridge.capture.session import SessionError

CURSOR_SCHEMA_VERSION = 1
CURSOR_MODEL = "grok-4.7-high"
CURSOR_CONFIG_RELATIVE = ".cursor/cli.json"
CURSOR_SESSION_KIND = "cursor_cli_one_call"
CURSOR_ARGV_FLAGS = ("--workspace", "-p", "--model", "--output-format", "--force")
CURSOR_STREAM_SOURCES = {
    "task": "frozen work/TASK.md original bytes",
    "request": "Cursor CLI positional prompt bytes (TASK.md minus one trailing LF)",
    "stdout": "pwsh agent.ps1 stdout pipe raw bytes",
    "stderr": "pwsh agent.ps1 stderr pipe raw bytes",
}
CURSOR_EXIT_NOTE = (
    "exit 0 covers the launch lifecycle and a sealed capture only; it is not a "
    "claim that the Cursor model task or any coding work succeeded"
)


def _frozen_manifest_entry(
    task_root: Path, plan: dict[str, object], relative: str
) -> tuple[int, str]:
    """The prepared manifest entry that the verified plan is bound to.

    The plan is addressed by the digest of one exact manifest byte string, so the
    manifest is re-read here and its identity re-checked against that digest
    before any entry is trusted. A swapped manifest can therefore never become
    the source of a frozen entry.
    """
    manifest_path = task_root / "manifest.json"
    _require_plain_file(manifest_path, "task manifest")
    manifest_bytes = manifest_path.read_bytes()
    if _sha256_hex(manifest_bytes) != plan["manifest_sha256"]:
        raise SliceRunError("task manifest no longer matches the verified plan")
    manifest = slice_workspace._parse_manifest(manifest_bytes)
    if manifest.source_commit != plan["source_commit"]:
        raise SliceRunError("task manifest source commit no longer matches the verified plan")
    for file in manifest.files:
        if file.path == relative:
            return file.size, file.sha256
    raise SliceRunError(
        "cursor project config must be a prepared frozen input: work/" + CURSOR_CONFIG_RELATIVE
    )


def _cursor_config(task_root: Path, plan: dict[str, object]) -> dict[str, object]:
    """The project permission config must itself be a prepared frozen input.

    The bytes read here are compared against the manifest entry the verified plan
    is bound to, so a config that changes after the plan was verified cannot
    supply its own new baseline.
    """
    path = task_root / "work" / CURSOR_CONFIG_RELATIVE
    _require_plain_file(path, "cursor project config")
    read_files = plan.get("read_file")
    if not isinstance(read_files, list) or path.as_posix() not in read_files:
        raise SliceRunError(
            "cursor project config must be a prepared frozen input: work/" + CURSOR_CONFIG_RELATIVE
        )
    frozen_size, frozen_sha256 = _frozen_manifest_entry(task_root, plan, CURSOR_CONFIG_RELATIVE)
    payload = path.read_bytes()
    digest = _sha256_hex(payload)
    if len(payload) != frozen_size or digest != frozen_sha256:
        raise SliceRunError(
            "cursor project config differs from the prepared manifest: work/"
            + CURSOR_CONFIG_RELATIVE
        )
    value = decode_strict_json_bytes(payload, label="cursor project config")
    if not isinstance(value, dict):
        raise SliceRunError("cursor project config must be one JSON object")
    return {"path": str(path), "size_bytes": len(payload), "sha256": digest}


def _cursor_inputs(task_root: Path, plan: dict[str, object]) -> dict[str, object]:
    """Read the frozen task note and derive the fixed positional prompt."""
    note_path = task_root / "work" / "TASK.md"
    _require_plain_file(note_path, "task note")
    task_bytes = note_path.read_bytes()
    manifest_path = task_root / "manifest.json"
    _require_plain_file(manifest_path, "task manifest")
    manifest_bytes = manifest_path.read_bytes()
    if _sha256_hex(manifest_bytes) != plan["manifest_sha256"]:
        raise SliceRunError("task manifest changed before capture")
    manifest = decode_strict_json_bytes(manifest_bytes, label="task manifest")
    expected = manifest.get("task_note")
    if (
        not isinstance(expected, dict)
        or expected.get("bytes") != len(task_bytes)
        or expected.get("sha256") != _sha256_hex(task_bytes)
    ):
        raise SliceRunError("task input differs from the frozen manifest")
    prompt_bytes = task_bytes[:-1] if task_bytes.endswith(b"\n") else task_bytes
    try:
        prompt = prompt_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SliceRunError("task note is not UTF-8 text") from error
    return {"task_bytes": task_bytes, "prompt_bytes": prompt_bytes, "prompt": prompt}


def _verify_inputs_unchanged(
    task_root: Path,
    plan: dict[str, object],
    launcher: dict[str, object],
    config: dict[str, object],
    task_bytes: bytes,
) -> None:
    """Refuse any drift of the frozen inputs between capture and launch."""
    if _sha256_file(task_root / "manifest.json") != plan["manifest_sha256"]:
        raise SliceRunError("task manifest drifted before launch")
    if _sha256_file(Path(str(launcher["path"]))) != launcher["sha256"]:
        raise SliceRunError("cursor launcher drifted before launch")
    if _sha256_file(Path(str(config["path"]))) != config["sha256"]:
        raise SliceRunError("cursor project config drifted before launch")
    if _sha256_file(task_root / "work" / "TASK.md") != _sha256_hex(task_bytes):
        raise SliceRunError("task note drifted before launch")


def _cursor_argv(launcher_path: str, workspace: str, prompt: str) -> list[str]:
    return [
        str(_pwsh_path()),
        "-NoProfile",
        "-NonInteractive",
        "-File",
        launcher_path,
        "--workspace",
        workspace,
        "-p",
        "--model",
        CURSOR_MODEL,
        "--output-format",
        "stream-json",
        "--force",
        prompt,
    ]


def command_cursor_run(arguments: argparse.Namespace) -> int:
    try:
        plan = slice_workspace.build_plan(arguments.task_root)
    except slice_workspace.SliceWorkspaceError as error:
        raise SliceRunError(str(error)) from error
    task_root = Path(str(plan["task_root"]))
    launcher = _verify_executable(arguments.exe, arguments.exe_sha256)
    config = _cursor_config(task_root, plan)
    inputs = _cursor_inputs(task_root, plan)
    argv = _cursor_argv(str(launcher["path"]), str(plan["cwd"]), str(inputs["prompt"]))
    run_root = _require_new_run_root(arguments.run_root, task_root)
    plan_bytes = _canonical_json(plan)
    if not arguments.execute:
        _emit_json(
            {
                "schema_version": CURSOR_SCHEMA_VERSION,
                "mode": "preflight",
                "entry": "cursor",
                "execute": False,
                "task_root": str(task_root),
                "run_root_would_create": str(run_root),
                "manifest_sha256": plan["manifest_sha256"],
                "source_commit": plan["source_commit"],
                "launcher": launcher,
                "cursor_config": config,
                "model_requested": CURSOR_MODEL,
                "argv_flags": list(CURSOR_ARGV_FLAGS),
                "fixed_argv_elements": len(argv) - 1,
                "observation": {
                    "timeout_seconds": OBSERVATION_TIMEOUT_SECONDS,
                    "kill_grace_seconds": KILL_GRACE_SECONDS,
                    "capture_join_seconds": CAPTURE_JOIN_SECONDS,
                },
                "execution_authorized": False,
                "provider_calls": 0,
                "cursor_cli_invocations": 0,
                "note": "preflight only: no session write, no configuration change and no process",
            }
        )
        return EXIT_OK
    store = _session_store()
    setup_steps = (
        ("run root creation", run_root.mkdir),
        ("run root protection", lambda: _protect_directory(run_root)),
        (
            "plan receipt write",
            lambda: _write_json_new(
                run_root / "plan.json",
                {
                    "schema_version": CURSOR_SCHEMA_VERSION,
                    "kind": "cursor",
                    "plan_sha256": _sha256_hex(plan_bytes),
                    "manifest_sha256": plan["manifest_sha256"],
                    "source_commit": plan["source_commit"],
                    "model_requested": CURSOR_MODEL,
                    "launcher_sha256": launcher["sha256"],
                    "cursor_config_sha256": config["sha256"],
                    "argv_elements": len(argv) - 1,
                },
            ),
        ),
    )
    for setup_stage, setup_step in setup_steps:
        try:
            setup_step()
        except Exception as error:
            _emit_json(
                {
                    "schema_version": CURSOR_SCHEMA_VERSION,
                    "mode": "execute",
                    "entry": "cursor",
                    "setup_stage": setup_stage,
                    "setup_error": type(error).__name__,
                    "receipt_persisted": False,
                    "exit_code": EXIT_REFUSED,
                    "exit_code_label": EXIT_LABELS[EXIT_REFUSED],
                }
            )
            return EXIT_REFUSED
    try:
        writer = store.start()
        task_ok = writer.append("task", inputs["task_bytes"])
        request_ok = writer.append("request", inputs["prompt_bytes"])
        if not task_ok or not request_ok:
            if writer.incomplete_reason == "over_limit":
                raise StorageError("over_limit: cursor input exceeds session storage budget")
            raise SessionError("cursor encrypted input capture is unavailable")
        _verify_inputs_unchanged(task_root, plan, launcher, config, inputs["task_bytes"])
    except (OSError, StorageError, SessionError, SliceRunError) as error:
        reason = (
            "over_limit"
            if isinstance(error, StorageError) and str(error).startswith("over_limit")
            else "capture_unavailable"
        )
        _emit_json(
            {
                "schema_version": CURSOR_SCHEMA_VERSION,
                "mode": "execute",
                "entry": "cursor",
                "run_root": str(run_root),
                "setup_stage": "cursor session input capture",
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
    launch_record = None
    lifecycle_exception = None
    evidence_write_failures: list[dict[str, str]] = []
    try:
        launch_record = _launch_and_capture(
            argv[0], argv, str(plan["cwd"]), stdout_sink, stderr_sink
        )
    except Exception as error:
        lifecycle_exception = type(error).__name__
    sealed = False
    if launch_record is not None and launch_record.get("capture_state") == "complete":
        try:
            writer.seal(
                {
                    "kind": CURSOR_SESSION_KIND,
                    "model_requested": CURSOR_MODEL,
                    "launcher_path": launcher["path"],
                    "launcher_sha256": launcher["sha256"],
                    "cursor_config_sha256": config["sha256"],
                    "manifest_sha256": plan["manifest_sha256"],
                    "source_commit": plan["source_commit"],
                    "process_exit_code": launch_record.get("exit_code"),
                    "workspace": plan["cwd"],
                    "stream_sources": CURSOR_STREAM_SOURCES,
                }
            )
            sealed = True
        except (OSError, StorageError, SessionError) as error:
            launch_record["capture_state"] = "incomplete"
            launch_record["capture_error"] = type(error).__name__
    if launch_record is None:
        result = "launch_failed"
    elif launch_record.get("timed_out"):
        result = "observation_timeout"
    elif sealed:
        result = "lifecycle_complete_capture_sealed"
    else:
        result = "capture_incomplete"
    receipt = {
        "schema_version": CURSOR_SCHEMA_VERSION,
        "mode": "execute",
        "entry": "cursor",
        "task_root": str(task_root),
        "run_root": str(run_root),
        "manifest_sha256": plan["manifest_sha256"],
        "source_commit": plan["source_commit"],
        "launcher": launcher,
        "cursor_config": config,
        "workspace": plan["cwd"],
        "model_requested": CURSOR_MODEL,
        "argv_flags": list(CURSOR_ARGV_FLAGS),
        "launches": 1 if launch_record is not None else 0,
        "spawn_state": "confirmed" if launch_record is not None else "not_confirmed",
        "launch": launch_record,
        "result": result,
        "session": {
            "session_id": writer.session_id,
            "sealed": writer.sealed,
            "capture_complete": sealed,
            "storage_root": str(store.domain.root),
        },
        "lifecycle_exception": lifecycle_exception,
        "evidence_write_failures": list(evidence_write_failures),
    }
    receipt_persisted = True
    try:
        _write_json_new(run_root / "run.json", receipt)
    except Exception as error:
        receipt_persisted = False
        evidence_write_failures.append({"stage": "run.json", "error": type(error).__name__})
    exit_code = (
        EXIT_OK
        if lifecycle_exception is None
        and launch_record is not None
        and sealed
        and not evidence_write_failures
        else EXIT_LIFECYCLE_FAILED
    )
    _emit_json(
        {
            "schema_version": CURSOR_SCHEMA_VERSION,
            "mode": "execute",
            "entry": "cursor",
            "task_root": str(task_root),
            "run_root": str(run_root),
            "launches": receipt["launches"],
            "spawn_state": receipt["spawn_state"],
            "result": result,
            "process_exit_code": (launch_record or {}).get("exit_code"),
            "session": receipt["session"],
            "lifecycle_exception": lifecycle_exception,
            "evidence_write_failures": list(evidence_write_failures),
            "receipt_persisted": receipt_persisted,
            "exit_code": exit_code,
            "exit_code_label": EXIT_LABELS[exit_code],
            "run_receipt": str(run_root / "run.json") if receipt_persisted else None,
            "note": CURSOR_EXIT_NOTE,
        }
    )
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-agent-bridge cursor",
        description=(
            "One fixed Cursor CLI call with encrypted capture. The launcher path and "
            "its SHA-256 come from the caller; argv, model and output format are fixed."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="preflight (default) or execute one fixed Cursor call")
    run.add_argument("--task-root", required=True)
    run.add_argument("--run-root", required=True)
    run.add_argument("--exe", required=True)
    run.add_argument("--exe-sha256", required=True)
    run.add_argument("--execute", action="store_true")
    run.set_defaults(handler=command_cursor_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        return arguments.handler(arguments)
    except (SliceRunError, SessionKeyError, StorageError, SessionError) as error:
        print("local-agent-bridge: " + str(error), file=sys.stderr)
        return EXIT_REFUSED
