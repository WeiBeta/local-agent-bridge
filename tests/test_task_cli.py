"""CLI v1: actual A/B imports, synthetic management trust and fake C launches."""

from __future__ import annotations

import json
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import test_task_input as input_fixtures
import test_task_run as fixtures
import test_task_workspace as workspace_fixtures

from local_agent_bridge import cli, task_cli
from local_agent_bridge.bridge import task_run as runner

NOTE = b"\xef\xbb\xbfOffline task note\r\nwithout final newline"
RULE = b"\xef\xbb\xbfSynthetic checked rule\r\n"
PROJECT = b'{ "permissions": {"deny":["Mcp(*)"],"allow":["Read(work/**)"]}}\r\n'


def invoke(tmp_path, capsys, command, fields, *, case=None, execute=False, raw=None):
    spec = tmp_path / "invocation.json"
    document = {"cli_contract_version": 1, **fields}
    spec.write_bytes(fixtures.canonical(document) if raw is None else raw)
    arguments = ["task", command, "--spec", str(spec)]
    if case is not None:
        arguments += [
            "--trusted-control-root",
            str(case.trust),
            "--trusted-inputs-sha256",
            case.expected,
        ]
    if execute:
        arguments.append("--execute")
    code = cli.main(arguments)
    captured = capsys.readouterr()
    value = json.loads(captured.out) if captured.out else None
    if value is not None:
        assert captured.out.encode() == fixtures.canonical(value) + b"\n"
        assert not captured.err
    else:
        assert code in {2, 130}
        assert captured.err.startswith("local-agent-bridge task: ")
        assert str(tmp_path) not in captured.err
    return code, value, captured.err


def cli_case(tmp_path, monkeypatch, capsys, **options):
    case = fixtures.prepare(
        tmp_path,
        monkeypatch,
        actual_b=True,
        publish=False,
        note=NOTE,
        files={"source.py": b"n = 0\r\n", "AGENTS.md": RULE},
        **options,
    )
    source = tmp_path / "input.zip"
    snapshot = tmp_path / "cli-snapshot"
    policy = input_fixtures._policy(
        source_paths=["source.py"], trusted_control_files={"AGENTS.md": runner._digest(RULE)}
    )
    code, imported, error = invoke(
        tmp_path,
        capsys,
        "import",
        {
            "source": input_fixtures._zip_source(source, runner._digest(source.read_bytes()), None),
            "policy": policy,
            "snapshot_root": str(snapshot),
        },
    )
    assert code == 0 and imported == case.snapshot, error
    assert not case.root.exists()
    manifest, note = tmp_path / "task-manifest.json", tmp_path / "task-note.md"
    manifest.write_bytes(b" \r\n" + fixtures.canonical(case.task) + b"\t")
    note.write_bytes(NOTE)
    case.prepare_fields = {
        "snapshot_root": str(snapshot),
        "task_manifest_path": str(manifest),
        "task_note_path": str(note),
        "task_root": str(case.root),
    }
    if case.receipt["host"] == "cursor":
        case.receipt["configuration"]["cursor_project"]["sha256"] = runner._digest(PROJECT)
        fixtures.sync(case, refresh_r=True, persist_task=False)
        manifest.write_bytes(fixtures.canonical(case.task))
        (case.trust / "cursor-project.json").write_bytes(PROJECT)
    return case


def prepared(tmp_path, monkeypatch, capsys, **options):
    case = cli_case(tmp_path, monkeypatch, capsys, **options)
    code, result, error = invoke(tmp_path, capsys, "prepare", case.prepare_fields, case=case)
    assert code == 0 and result == case.task, error
    assert (case.root / "control/TASK.md").read_bytes() == NOTE
    assert (case.root / "work/AGENTS.md").read_bytes() == RULE
    return case


def planned(tmp_path, capsys, case):
    return invoke(
        tmp_path,
        capsys,
        "plan",
        {
            "task_root": str(case.root),
            "host": case.receipt["host"],
        },
        case=case,
    )


@pytest.mark.parametrize("command", [None, "import", "prepare", "plan", "run", "collect"])
def test_help_reads_nothing(monkeypatch, capsys, command):
    monkeypatch.setattr(runner, "read_host_input_bytes", lambda **_: pytest.fail("file read"))
    monkeypatch.setattr(fixtures.slice_run, "_session_store", lambda: pytest.fail("key read"))
    args = ["task", *([] if command is None else [command]), "--help"]
    assert cli.main(args) == 0
    assert "usage: local-agent-bridge task" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["invalid"],
        ["import", "--spec", "-"],
        ["import", "--sp", "C:/fake.json"],
        ["import", "--spec", "C:/fake.json", "--spec=C:/other.json"],
        ["import", "--spec", "C:/fake.json", "extra"],
        ["import", "--spec", "C:/fake.json", "--model", "private-model"],
        ["prepare", "--spec", "C:/fake.json"],
        ["run", "--spec", "C:/fake.json", "--execute", "--execute"],
        ["import", "--help", "--spec", "C:/fake.json"],
        ["--help", "-h"],
    ],
)
def test_arguments_refuse_without_raw_diagnostics(capsys, arguments):
    assert cli.main(["task", *arguments]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err.startswith("local-agent-bridge task: ")
    assert "fake" not in captured.err and "private-model" not in captured.err


@pytest.mark.parametrize(
    "raw",
    [
        b"\xef\xbb\xbf{}",
        b"\xff",
        b"{}{}",
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1e999}',
        b'{"x":1,"x":2}',
        b"[]",
        b"null",
        b"{}",
        b'{"cli_contract_version":true,"task_root":"C:/task","host":"agy"}',
        b'{"cli_contract_version":1,"task_root":"C:/task","host":"agy","extra":1}',
    ],
)
def test_strict_envelope_refused(tmp_path, capsys, raw):
    case = type("Trust", (), {"trust": tmp_path, "expected": fixtures.H})()
    code, result, _ = invoke(tmp_path, capsys, "plan", {}, case=case, raw=raw)
    assert code == 2 and result is None


@pytest.mark.parametrize(
    "raw_path",
    [
        "relative.json",
        "-",
        "C:/root/./file",
        "C:/root/../file",
        " C:/root/file",
        "C:/root/file ",
        "C:/root./file",
        None,
        1,
    ],
)
def test_host_raw_paths_are_not_normalized(raw_path):
    with pytest.raises(runner.TaskRunError):
        runner.checked_host_path(path=raw_path)


@pytest.mark.parametrize("change", ["oversize", "grow", "identity", "hardlink", "directory"])
def test_bounded_reader_checks_before_and_after(tmp_path, monkeypatch, change):
    target = tmp_path / "bytes.json"
    target.write_bytes(b"1234")
    monkeypatch.setattr(runner, "_JSON_LIMIT", 4)
    expected = "ResourceLimitExceeded" if change in {"oversize", "grow"} else "PathRejected"
    if change == "oversize":
        target.write_bytes(b"12345")
    elif change == "hardlink":
        os.link(target, tmp_path / "second-link.json")
    elif change == "directory":
        target = tmp_path
    elif change == "grow":
        original = Path.open

        def growing(path, *args, **kwargs):
            if path == target:
                with original(path, "ab") as stream:
                    stream.write(b"5")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", growing)
    else:
        original = os.fstat
        calls = []

        def changed(descriptor):
            info = original(descriptor)
            calls.append(info)
            if len(calls) == 2:
                os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
            return info

        monkeypatch.setattr(os, "fstat", changed)
        expected = "InputChanged"
    with pytest.raises(runner.TaskRunError) as error:
        runner.read_host_input_bytes(path=str(target))
    assert error.value.code == expected


def test_reader_accepts_an_ordinary_rewritten_file(tmp_path):
    target = tmp_path / "rewritten.json"
    target.write_bytes(b"first version")
    target.write_bytes(b"second version")
    assert runner.read_host_input_bytes(path=str(target)) == b"second version"


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
def test_actual_import_sources(tmp_path, capsys, kind):
    files = {"a.cs": b"\xef\xbb\xbfbyte source\r\n", "bin.dat": b"\x00\xff"}
    if kind == "git":
        root = tmp_path / "repo"
        root.mkdir()
        commit = input_fixtures._git_repository(root, files)
        source = input_fixtures._git_source(root, commit, sorted(files))
    elif kind == "zip":
        package = tmp_path / "package.zip"
        digest = input_fixtures._write_zip(package, files)
        source = input_fixtures._zip_source(package, digest)
    else:
        root = tmp_path / "directory"
        input_fixtures._write_tree(root, files)
        manifest = input_fixtures._manifest_file(root, input_fixtures._tree_document(root))
        source = input_fixtures._directory_source(root, manifest)
    output = tmp_path / "snapshot"
    code, result, _ = invoke(
        tmp_path,
        capsys,
        "import",
        {
            "source": source,
            "policy": input_fixtures._policy(),
            "snapshot_root": str(output),
        },
    )
    assert code == 0 and result["source"]["kind"] == kind
    for path, raw in files.items():
        assert (output / "source" / path).read_bytes() == raw


@pytest.mark.parametrize(
    "change", ["missing_policy", "source_extra", "unpinned_zip", "missing_strip"]
)
def test_import_keeps_a_schema(tmp_path, capsys, change):
    package = tmp_path / "package.zip"
    digest = input_fixtures._write_zip(package, {"a.cs": b"code"})
    source = input_fixtures._zip_source(package, digest)
    policy = input_fixtures._policy()
    if change == "missing_policy":
        policy.pop("sensitive_paths")
    elif change == "source_extra":
        source["url"] = "https://example.invalid"
    elif change == "unpinned_zip":
        source["sha256"] = None
    else:
        source.pop("strip_prefix")
    code, value, _ = invoke(
        tmp_path,
        capsys,
        "import",
        {
            "source": source,
            "policy": policy,
            "snapshot_root": str(tmp_path / "snapshot"),
        },
    )
    assert code == 2 and value is None


@pytest.mark.parametrize("mutation", ["hash", "canonical", "cross_binding", "b_binding", "note"])
def test_prepare_refuses_trust_or_control_drift(tmp_path, monkeypatch, capsys, mutation):
    case = cli_case(tmp_path, monkeypatch, capsys)
    if mutation == "hash":
        case.expected = "0" * 64
    elif mutation == "canonical":
        path = case.trust / "authorization.json"
        path.write_bytes(path.read_bytes() + b"\n")
    elif mutation == "cross_binding":
        case.profile["receipt_sha256"] = "b" * 64
        fixtures.write_json(case.trust / "deployment-profile.json", case.profile)
        case.expected = fixtures.digest(
            {
                "deployment_receipt": case.receipt,
                "deployment_profile": case.profile,
                "authorization": case.auth,
            }
        )
    elif mutation == "b_binding":
        case.auth["input_control_bindings"]["files"] = []
        fixtures.sync(case, persist_task=False)
        Path(case.prepare_fields["task_manifest_path"]).write_bytes(fixtures.canonical(case.task))
    else:
        Path(case.prepare_fields["task_note_path"]).write_bytes(b"changed note")
    code, value, _ = invoke(tmp_path, capsys, "prepare", case.prepare_fields, case=case)
    assert code == 2 and value is None and not case.root.exists()


@pytest.mark.parametrize("root_kind", ["task", "snapshot", "run", "product"])
def test_trusted_root_disjointness(tmp_path, monkeypatch, capsys, root_kind):
    case = cli_case(tmp_path, monkeypatch, capsys)
    other = {
        "task": case.root,
        "snapshot": tmp_path / "cli-snapshot",
        "run": tmp_path / "run",
        "product": Path(runner.__file__).parents[3],
    }[root_kind]
    if root_kind == "run":
        other.mkdir()
    with pytest.raises(runner.TaskRunError, match="TrustedRootRejected"):
        runner.load_trusted_inputs(
            trusted_control_root=other.parent if root_kind == "task" else other,
            trusted_inputs_sha256=case.expected,
            task_root=case.root,
            snapshot_root=tmp_path / "cli-snapshot",
            run_root=tmp_path / "run",
        )


@pytest.mark.parametrize("host", ["agy", "cursor"])
@pytest.mark.parametrize("role,worker_execute", [("Coding", True), ("Review", False)])
@pytest.mark.parametrize("accepted", [True, False])
def test_actual_pipeline_dry_and_fake_execute(
    tmp_path, monkeypatch, capsys, host, role, worker_execute, accepted
):
    case = prepared(
        tmp_path,
        monkeypatch,
        capsys,
        host=host,
        role=role,
        accepted=accepted,
        caps={"execute": worker_execute, "web_reference": False, "prepare_dependencies": False},
    )
    code, frozen, _ = planned(tmp_path, capsys, case)
    assert code == (0 if accepted else 2)
    assert frozen["preflight_status"] == ("Ready" if accepted else "Blocked")
    if host == "cursor":
        assert (case.root / ".cursor/cli.json").read_bytes() == PROJECT
    run_root = tmp_path / "dry"
    with monkeypatch.context() as dry:
        dry.setattr(fixtures.slice_run, "_session_store", lambda: pytest.fail("dry key read"))
        dry.setattr(
            fixtures.slice_run,
            "spawn_suspended_in_job",
            lambda *_a, **_k: pytest.fail("dry launch"),
        )
        code, receipt, _ = invoke(
            tmp_path,
            capsys,
            "run",
            {
                "task_root": str(case.root),
                "run_root": str(run_root),
            },
            case=case,
        )
    assert code == (0 if accepted else 2) and receipt["launch_count"] == 0
    assert (run_root / "run.json").read_bytes() == fixtures.canonical(receipt)
    fixtures.fake_spawn(case, monkeypatch)
    code, receipt, _ = invoke(
        tmp_path,
        capsys,
        "run",
        {
            "task_root": str(case.root),
            "run_root": str(tmp_path / "executed"),
        },
        case=case,
        execute=True,
    )
    assert code == (0 if accepted else 2) and receipt["launch_count"] == (1 if accepted else 0)
    assert len(case.calls) == (1 if accepted else 0)
    if role == "Review":
        workspace_fixtures.review_outputs(case.root, case.task, case.snapshot)
    else:
        workspace_fixtures.progress(case.root, case.task)
    code, result, _ = invoke(
        tmp_path,
        capsys,
        "collect",
        {
            "task_root": str(case.root),
            "run_root": str(tmp_path / "executed"),
            "result_root": str(tmp_path / "collected"),
        },
    )
    assert code == (0 if accepted else 2)
    assert result["management_decision"] is None
    assert result["worker_status"] == "Completed"


@pytest.mark.parametrize("conflict", ["bytes", "extra", "missing_template", "schema", "partial"])
def test_cursor_preparation_conflicts_preserve_material(tmp_path, monkeypatch, capsys, conflict):
    case = prepared(tmp_path, monkeypatch, capsys, host="cursor")
    template = case.trust / "cursor-project.json"
    if conflict in {"bytes", "extra"}:
        directory = case.root / ".cursor"
        directory.mkdir()
        (directory / "cli.json").write_bytes(PROJECT if conflict == "extra" else b"conflict")
        if conflict == "extra":
            (directory / "other.json").write_bytes(b"retained")
    elif conflict == "missing_template":
        template.rename(template.with_suffix(".retained"))
    elif conflict == "schema":
        raw = b'{"permissions":{"allow":[],"deny":[],"extra":true}}'
        template.write_bytes(raw)
        case.receipt["configuration"]["cursor_project"]["sha256"] = runner._digest(raw)
        fixtures.sync(case, refresh_r=True)
    else:
        original = runner._persist

        def persist(path, value, **options):
            if path.name == "plan.json":
                raise OSError("synthetic fixed persistence failure")
            return original(path, value, **options)

        monkeypatch.setattr(runner, "_persist", persist)
    code, result, _ = planned(tmp_path, capsys, case)
    assert code == 2 and result is None and not case.calls
    assert not (case.root / "control/plan.json").exists()
    if conflict == "partial":
        assert (case.root / ".cursor/cli.json").read_bytes() == PROJECT
        assert (case.root / "control/deployment-receipt.json").exists()
    elif conflict == "bytes":
        assert (case.root / ".cursor/cli.json").read_bytes() == b"conflict"
    elif conflict == "extra":
        assert (case.root / ".cursor/other.json").read_bytes() == b"retained"


def test_existing_cursor_material_is_read_only_and_run_does_not_prepare(
    tmp_path, monkeypatch, capsys
):
    case = prepared(tmp_path, monkeypatch, capsys, host="cursor")
    assert planned(tmp_path, capsys, case)[0] == 0
    target = case.root / ".cursor/cli.json"
    before = target.stat()
    assert planned(tmp_path, capsys, case)[0] == 0
    assert target.stat().st_mtime_ns == before.st_mtime_ns
    monkeypatch.setattr(
        runner, "prepare_cursor_project", lambda **_: pytest.fail("run prepared config")
    )
    target.write_bytes(b"changed")
    code, value, _ = invoke(
        tmp_path,
        capsys,
        "run",
        {
            "task_root": str(case.root),
            "run_root": str(tmp_path / "run"),
        },
        case=case,
        execute=True,
    )
    assert code == 2 and value is None and target.read_bytes() == b"changed" and not case.calls


@pytest.mark.parametrize("drift", ["trust", "note", "source", "rule", "plan", "identity"])
def test_plan_run_drift_never_launches(tmp_path, monkeypatch, capsys, drift):
    case = prepared(tmp_path, monkeypatch, capsys)
    assert planned(tmp_path, capsys, case)[0] == 0
    path = {
        "trust": case.trust / "authorization.json",
        "note": case.root / "control/TASK.md",
        "source": case.root / "work/source.py",
        "rule": case.root / "work/AGENTS.md",
        "plan": case.root / "control/plan.json",
        "identity": case.host_entry,
    }[drift]
    path.write_bytes(path.read_bytes() + b"changed")
    monkeypatch.setattr(
        fixtures.slice_run, "spawn_suspended_in_job", lambda *_a, **_k: pytest.fail("launch")
    )
    code, value, _ = invoke(
        tmp_path,
        capsys,
        "run",
        {
            "task_root": str(case.root),
            "run_root": str(tmp_path / "run"),
        },
        case=case,
        execute=True,
    )
    assert code == 2 and not case.calls
    if value is not None:
        assert value["blockers"] and value["launch_count"] == 0


@pytest.mark.parametrize(
    "outcome", ["failed", "timeout", "null", "capture", "restore", "interrupt"]
)
def test_fake_run_terminal_states_are_not_cli_success(tmp_path, monkeypatch, capsys, outcome):
    case = prepared(tmp_path, monkeypatch, capsys)
    assert planned(tmp_path, capsys, case)[0] == 0
    process = fixtures.fake_spawn(
        case,
        monkeypatch,
        exit_code=7 if outcome == "failed" else 0,
        wait_error=subprocess.TimeoutExpired("synthetic", 1)
        if outcome == "timeout"
        else KeyboardInterrupt()
        if outcome == "interrupt"
        else None,
    )
    if outcome == "null":

        def ambiguous(_argv, _cwd, *, lifecycle):
            case.calls.append("one attempt")
            lifecycle.begin_resume()
            raise OSError("synthetic private diagnostic")

        monkeypatch.setattr(fixtures.slice_run, "spawn_suspended_in_job", ambiguous)
    elif outcome == "capture":
        monkeypatch.setattr(
            fixtures.slice_run, "_session_store", lambda: (_ for _ in ()).throw(OSError("private"))
        )
    elif outcome == "restore":
        monkeypatch.setattr(
            fixtures.slice_run,
            "_restore_settings",
            lambda *_a, **_k: {"restored_original_bytes": False},
        )
    code, result, error = invoke(
        tmp_path,
        capsys,
        "run",
        {
            "task_root": str(case.root),
            "run_root": str(tmp_path / "run"),
        },
        case=case,
        execute=True,
    )
    assert code == (130 if outcome == "interrupt" else 2)
    assert len(case.calls) <= 1
    if outcome == "interrupt":
        assert result is None and process.closed and process.terminated
        assert error == "local-agent-bridge task: Interrupted\n"
    elif outcome == "null":
        assert result["launch_count"] is None
    elif outcome == "restore":
        assert result["restore_state"] == "Failed"


@pytest.mark.parametrize("change", ["null_run", "missing_output", "out_of_scope", "worker_blocked"])
def test_collect_exit_tracks_host_checks_not_worker_verdict(tmp_path, monkeypatch, capsys, change):
    case = prepared(tmp_path, monkeypatch, capsys)
    if change != "missing_output":
        workspace_fixtures.progress(
            case.root, case.task, status="Blocked" if change == "worker_blocked" else "Completed"
        )
    if change == "out_of_scope":
        (case.root / "work/vendor").mkdir()
        (case.root / "work/vendor/new.py").write_bytes(b"unapproved")
    code, result, _ = invoke(
        tmp_path,
        capsys,
        "collect",
        {
            "task_root": str(case.root),
            "run_root": None,
            "result_root": str(tmp_path / "collected"),
        },
    )
    assert code == (2 if change in {"missing_output", "out_of_scope"} else 0)
    assert result["management_decision"] is None
    assert result["host_observations"]["transport_state"] == "NotRun"
    assert result["plan_sha256"] is None
    if change == "worker_blocked":
        assert result["worker_status"] == "Blocked" and not result["blockers"]


def test_runtime_identity_includes_actual_cli_modules(tmp_path, monkeypatch, capsys):
    case = prepared(tmp_path, monkeypatch, capsys)
    required = set(runner._runtime_files())
    assert (
        Path(cli.__file__).resolve() in required and Path(task_cli.__file__).resolve() in required
    )
    case.receipt["bridge"]["product_files"] = [
        item
        for item in case.receipt["bridge"]["product_files"]
        if Path(item["path"]).name != "task_cli.py"
    ]
    fixtures.sync(case, refresh_r=True)
    code, result, _ = planned(tmp_path, capsys, case)
    assert code == 2 and "RuntimeIdentityUnverified" in result["blockers"]


def test_unexpected_failure_has_no_trace_or_raw_text(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        task_cli, "_dispatch", lambda *_: (_ for _ in ()).throw(RuntimeError("private raw text"))
    )
    code, result, error = invoke(
        tmp_path,
        capsys,
        "collect",
        {
            "task_root": str(tmp_path / "task"),
            "run_root": None,
            "result_root": str(tmp_path / "result"),
        },
    )
    assert code == 2 and result is None and error == "local-agent-bridge task: CliInternalError\n"


def test_import_rejects_spec_changed_after_read_observation(tmp_path, monkeypatch, capsys):
    """R01 actual CLI equivalent to the independently reviewed ZIP spec change."""
    case = cli_case(tmp_path, monkeypatch, capsys)
    source = tmp_path / "input.zip"
    old_root, new_root = tmp_path / "out-one", tmp_path / "out-two"
    fields = {
        "source": input_fixtures._zip_source(source, runner._digest(source.read_bytes()), None),
        "policy": input_fixtures._policy(trusted_control_files={"AGENTS.md": runner._digest(RULE)}),
        "snapshot_root": str(old_root),
    }
    original = fixtures.canonical({"cli_contract_version": 1, **fields})
    changed = fixtures.canonical(
        {"cli_contract_version": 1, **fields, "snapshot_root": str(new_root)}
    )
    assert len(original) == len(changed)
    spec = tmp_path / "invocation.json"
    real_fstat, observations = os.fstat, []

    def observe(descriptor):
        info = real_fstat(descriptor)
        observations.append(info.st_ctime_ns)
        if len(observations) == 2:
            before = spec.stat()
            time.sleep(0.05)
            spec.write_bytes(changed)
            os.utime(spec, ns=(before.st_atime_ns, before.st_mtime_ns))
        return info

    monkeypatch.setattr(os, "fstat", observe)
    code, result, error = invoke(tmp_path, capsys, "import", fields, raw=original)
    facts = {
        "exit": code,
        "result": result,
        "error": error,
        "old_published": old_root.exists(),
        "new_published": new_root.exists(),
        "current_spec_sha256": runner._digest(spec.read_bytes()),
        "observations": observations,
        "prepared_task_published": case.root.exists(),
    }
    (tmp_path / "spec-change-facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
    assert code == 2 and result is None and error.endswith("InputChanged\n"), facts
    assert not old_root.exists() and not new_root.exists()


@pytest.mark.parametrize("host", ["agy", "cursor"])
@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
@pytest.mark.parametrize(
    "stage",
    [
        "receipt_before",
        "receipt_partial",
        "receipt_after",
        "plan_before",
        "plan_partial",
        "plan_after",
    ],
)
def test_partial_plan_persistence_is_observed_by_b(
    tmp_path, monkeypatch, capsys, host, failure, stage
):
    case = prepared(tmp_path, monkeypatch, capsys, host=host)
    original = runner._persist
    filename, moment = stage.split("_")
    expected_name = "deployment-receipt.json" if filename == "receipt" else "plan.json"

    def persist(path, value, **options):
        if path.name != expected_name:
            return original(path, value, **options)
        if moment == "partial":
            with path.open("xb") as stream:
                stream.write(fixtures.canonical(value)[:5])
        elif moment == "after":
            original(path, value, **options)
        raise failure("synthetic fixed publication failure")

    monkeypatch.setattr(runner, "_persist", persist)
    code, result, _ = planned(tmp_path, capsys, case)
    assert code == (130 if failure is KeyboardInterrupt else 2) and result is None
    controls = [
        case.root / "control/deployment-receipt.json",
        case.root / "control/plan.json",
        case.root / ".cursor/cli.json",
    ]
    retained = {path: path.read_bytes() for path in controls if path.exists()}
    workspace_fixtures.progress(case.root, case.task)
    code, result, _ = invoke(
        tmp_path,
        capsys,
        "collect",
        {"task_root": str(case.root), "run_root": None, "result_root": str(tmp_path / "collected")},
    )
    # A failure before agy writes anything still leaves exactly a pure prepare.
    complete = stage == "plan_after" or (host == "agy" and stage == "receipt_before")
    assert code == (0 if complete else 2), result["blockers"]
    assert result["host_observations"]["scope_status"] == ("Pass" if complete else "Fail")
    assert ("ControlChanged" in result["blockers"]) is not complete
    assert (result["continuation"] is None) is not complete
    assert result["management_decision"] is None and result["plan_sha256"] is None
    assert not case.calls
    for path, raw in retained.items():
        assert path.read_bytes() == raw


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
@pytest.mark.parametrize(
    "stage", ["mkdir_before", "mkdir_after", "file_before", "file_partial", "file_after"]
)
def test_cursor_preparation_failure_is_observed_by_b(tmp_path, monkeypatch, capsys, failure, stage):
    case = prepared(tmp_path, monkeypatch, capsys, host="cursor")
    directory, target = case.root / ".cursor", case.root / ".cursor/cli.json"
    original_mkdir, original_open = Path.mkdir, Path.open

    def fail():
        raise failure("synthetic fixed Cursor preparation failure")

    def mkdir(path, *args, **kwargs):
        if path == directory and stage == "mkdir_before":
            fail()
        value = original_mkdir(path, *args, **kwargs)
        if path == directory and stage == "mkdir_after":
            fail()
        return value

    class PartialWriter:
        def __init__(self, stream):
            self.stream = stream

        def write(self, raw):
            self.stream.write(raw[:5])
            fail()

    @contextmanager
    def failing_open(path, *args, **kwargs):
        if stage == "file_before":
            fail()
        with original_open(path, *args, **kwargs) as stream:
            yield PartialWriter(stream) if stage == "file_partial" else stream
        if stage == "file_after":
            fail()

    def open_file(path, *args, **kwargs):
        if path == target and args == ("xb",):
            return failing_open(path, *args, **kwargs)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(Path, "open", open_file)
    code, value, _ = planned(tmp_path, capsys, case)
    assert code == (130 if failure is KeyboardInterrupt else 2) and value is None
    before = target.read_bytes() if target.exists() else None
    workspace_fixtures.progress(case.root, case.task)
    code, result, _ = invoke(
        tmp_path,
        capsys,
        "collect",
        {"task_root": str(case.root), "run_root": None, "result_root": str(tmp_path / "collected")},
    )
    incomplete = stage != "mkdir_before"
    assert code == (2 if incomplete else 0)
    assert ("ControlChanged" in result["blockers"]) is incomplete
    assert (result["continuation"] is None) is incomplete
    assert not case.calls and result["management_decision"] is None
    if before is not None:
        assert target.read_bytes() == before
