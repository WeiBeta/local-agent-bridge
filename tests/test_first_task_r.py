"""Frozen permits and fake Task lifecycles only; no host/key/Job/provider IO."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_task_run import digest, fake_spawn, identity, plan, prepare, sync, write_json

from local_agent_bridge.bridge import slice_run, task_run, task_workspace, winjob
from local_agent_bridge.capture.session import SessionWriter

SCRIPT = Path(__file__).resolve().parents[1] / "verification" / "first_task_r.py"
spec = importlib.util.spec_from_file_location("first_task_r_validation", SCRIPT)
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


def freeze(case):
    sync(case, refresh_r=True)
    # First plan has exclusive controls; subsequent fixture rebinding is test-only.
    for filename in ("plan.json", "deployment-receipt.json"):
        target = case.root / "control" / filename
        if target.exists():
            case.saved_controls[filename + str(len(case.saved_controls))] = target.read_bytes()
            target.rename(
                case.base / (filename + ".fixture-previous-" + str(len(case.saved_controls)))
            )
    case.frozen_plan = plan(case)
    case.sheet.update(
        {
            "task_manifest_sha256": digest(case.task),
            "plan_sha256": digest(case.frozen_plan),
            "trusted_inputs_sha256": case.expected,
            "receipt_binding_sha256": digest(
                {
                    key: value
                    for key, value in case.receipt.items()
                    if key not in {"runtime_acceptances", "provenance_refs"}
                }
            ),
        }
    )
    write_json(case.sheet_path, case.sheet)
    case.sheet_sha = task_run._digest(case.sheet_path.read_bytes())


@pytest.fixture
def case(tmp_path, monkeypatch):
    value = prepare(
        tmp_path,
        monkeypatch,
        accepted=False,
        actual_b=True,
        files={"source.py": b"answer = 0\n", "test_recipe.py": b"assert answer == 30\n"},
    )
    value.base = tmp_path
    value.saved_controls = {}
    value.profile["roles"] = ["Coding"]
    value.profile["supported_capabilities"] = validation.CAPABILITIES.copy()
    value.profile["execution_modes"] = ["declared_scope"]
    value.task["protected_paths"] = sorted([*value.task["protected_paths"], "work/test_recipe.py"])
    value.receipt["toolchains"][0]["recipe_refs"] = [validation.RECIPE_REF]
    shell = tmp_path / "worker-shell.exe"
    shell.write_bytes(b"fake Worker Shell identity only")
    environment_path = tmp_path / "environment.json"
    write_json(
        environment_path,
        {
            "contract_version": 1,
            "kind": "TaskRuntimeValidationEnvironment",
            "local_appdata": str(tmp_path / "isolated-appdata"),
            "worker_shell": identity(shell),
        },
    )
    value.profile["enforcement"]["evidence_refs"] = [
        {
            "ref": str(environment_path),
            "sha256": identity(environment_path)["sha256"],
            "origin": "HostObserved",
        }
    ]
    wheel = tmp_path / "fixture-wheel.whl"
    wheel.write_bytes(b"fake wheel identity; never installed")
    value.receipt["bridge"]["wheel_sha256"] = identity(wheel)["sha256"]
    value.sheet_path = tmp_path / "permit.json"
    value.sheet = {
        "contract_version": 1,
        "kind": "TaskRuntimeValidationPermit",
        "permit_id": "fixture-permit",
        "task_id": value.task["task_id"],
        "management_task_id": validation.MANAGEMENT_TASK,
        "approval": {"status": "Approved", "author_confirmed": True},
        "grant_ref": value.auth["grant_ref"],
        "budget_ref": {
            "ref": "fake-budget-no-real-grant",
            "sha256": "a" * 64,
            "origin": "HostObserved",
        },
        "max_host_launches": 1,
        "host": "agy",
        "role": "Coding",
        "capabilities": validation.CAPABILITIES.copy(),
        "execution_boundary": "declared_scope",
        "task_root": str(value.root),
        "trusted_control_root": str(value.trust),
        "run_root": str(tmp_path / "validation-run"),
        "result_root": str(tmp_path / "validation-result"),
        "deadline_seconds": value.task["deadline_seconds"],
        "validator": identity(SCRIPT),
        "installation": {
            "root": str(value.host_entry.parent),
            "python": value.receipt["toolchains"][0]["identity_files"][0],
            "wheel": identity(wheel),
        },
        "environment": identity(environment_path),
        "recipes": [
            {"ref": validation.RECIPE_REF, "identity": identity(value.root / "work/test_recipe.py")}
        ],
        "permissions": dict.fromkeys(validation.PERMISSIONS, True),
    }
    value.identity_checks = []

    def fake_installation(sheet, receipt):
        value.identity_checks.append(sheet["installation"]["root"])
        for item in (sheet["installation"]["python"], sheet["installation"]["wheel"]):
            task_run._verify_file_identity(item)
        validation._require(
            sheet["installation"]["wheel"]["sha256"] == receipt["bridge"]["wheel_sha256"],
            "InstallationUnverified",
        )
        task_run._verify_runtime_identity(receipt)

    monkeypatch.setattr(validation, "_verify_installation", fake_installation)
    monkeypatch.setattr(task_run, "_configuration_lease", lambda _path: contextlib.nullcontext())
    freeze(value)
    return value


def invoke(case):
    return validation.validate_once(sheet_path=case.sheet_path, expected_sha256=case.sheet_sha)


def update_sheet(case):
    write_json(case.sheet_path, case.sheet)
    case.sheet_sha = task_run._digest(case.sheet_path.read_bytes())


def complete_output(case):
    write_json(
        case.root / "out/progress.json",
        {
            "contract_version": 1,
            "task_id": case.task["task_id"],
            "status": "Completed",
            "summary": "synthetic candidate only",
            "remaining_paths": [],
        },
    )


def observations(case):
    return task_run._read(Path(case.sheet["run_root"]) / "validation.json")


def test_fake_lifecycle_records_observation_and_keeps_production_blocked(case, monkeypatch):
    original_appdata = os.environ.get("LOCALAPPDATA")
    controls = {
        name: (case.root / "control" / name).read_bytes()
        for name in ("plan.json", "deployment-receipt.json", "authorization.json")
    }
    process = fake_spawn(case, monkeypatch, lambda: complete_output(case))
    result = invoke(case)
    assert result["kind"] == "TaskRuntimeValidation" and result["status"] == "ObservationRecorded"
    assert result["launch_count"] == 1 and result["runtime_acceptance"] == "Unverified"
    assert result["management_decision"] is None and len(case.calls) == 1
    assert process.closed and result == observations(case)
    assert len(case.identity_checks) >= 4 and os.environ.get("LOCALAPPDATA") == original_appdata
    assert all((case.root / "control" / name).read_bytes() == raw for name, raw in controls.items())
    run = task_run._read(Path(case.sheet["run_root"]) / "run.json")
    assert run["blockers"] == [validation.MISSING_R]
    collected = task_run._read(Path(case.sheet["result_root"]) / "result.json")
    assert collected["host_observations"]["scope_status"] == "Pass"
    assert collected["host_observations"]["transport_state"] == "NotRun"
    assert collected["management_decision"] is None
    ordinary_blockers = []
    normal_receipt, _ = task_workspace._run_receipt(
        case.root, Path(case.sheet["run_root"]), case.task, digest(case.task), ordinary_blockers
    )
    assert normal_receipt is None and "RunReceiptInvalid" in ordinary_blockers
    ordinary = task_run.run_task(
        task_root=case.root,
        plan=case.frozen_plan,
        run_root=case.base / "ordinary-still-blocked",
        trusted_control_root=case.trust,
        trusted_inputs_sha256=case.expected,
        execute=True,
    )
    assert ordinary["transport_state"] == "NotRun" and ordinary["launch_count"] == 0
    assert len(case.calls) == 1
    with pytest.raises(validation.ValidationError):
        invoke(case)
    assert len(case.calls) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "proposed",
        "unconfirmed",
        "permission",
        "budget",
        "bool_count",
        "host",
        "role",
        "caps",
        "boundary",
        "unknown",
        "deadline",
    ],
)
def test_closed_permit_rejects_unapproved_or_expanded_fields_without_effects(case, mutation):
    if mutation == "proposed":
        case.sheet["approval"]["status"] = "Proposed"
    elif mutation == "unconfirmed":
        case.sheet["approval"]["author_confirmed"] = False
    elif mutation == "permission":
        case.sheet["permissions"]["capture_key_read"] = False
    elif mutation == "budget":
        case.sheet["budget_ref"]["origin"] = "WorkerReported"
    elif mutation == "bool_count":
        case.sheet["max_host_launches"] = True
    elif mutation in {"host", "role", "boundary"}:
        case.sheet[{"boundary": "execution_boundary"}.get(mutation, mutation)] = {
            "host": "cursor",
            "role": "Review",
            "boundary": "required_enforced",
        }[mutation]
    elif mutation == "caps":
        case.sheet["capabilities"]["web_reference"] = True
    elif mutation == "unknown":
        case.sheet["argv"] = ["forbidden"]
    else:
        case.sheet["deadline_seconds"] = True
    update_sheet(case)
    with pytest.raises((validation.ValidationError, task_run.TaskRunError)):
        invoke(case)
    assert not Path(case.sheet["run_root"]).exists() and not case.calls
    assert not list(case.base.glob("*.consumed.json"))


@pytest.mark.parametrize("fault", ["missing", "changed", "duplicate", "consumed", "validator"])
def test_permit_bytes_and_consumption_are_fixed(case, fault):
    if fault == "missing":
        case.sheet_path.rename(case.base / "saved-permit.json")
    elif fault == "changed":
        case.sheet_path.write_bytes(case.sheet_path.read_bytes() + b" ")
    elif fault == "duplicate":
        raw = case.sheet_path.read_bytes().replace(b"{", b'{"kind":"duplicate",', 1)
        case.sheet_path.write_bytes(raw)
        case.sheet_sha = task_run._digest(raw)
    elif fault == "consumed":
        (case.base / "fixture-permit.consumed.json").write_bytes(b"partial preserved")
    else:
        case.sheet["validator"]["sha256"] = "b" * 64
        update_sheet(case)
    with pytest.raises(
        (validation.ValidationError, task_run.TaskRunError, task_run.contract.BridgeContractError)
    ):
        invoke(case)
    assert not case.calls and not Path(case.sheet["run_root"]).exists()


@pytest.mark.parametrize(
    "fault", ["root", "identity", "binding", "other_blocker", "recipe", "environment"]
)
def test_every_non_r_gate_is_required_before_consumption(case, fault):
    if fault == "root":
        case.sheet["run_root"] = str(case.root / "unauthorized-run")
    elif fault == "identity":
        case.host_entry.write_bytes(b"drifted fake identity")
    elif fault == "binding":
        case.sheet["receipt_binding_sha256"] = "c" * 64
    elif fault == "other_blocker":
        case.receipt["toolchains"] = []
        case.profile["toolchain_refs"] = []
        freeze(case)
    elif fault == "recipe":
        case.sheet["recipes"][0]["identity"]["sha256"] = "d" * 64
    else:
        case.profile["enforcement"]["evidence_refs"] = []
        freeze(case)
    update_sheet(case)
    with pytest.raises((validation.ValidationError, task_run.TaskRunError)):
        invoke(case)
    assert not case.calls and not list(case.base.glob("*.consumed.json"))


@pytest.mark.parametrize("configuration", [[], {"permissions": []}, {"permissions": {"ask": []}}])
def test_invalid_configuration_consumes_permit_and_retains_failure(case, configuration):
    write_json(case.settings, configuration)
    case.receipt["configuration"]["agy_settings"] = identity(case.settings)
    freeze(case)
    result = invoke(case)
    assert result["status"] == "Failed" and result["launch_count"] == 0
    assert observations(case) == result and not case.calls
    assert (case.base / "fixture-permit.consumed.json").exists()
    assert json.loads(case.settings.read_bytes()) == configuration


@pytest.mark.parametrize("count", [0, 1, None])
def test_fake_launch_failure_records_zero_one_or_unknown_without_retry(case, monkeypatch, count):
    if count == 1:
        fake_spawn(case, monkeypatch, wait_error=OSError("private failure body"))
    else:

        def fail_spawn(argv, cwd, *, lifecycle):
            case.calls.append((argv, cwd))
            if count is None:
                lifecycle.execution_state = "unknown"
            raise winjob.AgWinJobError("spawn_failed")

        monkeypatch.setattr(slice_run, "spawn_suspended_in_job", fail_spawn)
    result = invoke(case)
    assert result["status"] == "Failed" and result["launch_count"] is count
    assert len(case.calls) == 1 and result == observations(case)
    assert "private failure body" not in json.dumps(result)


@pytest.mark.parametrize("fault", ["capture", "restore"])
def test_capture_and_restore_failure_are_not_r_acceptance(case, monkeypatch, fault):
    fake_spawn(case, monkeypatch, lambda: complete_output(case))
    if fault == "capture":

        def fail_seal(*args, **kwargs):
            raise OSError("private capture diagnostic")

        monkeypatch.setattr(SessionWriter, "seal", fail_seal)
    else:
        monkeypatch.setattr(
            slice_run, "_restore_settings", lambda *args: {"restored_original_bytes": False}
        )
    result = invoke(case)
    assert result["status"] == "Failed" and result["launch_count"] == 1
    assert result["runtime_acceptance"] == "Unverified" and len(case.calls) == 1


@pytest.mark.parametrize("secondary", ["none", "collect", "write"])
def test_original_interrupt_survives_secondary_cleanup_failure(case, monkeypatch, secondary):
    interrupt = KeyboardInterrupt("private interrupt body")
    fake_spawn(case, monkeypatch, wait_error=interrupt)
    original_appdata = os.environ.get("LOCALAPPDATA")

    def fail(*args, **kwargs):
        raise OSError("private secondary diagnostic")

    if secondary == "collect":
        monkeypatch.setattr(task_workspace, "collect_task", fail)
    elif secondary == "write":
        original_persist = task_run._persist

        def persist(path, value, **kwargs):
            if path.name == "validation.json":
                return fail()
            return original_persist(path, value, **kwargs)

        monkeypatch.setattr(task_run, "_persist", persist)
    with pytest.raises(KeyboardInterrupt) as caught:
        invoke(case)
    assert caught.value is interrupt and len(case.calls) == 1
    assert os.environ.get("LOCALAPPDATA") == original_appdata
    assert (Path(case.sheet["run_root"]) / "run.json").exists()
    if secondary != "write":
        assert observations(case)["status"] == "Interrupted"


def test_recheck_detects_permit_drift_after_capture_start_before_launch(case, monkeypatch):
    original_start = case.store.start

    def start():
        writer = original_start()
        case.sheet_path.write_bytes(case.sheet_path.read_bytes() + b" ")
        return writer

    monkeypatch.setattr(case.store, "start", start)
    result = invoke(case)
    assert result["status"] == "Failed" and result["launch_count"] == 0 and not case.calls
    assert (Path(case.sheet["run_root"]) / "private/settings.original.bin").exists()
    assert (case.base / "fixture-permit.consumed.json").exists()


def test_no_lifecycle_receipt_is_unknown_not_zero(case, monkeypatch):
    def no_receipt(*args):
        raise OSError("private unknown-execution detail")

    monkeypatch.setattr(task_run, "_execute_once", no_receipt)
    result = invoke(case)
    assert result["status"] == "Failed" and result["launch_count"] is None
    assert result == observations(case)


@pytest.mark.parametrize("fault", ["missing_output", "protected_change"])
def test_collection_gaps_are_failed_observations(case, monkeypatch, fault):
    def change():
        if fault == "protected_change":
            complete_output(case)
            (case.root / "work/test_recipe.py").write_bytes(b"changed protected recipe")

    fake_spawn(case, monkeypatch, change)
    result = invoke(case)
    assert result["status"] == "Failed" and result["launch_count"] == 1
    assert result["collection_mode"] == "ArtifactsOnlyNullRun"
    assert result["runtime_acceptance"] == "Unverified"


def test_malformed_secondary_receipt_does_not_replace_original_interrupt(case, monkeypatch):
    interrupt = KeyboardInterrupt("original private interrupt")

    def interrupted(*args):
        write_json(Path(case.sheet["run_root"]) / "run.json", {"contract_version": 1})
        raise interrupt

    monkeypatch.setattr(task_run, "_execute_once", interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        invoke(case)
    assert caught.value is interrupt
    assert observations(case)["launch_count"] is None
    assert observations(case)["status"] == "Interrupted"


def test_cli_requires_closed_arguments_and_redacts_errors(case, capsys):
    case.sheet["approval"]["status"] = "Proposed"
    update_sheet(case)
    assert (
        validation.main(
            ["--acceptance-sheet", str(case.sheet_path), "--expected-sha256", case.sheet_sha]
        )
        == 2
    )
    output = capsys.readouterr()
    assert json.loads(output.out)["error_code"] == "PermissionUnverified"
    assert str(case.sheet_path) not in output.out and not output.err
    with pytest.raises(SystemExit) as error:
        validation.main(
            [
                "--acceptance-sheet",
                str(case.sheet_path),
                "--expected-sha256",
                case.sheet_sha,
                "--model",
                "forbidden",
            ]
        )
    assert error.value.code == 2


@pytest.mark.parametrize(
    "fault", ["none", "editable", "wheel", "installed", "missing_payload", "prefix"]
)
def test_installation_verifier_checks_real_fixture_bytes_and_origin(tmp_path, monkeypatch, fault):
    root = tmp_path / "fixture-install"
    package = root / "Lib/site-packages/local_agent_bridge"
    package.mkdir(parents=True)
    source = package / "task_run.py"
    source.write_bytes(b"frozen fixture payload; not imported")
    python = root / "Scripts/python.exe"
    python.parent.mkdir()
    python.write_bytes(b"fake interpreter; not executed")
    entry = python.parent / "local-agent-bridge.exe"
    entry.write_bytes(b"fake console; not executed")
    wheel_path = tmp_path / "fixture.whl"
    with zipfile.ZipFile(wheel_path, "w") as wheel:
        wheel.writestr("local_agent_bridge/task_run.py", source.read_bytes())
    sheet = {
        "installation": {
            "root": str(root),
            "python": identity(python),
            "wheel": identity(wheel_path),
        }
    }
    receipt = {
        "bridge": {
            "entry": identity(entry),
            "version": "fixture",
            "wheel_sha256": identity(wheel_path)["sha256"],
            "product_files": [identity(source)],
        },
        "host_entry": identity(entry),
        "host_identity_files": [identity(entry)],
        "toolchains": [],
        "host": "agy",
    }
    distribution = SimpleNamespace(
        locate_file=lambda _name: package,
        version="fixture",
        read_text=lambda _name: (
            json.dumps({"dir_info": {"editable": True}}) if fault == "editable" else None
        ),
    )
    monkeypatch.setattr(validation.metadata, "distribution", lambda _name: distribution)
    monkeypatch.setattr(validation.sys, "prefix", str(root if fault != "prefix" else tmp_path))
    monkeypatch.setattr(validation.sys, "executable", str(python))
    monkeypatch.setattr(task_run, "_runtime_files", lambda: {source})
    if fault == "wheel":
        with zipfile.ZipFile(wheel_path, "w") as wheel:
            wheel.writestr("local_agent_bridge/task_run.py", b"different fixture bytes")
        sheet["installation"]["wheel"] = identity(wheel_path)
        receipt["bridge"]["wheel_sha256"] = identity(wheel_path)["sha256"]
    elif fault == "installed":
        source.write_bytes(b"changed installed bytes")
    elif fault == "missing_payload":
        receipt["bridge"]["product_files"] = []
    if fault == "none":
        validation._verify_installation(sheet, receipt)
    else:
        with pytest.raises((validation.ValidationError, task_run.TaskRunError)):
            validation._verify_installation(sheet, receipt)
