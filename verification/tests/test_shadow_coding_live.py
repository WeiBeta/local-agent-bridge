"""Frozen task integration with real collector and synthetic CLI/key/config only."""

from __future__ import annotations

import copy
import io
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "verification"))
sys.path.insert(0, str(ROOT / "tests"))
import shadow_coding_live as live  # noqa: E402
import test_task_run as fixture  # noqa: E402

from local_agent_bridge.bridge import layered_acceptance, task_run  # noqa: E402
from local_agent_bridge.capture.session import SessionStore  # noqa: E402

SELECT = Path("C:/Users/user/Documents/Codex-Archive/2026-10-10-LAB-SHADOW-CODING-SELECT-01")


def selected_files():
    return {
        "tool.py": (SELECT / "worker-input/tool.py").read_bytes(),
        **{
            "recipe/" + name: (SELECT / "worker-input/recipe" / name).read_bytes()
            for name in ("run_tests.py", "public_tests.py")
        },
        "recipe/shadow_worker_tests.py": (
            ROOT / "verification/shadow_worker_tests.py"
        ).read_bytes(),
    }


def freeze(case):
    fixture.sync(case, refresh_r=True)
    for filename in ("plan.json", "deployment-receipt.json"):
        target = case.root / "control" / filename
        if target.exists():
            target.rename(
                case.base
                / (
                    filename
                    + ".retained-"
                    + str(len(list(case.base.glob(filename + ".retained-*"))))
                )
            )
    case.frozen_plan = fixture.plan(case)
    case.sheet.update(
        task_manifest_sha256=fixture.digest(case.task),
        plan_sha256=fixture.digest(case.frozen_plan),
        trusted_inputs_sha256=case.expected,
        receipt_binding_sha256=layered_acceptance.receipt_binding(case.receipt),
    )
    fixture.write_json(case.sheet_path, case.sheet)
    case.sheet_sha = fixture.identity(case.sheet_path)["sha256"]


@pytest.fixture
def case(tmp_path, monkeypatch):
    value = fixture.prepare(
        tmp_path, monkeypatch, accepted=False, actual_b=True, files=selected_files()
    )
    value.base = tmp_path
    value.receipt.update(
        contract_version=3,
        host_identity_files=[],
        host_composition=layered_acceptance.COMPOSITION.copy(),
        acceptance_method=layered_acceptance.METHOD,
        layered_acceptances=[],
    )
    value.profile.update(
        roles=["Coding"],
        supported_capabilities=live.CAPABILITIES.copy(),
        execution_modes=["declared_scope"],
    )
    value.task.update(
        deadline_seconds=live.BUDGET["deadline_seconds"],
        protected_paths=sorted([*value.task["protected_paths"], "work/recipe"]),
    )
    value.receipt["toolchains"][0]["recipe_refs"] = [live.RECIPE_REF]
    value.recipe_root = tmp_path / "acceptance"
    value.recipe_root.mkdir()
    for name in live.retests.RECIPE_HASHES:
        shutil.copyfile(SELECT / "scripts" / name, value.recipe_root / name)
    environment_path = tmp_path / "environment.json"
    value.appdata = tmp_path / "isolated-appdata"
    fixture.write_json(
        environment_path,
        {
            "contract_version": 3,
            "kind": "TaskRuntimeValidationEnvironment",
            "local_appdata": str(value.appdata),
            "worker_shell": {"status": "Unknown", "identity": None},
            "scope": "LayeredFirstExecution",
        },
    )
    value.store = SessionStore(fixture.KEY, root=value.appdata / "LocalAgentBridge/sessions")
    value.profile["enforcement"]["evidence_refs"] = [
        {
            "ref": str(environment_path),
            "sha256": fixture.identity(environment_path)["sha256"],
            "origin": "HostObserved",
        }
    ]
    wheel = tmp_path / "fixture.whl"
    wheel.write_bytes(b"synthetic wheel never installed")
    value.receipt["bridge"]["wheel_sha256"] = fixture.identity(wheel)["sha256"]
    value.contract_path = tmp_path / "shadow-contract.json"
    value.contract = {
        "contract_version": 1,
        "kind": "ShadowCodingContract",
        "task_id": value.task["task_id"],
        "input_files": [
            {"path": name, "bytes": len(raw), "sha256": task_run._digest(raw)}
            for name, raw in selected_files().items()
        ],
        "acceptance_recipe": str(value.recipe_root),
        "verifiers": [
            fixture.identity(ROOT / "verification" / name) for name in sorted(live.VERIFIERS)
        ],
        "budget": live.BUDGET.copy(),
    }
    fixture.write_json(value.contract_path, value.contract)
    value.sheet_path = tmp_path / "permit.json"
    value.sheet = {
        "contract_version": 3,
        "kind": "TaskRuntimeValidationPermit",
        "permit_id": "shadow-fixture",
        "task_id": value.task["task_id"],
        "management_task_id": live.MANAGEMENT_TASK,
        "approval": {"status": "Approved", "author_confirmed": True},
        "grant_ref": value.auth["grant_ref"],
        "budget_ref": {
            "ref": str(value.contract_path),
            "sha256": fixture.identity(value.contract_path)["sha256"],
            "origin": "HostObserved",
        },
        "max_host_launches": 1,
        "host": "agy",
        "role": "Coding",
        "capabilities": live.CAPABILITIES.copy(),
        "execution_boundary": "declared_scope",
        "task_root": str(value.root),
        "trusted_control_root": str(value.trust),
        "run_root": str(tmp_path / "live-run"),
        "result_root": str(tmp_path / "live-result"),
        "deadline_seconds": live.BUDGET["deadline_seconds"],
        "validator": fixture.identity(ROOT / "verification/shadow_coding_live.py"),
        "installation": {
            "root": str(value.host_entry.parent),
            "python": value.receipt["toolchains"][0]["identity_files"][0],
            "wheel": fixture.identity(wheel),
        },
        "environment": fixture.identity(environment_path),
        "recipes": [
            {
                "ref": live.RECIPE_REF,
                "identity": fixture.identity(value.root / "work/recipe/run_tests.py"),
            }
        ],
        "permissions": dict.fromkeys(live.PERMISSIONS | {"management_local_retest"}, True),
        "acceptance_method": layered_acceptance.METHOD,
        "waived_blockers": [task_run.FIRST_LAYERED_BLOCKER],
        "manager_retest": {
            "root": str(tmp_path / "manager-retest"),
            "timeout_seconds": 10,
            "baseline_tests": 8,
            "candidate_tests": 8,
        },
    }
    value.manager_calls = []
    value.key_reads = []

    def installation(sheet, receipt):
        for identity in (sheet["installation"]["python"], sheet["installation"]["wheel"]):
            task_run._verify_file_identity(identity)
        assert sheet["installation"]["wheel"]["sha256"] == receipt["bridge"]["wheel_sha256"]
        task_run._verify_runtime_identity(receipt)

    monkeypatch.setattr(live, "_verify_installation", installation)
    monkeypatch.setattr(task_run, "_configuration_lease", lambda _: live.contextlib.nullcontext())
    monkeypatch.setattr(live, "load_key", lambda: value.key_reads.append("reader") or fixture.KEY)
    original_close = fixture.FakeProcess.close_job
    monkeypatch.setattr(fixture.FakeProcess, "close_job", lambda p: original_close(p) or True)
    freeze(value)
    return value


def invoke(case):
    return live.validate_once(sheet_path=case.sheet_path, expected_sha256=case.sheet_sha)


def saved(case):
    path = Path(case.sheet["run_root"]) / "shadow-validation.json"
    return live.read_saved(
        sheet_path=case.sheet_path,
        expected_sha256=case.sheet_sha,
        observation_sha256=fixture.identity(path)["sha256"],
    )


def events(case):
    future = case.base / "future"
    shutil.copytree(case.root / "work", future / "candidate")
    shutil.copyfile(SELECT / "acceptance/reference/tool.py", future / "candidate/tool.py")
    for phase in ("reproduce", "regression"):
        target = future / "out/worker-tests" / phase / "report/tests.xml"
        target.parent.mkdir(parents=True)
        target.write_text(
            report_xml("baseline_public" if phase == "reproduce" else "candidate_public"),
            encoding="utf-8",
        )
    roots = {"task_root": case.root, "result_root": future}
    context = {
        "task": case.task,
        "bundle": {"deployment_receipt": case.receipt},
        "shadow_wrapper_sha256": fixture.identity(case.root / "work/recipe/shadow_worker_tests.py")[
            "sha256"
        ],
    }
    files, dirs = live.retests._inventory(future / "candidate", live.retests.MAX_BYTES)
    commands, summaries = live.expectations(
        context,
        roots,
        {"continuation": {"candidate_tree_sha256": live.task_workspace._tree_sha(files, dirs)}},
    )
    conversation = "native-fixture"
    stream = [{"event": "init", "conversation_id": conversation, "init": {}}]
    for index, phase in enumerate(("reproduce", "regression")):
        value = {
            **summaries[phase],
            "start_utc": f"2026-10-11T00:00:0{index * 2}+00:00",
            "end_utc": f"2026-10-11T00:00:0{index * 2 + 1}+00:00",
        }
        fixture.write_json(future / "out/worker-tests" / phase / "summary.json", value)
        stream.append(
            {
                "event": "step_update",
                "step_update": {
                    "conversation_id": conversation,
                    "step_index": index,
                    "state": "DONE",
                    "step_type": "tool",
                    "tool_name": "run_command",
                    "tool_info": {
                        "name": "run_command",
                        "parameters": {"CommandLine": commands[phase]},
                        "output": live.wrapper.PREFIX + json.dumps(value) + "\n",
                    },
                },
            }
        )
    stream.append(
        {
            "event": "result",
            "result": {
                "conversation_id": conversation,
                "status": "SUCCESS",
                "response": "not evidence",
            },
        }
    )
    return stream, commands, summaries


def fake_host(case, monkeypatch, stream=None, **kwargs):
    prepared, _, _ = events(case)
    if stream is None:
        stream = prepared

    def candidate():
        shutil.copyfile(SELECT / "acceptance/reference/tool.py", case.root / "work/tool.py")
        shutil.copytree(case.base / "future/out/worker-tests", case.root / "out/worker-tests")
        fixture.write_json(
            case.root / "out/progress.json",
            {
                "contract_version": 1,
                "task_id": case.task["task_id"],
                "status": "Completed",
                "summary": "synthetic reference feasibility only",
                "remaining_paths": [],
            },
        )

    process = fixture.fake_spawn(case, monkeypatch, candidate, **kwargs)
    process.stdout = io.BytesIO(b"".join(json.dumps(item).encode() + b"\n" for item in stream))
    return process


def report_xml(phase):
    names = sorted(
        live.retests.PRIVATE_CASES if phase == "candidate_private" else live.retests.PUBLIC_CASES
    )
    children = "".join(
        '<testcase name="'
        + name
        + '">'
        + (
            "<error/>"
            if phase == "baseline_public" and name in live.wrapper.BASELINE_ERRORS
            else ""
        )
        + "</testcase>"
        for name in names
    )
    errors = 4 if phase == "baseline_public" else 0
    return (
        f'<testsuite tests="{len(names)}" failures="0" errors="{errors}" skipped="0">'
        f"{children}</testsuite>"
    )


def manager(case, monkeypatch, callback=None):
    def run(argv, **kwargs):
        phase = Path(kwargs["cwd"]).name
        case.manager_calls.append(phase)
        assert kwargs["shell"] is False and kwargs["timeout"] == 10
        target = Path(kwargs["cwd"]) / "out"
        target.mkdir()
        (target / "tests.xml").write_text(report_xml(phase), encoding="utf-8")
        if callback:
            callback(phase)
        return SimpleNamespace(returncode=1 if phase == "baseline_public" else 0)

    monkeypatch.setattr(live.retests.subprocess, "run", run)


@pytest.mark.parametrize("seconds", [300, 1020, 3600])
def test_initial_saved_one_use_real_collector_and_source_binding(case, monkeypatch, seconds):
    case.task["deadline_seconds"] = case.sheet["deadline_seconds"] = seconds
    case.contract["budget"]["deadline_seconds"] = seconds
    fixture.write_json(case.contract_path, case.contract)
    case.sheet["budget_ref"]["sha256"] = fixture.identity(case.contract_path)["sha256"]
    freeze(case)
    before = case.settings.read_bytes()
    previous = os.environ.get("LOCALAPPDATA")
    fake_host(case, monkeypatch)
    manager(case, monkeypatch)
    result = invoke(case)
    assert result["status"] == "EvidenceReadyForManagement", result
    assert result["worker_execution"] == "Unknown" and result["accepted"] is False
    assert (
        len(case.calls) == 1
        and case.manager_calls == list(live.retests.PHASES)
        and case.key_reads == ["reader"]
    )
    assert result["worker_evidence"]["value"]["origin"] == "CliToolResult"
    assert saved(case) == result
    assert len(case.calls) == 1 and case.key_reads == ["reader"]
    assert case.settings.read_bytes() == before and os.environ.get("LOCALAPPDATA") == previous
    with pytest.raises(live.lifecycle.ValidationError):
        invoke(case)
    assert len(case.calls) == 1


@pytest.mark.parametrize(
    "problem",
    ["private", "budget", "manifest", "verifier", "approval", "old_counts", "non_r_blocker"],
)
def test_preflight_failures_have_no_consumption_launch_or_reader(case, monkeypatch, problem):
    if problem == "private":
        case.contract["acceptance_recipe"] = str(case.root / "work/recipe")
    elif problem == "budget":
        case.contract["budget"]["reader_key_reads"] = 2
    elif problem == "manifest":
        case.contract["input_files"][0]["sha256"] = "f" * 64
    elif problem == "verifier":
        case.contract["verifiers"][0]["sha256"] = "f" * 64
    elif problem == "approval":
        case.sheet["approval"] = {"status": "Proposed", "author_confirmed": False}
    elif problem == "old_counts":
        case.sheet["manager_retest"].update(baseline_tests=1, candidate_tests=6)
    else:
        case.receipt["toolchains"][0]["recipe_refs"] = []
    fixture.write_json(case.contract_path, case.contract)
    case.sheet["budget_ref"]["sha256"] = fixture.identity(case.contract_path)["sha256"]
    freeze(case)
    with pytest.raises(
        (live.lifecycle.ValidationError, live.retests.RetestError, task_run.TaskRunError)
    ):
        invoke(case)
    assert (
        not case.calls
        and not case.key_reads
        and not (case.base / "shadow-fixture.consumed.json").exists()
    )


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(37), OSError("synthetic")])
def test_interrupt_and_manager_failure_stop_and_preserve_original(case, monkeypatch, error):
    fake_host(case, monkeypatch)

    def fail(_phase):
        raise error

    manager(case, monkeypatch, fail)
    if isinstance(error, Exception):
        result = invoke(case)
        assert result["status"] == "Stopped"
    else:
        with pytest.raises(type(error)) as caught:
            invoke(case)
        assert caught.value is error
    assert case.manager_calls == ["baseline_public"] and not case.key_reads
    assert (
        case.settings.read_bytes()
        == (Path(case.sheet["run_root"]) / "private/settings.original.bin").read_bytes()
    )
    assert (Path(case.sheet["manager_retest"]["root"]) / "baseline_public/failure.json").exists()


def test_native_gap_retains_unknown_and_never_second_reader(case, monkeypatch):
    fake_host(
        case,
        monkeypatch,
        [{"event": "result", "result": {"conversation_id": "wrong", "status": "SUCCESS"}}],
    )
    manager(case, monkeypatch)
    result = invoke(case)
    assert result["status"] == "Stopped" and result["error_code"] == "CliEvidenceUnknown"
    assert result["worker_evidence"]["value"]["status"] == "Unknown"
    assert saved(case) == result and case.key_reads == ["reader"]


def test_initial_wrong_collected_case_outcomes_stop_before_reader(case, monkeypatch):
    fake_host(case, monkeypatch)
    manager(case, monkeypatch)
    original_expectations = live.expectations

    def wrong_xml(context, roots, collection):
        path = roots["result_root"] / "out/worker-tests/reproduce/report/tests.xml"
        _swap_error_names(path)
        return original_expectations(context, roots, collection)

    monkeypatch.setattr(live, "expectations", wrong_xml)
    result = invoke(case)
    assert result["status"] == "Stopped" and result["error_code"] == "WorkerCaseOutcomesChanged"
    assert len(case.calls) == 1 and not case.key_reads


@pytest.mark.parametrize("seconds", [1, 300, 1020, 3600, 0, -1, 3601, True, 3600.0, "3600", None])
def test_shadow_permit_work_deadline_boundaries(case, seconds):
    case.sheet["deadline_seconds"] = seconds
    fixture.write_json(case.sheet_path, case.sheet)
    case.sheet_sha = fixture.identity(case.sheet_path)["sha256"]
    if type(seconds) is int and 1 <= seconds <= 3600:
        assert live._sheet(case.sheet_path, case.sheet_sha)["deadline_seconds"] == seconds
    else:
        with pytest.raises(live.lifecycle.ValidationError, match="BudgetUnverified"):
            live._sheet(case.sheet_path, case.sheet_sha)
    assert not case.calls and not case.key_reads and not Path(case.sheet["run_root"]).exists()


@pytest.mark.parametrize("mismatch", ["task", "budget", "budget_type"])
def test_shadow_extended_deadline_preserves_exact_bindings(case, mismatch):
    if mismatch == "task":
        case.task["deadline_seconds"] = 300
    else:
        case.contract["budget"]["deadline_seconds"] = True if mismatch == "budget_type" else 300
        fixture.write_json(case.contract_path, case.contract)
        case.sheet["budget_ref"]["sha256"] = fixture.identity(case.contract_path)["sha256"]
    freeze(case)
    with pytest.raises(
        live.lifecycle.ValidationError, match=r"PermitBindingMismatch|BudgetUnverified"
    ):
        invoke(case)
    assert not case.calls and not case.key_reads and not Path(case.sheet["run_root"]).exists()
    assert not list(case.base.glob("*.consumed.json"))


def _swap_error_names(path):
    import xml.etree.ElementTree as ET

    suite = ET.fromstring(path.read_bytes())
    for node in suite:
        for child in list(node):
            node.remove(child)
    for node in list(suite)[:4]:
        ET.SubElement(node, "error")
    assert {node.get("name") for node in suite if len(node)} != live.wrapper.BASELINE_ERRORS
    path.write_bytes(ET.tostring(suite))


@pytest.mark.parametrize("what", ["worker_xml", "worker_summary", "manager_xml"])
def test_saved_checks_case_outcomes_even_after_inventory_seam(case, monkeypatch, what):
    fake_host(case, monkeypatch)
    manager(case, monkeypatch)
    result = invoke(case)
    assert result["status"] == "EvidenceReadyForManagement"
    observation = Path(case.sheet["run_root"]) / "shadow-validation.json"
    original = observation.read_bytes()
    if what == "worker_xml":
        path = Path(case.sheet["result_root"]) / "out/worker-tests/reproduce/report/tests.xml"
        _swap_error_names(path)
    elif what == "worker_summary":
        path = Path(case.sheet["result_root"]) / "out/worker-tests/reproduce/summary.json"
        value = json.loads(path.read_bytes())
        outcomes = value["case_outcomes"]
        error_name = sorted(live.wrapper.BASELINE_ERRORS)[0]
        pass_name = sorted(set(live.wrapper.CASES) - live.wrapper.BASELINE_ERRORS)[0]
        outcomes[error_name], outcomes[pass_name] = "pass", "error"
        fixture.write_json(path, value)
    else:
        path = Path(case.sheet["manager_retest"]["root"]) / "baseline_public/out/tests.xml"
        _swap_error_names(path)
        # Only bypass the earlier retained-file hash gate to exercise named states.
        monkeypatch.setattr(live.retests, "read_manager_evidence", lambda **_: None)
    monkeypatch.setattr(live.lifecycle, "_saved_collection", lambda *_: result["collection_sha256"])
    with pytest.raises((live.lifecycle.ValidationError, live.native.bounded.Refused)):
        saved(case)
    assert len(case.calls) == 1 and case.key_reads == ["reader"]
    assert case.manager_calls == list(live.retests.PHASES) and observation.read_bytes() == original


def test_saved_mutation_needs_external_observation_pin(case, monkeypatch):
    fake_host(case, monkeypatch)
    manager(case, monkeypatch)
    result = invoke(case)
    path = Path(case.sheet["run_root"]) / "shadow-validation.json"
    pin = fixture.identity(path)["sha256"]
    changed = copy.deepcopy(result)
    changed["worker_execution"] = "Pass"
    fixture.write_json(path, changed)
    with pytest.raises(live.lifecycle.ValidationError):
        live.read_saved(
            sheet_path=case.sheet_path, expected_sha256=case.sheet_sha, observation_sha256=pin
        )
    assert len(case.calls) == 1 and case.key_reads == ["reader"]


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(51), OSError("synthetic wait")])
def test_host_interrupt_or_failure_restores_and_never_runs_manager(case, monkeypatch, error):
    before = case.settings.read_bytes()
    fake_host(case, monkeypatch, wait_error=error)
    if isinstance(error, Exception):
        result = invoke(case)
        assert result["status"] == "Stopped" and result["launch_count"] == 1
    else:
        with pytest.raises(type(error)) as caught:
            invoke(case)
        assert caught.value is error
        observed = task_run._read(Path(case.sheet["run_root"]) / "shadow-validation.json")
        assert observed["launch_count"] == 1
    assert not case.manager_calls and not case.key_reads and case.settings.read_bytes() == before


@pytest.mark.parametrize("count", [0, None], ids=["not-attempted", "unknown"])
def test_zero_and_unknown_launch_are_retained_without_followup(case, monkeypatch, count):
    def execute(context, plan, root, recheck, started, *, first_execution):
        value = task_run._receipt(plan)
        value.update(launch_count=count, transport_state="NotRun" if count == 0 else "Failed")
        value["blockers"] = [] if count == 0 else ["LaunchUnverified"]
        launch = {
            "spawn_state": "not_attempted" if count == 0 else "unknown",
            "launch_count": count,
        }
        task_run._persist(root / "launch.json", launch)
        value["evidence_refs"] = [
            {
                "ref": "first-execution.json",
                "sha256": first_execution["sha256"],
                "origin": "HostObserved",
            },
            {"ref": "launch.json", "sha256": fixture.digest(launch), "origin": "HostObserved"},
        ]
        task_run._persist(root / "run.json", value)
        return value

    monkeypatch.setattr(task_run, "_execute_once", execute)
    result = invoke(case)
    assert result["status"] == "Stopped" and result["launch_count"] is count
    assert not case.calls and not case.key_reads and not case.manager_calls
    assert (case.base / "shadow-fixture.consumed.json").exists()


def test_primary_interrupt_survives_observation_and_env_restore_failure(case, monkeypatch):
    original = KeyboardInterrupt()
    previous = os.environ.get("LOCALAPPDATA")
    fake_host(case, monkeypatch)

    def fail(_phase):
        raise original

    manager(case, monkeypatch, fail)
    real_persist = task_run._persist

    def persist(path, value):
        if path.name == "shadow-validation.json":
            raise OSError("synthetic diagnostic failure")
        real_persist(path, value)

    monkeypatch.setattr(task_run, "_persist", persist)

    class Environment(dict):
        def __setitem__(self, name, value):
            if name == "LOCALAPPDATA" and value == previous:
                raise SystemExit(73)
            super().__setitem__(name, value)

        def pop(self, name, *args):
            if name == "LOCALAPPDATA" and previous is None:
                raise SystemExit(73)
            return super().pop(name, *args)

    monkeypatch.setattr(live.os, "environ", Environment(os.environ))
    with pytest.raises(KeyboardInterrupt) as caught:
        invoke(case)
    assert caught.value is original and not case.key_reads
    assert task_run._read(Path(case.sheet["run_root"]) / "environment-restore-failure.json") == {
        "exception_type": "SystemExit"
    }


def test_normal_env_restore_failure_is_saved_stopped(case, monkeypatch):
    fake_host(case, monkeypatch)
    manager(case, monkeypatch)
    previous = os.environ.get("LOCALAPPDATA")

    class Environment(dict):
        def __setitem__(self, name, value):
            if name == "LOCALAPPDATA" and value == previous:
                raise OSError("synthetic restore failure")
            super().__setitem__(name, value)

        def pop(self, name, *args):
            if name == "LOCALAPPDATA" and previous is None:
                raise OSError("synthetic restore failure")
            return super().pop(name, *args)

    monkeypatch.setattr(live.os, "environ", Environment(os.environ))
    result = invoke(case)
    assert result["status"] == "Stopped" and result["launch_count"] == 1
    assert task_run._read(Path(case.sheet["run_root"]) / "shadow-validation.json") == result
    assert result["worker_evidence"]["value"]["status"] == "CliPublicTestsMatch"
    assert saved(case) == result and case.key_reads == ["reader"]
