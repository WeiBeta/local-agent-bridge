"""Native parser/reader faults use synthetic streams and synthetic keys only."""

from __future__ import annotations

import copy
import json

import pytest
from test_shadow_coding_live import case as shadow_case  # noqa: F401
from test_shadow_coding_live import events, live


def raw(stream):
    return b"".join(json.dumps(event).encode() + b"\n" for event in stream)


def truncated_preview(value):
    return value.encode("utf-8")[:512].decode("utf-8") + "…"


@pytest.fixture
def native_fixture(request):
    return events(request.getfixturevalue("shadow_case"))


def test_documented_done_output_with_active_transition(native_fixture):
    stream, commands, summaries = native_fixture
    active = copy.deepcopy(stream[1])
    active["step_update"]["state"] = "ACTIVE"
    active["step_update"]["tool_info"].pop("output")
    complete = active["step_update"]["tool_info"]["parameters"]["CommandLine"]
    active["step_update"]["tool_info"]["parameters"]["CommandLine"] = (
        complete.encode("utf-8")[:512].decode("utf-8") + "…"
    )
    stream.insert(1, active)
    result = live.native.analyze(raw(stream), commands=commands, summaries=summaries)
    assert result["status"] == "CliPublicTestsMatch" and result["origin"] == "CliToolResult"
    assert result["accepted"] is False and result["worker_execution"] == "Unknown"
    assert "argv" not in json.dumps(result) and "CommandLine" not in json.dumps(result)


@pytest.mark.parametrize("second_active", ["shorter-prefix", "different-preview"])
def test_consecutive_active_run_command_parameters_may_update(native_fixture, second_active):
    stream, commands, summaries = native_fixture
    complete = stream[1]["step_update"]["tool_info"]["parameters"]["CommandLine"]
    first = copy.deepcopy(stream[1])
    second = copy.deepcopy(stream[1])
    for event in (first, second):
        event["step_update"]["state"] = "ACTIVE"
        event["step_update"]["tool_info"].pop("output")
    first["step_update"]["tool_info"]["parameters"]["CommandLine"] = (
        complete.encode("utf-8")[:512].decode("utf-8") + "…"
    )
    if second_active == "shorter-prefix":
        second["step_update"]["tool_info"]["parameters"]["CommandLine"] = (
            complete.encode("utf-8")[:313].decode("utf-8") + "…"
        )
    else:
        second["step_update"]["tool_info"]["parameters"]["CommandLine"] += " preview"
    stream[1:1] = [first, second]
    result = live.native.analyze(raw(stream), commands=commands, summaries=summaries)
    assert result["status"] == "CliPublicTestsMatch" and result["accepted"] is False


@pytest.mark.parametrize("literal", ["exact", "prefix_ellipsis", "different"])
def test_provenance_a_uses_final_summaries_not_outer_literal(native_fixture, literal):
    stream, commands, summaries = native_fixture
    expected = {
        "exact": {"match": True, "classification": "exact"},
        "prefix_ellipsis": {"match": False, "classification": "prefix_ellipsis"},
        "different": {"match": False, "classification": "different"},
    }[literal]
    for event in stream[1:3]:
        parameters = event["step_update"]["tool_info"]["parameters"]
        if literal in {"prefix_ellipsis", "different"}:
            parameters["CommandLine"] = truncated_preview(parameters["CommandLine"])
        if literal == "different":
            parameters["CommandLine"] = "synthetic non-literal command"
    result = live.native.analyze(
        raw(stream),
        commands=commands,
        summaries=summaries,
        provenance=live.native.PROVENANCE_FINAL_TOOL_SUMMARY,
    )
    assert result["status"] == "CliBoundPublicResults"
    assert result["basis"] == "FinalToolSummaryAndArtifacts"
    assert result["accepted"] is False and result["worker_execution"] == "Unknown"
    assert set(result["outer_literal_match"]) == {"reproduce", "regression"}
    assert all(value == expected for value in result["outer_literal_match"].values())


def test_provenance_a_rejects_model_self_report_and_missing_summary(native_fixture):
    stream, commands, summaries = native_fixture
    output = stream[2]["step_update"]["tool_info"].pop("output")
    stream[-1]["result"]["response"] = output
    result = live.native.analyze(
        raw(stream),
        commands=commands,
        summaries=summaries,
        provenance=live.native.PROVENANCE_FINAL_TOOL_SUMMARY,
    )
    assert result["status"] == "Unknown"
    assert result["error_code"] == "PhaseEvidenceMissingOrOrder"


@pytest.mark.parametrize(
    ("command", "output", "strict_status"),
    [
        (
            "Get-Content -LiteralPath synthetic/tool.py",
            "synthetic ordinary file content",
            live.native.STRICT_STATUS,
        ),
        (
            "Get-Content -LiteralPath synthetic/shadow_worker_tests.py",
            "synthetic wrapper source text",
            "Unknown",
        ),
        ("git status --short", "", live.native.STRICT_STATUS),
        ("python -c 'print(1)'", "1", live.native.STRICT_STATUS),
    ],
)
def test_provenance_a_allows_ordinary_auxiliary_commands_without_marker(
    native_fixture,
    command,
    output,
    strict_status,
):
    stream, commands, summaries = native_fixture
    stream.insert(
        2,
        {
            "event": "step_update",
            "step_update": {
                "conversation_id": "native-fixture",
                "step_index": 20,
                "state": "DONE",
                "step_type": "tool",
                "tool_name": "run_command",
                "tool_info": {
                    "name": "run_command",
                    "parameters": {"CommandLine": command},
                    "output": output,
                },
            },
        },
    )
    strict = live.native.analyze(raw(stream), commands=commands, summaries=summaries)
    artifacts = live.native.analyze(
        raw(stream),
        commands=commands,
        summaries=summaries,
        provenance=live.native.PROVENANCE_FINAL_TOOL_SUMMARY,
    )
    assert strict["status"] == strict_status
    assert artifacts["status"] == live.native.ARTIFACT_STATUS
    assert set(artifacts["outer_literal_match"]) == {"reproduce", "regression"}


def test_provenance_a_still_rejects_failed_auxiliary_command(native_fixture):
    stream, commands, summaries = native_fixture
    stream.insert(
        2,
        {
            "event": "step_update",
            "step_update": {
                "conversation_id": "native-fixture",
                "step_index": 20,
                "state": "DONE",
                "step_type": "tool",
                "tool_name": "run_command",
                "tool_info": {
                    "name": "run_command",
                    "parameters": {"CommandLine": "Get-Content -LiteralPath synthetic/tool.py"},
                    "error": {"type": "ExecutionError", "message": "synthetic"},
                },
            },
        },
    )
    result = live.native.analyze(
        raw(stream),
        commands=commands,
        summaries=summaries,
        provenance=live.native.PROVENANCE_FINAL_TOOL_SUMMARY,
    )
    assert result["status"] == "Unknown" and result["error_code"] == "DuplicateOrFailedTool"


def test_provenance_a_rejects_malformed_marker_output(native_fixture):
    stream, commands, summaries = native_fixture
    stream.insert(
        2,
        {
            "event": "step_update",
            "step_update": {
                "conversation_id": "native-fixture",
                "step_index": 20,
                "state": "DONE",
                "step_type": "tool",
                "tool_name": "run_command",
                "tool_info": {
                    "name": "run_command",
                    "parameters": {"CommandLine": "Get-Content -LiteralPath synthetic/tool.py"},
                    "output": live.wrapper.PREFIX + "not-json",
                },
            },
        },
    )
    result = live.native.analyze(
        raw(stream),
        commands=commands,
        summaries=summaries,
        provenance=live.native.PROVENANCE_FINAL_TOOL_SUMMARY,
    )
    assert result["status"] == "Unknown"
    assert result["error_code"] in {"SummaryMissingOrAmbiguous", "MalformedJson"}


@pytest.mark.parametrize(
    "problem",
    [
        "wrong_case",
        "wrong_phase",
        "wrong_source",
        "missing_regression",
        "duplicate_phase",
        "tool_error",
        "failed_result",
    ],
)
def test_provenance_a_keeps_summary_event_and_artifact_gates(native_fixture, problem):
    stream, commands, summaries = native_fixture
    tool = stream[1]["step_update"]
    if problem == "wrong_case":
        summary = json.loads(tool["tool_info"]["output"][len(live.wrapper.PREFIX) :])
        outcomes = summary["case_outcomes"]
        outcomes[sorted(live.wrapper.BASELINE_ERRORS)[0]] = "pass"
        tool["tool_info"]["output"] = live.wrapper.PREFIX + json.dumps(summary)
    elif problem in {"wrong_phase", "wrong_source"}:
        summary = json.loads(tool["tool_info"]["output"][len(live.wrapper.PREFIX) :])
        summary["phase" if problem == "wrong_phase" else "source_tree_sha256"] = (
            "regression" if problem == "wrong_phase" else "f" * 64
        )
        tool["tool_info"]["output"] = live.wrapper.PREFIX + json.dumps(summary)
    elif problem == "missing_regression":
        stream.pop(2)
    elif problem == "duplicate_phase":
        stream[2]["step_update"]["tool_info"]["output"] = tool["tool_info"]["output"]
    elif problem == "tool_error":
        tool["tool_info"]["error"] = {"type": "failure", "message": "synthetic"}
    else:
        stream[-1]["result"]["status"] = "ERROR"
    result = live.native.analyze(
        raw(stream),
        commands=commands,
        summaries=summaries,
        provenance=live.native.PROVENANCE_FINAL_TOOL_SUMMARY,
    )
    assert result["status"] == "Unknown" and result["accepted"] is False
    assert result["worker_execution"] == "Unknown" and result.get("error_code")


def test_invalid_provenance_is_rejected_before_stream_parsing(native_fixture):
    stream, commands, summaries = native_fixture
    result = live.native.analyze(
        raw(stream), commands=commands, summaries=summaries, provenance="invalid"
    )
    assert result["status"] == "Unknown" and result["error_code"] == "ProvenanceInvalid"


@pytest.mark.parametrize("problem", ["missing", "wrong_status", "wrong_name", "polluted_expected"])
def test_per_case_status_and_exact_error_distribution(native_fixture, problem):
    stream, commands, summaries = native_fixture
    info = stream[1]["step_update"]["tool_info"]
    summary = json.loads(info["output"][len(live.wrapper.PREFIX) :])
    outcomes = summary["case_outcomes"]
    if problem == "missing":
        summary.pop("case_outcomes")
    elif problem == "wrong_status":
        outcomes[sorted(live.wrapper.BASELINE_ERRORS)[0]] = "failure"
    elif problem == "wrong_name":
        outcomes["public_tests.ForeignCase"] = outcomes.pop(sorted(outcomes)[0])
    else:
        error_name = sorted(live.wrapper.BASELINE_ERRORS)[0]
        pass_name = sorted(set(live.wrapper.CASES) - live.wrapper.BASELINE_ERRORS)[0]
        outcomes[error_name], outcomes[pass_name] = "pass", "error"
        summaries["reproduce"]["case_outcomes"] = copy.deepcopy(outcomes)
    info["output"] = live.wrapper.PREFIX + json.dumps(summary)
    result = live.native.analyze(raw(stream), commands=commands, summaries=summaries)
    assert result["status"] == "Unknown" and result["accepted"] is False


@pytest.mark.parametrize(
    "problem",
    [
        "no_init",
        "duplicate_init",
        "no_result",
        "failed_result",
        "wrong_uid",
        "missing_output",
        "tool_error",
        "active_only",
        "duplicate_done",
        "duplicate_phase",
        "reversed",
        "step_index_regression",
        "identity_conflict_tool",
        "identity_conflict_info_name",
        "identity_conflict_step_type",
        "unbound_command",
        "unbound_command_with_error",
        "done_truncated",
        "unknown_tool",
        "bool_step",
        "missing_case",
        "bool_count",
        "wrong_source",
        "wrong_python",
        "wrong_phase",
        "wrong_recipe",
        "wrong_exit",
        "wrong_report",
        "multiple_summaries",
        "model_only",
        "incomplete_other_step",
        "time_order",
        "byte_limit",
        "line_limit",
        "truncated",
        "duplicate_key",
        "depth",
        "nan",
    ],
)
def test_gaps_conflicts_and_bounds_never_pass(native_fixture, problem):
    stream, commands, summaries = native_fixture
    tool = stream[1]["step_update"]
    if problem == "no_init":
        stream.pop(0)
    elif problem == "duplicate_init":
        stream.insert(1, copy.deepcopy(stream[0]))
    elif problem == "no_result":
        stream.pop()
    elif problem == "failed_result":
        stream[-1]["result"]["status"] = "ERROR"
    elif problem == "wrong_uid":
        tool["conversation_id"] = "other"
    elif problem == "missing_output":
        tool["tool_info"].pop("output")
    elif problem == "tool_error":
        tool["tool_info"]["error"] = {"type": "failure", "message": "synthetic"}
    elif problem == "active_only":
        tool["state"] = "ACTIVE"
    elif problem == "duplicate_done":
        stream.insert(2, copy.deepcopy(stream[1]))
    elif problem == "duplicate_phase":
        event = copy.deepcopy(stream[1])
        event["step_update"]["step_index"] = 10
        stream.insert(2, event)
    elif problem == "reversed":
        stream[1], stream[2] = stream[2], stream[1]
    elif problem == "step_index_regression":
        stream[1]["step_update"]["step_index"] = 5
    elif problem in {
        "identity_conflict_tool",
        "identity_conflict_info_name",
        "identity_conflict_step_type",
    }:
        event = copy.deepcopy(stream[1])
        event["step_update"]["state"] = "ACTIVE"
        if problem == "identity_conflict_tool":
            event["step_update"]["tool_name"] = "read_command"
        elif problem == "identity_conflict_info_name":
            event["step_update"]["tool_info"]["name"] = "read_command"
        else:
            event["step_update"]["step_type"] = "agent_response"
        stream.insert(1, event)
    elif problem == "unbound_command":
        tool["tool_info"]["parameters"]["CommandLine"] += "; echo fake"
    elif problem == "unbound_command_with_error":
        tool["tool_info"]["parameters"]["CommandLine"] += "; echo fake"
        tool["tool_info"]["error"] = {"type": "failure", "message": "synthetic"}
    elif problem == "done_truncated":
        complete = tool["tool_info"]["parameters"]["CommandLine"]
        tool["tool_info"]["parameters"]["CommandLine"] = (
            complete.encode("utf-8")[:512].decode("utf-8") + "…"
        )
    elif problem == "unknown_tool":
        tool["tool_name"] = "other"
    elif problem == "bool_step":
        tool["step_index"] = True
    elif problem in {
        "missing_case",
        "bool_count",
        "wrong_source",
        "wrong_python",
        "wrong_phase",
        "wrong_recipe",
        "wrong_exit",
        "wrong_report",
        "time_order",
    }:
        value = json.loads(tool["tool_info"]["output"][len(live.wrapper.PREFIX) :])
        if problem == "missing_case":
            value["case_ids"].pop()
        elif problem == "bool_count":
            value["failures"] = False
        elif problem == "wrong_phase":
            value["phase"] = "regression"
        elif problem == "wrong_exit":
            value["exit_code"] = 0
        elif problem == "time_order":
            value["end_utc"] = "2026-10-11T00:00:09+00:00"
        else:
            key = {
                "wrong_source": "source_tree_sha256",
                "wrong_python": "python_sha256",
                "wrong_recipe": "recipe_sha256",
                "wrong_report": "report_sha256",
            }[problem]
            value[key] = "f" * 64
        tool["tool_info"]["output"] = live.wrapper.PREFIX + json.dumps(value)
    elif problem == "multiple_summaries":
        tool["tool_info"]["output"] *= 2
    elif problem == "model_only":
        stream[-1]["result"]["response"] = tool["tool_info"].pop("output")
    elif problem == "incomplete_other_step":
        stream.insert(
            3,
            {
                "event": "step_update",
                "step_update": {
                    "conversation_id": "native-fixture",
                    "step_index": 20,
                    "step_type": "agent_response",
                    "state": "ACTIVE",
                },
            },
        )
    data = raw(stream)
    if problem == "byte_limit":
        data = b" " * (live.native.bounded.MAX_BYTES + 1)
    elif problem == "line_limit":
        data = b" " * (live.native.bounded.MAX_LINE + 1) + b"\n"
    elif problem == "truncated":
        data = data[:-1]
    elif problem == "duplicate_key":
        data = b'{"event":"init","event":"result"}\n'
    elif problem == "depth":
        data = b'{"nested":' + b"[" * 17 + b"0" + b"]" * 17 + b"}\n"
    elif problem == "nan":
        data = b'{"event":"init","v":NaN}\n'
    result = live.native.analyze(data, commands=commands, summaries=summaries)
    assert result["status"] == "Unknown" and result["accepted"] is False
    assert result["worker_execution"] == "Unknown" and result.get("error_code")
    if problem == "unbound_command_with_error":
        assert result["error_code"] == "UnboundWrapperCommand"


@pytest.mark.parametrize(
    "fault", ["wrong_key", "cipher_mutation", "key_interrupt", "key_exit", "missing_frame"]
)
def test_one_reader_attempt_retained_without_retry(native_fixture, tmp_path, fault):
    stream, commands, summaries = native_fixture
    store = live.task_run.slice_run.SessionStore(bytes(range(32)), root=tmp_path / "sessions")
    writer = store.start()
    writer.append("stdout", raw(stream))
    writer.seal({})
    output = tmp_path / "reader"
    reads = []
    original = KeyboardInterrupt() if fault == "key_interrupt" else SystemExit(39)

    def key():
        reads.append(1)
        if fault in {"key_interrupt", "key_exit"}:
            raise original
        return b"x" * 32 if fault == "wrong_key" else bytes(range(32))

    if fault in {"cipher_mutation", "missing_frame"}:
        path = writer.path / "stdout.enc"
        value = path.read_bytes()
        path.write_bytes(
            value[:-1] if fault == "missing_frame" else value[:-1] + bytes([value[-1] ^ 1])
        )
    with pytest.raises((live.native.bounded.Refused, KeyboardInterrupt, SystemExit)) as caught:
        live.native.read_capture_once(
            bundle=writer.path,
            uid=writer.session_id,
            output=output,
            commands=commands,
            summaries=summaries,
            key_loader=key,
        )
    if fault in {"key_interrupt", "key_exit"}:
        assert caught.value is original
    assert (output / "attempt.consumed.json").exists() and (output / "failure.json").exists()
    assert len(reads) == (0 if fault in {"cipher_mutation", "missing_frame"} else 1)
    with pytest.raises(FileExistsError):
        live.native.read_capture_once(
            bundle=writer.path,
            uid=writer.session_id,
            output=output,
            commands=commands,
            summaries=summaries,
            key_loader=key,
        )
    assert len(reads) <= 1
