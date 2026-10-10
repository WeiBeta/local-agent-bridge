"""First v3 execution, with synthetic host and management process boundaries."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_first_task_r as legacy

from local_agent_bridge.bridge import layered_acceptance as layered
from local_agent_bridge.bridge import task_run as runner
from local_agent_bridge.bridge import task_workspace as workspace

validation = legacy.validation


@pytest.fixture
def case(tmp_path, monkeypatch):
    value = legacy.case.__wrapped__(tmp_path, monkeypatch, SimpleNamespace(param=3))
    value.manager_calls = []
    return value


def manager_process(case, monkeypatch, callback=None):
    def run(argv, **kwargs):
        assert kwargs["shell"] is False and kwargs["check"] is False
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 30
        case.manager_calls.append((argv.copy(), kwargs["cwd"]))
        phase = argv[-1]
        counts = (1, 1) if phase == "reproduce" else (6, 0)
        root = Path(kwargs["cwd"])
        children = "".join(
            '<testcase name="t'
            + str(i)
            + '">'
            + ("<failure/>" if i == 0 and counts[1] else "")
            + "</testcase>"
            for i in range(counts[0])
        )
        (root / "out" / (phase + ".xml")).write_text(
            f'<testsuite tests="{counts[0]}" failures="{counts[1]}" errors="0">'
            f"{children}</testsuite>",
            encoding="utf-8",
        )
        returned = SimpleNamespace(returncode=1 if phase == "reproduce" else 0)
        if callback is not None:
            callback(argv, root, returned)
        return returned

    monkeypatch.setattr(validation.subprocess, "run", run)


def fake_host(case, monkeypatch, output=None, **kwargs):
    def candidate():
        legacy.complete_output(case)
        (case.root / "work/source.py").write_bytes(b"answer = 30\n")
        (case.root / "out/regression.xml").write_bytes(b'<testsuite tests="999" failures="0"/>')
        if output is not None:
            output()

    return legacy.fake_spawn(case, monkeypatch, candidate, **kwargs)


def pinned(identity):
    value = runner._read(Path(identity["path"]))
    return {
        "value": value,
        "evidence_ref": {
            "ref": identity["path"],
            "sha256": identity["sha256"],
            "origin": "HostObserved",
        },
    }


def test_first_v3_binds_real_collector_and_independent_facts(case, monkeypatch):
    frozen = (case.root / "control/plan.json").read_bytes()
    blocked = runner.run_task(
        task_root=case.root,
        plan=case.frozen_plan,
        run_root=case.base / "ordinary-run",
        trusted_control_root=case.trust,
        trusted_inputs_sha256=case.expected,
        execute=True,
    )
    assert blocked["launch_count"] == 0 and blocked["transport_state"] == "NotRun"
    assert blocked["blockers"] == [runner.FIRST_LAYERED_BLOCKER] and not case.calls
    fake_host(case, monkeypatch)
    manager_process(case, monkeypatch)
    observed = legacy.invoke(case)
    assert observed["status"] == "ObservationRecorded", observed
    assert observed == legacy.observations(case)
    assert observed["collection_mode"] == "BoundFirstExecution"
    assert observed["launch_count"] == 1 and len(case.calls) == 1
    assert len(case.manager_calls) == 2
    assert (case.root / "control/plan.json").read_bytes() == frozen
    assert case.receipt["layered_acceptances"] == [] and case.receipt["runtime_acceptances"] == []
    run = runner._read(Path(case.sheet["run_root"]) / "run.json")
    collected = runner._read(Path(case.sheet["result_root"]) / "result.json")
    assert run["blockers"] == collected["blockers"] == []
    assert collected["plan_sha256"] == case.sheet["plan_sha256"]
    assert collected["continuation"]["session_id"] == run["capture_uid"]
    assert any(a["path"] == "run/first-execution.json" for a in collected["artifacts"])
    identities = observed["manager_evidence"]
    candidate = pinned(identities["candidate"])
    baseline = pinned(identities["baseline"])["value"]
    assert baseline["exit_code"] == 1 and baseline["tests"] == baseline["failures"] == 1
    assert candidate["value"]["actor"] == "ManagementIndependent"
    assert candidate["value"]["worker_shell_identity"] is None
    assert candidate["value"]["tests"] == 6 and candidate["value"]["exit_code"] == 0
    assert (
        candidate["value"]["source_tree_sha256"]
        == collected["continuation"]["candidate_tree_sha256"]
    )
    assert case.manager_calls == [
        (pinned(identities[name])["value"]["argv"], pinned(identities[name])["value"]["cwd"])
        for name in ("baseline", "candidate")
    ]
    evaluation = layered.evaluate_delivery(
        task=case.task,
        receipt=case.receipt,
        candidate_tree_sha256=collected["continuation"]["candidate_tree_sha256"],
        recipes=pinned(identities["recipes"])["value"],
        collection={
            "value": collected,
            "evidence_ref": {
                "ref": "result.json",
                "sha256": legacy.digest(collected),
                "origin": "HostObserved",
            },
        },
        manager_retest=candidate,
        host_lifecycle=pinned(identities["host_lifecycle"]),
    )
    assert evaluation["status"] == "Eligible" and evaluation["strict_r_status"] == "Unverified"
    assert evaluation["layers"]["worker_execution"]["result"] == "Unknown"
    blockers = []
    assert (
        workspace._run_receipt(
            case.root, Path(case.sheet["run_root"]), case.task, legacy.digest(case.task), blockers
        )[0]
        is None
    )
    assert "RunReceiptInvalid" in blockers
    with pytest.raises(runner.TaskRunError, match="TreeMismatch"):
        runner.run_task(
            task_root=case.root,
            plan=case.frozen_plan,
            run_root=case.base / "ordinary-after-candidate",
            trusted_control_root=case.trust,
            trusted_inputs_sha256=case.expected,
            execute=True,
        )
    with pytest.raises(validation.ValidationError):
        legacy.invoke(case)
    assert len(case.calls) == 1 and len(case.manager_calls) == 2


@pytest.mark.parametrize(
    "fault",
    [
        "waiver",
        "method",
        "permission",
        "task",
        "plan",
        "receipt",
        "unknown",
        "count",
        "timeout",
        "overlap",
        "environment",
        "validator",
        "partial_marker",
        "other_blocker",
    ],
)
def test_first_permit_only_covers_missing_prior_acceptance(case, monkeypatch, fault):
    fake_host(case, monkeypatch)
    manager_process(case, monkeypatch)
    if fault == "waiver":
        case.sheet["waived_blockers"].append("AuthorizationUnverified")
    elif fault == "method":
        case.sheet["acceptance_method"] = "other"
    elif fault == "permission":
        case.sheet["permissions"]["management_local_retest"] = False
    elif fault in {"task", "plan", "receipt"}:
        key = {"task": "task_id", "plan": "plan_sha256", "receipt": "receipt_binding_sha256"}[fault]
        case.sheet[key] = "other-task" if fault == "task" else "e" * 64
    elif fault == "unknown":
        case.sheet["argv"] = ["forbidden"]
    elif fault in {"count", "timeout"}:
        case.sheet["manager_retest"][
            "candidate_tests" if fault == "count" else "timeout_seconds"
        ] = True
    elif fault == "overlap":
        case.sheet["manager_retest"]["root"] = str(case.root / "scratch")
    elif fault == "environment":
        case.sheet["environment"]["sha256"] = "b" * 64
    elif fault == "validator":
        case.sheet["validator"]["sha256"] = "b" * 64
    elif fault == "partial_marker":
        (case.base / "fixture-permit.consumed.json").write_bytes(b"partial consumed marker")
    else:
        original_plan = runner._make_plan

        def additional_gate(*args, **kwargs):
            result = original_plan(*args, **kwargs)
            result["blockers"] = sorted([*result["blockers"], "RuntimeIdentityUnverified"])
            return result

        monkeypatch.setattr(runner, "_make_plan", additional_gate)
        legacy.freeze(case)
    legacy.update_sheet(case)
    with pytest.raises((validation.ValidationError, runner.TaskRunError)):
        legacy.invoke(case)
    assert not case.calls and not case.manager_calls
    assert not Path(case.sheet["run_root"]).exists()


@pytest.mark.parametrize(
    "fault",
    [
        "exit",
        "count",
        "malformed",
        "missing",
        "timeout",
        "source",
        "recipe",
        "executable",
        "original_candidate",
        "interrupt",
    ],
)
@pytest.mark.parametrize("phase", ["reproduce", "regression"])
def test_manager_commands_fail_closed_without_worker_substitution(case, monkeypatch, fault, phase):
    fake_host(case, monkeypatch)
    original_interrupt = KeyboardInterrupt("synthetic management interrupt")

    def fail(argv, root, process):
        if argv[-1] != phase:
            return
        target = root / "out" / (phase + ".xml")
        if fault == "exit":
            process.returncode = 99
        elif fault == "count":
            target.write_bytes(b'<testsuite tests="99" failures="0" errors="0"/>')
        elif fault == "malformed":
            target.write_bytes(b"broken XML")
        elif fault == "missing":
            target.rename(target.with_suffix(".retained.xml"))
        elif fault == "timeout":
            raise subprocess.TimeoutExpired(argv, 30)
        elif fault == "source":
            (root / "work/source.py").write_bytes(b"changed during management command")
        elif fault == "recipe":
            (root / argv[-2]).write_bytes(b"changed recipe during management command")
        elif fault == "executable":
            Path(case.sheet["installation"]["python"]["path"]).write_bytes(b"identity drift")
        elif fault == "original_candidate":
            (Path(case.sheet["result_root"]) / "candidate/source.py").write_bytes(
                b"late candidate drift"
            )
        else:
            raise original_interrupt

    manager_process(case, monkeypatch, fail)
    if fault == "interrupt":
        with pytest.raises(KeyboardInterrupt) as caught:
            legacy.invoke(case)
        assert caught.value is original_interrupt
        observed = legacy.observations(case)
    else:
        observed = legacy.invoke(case)
    assert observed["status"] == ("Interrupted" if fault == "interrupt" else "Failed")
    assert observed["launch_count"] == 1 and len(case.calls) == 1
    assert len(case.manager_calls) == (1 if phase == "reproduce" else 2)
    assert observed["runtime_acceptance"] == "Unverified"
    assert (case.base / "fixture-permit.consumed.json").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "task_id",
        "plan_sha256",
        "task_scope_sha256",
        "receipt_binding_sha256",
        "waived_blockers",
        "permit_identity",
        "consumption_identity",
        "unknown",
    ],
)
def test_first_record_drift_is_rejected_before_launch(case, monkeypatch, fault):
    fake_host(case, monkeypatch)
    manager_process(case, monkeypatch)
    original = validation._new_first_execution

    def create(*args):
        identity = original(*args)
        path = Path(identity["path"])
        record = runner._read(path)
        if fault == "unknown":
            record["accepted"] = True
        elif fault == "waived_blockers":
            record[fault] = []
        elif fault.endswith("identity"):
            record[fault]["sha256"] = "e" * 64
        else:
            record[fault] = "other-task" if fault == "task_id" else "e" * 64
        legacy.retain_and_write(path, runner._canonical(record))
        return {"path": str(path), "sha256": legacy.digest(record)}

    monkeypatch.setattr(validation, "_new_first_execution", create)
    observed = legacy.invoke(case)
    assert observed["status"] == "Failed" and observed["launch_count"] == 0
    assert not case.calls and not case.manager_calls
    assert (case.base / "fixture-permit.consumed.json").exists()


@pytest.mark.parametrize("fault", ["exit", "timeout", "capture", "restore", "unknown"])
def test_lifecycle_failure_never_starts_management_retest(case, monkeypatch, fault):
    if fault in {"exit", "timeout"}:
        fake_host(
            case,
            monkeypatch,
            exit_code=3 if fault == "exit" else 0,
            wait_error=subprocess.TimeoutExpired(["synthetic"], 1) if fault == "timeout" else None,
        )
    elif fault == "unknown":

        def launch(*args, **kwargs):
            kwargs["lifecycle"].execution_state = "unknown"
            kwargs["lifecycle"].stage = "resume_call"
            raise OSError("synthetic unknown launch")

        monkeypatch.setattr(runner.slice_run, "_launch_and_capture", launch)
    else:
        fake_host(case, monkeypatch)
        if fault == "capture":
            monkeypatch.setattr(
                runner.session.SessionWriter,
                "seal",
                lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic seal")),
            )
        else:
            monkeypatch.setattr(
                runner.slice_run,
                "_restore_settings",
                lambda *args: {"restored_original_bytes": False},
            )
    manager_process(case, monkeypatch)
    observed = legacy.invoke(case)
    assert observed["status"] == "Failed"
    assert observed["launch_count"] == (None if fault == "unknown" else 1)
    assert not case.manager_calls and observed["runtime_acceptance"] == "Unverified"


def test_ordinary_collector_does_not_discover_first_record(case, monkeypatch):
    fake_host(case, monkeypatch)
    manager_process(case, monkeypatch)
    observed = legacy.invoke(case)
    assert observed["status"] == "ObservationRecorded"
    result = workspace.collect_task(
        task_root=case.root,
        run_root=Path(case.sheet["run_root"]),
        result_root=case.base / "ordinary-collection",
    )
    assert "RunReceiptInvalid" in result["blockers"]
    assert result["host_observations"]["transport_state"] == "Failed"


def test_consumption_race_is_exclusive_and_never_launches(case, monkeypatch):
    original = validation._verify_context

    def verify(*args, **kwargs):
        returned = original(*args, **kwargs)
        if not kwargs.get("context"):
            (case.base / "fixture-permit.consumed.json").write_bytes(b"other consumer retained")
        return returned

    monkeypatch.setattr(validation, "_verify_context", verify)
    with pytest.raises(validation.ValidationError, match="PermitConsumed"):
        legacy.invoke(case)
    assert not case.calls and not case.manager_calls
    assert (case.base / "fixture-permit.consumed.json").read_bytes() == b"other consumer retained"


@pytest.mark.parametrize("fault", ["plan", "uid", "first_record_digest", "first_record_path"])
def test_collector_first_binding_cannot_drift(case, monkeypatch, fault):
    fake_host(case, monkeypatch)
    manager_process(case, monkeypatch)
    original = workspace.collect_task

    def collect(**kwargs):
        if fault == "first_record_digest":
            kwargs["first_execution"] = {**kwargs["first_execution"], "sha256": "e" * 64}
        elif fault == "first_record_path":
            kwargs["first_execution"] = {**kwargs["first_execution"], "path": str(case.sheet_path)}
        result = original(**kwargs)
        if fault == "plan":
            result["plan_sha256"] = "e" * 64
        elif fault == "uid":
            result["continuation"]["session_id"] = "other-new-uid"
        if fault in {"plan", "uid"}:
            target = Path(case.sheet["result_root"]) / "result.json"
            legacy.retain_and_write(target, runner._canonical(result))
        return result

    monkeypatch.setattr(workspace, "collect_task", collect)
    observed = legacy.invoke(case)
    assert observed["status"] == "Failed" and observed["launch_count"] == 1
    assert not case.manager_calls and len(case.calls) == 1


@pytest.mark.parametrize(
    "fault", ["bytes", "actor", "candidate_tree", "recipe", "baseline", "lifecycle", "report"]
)
def test_management_final_evidence_is_rechecked(case, monkeypatch, fault):
    fake_host(case, monkeypatch)
    manager_process(case, monkeypatch)
    original = validation._manager_retests

    def retest(*args):
        identities = original(*args)
        name = {"baseline": "baseline", "lifecycle": "host_lifecycle"}.get(fault, "candidate")
        path = Path(identities[name]["path"])
        value = runner._read(path)
        key = {
            "actor": "actor",
            "candidate_tree": "source_tree_sha256",
            "recipe": "recipe_sha256",
        }.get(fault)
        if key:
            value[key] = "Worker" if fault == "actor" else "e" * 64
        elif fault == "baseline":
            value["failures"] = 0
        elif fault == "lifecycle":
            value["capture_uid"] = "other-new-uid"
        elif fault == "report":
            report = path.parent / "out/regression.xml"
            legacy.retain_and_write(report, report.read_bytes() + b" ")
        legacy.retain_and_write(
            path, runner._canonical(value) + (b" " if fault == "bytes" else b"")
        )
        if key or fault in {"baseline", "lifecycle"}:
            identities[name]["sha256"] = legacy.digest(value)
        return identities

    monkeypatch.setattr(validation, "_manager_retests", retest)
    observed = legacy.invoke(case)
    assert observed["status"] == "Failed" and observed["launch_count"] == 1
    assert len(case.manager_calls) == 2 and observed["runtime_acceptance"] == "Unverified"
