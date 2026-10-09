"""Closed, synthetic evidence matrix. No native process, key or real acceptance."""

from __future__ import annotations

import copy

import pytest
import test_task_run as fixtures
import test_task_workspace as workspace_fixtures

from local_agent_bridge.bridge import layered_acceptance as layered
from local_agent_bridge.bridge import task_run as runner
from local_agent_bridge.bridge import task_workspace as workspace


def pinned(value, ref, origin="HostObserved"):
    return {
        "value": value,
        "evidence_ref": {
            "ref": "synthetic/" + ref,
            "sha256": fixtures.digest(value),
            "origin": origin,
        },
    }


@pytest.fixture
def case(tmp_path, monkeypatch):
    value = fixtures.prepare(tmp_path, monkeypatch, actual_b=True, accepted=False)
    value.receipt.update(
        contract_version=3,
        host_composition=layered.COMPOSITION.copy(),
        acceptance_method=layered.METHOD,
        host_identity_files=[],
        runtime_acceptances=[],
        layered_acceptances=[],
    )
    fixtures.sync(value)
    value.candidate = "c" * 64
    tool = value.receipt["toolchains"][0]
    value.recipes = {
        "recipe_sha256": "d" * 64,
        "toolchain_sha256": fixtures.digest(tool),
        "executable_identity": tool["identity_files"][0].copy(),
        "argv": [tool["identity_files"][0]["path"], "-I", "recipe.py", "regression"],
        "cwd": str(tmp_path / "management-retest"),
    }
    task_sha = fixtures.digest(value.task)
    value.collection = {
        "contract_version": 1,
        "task_id": value.task["task_id"],
        "snapshot_id": value.task["snapshot_id"],
        "task_manifest_sha256": task_sha,
        "plan_sha256": "e" * 64,
        "worker_status": "Completed",
        "changes": [],
        "artifacts": [],
        "blockers": [],
        "management_decision": None,
        "host_observations": {
            "transport_state": "Completed",
            "scope_status": "Pass",
            "outputs_status": "Pass",
            "coverage_status": "NotApplicable",
            "test_observations": [],
            "acceptance_observations": [],
        },
        "continuation": {
            "snapshot_id": value.task["snapshot_id"],
            "candidate_tree_sha256": value.candidate,
            "artifact_manifest_sha256": fixtures.digest([]),
            "task_manifest_sha256": task_sha,
            "remaining_acceptance_ids": value.task["acceptance_ids"].copy(),
            "remaining_paths": [],
            "last_test_run_id": None,
            "blocker": None,
            "next_action": "Synthetic management review only",
            "session_id": "synthetic-new-uid",
        },
    }
    value.retest = {
        "actor": "ManagementIndependent",
        "task_id": value.task["task_id"],
        "source_tree_sha256": value.candidate,
        **{key: copy.deepcopy(item) for key, item in value.recipes.items()},
        "worker_shell_identity": None,
        "start_utc": "2026-10-09T01:00:00+00:00",
        "end_utc": "2026-10-09T01:00:01+00:00",
        "exit_code": 0,
        "tests": 6,
        "failures": 0,
        "errors": 0,
    }
    value.lifecycle = {
        "task_id": value.task["task_id"],
        "plan_sha256": value.collection["plan_sha256"],
        "transport_state": "Completed",
        "launch_count": 1,
        "capture_uid": "synthetic-new-uid",
        "capture_state": "Sealed",
        "restore_state": "Restored",
        "owned_process_cleanup": "Pass",
        "exit_code": 0,
        "blockers": [],
    }
    return value


def evaluate(case, *, execution=None, retest_origin="HostObserved", worker_recipe=None):
    return layered.evaluate_delivery(
        task=case.task,
        receipt=case.receipt,
        candidate_tree_sha256=case.candidate,
        recipes=case.recipes,
        collection=pinned(case.collection, "collection.json"),
        manager_retest=pinned(case.retest, "retest.json", retest_origin),
        host_lifecycle=pinned(case.lifecycle, "lifecycle.json"),
        worker_execution=execution,
        worker_recipe=worker_recipe,
    )


def accepted(case):
    evaluation = evaluate(case)
    assert evaluation["status"] == "Eligible"
    record = {
        "role": "Coding",
        "capabilities": layered.CAPABILITIES.copy(),
        "execution_boundary": "declared_scope",
        "receipt_binding_sha256": evaluation["receipt_binding_sha256"],
        "task_scope_sha256": evaluation["task_scope_sha256"],
        "status": "Accepted",
        "evaluation": evaluation,
        "management_acceptance_ref": fixtures.observed("synthetic/decision"),
    }
    case.receipt["layered_acceptances"] = [record]
    fixtures.sync(case)
    return record


def test_eligible_keeps_unknown_worker_and_strict_r(case):
    result = evaluate(case)
    assert result["status"] == "Eligible"
    assert result["strict_r_status"] == "Unverified"
    assert result["layers"]["worker_execution"] == {
        "result": "Unknown",
        "origin": "Unknown",
        "evidence_refs": [],
    }
    assert case.receipt["layered_acceptances"] == case.receipt["runtime_acceptances"] == []


@pytest.mark.parametrize("origin", ["WorkerReported", "CliDeclared"])
def test_declaration_never_proves_worker_execution(case, origin):
    result = evaluate(
        case, execution=pinned({"xml": "<testsuite failures='0'/>"}, "worker.xml", origin)
    )
    assert result["status"] == "Eligible"
    assert result["layers"]["worker_execution"]["origin"] == origin
    assert result["layers"]["worker_execution"]["result"] == "Unknown"


@pytest.mark.parametrize("origin", ["WorkerReported", "CliDeclared"])
def test_worker_retest_report_cannot_accept_manager_layer(case, origin):
    result = evaluate(case, retest_origin=origin)
    assert result["layers"]["manager_retest"]["result"] == "Unknown"
    assert result["status"] == "Unverified"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor", "Worker"),
        ("task_id", "other-task"),
        ("source_tree_sha256", "0" * 64),
        ("recipe_sha256", "0" * 64),
        ("toolchain_sha256", "0" * 64),
        ("argv", ["fake.exe"]),
        ("cwd", "C:/unbound"),
        ("exit_code", 1),
        ("tests", 0),
        ("failures", 1),
        ("errors", 1),
        ("start_utc", "2026-10-09T01:00:02+00:00"),
        ("end_utc", "2026-10-09T01:00:01"),
    ],
)
def test_retest_mismatch_is_not_accepted(case, field, value):
    case.retest[field] = value
    result = evaluate(case)
    assert result["layers"]["manager_retest"]["result"] == "Fail"
    assert result["status"] == "Blocked"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transport_state", "Failed"),
        ("transport_state", "TimedOut"),
        ("launch_count", None),
        ("launch_count", 0),
        ("launch_count", True),
        ("exit_code", True),
        ("exit_code", 1),
        ("capture_state", "Incomplete"),
        ("capture_uid", None),
        ("capture_uid", "wrong-uid"),
        ("restore_state", "Failed"),
        ("owned_process_cleanup", "Unknown"),
        ("plan_sha256", "0" * 64),
        ("blockers", ["TransportFailed"]),
    ],
)
def test_lifecycle_failure_is_not_covered_by_code_pass(case, field, value):
    case.lifecycle[field] = value
    result = evaluate(case)
    assert result["layers"]["code_delivery"]["result"] == "Pass"
    assert result["layers"]["manager_retest"]["result"] == "Pass"
    expected = (
        "Unknown"
        if (field == "launch_count" and value is None) or field == "owned_process_cleanup"
        else "Fail"
    )
    assert result["layers"]["host_lifecycle"]["result"] == expected
    assert result["status"] == ("Unverified" if expected == "Unknown" else "Blocked")


def test_host_observed_requires_complete_matching_worker_command(case):
    worker = copy.deepcopy(case.retest)
    worker["actor"] = "Worker"
    worker["worker_shell_identity"] = fixtures.identity(case.host_entry)
    worker_recipe = copy.deepcopy(case.recipes)
    worker_recipe["cwd"] = str(case.root / "work")
    worker_recipe["argv"][-1] = "worker-regression"
    worker["cwd"] = worker_recipe["cwd"]
    worker["argv"] = worker_recipe["argv"].copy()
    result = evaluate(
        case, execution=pinned(worker, "host-command.json"), worker_recipe=worker_recipe
    )
    assert result["layers"]["worker_execution"]["result"] == "Pass"
    worker["worker_shell_identity"] = None
    result = evaluate(
        case, execution=pinned(worker, "missing-shell.json"), worker_recipe=worker_recipe
    )
    assert result["layers"]["worker_execution"]["result"] == "Unknown"
    # Delivery acceptance never becomes strict R, even with a command fact.
    assert result["strict_r_status"] == "Unverified"


def test_host_observed_worker_without_frozen_command_remains_unknown(case):
    worker = copy.deepcopy(case.retest)
    worker["actor"] = "Worker"
    worker["worker_shell_identity"] = fixtures.identity(case.host_entry)
    result = evaluate(case, execution=pinned(worker, "unbound-command"))
    assert result["layers"]["worker_execution"]["result"] == "Unknown"


@pytest.mark.parametrize("fault", ["xml-only", "unknown-field", "wrong-hash", "missing-evidence"])
def test_closed_input_and_fake_xml_refused(case, fault):
    inputs = dict(
        task=case.task,
        receipt=case.receipt,
        candidate_tree_sha256=case.candidate,
        recipes=case.recipes,
        collection=pinned(case.collection, "collection"),
        manager_retest=pinned(case.retest, "retest"),
        host_lifecycle=pinned(case.lifecycle, "lifecycle"),
    )
    if fault == "xml-only":
        inputs["manager_retest"] = pinned({"xml": "<testsuite tests='6' failures='0'/>"}, "xml")
    elif fault == "unknown-field":
        case.collection["invented"] = True
        inputs["collection"] = pinned(case.collection, "collection")
    elif fault == "wrong-hash":
        inputs["manager_retest"]["evidence_ref"]["sha256"] = "0" * 64
    else:
        del inputs["manager_retest"]["evidence_ref"]
    with pytest.raises(runner.TaskRunError):
        layered.evaluate_delivery(**inputs)


def test_missing_observations_stay_unknown(case):
    value = layered.evaluate_delivery(
        task=case.task,
        receipt=case.receipt,
        candidate_tree_sha256=case.candidate,
        recipes=case.recipes,
        collection=None,
        manager_retest=None,
        host_lifecycle=None,
    )
    assert value["status"] == "Unverified"
    assert all(layer["result"] == "Unknown" for layer in value["layers"].values())


@pytest.mark.parametrize(
    "fault",
    [
        "version",
        "bool-version",
        "method",
        "host",
        "unknown-field",
        "composition",
        "fake-exe-composition",
        "old-r",
    ],
)
def test_receipt_v3_shape_is_closed(case, fault):
    if fault == "version":
        case.receipt["contract_version"] = 4
    elif fault == "bool-version":
        case.receipt["contract_version"] = True
    elif fault == "method":
        case.receipt["acceptance_method"] = "runtime_v1"
    elif fault == "host":
        case.receipt["host"] = "cursor"
    elif fault == "unknown-field":
        case.receipt["unknown"] = 1
    elif fault == "composition":
        case.receipt["host_composition"]["status"] = "Known"
    elif fault == "fake-exe-composition":
        case.receipt["host_identity_files"] = [case.receipt["host_entry"].copy()]
    else:
        case.receipt["runtime_acceptances"] = [{"status": "Accepted"}]
    with pytest.raises(runner.TaskRunError):
        runner._validate_receipt(case.receipt)


def test_normal_plan_requires_explicit_accepted_record(case):
    blocked = runner._make_plan(runner._load_inputs(case.root, case.trust, case.expected), "agy")
    assert blocked["contract_version"] == 2
    assert blocked["blockers"] == ["LayeredAcceptanceUnverified"]
    accepted(case)
    ready = fixtures.plan(case)
    assert ready["contract_version"] == 2 and ready["acceptance_method"] == layered.METHOD
    assert ready["preflight_status"] == "Ready" and ready["blockers"] == []
    assert case.receipt["runtime_acceptances"] == []


@pytest.mark.parametrize(
    "fault",
    [
        "task_id",
        "acceptance_ids",
        "instructions",
        "snapshot",
        "role",
        "web",
        "deps",
        "boundary",
        "path",
        "receipt",
        "authorization",
    ],
)
def test_exact_scope_and_authority_match(case, fault):
    record = accepted(case)
    if fault == "task_id":
        case.task["task_id"] = case.auth["task_id"] = "different-task"
    elif fault == "acceptance_ids":
        case.task["acceptance_ids"] = ["CRUD-01", "RENAME-01"]
    elif fault == "instructions":
        note = b"Different scope"
        (case.root / "control" / "TASK.md").write_bytes(note)
        case.task["instructions_sha256"] = runner._digest(note)
    elif fault == "snapshot":
        case.task["snapshot_id"] = "0" * 64
    elif fault == "role":
        case.task["role"] = "Review"
        case.task["write_roots"] = ["out", "scratch"]
        case.auth["write_roots"] = ["out", "scratch"]
    elif fault in {"web", "deps"}:
        key = "web_reference" if fault == "web" else "prepare_dependencies"
        case.task["capabilities"][key] = case.auth["capabilities"][key] = True
        case.auth["web_scope" if fault == "web" else "dependency_scope"] = "synthetic-expansion"
    elif fault == "boundary":
        case.task["execution_boundary"] = case.auth["execution_boundary"] = "required_enforced"
    elif fault == "path":
        case.task["protected_paths"] = sorted([*case.task["protected_paths"], "work/source.py"])
    elif fault == "receipt":
        record["receipt_binding_sha256"] = record["evaluation"]["receipt_binding_sha256"] = "0" * 64
    else:
        case.auth["capabilities"]["execute"] = False
    fixtures.sync(case)
    try:
        result = fixtures.plan(case)
    except runner.TaskRunError:
        assert fault in {"snapshot", "authorization"}
    else:
        assert result["preflight_status"] == "Blocked"
        assert result["blockers"]


@pytest.mark.parametrize(
    "fault", ["worker-only", "unknown-required", "wrong-evaluation-binding", "unobserved-decision"]
)
def test_accepted_record_cannot_fabricate_required_layers(case, fault):
    record = accepted(case)
    if fault in {"worker-only", "unknown-required"}:
        layer = record["evaluation"]["layers"]["manager_retest"]
        layer.update(result="Unknown", origin="Unknown", evidence_refs=[])
        record["evaluation"]["status"] = "Unverified"
    elif fault == "wrong-evaluation-binding":
        record["evaluation"]["task_scope_sha256"] = "0" * 64
    else:
        record["management_acceptance_ref"]["origin"] = "WorkerReported"
    with pytest.raises(runner.TaskRunError):
        runner._validate_receipt(case.receipt)


@pytest.mark.parametrize("execute", [False, True])
def test_new_plan_dry_run_and_actual_collector_keep_business_unverified(
    case, tmp_path, monkeypatch, execute
):
    accepted(case)
    plan = fixtures.plan(case)
    run_root = tmp_path / "dry-run"
    if execute:
        monkeypatch.setattr(fixtures.FakeProcess, "close_job", lambda _process: True)
        fixtures.fake_spawn(case, monkeypatch)
    result = runner.run_task(
        task_root=case.root,
        plan=plan,
        run_root=run_root,
        trusted_control_root=case.trust,
        trusted_inputs_sha256=case.expected,
        execute=execute,
    )
    assert result["launch_count"] == int(execute)
    assert result["transport_state"] == ("Completed" if execute else "NotRun")
    workspace_fixtures.progress(case.root, case.task)
    result = workspace.collect_task(
        task_root=case.root, run_root=run_root, result_root=tmp_path / "collected"
    )
    assert result["blockers"] == []
    assert result["management_decision"] is None
    assert result["host_observations"]["acceptance_observations"][0]["result"] == (
        "Unverified" if execute else "Unrun"
    )
    if execute:
        case.collection = result
        case.candidate = result["continuation"]["candidate_tree_sha256"]
        case.retest["source_tree_sha256"] = case.candidate
        case.lifecycle["plan_sha256"] = result["plan_sha256"]
        case.lifecycle["capture_uid"] = result["continuation"]["session_id"]
        assert evaluate(case)["status"] == "Eligible"


@pytest.mark.parametrize(
    "fault", ["scope", "outputs", "remaining", "candidate", "task", "artifact"]
)
def test_code_delivery_evidence_must_match(case, fault):
    if fault in {"scope", "outputs"}:
        case.collection["host_observations"][fault + "_status"] = "Fail"
    elif fault == "remaining":
        case.collection["continuation"]["remaining_paths"] = ["work/source.py"]
    elif fault == "candidate":
        case.collection["continuation"]["candidate_tree_sha256"] = "0" * 64
    elif fault == "task":
        case.collection["task_manifest_sha256"] = "0" * 64
    else:
        case.collection["continuation"]["artifact_manifest_sha256"] = "0" * 64
    result = evaluate(case)
    assert result["layers"]["code_delivery"]["result"] == "Fail"
    assert result["status"] == "Blocked"


def test_fixed_entry_identity_still_required(case):
    accepted(case)
    case.host_entry.write_bytes(b"changed synthetic entry")
    assert "RuntimeIdentityUnverified" in fixtures.plan(case)["blockers"]


@pytest.mark.parametrize("fault", ["old-version", "method", "unknown-field", "bool-version"])
def test_new_plan_loader_refuses_mixed_formats(case, fault):
    accepted(case)
    plan = fixtures.plan(case)
    if fault == "old-version":
        plan["contract_version"] = 1
    elif fault == "method":
        plan["acceptance_method"] = "other"
    elif fault == "unknown-field":
        plan["unknown"] = 1
    else:
        plan["contract_version"] = True
    with pytest.raises(runner.TaskRunError):
        runner._validate_plan(plan)
    with pytest.raises(workspace.TaskWorkspaceError):
        workspace._plan(plan, case.task, fixtures.digest(case.task))


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_plan_semantics_remain(case, version):
    for key in ("acceptance_method", "layered_acceptances", "host_composition"):
        case.receipt.pop(key)
    case.receipt["contract_version"] = 1
    case.receipt["host_identity_files"] = [fixtures.identity(case.settings)]
    if version == 1:
        case.accepted = True
        fixtures.sync(case, refresh_r=True)
        result = fixtures.plan(case)
        assert result["preflight_status"] == "Ready"
    else:
        fixtures.first_observation_receipt(case)
        fixtures.sync(case)
        result = fixtures.plan(case)
        assert result["blockers"] == ["HostCompositionUnverified", "RuntimeAcceptanceUnverified"]
        case.receipt["runtime_acceptances"] = [{"status": "Accepted"}]
        with pytest.raises(runner.TaskRunError):
            runner._validate_receipt(case.receipt)
    assert result["contract_version"] == 1 and "acceptance_method" not in result
