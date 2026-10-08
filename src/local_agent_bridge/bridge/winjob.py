"""Windows Job-channel spawn for the AG CLI oneshot capture core.

The only enabled descendant-reclamation form is a CREATE_SUSPENDED spawn,
Job assignment while no user code has run, then a verified thread resume
(design AG_CLI_LIFECYCLE_DESIGN_02/R3, probe P4). A process created
suspended can still be terminated externally, so the resume path never
trusts the suspended state alone: it gates on held-handle liveness checks,
thread-handle ownership verification (GetProcessIdOfThread compared with the
PID read from our own process handle) and the creation identity recorded from
the spawn handle. Failure triggers reclamation through our own handles and
Job closure. A failure after or during resume cannot establish non-execution;
reclamation does not reverse code that may already have run. There is no
fallback to a normal (non-suspended) spawn.

Error messages stay neutral: they never embed argv, prompt text, stream bytes
or host paths.
"""

from __future__ import annotations

import contextlib
import ctypes
import subprocess
import sys
from collections.abc import Mapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Literal

_WIN32 = sys.platform == "win32"

if _WIN32:
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel.SetInformationJobObject.restype = wintypes.BOOL
    _kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel.TerminateJobObject.restype = wintypes.BOOL
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel.TerminateProcess.restype = wintypes.BOOL
    _kernel.GetProcessId.argtypes = [wintypes.HANDLE]
    _kernel.GetProcessId.restype = wintypes.DWORD
    _kernel.GetProcessIdOfThread.argtypes = [wintypes.HANDLE]
    _kernel.GetProcessIdOfThread.restype = wintypes.DWORD
    _kernel.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        *([ctypes.POINTER(wintypes.FILETIME)] * 4),
    ]
    _kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel.WaitForSingleObject.restype = wintypes.DWORD
    _kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel.OpenThread.restype = wintypes.HANDLE
    _kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel.ResumeThread.restype = wintypes.DWORD
    _kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _kernel.Thread32First.restype = wintypes.BOOL
    _kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _kernel.Thread32Next.restype = wintypes.BOOL


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_CREATE_SUSPENDED = 0x00000004
_TH32CS_SNAPTHREAD = 0x4
_THREAD_SUSPEND_RESUME = 0x2
_THREAD_QUERY_LIMITED_INFORMATION = 0x0800
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_RESUME_FAILED = 0xFFFFFFFF
_RECLAIM_WAIT_SECONDS = 5.0

# Closed set of failure stages (FR-02 callers validate spawn faults against it).
AG_WINJOB_ERROR_STAGES = frozenset(
    {
        "job_create_failed",
        "job_config_failed",
        "spawn_failed",
        "handle_unavailable",
        "process_dead_before_assignment",
        "assign_failed",
        "thread_snapshot_failed",
        "process_dead_before_resume",
        "no_threads_found",
        "thread_open_failed",
        "thread_ownership_mismatch",
        "thread_resume_failed",
        "unexpected_suspend_count",
        "thread_close_failed",
    }
)


@dataclass
class LaunchLifecycle:
    """One spawn's execution fact, shared across native calls and receipt writing.

    Unknown reserves the single execution attempt; it is never permission to
    retry. Cleanup observations concern our own handles, not non-execution.
    """

    execution_state: Literal["not_attempted", "confirmed", "unknown"] = "not_attempted"
    stage: str = "not_attempted"
    pid: int | None = None
    pid_created_filetime: int | None = None
    child_exit_observed: bool | None = None
    pipes_closed: bool | None = None
    job_closed: bool | None = None
    thread_close_observations: list[bool | None] = field(default_factory=list)

    @property
    def launch_count(self) -> int | None:
        return {"not_attempted": 0, "confirmed": 1, "unknown": None}[self.execution_state]

    def begin_resume(self) -> str:
        previous_state = self.execution_state
        if previous_state != "confirmed":
            self.execution_state = "unknown"
        self.stage = "resume_call"
        return previous_state

    def observe_resume(self, previous_count: int, previous_state: str) -> None:
        if previous_count == 1:
            self.execution_state = "confirmed"
        elif self.execution_state != "confirmed" and (
            previous_count == _RESUME_FAILED or previous_count > 1
        ):
            # A reported failure or still-positive suspend count proves this
            # call did not resume the thread. A return of zero does not.
            self.execution_state = previous_state
        self.stage = "resume_observed"

    def record(self) -> dict[str, object]:
        return {
            "spawn_state": self.execution_state,
            "launch_count": self.launch_count,
            "stage": self.stage,
            "pid": self.pid,
            "pid_created_filetime": self.pid_created_filetime,
            "cleanup": {
                "child_exit_observed": self.child_exit_observed,
                "pipes_closed": self.pipes_closed,
                "job_closed": self.job_closed,
                "thread_close_observations": list(self.thread_close_observations),
            },
        }


class AgWinJobError(RuntimeError):
    """Narrow winjob failure with a closed-set stage name and neutral detail."""

    def __init__(self, stage: str, detail: str = "") -> None:
        message = f"ag winjob failure: {stage}"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)
        self.stage = stage
        self.detail = detail
        self.lifecycle: LaunchLifecycle | None = None


def _process_handle(proc: subprocess.Popen) -> int:
    # CPython Windows implementation attribute (R3 2.4; version-locked 3.13).
    handle = getattr(proc, "_handle", None)
    if not handle:
        raise AgWinJobError("handle_unavailable")
    return int(handle)


def _liveness(handle: int) -> str:
    """Classify a held process handle: alive, exited or unknown."""
    wait = _kernel.WaitForSingleObject(handle, 0)
    if wait == _WAIT_OBJECT_0:
        return "exited"
    if wait == _WAIT_TIMEOUT:
        return "alive"
    return "unknown"


def handle_pid(handle: int) -> int:
    """PID read from our own handle, never from a PID-based lookup."""
    pid = int(_kernel.GetProcessId(handle))
    if not pid:
        raise AgWinJobError("handle_unavailable", "GetProcessId")
    return pid


def process_created_filetime(handle: int) -> int | None:
    """Creation FILETIME via the spawn handle (P3); None records unknown."""
    created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
    if not _kernel.GetProcessTimes(
        handle,
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time),
    ):
        return None
    return (created.dwHighDateTime << 32) | created.dwLowDateTime


def create_kill_on_close_job() -> int:
    """Create a Job handle with kill-on-close semantics (P4 mechanism)."""
    job = _kernel.CreateJobObjectW(None, None)
    if not job:
        raise AgWinJobError("job_create_failed", f"last_error={ctypes.get_last_error()}")
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _kernel.SetInformationJobObject(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        error = ctypes.get_last_error()
        _kernel.CloseHandle(job)
        raise AgWinJobError("job_config_failed", f"last_error={error}")
    return int(job)


def spawn_suspended(
    argv: Sequence[str], cwd: str, *, env: Mapping[str, str] | None = None
) -> subprocess.Popen:
    """Spawn a suspended, hidden-window child with piped stdio."""
    try:
        return subprocess.Popen(
            list(argv),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW,
            env=env,
        )
    except OSError as error:
        raise AgWinJobError("spawn_failed", type(error).__name__) from error


def assign_to_job(job: int, proc: subprocess.Popen) -> None:
    """Assign the still-suspended child to the Job before any user code runs."""
    handle = _process_handle(proc)
    if handle is not None and _liveness(handle) == "exited":
        raise AgWinJobError("process_dead_before_assignment")
    if not _kernel.AssignProcessToJobObject(job, handle):
        if _liveness(handle) == "exited":
            raise AgWinJobError("process_dead_before_assignment")
        raise AgWinJobError("assign_failed", f"last_error={ctypes.get_last_error()}")


def _snapshot_thread_ids(pid: int) -> list[int]:
    snapshot = _kernel.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snapshot:
        raise AgWinJobError("thread_snapshot_failed", f"last_error={ctypes.get_last_error()}")
    identifiers: list[int] = []
    try:
        entry = _THREADENTRY32()
        entry.dwSize = ctypes.sizeof(_THREADENTRY32)
        if _kernel.Thread32First(snapshot, ctypes.byref(entry)):
            while True:
                if entry.th32OwnerProcessID == pid:
                    identifiers.append(entry.th32ThreadID)
                if not _kernel.Thread32Next(snapshot, ctypes.byref(entry)):
                    break
    finally:
        _kernel.CloseHandle(snapshot)
    return identifiers


def resume_verified(proc: subprocess.Popen, *, lifecycle: LaunchLifecycle | None = None) -> None:
    """Resume the suspended child after proving safe ownership.

    Every thread located through the snapshot is re-verified through its own
    opened handle (GetProcessIdOfThread must match the PID read from our held
    process handle), so a reused thread ID can never make us resume a foreign
    thread. A suspended process can be terminated externally at any moment, so
    liveness is rechecked from the held handle at each failure boundary and a
    dead process is reported as such instead of being treated as an error.
    """
    lifecycle = lifecycle if lifecycle is not None else LaunchLifecycle()
    lifecycle.stage = "resume_verify"
    handle = _process_handle(proc)
    pid = handle_pid(handle)
    if _liveness(handle) != "alive":
        raise AgWinJobError("process_dead_before_resume")
    identifiers = _snapshot_thread_ids(pid)
    if not identifiers:
        if _liveness(handle) == "exited":
            raise AgWinJobError("process_dead_before_resume")
        raise AgWinJobError("no_threads_found")
    open_rights = _THREAD_SUSPEND_RESUME | _THREAD_QUERY_LIMITED_INFORMATION
    for thread_id in identifiers:
        thread = _kernel.OpenThread(open_rights, False, thread_id)
        if not thread:
            if _liveness(handle) == "exited":
                raise AgWinJobError("process_dead_before_resume")
            raise AgWinJobError("thread_open_failed", f"last_error={ctypes.get_last_error()}")
        resume_error: BaseException | None = None
        try:
            owner_pid = int(_kernel.GetProcessIdOfThread(thread))
            if owner_pid != pid:
                raise AgWinJobError("thread_ownership_mismatch")
            previous_state = lifecycle.begin_resume()
            previous = int(_kernel.ResumeThread(thread))
            lifecycle.observe_resume(previous, previous_state)
            if previous == _RESUME_FAILED:
                raise AgWinJobError("thread_resume_failed", f"last_error={ctypes.get_last_error()}")
            if previous != 1:
                # The initial CREATE_SUSPENDED thread must present suspend count 1;
                # anything else means another actor already manipulated it. Fail closed.
                raise AgWinJobError("unexpected_suspend_count", f"prev={previous}")
        except BaseException as error:
            resume_error = error
            raise
        finally:
            closed = None
            try:
                if resume_error is None:
                    lifecycle.stage = "resume_thread_close"
                closed = bool(_kernel.CloseHandle(thread))
                if not closed and resume_error is None:
                    raise AgWinJobError("thread_close_failed")
            except BaseException:
                if resume_error is None:
                    raise
            finally:
                lifecycle.thread_close_observations.append(closed)


def _close_child_pipes(proc: subprocess.Popen) -> bool:
    """Close each parent pipe independently after its readers have stopped."""
    closed = True
    interrupted: BaseException | None = None
    for stream in (proc.stdout, proc.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except BaseException as error:
            closed = False
            if not isinstance(error, OSError) and interrupted is None:
                interrupted = error
    if interrupted is not None:
        raise interrupted
    return closed


def _reclaim_assigned(proc: subprocess.Popen, job: int) -> bool:
    """Reclaim the child through its own handles; the Job covers a missing _handle.

    After a successful assign the child is inside the Job, so TerminateJobObject
    reaches it even when the process handle is unavailable to this module. No
    PID-based lookup is ever used, and a child that was already resumed is
    never claimed to have not run.
    """
    try:
        handle = _process_handle(proc)
    except AgWinJobError:
        handle = None
    if handle is not None and _liveness(handle) == "exited":
        with contextlib.suppress(Exception):
            proc.wait(timeout=_RECLAIM_WAIT_SECONDS)
        return True
    terminated = False
    if handle is not None:
        terminated = bool(_kernel.TerminateProcess(handle, 1))
    if not terminated:
        terminated = bool(_kernel.TerminateJobObject(job, 1))
    try:
        proc.wait(timeout=_RECLAIM_WAIT_SECONDS)
    except Exception:
        return False
    if handle is None:
        return terminated
    return _liveness(handle) == "exited"


class AgSuspendedJobProcess:
    """Child wrapper for a verified suspended spawn pre-assigned to a Job."""

    uses_job = True

    def __init__(
        self, proc: subprocess.Popen, job: int, *, lifecycle: LaunchLifecycle | None = None
    ) -> None:
        self._proc = proc
        self._job = job
        self._job_closed = False
        self.lifecycle = lifecycle if lifecycle is not None else LaunchLifecycle()
        handle = _process_handle(proc)
        self.pid = handle_pid(handle)
        self.lifecycle.pid = self.pid
        self.pid_created_filetime = process_created_filetime(handle)
        self.lifecycle.pid_created_filetime = self.pid_created_filetime

    @property
    def stdout(self):
        return self._proc.stdout

    @property
    def stderr(self):
        return self._proc.stderr

    @property
    def returncode(self) -> int | None:
        return self._proc.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self._proc.wait(timeout=timeout)

    def poll(self) -> int | None:
        return self._proc.poll()

    def process_alive(self) -> bool | None:
        """Held-handle liveness; None records an unknown state."""
        try:
            handle = _process_handle(self._proc)
        except AgWinJobError:
            return None
        state = _liveness(handle)
        return None if state == "unknown" else state == "alive"

    def terminate_once(self) -> bool:
        """One explicit termination round over our own Job handle."""
        if self._job_closed or not self._job:
            return False
        return bool(_kernel.TerminateJobObject(self._job, 1))

    def close_job(self) -> bool:
        """Close our Job handle; kill-on-close semantics may reclaim stragglers."""
        if self._job_closed or not self._job:
            return False
        closed = bool(_kernel.CloseHandle(self._job))
        if closed:
            self._job_closed = True
        return closed


def spawn_suspended_in_job(
    argv: Sequence[str],
    cwd: str,
    *,
    lifecycle: LaunchLifecycle | None = None,
    env: Mapping[str, str] | None = None,
) -> AgSuspendedJobProcess:
    """Production spawner: suspended spawn -> pre-execution Job ownership -> verified resume.

    Failures attempt reclamation through our own handle and close the Job.
    A resumed child may have executed before a later failure; an interrupted
    native resume can have an unobserved result. Neither an exception nor
    successful reclamation proves non-execution. No normal-spawn fallback.
    """
    lifecycle = lifecycle if lifecycle is not None else LaunchLifecycle()
    job = proc = None
    try:
        lifecycle.stage = "job_create"
        job = create_kill_on_close_job()
        lifecycle.stage = "suspended_spawn"
        proc = spawn_suspended(argv, cwd) if env is None else spawn_suspended(argv, cwd, env=env)
        lifecycle.stage = "assign_job"
        assign_to_job(job, proc)
        lifecycle.stage = "prepare_identity"
        wrapper = AgSuspendedJobProcess(proc, job, lifecycle=lifecycle)
        resume_verified(proc, lifecycle=lifecycle)
        lifecycle.stage = "wrapper_handoff"
        return wrapper
    except BaseException as error:
        # Every cleanup is independent and must preserve the original failure,
        # including an interrupt. None means the result was not observed.
        if proc is not None:
            with contextlib.suppress(BaseException):
                lifecycle.child_exit_observed = _reclaim_assigned(proc, job)
            with contextlib.suppress(BaseException):
                lifecycle.pipes_closed = _close_child_pipes(proc)
        if job is not None:
            with contextlib.suppress(BaseException):
                lifecycle.job_closed = bool(_kernel.CloseHandle(job))
        if isinstance(error, AgWinJobError):
            error.lifecycle = lifecycle
            error.detail = (
                f"{error.detail};" if error.detail else ""
            ) + f"reclaimed={lifecycle.child_exit_observed}"
        raise
