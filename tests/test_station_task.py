"""Complete dispatch chain with real importer/collector and synthetic host capture."""

from __future__ import annotations

import copy
import io
import json
import multiprocessing
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
