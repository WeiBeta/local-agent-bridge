"""Task-specific synthetic retests; no real CLI, provider, keys or host IO."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_agent_bridge.bridge import task_run, task_workspace

SCRIPT = Path(__file__).resolve().parents[2] / "verification/shadow_coding_r.py"
spec = importlib.util.spec_from_file_location("shadow_coding_r", SCRIPT)
retests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retests)


def identity(path):
    return {"path": str(path), "sha256": task_run._digest(path.read_bytes())}


def write_json(path, value):
    path.write_bytes(task_run._canonical(value))


@pytest.fixture
def case(tmp_path, monkeypatch):
    recipe = tmp_path / "acceptance-recipe"
    recipe.mkdir()
    hashes = {}
    for name in retests.RECIPE_HASHES:
        path = recipe / name
        path.write_bytes(("# synthetic protected " + name + "\n").encode())
        hashes[name] = identity(path)["sha256"]
    monkeypatch.setattr(retests, "RECIPE_HASHES", hashes)
    baseline = tmp_path / "task/control/snapshot/source"
    baseline.mkdir(parents=True)
    (baseline / "tool.py").write_bytes(b"broken = True\n")
    (baseline / "recipe").mkdir()
    for name in ("run_tests.py", "public_tests.py"):
        shutil.copyfile(recipe / name, baseline / "recipe" / name)
    monkeypatch.setattr(retests, "BASELINE_TOOL_SHA256", identity(baseline / "tool.py")["sha256"])
    candidate = tmp_path / "result/candidate"
    shutil.copytree(baseline, candidate)
    (candidate / "tool.py").write_bytes(b"fixed = True\n")
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic interpreter identity, never launched")
    context = {
        "task": {"task_id": "shadow-fixture", "source_output_bytes_limit": 1024 * 1024},
        "bundle": {
            "deployment_receipt": {
                "toolchains": [
                    {
                        "recipe_refs": [retests.RECIPE_REF],
                        "identity_files": [identity(executable)],
                    }
                ]
            }
        },
    }
    roots = {
        "task_root": tmp_path / "task",
        "result_root": tmp_path / "result",
        "manager_retest": tmp_path / "manager-tests",
    }
    files, directories = retests._inventory(candidate, 1024 * 1024)
    collection = {
        "task_id": "shadow-fixture",
        "continuation": {"candidate_tree_sha256": task_workspace._tree_sha(files, directories)},
    }
    value = SimpleNamespace(
        context=context,
        roots=roots,
        collection=collection,
        recipe_root=recipe,
        baseline=baseline,
        candidate=candidate,
        executable=executable,
        calls=[],
        fault=None,
    )

    def process(argv, **kwargs):
        phase = Path(kwargs["cwd"]).name
        assert phase in retests.PHASES
        assert kwargs["timeout"] == 10
        assert kwargs["shell"] is False and kwargs["check"] is False
        assert argv == [
            str(executable),
            "-I",
            "-B",
            str(Path(kwargs["cwd"]) / "acceptance/run_tests.py"),
            "--source",
            str(Path(kwargs["cwd"]) / "work"),
            "--out",
            str(Path(kwargs["cwd"]) / "out"),
            "--suite",
            "private" if phase == "candidate_private" else "public",
        ]
        value.calls.append(phase)
        stage = Path(kwargs["cwd"])
        (stage / "out").mkdir()
        names = sorted(
            retests.PRIVATE_CASES if phase == "candidate_private" else retests.PUBLIC_CASES
        )
        counts = retests._counts(phase)
        suite = ET.Element("testsuite", {**{k: str(v) for k, v in counts.items()}, "skipped": "0"})
        for i, name in enumerate(names):
            child = ET.SubElement(suite, "testcase", {"name": name})
            if i < counts["errors"]:
                ET.SubElement(child, "error").text = "retained baseline error"
        (stage / "out/tests.xml").write_bytes(ET.tostring(suite, encoding="utf-8"))
        kwargs["stdout"].write(b"synthetic console result\n")
        result = SimpleNamespace(returncode=1 if phase == "baseline_public" else 0)
        if value.fault is not None:
            value.fault(phase, stage, result)
        return result

    monkeypatch.setattr(retests.subprocess, "run", process)
    return value


def invoke(case):
    return retests.run_manager_retests(
        context=case.context,
        roots=case.roots,
        collection=case.collection,
        recipe_root=case.recipe_root,
    )


def reread(case, identities):
    return retests.read_manager_evidence(
        identities=identities,
        context=case.context,
        roots=case.roots,
        collection=case.collection,
        recipe_root=case.recipe_root,
    )


def test_three_natural_matrices_and_saved_reread_are_management_only(case):
    before = retests._inventory(case.baseline, 1024 * 1024)
    ids = invoke(case)
    assert case.calls == list(retests.PHASES)
    assert retests._inventory(case.baseline, 1024 * 1024) == before
    assert reread(case, ids) == {
        "status": "ManagementRetestsPass",
        "origin": "HostObserved",
        "actor": "ManagementIndependent",
        "worker_execution": "Unknown",
        "worker_shell_identity": "Unknown",
        "runtime_acceptance": "Unverified",
        "accepted": False,
    }
    for phase in retests.PHASES:
        command = task_run._read(Path(ids[phase]["command"]["path"]))
        assert command["actor"] == "ManagementIndependent"
        assert command["worker_shell_identity"] is None
        assert {key: command[key] for key in ("tests", "failures", "errors")} == retests._counts(
            phase
        )
        assert command["exit_code"] == (1 if phase == "baseline_public" else 0)
        stage = case.roots["manager_retest"] / phase
        assert not (stage / "work/recipe/private_tests.py").exists()
        assert (stage / "stderr.txt").exists()


@pytest.mark.parametrize("phase", retests.PHASES)
@pytest.mark.parametrize(
    "fault", ["exit", "boolean_exit", "count", "wrong_names", "duplicate", "skipped", "doctype"]
)
def test_initial_counts_exits_and_named_xml_must_match(case, phase, fault):
    def corrupt(current, stage, result):
        if current != phase:
            return
        xml = stage / "out/tests.xml"
        root = ET.fromstring(xml.read_bytes())
        if fault == "exit":
            result.returncode = 0 if phase == "baseline_public" else 1
        elif fault == "boolean_exit":
            result.returncode = bool(result.returncode)
        elif fault == "count":
            root.set("errors" if phase == "baseline_public" else "tests", "1")
        elif fault == "wrong_names":
            root[0].set("name", "wrong_suite.test_wrong")
        elif fault == "duplicate":
            root[0].set("name", root[1].get("name"))
        elif fault == "skipped":
            root.set("skipped", "1")
        elif fault == "doctype":
            xml.write_bytes(b'<!DOCTYPE testsuite [<!ENTITY x "test">]>' + xml.read_bytes())
            return
        xml.write_bytes(ET.tostring(root))

    case.fault = corrupt
    with pytest.raises(retests.RetestError):
        invoke(case)
    assert case.calls == list(retests.PHASES[: retests.PHASES.index(phase) + 1])
    assert (case.roots["manager_retest"] / phase / "failure.json").exists()
    assert (case.roots["manager_retest"] / phase / "out/tests.xml").exists()
    with pytest.raises(FileExistsError):
        invoke(case)


@pytest.mark.parametrize(
    "target", ["stage_source", "source", "stage_recipe", "recipe", "python", "collection"]
)
def test_initial_post_process_rechecks_inputs_and_preserves_failure(case, target):
    def corrupt(phase, stage, result):
        if phase != "baseline_public":
            return
        if target == "collection":
            case.collection["continuation"]["candidate_tree_sha256"] = "f" * 64
        else:
            path = {
                "stage_source": stage / "work/tool.py",
                "source": case.candidate / "tool.py",
                "stage_recipe": stage / "acceptance/private_tests.py",
                "recipe": case.recipe_root / "public_tests.py",
                "python": case.executable,
            }[target]
            path.write_bytes(b"changed after invocation")

    case.fault = corrupt
    with pytest.raises((retests.RetestError, task_run.TaskRunError)):
        invoke(case)
    assert case.calls == ["baseline_public"]
    assert (case.roots["manager_retest"] / "baseline_public/failure.json").exists()


@pytest.mark.parametrize(
    "fault", ["argv", "cwd", "actor", "tree", "recipe", "time", "counts", "exit", "task", "shell"]
)
def test_saved_rehashed_command_still_cannot_change_bindings(case, fault):
    ids = invoke(case)
    pinned = ids["candidate_private"]["command"]
    path = Path(pinned["path"])
    value = task_run._read(path)
    changes = {
        "argv": {"argv": [*value["argv"][:-1], "public"]},
        "cwd": {"cwd": str(case.recipe_root)},
        "actor": {"actor": "Worker"},
        "tree": {"source_tree_sha256": "f" * 64},
        "recipe": {"recipe_sha256": "f" * 64},
        "time": {"end_utc": "2000-01-01T00:00:00+00:00"},
        "counts": {"tests": 8},
        "exit": {"exit_code": 1},
        "task": {"task_id": "another-task"},
        "shell": {"worker_shell_identity": identity(case.executable)},
    }
    value.update(changes[fault])
    write_json(path, value)
    ids["candidate_private"]["command"] = identity(path)
    with pytest.raises(retests.RetestError):
        reread(case, ids)
    assert case.calls == list(retests.PHASES)


@pytest.mark.parametrize(
    "target",
    [
        "source",
        "stage_source",
        "recipe",
        "stage_recipe",
        "python",
        "binding",
        "report",
        "report_pin",
        "command",
        "command_path",
        "task",
        "collection",
    ],
)
def test_saved_rechecks_files_context_paths_and_raw_identities(case, target):
    ids = invoke(case)
    stage = case.roots["manager_retest"] / "candidate_public"
    if target in {
        "source",
        "stage_source",
        "recipe",
        "stage_recipe",
        "python",
        "binding",
        "command",
    }:
        path = {
            "source": case.candidate / "tool.py",
            "stage_source": stage / "work/tool.py",
            "recipe": case.recipe_root / "private_tests.py",
            "stage_recipe": stage / "acceptance/public_tests.py",
            "python": case.executable,
            "binding": Path(ids["binding"]["path"]),
            "command": stage / "command.json",
        }[target]
        path.write_bytes(b"retained mutated evidence")
    elif target == "report":
        xml = stage / "out/tests.xml"
        xml.write_bytes(xml.read_bytes() + b"\n")
        write_json(stage / "report-identity.json", identity(xml))
    elif target == "report_pin":
        write_json(stage / "report-identity.json", {"path": "wrong", "sha256": "f" * 64})
    elif target == "command_path":
        ids["candidate_public"]["command"] = copy.deepcopy(ids["candidate_private"]["command"])
    elif target == "task":
        case.context["task"]["extra"] = "changed contract"
    elif target == "collection":
        case.collection["extra"] = "changed collection"
    with pytest.raises((retests.RetestError, task_run.TaskRunError)):
        reread(case, ids)


@pytest.mark.parametrize(
    "target",
    [
        "private_in_source",
        "wrong_baseline",
        "wrong_recipe",
        "wrong_toolchain",
        "overlap",
        "bad_limit",
    ],
)
def test_initial_bad_scope_never_reserves_output_or_calls_process(case, target):
    if target == "private_in_source":
        (case.candidate / "recipe/private_tests.py").write_bytes(
            b"private must stay outside Worker"
        )
    elif target == "wrong_baseline":
        (case.baseline / "tool.py").write_bytes(b"not the historical baseline")
    elif target == "wrong_recipe":
        (case.recipe_root / "run_tests.py").write_bytes(b"a different recipe")
    elif target == "wrong_toolchain":
        case.context["bundle"]["deployment_receipt"]["toolchains"][0]["recipe_refs"] = ["old_1_6"]
    elif target == "overlap":
        case.roots["manager_retest"] = case.candidate / "manager-tests"
    elif target == "bad_limit":
        case.context["task"]["source_output_bytes_limit"] = True
    with pytest.raises(retests.RetestError):
        invoke(case)
    assert not case.calls
    assert not case.roots["manager_retest"].exists()


def test_interrupt_survives_diagnostic_failure_and_is_not_retried(case, monkeypatch):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt("original interrupt")

    original = task_run._persist

    def diagnostic_failure(path, value):
        if path.name == "failure.json":
            raise OSError("secondary diagnostic")
        return original(path, value)

    monkeypatch.setattr(subprocess, "run", interrupt)
    monkeypatch.setattr(task_run, "_persist", diagnostic_failure)
    with pytest.raises(KeyboardInterrupt, match="original interrupt"):
        invoke(case)
    assert (case.roots["manager_retest"] / "binding.json").exists()
    with pytest.raises(FileExistsError):
        invoke(case)


@pytest.mark.parametrize("fault", ["timeout", "missing_xml"])
def test_control_failure_retains_stage_and_stops_remaining_commands(case, monkeypatch, fault):
    original = retests.subprocess.run

    def process(argv, **kwargs):
        if fault == "timeout":
            case.calls.append(Path(kwargs["cwd"]).name)
            raise subprocess.TimeoutExpired(argv, 10)
        result = original(argv, **kwargs)
        (Path(kwargs["cwd"]) / "out/tests.xml").rename(
            Path(kwargs["cwd"]) / "out/retained-missing-report.xml"
        )
        return result

    monkeypatch.setattr(retests.subprocess, "run", process)
    with pytest.raises(subprocess.TimeoutExpired if fault == "timeout" else FileNotFoundError):
        invoke(case)
    assert case.calls == ["baseline_public"]
    stage = case.roots["manager_retest"] / "baseline_public"
    assert (stage / "failure.json").exists()
    assert not (case.roots["manager_retest"] / "candidate_public").exists()


def test_live_entry_point_stops_without_lifecycle_or_retest_io(case, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("live lifecycle or retest must not be called")

    monkeypatch.setattr(task_run, "_execute_once", forbidden)
    monkeypatch.setattr(retests, "run_manager_retests", forbidden)
    monkeypatch.setattr(task_run, "_persist", forbidden)
    assert retests.main() == 2
    output = json.loads(capsys.readouterr().out)
    assert output["error_code"] == "WorkerTestEvidenceInterfaceUnverified"
    assert output["launch_count"] == 0 and output["accepted"] is False
    assert not case.roots["manager_retest"].exists()
