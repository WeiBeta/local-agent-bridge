"""Actual B prepare → C fake lifecycle → B collect, with explicit synthetic trust."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import test_task_run as fixtures
import test_task_workspace as workspace_fixtures

from local_agent_bridge.bridge import task_run as runner
from local_agent_bridge.bridge import task_workspace as workspace

RULE_BYTES = {
    "AGENTS.md": b"\xef\xbb\xbfSynthetic management-checked fixture rule\r\n",
    "nested/GEMINI.md": "合成规则原字节\r\n".encode(),
    "nested/CLAUDE.md": b"Offline fixture rule without trailing newline",
    ".cursorrules": b"Synthetic fixture rule\n",
}


def actual_case(tmp_path, monkeypatch, *, host="agy", role="Coding", rules=True, accepted=True):
    files = {"source.py": b"n = 0\r\n", **(RULE_BYTES if rules else {})}
    case = fixtures.prepare(
        tmp_path, monkeypatch, host=host, role=role, actual_b=True, files=files, accepted=accepted
    )
    assert (case.root / "task.json").read_bytes() == fixtures.canonical(case.task)
    assert (
        case.root / "control" / "snapshot" / "manifest.json"
    ).read_bytes() == fixtures.canonical(case.snapshot)
    for path, raw in files.items():
        assert (case.root / "work" / path).read_bytes() == raw
        assert (case.root / "control" / "snapshot" / "source" / path).read_bytes() == raw
    return case


def outputs(case):
    if case.task["role"] == "Review":
        workspace_fixtures.review_outputs(case.root, case.task, case.snapshot)
    else:
        workspace_fixtures.progress(case.root, case.task)


def collect(case, tmp_path, run_root=None):
    return workspace.collect_task(
        task_root=case.root, run_root=run_root, result_root=tmp_path / "collected"
    )


@pytest.mark.parametrize("role", ["Coding", "Review"])
@pytest.mark.parametrize("drift", ["benign", "permission", "project"])
def test_cursor_v5_config_finalization_actual_b_and_collect(tmp_path, monkeypatch, role, drift):
    case = actual_case(tmp_path, monkeypatch, host="cursor", role=role, accepted=False)
    global_path, value = fixtures.bind_cursor_global(case)
    frozen = fixtures.plan(case)
    original_global = global_path.read_bytes()

    def maintain_configuration():
        if drift == "benign":
            value["hints"] = True
            global_path.write_bytes(json.dumps(value, indent=2).encode())
        elif drift == "permission":
            value["permissions"]["deny"] = ["Write(work/**)"]
            fixtures.write_json(global_path, value)
        else:
            (case.root / ".cursor/cli.json").write_bytes(b"{}")

    fixtures.fake_spawn(case, monkeypatch, behavior=maintain_configuration)
    run_root = tmp_path / "v5-run"
    receipt = fixtures.run(case, frozen, run_root, execute=True)
    outputs(case)
    result = collect(case, tmp_path, run_root)
    assert receipt["launch_count"] == len(case.calls) == 1
    assert result["management_decision"] is None
    assert all(
        item["result"] == "Unverified"
        for item in result["host_observations"]["acceptance_observations"]
    )
    assert (tmp_path / "collected/run/run.json").read_bytes() == (
        run_root / "run.json"
    ).read_bytes()
    if drift == "benign":
        assert receipt["transport_state"] == "Completed" and receipt["restore_state"] == "Unchanged"
        assert not result["blockers"]
        assert result["host_observations"]["scope_status"] == "Pass"
        assert result["host_observations"]["outputs_status"] == "Pass"
        assert global_path.read_bytes() != original_global
    else:
        assert receipt["transport_state"] == "Failed" and receipt["restore_state"] == "Failed"
        assert {"CursorConfigurationUnverified", "RestoreFailed", "TransportFailed"} <= set(
            result["blockers"]
        )
        if drift == "project":
            assert "ControlChanged" in result["blockers"] and result["continuation"] is None


@pytest.mark.parametrize("role", ["Coding", "Review"])
def test_native_project_actual_b_prepare_fake_run_and_collect(tmp_path, monkeypatch, role):
    case = actual_case(tmp_path, monkeypatch, role=role)
    fixtures.bind_native_project(case)
    fixtures.forbid_global_settings(monkeypatch, case.settings)
    frozen = fixtures.plan(case)
    assert frozen["preflight_status"] == "Ready"
    fixtures.fake_spawn(case, monkeypatch)
    run_root = tmp_path / "native-run"
    receipt = fixtures.run(case, frozen, run_root, execute=True)
    outputs(case)
    result = collect(case, tmp_path, run_root)
    assert receipt["launch_count"] == 1 and receipt["restore_state"] == "Unchanged"
    assert result["host_observations"]["scope_status"] == "Pass"
    assert result["host_observations"]["outputs_status"] == "Pass"
    assert result["management_decision"] is None and not result["blockers"]
    assert (tmp_path / "collected/run/native-project-check.json").read_bytes() == (
        run_root / "native-project-check.json"
    ).read_bytes()
    assert (tmp_path / "collected/host/control/deployment-receipt.json").read_bytes() == (
        case.root / "control/deployment-receipt.json"
    ).read_bytes()


def test_public_host_verification_follows_external_trust_validation(tmp_path, monkeypatch):
    case = actual_case(tmp_path, monkeypatch)
    monkeypatch.setattr(
        workspace,
        "verify_input_controls",
        lambda **_kwargs: pytest.fail("untrusted bundle reached verifier"),
    )
    case.expected = "0" * 64
    with pytest.raises(runner.TaskRunError, match="TrustedInputChanged"):
        fixtures.plan(case)


@pytest.mark.parametrize("host", ["agy", "cursor"])
@pytest.mark.parametrize("role", ["Coding", "Review"])
@pytest.mark.parametrize("rules", [False, True])
def test_actual_b_prepared_inputs_survive_c_and_collect(tmp_path, monkeypatch, host, role, rules):
    case = actual_case(tmp_path, monkeypatch, host=host, role=role, rules=rules)
    frozen = fixtures.plan(case)
    assert frozen["preflight_status"] == "Ready"
    assert frozen["task_manifest_sha256"] == fixtures.digest(case.task)
    fixtures.fake_spawn(case, monkeypatch)
    run_root = tmp_path / "run"
    receipt = fixtures.run(case, frozen, run_root, execute=True)
    outputs(case)
    result = collect(case, tmp_path, run_root)
    assert len(case.calls) == 1
    assert receipt["launch_count"] == 1 and receipt["transport_state"] == "Completed"
    assert result["host_observations"]["transport_state"] == "Completed"
    assert result["host_observations"]["scope_status"] == "Pass"
    assert result["host_observations"]["outputs_status"] == "Pass"
    assert result["worker_status"] == "Completed" and result["management_decision"] is None
    assert not result["blockers"]
    checks = json.loads((tmp_path / "collected/validation/run-evidence-checks.txt").read_bytes())
    opaque = next(item for item in checks if item["ref"].startswith("session:"))
    assert opaque["check"] == "Unverified" and opaque["actual_sha256"] is None
    assert all(
        item["result"] == "Unverified"
        for item in result["host_observations"]["acceptance_observations"]
    )
    assert (tmp_path / "collected/run/run.json").read_bytes() == (
        run_root / "run.json"
    ).read_bytes()
    if rules:
        for path, raw in RULE_BYTES.items():
            assert (tmp_path / "collected/candidate" / path).read_bytes() == raw


@pytest.mark.parametrize("host", ["agy", "cursor"])
@pytest.mark.parametrize("accepted", [False, True])
def test_actual_b_dry_run_collect_preserves_zero(tmp_path, monkeypatch, host, accepted):
    case = actual_case(tmp_path, monkeypatch, host=host, accepted=accepted)
    monkeypatch.setattr(fixtures.slice_run, "_session_store", lambda: pytest.fail("key read"))
    frozen = fixtures.plan(case)
    run_root = tmp_path / "dry"
    receipt = fixtures.run(case, frozen, run_root)
    outputs(case)
    result = collect(case, tmp_path, run_root)
    assert receipt["launch_count"] == 0 and receipt["transport_state"] == "NotRun"
    assert result["host_observations"]["transport_state"] == "NotRun"
    assert not case.calls
    assert frozen["preflight_status"] == ("Ready" if accepted else "Blocked")


@pytest.mark.parametrize("stage", ["plan", "run", "capture"])
def test_rule_drift_refused_before_launch_and_preserved_by_collect(tmp_path, monkeypatch, stage):
    case = actual_case(tmp_path, monkeypatch)
    frozen = fixtures.plan(case) if stage != "plan" else None
    drift = b"changed fixture rule\r\n"
    path = case.root / "work/AGENTS.md"
    if stage == "capture":
        capture = runner._capture_bytes

        def change_rule(writer, name, raw):
            capture(writer, name, raw)
            path.write_bytes(drift)

        monkeypatch.setattr(runner, "_capture_bytes", change_rule)
        run_root = tmp_path / "run"
        receipt = fixtures.run(case, frozen, run_root, execute=True)
        assert receipt["launch_count"] == 0
        assert "InputControlConflict" in receipt["blockers"]
    else:
        path.write_bytes(drift)
        run_root = None
        with pytest.raises(runner.TaskRunError, match="InputControlConflict"):
            if stage == "plan":
                fixtures.plan(case)
            else:
                fixtures.run(case, frozen, tmp_path / "refused", execute=True)
        assert not (tmp_path / "refused").exists()
    assert not case.calls and case.settings.read_bytes() == b'{ "user": 7 }\r\n'
    outputs(case)
    result = collect(case, tmp_path, run_root)
    assert "InputControlConflict" in result["blockers"]
    assert result["host_observations"]["scope_status"] == "Fail"
    assert result["continuation"] is None
    assert path.read_bytes() == drift
    assert (tmp_path / "collected/candidate/AGENTS.md").read_bytes() == drift
    assert (case.root / "control/snapshot/source/AGENTS.md").read_bytes() == RULE_BYTES["AGENTS.md"]


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "null", "projection", "hash", "name", "protection"]
)
def test_c_rejects_control_binding_mismatch_without_native_effect(tmp_path, monkeypatch, mutation):
    case = actual_case(tmp_path, monkeypatch)
    binding = case.auth["input_control_bindings"]
    if mutation == "missing":
        del case.auth["input_control_bindings"]
    elif mutation == "extra":
        binding["extra"] = True
    elif mutation == "null":
        case.auth["input_control_bindings"] = None
    elif mutation == "projection":
        binding["task_fields_sha256"] = "0" * 64
    elif mutation == "hash":
        binding["files"]["AGENTS.md"] = "0" * 64
    elif mutation == "name":
        binding["files"]["agents.md"] = binding["files"].pop("AGENTS.md")
    else:
        case.task["protected_paths"].remove("work/AGENTS.md")
        binding["task_fields_sha256"] = fixtures.digest(
            {key: value for key, value in case.task.items() if key != "authorization_sha256"}
        )
    case.task["authorization_sha256"] = fixtures.digest(case.auth)
    bundle = {
        "deployment_receipt": case.receipt,
        "deployment_profile": case.profile,
        "authorization": case.auth,
    }
    case.expected = fixtures.digest(bundle)
    fixtures.write_json(case.trust / "authorization.json", case.auth)
    fixtures.write_json(case.root / "control/authorization.json", case.auth)
    fixtures.write_json(case.root / "task.json", case.task)
    (case.root / "SEALED").write_bytes(fixtures.digest(case.task).encode("ascii"))
    monkeypatch.setattr(fixtures.slice_run, "_session_store", lambda: pytest.fail("key read"))
    with pytest.raises(runner.TaskRunError, match="InputControlConflict"):
        fixtures.plan(case)
    assert not case.calls and not (case.root / "control/plan.json").exists()


@pytest.mark.parametrize("host", ["agy", "cursor"])
@pytest.mark.parametrize("state", ["not_attempted", "confirmed", "unknown"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_actual_b_collect_preserves_exception_lifecycle_fact(
    tmp_path, monkeypatch, host, state, interrupt
):
    case = actual_case(tmp_path, monkeypatch, host=host)
    frozen = fixtures.plan(case)
    error = (
        KeyboardInterrupt("synthetic original interrupt")
        if interrupt
        else RuntimeError("synthetic failure")
    )

    def fail(argv, cwd, *, lifecycle, env=None):
        case.calls.append((argv, cwd))
        if state != "not_attempted":
            previous = lifecycle.begin_resume()
        if state == "confirmed":
            lifecycle.observe_resume(1, previous)
        lifecycle.child_exit_observed = None
        lifecycle.pipes_closed = False
        lifecycle.job_closed = None
        raise error

    monkeypatch.setattr(fixtures.slice_run, "spawn_suspended_in_job", fail)
    run_root = tmp_path / "run"
    if interrupt:
        with pytest.raises(KeyboardInterrupt) as caught:
            fixtures.run(case, frozen, run_root, execute=True)
        assert caught.value is error
        receipt = json.loads((run_root / "run.json").read_bytes())
    else:
        receipt = fixtures.run(case, frozen, run_root, execute=True)
    count = {"not_attempted": 0, "confirmed": 1, "unknown": None}[state]
    assert receipt["launch_count"] == count and receipt["transport_state"] == "Failed"
    outputs(case)
    result = collect(case, tmp_path, run_root)
    assert result["host_observations"]["transport_state"] == "Failed"
    assert "RunReceiptInvalid" not in result["blockers"]
    assert len(case.calls) == 1
    assert (tmp_path / "collected/run/run.json").read_bytes() == (
        run_root / "run.json"
    ).read_bytes()
    if state == "unknown":
        assert "LaunchUnverified" in result["blockers"] and result["continuation"] is None
    if state != "not_attempted":
        fact = json.loads((tmp_path / "collected/run/launch.json").read_bytes())
        assert fact["spawn_state"] == state and fact["launch_count"] == count
        assert fact["cleanup"]["pipes_closed"] is False
        assert fact["cleanup"]["child_exit_observed"] is None
        assert fact["cleanup"]["job_closed"] is None


@pytest.mark.parametrize("host", ["agy", "cursor"])
def test_configuration_finalization_failure_retained_through_collect(tmp_path, monkeypatch, host):
    case = actual_case(tmp_path, monkeypatch, host=host)
    frozen = fixtures.plan(case)
    original = case.settings.read_bytes()

    def drift():
        target = (
            case.settings
            if host == "agy"
            else Path(case.receipt["configuration"]["cursor_project"]["path"])
        )
        target.write_bytes(b'{"synthetic_drift":true}')

    fixtures.fake_spawn(case, monkeypatch, behavior=drift)
    run_root = tmp_path / "run"
    receipt = fixtures.run(case, frozen, run_root, execute=True)
    outputs(case)
    result = collect(case, tmp_path, run_root)
    assert receipt["launch_count"] == 1 and receipt["restore_state"] == "Failed"
    assert result["host_observations"]["transport_state"] == "Failed"
    assert "RestoreFailed" in result["blockers"] and len(case.calls) == 1
    if host == "agy":
        assert (run_root / "private/settings.original.bin").read_bytes() == original
        assert case.settings.read_bytes() == b'{"synthetic_drift":true}'
    else:
        assert "ControlChanged" in result["blockers"] and result["continuation"] is None


@pytest.mark.parametrize("proof", ["self_report", "opaque", "null_hash", "drift"])
def test_c_receipt_test_declarations_never_promote_unverified_proof(tmp_path, monkeypatch, proof):
    case = actual_case(tmp_path, monkeypatch)
    frozen = fixtures.plan(case)
    fixtures.fake_spawn(case, monkeypatch)
    run_root = tmp_path / "run"
    receipt = fixtures.run(case, frozen, run_root, execute=True)
    outputs(case)
    report = run_root / "synthetic-junit.xml"
    report.write_bytes(b'<testsuite tests="1" failures="0"/>')
    evidence = {
        "ref": report.name,
        "sha256": runner._digest(report.read_bytes()),
        "origin": "HostObserved",
    }
    if proof == "opaque":
        evidence = copy.deepcopy(
            next(item for item in receipt["evidence_refs"] if item["ref"].startswith("session:"))
        )
    if proof == "null_hash":
        evidence["sha256"] = None
    if proof == "self_report":
        evidence["origin"] = "WorkerReported"
    test = {
        "test_run_id": "synthetic-test",
        "phase": "regression",
        "recipe_id": "fixture-test",
        "toolchain_sha256": fixtures.H,
        "source_tree_sha256": case.task["snapshot_id"],
        "exit_code": 0,
        "start_utc": "2026-10-06T00:00:00Z",
        "end_utc": "2026-10-06T00:00:01Z",
        "evidence_refs": [evidence],
        "origin": "WorkerReported" if proof == "self_report" else "HostObserved",
    }
    receipt["test_observations"] = [test]
    if proof == "drift":
        receipt["evidence_refs"] = sorted(
            [*receipt["evidence_refs"], evidence], key=lambda item: item["ref"].encode()
        )
        report.write_bytes(b"changed report bytes")
    fixtures.write_json(run_root / "run.json", receipt)
    result = collect(case, tmp_path, run_root)
    assert result["host_observations"]["test_observations"] == [test]
    assert "TestEvidenceUnverified" in result["blockers"]
    assert result["continuation"]["last_test_run_id"] is None
    assert result["management_decision"] is None
    if proof == "drift":
        assert "RunEvidenceDigestMismatch" in result["blockers"]
        assert (
            tmp_path / "collected/validation/current-run-evidence" / report.name
        ).read_bytes() == report.read_bytes()
