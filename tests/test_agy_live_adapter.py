"""Child environment and progress delivery; only synthetic/fake process boundaries."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from test_task_run import plan, prepare, run

from local_agent_bridge.bridge import slice_run, task_run, task_workspace, winjob


@pytest.mark.parametrize("previous", [None, "1", "false", "true"])
@pytest.mark.parametrize("failure", [None, OSError, KeyboardInterrupt, SystemExit])
def test_child_environment_reaches_popen_without_parent_mutation(monkeypatch, previous, failure):
    name = slice_run.AUTO_UPDATE_VARIABLE
    if previous is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, previous)
    monkeypatch.setenv("LAB_SYNTHETIC_INHERITED", "parent-value")
    child = slice_run._agy_child_environment()
    original = failure("SENSITIVE") if failure else None

    def popen(argv, **kwargs):
        assert kwargs["env"][name] == "true"
        assert kwargs["env"]["LAB_SYNTHETIC_INHERITED"] == "parent-value"
        assert kwargs["creationflags"] & winjob._CREATE_SUSPENDED
        # A concurrent parent change must never be overwritten by a restoration.
        os.environ[name] = "concurrent-value"
        if original:
            raise original
        return "fake-process"

    monkeypatch.setattr(winjob.subprocess, "Popen", popen)
    if failure:
        expected = winjob.AgWinJobError if failure is OSError else failure
        with pytest.raises(expected) as caught:
            winjob.spawn_suspended(["synthetic.exe"], "synthetic", env=child)
        if failure is not OSError:
            assert caught.value is original
    else:
        assert winjob.spawn_suspended(["synthetic.exe"], "synthetic", env=child) == "fake-process"
    assert os.environ[name] == "concurrent-value"
    assert child[name] == "true"


def test_parallel_task_environment_copies_are_independent(monkeypatch):
    monkeypatch.setenv(slice_run.AUTO_UPDATE_VARIABLE, "parent")
    with ThreadPoolExecutor(max_workers=4) as pool:
        copies = list(pool.map(lambda _: slice_run._agy_child_environment(), range(16)))
    assert len({id(item) for item in copies}) == 16
    assert all(item[slice_run.AUTO_UPDATE_VARIABLE] == "true" for item in copies)
    copies[0][slice_run.AUTO_UPDATE_VARIABLE] = "changed-child"
    assert copies[1][slice_run.AUTO_UPDATE_VARIABLE] == "true"
    assert os.environ[slice_run.AUTO_UPDATE_VARIABLE] == "parent"


@pytest.mark.parametrize("host", ["agy", "cursor"])
def test_task_launch_delivers_environment_and_progress(tmp_path, monkeypatch, host):
    case = prepare(tmp_path, monkeypatch, host=host)
    frozen = plan(case)
    observed = []

    def capture(*args, **kwargs):
        observed.append((args, kwargs))
        raise KeyboardInterrupt("SENSITIVE")

    monkeypatch.setattr(slice_run, "_launch_and_capture", capture)
    with pytest.raises(KeyboardInterrupt):
        run(case, frozen, tmp_path / "interrupted", execute=True)
    args, kwargs = observed[0]
    environment = kwargs["env"]
    assert (environment[slice_run.AUTO_UPDATE_VARIABLE] if host == "agy" else environment) == (
        "true" if host == "agy" else None
    )
    request = args[1][args[1].index("--print") + 1] if host == "agy" else None
    # Test the shared request independently of each host's argv spelling.
    if request is None:
        context = {
            "task": case.task,
            "bundle": {"authorization": case.auth},
            "note": b"Synthetic note",
        }
        request = task_run._request(context)
    controls = json.loads(request.splitlines()[1])
    progress = controls["progress_contract"]
    assert progress["exact_fields"] == [
        "contract_version",
        "task_id",
        "status",
        "summary",
        "remaining_paths",
    ]
    assert progress["status_enum"] == ["Completed", "Partial", "Blocked"]
    assert progress["task_id"] == case.task["task_id"]
    assert "not management Accepted" in request


def test_job_spawner_forwards_child_environment(monkeypatch):
    environment = {slice_run.AUTO_UPDATE_VARIABLE: "true"}
    process = SimpleNamespace()
    seen = []
    monkeypatch.setattr(winjob, "create_kill_on_close_job", lambda: 12)
    monkeypatch.setattr(winjob, "spawn_suspended", lambda *a, **kw: seen.append(kw) or process)
    monkeypatch.setattr(winjob, "assign_to_job", lambda *a: None)
    monkeypatch.setattr(winjob, "resume_verified", lambda *a, **kw: None)
    monkeypatch.setattr(winjob, "AgSuspendedJobProcess", lambda *a, **kw: "wrapper")
    assert winjob.spawn_suspended_in_job(["synthetic"], "synthetic", env=environment) == "wrapper"
    assert seen == [{"env": environment}]


def test_collector_still_rejects_candidate_progress(tmp_path):
    (tmp_path / "out").mkdir()
    task = {"task_id": "synthetic", "contract_version": 1}
    progress = {**task, "status": "Candidate", "summary": "synthetic", "remaining_paths": []}
    (tmp_path / "out/progress.json").write_text(json.dumps(progress), encoding="utf-8")
    blockers = []
    assert task_workspace._progress(tmp_path, task, blockers) is None
    assert blockers == ["ProgressInvalid"]
