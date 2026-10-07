"""Five fixed Task commands over the existing A/B/C public APIs."""

from __future__ import annotations

import argparse
import json
import sys

from local_agent_bridge.bridge import contract, task_input, task_run, task_workspace

_FIELDS = {
    "import": {"source", "policy", "snapshot_root"},
    "prepare": {"snapshot_root", "task_manifest_path", "task_note_path", "task_root"},
    "plan": {"task_root", "host"},
    "run": {"task_root", "run_root"},
    "collect": {"task_root", "run_root", "result_root"},
}
_TRUSTED_COMMANDS = {"prepare", "plan", "run"}


class TaskCliError(ValueError):
    """Fixed CLI diagnosis without the rejected input or exception text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise TaskCliError("CliArgumentsInvalid")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="local-agent-bridge task", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in _FIELDS:
        child = commands.add_parser(command, allow_abbrev=False)
        child.add_argument("--spec", required=True, help="absolute path to the fixed v1 JSON spec")
        if command in _TRUSTED_COMMANDS:
            child.add_argument("--trusted-control-root", required=True)
            child.add_argument("--trusted-inputs-sha256", required=True)
        if command == "run":
            child.add_argument(
                "--execute", action="store_true", help="launch once after all C gates"
            )
    return parser


def _check_arguments(arguments: list[str]) -> None:
    seen = set()
    for token in arguments:
        if token.startswith("-"):
            flag = token.split("=", 1)[0]
            if flag == "-h":
                flag = "--help"
            if flag in seen:
                raise TaskCliError("CliArgumentsInvalid")
            seen.add(flag)
    if "--help" in seen and not (
        arguments in (["--help"], ["-h"])
        or (len(arguments) == 2 and arguments[0] in _FIELDS and arguments[1] in {"-h", "--help"})
    ):
        raise TaskCliError("CliArgumentsInvalid")


def _read_json(path: str) -> object:
    return contract.decode_strict_json_bytes(
        task_run.read_host_input_bytes(path=path), label="Task CLI input"
    )


def _spec(command: str, path: str) -> dict:
    value = _read_json(path)
    if (
        type(value) is not dict
        or set(value) != _FIELDS[command] | {"cli_contract_version"}
        or type(value["cli_contract_version"]) is not int
        or value["cli_contract_version"] != 1
    ):
        raise TaskCliError("CliSpecInvalid")
    for field in _FIELDS[command]:
        item = value[field]
        if field in {"source", "policy"}:
            if type(item) is not dict:
                raise TaskCliError("CliSpecInvalid")
        elif field == "host":
            if type(item) is not str or item not in {"agy", "cursor"}:
                raise TaskCliError("CliSpecInvalid")
        elif not (command == "collect" and field == "run_root" and item is None):
            value[field] = task_run.checked_host_path(path=item)
    return value


def _dispatch(options: argparse.Namespace, spec: dict) -> dict:
    command = options.command
    if command == "import":
        return task_input.import_snapshot(
            source=spec["source"], policy=spec["policy"], snapshot_root=spec["snapshot_root"]
        )
    if command == "collect":
        return task_workspace.collect_task(
            task_root=spec["task_root"], run_root=spec["run_root"], result_root=spec["result_root"]
        )
    trusted_root = task_run.checked_host_path(path=options.trusted_control_root)
    expected = options.trusted_inputs_sha256
    if command == "prepare":
        bundle = task_run.load_trusted_inputs(
            trusted_control_root=trusted_root,
            trusted_inputs_sha256=expected,
            task_root=spec["task_root"],
            snapshot_root=spec["snapshot_root"],
        )
        return task_workspace.prepare_task(
            snapshot_root=spec["snapshot_root"],
            task_manifest=_read_json(str(spec["task_manifest_path"])),
            task_note=task_run.read_host_input_bytes(path=str(spec["task_note_path"])),
            deployment_profile=bundle["deployment_profile"],
            authorization=bundle["authorization"],
            task_root=spec["task_root"],
        )
    if command == "plan":
        if spec["host"] == "cursor":
            task_run.prepare_cursor_project(
                task_root=spec["task_root"],
                trusted_control_root=trusted_root,
                trusted_inputs_sha256=expected,
            )
        return task_run.plan_task(
            task_root=spec["task_root"],
            host=spec["host"],
            trusted_control_root=trusted_root,
            trusted_inputs_sha256=expected,
        )
    return task_run.run_task(
        task_root=spec["task_root"],
        plan=_read_json(str(spec["task_root"] / "control" / "plan.json")),
        run_root=spec["run_root"],
        trusted_control_root=trusted_root,
        trusted_inputs_sha256=expected,
        execute=options.execute,
    )


def _exit_code(command: str, result: dict, *, execute: bool) -> int:
    if command == "plan":
        return 0 if result["preflight_status"] == "Ready" else 2
    if command == "collect":
        return (
            2 if result["blockers"] or result["host_observations"]["scope_status"] == "Fail" else 0
        )
    if command == "run":
        if result["blockers"]:
            return 2
        if not execute and result["transport_state"] == "NotRun" and result["launch_count"] == 0:
            return 0
        return (
            0
            if result["transport_state"] == "Completed"
            and result["launch_count"] == 1
            and result["capture_state"] == "Sealed"
            and result["restore_state"] in {"Unchanged", "Restored"}
            else 2
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Keep business receipts intact, map errors without disclosing input text."""
    try:
        arguments = list(sys.argv[1:] if argv is None else argv)
        _check_arguments(arguments)
        try:
            options = _parser().parse_args(arguments)
        except SystemExit as error:
            return int(error.code)
        result = _dispatch(options, _spec(options.command, options.spec))
        code = _exit_code(options.command, result, execute=getattr(options, "execute", False))
        raw = json.dumps(
            result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        sys.stdout.buffer.write(raw + b"\n")
        return code
    except KeyboardInterrupt:
        code, status = "Interrupted", 130
    except (
        TaskCliError,
        task_input.TaskInputError,
        task_workspace.TaskWorkspaceError,
        task_run.TaskRunError,
    ) as error:
        code, status = error.code, 2
    except contract.BridgeContractError:
        code, status = "CliSpecInvalid", 2
    except Exception:
        code, status = "CliInternalError", 2
    print(f"local-agent-bridge task: {code}", file=sys.stderr)
    return status
