"""Execution/receipt boundaries with fake native APIs; no host or provider calls."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from test_task_run import FakeProcess, fake_spawn, plan, prepare, run

from local_agent_bridge.bridge import slice_run, winjob
from local_agent_bridge.bridge import task_run as runner

CASES = [
    ("job", 0, False),
    ("spawn", 0, False),
    ("assign", 0, True),
    ("identity", 0, True),
    ("native_no_effect", None, True),
    ("native_effect", None, True),
    ("result_conversion", None, True),
    ("before_record", None, True),
    ("after_record", 1, True),
    ("thread_close_error", 1, False),
    ("thread_close_interrupt", 1, True),
    ("thread_close_false", 1, False),
    ("handoff_error", 1, False),
    ("handoff_interrupt", 1, True),
    ("second_resume_unknown", 1, True),
    ("second_resume_failed", 1, False),
    ("resume_failed", 0, False),
    ("resume_still_suspended", 0, False),
    ("resume_already_running", None, False),
    ("capture_interrupt", 1, True),
    ("job_close_interrupt", 1, True),
    ("completed", 1, False),
]


def install_native(monkeypatch, boundary, original, *, cleanup_fault=None):
    trace = []
    oracle = {"effect": False, "resume_calls": 0}
    process = FakeProcess(wait_error=original if boundary == "capture_interrupt" else None)
    lifecycle_type = winjob.LaunchLifecycle

    class BoundaryLifecycle(lifecycle_type):
        def observe_resume(self, previous_count, previous_state):
            if boundary == "before_record":
                raise original
            super().observe_resume(previous_count, previous_state)
            if boundary == "after_record":
                raise original

        def __setattr__(self, name, value):
            if name == "stage" and value == "wrapper_handoff" and boundary.startswith("handoff"):
                raise original if boundary.endswith("interrupt") else RuntimeError("SECRET-handoff")
            super().__setattr__(name, value)

    def create_job():
        trace.append("job")
        if boundary == "job":
            raise RuntimeError("SECRET-job")
        return 71

    def spawn(*_, env=None):
        trace.append("spawn")
        if boundary == "spawn":
            raise RuntimeError("SECRET-spawn")
        return process

    def assign(*_):
        trace.append("assign")
        if boundary == "assign":
            raise original

    def identity(*_):
        trace.append("identity")
        if boundary == "identity":
            raise original
        return 100

    class UnrecordedReturn:
        def __int__(self):
            raise original

    def resume(*_):
        trace.append("resume")
        oracle["resume_calls"] += 1
        if boundary == "native_no_effect":
            raise original
        oracle["effect"] = boundary not in {"resume_failed", "resume_still_suspended"}
        if boundary == "native_effect" or (
            boundary == "second_resume_unknown" and oracle["resume_calls"] == 2
        ):
            raise original
        if boundary == "result_conversion":
            return UnrecordedReturn()
        if boundary == "resume_failed" or (
            boundary == "second_resume_failed" and oracle["resume_calls"] == 2
        ):
            return winjob._RESUME_FAILED
        if boundary == "resume_still_suspended":
            return 2
        if boundary == "resume_already_running":
            return 0
        return 1

    def close(handle):
        trace.append("close_thread" if handle in {73, 74} else "close_job")
        if handle == 73:
            if boundary == "thread_close_error":
                raise OSError("SECRET-thread-close")
            if boundary == "thread_close_interrupt":
                raise original
            if boundary == "thread_close_false":
                return False
            if cleanup_fault == "thread":
                raise RuntimeError("SECRET-secondary-thread")
        elif cleanup_fault == "job":
            raise RuntimeError("SECRET-secondary-job")
        elif boundary == "job_close_interrupt":
            raise original
        return True

    def reclaim(*_):
        trace.append("reclaim")
        if cleanup_fault == "reclaim":
            raise RuntimeError("SECRET-secondary-reclaim")
        return True

    real_close_pipes = winjob._close_child_pipes

    def close_pipes(child):
        trace.append("close_pipes")
        if cleanup_fault == "pipes":
            raise RuntimeError("SECRET-secondary-pipes")
        return real_close_pipes(child)

    monkeypatch.setattr(winjob, "LaunchLifecycle", BoundaryLifecycle)
    monkeypatch.setattr(winjob, "create_kill_on_close_job", create_job)
    monkeypatch.setattr(winjob, "spawn_suspended", spawn)
    monkeypatch.setattr(winjob, "assign_to_job", assign)
    monkeypatch.setattr(winjob, "_process_handle", lambda *_: 72)
    monkeypatch.setattr(winjob, "process_created_filetime", identity)
    monkeypatch.setattr(winjob, "handle_pid", lambda *_: process.pid)
    monkeypatch.setattr(winjob, "_liveness", lambda *_: "alive")
    monkeypatch.setattr(
        winjob,
        "_snapshot_thread_ids",
        lambda *_: [73, 74] if boundary.startswith("second") else [73],
    )
    monkeypatch.setattr(
        winjob,
        "_kernel",
        SimpleNamespace(
            OpenThread=lambda _rights, _inherit, thread_id: thread_id,
            GetProcessIdOfThread=lambda *_: process.pid,
            ResumeThread=resume,
            CloseHandle=close,
            TerminateJobObject=lambda *_: True,
        ),
    )
    monkeypatch.setattr(winjob, "_reclaim_assigned", reclaim)
    monkeypatch.setattr(winjob, "_close_child_pipes", close_pipes)
    monkeypatch.setattr(slice_run, "spawn_suspended_in_job", winjob.spawn_suspended_in_job)
    return process, trace, oracle


@pytest.mark.parametrize("host", ["agy", "cursor"])
@pytest.mark.parametrize("boundary,expected,interrupt", CASES)
def test_receipt_uses_native_fact_on_every_boundary(
    tmp_path, monkeypatch, host, boundary, expected, interrupt
):
    case = prepare(tmp_path, monkeypatch, host=host)
    frozen = plan(case)
    original = KeyboardInterrupt()
    process, trace, oracle = install_native(monkeypatch, boundary, original)
    settings_before = case.settings.read_bytes()
    target = tmp_path / "run"
    if interrupt:
        with pytest.raises(KeyboardInterrupt) as error:
            run(case, frozen, target, execute=True)
        assert error.value is original
        result = json.loads((target / "run.json").read_bytes())
    else:
        result = run(case, frozen, target, execute=True)
    assert result["launch_count"] == expected
    assert result["transport_state"] == ("Completed" if boundary == "completed" else "Failed")
    assert ("LaunchUnverified" in result["blockers"]) == (expected is None)
    assert result["restore_state"] == ("Restored" if host == "agy" else "Unchanged")
    assert case.settings.read_bytes() == settings_before
    launch = json.loads((target / "launch.json").read_bytes())
    assert launch["launch_count"] == expected
    assert launch["spawn_state"] == (
        "unknown" if expected is None else "confirmed" if expected else "not_attempted"
    )
    if "identity" in trace:
        assert launch["pid"] == process.pid
    if "resume" in trace:
        assert trace.index("identity") < trace.index("resume")
        assert launch["pid_created_filetime"] == 100
    assert oracle["resume_calls"] <= (2 if boundary.startswith("second") else 1)
    if boundary not in {"job", "spawn"}:
        assert process.stdout.closed and process.stderr.closed
    if boundary.startswith("thread_close"):
        assert launch["cleanup"]["thread_close_observations"] == [
            False if boundary.endswith("false") else None
        ]
    if boundary == "job_close_interrupt":
        assert launch["cleanup"]["job_closed"] is None
    for name in ("launch.json", "lifecycle-failure.json", "run.json"):
        if (target / name).exists():
            assert b"SECRET" not in (target / name).read_bytes()
    refs = [item["ref"] for item in result["evidence_refs"]]
    assert refs == sorted(set(refs), key=lambda value: value.encode("utf-8"))


@pytest.mark.parametrize("cleanup_fault", ["thread", "reclaim", "pipes", "job"])
@pytest.mark.parametrize("boundary,expected", [("native_effect", None), ("after_record", 1)])
def test_secondary_cleanup_cannot_replace_original_interrupt(
    tmp_path, monkeypatch, cleanup_fault, boundary, expected
):
    case = prepare(tmp_path, monkeypatch)
    frozen = plan(case)
    original = KeyboardInterrupt()
    _process, trace, _oracle = install_native(
        monkeypatch, boundary, original, cleanup_fault=cleanup_fault
    )
    target = tmp_path / "run"
    with pytest.raises(KeyboardInterrupt) as error:
        run(case, frozen, target, execute=True)
    assert error.value is original
    assert trace[-3:] == ["reclaim", "close_pipes", "close_job"]
    result = json.loads((target / "run.json").read_bytes())
    launch = json.loads((target / "launch.json").read_bytes())
    assert result["launch_count"] == launch["launch_count"] == expected
    field = {"reclaim": "child_exit_observed", "pipes": "pipes_closed", "job": "job_closed"}
    if cleanup_fault in field:
        assert launch["cleanup"][field[cleanup_fault]] is None
    else:
        assert launch["cleanup"]["thread_close_observations"] == [None]


def test_unknown_held_handle_liveness_does_not_claim_reclaimed(monkeypatch):
    process = FakeProcess()
    monkeypatch.setattr(winjob, "_process_handle", lambda *_: 72)
    monkeypatch.setattr(winjob, "_liveness", lambda *_: "unknown")
    monkeypatch.setattr(winjob, "_kernel", SimpleNamespace(TerminateProcess=lambda *_: True))
    assert winjob._reclaim_assigned(process, 71) is False


@pytest.mark.parametrize("boundary,expected", [("native_effect", None), ("after_record", 1)])
@pytest.mark.parametrize("cleanup", ["restore_error", "restore_interrupt", "restore_record"])
def test_configuration_cleanup_preserves_original_interrupt(
    tmp_path, monkeypatch, boundary, expected, cleanup
):
    case = prepare(tmp_path, monkeypatch)
    frozen = plan(case)
    original = KeyboardInterrupt()
    install_native(monkeypatch, boundary, original)
    target = tmp_path / "run"
    if cleanup == "restore_record":
        from local_agent_bridge.bridge import task_run

        persist = task_run._persist

        def fail_record(path, value):
            if path.name == "config-restore.json":
                raise OSError("SECRET-restore-record")
            return persist(path, value)

        monkeypatch.setattr(task_run, "_persist", fail_record)
    else:

        def fail_restore(*_):
            if cleanup == "restore_interrupt":
                raise KeyboardInterrupt()
            raise OSError("SECRET-restore")

        monkeypatch.setattr(slice_run, "_restore_settings", fail_restore)
    with pytest.raises(KeyboardInterrupt) as error:
        run(case, frozen, target, execute=True)
    assert error.value is original
    result = json.loads((target / "run.json").read_bytes())
    assert result["launch_count"] == expected
    assert result["transport_state"] == "Failed"
    expected_restore = "Restored" if cleanup == "restore_record" else "Failed"
    assert result["restore_state"] == expected_restore
    assert ("RestoreFailed" in result["blockers"]) == (expected_restore == "Failed")


def test_pipe_cleanup_attempts_both_streams_when_one_is_interrupted():
    original = KeyboardInterrupt()
    trace = []

    def first():
        trace.append("first")
        raise original

    def second():
        trace.append("second")

    process = SimpleNamespace(
        stdout=SimpleNamespace(close=first), stderr=SimpleNamespace(close=second)
    )
    with pytest.raises(KeyboardInterrupt) as error:
        winjob._close_child_pipes(process)
    assert error.value is original and trace == ["first", "second"]


WRITE_POINTS = ["lifecycle-failure.json", "launch.json", "run.json"]


def fail_one_write(monkeypatch, write_point, attempts):
    persist = runner._persist

    def failing(path, value, **kwargs):
        if path.name == write_point:
            attempts.append(path.name)
            raise OSError("SECRET-secondary-write")
        return persist(path, value, **kwargs)

    monkeypatch.setattr(runner, "_persist", failing)


@pytest.mark.parametrize("write_point", WRITE_POINTS)
@pytest.mark.parametrize("boundary,expected", [("native_effect", None), ("after_record", 1)])
@pytest.mark.parametrize("host", ["agy", "cursor"])
def test_secondary_write_failure_preserves_original_interrupt(
    tmp_path, monkeypatch, host, boundary, expected, write_point
):
    case = prepare(tmp_path, monkeypatch, host=host)
    frozen = plan(case)
    original = KeyboardInterrupt()
    _process, trace, _oracle = install_native(monkeypatch, boundary, original)
    attempts = []
    fail_one_write(monkeypatch, write_point, attempts)
    target = tmp_path / "run"
    with pytest.raises(KeyboardInterrupt) as error:
        run(case, frozen, target, execute=True)
    assert error.value is original
    assert attempts == [write_point]
    assert trace[-3:] == ["reclaim", "close_pipes", "close_job"]
    for name in ("lifecycle-failure.json", "launch.json", "run.json"):
        if (target / name).exists():
            assert b"SECRET" not in (target / name).read_bytes()
    assert (target / "lifecycle-failure.json").exists() == (write_point != "lifecycle-failure.json")
    assert (target / "launch.json").exists() == (write_point != "launch.json")
    if write_point == "run.json":
        assert not (target / "run.json").exists()
    else:
        result = json.loads((target / "run.json").read_bytes())
        assert result["launch_count"] == expected
        refs = [item["ref"] for item in result["evidence_refs"]]
        assert (write_point in refs) is False
        assert result["transport_state"] == "Failed"


@pytest.mark.parametrize("boundary,expected", [("native_effect", None), ("after_record", 1)])
def test_every_secondary_write_failing_together_still_raises_original(
    tmp_path, monkeypatch, boundary, expected
):
    case = prepare(tmp_path, monkeypatch)
    frozen = plan(case)
    original = KeyboardInterrupt()
    install_native(monkeypatch, boundary, original)
    attempts = []

    def failing(path, value, **kwargs):
        attempts.append(path.name)
        raise OSError("SECRET-secondary-write")

    monkeypatch.setattr(runner, "_persist", failing)
    target = tmp_path / "run"
    with pytest.raises(KeyboardInterrupt) as error:
        run(case, frozen, target, execute=True)
    assert error.value is original
    # config-restore.json is attempted first (inside the settings-patch finally)
    # and keeps its own already-verified launch_error protection.
    assert attempts == [
        "config-restore.json",
        "lifecycle-failure.json",
        "launch.json",
        "run.json",
    ]
    assert not any((target / name).exists() for name in WRITE_POINTS)


@pytest.mark.parametrize("write_point", WRITE_POINTS)
@pytest.mark.parametrize("host", ["agy", "cursor"])
def test_write_failure_without_interrupt_reaches_public_mapping(
    tmp_path, monkeypatch, host, write_point
):
    case = prepare(tmp_path, monkeypatch, host=host)
    frozen = plan(case)
    if write_point == "lifecycle-failure.json":

        def fail_capture(*_args, **_kwargs):
            raise ValueError("synthetic lifecycle error")

        monkeypatch.setattr(runner, "_capture_bytes", fail_capture)
    else:
        fake_spawn(case, monkeypatch)
    attempts = []
    fail_one_write(monkeypatch, write_point, attempts)
    target = tmp_path / "run"
    with pytest.raises(runner.TaskRunError, match="IoFailed") as error:
        run(case, frozen, target, execute=True)
    assert error.value.code == "IoFailed"
    assert attempts == [write_point]
