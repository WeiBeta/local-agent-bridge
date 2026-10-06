"""Legacy execute v2 facts with synthetic inputs and fake native/capture APIs."""

from __future__ import annotations

import json

import pytest
import test_bridge_run as slice_fixtures
import test_cursor_run as cursor_fixtures
import test_task_launch_lifecycle as native_fixtures
import test_task_workspace as workspace_fixtures

from local_agent_bridge.bridge import cursor_run as cursor
from local_agent_bridge.bridge import slice_run as slice_runner
from local_agent_bridge.bridge import task_workspace, winjob
from local_agent_bridge.capture.session import SessionStore, SessionWriter

slice_case = slice_fixtures.case
cursor_case = cursor_fixtures.cursor_case


@pytest.fixture(autouse=True)
def synthetic_environment(tmp_path, monkeypatch):
    store = SessionStore(bytes(range(32)), root=tmp_path / "synthetic-sessions")
    monkeypatch.setattr(slice_runner, "_session_store", lambda: store)
    monkeypatch.setattr(cursor, "_session_store", lambda: store)
    monkeypatch.setattr(slice_runner, "_protect_directory", lambda _root: None)
    monkeypatch.setattr(cursor, "_protect_directory", lambda _root: None)


def build_adapter(request, tmp_path, host):
    if host == "slice":
        case = request.getfixturevalue("slice_case")
        settings = slice_fixtures._new_settings(tmp_path, "synthetic-settings.json")
        return host, slice_runner, case, settings
    return host, cursor, request.getfixturevalue("cursor_case"), None


@pytest.fixture(params=["slice", "cursor"])
def adapter(request, tmp_path):
    return build_adapter(request, tmp_path, request.param)


@pytest.fixture(
    params=[
        ("slice", "run.json"),
        ("slice", "config-restore.json"),
        ("slice", "restore"),
        ("cursor", "run.json"),
    ]
)
def failure_surface(request, tmp_path):
    host, point = request.param
    return build_adapter(request, tmp_path, host), point


def arguments(adapter, run_root, *, execute=True):
    host, _entry, case, settings = adapter
    if host == "slice":
        return slice_fixtures._run_arguments(case, run_root, settings, execute=execute)
    return cursor_fixtures._run_arguments(case, run_root, execute=execute)


def read_output(capsys):
    captured = capsys.readouterr()
    assert not captured.err
    return json.loads(captured.out)


@pytest.mark.parametrize("boundary,expected,interrupt", native_fixtures.CASES)
def test_native_fact_reaches_both_legacy_v2_receipts(
    adapter, tmp_path, monkeypatch, capsys, boundary, expected, interrupt
):
    host, entry, _case, settings = adapter
    original = KeyboardInterrupt("synthetic original interrupt")
    process, trace, oracle = native_fixtures.install_native(monkeypatch, boundary, original)
    terminate_job = winjob._kernel.TerminateJobObject
    termination_calls = []

    def record_termination(job, exit_code):
        termination_calls.append((job, exit_code))
        return terminate_job(job, exit_code)

    monkeypatch.setattr(winjob._kernel, "TerminateJobObject", record_termination)
    monkeypatch.setattr(slice_runner, "LaunchLifecycle", winjob.LaunchLifecycle)
    run_root = tmp_path / "run"
    if interrupt:
        with pytest.raises(KeyboardInterrupt) as caught:
            entry.main(arguments(adapter, run_root))
        assert caught.value is original
    else:
        code = entry.main(arguments(adapter, run_root))
        assert code == (0 if boundary == "completed" else 3)
    output = read_output(capsys)
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert output["schema_version"] == receipt["schema_version"] == 2
    assert output["launches"] == receipt["launches"] == expected
    assert receipt["spawn_state"] == ("confirmed" if expected == 1 else "not_confirmed")
    if expected is None:
        assert receipt["launch"]["spawn_state"] == "unknown"
        assert receipt["session"]["sealed"] is False and output["exit_code"] == 3
    if boundary != "completed":
        assert output["exit_code"] == 3
    assert (run_root / "plan.json").is_file()
    assert json.loads((run_root / "plan.json").read_bytes())["schema_version"] == 1
    assert oracle["resume_calls"] <= (2 if boundary.startswith("second") else 1)
    if oracle["effect"]:
        assert expected in {1, None}
    assert "SECRET" not in json.dumps(receipt)
    if boundary in {"job", "spawn"}:
        assert not process.terminated
    if interrupt and boundary not in {"capture_interrupt", "job_close_interrupt"}:
        assert trace[-3:] == ["reclaim", "close_pipes", "close_job"]
    if boundary not in {"job", "spawn"}:
        assert process.stdout.closed and process.stderr.closed
    if boundary == "capture_interrupt":
        assert termination_calls == [(71, 1)]
        assert receipt["launch"]["cleanup"]["child_exit_observed"] is True
        assert receipt["launch"]["cleanup"]["job_closed"] is True
    if boundary == "job_close_interrupt":
        assert receipt["launch"]["cleanup"]["job_closed"] is None
    if host == "slice":
        assert settings.read_bytes() == slice_fixtures.SETTINGS_BYTES


@pytest.mark.parametrize("state,count", [("not_attempted", 0), ("confirmed", 1), ("unknown", None)])
@pytest.mark.parametrize("interrupt", [False, True])
def test_capture_exception_preserves_fallback_observations(
    adapter, tmp_path, monkeypatch, capsys, state, count, interrupt
):
    host, entry, _case, _settings = adapter
    error = (
        KeyboardInterrupt("synthetic interruption")
        if interrupt
        else RuntimeError("synthetic failure")
    )
    facts, calls = [], []

    def fail(_exe, _argv, _cwd, _stdout, _stderr, *, lifecycle):
        calls.append("capture")
        lifecycle.execution_state = state
        lifecycle.stage = "fake_capture_boundary"
        lifecycle.pid = 71
        lifecycle.pid_created_filetime = None
        lifecycle.child_exit_observed = None
        lifecycle.pipes_closed = False
        lifecycle.job_closed = None
        lifecycle.thread_close_observations = [True, None]
        facts.append(lifecycle.record())
        raise error

    monkeypatch.setattr(entry, "_launch_and_capture", fail)
    run_root = tmp_path / "run"
    if interrupt:
        with pytest.raises(KeyboardInterrupt) as caught:
            entry.main(arguments(adapter, run_root))
        assert caught.value is error
    else:
        assert entry.main(arguments(adapter, run_root)) == 3
    output = read_output(capsys)
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert calls == ["capture"] and receipt["launch"] == facts[0]
    assert receipt["launches"] == output["launches"] == count
    assert output["exit_code"] == 3 and not receipt["session"]["sealed"]
    assert (
        receipt["coding"]["outcome"] if host == "slice" else receipt["result"]
    ) == "launch_failed"


@pytest.mark.parametrize("state,count", [("confirmed", 1), ("unknown", None)])
@pytest.mark.parametrize("primary_interrupt", [False, True])
@pytest.mark.parametrize("secondary_interrupt", [False, True])
def test_secondary_failure_does_not_replace_launch_fact_or_original_interrupt(
    failure_surface,
    tmp_path,
    monkeypatch,
    capsys,
    state,
    count,
    primary_interrupt,
    secondary_interrupt,
):
    adapter, write_point = failure_surface
    host, entry, _case, settings = adapter
    original = KeyboardInterrupt("primary") if primary_interrupt else RuntimeError("primary")
    secondary = KeyboardInterrupt("secondary") if secondary_interrupt else OSError("secondary")
    launch_calls, writes = [], []
    restore = slice_runner._restore_settings

    def fail_launch(_exe, _argv, _cwd, _stdout, _stderr, *, lifecycle):
        launch_calls.append("once")
        lifecycle.execution_state = state
        lifecycle.stage = "fake_launch_failure"
        raise original

    def fail_write(path, document):
        writes.append(path.name)
        if path.name == write_point:
            raise secondary
        return write(path, document)

    def fail_restore(*values):
        restore(*values)
        raise secondary

    write = entry._write_json_new
    monkeypatch.setattr(entry, "_launch_and_capture", fail_launch)
    monkeypatch.setattr(entry, "_write_json_new", fail_write)
    if write_point == "restore":
        monkeypatch.setattr(slice_runner, "_restore_settings", fail_restore)
    run_root = tmp_path / "run"
    if primary_interrupt or secondary_interrupt:
        with pytest.raises(KeyboardInterrupt) as caught:
            entry.main(arguments(adapter, run_root))
        assert caught.value is (original if primary_interrupt else secondary)
    else:
        assert entry.main(arguments(adapter, run_root)) == 3
    output = read_output(capsys)
    assert (
        output["schema_version"] == 2 and output["launches"] == count and output["exit_code"] == 3
    )
    assert launch_calls == ["once"] and writes.count("run.json") == 1
    if host == "slice":
        assert writes.count("config-restore.json") == 1
        assert settings.read_bytes() == slice_fixtures.SETTINGS_BYTES
    if write_point == "run.json":
        assert not (run_root / "run.json").exists()
        assert not output["receipt_persisted"] and output["run_receipt"] is None
    else:
        receipt = json.loads((run_root / "run.json").read_bytes())
        assert receipt["launches"] == count and receipt["launch"]["launch_count"] == count


@pytest.mark.parametrize("state,count", [("not_attempted", 0), ("unknown", None)])
def test_returned_capture_record_does_not_self_confirm_execution(
    adapter, tmp_path, monkeypatch, capsys, state, count
):
    _host, entry, _case, _settings = adapter
    returned = {"capture_state": "complete", "exit_code": 0, "timed_out": False}

    def fake(_exe, _argv, _cwd, _stdout, _stderr, *, lifecycle):
        lifecycle.execution_state = state
        return returned

    monkeypatch.setattr(entry, "_launch_and_capture", fake)
    run_root = tmp_path / "run"
    assert entry.main(arguments(adapter, run_root)) == 3
    output = read_output(capsys)
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert receipt["launches"] == output["launches"] == count
    assert receipt["launch"] == returned and not receipt["session"]["sealed"]


def test_original_launch_interrupt_survives_secondary_stdout_fault(adapter, tmp_path, monkeypatch):
    _host, entry, _case, _settings = adapter
    original = KeyboardInterrupt("primary")

    def fail(_exe, _argv, _cwd, _stdout, _stderr, *, lifecycle):
        lifecycle.execution_state = "confirmed"
        raise original

    monkeypatch.setattr(entry, "_launch_and_capture", fail)
    monkeypatch.setattr(
        entry, "_emit_json", lambda _value: (_ for _ in ()).throw(OSError("secondary stdout"))
    )
    run_root = tmp_path / "run"
    with pytest.raises(KeyboardInterrupt) as caught:
        entry.main(arguments(adapter, run_root))
    assert caught.value is original
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert receipt["launches"] == 1 and receipt["schema_version"] == 2


def test_seal_interrupt_propagates_after_v2_failure_receipt(adapter, tmp_path, monkeypatch, capsys):
    host, entry, _case, _settings = adapter
    original = KeyboardInterrupt("synthetic seal interruption")

    def fake(_exe, _argv, _cwd, stdout, stderr, *, lifecycle):
        lifecycle.execution_state = "confirmed"
        stdout.write_bytes(b'{"type":"result","status":"SUCCESS"}\n')
        stderr.write_bytes(b"")
        return {
            "capture_state": "complete",
            "capture_error": None,
            "exit_code": 0,
            "timed_out": False,
        }

    def fail_seal(_writer, _metadata):
        raise original

    monkeypatch.setattr(entry, "_launch_and_capture", fake)
    monkeypatch.setattr(SessionWriter, "seal", fail_seal)
    run_root = tmp_path / "run"
    with pytest.raises(KeyboardInterrupt) as caught:
        entry.main(arguments(adapter, run_root))
    assert caught.value is original
    output = read_output(capsys)
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert receipt["schema_version"] == 2 and receipt["launches"] == 1 and output["exit_code"] == 3
    assert (
        receipt["coding"]["outcome"] if host == "slice" else receipt["result"]
    ) == "capture_incomplete"


def test_preflight_and_historical_v1_bytes_keep_original_meaning(
    adapter, tmp_path, monkeypatch, capsys
):
    _host, entry, _case, _settings = adapter
    legacy = tmp_path / "historical-v1.json"
    raw = (
        b'{ "schema_version": 1, "launches": 0, '
        b'"spawn_state": "not_confirmed", "launch": null }\r\n'
    )
    legacy.write_bytes(raw)
    run_root = tmp_path / "run"
    assert entry.main(arguments(adapter, run_root, execute=False)) == 0
    assert read_output(capsys)["schema_version"] == 1
    assert not run_root.exists() and legacy.read_bytes() == raw
    run_root.mkdir()
    (run_root / "run.json").write_bytes(raw)
    monkeypatch.setattr(
        entry, "_launch_and_capture", lambda *_args, **_kwargs: pytest.fail("reused root launched")
    )
    assert entry.main(arguments(adapter, run_root)) == 2
    capsys.readouterr()
    assert (run_root / "run.json").read_bytes() == raw and legacy.read_bytes() == raw


@pytest.mark.parametrize("version", [1, 2, 3])
def test_distinct_task_consumer_explicitly_refuses_legacy_receipt_versions(tmp_path, version):
    root, task, _snapshot = workspace_fixtures.prepare(tmp_path)
    workspace_fixtures.progress(root, task)
    run_root, _receipt = workspace_fixtures.receipt_fixture(root, task)
    raw = json.dumps(
        {
            "schema_version": version,
            "mode": "execute",
            "launches": 0 if version == 1 else None,
            "spawn_state": "not_confirmed",
            "launch": None,
        }
    ).encode()
    (run_root / "run.json").write_bytes(raw)
    result = task_workspace.collect_task(
        task_root=root, run_root=run_root, result_root=tmp_path / "collected"
    )
    assert "RunReceiptInvalid" in result["blockers"]
    assert result["host_observations"]["transport_state"] == "Failed"
    assert result["continuation"] is None and result["management_decision"] is None
    assert (run_root / "run.json").read_bytes() == raw


def test_execute_setup_refusal_is_v2_without_a_launch(adapter, tmp_path, monkeypatch, capsys):
    _host, entry, _case, _settings = adapter

    def fail_write(_path, _document):
        raise OSError("synthetic prelaunch write failure")

    monkeypatch.setattr(entry, "_write_json_new", fail_write)
    monkeypatch.setattr(
        entry,
        "_launch_and_capture",
        lambda *_args, **_kwargs: pytest.fail("setup refusal launched"),
    )
    run_root = tmp_path / "refused"
    assert entry.main(arguments(adapter, run_root)) == 2
    output = read_output(capsys)
    assert output["mode"] == "execute" and output["schema_version"] == 2
    assert output["receipt_persisted"] is False and not (run_root / "run.json").exists()


def test_slice_failure_before_launch_keeps_known_zero(slice_case, tmp_path, monkeypatch, capsys):
    settings = slice_fixtures._new_settings(tmp_path, "synthetic-settings.json")

    def fail_patch(*_args):
        raise RuntimeError("synthetic patch failure")

    monkeypatch.setattr(slice_runner, "_apply_settings_patch", fail_patch)
    monkeypatch.setattr(
        slice_runner,
        "_launch_and_capture",
        lambda *_args, **_kwargs: pytest.fail("patch refusal launched"),
    )
    run_root = tmp_path / "failed"
    assert (
        slice_runner.main(
            slice_fixtures._run_arguments(slice_case, run_root, settings, execute=True)
        )
        == 3
    )
    output = read_output(capsys)
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert output["launches"] == receipt["launches"] == receipt["launch_attempts"] == 0
    assert receipt["spawn_state"] == "not_attempted"
    assert receipt["launch"]["spawn_state"] == "not_attempted"
    assert settings.read_bytes() == slice_fixtures.SETTINGS_BYTES


def install_failing_environment(monkeypatch, events, *, present, error):
    """Fixture-only environment mapping whose restore attempt raises once.

    The real process environment is never reached: ``slice_runner.os`` is
    replaced by a proxy that keeps the genuine module attributes but exposes a
    synthetic mapping. The initial patch (the fixed value) still succeeds; only
    the later restore operation raises, exactly as the frozen defect describes.
    """

    class Environment(dict):
        def __setitem__(self, key, value):
            events.append(["set", key, value])
            if key == slice_runner.AUTO_UPDATE_VARIABLE and value != slice_runner.AUTO_UPDATE_VALUE:
                raise error
            super().__setitem__(key, value)

        def pop(self, key, default=None):
            events.append(["pop", key])
            if key == slice_runner.AUTO_UPDATE_VARIABLE:
                raise error
            return super().pop(key, default)

    mapping = Environment(
        {slice_runner.AUTO_UPDATE_VARIABLE: "synthetic-existing"} if present else {}
    )
    real_os = slice_runner.os

    class OSProxy:
        environ = mapping

        def __getattr__(self, name):
            return getattr(real_os, name)

    monkeypatch.setattr(slice_runner, "os", OSProxy())
    return mapping


def install_slice_interrupt(monkeypatch, boundary, original):
    """Frozen shared fake-native seam, plus the adapter's own lifecycle binding."""
    process, trace, oracle = native_fixtures.install_native(monkeypatch, boundary, original)
    monkeypatch.setattr(slice_runner, "LaunchLifecycle", winjob.LaunchLifecycle)
    return process, trace, oracle


@pytest.mark.parametrize("present", [False, True])
@pytest.mark.parametrize(
    "boundary,expected", [("assign", 0), ("native_effect", None), ("after_record", 1)]
)
@pytest.mark.parametrize("secondary_interrupt", [False, True])
def test_original_interrupt_survives_environment_restore_failure(
    slice_case, tmp_path, monkeypatch, capsys, present, boundary, expected, secondary_interrupt
):
    settings = slice_fixtures._new_settings(tmp_path, "synthetic-settings.json")
    original = KeyboardInterrupt("synthetic original launch interrupt")
    secondary = (
        KeyboardInterrupt("synthetic environment restore interrupt")
        if secondary_interrupt
        else OSError("synthetic environment restore failure")
    )
    _process, trace, oracle = install_slice_interrupt(monkeypatch, boundary, original)
    events = []
    mapping = install_failing_environment(monkeypatch, events, present=present, error=secondary)
    run_root = tmp_path / "run"
    with pytest.raises(KeyboardInterrupt) as caught:
        slice_runner.main(
            slice_fixtures._run_arguments(slice_case, run_root, settings, execute=True)
        )
    assert caught.value is original
    output = read_output(capsys)
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert output["schema_version"] == receipt["schema_version"] == 2
    assert output["launches"] == receipt["launches"] == expected
    assert receipt["launch"]["launch_count"] == expected
    assert output["exit_code"] == 3 and output["receipt_persisted"] is True
    assert receipt["lifecycle_exception"] == "KeyboardInterrupt"
    diagnostic = [{"stage": "environment-restore", "error": type(secondary).__name__}]
    assert receipt["evidence_write_failures"] == diagnostic
    assert output["evidence_write_failures"] == diagnostic
    # One bounded best-effort attempt only: the fixed initial patch, then the
    # failing restore. The mapping still holds the patched value, so nothing
    # observed a completed restoration and nothing claims one.
    assert len(events) == 2 and events[-1][0] == ("pop" if not present else "set")
    assert mapping.get(slice_runner.AUTO_UPDATE_VARIABLE) == slice_runner.AUTO_UPDATE_VALUE
    assert trace.count("spawn") == 1 and oracle["resume_calls"] <= 1
    assert receipt["restore"]["restored_original_bytes"] is True
    assert settings.read_bytes() == slice_fixtures.SETTINGS_BYTES
    assert "SECRET" not in json.dumps(receipt)


@pytest.mark.parametrize("present", [False, True])
@pytest.mark.parametrize("secondary_interrupt", [False, True])
def test_environment_restore_failure_without_original_interrupt_is_not_a_success(
    slice_case, tmp_path, monkeypatch, capsys, present, secondary_interrupt
):
    settings = slice_fixtures._new_settings(tmp_path, "synthetic-settings.json")
    secondary = (
        KeyboardInterrupt("synthetic environment restore interrupt")
        if secondary_interrupt
        else OSError("synthetic environment restore failure")
    )
    install_slice_interrupt(monkeypatch, "completed", KeyboardInterrupt("unused"))
    events = []
    mapping = install_failing_environment(monkeypatch, events, present=present, error=secondary)
    run_root = tmp_path / "run"
    if secondary_interrupt:
        with pytest.raises(KeyboardInterrupt) as caught:
            slice_runner.main(
                slice_fixtures._run_arguments(slice_case, run_root, settings, execute=True)
            )
        assert caught.value is secondary
    else:
        assert (
            slice_runner.main(
                slice_fixtures._run_arguments(slice_case, run_root, settings, execute=True)
            )
            == 3
        )
    output = read_output(capsys)
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert output["schema_version"] == receipt["schema_version"] == 2
    assert output["launches"] == receipt["launches"] == 1
    assert output["exit_code"] == 3 and output["receipt_persisted"] is True
    # No original error was in flight, so the environment failure keeps its own
    # pre-repair semantics: never swallowed, never a success claim.
    assert receipt["lifecycle_exception"] == type(secondary).__name__
    assert receipt["evidence_write_failures"] == []
    assert len(events) == 2 and events[-1][0] == ("pop" if not present else "set")
    assert mapping.get(slice_runner.AUTO_UPDATE_VARIABLE) == slice_runner.AUTO_UPDATE_VALUE
    assert settings.read_bytes() == slice_fixtures.SETTINGS_BYTES


@pytest.mark.parametrize(
    "boundary,expected", [("assign", 0), ("native_effect", None), ("after_record", 1)]
)
@pytest.mark.parametrize("secondary_interrupt", [False, True])
def test_simultaneous_finalization_failures_preserve_original_interrupt(
    slice_case, tmp_path, monkeypatch, capsys, boundary, expected, secondary_interrupt
):
    settings = slice_fixtures._new_settings(tmp_path, "synthetic-settings.json")
    original = KeyboardInterrupt("synthetic original launch interrupt")
    secondary = (
        KeyboardInterrupt("synthetic environment restore interrupt")
        if secondary_interrupt
        else OSError("synthetic environment restore failure")
    )
    _process, trace, _oracle = install_slice_interrupt(monkeypatch, boundary, original)
    events = []
    install_failing_environment(monkeypatch, events, present=False, error=secondary)
    write = slice_runner._write_json_new
    attempts = []

    def fail_write(path, document):
        attempts.append(path.name)
        if path.name in {"config-restore.json", "run.json"}:
            raise OSError("synthetic evidence write failure")
        return write(path, document)

    monkeypatch.setattr(slice_runner, "_write_json_new", fail_write)
    run_root = tmp_path / "run"
    with pytest.raises(KeyboardInterrupt) as caught:
        slice_runner.main(
            slice_fixtures._run_arguments(slice_case, run_root, settings, execute=True)
        )
    assert caught.value is original
    output = read_output(capsys)
    assert attempts.count("config-restore.json") == 1 and attempts.count("run.json") == 1
    assert not (run_root / "run.json").exists()
    assert output["schema_version"] == 2 and output["launches"] == expected
    assert output["exit_code"] == 3 and output["receipt_persisted"] is False
    assert output["run_receipt"] is None and output["lifecycle_exception"] == "KeyboardInterrupt"
    assert output["evidence_write_failures"] == [
        {"stage": "environment-restore", "error": type(secondary).__name__},
        {"stage": "config-restore.json", "error": "OSError"},
        {"stage": "run.json", "error": "OSError"},
    ]
    assert trace.count("spawn") == 1
    assert len(events) == 2 and events[-1][0] == "pop"
    assert settings.read_bytes() == slice_fixtures.SETTINGS_BYTES
    assert "SECRET" not in json.dumps(output)
