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
from test_task_run import FakeProcess, digest, fake_spawn, identity, plan, prepare, sync, write_json

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


@pytest.fixture(params=[1, 2], ids=["legacy-v1", "first-observation-v2"])
def case(tmp_path, monkeypatch, request):
    original_close = FakeProcess.close_job

    def close_job(process):
        original_close(process)
        return True  # The fake explicitly reports its already recorded successful owned close.

    monkeypatch.setattr(FakeProcess, "close_job", close_job)
    value = prepare(
        tmp_path,
        monkeypatch,
        accepted=False,
        actual_b=True,
        files={"source.py": b"answer = 0\n", "test_recipe.py": b"assert answer == 30\n"},
    )
    version = request.param
    if version == 2:
        value.receipt.update(
            contract_version=2,
            host_identity_files=[],
            host_composition=task_run.FIRST_OBSERVATION_COMPOSITION.copy(),
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
    environment = {
        "contract_version": version,
        "kind": "TaskRuntimeValidationEnvironment",
        "local_appdata": str(tmp_path / "isolated-appdata"),
        "worker_shell": identity(shell),
    }
    if version == 2:
        environment.update(
            scope="FirstObservation", worker_shell={"status": "Unknown", "identity": None}
        )
    write_json(environment_path, environment)
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
        "contract_version": version,
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


def retain_and_write(path, raw, *, retained_root=None):
    root = path.parent if retained_root is None else retained_root
    root.mkdir(exist_ok=True)
    retained = root / (path.name + ".retained-" + str(len(list(root.glob("*.retained-*")))))
    path.rename(retained)
    path.write_bytes(raw)


@pytest.mark.parametrize(
    "returned,saved,local,expected_count",
    [
        ("interrupt", "task-zero", 1, 1),
        ("interrupt", "task-one", 0, 0),
        ("interrupt", "plan-zero", 1, 1),
        ("none", "plan-one", 0, 0),
        ("interrupt", "plan-unknown", 1, 1),
        ("interrupt", "state-zero", 1, 1),
        ("interrupt", "state-one", "missing", None),
        ("interrupt", "capture-zero", 1, 1),
        ("none", "capture-one", "missing", None),
        ("interrupt", "restore-zero", 1, 1),
        ("none", "restore-one", "missing", None),
        ("interrupt", "version-zero", 1, 1),
        ("none", "version-one", "missing", None),
        ("none", "notrun-one", "missing", None),
        ("interrupt", "notrun-sealed-zero", 1, 1),
        ("none", "completed-zero", 1, 1),
        ("interrupt", "timeout-zero", 1, 1),
        ("interrupt", "unknown-no-blocker", 1, 1),
        ("none", "count-bool", "missing", None),
        ("interrupt", "count-two", 1, 1),
        ("interrupt", "uid-number", "missing", None),
        ("interrupt", "missing", 1, 1),
        ("none", "missing", 0, 0),
        ("interrupt", "missing", None, None),
        ("interrupt", "missing", "missing", None),
        ("none", "malformed", "mismatch", None),
        ("interrupt", "noncanonical", 1, 1),
        ("interrupt", "zero", "missing", 0),
        ("interrupt", "one", "missing", 1),
        ("interrupt", "one", "mismatch", 1),
        ("none", "one", None, 1),
        ("interrupt", "bad-ref-one", "missing", 1),
        ("interrupt", "bad-tests-one", "missing", 1),
        ("interrupt", "zero", 1, 1),
        ("interrupt", "one", 0, 1),
        ("interrupt", "unknown", "missing", None),
        ("interrupt", "unknown", 0, 0),
        (None, "task-zero", 1, 1),
        (None, "one", "missing", 1),
        (None, "one", 0, 1),
        (0, "task-one", 1, 0),
        (1, "plan-zero", 0, 1),
        (0, "one", 1, 0),
        (1, "zero", 0, 1),
        ("malformed", "task-zero", 1, 1),
        ("bool", "task-zero", 1, 1),
        ("two", "task-zero", 1, 1),
    ],
)
def test_launch_count_sources_are_bound_and_ordered(
    case, monkeypatch, returned, saved, local, expected_count
):
    interrupt = KeyboardInterrupt("original synthetic interrupt")
    calls = []
    preserved = {}

    def body(count):
        value = task_run._receipt(case.frozen_plan)
        value.update(transport_state="Failed", launch_count=count)
        value["blockers"] = ["LaunchUnverified"] if count is None else []
        return value

    def execute(*args):
        calls.append(args)
        complete_output(case)
        root = Path(case.sheet["run_root"])
        count = 1 if saved.endswith("one") else None if "unknown" in saved else 0
        value = body(count)
        if local != "missing":
            local_value = {
                "spawn_state": {0: "not_attempted", 1: "confirmed", None: "unknown"}.get(
                    local, "confirmed"
                ),
                "launch_count": local if local != "mismatch" else 0,
            }
            write_json(root / "launch.json", local_value)
            value["evidence_refs"] = [
                {"ref": "launch.json", "sha256": digest(local_value), "origin": "HostObserved"}
            ]
        if saved.startswith("task"):
            value["task_id"] = "wrong-task"
        elif saved.startswith("plan"):
            value["plan_sha256"] = "e" * 64
        elif saved.startswith("state"):
            value["transport_state"] = "invalid"
        elif saved.startswith("capture"):
            value["capture_state"] = "invalid"
        elif saved.startswith("restore"):
            value["restore_state"] = "invalid"
        elif saved.startswith("version"):
            value["contract_version"] = 2
        elif saved.startswith("notrun"):
            value["transport_state"] = "NotRun"
            if saved == "notrun-sealed-zero":
                value.update(capture_state="Sealed", capture_uid="fake-session")
        elif saved == "completed-zero":
            value["transport_state"] = "Completed"
        elif saved == "timeout-zero":
            value["transport_state"] = "TimedOut"
        elif saved == "unknown-no-blocker":
            value["blockers"] = []
        elif saved.startswith("count"):
            value["launch_count"] = True if saved == "count-bool" else 2
        elif saved == "uid-number":
            value["capture_uid"] = 42
        elif saved == "bad-ref-one":
            value["evidence_refs"] = [None]
        elif saved == "bad-tests-one":
            value["test_observations"] = [None]
        elif saved == "malformed":
            value = {"launch_count": 0}
        raw = task_run._canonical(value) + (b" " if saved == "noncanonical" else b"")
        preserved["raw"] = raw
        # Missing fixed run keeps the original bytes at a separate retained name.
        (root / ("run.retained.json" if saved == "missing" else "run.json")).write_bytes(raw)
        if returned == "interrupt":
            raise interrupt
        if returned == "none":
            return None
        if returned == "malformed":
            return {"launch_count": 0}
        return body(True if returned == "bool" else 2 if returned == "two" else returned)

    monkeypatch.setattr(task_run, "_execute_once", execute)
    if returned == "interrupt":
        with pytest.raises(KeyboardInterrupt) as caught:
            invoke(case)
        assert caught.value is interrupt
    else:
        assert invoke(case)["status"] == "Failed"
    observed = observations(case)
    assert observed["launch_count"] is expected_count and len(calls) == 1
    assert observed["status"] == ("Interrupted" if returned == "interrupt" else "Failed")
    assert observed["runtime_acceptance"] == "Unverified"
    assert (case.base / "fixture-permit.consumed.json").exists()
    root = Path(case.sheet["run_root"])
    retained = root / ("run.retained.json" if saved == "missing" else "run.json")
    assert retained.read_bytes() == preserved["raw"]
    if saved not in {"zero", "one", "unknown"} or local == "mismatch":
        assert observed["run_receipt_sha256"] is None


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "noncanonical",
        "returned",
        "task",
        "plan",
        "none_return",
        "launch_missing",
        "restore_missing",
        "launch_hash",
        "restore_hash",
        "launch_ref_missing",
        "restore_ref_missing",
        "duplicate_bad",
        "duplicate_good",
        "launch_fact",
        "restore_fact",
        "restored_settings",
        "unknown_ref",
        "session_binding",
    ],
)
def test_saved_lifecycle_and_every_local_declaration_are_required(case, monkeypatch, fault):
    fake_spawn(case, monkeypatch, lambda: complete_output(case))
    original_execute = task_run._execute_once
    forbidden = case.base / "unrelated-evidence.json"
    forbidden.write_bytes(b"not authorized evidence")
    original_reader = task_run.read_host_input_bytes

    def reader(*, path):
        assert Path(path) != forbidden, "unknown evidence ref must not be read"
        return original_reader(path=path)

    monkeypatch.setattr(task_run, "read_host_input_bytes", reader)

    def execute(*args, **kwargs):
        returned = original_execute(*args, **kwargs)
        root = Path(case.sheet["run_root"])
        path = root / "run.json"
        if fault == "none_return":
            return None
        if fault == "missing":
            path.rename(root / "run.json.retained-original")
        elif fault == "noncanonical":
            retain_and_write(path, path.read_bytes() + b" ")
        elif fault == "returned":
            returned = {**returned, "restore_state": "Failed"}
        elif fault == "restored_settings":
            retain_and_write(case.settings, b'{"changed":true}')
        else:
            if fault in {"task", "plan"}:
                returned["task_id" if fault == "task" else "plan_sha256"] = (
                    "other-task" if fault == "task" else "e" * 64
                )
            elif fault in {"launch_ref_missing", "restore_ref_missing"}:
                name = "launch.json" if fault.startswith("launch") else "config-restore.json"
                returned["evidence_refs"] = [
                    e for e in returned["evidence_refs"] if e["ref"] != name
                ]
            elif fault.startswith("duplicate"):
                reference = next(e for e in returned["evidence_refs"] if e["ref"] == "launch.json")
                returned["evidence_refs"].append(
                    {**reference, "sha256": "f" * 64}
                    if fault == "duplicate_bad"
                    else reference.copy()
                )
            elif fault == "unknown_ref":
                returned["evidence_refs"].append(
                    {"ref": str(forbidden), "sha256": "a" * 64, "origin": "HostObserved"}
                )
            elif fault == "session_binding":
                next(e for e in returned["evidence_refs"] if e["ref"].startswith("session:"))[
                    "ref"
                ] = "session:other"
            else:
                name = "launch.json" if fault.startswith("launch") else "config-restore.json"
                evidence_path = root / name
                if fault.endswith("missing"):
                    evidence_path.rename(root / (name + ".retained-original"))
                elif fault.endswith("hash"):
                    retain_and_write(evidence_path, task_run._canonical({"drifted": True}))
                else:
                    value = task_run._read(evidence_path)
                    value["launch_count" if name == "launch.json" else "final_sha256"] = (
                        0 if name == "launch.json" else "a" * 64
                    )
                    retain_and_write(evidence_path, task_run._canonical(value))
                    next(e for e in returned["evidence_refs"] if e["ref"] == name)["sha256"] = (
                        digest(value)
                    )
            retain_and_write(path, task_run._canonical(returned))
        return returned

    monkeypatch.setattr(task_run, "_execute_once", execute)
    result = invoke(case)
    assert result["launch_count"] == 1 and len(case.calls) == 1
    assert result == observations(case) and result["runtime_acceptance"] == "Unverified"
    assert result["status"] == (
        "ObservationRecorded" if fault in {"none_return", "duplicate_good"} else "Failed"
    )
    if fault in {"missing", "noncanonical", "returned", "task", "plan"}:
        assert result["run_receipt_sha256"] is None
    if fault == "duplicate_good":
        assert len([e for e in result["run_evidence_checks"] if e["ref"] == "launch.json"]) == 2
    if result["status"] == "ObservationRecorded":
        assert result["run_receipt_sha256"] == task_run._digest(
            (Path(case.sheet["run_root"]) / "run.json").read_bytes()
        )
        assert any(e["check"] == "OpaqueDeclarationOnly" for e in result["run_evidence_checks"])
    if fault == "unknown_ref":
        assert result["error_code"] == "RunEvidenceRefRejected"


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "bytes",
        "returned",
        "task",
        "artifact_manifest",
        "artifact_missing",
        "artifact_changed",
        "extra_file",
        "control",
        "source_after_collect",
        "directory_after_collect",
        "environment",
        "run_after_collect",
    ],
)
def test_actual_collection_artifacts_and_final_binding_are_required(case, monkeypatch, fault):
    fake_spawn(case, monkeypatch, lambda: complete_output(case))
    original_collect = task_workspace.collect_task

    def collect(**kwargs):
        result = original_collect(**kwargs)
        root = Path(case.sheet["result_root"])
        path = root / "result.json"

        def retain(target, raw):
            retain_and_write(target, raw, retained_root=case.base / "retained-collected-files")

        if fault == "missing":
            path.rename(root / "result.json.retained-original")
        elif fault == "bytes":
            retain(path, path.read_bytes() + b" ")
        elif fault == "returned":
            result = {**result, "task_id": "other-return"}
        elif fault == "task":
            result["task_id"] = "other-task"
            retain(path, task_run._canonical(result))
        elif fault == "artifact_manifest":
            manifest = root / "artifacts.json"
            retain(manifest, manifest.read_bytes() + b" ")
        elif fault in {"artifact_missing", "artifact_changed"}:
            artifact = next(a for a in result["artifacts"] if a["origin"] == "CandidateTree")
            target = root / artifact["path"]
            if fault == "artifact_missing":
                target.rename(case.base / "retained-candidate-file")
            else:
                retain(target, target.read_bytes() + b"changed")
        elif fault == "extra_file":
            (root / "undeclared.bin").write_bytes(b"synthetic")
        elif fault == "control":
            target = root / "host/control/plan.json"
            value = task_run._read(target)
            value["task_id"] = "wrong-control-task"
            retain(target, task_run._canonical(value))
            artifact = next(a for a in result["artifacts"] if a["path"] == "host/control/plan.json")
            artifact.update({"bytes": target.stat().st_size, "sha256": digest(value)})
            artifact_raw = task_run._canonical(result["artifacts"])
            retain(root / "artifacts.json", artifact_raw)
            result["continuation"]["artifact_manifest_sha256"] = task_run._digest(artifact_raw)
            retain(path, task_run._canonical(result))
        elif fault == "source_after_collect":
            retain_and_write(case.root / "work/source.py", b"post-collection source drift")
        elif fault == "directory_after_collect":
            (case.root / "work/post-collect-authored").mkdir()
        elif fault == "environment":
            environment = Path(case.sheet["environment"]["path"])
            retain_and_write(environment, environment.read_bytes() + b" ")
        else:
            run = Path(case.sheet["run_root"]) / "run.json"
            run.rename(case.base / "retained-run-after-collect.json")
        return result

    monkeypatch.setattr(task_workspace, "collect_task", collect)
    result = invoke(case)
    assert result["status"] == "Failed" and result["launch_count"] == 1
    assert len(case.calls) == 1 and result == observations(case)
    assert (case.base / "fixture-permit.consumed.json").exists()


def test_legitimate_authored_source_change_is_collected(case, monkeypatch):
    def output():
        complete_output(case)
        (case.root / "work/source.py").write_bytes(b"answer = 30\n")
        (case.root / "work/new-authored-directory").mkdir()

    fake_spawn(case, monkeypatch, output)
    result = invoke(case)
    assert result["status"] == "ObservationRecorded" and result["launch_count"] == 1
    assert (
        Path(case.sheet["result_root"]) / "candidate/source.py"
    ).read_bytes() == b"answer = 30\n"
    assert (Path(case.sheet["result_root"]) / "candidate/new-authored-directory").is_dir()


DIRECTORY_DOMAINS = {
    "authored": ("work/authored-empty/nested", "candidate/authored-empty/nested"),
    "generated": ("work/pkg/.venv/nested", "generated/work/pkg/.venv/nested"),
    "out": ("out/empty/nested", "out/empty/nested"),
    "scratch": ("scratch/empty/nested", "scratch/empty/nested"),
}


@pytest.mark.parametrize("domain", DIRECTORY_DOMAINS)
@pytest.mark.parametrize(
    "fault",
    [
        "before",
        "source_add",
        "source_remove",
        "source_rename",
        "result_add",
        "result_remove",
        "result_wrong_map",
    ],
)
def test_complete_directory_mapping(case, monkeypatch, domain, fault):
    source_path, published_path = DIRECTORY_DOMAINS[domain]
    source = case.root / source_path
    result_root = Path(case.sheet["result_root"])
    published = result_root / published_path

    def output():
        complete_output(case)
        source.mkdir(parents=True)

    fake_spawn(case, monkeypatch, output)
    original_collect = task_workspace.collect_task

    def collect(**kwargs):
        result = original_collect(**kwargs)
        assert source.is_dir() and published.is_dir()
        if fault == "source_add":
            (source / "late-empty").mkdir()
        elif fault == "source_remove":
            source.rename(case.base / "retained-source-directory")
        elif fault == "source_rename":
            source.rename(source.with_name("renamed-empty"))
        elif fault == "result_add":
            (published / "late-empty").mkdir()
        elif fault == "result_remove":
            published.rename(case.base / "retained-result-directory")
        elif fault == "result_wrong_map":
            published.rename(result_root / "out/misplaced-empty")
        return result

    monkeypatch.setattr(task_workspace, "collect_task", collect)
    observed = invoke(case)
    assert observed == observations(case) and observed["launch_count"] == 1
    assert observed["status"] == ("ObservationRecorded" if fault == "before" else "Failed")
    assert observed["runtime_acceptance"] == "Unverified" and len(case.calls) == 1
    if fault != "before":
        assert observed["run_receipt_sha256"] is None
        assert observed["collection_sha256"] is None
    assert (case.base / "fixture-permit.consumed.json").exists()


@pytest.mark.parametrize(
    "operation,relative",
    [
        ("add", "candidate/orphan"),
        ("add", "out/orphan"),
        ("add", "scratch/orphan"),
        ("add", "generated/orphan"),
        ("add", "generated/work/orphan"),
        ("add", "host/orphan"),
        ("add", "host/control/orphan"),
        ("add", "validation/orphan"),
        ("add", "run/orphan"),
        ("remove", "scratch"),
        ("remove", "generated"),
        ("remove", "generated/work"),
        ("remove", "generated/work/pkg"),
    ],
)
def test_result_structure_directories_are_exact(case, monkeypatch, operation, relative):
    def output():
        complete_output(case)
        (case.root / "work/pkg/.venv/nested").mkdir(parents=True)

    fake_spawn(case, monkeypatch, output)
    original_collect = task_workspace.collect_task

    def collect(**kwargs):
        result = original_collect(**kwargs)
        target = Path(case.sheet["result_root"]) / relative
        if operation == "add":
            target.mkdir(parents=True)
        else:
            target.rename(case.base / "retained-b-directory")
        return result

    monkeypatch.setattr(task_workspace, "collect_task", collect)
    observed = invoke(case)
    assert observed["status"] == "Failed" and observed["launch_count"] == 1
    assert observed["collection_sha256"] is None and observed["run_receipt_sha256"] is None
    assert observed == observations(case) and len(case.calls) == 1


def test_generic_build_empty_directory_remains_authored(case, monkeypatch):
    def output():
        complete_output(case)
        (case.root / "work/build/empty").mkdir(parents=True)

    fake_spawn(case, monkeypatch, output)
    observed = invoke(case)
    result_root = Path(case.sheet["result_root"])
    assert observed["status"] == "ObservationRecorded"
    assert (result_root / "candidate/build/empty").is_dir()
    assert not (result_root / "generated").exists()


def test_directory_failure_keeps_original_interrupt_and_launch(case, monkeypatch):
    original = KeyboardInterrupt("original synthetic interrupt")
    fake_spawn(case, monkeypatch, lambda: complete_output(case))
    original_execute = task_run._execute_once
    original_collect = task_workspace.collect_task

    def execute(*args, **kwargs):
        original_execute(*args, **kwargs)
        raise original

    def collect(**kwargs):
        result = original_collect(**kwargs)
        (case.root / "out/after-interrupt").mkdir()
        return result

    monkeypatch.setattr(task_run, "_execute_once", execute)
    monkeypatch.setattr(task_workspace, "collect_task", collect)
    with pytest.raises(KeyboardInterrupt) as caught:
        invoke(case)
    observed = observations(case)
    assert caught.value is original and observed["status"] == "Interrupted"
    assert observed["launch_count"] == 1 and len(case.calls) == 1
    assert observed["collection_sha256"] is None and observed["run_receipt_sha256"] is None
    assert (case.base / "fixture-permit.consumed.json").exists()


@pytest.mark.parametrize("fault", ["limit", "identity"])
def test_saved_run_uses_bounded_stable_descriptor_read(case, monkeypatch, fault):
    fake_spawn(case, monkeypatch, lambda: complete_output(case))
    target = Path(case.sheet["run_root"]) / "run.json"
    if fault == "limit":
        original_reader = task_run.read_host_input_bytes

        def reader(*, path):
            if Path(path) == target:
                with monkeypatch.context() as patches:
                    patches.setattr(task_run, "_JSON_LIMIT", target.stat().st_size - 1)
                    return original_reader(path=path)
            return original_reader(path=path)

        monkeypatch.setattr(task_run, "read_host_input_bytes", reader)
    else:
        original_stat = Path.stat
        observations = 0

        def stat_file(path, *args, **kwargs):
            nonlocal observations
            observed = original_stat(path, *args, **kwargs)
            if path == target and kwargs.get("follow_symlinks", True):
                observations += 1
                if observations == 2:
                    # The real descriptor stays open. Inject only the final path identity
                    # observation, since this Windows file handle denies actual rename.
                    changed = SimpleNamespace(
                        **{
                            key: getattr(observed, key)
                            for key in (
                                "st_dev",
                                "st_ino",
                                "st_size",
                                "st_mtime_ns",
                                "st_nlink",
                                "st_mode",
                                "st_file_attributes",
                                "st_ctime_ns",
                            )
                        }
                    )
                    changed.st_ino += 1
                    return changed
            return observed

        monkeypatch.setattr(Path, "stat", stat_file)
    result = invoke(case)
    assert result["status"] == "Failed" and result["launch_count"] == 1
    assert result["run_receipt_sha256"] is None and len(case.calls) == 1
    assert result["error_code"] == ("ResourceLimitExceeded" if fault == "limit" else "InputChanged")


@pytest.mark.parametrize("fault", ["missing_run", "local_evidence", "collection"])
def test_saved_evidence_cleanup_never_replaces_original_interrupt(case, monkeypatch, fault):
    interrupt = KeyboardInterrupt("original private interrupt")
    fake_spawn(case, monkeypatch, wait_error=interrupt)
    original_execute = task_run._execute_once

    def execute(*args, **kwargs):
        try:
            return original_execute(*args, **kwargs)
        finally:
            root = Path(case.sheet["run_root"])
            name = "run.json" if fault == "missing_run" else "launch.json"
            if fault != "collection":
                (root / name).rename(root / (name + ".retained-original"))

    monkeypatch.setattr(task_run, "_execute_once", execute)
    if fault == "collection":

        def fail(**kwargs):
            raise OSError("secondary collection detail")

        monkeypatch.setattr(task_workspace, "collect_task", fail)
    with pytest.raises(KeyboardInterrupt) as caught:
        invoke(case)
    assert caught.value is interrupt and len(case.calls) == 1
    observed = observations(case)
    assert observed["status"] == "Interrupted"
    assert observed["launch_count"] == 1


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
    assert result["contract_version"] == case.sheet["contract_version"]
    if result["contract_version"] == 2:
        assert result["host_composition"] == task_run.FIRST_OBSERVATION_COMPOSITION
        assert result["expected_worker_shell"] == {"status": "Unknown", "identity": None}
        assert result["actual_worker_shell"] == {"status": "Unknown", "identity": None}
        assert result["command_evidence_status"] == "Unverified"
        assert result["acceptance_requirements"] == [
            "ActualWorkerShellIdentity",
            "RecipeCommandCompletionEvidence",
        ]
    else:
        assert "host_composition" not in result and "actual_worker_shell" not in result
    assert process.closed and result == observations(case)
    assert len(case.identity_checks) >= 4 and os.environ.get("LOCALAPPDATA") == original_appdata
    assert all((case.root / "control" / name).read_bytes() == raw for name, raw in controls.items())
    run = task_run._read(Path(case.sheet["run_root"]) / "run.json")
    assert run["blockers"] == validation._expected_blockers(case.sheet)
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


def bind_environment(case, value):
    path = Path(case.sheet["environment"]["path"])
    retain_and_write(path, task_run._canonical(value))
    case.sheet["environment"] = identity(path)
    case.profile["enforcement"]["evidence_refs"] = [
        {"ref": str(path), "sha256": identity(path)["sha256"], "origin": "HostObserved"}
    ]
    freeze(case)


@pytest.mark.parametrize("case", [2], indirect=True)
@pytest.mark.parametrize("fault", ["none", "missing", "changed", "hardlink"])
def test_first_observation_known_expected_shell_is_a_real_file(case, monkeypatch, fault):
    path = case.base / "worker-shell.exe"
    shell_identity = identity(path)
    environment = task_run._read(Path(case.sheet["environment"]["path"]))
    environment["worker_shell"] = {"status": "Known", "identity": shell_identity}
    bind_environment(case, environment)
    if fault == "missing":
        path.rename(case.base / "retained-shell.exe")
    elif fault == "changed":
        retain_and_write(path, b"changed expected shell")
    elif fault == "hardlink":
        os.link(path, case.base / "shell-link.exe")
    fake_spawn(case, monkeypatch, lambda: complete_output(case))
    if fault == "none":
        result = invoke(case)
        assert result["status"] == "ObservationRecorded"
        assert result["expected_worker_shell"] == environment["worker_shell"]
        assert result["actual_worker_shell"] == {"status": "Unknown", "identity": None}
        assert result["runtime_acceptance"] == "Unverified"
    else:
        with pytest.raises((task_run.TaskRunError, OSError)):
            invoke(case)
        assert not case.calls and not list(case.base.glob("*.consumed.json"))


@pytest.mark.parametrize("case", [2], indirect=True)
@pytest.mark.parametrize(
    "fault",
    [
        "env_version",
        "permit_version",
        "receipt_version",
        "bool_env_version",
        "bool_permit_version",
        "future_permit",
        "missing_scope",
        "ordinary_scope",
        "extra_env",
        "null_shell",
        "bare_identity",
        "wrong_state",
        "unknown_identity",
        "known_null",
        "extra_shell",
        "worker_reported",
        "receipt_composition",
        "accepted_receipt",
    ],
)
def test_first_observation_versions_scope_and_unknown_shape_are_closed(case, fault):
    environment = task_run._read(Path(case.sheet["environment"]["path"]))
    if fault == "env_version":
        environment["contract_version"] = 1
    elif fault == "permit_version":
        case.sheet["contract_version"] = 1
    elif fault == "receipt_version":
        case.receipt["contract_version"] = 1
        case.receipt.pop("host_composition")
        case.receipt["host_identity_files"] = [identity(case.base / "worker-shell.exe")]
    elif fault == "bool_env_version":
        environment["contract_version"] = True
    elif fault == "bool_permit_version":
        case.sheet["contract_version"] = True
    elif fault == "future_permit":
        case.sheet["contract_version"] = 3
    elif fault == "missing_scope":
        environment.pop("scope")
    elif fault == "ordinary_scope":
        environment["scope"] = "OrdinaryRun"
    elif fault == "extra_env":
        environment["select_shell"] = "forbidden"
    elif fault == "null_shell":
        environment["worker_shell"] = None
    elif fault == "bare_identity":
        environment["worker_shell"] = identity(case.base / "worker-shell.exe")
    elif fault == "wrong_state":
        environment["worker_shell"]["status"] = "Accepted"
    elif fault == "unknown_identity":
        environment["worker_shell"]["identity"] = identity(case.base / "worker-shell.exe")
    elif fault == "known_null":
        environment["worker_shell"]["status"] = "Known"
    elif fault == "extra_shell":
        environment["worker_shell"]["argv"] = []
    elif fault == "receipt_composition":
        case.receipt["host_composition"]["status"] = "Known"
    elif fault == "accepted_receipt":
        case.accepted = True
    with pytest.raises((validation.ValidationError, task_run.TaskRunError)):
        bind_environment(case, environment)
        if fault == "worker_reported":
            case.profile["enforcement"]["evidence_refs"][0]["origin"] = "WorkerReported"
            freeze(case)
        invoke(case)
    assert not case.calls and not list(case.base.glob("*.consumed.json"))


@pytest.mark.parametrize("case", [1], indirect=True)
@pytest.mark.parametrize("shell", [None, "Unknown", {"status": "Unknown", "identity": None}])
def test_legacy_environment_cannot_silently_gain_unknown(case, shell):
    environment = task_run._read(Path(case.sheet["environment"]["path"]))
    environment["worker_shell"] = shell
    bind_environment(case, environment)
    with pytest.raises(task_run.TaskRunError):
        invoke(case)
    assert not list(case.base.glob("*.consumed.json")) and not case.calls


@pytest.mark.parametrize("case", [2], indirect=True)
@pytest.mark.parametrize("subject", ["environment", "receipt", "known_shell"])
def test_observation_identity_drift_during_capture_prevents_launch(case, monkeypatch, subject):
    if subject == "known_shell":
        environment = task_run._read(Path(case.sheet["environment"]["path"]))
        environment["worker_shell"] = {
            "status": "Known",
            "identity": identity(case.base / "worker-shell.exe"),
        }
        bind_environment(case, environment)
    original = case.store.start

    def drift():
        writer = original()
        path = {
            "environment": Path(case.sheet["environment"]["path"]),
            "receipt": case.trust / "deployment-receipt.json",
            "known_shell": case.base / "worker-shell.exe",
        }[subject]
        retain_and_write(path, path.read_bytes() + b" ")
        return writer

    monkeypatch.setattr(case.store, "start", drift)
    fake_spawn(case, monkeypatch)
    result = invoke(case)
    assert result["status"] == "Failed" and result["launch_count"] == 0 and not case.calls
    assert result["runtime_acceptance"] == "Unverified"
    assert (case.base / "fixture-permit.consumed.json").exists()
