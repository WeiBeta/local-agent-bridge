"""Bounded native agy tool results, with CLI provenance and no OS attestation."""

from __future__ import annotations

import contextlib
import hashlib
from datetime import datetime
from pathlib import Path
from uuid import UUID

import agy_stdout_reanalysis as bounded
import shadow_worker_tests as wrapper

from local_agent_bridge.bridge import task_run


def command_line(argv: list[str]) -> str:
    """One frozen PowerShell invocation; never interpret incoming shell text."""
    return "& " + " ".join("'" + item.replace("'", "''") + "'" for item in argv)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise bounded.Refused(code)


def _summary(output: object, expected: dict) -> dict:
    _require(type(output) is str and len(output.encode()) <= 16384, "ToolOutputMissingOrLarge")
    text = output.rstrip("\r\n")
    _require(
        text.startswith(wrapper.PREFIX) and "\n" not in text and "\r" not in text,
        "SummaryMissingOrAmbiguous",
    )
    value = bounded._json(text[len(wrapper.PREFIX) :].encode())
    _require(
        task_run.contract.deep_equal_strict(
            value.get("case_outcomes"), wrapper.expected_outcomes(expected["phase"])
        ),
        "CaseOutcomesChanged",
    )
    keys = set(expected) | {"start_utc", "end_utc", "report_sha256"}
    _require(set(value) == keys, "SummaryShapeMismatch")
    for key, item in expected.items():
        _require(task_run.contract.deep_equal_strict(value[key], item), "SummaryBindingMismatch")
    task_run._hash(value["report_sha256"])
    started, ended = (datetime.fromisoformat(value[key]) for key in ("start_utc", "end_utc"))
    _require(
        started.utcoffset() is not None and ended.utcoffset() is not None and started <= ended,
        "SummaryTimeInvalid",
    )
    return value


def analyze(plaintext: bytes, *, commands: dict, summaries: dict) -> dict:
    """Only fixed completed tool calls count; any gap yields Unknown, never Pass."""
    result = {
        "status": "Unknown",
        "origin": "CliToolResult",
        "worker_execution": "Unknown",
        "accepted": False,
        "phases": {},
    }
    try:
        _require(
            type(plaintext) is bytes and len(plaintext) <= bounded.MAX_BYTES, "StreamByteLimit"
        )
        _require(set(commands) == set(summaries) == {"reproduce", "regression"}, "ExpectationShape")
        lines = plaintext.splitlines()
        _require(
            0 < len(lines) <= bounded.MAX_LINES and plaintext.endswith(b"\n"),
            "IncompleteOrLargeStream",
        )
        _require(all(0 < len(line) <= bounded.MAX_LINE for line in lines), "LineByteLimit")
        conversation = None
        terminal = False
        seen = {}
        selected = []
        selected_steps = []
        facts = {}
        for line in lines:
            event = bounded._json(line)
            kind = event.get("event")
            _require(not terminal and kind in bounded.EVENTS, "EventOrderOrType")
            if kind == "init":
                _require(conversation is None and not seen, "DuplicateInit")
                conversation = event.get("conversation_id")
                _require(
                    type(conversation) is str and 0 < len(conversation) <= 128,
                    "ConversationInvalid",
                )
                _require(type(event.get("init")) is dict, "InitMissing")
                continue
            _require(conversation is not None, "InitMissing")
            payload = event.get(kind)
            _require(
                type(payload) is dict and payload.get("conversation_id") == conversation,
                "ConversationMismatch",
            )
            if kind == "result":
                _require(payload.get("status") == "SUCCESS", "CliTerminalFailure")
                terminal = True
                continue
            index, state = payload.get("step_index"), payload.get("state")
            _require(
                type(index) is int and 0 <= index < bounded.MAX_STEPS and state in bounded.STATES,
                "StepShape",
            )
            _require(payload.get("step_type") in bounded.STEP_TYPES, "StepTypeUnknown")
            previous = seen.get(index)
            _require(previous is None or previous["state"] != "DONE", "DuplicateOrRegressedStep")
            info = payload.get("tool_info", {})
            _require(type(info) is dict, "ToolInfoShape")
            is_run_command = (
                payload.get("step_type") == "tool"
                and payload.get("tool_name") == "run_command"
                and info.get("name") == "run_command"
            )
            declared = (
                payload.get("step_type"),
                payload.get("tool_name"),
                info.get("name"),
                # ACTIVE run_command parameters are a preview and may be updated
                # by the completed event. Other tools retain exact declarations.
                None if is_run_command else info.get("parameters"),
            )
            _require(previous is None or previous["declared"] == declared, "ConflictingStep")
            seen[index] = {"state": state, "declared": declared}
            if payload.get("step_type") != "tool":
                continue
            if payload.get("tool_name") != "run_command" or info.get("name") != "run_command":
                continue
            parameters = info.get("parameters")
            _require(type(parameters) is dict, "ParametersMissing")
            command = parameters.get("CommandLine")
            _require(type(command) is str, "CommandMissing")
            if state != "DONE":
                continue
            matches = [phase for phase, frozen in commands.items() if command == frozen]
            if not matches:
                _require("shadow_worker_tests.py" not in command, "UnboundWrapperCommand")
                continue
            phase = matches[0]
            _require(
                len(matches) == 1 and phase not in facts and "error" not in info,
                "DuplicateOrFailedTool",
            )
            facts[phase] = _summary(info.get("output"), summaries[phase])
            selected.append(phase)
            selected_steps.append(index)
        _require(
            terminal and selected == ["reproduce", "regression"], "PhaseEvidenceMissingOrOrder"
        )
        _require(selected_steps[0] < selected_steps[1], "PhaseStepOrderConflict")
        _require(all(item["state"] == "DONE" for item in seen.values()), "IncompleteStep")
        _require(
            datetime.fromisoformat(facts["reproduce"]["end_utc"])
            <= datetime.fromisoformat(facts["regression"]["start_utc"]),
            "PhaseTimeOrder",
        )
        result.update(
            status="CliPublicTestsMatch",
            conversation_id=conversation,
            phases={
                phase: {
                    "summary_sha256": bounded._sha(bounded._canonical(fact)),
                    "report_sha256": fact["report_sha256"],
                    "exit_code": fact["exit_code"],
                    "tests": fact["tests"],
                    "errors": fact["errors"],
                    "source_tree_sha256": fact["source_tree_sha256"],
                }
                for phase, fact in facts.items()
            },
        )
    except Exception as error:
        result["error_code"] = (
            str(error) if isinstance(error, bounded.Refused) else type(error).__name__
        )
    return result


def read_capture_once(
    *, bundle: Path, uid: str, output: Path, commands: dict, summaries: dict, key_loader
) -> dict:
    """One key load and one stdout authentication; no plaintext export or retry.

    Reuse the existing sealed-stdout byte reader/authenticator, without its old
    task/UID-specific executable or recipe parser. The caller binds the bundle
    under this invocation's isolated LOCALAPPDATA and saved lifecycle UID.
    """
    _require(str(UUID(uid)) == uid and bundle.name == uid, "CaptureUidInvalid")
    task_run._absolute(output)
    output.mkdir(exist_ok=False)
    task_run._persist(
        output / "attempt.consumed.json",
        {"key_read_cap": 1, "stdout_authentication_cap": 1, "retry": False},
    )
    raw = {}
    key = plaintext = None
    try:
        bounded._plain_file(bundle / "seal.json")
        _require((bundle / "seal.json").stat().st_size <= bounded.MAX_BYTES, "SealByteLimit")
        seal_raw = task_run.read_host_input_bytes(path=str(bundle / "seal.json"))
        seal = bounded._json(seal_raw)
        manifest = seal.get("manifest")
        _require(type(manifest) is dict, "ManifestMissing")
        files = manifest.get("files")
        streams = manifest.get("streams")
        _require(
            type(files) is dict and type(streams) is dict and type(streams.get("stdout")) is dict,
            "StreamBindingMissing",
        )
        config = {
            "uid": uid,
            "manifest_sha256": bounded._sha(bounded._canonical(manifest)),
            "files": files,
            "plaintext": streams["stdout"],
        }
        raw = {
            "seal.json": seal_raw,
            **{
                name: bounded._read_bound(bundle / name, files[name])
                for name in ("open.json", "stdout.enc")
            },
        }
        key = key_loader()
        plaintext = bounded._authenticate(raw, key, config)
        result = analyze(plaintext, commands=commands, summaries=summaries)
        result.update(
            capture_uid=uid,
            seal_sha256=hashlib.sha256(seal_raw).hexdigest(),
            plaintext_sha256=bounded._sha(plaintext),
            plaintext_bytes=len(plaintext),
        )
        task_run._persist(output / "result.json", result)
        return result
    except BaseException as error:
        with contextlib.suppress(BaseException):
            task_run._persist(output / "failure.json", {"exception_type": type(error).__name__})
        raise
    finally:
        raw.clear()
        key = plaintext = None  # No claim of Python memory zeroization.
