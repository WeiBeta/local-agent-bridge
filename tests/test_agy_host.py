"""R03-R05/R07-R08/R10: RAM-only diagnostics through the existing fake Job channel."""

from __future__ import annotations

import copy
import io
import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import test_task_run as fixtures

from local_agent_bridge.bridge import agy_host as host
from local_agent_bridge.bridge import slice_run

HELP = b"""Options:
  -p, --project <id>              Project
  --print <prompt>               Print
  --model <model>                Model
  --effort <level>               Effort
  --output-format <format>       Format
  --disable-slash-commands       Disable
  --print-timeout <duration>     Timeout
"""


def entry_fixture(tmp_path):
    root = tmp_path / "installation"
    root.mkdir()
    entry = root / "agy.exe"
    entry.write_bytes(b"synthetic never executed")
    return {"path": str(entry), "install_root": str(root), "identity_mode": "StableInstalledEntry"}


def probe_host(monkeypatch, *, version=b"1.3.4\n", help_text=HELP, fault=None):
    calls = []

    class Process(fixtures.FakeProcess):
        def close_job(self):
            return None if fault == "cleanup_unknown" else True

    def spawn(argv, cwd, *, lifecycle, env):
        assert len(argv) == 2 and argv[1] in {"--version", "--help"}
        assert env["AGY_CLI_DISABLE_AUTO_UPDATE"] == "true"
        assert all(flag not in argv for flag in ("--model", "--project", "--print"))
        calls.append((argv, lifecycle, cwd))
        lifecycle.pid = 1234
        lifecycle.pid_created_filetime = 999
        lifecycle.execution_state = "unknown" if fault == "resume_unknown" else "confirmed"
        if fault == "resume_unknown":
            lifecycle.stage = "resume_call"
            lifecycle.child_exit_observed = lifecycle.pipes_closed = lifecycle.job_closed = True
            raise RuntimeError("SECRET-SENTINEL")
        if fault == "interrupt":
            lifecycle.child_exit_observed = lifecycle.pipes_closed = lifecycle.job_closed = True
            raise KeyboardInterrupt("primary")
        process = Process(
            exit_code=1 if fault == "exit" else 0,
            wait_error=subprocess.TimeoutExpired(argv, 10) if fault == "timeout" else None,
        )
        process.stdout = io.BytesIO(
            (version() if callable(version) else version) if argv[1] == "--version" else help_text
        )
        process.stderr = io.BytesIO(b"SECRET-SENTINEL")
        return process

    monkeypatch.setattr(slice_run, "spawn_suspended_in_job", spawn)
    return calls


def observe(tmp_path, monkeypatch, **kwargs):
    spec = entry_fixture(tmp_path)
    calls = probe_host(monkeypatch, **kwargs)
    value = host.new_observation("task", "a" * 64)
    host.observe(spec, tmp_path, host.time.monotonic() + 30, value)
    host.validate_observation(value, "task", "a" * 64, spec["path"])
    assert "SECRET-SENTINEL" not in json.dumps(value)
    return value, calls, spec


def test_r04_shared_launcher_ram_shape_child_environment_and_budget(tmp_path, monkeypatch):
    before = dict(os.environ)
    monkeypatch.setattr(host.time, "monotonic", lambda: 100)
    actual = slice_run._launch_and_capture
    timeouts = []

    def launcher(*args, **kwargs):
        timeouts.append(kwargs["timeout_seconds"])
        return actual(*args, **kwargs)

    monkeypatch.setattr(slice_run, "_launch_and_capture", launcher)
    value, calls, _ = observe(tmp_path, monkeypatch)
    assert value["compatibility"]["state"] == "Supported"
    assert [call[0][1] for call in calls] == ["--version", "--help"]
    assert calls[0][1] is not calls[1][1]
    assert timeouts == [10, 10] and dict(os.environ) == before
    output = host._RamOutput(8192)
    left, right = host._RamStream(output), host._RamStream(output)
    assert left.append(b"x" * 4096) and right.append(b"y" * 4096)
    assert not right.append(b"z") and left.stat().st_size == 4096
    assert len(left.sha256) == 64 and output.kept == 8192


@pytest.mark.parametrize("name,limit", [("version", 8192), ("help_text", 262144)])
def test_r04_combined_output_boundaries(tmp_path, monkeypatch, name, limit):
    # stderr shares the cap; exact-limit stdout cannot bypass the combined budget.
    value, calls, _ = observe(tmp_path, monkeypatch, **{name: b"x" * limit})
    assert value["compatibility"]["reason"] == "ProbeOutputTruncated"
    assert len(calls) == (1 if name == "version" else 2)


@pytest.mark.parametrize("version", [b"1.8.27\n", b"agy v2.0.0\n", b"Antigravity CLI 7.2.13\n"])
def test_r01_version_normalization_without_banner_or_version_pin(tmp_path, monkeypatch, version):
    value, calls, _ = observe(tmp_path, monkeypatch, version=version)
    assert value["compatibility"]["state"] == "Supported" and len(calls) == 2
    assert re.fullmatch(host._VERSION, value["reported_version"])


@pytest.mark.parametrize("version", [b"unknown\n", b"version 1.3.4 backend 2.1.0\n"])
def test_r05_unparseable_version_stops_help(tmp_path, monkeypatch, version):
    value, calls, _ = observe(tmp_path, monkeypatch, version=version)
    assert value["compatibility"]["reason"] == "VersionProbeFailed" and len(calls) == 1


@pytest.mark.parametrize(
    "text",
    [
        HELP,
        b"  --extra <anything> Added\n" + b"\n".join(reversed(HELP.splitlines()[1:])),
        HELP.replace(
            b"<format>       Format", b"\n       <format> Description\n        more description"
        ),
        HELP.replace(b"<level>", b"<low|high>").replace(b"<format>", b"<json|stream-json>"),
        HELP.replace(b"<level>", b"<level> (choices: low, high)"),
        HELP.replace(
            b"<level>               Effort",
            b"<level>               Effort (choices: low,\n"
            b"                                 medium, high)",
        ),
        HELP.replace(b"--model <model>", b"--model, -m <name>"),
    ],
)
def test_r05_help_projection_tolerates_layout_and_new_options(text):
    assert host.missing_flags(text) == []


@pytest.mark.parametrize("flag", host.REQUIRED_FLAGS)
def test_r05_each_required_parameter_missing(flag):
    text = b"\n".join(
        line
        for line in HELP.splitlines()
        if re.search(re.escape(flag.encode()) + rb"(?![\w-])", line) is None
    )
    assert host.missing_flags(text) == [flag]


@pytest.mark.parametrize(
    "text,flag",
    [
        (HELP.replace(b"--model <model>", b"--model"), "--model"),
        (HELP.replace(b"<level>", b"<low|medium>"), "--effort"),
        (HELP.replace(b"<format>", b"<format> (choices: json, text)"), "--output-format"),
        (HELP.replace(b"--model <model>", b"--model, -m"), "--model"),
        (
            HELP.replace(
                b"<level>               Effort",
                b"<level>               Effort (choices: low,\n"
                b"                                 medium)",
            ),
            "--effort",
        ),
        (
            HELP.replace(
                b"<level>               Effort",
                b"<level>               Effort (choices: low, medium) (high planned later)",
            ),
            "--effort",
        ),
    ],
)
def test_r05_explicit_incompatible_values_or_no_parameter(text, flag):
    assert host.missing_flags(text) == [flag]


@pytest.mark.parametrize(
    "fault,count,closed",
    [
        ("resume_unknown", None, False),
        ("cleanup_unknown", 1, False),
        ("exit", 1, True),
        ("timeout", 1, True),
    ],
)
def test_r07_failures_keep_count_separate_from_cleanup(tmp_path, monkeypatch, fault, count, closed):
    value, calls, _ = observe(tmp_path, monkeypatch, fault=fault)
    assert len(calls) == 1 and value["diagnostics"][0]["launch_count"] == count
    assert host.diagnostics_complete(value) is closed
    assert value["compatibility"]["state"] == "Unverified"


@pytest.mark.parametrize("fault", ["escape", "directory", "hardlink", "junction"])
def test_r03_source_boundary_no_path_fallback(tmp_path, fault):
    spec = entry_fixture(tmp_path)
    entry = Path(spec["path"])
    if fault == "escape":
        spec["path"] = str(tmp_path / "agy.exe")
    elif fault == "directory":
        entry.unlink()
        entry.mkdir()
    elif fault == "hardlink":
        os.link(entry, tmp_path / "copy.exe")
    else:
        destination = tmp_path / "elsewhere"
        entry.parent.rename(destination)
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(entry.parent), str(destination)],
            check=True,
            capture_output=True,
        )
    with pytest.raises((host.AgyHostError, fixtures.runner.task_input.TaskInputError)):
        host.checked_entry(spec)


@pytest.mark.parametrize(
    "fault",
    ["task", "plan", "extra", "excess", "supported", "count_bool", "order", "entry", "version"],
)
def test_r08_closed_observation_binding_and_supported_conditions(tmp_path, monkeypatch, fault):
    value, _, spec = observe(tmp_path, monkeypatch)
    changed = copy.deepcopy(value)
    if fault in {"task", "plan"}:
        changed["task_id" if fault == "task" else "plan_sha256"] = "foreign"
    elif fault == "extra":
        changed["raw_help"] = "SECRET-SENTINEL"
    elif fault == "excess":
        changed["diagnostics"].append(copy.deepcopy(changed["diagnostics"][0]))
    elif fault == "supported":
        changed["diagnostics"][0]["cleanup"]["job_closed"] = None
    elif fault == "count_bool":
        changed["diagnostics"][0]["launch_count"] = True
    elif fault == "order":
        changed["diagnostics"].reverse()
    elif fault == "entry":
        changed["entry"]["path"] = "foreign"
    else:
        changed["reported_version"] = "SECRET-SENTINEL"
    with pytest.raises(host.AgyHostError):
        host.validate_observation(changed, "task", "a" * 64, spec["path"])


def test_r10_interrupt_preserves_partial_facts_and_primary(tmp_path, monkeypatch):
    spec = entry_fixture(tmp_path)
    calls = probe_host(monkeypatch, fault="interrupt")
    value = host.new_observation("task", "a" * 64)
    with pytest.raises(KeyboardInterrupt, match="primary"):
        host.observe(spec, tmp_path, host.time.monotonic() + 30, value)
    assert len(calls) == 1 and value["diagnostics"][0]["launch_count"] == 1
    assert value["compatibility"]["reason"] == "ProbeInterrupted"
    assert host.diagnostics_complete(value)


def test_r10_remaining_budget_prevents_second_diagnostic(tmp_path, monkeypatch):
    spec = entry_fixture(tmp_path)
    calls = probe_host(monkeypatch)
    clock = [100.0]
    actual = slice_run._launch_and_capture
    timeouts = []

    def launcher(*args, **kwargs):
        timeouts.append(kwargs["timeout_seconds"])
        result = actual(*args, **kwargs)
        clock[0] = 106
        return result

    monkeypatch.setattr(host.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(slice_run, "_launch_and_capture", launcher)
    value = host.new_observation("task", "a" * 64)
    host.observe(spec, tmp_path, 105, value)
    assert timeouts == [5] and len(calls) == 1
    assert value["compatibility"]["reason"] == "DeadlineExceeded"
