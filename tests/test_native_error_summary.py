"""Synthetic terminal-error projection through the station receipt path."""

from __future__ import annotations

import json

import pytest
import test_station_task as station

from local_agent_bridge.bridge import task_run as runner

CAPACITY_ERROR = (
    "API error (attempt 5): UNAVAILABLE (code 503): "
    "No capacity available for model gemini-3.8-flash-high on the server"
)


class ConversationStream:
    def __init__(self, events):
        self.events = events

    def iter_stream(self, stream):
        assert stream == "stdout"
        return iter([station.fixtures.canonical(event) + b"\n" for event in self.events])


def conversation_events(root, *, result):
    return [
        {
            "event": "init",
            "conversation_id": "conversation-fixed",
            "init": {
                "cwd": str(root),
                "model": runner._ROUTES["agy"]["model"],
                "permission_mode": "synthetic-only",
            },
        },
        {
            "event": "result",
            "result": {"conversation_id": "conversation-fixed", **result},
        },
    ]


@pytest.mark.parametrize(
    "status,error,category",
    [
        ("SUCCESS", None, None),
        ("SUCCESS", CAPACITY_ERROR, "Unknown"),
        ("ERROR", None, "Unknown"),
        ("ERROR", 7, "Unknown"),
        ("ERROR", {"message": CAPACITY_ERROR}, "Unknown"),
        ("ERROR", "ordinary upstream failure", "Unknown"),
        ("ERROR", CAPACITY_ERROR, "ProviderCapacityUnavailable"),
        (
            "ERROR",
            "Bearer SYNTHETIC_TOKEN\nUNAVAILABLE 503 no capacity available",
            "ProviderCapacityUnavailable",
        ),
        ("ERROR", "api-key=SYNTHETIC_TOKEN upstream denied", "Unknown"),
        (
            "ERROR",
            "https://user:pass@example.test?a=SYNTHETIC_TOKEN upstream denied",
            "Unknown",
        ),
        ("ERROR", "line one\r\nBearer SYNTHETIC_TOKEN\r\nline three", "Unknown"),
        pytest.param(
            "ERROR",
            "A" * 100_000 + " " + CAPACITY_ERROR,
            "Unknown",
            id="overlong-prefix-unknown",
        ),
        pytest.param(
            "ERROR",
            CAPACITY_ERROR + " " + "A" * 100_000,
            "ProviderCapacityUnavailable",
            id="capacity-before-overlong-suffix",
        ),
    ],
)
def test_native_error_summary_uses_only_fixed_safe_labels(status, error, category):
    summary = None
    if category == "ProviderCapacityUnavailable":
        summary = runner._NATIVE_CAPACITY_ERROR[1]
    elif category == "Unknown":
        summary = runner._NATIVE_UNKNOWN_ERROR[1]
    assert runner._native_error_summary(status, error) == (category, summary)
    rendered = json.dumps(runner._native_error_summary(status, error))
    assert "SYNTHETIC_TOKEN" not in rendered
    assert "A" * 512 not in rendered


def test_station_conversation_projects_terminal_error_without_source_text(tmp_path):
    result = {
        "status": "ERROR",
        "error": "Bearer SYNTHETIC_TOKEN " + CAPACITY_ERROR,
    }
    events = conversation_events(tmp_path, result=result)
    observation = runner._station_conversation(ConversationStream(events), tmp_path)
    assert observation["status"] == "Observed"
    assert observation["result_status"] == "ERROR"
    assert observation["error_category"] == "ProviderCapacityUnavailable"
    assert observation["error_summary"] == runner._NATIVE_CAPACITY_ERROR[1]
    assert "SYNTHETIC_TOKEN" not in json.dumps(observation)


def test_station_conversation_rejects_duplicate_result_before_error_projection(tmp_path):
    result = {"status": "ERROR", "error": CAPACITY_ERROR}
    events = conversation_events(tmp_path, result=result)
    events.append(events[-1])
    observation = runner._station_conversation(ConversationStream(events), tmp_path)
    assert observation == {"status": "Unknown", "conversation_id": None}


def test_station_conversation_keeps_identity_gate_and_safe_error_projection(tmp_path):
    result = {"status": "ERROR", "error": CAPACITY_ERROR}
    events = conversation_events(tmp_path, result=result)
    events[-1]["result"]["conversation_id"] = "foreign-conversation"
    observation = runner._station_conversation(ConversationStream(events), tmp_path)
    assert observation["status"] == "Mismatch"
    assert observation["result_status"] == "ERROR"
    assert observation["error_category"] == "ProviderCapacityUnavailable"


def test_capacity_error_summary_reaches_dispatch_receipt(tmp_path, monkeypatch):
    case, path, pin, _document, spec = station.configured_stable(tmp_path, monkeypatch)
    diagnostics, business = station.install_stable_host(
        case, monkeypatch, protocol="error", result_error=CAPACITY_ERROR
    )
    outcome = station.dispatch(path, pin, spec, execute=True)
    assert len(diagnostics) == 2 and len(business) == 1
    assert outcome["native_conversation"] == {
        "status": "Observed",
        "conversation_id": business[0]["cid"],
        "cwd": str(business[0]["root"]),
        "model": runner._ROUTES["agy"]["model"],
        "permission_mode": "synthetic-only",
        "result_status": "ERROR",
        "error_category": "ProviderCapacityUnavailable",
        "error_summary": runner._NATIVE_CAPACITY_ERROR[1],
    }
    assert "NativeConversationUnverified" in outcome["run"]["blockers"]
    assert "SYNTHETIC_TOKEN" not in json.dumps(outcome["native_conversation"])
