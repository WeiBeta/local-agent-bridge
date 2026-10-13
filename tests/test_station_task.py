"""Complete dispatch chain with real importer/collector and synthetic host capture."""

from __future__ import annotations

import copy
import io
import json
import multiprocessing
import os
import subprocess
import threading
import uuid
from pathlib import Path

import pytest
import test_station_pool as pool_fixtures
import test_task_run as fixtures

from local_agent_bridge import cli
from local_agent_bridge.bridge import station_pool, station_task, task_workspace
from local_agent_bridge.bridge import task_run as runner


def configured(tmp_path, monkeypatch, shape="Coding", count=4):
    case = fixtures.prepare(tmp_path, monkeypatch, actual_b=True, publish=False)
    path, pin, document = pool_fixtures.registry(tmp_path, count, case.receipt)
    note = tmp_path / "frozen-task.md"
    note.write_text("Synthetic isolated task token " + str(uuid.uuid4()), encoding="utf-8")
    fields = {key: copy.deepcopy(case.task[key]) for key in station_task._TASK_FIELDS}
    fields["read_roots"] = ["out", "scratch", "work"]
    fields["protected_paths"] = ["work"] if shape in {"Review", "Testing"} else []
    fields["write_roots"] = (
        ["out", "scratch"] if shape in {"Review", "Testing"} else ["out", "scratch", "work"]
    )
    fields["role"] = "Review" if shape == "Review" else "Coding"
    if shape == "Review":
        fields["required_outputs"] += ["out/coverage.json", "out/findings.json", "out/report.md"]
        fields["required_outputs"].sort()
    spec = {
        "cli_contract_version": 1,
        "source": {
            "kind": "zip",
            "path": str(tmp_path / "input.zip"),
            "sha256": runner._digest((tmp_path / "input.zip").read_bytes()),
            "strip_prefix": None,
        },
        "policy": {
            "source_paths": ["source.py"],
            "excluded_paths": [],
            "sensitive_paths": [],
            "trusted_control_files": {},
        },
        "instructions_path": str(note),
        "instructions_sha256": runner._digest(note.read_bytes()),
        "task": fields,
        "admission_timeout_seconds": 2,
    }
    return case, path, pin, document, spec


def read(path):
    return json.loads(Path(path).read_bytes())


def install_host(
    case,
    monkeypatch,
    *,
    shape="Coding",
    closed=True,
    exit_code=0,
    conversation="valid",
    before_complete=None,
):
    calls = []

    class Process(fixtures.FakeProcess):
        def close_job(self):
            self.closed = True
            return closed

    def spawn(argv, cwd, *, lifecycle, env=None):
        root = Path(cwd)
        task = read(root / "task.json")
        request = argv[argv.index("--print") + 1]
        controls = json.loads(request.split("\nFrozen task note:\n")[0].splitlines()[-1])
        assert controls["task_root"] == root.as_posix()
        assert controls["tool_working_directory"] == (root / "work").as_posix()
        assert controls["progress_contract"]["path"] == (root / "out/progress.json").as_posix()
        assert Path(controls["station_root"]) == root.parent.parent
        assert "--resume" not in argv
        cid = str(uuid.uuid4())
        calls.append({"root": root, "argv": argv, "cid": cid, "task": task, "controls": controls})
        if before_complete is not None:
            before_complete(root)
        token = task["task_id"]
        if shape in {"Coding", "Mixed"}:
            (root / "work/source.py").write_bytes(b"n = 1\r\n")
        (root / "out/worker-facts.json").write_bytes(
            fixtures.canonical({"token": token, "test_failures": 1 if shape == "Testing" else 0})
        )
        fixtures.write_json(
            root / "out/progress.json",
            {
                "contract_version": 1,
                "task_id": token,
                "status": "Completed",
                "summary": "Synthetic expected red"
                if shape == "Testing"
                else "Synthetic completed",
                "remaining_paths": [],
            },
        )
        if shape == "Review":
            common = {"contract_version": 1, "task_id": token, "snapshot_id": task["snapshot_id"]}
            fixtures.write_json(
                root / "out/coverage.json",
                {
                    **common,
                    "entries": [{"path": "source.py", "state": "Analyzed", "reason": "read"}],
                    "package_entry_count": 1,
                    "source_file_count": 1,
                },
            )
            fixtures.write_json(
                root / "out/findings.json",
                {
                    **common,
                    "findings": [
                        {
                            "id": "SYNTHETIC-P2",
                            "severity": "P2",
                            "file": "source.py",
                            "line": 1,
                            "evidence": "n = 0",
                            "recommendation": "Report this candidate finding",
                        }
                    ],
                },
            )
            (root / "out/report.md").write_text("Synthetic Review finding", encoding="utf-8")
            (root / "scratch/review-copy.py").write_bytes((root / "work/source.py").read_bytes())
        lifecycle.execution_state = "confirmed"
        lifecycle.pid = 9183
        process = Process(exit_code=exit_code)
        initial = {
            "event": "init",
            "conversation_id": cid,
            "init": {
                "cwd": str(root),
                "model": runner._ROUTES["agy"]["model"],
                "permission_mode": "synthetic-only",
            },
        }
        if conversation == "wrong_cwd":
            initial["init"]["cwd"] = str(root.parent.parent)
        events = [
            initial,
            {
                "event": "result",
                "result": {
                    "conversation_id": str(uuid.uuid4()) if conversation == "foreign" else cid,
                    "status": "SUCCESS" if exit_code == 0 else "ERROR",
                },
            },
        ]
        if conversation == "missing":
            events = []
        process.stdout = io.BytesIO(b"".join(fixtures.canonical(event) + b"\n" for event in events))
        return process

    monkeypatch.setattr(fixtures.slice_run, "spawn_suspended_in_job", spawn)
    return calls


def dispatch(path, pin, spec, **kwargs):
    return station_task.dispatch_task(spec=spec, registry_path=path, registry_sha256=pin, **kwargs)


@pytest.mark.parametrize("shape", ["Coding", "Testing", "Mixed", "Review"])
@pytest.mark.parametrize("slot", range(4))
def test_every_station_runs_all_four_shapes_without_borrowing_acceptance(
    tmp_path, monkeypatch, shape, slot
):
    case, path, pin, document, spec = configured(tmp_path, monkeypatch, shape)
    # Reordering registry entries proves role eligibility is not A/B or ordinal hardcoding.
    entries = document["stations"]
    document["stations"] = entries[slot:] + entries[:slot]
    pin = pool_fixtures.save_registry(path, document)
    calls = install_host(case, monkeypatch, shape=shape, exit_code=1 if shape == "Testing" else 0)
    outcome = dispatch(path, pin, spec, execute=True)
    assert outcome["status"] == "Collected", outcome
    assert outcome["station_id"] == entries[slot]["id"]
    assert outcome["launch_count"] == 1 and len(calls) == 1
    assert outcome["control_complete"] and outcome["release_state"] == "Released"
    assert outcome["management_decision"] is None
    root, result = Path(outcome["task_root"]), Path(outcome["result_root"])
    receipt = read(root / "control/deployment-receipt.json")
    assert receipt["contract_version"] == 4 and receipt["runtime_acceptances"] == []
    assert read(root / "control/plan.json")["preflight_status"] == "Ready"
    assert outcome["native_conversation"]["conversation_id"] == calls[0]["cid"]
    assert outcome["native_conversation"]["status"] == "Observed"
    assert outcome["run"]["capture_uid"] != calls[0]["cid"]
    assert result.is_dir()
    assert read(outcome["terminal_path"])["release_state"] == "Released"
    if shape in {"Review", "Testing"}:
        assert (root / "work/source.py").read_bytes() == b"n = 0\r\n"
    if shape == "Testing":
        assert read(root / "out/worker-facts.json")["test_failures"] == 1
        assert outcome["run"]["transport_state"] == "Failed"
    if shape == "Review":
        assert read(root / "out/findings.json")["findings"][0]["severity"] == "P2"
        assert outcome["business"]["worker_status"] == "Completed"


def test_reuse_has_fresh_job_note_conversation_capture_and_result_without_touching_old(
    tmp_path, monkeypatch
):
    case, path, pin, _document, spec = configured(tmp_path, monkeypatch, count=1)
    calls = install_host(case, monkeypatch)
    first = dispatch(path, pin, spec, execute=True)
    assert first["status"] == "Collected", first
    old = Path(first["task_root"])
    before = {
        str(item.relative_to(old)): item.read_bytes() for item in old.rglob("*") if item.is_file()
    }
    note = Path(spec["instructions_path"])
    note.write_bytes(b"second-isolated-frozen-token")
    spec["instructions_sha256"] = runner._digest(note.read_bytes())
    second = dispatch(path, pin, spec, execute=True)
    assert second["status"] == "Collected", second
    for field in ("request_id", "task_root", "result_root", "terminal_path"):
        assert first[field] != second[field]
    assert first["station_id"] == second["station_id"]
    assert first["run"]["capture_uid"] != second["run"]["capture_uid"]
    assert (
        first["native_conversation"]["conversation_id"]
        != second["native_conversation"]["conversation_id"]
    )
    assert len(calls) == 2
    assert before == {
        str(item.relative_to(old)): item.read_bytes() for item in old.rglob("*") if item.is_file()
    }
    second_root = Path(second["task_root"])
    assert (second_root / "control/TASK.md").read_bytes() == b"second-isolated-frozen-token"
    assert first["request_id"] not in (second_root / "out/worker-facts.json").read_text()
    assert second["request_id"] not in (old / "out/worker-facts.json").read_text()


def test_job_collects_releases_while_sibling_is_still_running(tmp_path, monkeypatch):
    case, path, pin, document, spec = configured(tmp_path, monkeypatch)
    configured_pool = station_pool.load_registry(path, pin)
    sibling_ready, sibling_release = threading.Event(), threading.Event()
    sibling = {}

    def hold_sibling():
        manager = station_pool.Pool(configured_pool)
        lease = manager.acquire(str(uuid.uuid4()))
        sibling["lease"] = lease
        sibling_ready.set()
        assert sibling_release.wait(15)
        lease.finish(control_complete=True, terminal=pool_fixtures.terminal(lease))
        manager.close()

    thread = threading.Thread(target=hold_sibling)
    thread.start()
    try:
        assert sibling_ready.wait(8)
        install_host(case, monkeypatch)
        outcome = dispatch(path, pin, spec, execute=True)
        assert outcome["status"] == "Collected", outcome
        assert outcome["station_id"] != sibling["lease"].station.id
        state = read(
            Path(document["control_root"]) / "states" / (sibling["lease"].station.id + ".json")
        )
        assert state["state"] == "Reserved" and thread.is_alive()
    finally:
        sibling_release.set()
        thread.join(10)
    assert not thread.is_alive()


def test_unconfirmed_capture_cleanup_suspends_only_own_slot_then_other_completes(
    tmp_path, monkeypatch
):
    case, path, pin, _document, spec = configured(tmp_path, monkeypatch)
    calls = install_host(case, monkeypatch, closed=False)
    failed = dispatch(path, pin, spec, execute=True)
    assert failed["launch_count"] == 1 and len(calls) == 1
    assert not failed["control_complete"] and failed["release_state"] == "Suspended", failed
    install_host(case, monkeypatch)
    other = dispatch(path, pin, spec, execute=True)
    assert other["status"] == "Collected", other
    assert other["station_id"] != failed["station_id"]


def test_prelaunch_import_failure_releases_without_key_or_host_retry(tmp_path, monkeypatch):
    _case, path, pin, _document, spec = configured(tmp_path, monkeypatch, count=1)
    monkeypatch.setattr(fixtures.slice_run, "_session_store", lambda: pytest.fail("key load"))
    monkeypatch.setattr(
        fixtures.slice_run, "spawn_suspended_in_job", lambda *a, **k: pytest.fail("host")
    )
    spec["source"]["sha256"] = "0" * 64
    outcome = dispatch(path, pin, spec, execute=True)
    assert outcome["status"] == "Stopped" and outcome["launch_count"] == 0
    assert outcome["release_state"] == "Released", outcome


def test_collection_failure_after_closed_host_is_not_lost_control(tmp_path, monkeypatch):
    case, path, pin, _document, spec = configured(tmp_path, monkeypatch, count=1)
    calls = install_host(case, monkeypatch)

    def bad_collect(**kwargs):
        raise task_workspace.TaskWorkspaceError("SyntheticCollectionFailed", "synthetic failure")

    monkeypatch.setattr(task_workspace, "collect_task", bad_collect)
    outcome = dispatch(path, pin, spec, execute=True)
    assert outcome["status"] == "Stopped" and len(calls) == 1
    assert outcome["launch_count"] == 1 and outcome["release_state"] == "Released", outcome
    assert "SyntheticCollectionFailed" in outcome["blockers"]


@pytest.mark.parametrize(
    "conversation,expected",
    [("missing", "Unknown"), ("wrong_cwd", "Mismatch"), ("foreign", "Mismatch")],
)
def test_conversation_unknown_or_mismatch_does_not_claim_isolation(
    tmp_path, monkeypatch, conversation, expected
):
    case, path, pin, _document, spec = configured(tmp_path, monkeypatch, count=1)
    install_host(case, monkeypatch, conversation=conversation)
    outcome = dispatch(path, pin, spec, execute=True)
    assert outcome["native_conversation"]["status"] == expected, outcome
    assert outcome["release_state"] == "Released"
    if expected == "Unknown":
        assert outcome["native_conversation"]["conversation_id"] is None


def test_low_level_station_run_requires_current_lease_before_key_or_run_root(tmp_path, monkeypatch):
    _case, path, pin, _document, spec = configured(tmp_path, monkeypatch, count=1)
    configured_pool = station_pool.load_registry(path, pin)
    manager = station_pool.Pool(configured_pool)
    lease = manager.acquire(str(uuid.uuid4()))
    request = configured_pool["control_root"] / "requests" / lease.request_id
    request.mkdir(parents=True)
    try:
        context = station_task._materialize(
            lease, station_task.validate_spec(spec, configured_pool["document"]["policy"]), request
        )
        monkeypatch.setattr(fixtures.slice_run, "_session_store", lambda: pytest.fail("key load"))
        with pytest.raises(runner.TaskRunError, match="StationLeaseRequired"):
            runner.run_task(
                task_root=context["task_root"],
                plan=context["plan"],
                run_root=request / "run",
                trusted_control_root=context["trusted"],
                trusted_inputs_sha256=context["trusted_sha256"],
                execute=True,
            )
        assert not (request / "run").exists()
        lease.finish(control_complete=True, terminal=pool_fixtures.terminal(lease))
    finally:
        if not lease.closed:
            lease.abandon()
        manager.close()


def test_cli_dry_run_reads_frozen_spec_but_no_lock_import_job_key_or_host(
    tmp_path, monkeypatch, capsys
):
    _case, path, pin, document, spec = configured(tmp_path, monkeypatch)
    monkeypatch.setattr(station_pool, "Pool", lambda *a, **k: pytest.fail("mutex"))
    monkeypatch.setattr(
        station_task.task_input, "import_snapshot", lambda **k: pytest.fail("import")
    )
    monkeypatch.setattr(fixtures.slice_run, "_session_store", lambda: pytest.fail("key"))
    spec_path = tmp_path / "dispatch-spec.json"
    fixtures.write_json(spec_path, spec)
    args = [
        "task",
        "dispatch",
        "--spec",
        str(spec_path),
        "--pool-registry",
        str(path),
        "--pool-sha256",
        pin,
    ]
    assert cli.main(args) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["status"] == "PreparedOnly" and value["launch_count"] == 0
    assert not (Path(document["control_root"]) / "requests").exists()
    assert all(not (Path(entry["root"]) / "jobs").exists() for entry in document["stations"])
    assert cli.main([*args, "--model", "unapproved-model"]) == 2
    assert "CliArgumentsInvalid" in capsys.readouterr().err


def test_native_policy_drift_suspends_but_benign_metadata_is_allowed(tmp_path, monkeypatch):
    case, path, pin, document, spec = configured(tmp_path, monkeypatch)
    record = Path(document["stations"][0]["record"])

    def benign(_root):
        value = read(record)
        value["displayName"] = "benign synthetic metadata"
        fixtures.write_json(record, value)

    install_host(case, monkeypatch, before_complete=benign)
    first = dispatch(path, pin, spec, execute=True)
    assert first["release_state"] == "Released", first

    def policy_change(_root):
        value = read(record)
        value["permissionGrants"] = {"mode": "changed"}
        fixtures.write_json(record, value)

    install_host(case, monkeypatch, before_complete=policy_change)
    second = dispatch(path, pin, spec, execute=True)
    assert second["release_state"] == "Suspended" and second["launch_count"] == 1, second
    assert "StationNativePolicyChanged" in second["blockers"]


def test_dispatch_full_capacity_stops_before_import_task_grant_or_key(tmp_path, monkeypatch):
    _case, path, pin, document, spec = configured(tmp_path, monkeypatch)
    context = multiprocessing.get_context("spawn")
    owners = []
    try:
        for _ in range(4):
            owner = pool_fixtures.start_owner(context, path, pin)
            owners.append(owner)
            assert owner[1].wait(12)
            owner[3].recv()
        monkeypatch.setattr(
            station_task.task_input,
            "import_snapshot",
            lambda **k: pytest.fail("import before admission"),
        )
        monkeypatch.setattr(
            station_task, "_materialize", lambda *a, **k: pytest.fail("task grant before admission")
        )
        monkeypatch.setattr(
            fixtures.slice_run, "_session_store", lambda: pytest.fail("key before admission")
        )
        spec["admission_timeout_seconds"] = 0
        outcome = dispatch(path, pin, spec, execute=True)
        assert outcome["launch_count"] == 0 and outcome["task_root"] is None
        assert outcome["release_state"] == "NotAcquired"
        assert outcome["blockers"] == ["StationCapacityWaitExpired"]
        terminal_root = Path(outcome["terminal_path"]).parent
        assert {entry.name for entry in terminal_root.iterdir()} == {
            "dispatch.json",
            "dispatch-final.json",
        }
        assert (
            sum(len(list(Path(entry["root"]).glob("jobs/*"))) for entry in document["stations"])
            == 4
        )
    finally:
        pool_fixtures.finish_owners(owners)


def test_two_complete_chains_collect_in_own_terminal_order(tmp_path, monkeypatch):
    case, path, pin, _document, spec = configured(tmp_path, monkeypatch)
    held, proceed = threading.Event(), threading.Event()
    first_thread = threading.current_thread()
    results = {}
    errors = []

    def hold_first(_root):
        if threading.current_thread() is not first_thread:
            held.set()
            assert proceed.wait(20)

    calls = install_host(case, monkeypatch, before_complete=hold_first)

    def first_dispatch():
        try:
            results["first"] = dispatch(path, pin, copy.deepcopy(spec), execute=True)
        except BaseException as error:
            errors.append(type(error).__name__)

    thread = threading.Thread(target=first_dispatch)
    thread.start()
    try:
        assert held.wait(10)
        results["second"] = dispatch(path, pin, copy.deepcopy(spec), execute=True)
        assert results["second"]["status"] == "Collected", results["second"]
        assert "first" not in results and thread.is_alive()
        assert Path(results["second"]["terminal_path"]).is_file()
    finally:
        proceed.set()
        thread.join(15)
    assert not thread.is_alive() and not errors
    assert results["first"]["status"] == "Collected", results["first"]
    assert len(calls) == 2
    for field in ("station_id", "task_root", "result_root"):
        assert results["first"][field] != results["second"][field]
    assert results["first"]["run"]["capture_uid"] != results["second"]["run"]["capture_uid"]
    assert (
        results["first"]["native_conversation"]["conversation_id"]
        != results["second"]["native_conversation"]["conversation_id"]
    )


def test_admitted_task_uses_frozen_spec_and_one_existing_capture_key_load(tmp_path, monkeypatch):
    case, path, pin, _document, spec = configured(tmp_path, monkeypatch, count=1)
    original = station_pool.Pool.acquire
    loads = []

    def acquire(manager, *args, **kwargs):
        lease = original(manager, *args, **kwargs)
        spec["task"]["role"] = "Review"
        spec["task"]["write_roots"] = ["out", "scratch"]
        return lease

    def store():
        loads.append("synthetic-existing-key")
        return case.store

    monkeypatch.setattr(station_pool.Pool, "acquire", acquire)
    monkeypatch.setattr(fixtures.slice_run, "_session_store", store)
    install_host(case, monkeypatch)
    outcome = dispatch(path, pin, spec, execute=True)
    assert outcome["status"] == "Collected", outcome
    assert loads == ["synthetic-existing-key"]
    assert read(Path(outcome["task_root"]) / "task.json")["role"] == "Coding"


def test_final_receipt_write_failure_never_returns_success_or_relaunches(tmp_path, monkeypatch):
    case, path, pin, document, spec = configured(tmp_path, monkeypatch, count=1)
    calls = install_host(case, monkeypatch)
    persist = runner._persist

    def broken_final(target, value, **kwargs):
        if target.name == "dispatch-final.json":
            raise OSError("synthetic final write failure")
        return persist(target, value, **kwargs)

    monkeypatch.setattr(runner, "_persist", broken_final)
    with pytest.raises(OSError, match="synthetic final write failure"):
        dispatch(path, pin, spec, execute=True)
    assert len(calls) == 1
    request = next((Path(document["control_root"]) / "requests").iterdir())
    pending = read(request / "dispatch.json")
    assert pending["release_state"] == "Pending" and pending["launch_count"] == 1
    assert not (request / "dispatch-final.json").exists()


def test_primary_interrupt_survives_secondary_terminal_write_failure(tmp_path, monkeypatch):
    _case, path, pin, document, spec = configured(tmp_path, monkeypatch, count=1)
    persist = runner._persist

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    def broken_terminal(target, value):
        if target.name == "dispatch.json":
            raise OSError("synthetic secondary write failure")
        return persist(target, value)

    monkeypatch.setattr(station_task, "_materialize", interrupted)
    monkeypatch.setattr(runner, "_persist", broken_terminal)
    with pytest.raises(KeyboardInterrupt):
        dispatch(path, pin, spec, execute=True)
    state = read(
        Path(document["control_root"]) / "states" / (document["stations"][0]["id"] + ".json")
    )
    assert state["state"] == "Suspended" and state["reason"] == "TerminalUnavailable"


def test_cli_execute_outputs_one_collected_candidate_not_management_acceptance(
    tmp_path, monkeypatch, capsys
):
    case, path, pin, _document, spec = configured(tmp_path, monkeypatch, count=1)
    calls = install_host(case, monkeypatch)
    spec_path = tmp_path / "dispatch-spec.json"
    fixtures.write_json(spec_path, spec)
    assert (
        cli.main(
            [
                "task",
                "dispatch",
                "--spec",
                str(spec_path),
                "--pool-registry",
                str(path),
                "--pool-sha256",
                pin,
                "--execute",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    outcome = json.loads(captured.out)
    assert outcome["status"] == "Collected" and len(calls) == 1
    assert outcome["business"]["management_decision"] is None and not captured.err


def create_synthetic_junction(tmp_path, link, target):
    # Both physical directories belong to this pytest case, under the task's
    # explicit --basetemp. Arguments travel through environment, not shell text.
    assert link.parent.resolve().is_relative_to(tmp_path.resolve())
    assert target.resolve().is_relative_to(tmp_path.resolve())
    assert not os.path.lexists(link)
    result = subprocess.run(
        [
            "C:/Program Files/PowerShell/7/pwsh.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "New-Item -ItemType Junction -Path $env:LAB_SYNTHETIC_STATION_LINK "
            "-Target $env:LAB_SYNTHETIC_STATION_TARGET | Out-Null",
        ],
        env={
            **os.environ,
            "LAB_SYNTHETIC_STATION_LINK": str(link),
            "LAB_SYNTHETIC_STATION_TARGET": str(target),
        },
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, "synthetic junction creation failed; no permission change"
    assert link.is_junction()


def test_review_f01_requests_junction_rejected_before_any_escaped_mkdir(tmp_path, monkeypatch):
    case, path, pin, document, spec = configured(tmp_path, monkeypatch, count=1)
    calls = install_host(case, monkeypatch)
    outside = tmp_path / "outside-control"
    outside.mkdir()
    requests = Path(document["control_root"]) / "requests"
    create_synthetic_junction(tmp_path, requests, outside)
    with pytest.raises(station_task.task_input.TaskInputError, match="reparse"):
        dispatch(path, pin, spec, execute=True)
    assert not list(outside.iterdir())
    assert calls == []


def test_review_f02_missing_native_skips_only_bad_station_before_job_creation(
    tmp_path, monkeypatch
):
    case, path, pin, document, spec = configured(tmp_path, monkeypatch, count=2)
    broken, healthy = document["stations"]
    record = Path(broken["record"])
    raw = record.read_bytes()
    retained = record.with_suffix(".json.retained")
    record.rename(retained)
    calls = install_host(case, monkeypatch)
    for _ in range(2):
        outcome = dispatch(path, pin, spec, execute=True)
        assert outcome["status"] == "Collected", outcome
        assert outcome["station_id"] == healthy["id"]
        assert outcome["release_state"] == "Released"
    assert len(calls) == 2
    assert not (Path(broken["root"]) / "jobs").exists()
    assert retained.read_bytes() == raw
    state = read(Path(document["control_root"]) / "states" / (broken["id"] + ".json"))
    assert state["state"] == "Suspended"


def test_trusted_junction_rejected_before_import_or_external_write(tmp_path, monkeypatch):
    _case, path, pin, document, spec = configured(tmp_path, monkeypatch, count=1)
    manager = station_pool.Pool(station_pool.load_registry(path, pin))
    lease = manager.acquire(str(uuid.uuid4()))
    request = Path(document["control_root"]) / "requests" / lease.request_id
    request.mkdir(parents=True)
    outside = tmp_path / "outside-trusted"
    outside.mkdir()
    create_synthetic_junction(tmp_path, request / "trusted", outside)
    monkeypatch.setattr(
        station_task.task_input, "import_snapshot", lambda **k: pytest.fail("import before check")
    )
    try:
        with pytest.raises(station_task.task_input.TaskInputError, match="reparse"):
            station_task._materialize(
                lease, station_task.validate_spec(spec, document["policy"]), request
            )
        assert not list(outside.iterdir())
        assert not lease.task_root.exists()
    finally:
        lease.abandon()
        manager.close()


@pytest.mark.parametrize("primary_type", [None, KeyboardInterrupt, SystemExit])
def test_dispatch_release_failure_preserves_interrupt_without_released_receipt(
    tmp_path, monkeypatch, primary_type
):
    case, path, pin, document, spec = configured(tmp_path, monkeypatch, count=1)
    calls = install_host(case, monkeypatch)
    kernel = pool_fixtures.ReleaseFailureKernel()
    kernel.fail_release = True
    monkeypatch.setattr(station_pool, "WindowsHandles", lambda: kernel)
    primary = primary_type("synthetic materialization interrupt") if primary_type else None
    if primary is not None:

        def interrupted(*args, **kwargs):
            raise primary

        monkeypatch.setattr(station_task, "_materialize", interrupted)
    expected = primary_type if primary is not None else station_pool.StationError
    with pytest.raises(expected) as caught:
        dispatch(path, pin, spec, execute=True)
    if primary is not None:
        assert caught.value is primary
    else:
        assert caught.value.code == "SyntheticReleaseFailed"
    assert kernel.releases == [1]
    assert len(calls) == (0 if primary is not None else 1)
    request = next((Path(document["control_root"]) / "requests").iterdir())
    assert not (request / "dispatch-final.json").exists()
    diagnostic = read(request / "dispatch-cleanup.json")
    assert diagnostic["release_state"] == "Unconfirmed"
    assert diagnostic["release_unconfirmed"] == [document["stations"][0]["id"]]
    assert diagnostic["control_complete"] is False
    assert diagnostic["status"] == "Stopped"
    assert any(item["stage"] == "release" for item in diagnostic["cleanup_diagnostics"])


def test_dispatch_primary_interrupt_survives_late_handle_close_failure(tmp_path, monkeypatch):
    _case, path, pin, document, spec = configured(tmp_path, monkeypatch, count=1)
    primary = KeyboardInterrupt("synthetic original materialization interrupt")
    kernel = pool_fixtures.ReleaseFailureKernel()
    monkeypatch.setattr(station_pool, "WindowsHandles", lambda: kernel)

    def interrupted(*args, **kwargs):
        raise primary

    def broken_close(handle):
        kernel.closes.append(handle)
        raise OSError("synthetic close failure")

    kernel.close = broken_close
    monkeypatch.setattr(station_task, "_materialize", interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        dispatch(path, pin, spec, execute=True)
    assert caught.value is primary
    assert kernel.releases == [1] and kernel.closes == [1]
    request = next((Path(document["control_root"]) / "requests").iterdir())
    assert not (request / "dispatch-final.json").exists()
    diagnostic = read(request / "dispatch-cleanup.json")
    assert any(
        item["stage"] == "close" and item["error_type"] == "OSError"
        for item in diagnostic["cleanup_diagnostics"]
    )


def test_review_f04_hardlinked_native_record_admits_healthy_for_two_requests(tmp_path, monkeypatch):
    case, path, pin, document, spec = configured(tmp_path, monkeypatch, count=2)
    broken, healthy = document["stations"]
    record = Path(broken["record"])
    original = record.read_bytes()
    alias = tmp_path / "retained-record-hardlink"
    assert record.resolve().is_relative_to(tmp_path.resolve())
    os.link(record, alias)
    assert record.stat().st_nlink == 2
    calls = install_host(case, monkeypatch)
    outcomes = [dispatch(path, pin, spec, execute=True) for _ in range(2)]
    assert outcomes[0]["request_id"] != outcomes[1]["request_id"]
    assert all(
        outcome["station_id"] == healthy["id"] and outcome["status"] == "Collected"
        for outcome in outcomes
    ), outcomes
    assert len(calls) == 2
    assert not (Path(broken["root"]) / "jobs").exists()
    assert record.read_bytes() == alias.read_bytes() == original
    state = read(Path(document["control_root"]) / "states" / (broken["id"] + ".json"))
    assert state["state"] == "Suspended"


def test_review_f05_entered_run_without_receipt_suspends_only_its_station(tmp_path, monkeypatch):
    case, path, pin, document, spec = configured(tmp_path, monkeypatch, count=2)
    broken, healthy = document["stations"]
    calls = install_host(case, monkeypatch, closed=False)
    original = runner._persist

    def reject_run_receipt(target, value, **kwargs):
        if target.name == "run.json":
            raise OSError("synthetic terminal run receipt write failure")
        return original(target, value, **kwargs)

    monkeypatch.setattr(runner, "_persist", reject_run_receipt)
    outcome = dispatch(path, pin, spec, execute=True)
    request = Path(outcome["terminal_path"]).parent
    launch = read(request / "run/launch.json")
    assert len(calls) == 1 and launch["cleanup"]["job_closed"] is False
    assert launch["capture_state"] == "incomplete"
    assert not (request / "run/run.json").exists()
    assert outcome["launch_count"] is None and "IoFailed" in outcome["blockers"]
    assert outcome["control_complete"] is False and outcome["release_state"] == "Suspended"
    state = read(Path(document["control_root"]) / "states" / (broken["id"] + ".json"))
    assert state["state"] == "Suspended"
    monkeypatch.setattr(runner, "_persist", original)
    next_calls = install_host(case, monkeypatch)
    next_outcome = dispatch(path, pin, spec, execute=True)
    assert next_outcome["station_id"] == healthy["id"] and next_outcome["status"] == "Collected"
    assert len(next_calls) == 1


@pytest.mark.parametrize(
    "damage",
    [
        "missing_run",
        "unreadable_run",
        "missing_field",
        "foreign_task",
        "missing_launch",
        "partial_launch",
    ],
)
def test_entered_run_invalid_evidence_keeps_unknown_launch_and_suspends(
    tmp_path, monkeypatch, damage
):
    case, path, pin, document, spec = configured(tmp_path, monkeypatch, count=1)
    calls = install_host(case, monkeypatch)
    original = runner.run_task
    original_open = Path.open
    refused = []

    def fail_after_host(**kwargs):
        result = original(**kwargs)
        run_root = kwargs["run_root"]
        receipt = run_root / "run.json"
        if damage == "missing_run":
            receipt.rename(run_root / "run.json.retained")
        elif damage == "unreadable_run":

            def refuse_receipt(target, *args, **options):
                if target == receipt:
                    refused.append(target)
                    raise PermissionError("synthetic receipt read rejection")
                return original_open(target, *args, **options)

            monkeypatch.setattr(Path, "open", refuse_receipt)
        elif damage == "missing_field":
            result.pop("capture_state")
            fixtures.write_json(receipt, result)
        elif damage == "foreign_task":
            result["task_id"] = str(uuid.uuid4())
            fixtures.write_json(receipt, result)
        elif damage == "missing_launch":
            (run_root / "launch.json").rename(run_root / "launch.json.retained")
        else:
            launch = run_root / "launch.json"
            launch.rename(run_root / "launch.json.retained")
            partial = {"launch_count": 1, "capture_state": "complete", "cleanup": {}}
            fixtures.write_json(launch, partial)
            for evidence in result["evidence_refs"]:
                if evidence["ref"] == "launch.json":
                    evidence["sha256"] = runner._digest(fixtures.canonical(partial))
            fixtures.write_json(receipt, result)
        raise runner.TaskRunError("SyntheticOriginalRunFailure")

    monkeypatch.setattr(runner, "run_task", fail_after_host)
    outcome = dispatch(path, pin, spec, execute=True)
    monkeypatch.setattr(Path, "open", original_open)
    assert len(calls) == 1
    assert outcome["status"] == "Stopped"
    assert outcome["launch_count"] is None and outcome["control_complete"] is False
    assert outcome["release_state"] == "Suspended"
    assert outcome["blockers"] == ["SyntheticOriginalRunFailure", "DispatchRunEvidenceUnavailable"]
    state = read(
        Path(document["control_root"]) / "states" / (document["stations"][0]["id"] + ".json")
    )
    assert state["state"] == "Suspended"
    if damage == "unreadable_run":
        assert len(refused) == 1


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
def test_entered_run_primary_interrupt_survives_secondary_evidence_interrupt(
    tmp_path, monkeypatch, primary_type
):
    _case, path, pin, document, spec = configured(tmp_path, monkeypatch, count=1)
    primary = primary_type("synthetic primary entered-run interrupt")

    def interrupted_run(**kwargs):
        raise primary

    def interrupted_evidence(*args, **kwargs):
        raise KeyboardInterrupt("synthetic secondary recovery interrupt")

    monkeypatch.setattr(runner, "run_task", interrupted_run)
    monkeypatch.setattr(station_task, "_run_evidence", interrupted_evidence)
    with pytest.raises(primary_type) as caught:
        dispatch(path, pin, spec, execute=True)
    assert caught.value is primary
    request = next((Path(document["control_root"]) / "requests").iterdir())
    diagnostic = read(request / "dispatch-cleanup.json")
    assert not (request / "dispatch-final.json").exists()
    assert diagnostic["launch_count"] is None and diagnostic["control_complete"] is False
    assert diagnostic["release_state"] == "Suspended"
    assert diagnostic["blockers"][0] == primary_type.__name__
    assert any(item["stage"] == "run-evidence" for item in diagnostic["cleanup_diagnostics"])


def test_closed_host_business_red_releases_and_next_request_reuses_station(tmp_path, monkeypatch):
    case, path, pin, _document, spec = configured(tmp_path, monkeypatch, shape="Testing", count=1)
    calls = install_host(case, monkeypatch, shape="Testing", closed=True, exit_code=7)
    red = dispatch(path, pin, spec, execute=True)
    assert len(calls) == 1 and red["run"]["transport_state"] == "Failed"
    assert red["control_complete"] is True and red["release_state"] == "Released"
    assert "TransportFailed" in red["business"]["blockers"]
    next_calls = install_host(case, monkeypatch, shape="Testing")
    next_outcome = dispatch(path, pin, spec, execute=True)
    assert next_outcome["station_id"] == red["station_id"]
    assert next_outcome["request_id"] != red["request_id"]
    assert next_outcome["status"] == "Collected" and len(next_calls) == 1


def configured_stable(tmp_path, monkeypatch, count=1):
    case, path, _pin, document, spec = configured(tmp_path, monkeypatch, count=count)
    seed = document["deployment_receipt"]
    seed["contract_version"] = 6
    seed["host_entry"] = {
        "path": str(case.host_entry),
        "install_root": str(case.host_entry.parent),
        "identity_mode": "StableInstalledEntry",
    }
    del seed["host_version"], seed["host_identity_files"]
    seed["runtime_acceptances"] = []
    seed["configuration"] = dict.fromkeys(seed["configuration"])
    pin = pool_fixtures.save_registry(path, document)
    return case, path, pin, document, spec


def install_stable_host(
    case,
    monkeypatch,
    *,
    probe_fault=None,
    help_text=None,
    version=b"1.3.4\n",
    conversation="valid",
    protocol=None,
):
    import test_agy_host as probes

    business_calls = install_host(case, monkeypatch, conversation=conversation)
    business_spawn = fixtures.slice_run.spawn_suspended_in_job
    diagnostic_calls = probes.probe_host(
        monkeypatch,
        fault=probe_fault,
        help_text=probes.HELP if help_text is None else help_text,
        version=version,
    )
    diagnostic_spawn = fixtures.slice_run.spawn_suspended_in_job

    def spawn(argv, cwd, *, lifecycle, env=None):
        if argv[1] in {"--version", "--help"}:
            return diagnostic_spawn(argv, cwd, lifecycle=lifecycle, env=env)
        process = business_spawn(argv, cwd, lifecycle=lifecycle, env=env)
        events = [json.loads(line) for line in process.stdout.getvalue().splitlines()]
        if protocol == "extra":
            events.insert(1, {"event": "new_host_event", "payload": {"new": True}})
            events[0]["init"]["additional"] = 1
        elif protocol == "model":
            events[0]["init"]["model"] = "other-model"
        elif protocol == "cid":
            del events[-1]["result"]["conversation_id"]
        elif protocol == "error":
            events[-1]["result"]["status"] = "ERROR"
        process.stdout = io.BytesIO(b"".join(fixtures.canonical(event) + b"\n" for event in events))
        return process

    monkeypatch.setattr(fixtures.slice_run, "spawn_suspended_in_job", spawn)
    return diagnostic_calls, business_calls


def test_r01_stable_update_without_registry_plan_receipt_mutation(tmp_path, monkeypatch):
    case, path, pin, _document, spec = configured_stable(tmp_path, monkeypatch)
    registry_bytes = path.read_bytes()
    diags, business = install_stable_host(
        case,
        monkeypatch,
        version=lambda: (
            b"1.4.0\n"
            if case.host_entry.read_bytes() == b"updated ordinary vendor entry"
            else b"1.3.4\n"
        ),
    )
    first = dispatch(path, pin, spec, execute=True)
    assert first["status"] == "Collected" and first["release_state"] == "Released", first
    first_root = Path(first["task_root"])
    frozen = {
        name: (first_root / ("control/" + name)).read_bytes()
        for name in ("plan.json", "deployment-receipt.json")
    }
    case.host_entry.replace(case.host_entry.with_suffix(".old"))
    case.host_entry.write_bytes(b"updated ordinary vendor entry")
    second = dispatch(path, pin, spec, execute=True)
    assert second["release_state"] == "Released" and second["launch_count"] == 1, second
    assert path.read_bytes() == registry_bytes and len(diags) == 4 and len(business) == 2
    for name, raw in frozen.items():
        assert (first_root / ("control/" + name)).read_bytes() == raw
    from local_agent_bridge.bridge import agy_host

    old = read(Path(first["terminal_path"]).parent / "run" / agy_host.OBSERVATION_REF)
    new = read(Path(second["terminal_path"]).parent / "run" / agy_host.OBSERVATION_REF)
    assert old["entry"]["sha256"] != new["entry"]["sha256"]
    assert old["reported_version"] == "1.3.4" and new["reported_version"] == "1.4.0"
    assert len(new["diagnostics"]) == 2 and all(d["launch_count"] == 1 for d in new["diagnostics"])
    assert second["run"]["launch_count"] == 1  # business count, not total process count
    assert (Path(second["result_root"]) / "run" / agy_host.OBSERVATION_REF).exists()


@pytest.mark.parametrize("fault", ["missing", "exit", "timeout", "truncated"])
def test_r06_closed_diagnostic_failure_releases_and_next_request_reuses(
    tmp_path, monkeypatch, fault
):
    import test_agy_host as probes

    case, path, pin, _document, spec = configured_stable(tmp_path, monkeypatch)
    text = (
        probes.HELP.replace(b"--model", b"--unneeded")
        if fault == "missing"
        else (b"x" * 262144 if fault == "truncated" else probes.HELP)
    )
    diags, business = install_stable_host(
        case,
        monkeypatch,
        probe_fault=fault if fault in {"exit", "timeout"} else None,
        help_text=text,
    )
    monkeypatch.setattr(
        fixtures.slice_run, "_session_store", lambda: pytest.fail("failed diagnostics read key")
    )
    first = dispatch(path, pin, spec, execute=True)
    assert first["release_state"] == "Released" and first["control_complete"], first
    assert first["launch_count"] == 0 and not business and first["business"]["blockers"]
    assert len(diags) in {1, 2}
    monkeypatch.setattr(fixtures.slice_run, "_session_store", lambda: case.store)
    install_stable_host(case, monkeypatch)
    second = dispatch(path, pin, spec, execute=True)
    assert second["release_state"] == "Released" and second["launch_count"] == 1, second
    assert first["station_id"] == second["station_id"]


@pytest.mark.parametrize("variant", ["wrapped_enum", "trailing_short_alias"])
def test_r05_supported_help_formatting_reaches_the_unique_business_call(
    tmp_path, monkeypatch, variant
):
    import test_agy_host as probes

    text = probes.HELP
    if variant == "wrapped_enum":
        text = text.replace(
            b"<level>               Effort",
            b"<level>               Effort (choices: low,\n"
            b"                                 medium, high)",
        )
    else:
        text = text.replace(b"--model <model>", b"--model, -m <name>")
    assert text != probes.HELP
    case, path, pin, _document, spec = configured_stable(tmp_path, monkeypatch)
    diags, business = install_stable_host(case, monkeypatch, help_text=text)
    outcome = dispatch(path, pin, spec, execute=True)
    assert outcome["release_state"] == "Released", outcome
    assert len(diags) == 2 and outcome["launch_count"] == 1 and len(business) == 1, outcome


@pytest.mark.parametrize("fault,count", [("resume_unknown", None), ("cleanup_unknown", 1)])
def test_r07_unknown_diagnostic_control_suspends_without_business(
    tmp_path, monkeypatch, fault, count
):
    from local_agent_bridge.bridge import agy_host

    case, path, pin, _document, spec = configured_stable(tmp_path, monkeypatch)
    diags, business = install_stable_host(case, monkeypatch, probe_fault=fault)
    monkeypatch.setattr(
        fixtures.slice_run, "_session_store", lambda: pytest.fail("unknown probe read key")
    )
    outcome = dispatch(path, pin, spec, execute=True)
    assert outcome["release_state"] == "Suspended" and not outcome["control_complete"], outcome
    assert outcome["launch_count"] == 0 and len(diags) == 1 and not business
    observation = read(Path(outcome["terminal_path"]).parent / "run" / agy_host.OBSERVATION_REF)
    assert observation["diagnostics"][0]["launch_count"] == count


@pytest.mark.parametrize(
    "conversation,protocol,blocked",
    [
        ("valid", "extra", False),
        ("missing", None, True),
        ("foreign", None, True),
        ("wrong_cwd", None, True),
        ("valid", "model", True),
        ("valid", "cid", True),
        ("valid", "error", True),
    ],
)
def test_r09_native_business_protocol_failure_keeps_control_closed(
    tmp_path, monkeypatch, conversation, protocol, blocked
):
    case, path, pin, _document, spec = configured_stable(tmp_path, monkeypatch)
    diags, business = install_stable_host(
        case, monkeypatch, conversation=conversation, protocol=protocol
    )
    outcome = dispatch(path, pin, spec, execute=True)
    assert outcome["release_state"] == "Released" and outcome["control_complete"], outcome
    assert outcome["launch_count"] == 1 and len(diags) == 2 and len(business) == 1
    assert ("NativeConversationUnverified" in outcome["run"]["blockers"]) is blocked
    assert ("NativeConversationUnverified" in outcome["business"]["blockers"]) is blocked


def test_r10_probe_interrupt_keeps_run_evidence_and_releases_closed_control(tmp_path, monkeypatch):
    from local_agent_bridge.bridge import agy_host

    case, path, pin, document, spec = configured_stable(tmp_path, monkeypatch)
    diags, business = install_stable_host(case, monkeypatch, probe_fault="interrupt")
    with pytest.raises(KeyboardInterrupt, match="primary"):
        dispatch(path, pin, spec, execute=True)
    request = next((Path(document["control_root"]) / "requests").iterdir())
    saved = read(request / "dispatch-cleanup.json")
    assert saved["release_state"] == "Released" and saved["launch_count"] == 0
    observation = read(request / "run" / agy_host.OBSERVATION_REF)
    assert observation["compatibility"]["reason"] == "ProbeInterrupted"
    assert observation["diagnostics"][0]["launch_count"] == 1 and len(diags) == 1 and not business


@pytest.mark.parametrize("fault", ["mixed", "cursor", "configuration", "shell", "acceptance"])
def test_r02_v6_seed_does_not_silently_normalize_invalid_contract(tmp_path, monkeypatch, fault):
    case, path, _pin, document, spec = configured_stable(tmp_path, monkeypatch)
    seed = document["deployment_receipt"]
    if fault == "mixed":
        seed["host_version"] = "1.3.4"
    elif fault == "cursor":
        seed["host"] = "cursor"
    elif fault == "configuration":
        seed["configuration"]["agy_settings"] = fixtures.identity(case.settings)
    elif fault == "shell":
        seed["launch_shell"] = fixtures.identity(case.host_entry)
    else:
        seed["runtime_acceptances"] = [{"status": "Accepted"}]
    pin = pool_fixtures.save_registry(path, document)
    monkeypatch.setattr(
        fixtures.slice_run,
        "spawn_suspended_in_job",
        lambda *a, **kw: pytest.fail("invalid seed spawn"),
    )
    outcome = dispatch(path, pin, spec, execute=True)
    assert outcome["status"] == "Stopped" and "StationReceiptInvalid" in outcome["blockers"]
    assert outcome["launch_count"] == 0
