"""Offline Windows Job-channel tests for ag_oneshot_winjob (probe P4 shape).

All child processes are this repository's own fixtures: bounded, hidden
window, and reclaimed through handles this test or the module itself owns.
No fixture self-exit is ever accepted as reclamation evidence.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from local_agent_bridge.bridge import winjob
from local_agent_bridge.bridge.winjob import AgWinJobError

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only module")


@pytest.fixture(autouse=True)
def _fast_fixture_children(monkeypatch):
    """Keep the test-only bootstrap out of fixture children.

    The inherited sitecustomize installs the guard and imports the full
    application dependency stack in every child; with bytecode caching
    disabled that costs seconds per spawn. The fixtures are offline by
    construction and the parent process keeps its installed guard.
    """
    monkeypatch.delenv("PYTHONPATH", raising=False)


TESTS_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = TESTS_ROOT.parent
FIXTURE_CHILD = TESTS_ROOT / "fixtures" / "ag_oneshot" / "ag_child.py"
FIXTURE_GRAND_SPAWNER = TESTS_ROOT / "fixtures" / "ag_oneshot" / "ag_grand_spawner.py"


def child_argv(*args: str) -> list[str]:
    return [sys.executable, str(FIXTURE_CHILD), *args]


def test_quick_run_through_suspended_job_spawn():
    child = winjob.spawn_suspended_in_job(
        child_argv("quick", "7", "10", "4", "0"), str(REPOSITORY_ROOT)
    )
    try:
        assert child.uses_job is True
        assert child.pid_created_filetime is not None
        assert child.wait(timeout=20) == 7
        stdout = child.stdout.read()
        stderr = child.stderr.read()
        assert stdout == bytes((index * 31 + 7) % 256 for index in range(10))
        assert stderr == bytes((index * 31 + 7) % 256 for index in range(4))
    finally:
        assert child.close_job() is True


def test_assign_happens_before_resume(monkeypatch):
    order: list[str] = []
    real_assign = winjob.assign_to_job
    real_resume = winjob.resume_verified

    def recording_assign(job, proc):
        order.append("assign")
        return real_assign(job, proc)

    def recording_resume(proc):
        order.append("resume")
        return real_resume(proc)

    monkeypatch.setattr(winjob, "assign_to_job", recording_assign)
    monkeypatch.setattr(winjob, "resume_verified", recording_resume)
    child = winjob.spawn_suspended_in_job(
        child_argv("quick", "0", "0", "0", "0"), str(REPOSITORY_ROOT)
    )
    try:
        assert child.wait(timeout=20) == 0
    finally:
        child.close_job()
    assert order == ["assign", "resume"]


def test_externally_terminated_suspended_process_is_reported_and_reclaimed():
    job = winjob.create_kill_on_close_job()
    proc = None
    try:
        proc = winjob.spawn_suspended(child_argv("sleep", "60"), str(REPOSITORY_ROOT))
        # The test owns this process: termination through its own spawn handle.
        assert winjob._kernel.TerminateProcess(proc._handle, 1)
        proc.wait(timeout=10)
        with pytest.raises(AgWinJobError) as assign_error:
            winjob.assign_to_job(job, proc)
        assert assign_error.value.stage == "process_dead_before_assignment"
        with pytest.raises(AgWinJobError) as resume_error:
            winjob.resume_verified(proc)
        assert resume_error.value.stage == "process_dead_before_resume"
        assert winjob._reclaim_assigned(proc, job) is True
        assert proc.poll() is not None
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)
        winjob._kernel.CloseHandle(job)


@pytest.mark.parametrize(
    ("stage", "patch"),
    [
        ("assign_failed", "assign"),
        ("thread_ownership_mismatch", "ownership"),
        ("unexpected_suspend_count", "suspend_count"),
        ("thread_resume_failed", "resume_fail"),
        ("no_threads_found", "no_threads"),
        ("process_dead_before_assignment", "dead_on_spawn"),
    ],
)
def test_spawn_failures_reclaim_suspended_child(monkeypatch, stage: str, patch: str):
    spawn_calls: list[subprocess.Popen] = []
    real_spawn = winjob.spawn_suspended

    def tracked_spawn(argv, cwd):
        proc = real_spawn(argv, cwd)
        spawn_calls.append(proc)
        if patch == "dead_on_spawn":
            winjob._kernel.TerminateProcess(proc._handle, 1)
            proc.wait(timeout=10)
        return proc

    monkeypatch.setattr(winjob, "spawn_suspended", tracked_spawn)
    if patch == "assign":

        def failing_assign(job, proc):
            raise AgWinJobError("assign_failed")

        monkeypatch.setattr(winjob, "assign_to_job", failing_assign)
    elif patch == "ownership":
        monkeypatch.setattr(
            winjob._kernel, "GetProcessIdOfThread", lambda handle: 40000, raising=False
        )
    elif patch == "suspend_count":
        monkeypatch.setattr(winjob._kernel, "ResumeThread", lambda handle: 2, raising=False)
    elif patch == "resume_fail":
        monkeypatch.setattr(
            winjob._kernel, "ResumeThread", lambda handle: 0xFFFFFFFF, raising=False
        )
    elif patch == "no_threads":
        monkeypatch.setattr(winjob._kernel, "Thread32First", lambda *args: False, raising=False)

    with pytest.raises(AgWinJobError) as error:
        winjob.spawn_suspended_in_job(child_argv("sleep", "60"), str(REPOSITORY_ROOT))
    assert error.value.stage == stage
    assert "reclaimed=True" in error.value.detail
    assert spawn_calls and spawn_calls[0].poll() is not None


def test_job_create_failure_never_spawns(monkeypatch):
    spawn_attempts = []
    real_popen = subprocess.Popen

    def counting_popen(*args, **kwargs):
        spawn_attempts.append(args)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(winjob.subprocess, "Popen", counting_popen)
    monkeypatch.setattr(winjob._kernel, "CreateJobObjectW", lambda *args: None, raising=False)
    with pytest.raises(AgWinJobError) as error:
        winjob.spawn_suspended_in_job(child_argv("sleep", "60"), str(REPOSITORY_ROOT))
    assert error.value.stage == "job_create_failed"
    assert spawn_attempts == []


def test_job_channel_reclaims_non_self_exiting_pipe_holder():
    child = winjob.spawn_suspended_in_job(
        [sys.executable, str(FIXTURE_GRAND_SPAWNER)], str(REPOSITORY_ROOT)
    )
    try:
        marker = child.stdout.readline()
        assert marker.startswith(b"GRAND-PID ")
        assert child.wait(timeout=20) == 0
        time.sleep(0.3)
        # The grandchild (never self-exiting) keeps the stdout write end open.
        poller = child.stdout.raw
        assert poller is not None
        import threading

        state = {"eof": False}

        def reader():
            while True:
                data = child.stdout.raw.read(65536)
                if not data:
                    state["eof"] = True
                    return

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        thread.join(0.5)
        assert not state["eof"], "grandchild unexpectedly released the pipe"
        assert child.terminate_once() is True
        thread.join(5)
        assert state["eof"] is True
        assert not thread.is_alive()
    finally:
        child.terminate_once()
        child.wait(timeout=10)
        child.close_job()


# --- AG-CLI-CAPTURE-REPAIR-01 regression tests (written red first) ---


def test_wrapper_construction_exception_reclaims_everything(monkeypatch):
    spawn_calls = []
    real_spawn = winjob.spawn_suspended

    def tracked_spawn(argv, cwd):
        proc = real_spawn(argv, cwd)
        spawn_calls.append(proc)
        return proc

    class ExplodingWrapper:
        uses_job = True

        def __init__(self, proc, job):
            raise RuntimeError("SECRET-wrapper-construction")

    monkeypatch.setattr(winjob, "spawn_suspended", tracked_spawn)
    monkeypatch.setattr(winjob, "AgSuspendedJobProcess", ExplodingWrapper)
    with pytest.raises(RuntimeError):
        winjob.spawn_suspended_in_job(child_argv("sleep", "60"), str(REPOSITORY_ROOT))
    proc = spawn_calls[0]
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and proc.poll() is None:
        time.sleep(0.05)
    assert proc.poll() is not None, "suspended child leaked after wrapper failure"
    assert proc.stdout.closed is True
    assert proc.stderr.closed is True


def test_wrapper_handle_missing_reclaims_via_job(monkeypatch):
    spawn_calls = []
    real_spawn = winjob.spawn_suspended
    real_process_handle = winjob._process_handle
    calls = {"count": 0}

    def tracked_spawn(argv, cwd):
        proc = real_spawn(argv, cwd)
        spawn_calls.append(proc)
        return proc

    def handle_failing_on_wrapper(counter):
        def process_handle(proc):
            counter["count"] += 1
            if counter["count"] == 3:  # assign(1), resume(2), wrapper init(3)
                raise winjob.AgWinJobError("handle_unavailable")
            return real_process_handle(proc)

        return process_handle

    monkeypatch.setattr(winjob, "spawn_suspended", tracked_spawn)
    monkeypatch.setattr(winjob, "_process_handle", handle_failing_on_wrapper(calls))
    with pytest.raises(winjob.AgWinJobError) as error:
        winjob.spawn_suspended_in_job(child_argv("sleep", "60"), str(REPOSITORY_ROOT))
    assert error.value.stage == "handle_unavailable"
    proc = spawn_calls[0]
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and proc.poll() is None:
        time.sleep(0.05)
    assert proc.poll() is not None, "job termination did not reclaim the child"
    assert proc.stdout.closed is True
    assert proc.stderr.closed is True
