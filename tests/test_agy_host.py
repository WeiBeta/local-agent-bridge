"""R03-R05/R07-R08/R10: RAM-only diagnostics through the existing fake Job channel."""

from __future__ import annotations

import copy
import hashlib
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


def probe_host(
    monkeypatch,
    *,
    version=b"1.3.4\n",
    version_stderr=b"SECRET-SENTINEL",
    help_text=HELP,
    help_stderr=b"SECRET-SENTINEL",
    fault=None,
    fault_at=None,
):
    calls = []

    class Process(fixtures.FakeProcess):
        def close_job(self):
            return None if self.diagnostic_fault == "cleanup_unknown" else True

    def spawn(argv, cwd, *, lifecycle, env):
        assert len(argv) == 2 and argv[1] in {"--version", "--help"}
        assert env["AGY_CLI_DISABLE_AUTO_UPDATE"] == "true"
        assert all(flag not in argv for flag in ("--model", "--project", "--print"))
        calls.append((argv, lifecycle, cwd))
        active_fault = fault if fault_at is None or argv[1] == fault_at else None
        lifecycle.pid = 1234
        lifecycle.pid_created_filetime = 999
        lifecycle.execution_state = "unknown" if active_fault == "resume_unknown" else "confirmed"
        if active_fault == "resume_unknown":
            lifecycle.stage = "resume_call"
            lifecycle.child_exit_observed = lifecycle.pipes_closed = lifecycle.job_closed = True
            raise RuntimeError("SECRET-SENTINEL")
        if active_fault == "interrupt":
            lifecycle.child_exit_observed = lifecycle.pipes_closed = lifecycle.job_closed = True
            raise KeyboardInterrupt("primary")
        process = Process(
            exit_code=1 if active_fault == "exit" else 0,
            wait_error=subprocess.TimeoutExpired(argv, 10) if active_fault == "timeout" else None,
        )
        process.diagnostic_fault = active_fault
        process.stdout = io.BytesIO(
            (version() if callable(version) else version) if argv[1] == "--version" else help_text
        )
        process.stderr = io.BytesIO(help_stderr if argv[1] == "--help" else version_stderr)
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
    "flag,argument,choices,required",
    [
        ("--effort", "<level>", "low, medium", "high"),
        ("--output-format", "<format>", "json, text", "stream-json"),
    ],
    ids=["effort", "format"],
)
@pytest.mark.parametrize(
    "suffix",
    [
        " ({required} planned later)",
        "\n       ({required} planned later)",
        " Future release may include {required} (planned later)",
        "\n       Future release may include {required} (planned later)",
        "\n       (future choices: {required})",
        ", default: {required}",
    ],
    ids=["inline-note", "wrapped-note", "inline-prose", "wrapped-prose", "second-enum", "default"],
)
def test_r05_unparenthesized_enum_stops_before_description(
    flag, argument, choices, required, suffix
):
    original = f"{flag} {argument}".encode()
    declaration = f"{flag} {argument} choices: {choices}" + suffix.format(required=required)
    text = HELP.replace(original, declaration.encode())
    assert host.missing_flags(text) == [flag]


@pytest.mark.parametrize("label", ["choices", "OPTIONS", "values"])
@pytest.mark.parametrize("parenthesized", [False, True], ids=["plain", "enclosed"])
def test_r05_enum_metadata_does_not_supply_a_required_value(label, parenthesized):
    enum = f"{label}: low, medium, default: high"
    if parenthesized:
        enum = f"({enum})"
    assert host.missing_flags(HELP.replace(b"<level>", f"<level> {enum}".encode())) == ["--effort"]


@pytest.mark.parametrize(
    "flag,argument,choices,required",
    [
        ("--effort", "<level>", "low, medium", "high"),
        ("--output-format", "<format>", "json, text", "stream-json"),
    ],
    ids=["effort", "format"],
)
@pytest.mark.parametrize("layout", ["plain", "quoted", "pipe", "wrapped", "wrapped-colon"])
def test_r05_valid_enum_forms_preserve_declared_values(flag, argument, choices, required, layout):
    enum = f"choices: {choices}, {required}"
    if layout == "quoted":
        enum = "values: " + ", ".join(f'"{value}"' for value in [*choices.split(", "), required])
    elif layout == "pipe":
        enum = f"options: {choices.replace(', ', '|')}|{required}"
    elif layout == "wrapped":
        enum = f"(choices: {choices},\r\n       {required})"
    elif layout == "wrapped-colon":
        enum = f"(choices:\n       {choices}, {required})"
    declaration = f"{flag} {argument} {enum} (additional explanation)"
    assert (
        host.missing_flags(HELP.replace(f"{flag} {argument}".encode(), declaration.encode())) == []
    )


def checked_actual_help(raw):
    # Git's Windows checkout may expand LF; the committed blob is the original bytes.
    raw = raw.replace(b"\r\n", b"\n")
    assert len(raw) == 2905
    assert hashlib.sha256(raw).hexdigest() == (
        "337622c6dcdcb204312277570c4173dda83f3cbf006629f0eabe657069071e7c"
    )
    return raw


@pytest.fixture
def actual_help():
    # 2026-10-14 HELP-DIAG-01: secret-scanned stderr; original SHA is checked above.
    return checked_actual_help(
        (Path(__file__).parent / "fixtures" / "agy-help-1.3.4.txt").read_bytes()
    )


def test_help_format_fixture_git_checkout_normalization_preserves_original_bytes(actual_help):
    assert checked_actual_help(actual_help.replace(b"\n", b"\r\n")) == actual_help


def without_usage_row(raw, flag):
    return b"\n".join(
        line for line in raw.split(b"\n") if not line.lstrip().startswith(flag.encode() + b" ")
    )


@pytest.mark.parametrize("stream", ["stdout", "stderr", "both"])
def test_help_format_actual_bytes_projected_after_success(
    tmp_path, monkeypatch, actual_help, stream
):
    stdout = actual_help if stream in {"stdout", "both"} else b""
    stderr = actual_help if stream in {"stderr", "both"} else b""
    before = set(tmp_path.rglob("*"))
    value, calls, _ = observe(tmp_path, monkeypatch, help_text=stdout, help_stderr=stderr)
    assert value["compatibility"] == {
        "state": "Supported",
        "missing_required_flags": [],
        "reason": None,
    }
    assert value["reported_version"] == "1.3.4" and len(calls) == 2
    assert host.diagnostics_complete(value)
    assert set(tmp_path.rglob("*")) - before == {
        tmp_path / "installation",
        tmp_path / "installation" / "agy.exe",
    }


@pytest.mark.parametrize("flag", host.REQUIRED_FLAGS)
def test_help_format_missing_declarations_are_not_supplied_by_prose(actual_help, flag):
    text = without_usage_row(actual_help, flag)
    text += f"\nNotes: {flag} is mentioned only in prose.\n".encode()
    assert host.missing_flags(text) == [flag]


@pytest.mark.parametrize("flag", host.REQUIRED_FLAGS)
@pytest.mark.parametrize("placeholder", ["", " <value>"])
def test_help_format_floating_option_examples_are_not_usage_rows(actual_help, flag, placeholder):
    text = without_usage_row(actual_help, flag)
    text += f"\nExamples:\n  {flag}{placeholder}  Planned example (high|stream-json)\n".encode()
    assert host.missing_flags(text) == [flag]


@pytest.mark.parametrize(
    "original,replacement,flag",
    [
        (b"(low|medium|high|xhigh|max)", b"(low|medium) (high planned later)", "--effort"),
        (b"(low|medium|high|xhigh|max)", b"(low|medium) default: high", "--effort"),
        (b"(low|medium|high|xhigh|max)", b"High may be available later", "--effort"),
        (b"(low|medium|high|xhigh|max)", b"(default high)", "--effort"),
        (
            b"(text, json, stream-json)",
            b"(text, json) (stream-json planned later)",
            "--output-format",
        ),
        (b"(text, json, stream-json)", b"(text, json) default: stream-json", "--output-format"),
        (b"(text, json, stream-json)", b"stream-json may be available later", "--output-format"),
    ],
)
def test_help_format_enum_values_belong_to_the_first_explicit_list(
    actual_help, original, replacement, flag
):
    assert host.missing_flags(actual_help.replace(original, replacement)) == [flag]


@pytest.mark.parametrize("flag", ["--effort", "--output-format"])
def test_help_format_wrapped_prose_does_not_supply_a_usage_enum(actual_help, flag):
    if flag == "--effort":
        text = actual_help.replace(b"(low|medium|high|xhigh|max)", b"\n    (low|medium|high)")
    else:
        text = actual_help.replace(b"(text, json, stream-json)", b"\n    (text, json, stream-json)")
    assert flag in host.missing_flags(text)


@pytest.mark.parametrize("reverse", [False, True])
def test_help_format_conflicting_streams_are_order_independent(
    tmp_path, monkeypatch, actual_help, reverse
):
    changed = actual_help.replace(b"(low|medium|high|xhigh|max)", b"(low|high)")
    # Both standalone declarations support high; different declarations still conflict.
    assert host.missing_flags(actual_help) == host.missing_flags(changed) == []
    stdout, stderr = (changed, actual_help) if reverse else (actual_help, changed)
    value, calls, _ = observe(tmp_path, monkeypatch, help_text=stdout, help_stderr=stderr)
    assert len(calls) == 2
    assert value["compatibility"] == {
        "state": "Unsupported",
        "missing_required_flags": ["--effort"],
        "reason": "RequiredParametersMissing",
    }


@pytest.mark.parametrize("reverse", [False, True])
def test_help_format_conflicting_untyped_descriptions_reject(actual_help, reverse):
    changed = actual_help.replace(
        b"--model                         Model for the current CLI session",
        b"--model                         Disable model selection",
    )
    text = changed + b"\n" + actual_help if reverse else actual_help + b"\n" + changed
    assert host.missing_flags(text) == ["--model"]


@pytest.mark.parametrize("flag", ["--effort", "--output-format"])
@pytest.mark.parametrize("reverse", [False, True])
def test_help_format_legacy_conflicts_do_not_overwrite_supported_declarations(flag, reverse):
    if flag == "--effort":
        first = HELP.replace(b"<level>", b"<level> (choices: low, high)")
        second = HELP.replace(b"<level>", b"<level> (choices: medium, high)")
    else:
        first = HELP.replace(b"<format>", b"<format> (choices: text, stream-json)")
        second = HELP.replace(b"<format>", b"<format> (choices: json, stream-json)")
    assert host.missing_flags(first) == host.missing_flags(second) == []
    text = second + b"\n" + first if reverse else first + b"\n" + second
    assert host.missing_flags(text) == [flag]


def test_help_format_identical_legacy_streams_preserve_wrapped_and_alias_forms():
    text = HELP.replace(b"--model <model>", b"--model, -m <name>").replace(
        b"<level>", b"<level> (choices: low,\n       high)"
    )
    assert host.missing_flags(text + b"\n" + text) == []


@pytest.mark.parametrize("reverse", [False, True])
def test_help_format_boolean_duplicate_conflicts_do_not_overwrite(actual_help, reverse):
    changed = actual_help.replace(
        b"Disable slash command and skill expansion in print mode",
        b"Enable slash command and skill expansion in print mode",
    )
    text = changed + b"\n" + actual_help if reverse else actual_help + b"\n" + changed
    assert host.missing_flags(text) == ["--disable-slash-commands"]


def test_help_format_usage_duplicate_spacing_is_not_a_conflict(actual_help):
    changed = actual_help.replace(
        b"Model for the current CLI session", b"Model  for\tthe current CLI session"
    )
    assert host.missing_flags(actual_help + b"\n" + changed) == []


@pytest.mark.parametrize("fault", ["resume_unknown", "cleanup_unknown", "exit", "timeout"])
def test_help_format_successful_text_cannot_bypass_help_lifecycle_gates(
    tmp_path, monkeypatch, actual_help, fault
):
    def forbidden_projection(_raw):
        pytest.fail("Help was projected before its existing lifecycle gates passed")

    monkeypatch.setattr(host, "missing_flags", forbidden_projection)
    value, calls, _ = observe(
        tmp_path,
        monkeypatch,
        help_text=b"",
        help_stderr=actual_help,
        fault=fault,
        fault_at="--help",
    )
    assert len(calls) == 2 and value["compatibility"]["state"] == "Unverified"
    assert value["compatibility"]["reason"] in {
        "HelpProbeFailed",
        "DiagnosticCleanupUnverified",
        "ProbeTimedOut",
    }


def test_help_format_stderr_truncation_prevents_projection(tmp_path, monkeypatch, actual_help):
    def forbidden_projection(_raw):
        pytest.fail("Truncated Help was projected")

    monkeypatch.setattr(host, "missing_flags", forbidden_projection)
    value, calls, _ = observe(
        tmp_path, monkeypatch, help_text=b"x" * 262144, help_stderr=actual_help
    )
    assert len(calls) == 2 and value["compatibility"]["reason"] == "ProbeOutputTruncated"


def test_help_format_incomplete_capture_prevents_projection(tmp_path, monkeypatch, actual_help):
    actual = slice_run._launch_and_capture

    def launcher(*args, **kwargs):
        result = actual(*args, **kwargs)
        if args[1][-1] == "--help":
            result["capture_state"] = "incomplete"
        return result

    def forbidden_projection(_raw):
        pytest.fail("Incomplete Help capture was projected")

    monkeypatch.setattr(slice_run, "_launch_and_capture", launcher)
    monkeypatch.setattr(host, "missing_flags", forbidden_projection)
    value, calls, _ = observe(tmp_path, monkeypatch, help_text=b"", help_stderr=actual_help)
    assert len(calls) == 2 and value["compatibility"]["reason"] == "HelpProbeFailed"


def test_help_format_does_not_expand_version_to_stderr(tmp_path, monkeypatch, actual_help):
    value, calls, _ = observe(
        tmp_path,
        monkeypatch,
        version=b"",
        version_stderr=b"1.3.4\n",
        help_text=b"",
        help_stderr=actual_help,
    )
    assert len(calls) == 1 and value["compatibility"]["reason"] == "VersionProbeFailed"


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
