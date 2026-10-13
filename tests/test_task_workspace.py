"""Synthetic offline workspace/collector tests; no upstream CLI or credentials."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import zipfile
from pathlib import Path

import pytest

from local_agent_bridge.bridge import task_workspace as entry
from local_agent_bridge.bridge.task_input import import_snapshot, read_snapshot
from local_agent_bridge.bridge.task_workspace import TaskWorkspaceError, collect_task, prepare_task


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


FILES = {
    "src/main.cs": b"first\r\nsecond\r\n",
    "old.txt": b"old content",
    "rename.txt": b"unique rename bytes",
    "blob.bin": b"\x00\xff\xfe",
    "bom.txt": b"\xef\xbb\xbfUTF8\r\n",
    "TASK.md": "来源任务说明不等于可信指令".encode(),
}
OPAQUE_RECEIPT = {"offline_identity_fixture": "C schema and authorization not asserted"}


def snapshot_fixture(
    root: Path,
    files: dict[str, bytes] | None = None,
    excluded: list[dict] | None = None,
    trusted_controls: dict[str, str] | None = None,
) -> tuple[Path, dict]:
    files = FILES if files is None else files
    package = root / "input.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, raw in files.items():
            archive.writestr(path, raw)
    source_paths = sorted(
        [path for path in files if path.endswith(".cs")], key=lambda item: item.encode()
    )
    snapshot_root = root / "snapshot"
    snapshot = import_snapshot(
        source={
            "kind": "zip",
            "path": str(package),
            "sha256": sha(package.read_bytes()),
            "strip_prefix": None,
        },
        policy={
            "source_paths": source_paths,
            "excluded_paths": excluded or [],
            "sensitive_paths": [],
            "trusted_control_files": trusted_controls or {},
        },
        snapshot_root=snapshot_root,
    )
    return snapshot_root, snapshot


def documents(snapshot: dict, role: str = "Coding") -> tuple[dict, bytes, dict, dict]:
    note = "可信任务说明\r\n".encode()
    capabilities = {
        "execute": role == "Coding",
        "web_reference": False,
        "prepare_dependencies": False,
    }
    read_roots = ["control", "out", "scratch", "work"]
    write_roots = ["out", "scratch", "work"] if role == "Coding" else ["out", "scratch"]
    profile = {
        "contract_version": 1,
        "id": "offline-profile",
        "host": "agy",
        "receipt_sha256": sha(canonical(OPAQUE_RECEIPT)),
        "roles": ["Coding", "Review"],
        "supported_capabilities": {
            "execute": True,
            "web_reference": True,
            "prepare_dependencies": True,
        },
        "execution_modes": ["declared_scope", "required_enforced"],
        "read_roots": read_roots.copy(),
        "write_roots": ["out", "scratch", "work"],
        "toolchain_refs": ["offline-toolchain"],
        "enforcement": {
            "method": "fixture",
            "file_scope": "Unverified",
            "network_scope": "Unverified",
            "evidence_refs": [],
        },
    }
    auth = {
        "contract_version": 1,
        "task_id": "OFFLINE-01",
        "grant_ref": "offline fixture, not real authorization",
        "receipt_sha256": "2" * 64,
        "capabilities": capabilities.copy(),
        "execution_boundary": "declared_scope",
        "read_roots": read_roots.copy(),
        "write_roots": write_roots.copy(),
        "web_scope": None,
        "dependency_scope": None,
        "input_control_bindings": {"task_fields_sha256": "0" * 64, "files": {}},
    }
    required = (
        ["out/progress.json"]
        if role == "Coding"
        else ["out/coverage.json", "out/findings.json", "out/progress.json", "out/report.md"]
    )
    task = {
        "contract_version": 1,
        "task_id": "OFFLINE-01",
        "role": role,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_manifest_sha256": sha(canonical(snapshot)),
        "instructions_sha256": sha(note),
        "deployment_profile_id": profile["id"],
        "deployment_profile_sha256": sha(canonical(profile)),
        "capabilities": capabilities.copy(),
        "execution_boundary": "declared_scope",
        "authorization_sha256": sha(canonical(auth)),
        "read_roots": read_roots,
        "write_roots": write_roots,
        "protected_paths": ["control", "task.json"],
        "required_outputs": required,
        "acceptance_ids": ["CODING-01", "TEST-01"],
        "deadline_seconds": 1020,
        "source_output_bytes_limit": 536870912,
    }
    bind(task, profile, auth)
    return task, note, profile, auth


def bind(task: dict, profile: dict, auth: dict) -> None:
    task["deployment_profile_sha256"] = sha(canonical(profile))
    auth["input_control_bindings"]["task_fields_sha256"] = sha(
        canonical({key: value for key, value in task.items() if key != "authorization_sha256"})
    )
    task["authorization_sha256"] = sha(canonical(auth))


def prepare(
    root: Path, role: str = "Coding", files: dict[str, bytes] | None = None
) -> tuple[Path, dict, dict]:
    snapshot_root, snapshot = snapshot_fixture(root, files)
    task, note, profile, auth = documents(snapshot, role)
    task_root = root / "task"
    assert (
        prepare_task(
            snapshot_root=snapshot_root,
            task_manifest=task,
            task_note=note,
            deployment_profile=profile,
            authorization=auth,
            task_root=task_root,
        )
        == task
    )
    return task_root, task, snapshot


def progress(
    root: Path, task: dict, status: str = "Completed", remaining: list[str] | None = None
) -> None:
    (root / "out" / "progress.json").write_bytes(
        canonical(
            {
                "contract_version": 1,
                "task_id": task["task_id"],
                "status": status,
                "summary": "合成结果声明",
                "remaining_paths": remaining or [],
            }
        )
    )


def review_outputs(root: Path, task: dict, snapshot: dict) -> None:
    progress(root, task)
    (root / "out" / "report.md").write_bytes("# 中文审查\n这是 Worker 声明。\n".encode())
    paths = {item["path"] for item in snapshot["entries"]} | {
        item["path"] for item in snapshot["excluded_paths"]
    }
    coverage = {
        "contract_version": 1,
        "task_id": task["task_id"],
        "snapshot_id": snapshot["snapshot_id"],
        "entries": [
            {"path": path, "state": "Analyzed", "reason": "合成声明"} for path in sorted(paths)
        ],
        "package_entry_count": len(paths),
        "source_file_count": len(snapshot["source_paths"]),
    }
    (root / "out" / "coverage.json").write_bytes(canonical(coverage))
    (root / "out" / "findings.json").write_bytes(
        canonical(
            {
                "contract_version": 1,
                "task_id": task["task_id"],
                "snapshot_id": snapshot["snapshot_id"],
                "findings": [],
            }
        )
    )


def collect(root: Path, result: Path | None = None, run_root: Path | None = None) -> dict:
    return collect_task(
        task_root=root, run_root=run_root, result_root=result or root.parent / "result"
    )


def receipt_fixture(root: Path, task: dict, state: str = "Completed") -> tuple[Path, dict]:
    plan = {
        "contract_version": 1,
        "task_id": task["task_id"],
        "task_manifest_sha256": sha(canonical(task)),
        "deployment_receipt_sha256": sha(canonical(OPAQUE_RECEIPT)),
        "host": "agy",
        "route": {"model": "gemini-3.8-flash-high", "effort": "high"},
        "execution_boundary": task["execution_boundary"],
        "capabilities": task["capabilities"],
        "preflight_status": "Ready",
        "blockers": [],
        "evidence_refs": [],
    }
    (root / "control" / "plan.json").write_bytes(canonical(plan))
    (root / "control" / "deployment-receipt.json").write_bytes(canonical(OPAQUE_RECEIPT))
    run_root = root.parent / "run"
    run_root.mkdir()
    value = {
        "contract_version": 1,
        "task_id": task["task_id"],
        "plan_sha256": sha(canonical(plan)),
        "transport_state": state,
        "launch_count": 0 if state == "NotRun" else 1,
        "capture_uid": None if state == "NotRun" else "synthetic-uid",
        "capture_state": "NotRun" if state == "NotRun" else "Sealed",
        "restore_state": "NotRun" if state == "NotRun" else "Restored",
        "test_observations": [],
        "evidence_refs": [],
        "blockers": [],
    }
    (run_root / "run.json").write_bytes(canonical(value))
    return run_root, value


def test_signatures_and_error_contract():
    for function in (prepare_task, collect_task, entry.verify_input_controls):
        assert all(
            item.kind == inspect.Parameter.KEYWORD_ONLY
            for item in inspect.signature(function).parameters.values()
        )
    assert issubclass(TaskWorkspaceError, RuntimeError)
    assert TaskWorkspaceError("Code", "fixed message").code == "Code"
    assert list(inspect.signature(entry.verify_input_controls).parameters) == [
        "task_root",
        "task_manifest",
        "deployment_profile",
        "authorization",
    ]
    assert "verify_input_controls" in entry.__all__


@pytest.mark.parametrize("role", ["Coding", "Review"])
def test_prepare_independent_raw_bytes_and_notrun(tmp_path, role):
    root, task, snapshot = prepare(tmp_path, role)
    for path, raw in FILES.items():
        assert (root / "work" / path).read_bytes() == raw
        assert not os.path.samefile(root / "work" / path, tmp_path / "snapshot" / "source" / path)
    assert (root / "control" / "TASK.md").read_bytes() != FILES["TASK.md"]
    assert (root / "task.json").read_bytes() == canonical(task)
    if role == "Review":
        review_outputs(root, task, snapshot)
    else:
        progress(root, task)
    result = collect(root)
    assert result["worker_status"] == "Completed"
    assert result["management_decision"] is None
    assert result["host_observations"]["transport_state"] == "NotRun"
    assert all(
        item["result"] == "Unrun" for item in result["host_observations"]["acceptance_observations"]
    )
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == snapshot


@pytest.mark.parametrize(
    "mutation",
    [
        {"extra": True},
        {"contract_version": True},
        {"deadline_seconds": True},
        {"deadline_seconds": 3601},
        {"source_output_bytes_limit": 0},
        {"role": "Debug"},
        {"execution_boundary": "skip"},
        {"snapshot_id": "F" * 64},
        {"write_roots": ["control"]},
        {"write_roots": ["outside"]},
        {"write_roots": ["work", "out"]},
        {"protected_paths": ["task.json"]},
        {"required_outputs": ["out/missing.txt"]},
        {"required_outputs": ["out/progress.json", "work/test.txt"]},
        {"read_roots": ["control", "out", "scratch", "work/../escape"]},
        {"capabilities": {"execute": True}},
        {"capabilities": {"execute": 1, "web_reference": False, "prepare_dependencies": False}},
        {"capabilities": {"execute": False, "web_reference": False, "prepare_dependencies": True}},
    ],
)
def test_task_shape_rejections_before_publication(tmp_path, mutation):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot)
    task.update(mutation)
    with pytest.raises(TaskWorkspaceError):
        prepare_task(
            snapshot_root=source,
            task_manifest=task,
            task_note=note,
            deployment_profile=profile,
            authorization=auth,
            task_root=tmp_path / "task",
        )
    assert not (tmp_path / "task").exists()
    assert not (tmp_path / "task.staging").exists()


@pytest.mark.parametrize(
    "target,key,value",
    [
        ("task", "instructions_sha256", "0" * 64),
        ("task", "snapshot_manifest_sha256", "0" * 64),
        ("task", "deployment_profile_id", "unknown"),
        ("profile", "host", "unknown"),
        ("profile", "roles", ["Review"]),
        ("profile", "execution_modes", ["required_enforced"]),
        ("profile", "extra", "unknown"),
        ("auth", "task_id", "OTHER"),
        ("auth", "execution_boundary", "required_enforced"),
        ("auth", "write_roots", ["out"]),
        ("auth", "grant_ref", ""),
    ],
)
def test_control_identity_and_authorized_subset(tmp_path, target, key, value):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot)
    {"task": task, "profile": profile, "auth": auth}[target][key] = value
    bind(task, profile, auth)
    with pytest.raises(TaskWorkspaceError):
        prepare_task(
            snapshot_root=source,
            task_manifest=task,
            task_note=note,
            deployment_profile=profile,
            authorization=auth,
            task_root=tmp_path / "task",
        )


@pytest.mark.parametrize(
    "role,execute,web,deps,boundary",
    [
        ("Coding", True, False, False, "declared_scope"),
        ("Coding", True, True, True, "required_enforced"),
        ("Review", False, True, False, "declared_scope"),
        ("Review", True, False, True, "required_enforced"),
    ],
)
def test_capability_combinations_are_offline_only(tmp_path, role, execute, web, deps, boundary):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot, role)
    task["capabilities"] = {"execute": execute, "web_reference": web, "prepare_dependencies": deps}
    auth["capabilities"] = task["capabilities"].copy()
    task["execution_boundary"] = auth["execution_boundary"] = boundary
    auth["web_scope"] = "registered-query-fixture" if web else None
    auth["dependency_scope"] = "registered-lock-fixture" if deps else None
    bind(task, profile, auth)
    assert (
        prepare_task(
            snapshot_root=source,
            task_manifest=task,
            task_note=note,
            deployment_profile=profile,
            authorization=auth,
            task_root=tmp_path / "task",
        )
        == task
    )


def rule_documents(root, *, role="Review", name="AGENTS.md"):
    raw = b"# Synthetic source instructions\r\nPreserve original bytes.\r\n"
    source, snapshot = snapshot_fixture(
        root, {name: raw, "src/main.cs": b"source"}, trusted_controls={name: sha(raw)}
    )
    task, note, profile, auth = documents(snapshot, role)
    task["protected_paths"] = sorted(["control", "task.json", "work/" + name])
    auth["input_control_bindings"]["files"] = {name: sha(raw)}
    bind(task, profile, auth)
    return source, snapshot, task, note, profile, auth


def prepare_documents(root, source, task, note, profile, auth):
    return prepare_task(
        snapshot_root=source,
        task_manifest=task,
        task_note=note,
        deployment_profile=profile,
        authorization=auth,
        task_root=root / "task",
    )


@pytest.mark.parametrize("role", ["Coding", "Review"])
@pytest.mark.parametrize("seconds", [1, 300, 1020, 3600])
def test_work_deadline_all_existing_roles_and_shorter_limits(tmp_path, role, seconds):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot, role)
    task["deadline_seconds"] = seconds
    bind(task, profile, auth)
    assert prepare_documents(tmp_path, source, task, note, profile, auth) == task
    assert json.loads((tmp_path / "task/task.json").read_bytes())["deadline_seconds"] == seconds


@pytest.mark.parametrize("role", ["Coding", "Review"])
@pytest.mark.parametrize("seconds", [0, -1, 3601, True, False, 3600.0, "3600", None])
def test_work_deadline_type_and_bounds(tmp_path, role, seconds):
    _, snapshot = snapshot_fixture(tmp_path)
    task, _, _, _ = documents(snapshot, role)
    task["deadline_seconds"] = seconds
    with pytest.raises(TaskWorkspaceError):
        entry._task_shape(task)


def verify_documents(root, task, profile, auth):
    entry.verify_input_controls(
        task_root=root, task_manifest=task, deployment_profile=profile, authorization=auth
    )


@pytest.mark.parametrize("role", ["Coding", "Review"])
@pytest.mark.parametrize("name", ["AGENTS.md", "nest/GEMINI.md", "é/CLAUDE.md", ".cursorrules"])
def test_bound_rule_exact_raw_bytes_remain_in_all_copies(tmp_path, role, name):
    source, snapshot, task, note, profile, auth = rule_documents(tmp_path, role=role, name=name)
    assert prepare_documents(tmp_path, source, task, note, profile, auth) == task
    root = tmp_path / "task"
    verify_documents(root, task, profile, auth)
    raw = (source / "source" / name).read_bytes()
    for copy in (root / "work" / name, root / "control" / "snapshot" / "source" / name):
        assert copy.read_bytes() == raw
        assert not os.path.samefile(copy, source / "source" / name)
    if role == "Review":
        review_outputs(root, task, snapshot)
    else:
        progress(root, task)
    result = collect(root)
    assert result["host_observations"]["scope_status"] == "Pass"
    assert result["host_observations"]["transport_state"] == "NotRun"
    assert "InputControlConflict" not in result["blockers"]
    assert (tmp_path / "result" / "candidate" / name).read_bytes() == raw
    assert result["management_decision"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "null",
        "keys",
        "empty",
        "case",
        "nfc",
        "digest",
        "extra",
        "directory",
        "duplicate",
        "protection",
        "projection",
        "excluded",
    ],
)
def test_rule_binding_rejections_have_no_implicit_grant(tmp_path, mutation):
    source, _, task, note, profile, auth = rule_documents(tmp_path, name="é/AGENTS.md")
    mapping = auth["input_control_bindings"]["files"]
    if mutation == "missing":
        del auth["input_control_bindings"]
    elif mutation == "null":
        auth["input_control_bindings"] = None
    elif mutation == "keys":
        auth["input_control_bindings"]["extra"] = True
    elif mutation == "empty":
        mapping.clear()  # A accepted the exact rule, but that is not a B grant.
    elif mutation in {"case", "nfc"}:
        digest = mapping.pop("é/AGENTS.md")
        mapping["é/agents.md" if mutation == "case" else "e\u0301/AGENTS.md"] = digest
    elif mutation == "digest":
        mapping["é/AGENTS.md"] = "0" * 64
    elif mutation == "extra":
        mapping["src/main.cs"] = sha(b"source")
    elif mutation == "directory":
        mapping["é"] = "0" * 64
    elif mutation == "duplicate":
        mapping["É/agents.md"] = mapping["é/AGENTS.md"]
    elif mutation == "protection":
        task["protected_paths"] = ["control", "task.json"]
    elif mutation == "projection":
        auth["input_control_bindings"]["task_fields_sha256"] = "0" * 64
    else:
        mapping["omitted/AGENTS.md"] = "0" * 64
    # Reissue hashes, except the deliberately invalid projection/shape cases.
    if mutation not in {"missing", "null", "projection"}:
        bind(task, profile, auth)
    else:
        task["authorization_sha256"] = sha(canonical(auth))
    with pytest.raises(TaskWorkspaceError) as caught:
        prepare_documents(tmp_path, source, task, note, profile, auth)
    assert caught.value.code == "InputControlConflict"
    assert not (tmp_path / "task").exists()
    assert not (tmp_path / "task.staging").exists()
    assert (source / "source" / "é" / "AGENTS.md").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "Coding"),
        ("capabilities", {"execute": True, "web_reference": False, "prepare_dependencies": False}),
        ("execution_boundary", "required_enforced"),
        ("instructions_sha256", "1" * 64),
        ("deployment_profile_sha256", "1" * 64),
        ("snapshot_id", "1" * 64),
        ("deadline_seconds", 1000),
        ("acceptance_ids", ["OTHER"]),
        ("required_outputs", ["out/progress.json"]),
        ("source_output_bytes_limit", 100000),
        ("read_roots", ["out", "scratch", "work"]),
    ],
)
def test_task_projection_binds_fields_beyond_authorization_sha(tmp_path, field, value):
    source, _, task, note, profile, auth = rule_documents(tmp_path)
    task[field] = value
    with pytest.raises(TaskWorkspaceError) as caught:
        prepare_documents(tmp_path, source, task, note, profile, auth)
    assert caught.value.code == "InputControlConflict"


@pytest.mark.parametrize(
    "name", [".cursor/cli.json", ".gemini/settings.json", ".claude/settings.json"]
)
def test_native_configuration_cannot_be_exempted_by_rule_binding(tmp_path, name):
    source, _, task, note, profile, auth = rule_documents(tmp_path, name=name)
    with pytest.raises(TaskWorkspaceError) as caught:
        prepare_documents(tmp_path, source, task, note, profile, auth)
    assert caught.value.code == "InputControlConflict"


@pytest.mark.parametrize("drift", ["add", "delete", "rename", "bytes", "config", "auth", "profile"])
def test_current_control_drift_refused_and_retained(tmp_path, drift):
    source, _, task, note, profile, auth = rule_documents(tmp_path, role="Coding")
    prepare_documents(tmp_path, source, task, note, profile, auth)
    root = tmp_path / "task"
    original = (root / "work" / "AGENTS.md").read_bytes()
    if drift == "add":
        (root / "work" / "GEMINI.md").write_bytes(b"new rule")
    elif drift == "delete":
        (root / "work" / "AGENTS.md").unlink()
    elif drift == "rename":
        (root / "work" / "AGENTS.md").rename(root / "work" / "other.txt")
    elif drift == "bytes":
        (root / "work" / "AGENTS.md").write_bytes(b"changed rule")
    elif drift == "config":
        (root / "work" / ".cursor").mkdir()
        (root / "work" / ".cursor" / "cli.json").write_bytes(b"{}")
    elif drift == "auth":
        changed = json.loads(canonical(auth))
        changed["input_control_bindings"]["files"]["AGENTS.md"] = "0" * 64
        (root / "control" / "authorization.json").write_bytes(canonical(changed))
    else:
        changed = json.loads(canonical(profile))
        changed["toolchain_refs"] = ["changed"]
        (root / "control" / "deployment-profile.json").write_bytes(canonical(changed))
    with pytest.raises(TaskWorkspaceError):
        verify_documents(root, task, profile, auth)
    progress(root, task)
    result = collect(root)
    assert "InputControlConflict" in result["blockers"]
    assert result["host_observations"]["scope_status"] == "Fail"
    assert result["continuation"] is None
    assert (root / "control" / "snapshot" / "source" / "AGENTS.md").read_bytes() == original
    if drift == "bytes":
        assert (tmp_path / "result" / "candidate" / "AGENTS.md").read_bytes() == b"changed rule"


def test_staging_verification_precedes_seal_and_retains_copy_drift(tmp_path, monkeypatch):
    source, _, task, note, profile, auth = rule_documents(tmp_path)
    original = entry._verify_fixed_input_controls

    def change_then_verify(root, task, profile, auth, *, require_seal):
        assert require_seal is False
        assert not (root / "SEALED").exists()
        (root / "work" / "AGENTS.md").write_bytes(b"drift after copy")
        original(root, task, profile, auth, require_seal=require_seal)

    monkeypatch.setattr(entry, "_verify_fixed_input_controls", change_then_verify)
    with pytest.raises(TaskWorkspaceError) as caught:
        prepare_documents(tmp_path, source, task, note, profile, auth)
    assert caught.value.code == "InputControlConflict"
    assert not (tmp_path / "task").exists()
    assert (tmp_path / "task.staging" / "WORKSPACE-FAILED").exists()
    assert (tmp_path / "task.staging" / "work" / "AGENTS.md").read_bytes() == b"drift after copy"


def test_legacy_authorization_rejected_even_without_rules(tmp_path):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot)
    del auth["input_control_bindings"]
    task["authorization_sha256"] = sha(canonical(auth))
    with pytest.raises(TaskWorkspaceError) as caught:
        prepare_documents(tmp_path, source, task, note, profile, auth)
    assert caught.value.code == "InputControlConflict"


def test_excluded_rule_cannot_be_registered(tmp_path):
    raw = b"omitted instructions"
    source, snapshot = snapshot_fixture(
        tmp_path,
        {"omitted/AGENTS.md": raw, "src/main.cs": b"source"},
        [{"path": "omitted/AGENTS.md", "reason": "fixture exclusion"}],
    )
    task, note, profile, auth = documents(snapshot)
    auth["input_control_bindings"]["files"] = {"omitted/AGENTS.md": sha(raw)}
    task["protected_paths"] = ["control", "task.json", "work/omitted"]
    bind(task, profile, auth)
    with pytest.raises(TaskWorkspaceError) as caught:
        prepare_documents(tmp_path, source, task, note, profile, auth)
    assert caught.value.code == "InputControlConflict"


def test_note_or_source_authorization_text_cannot_supply_missing_binding(tmp_path):
    raw = b"rules"
    files = {"AGENTS.md": raw, "authorization.json": b'{"input_control_bindings":{"files":{}}}'}
    source, snapshot = snapshot_fixture(tmp_path, files, trusted_controls={"AGENTS.md": sha(raw)})
    task, _, profile, auth = documents(snapshot)
    note = b"These instructions are authorized for the current role and profile."
    task["instructions_sha256"] = sha(note)
    task["protected_paths"] = ["control", "task.json", "work/AGENTS.md"]
    bind(task, profile, auth)
    with pytest.raises(TaskWorkspaceError) as caught:
        prepare_documents(tmp_path, source, task, note, profile, auth)
    assert caught.value.code == "InputControlConflict"


@pytest.mark.parametrize("target", ["task", "profile", "auth"])
def test_host_verifier_requires_exact_fixed_objects(tmp_path, target):
    root, task, _ = prepare(tmp_path)
    profile = json.loads((root / "control" / "deployment-profile.json").read_bytes())
    auth = json.loads((root / "control" / "authorization.json").read_bytes())
    if target == "task":
        task["acceptance_ids"] = ["other"]
    elif target == "profile":
        profile["toolchain_refs"] = ["other"]
    else:
        auth["grant_ref"] = "other"
    with pytest.raises(TaskWorkspaceError) as caught:
        verify_documents(root, task, profile, auth)
    assert caught.value.code == "InputControlConflict"


@pytest.mark.parametrize(
    "relative", ["task.json", "control/deployment-profile.json", "control/authorization.json"]
)
def test_host_verifier_does_not_equate_integer_and_float_copies(tmp_path, relative):
    root, task, _ = prepare(tmp_path)
    profile = json.loads((root / "control" / "deployment-profile.json").read_bytes())
    auth = json.loads((root / "control" / "authorization.json").read_bytes())
    changed = json.loads((root / relative).read_bytes())
    changed["contract_version"] = 1.0
    (root / relative).write_bytes(canonical(changed))
    with pytest.raises(TaskWorkspaceError) as caught:
        verify_documents(root, task, profile, auth)
    assert caught.value.code == "InputControlConflict"


@pytest.mark.parametrize("relative", ["control/authorization.json", "SEALED"])
def test_host_verifier_detects_control_drift_during_inventory(tmp_path, monkeypatch, relative):
    root, task, _ = prepare(tmp_path)
    profile = json.loads((root / "control" / "deployment-profile.json").read_bytes())
    auth = json.loads((root / "control" / "authorization.json").read_bytes())
    original = entry._inventory

    def drift_after_inventory(path, limit, deadline):
        result = original(path, limit, deadline)
        if path == root / "work":
            (root / relative).write_bytes(b"changed during inventory")
        return result

    monkeypatch.setattr(entry, "_inventory", drift_after_inventory)
    with pytest.raises(TaskWorkspaceError) as caught:
        verify_documents(root, task, profile, auth)
    assert caught.value.code == (
        "TaskBindingMismatch" if relative == "SEALED" else "InputControlConflict"
    )


@pytest.mark.parametrize(
    "relative",
    ["control/authorization.json", "control/deployment-profile.json", "control/TASK.md", "SEALED"],
)
def test_collect_detects_control_drift_before_publication(tmp_path, monkeypatch, relative):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    original = entry._host_artifact

    def drift_after_observations(*args, **kwargs):
        original(*args, **kwargs)
        (root / relative).write_bytes(b"changed after verification")

    monkeypatch.setattr(entry, "_host_artifact", drift_after_observations)
    with pytest.raises(TaskWorkspaceError) as caught:
        collect(root)
    assert caught.value.code == (
        "TaskBindingMismatch" if relative == "SEALED" else "ControlChanged"
    )
    assert not (tmp_path / "result").exists()
    assert (tmp_path / "result.staging" / "WORKSPACE-FAILED").exists()
    assert (root / relative).read_bytes() == b"changed after verification"


@pytest.mark.parametrize(
    "location,claim",
    [
        ("run", "correct"),
        ("run", "wrong"),
        ("task", "correct"),
        ("task", "wrong"),
        ("run", "null"),
        ("task", "null"),
        ("run", "worker"),
        ("task", "worker"),
        ("run", "missing"),
        ("run", "opaque"),
        ("run", "duplicate"),
        ("task", "duplicate"),
    ],
)
def test_normal_run_evidence_declarations_compare_each_digest(tmp_path, location, claim):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, receipt = receipt_fixture(root, task)
    raw = b"current observation\r\n\x00\xff"
    ref = "evidence.txt" if location == "run" else "out/evidence.txt"
    path = run / ref if location == "run" else root / ref
    path.write_bytes(raw)
    declared = sha(raw) if claim in {"correct", "worker", "duplicate"} else "0" * 64
    if claim == "null":
        declared = None
    if claim == "missing":
        ref = "missing.txt"
    if claim == "opaque":
        ref = "session://opaque-uid"
    receipt["evidence_refs"] = [
        {
            "ref": ref,
            "sha256": declared,
            "origin": "WorkerReported" if claim == "worker" else "HostObserved",
        }
    ]
    if claim == "duplicate":
        receipt["evidence_refs"].append({"ref": ref, "sha256": "0" * 64, "origin": "HostObserved"})
    original = canonical(receipt)
    (run / "run.json").write_bytes(original)
    result = collect(root, run_root=run)
    checks = json.loads(
        (tmp_path / "result" / "validation" / "run-evidence-checks.txt").read_bytes()
    )
    assert len(checks) == len(receipt["evidence_refs"])
    expected = {"correct": "Match", "wrong": "Mismatch", "missing": "Invalid", "duplicate": "Match"}
    assert checks[0]["check"] == expected.get(claim, "Unverified")
    assert ("RunEvidenceDigestMismatch" in result["blockers"]) == (claim in {"wrong", "duplicate"})
    assert ("RunEvidenceInvalid" in result["blockers"]) == (claim == "missing")
    if claim == "duplicate":
        assert checks[1]["check"] == "Mismatch"
    if claim in {"wrong", "duplicate"}:
        relative = "validation/current-run-evidence/" + ref
        assert (tmp_path / "result" / relative).read_bytes() == raw
        artifact = next(item for item in result["artifacts"] if item["path"] == relative)
        assert artifact["origin"] == "HostValidation"
        assert artifact["sha256"] == sha(raw)
        assert checks[-1]["declared_sha256"] == "0" * 64
        assert checks[-1]["actual_sha256"] == sha(raw)
    assert (tmp_path / "result" / "run" / "run.json").read_bytes() == original
    assert result["host_observations"]["transport_state"] == "Completed"
    assert result["worker_status"] == "Completed"
    assert result["management_decision"] is None
    assert result["continuation"]["last_test_run_id"] is None
    assert all(
        item["result"] != "Pass" for item in result["host_observations"]["acceptance_observations"]
    )
    if location == "run" and claim in {"worker", "null", "opaque"}:
        assert not (tmp_path / "result" / "run" / "evidence.txt").exists()


def test_wrong_normal_claim_invalidates_only_associated_test(tmp_path):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, receipt = receipt_fixture(root, task)
    for name in ("good.xml", "bad.xml"):
        (run / name).write_bytes(b'<testsuite tests="1" failures="0"/>')
    receipt["evidence_refs"] = [{"ref": "bad.xml", "sha256": "0" * 64, "origin": "HostObserved"}]
    receipt["test_observations"] = [
        {
            "test_run_id": run_id,
            "phase": "regression",
            "recipe_id": "synthetic-recipe",
            "toolchain_sha256": "3" * 64,
            "source_tree_sha256": task["snapshot_id"],
            "exit_code": 0,
            "start_utc": "2026-10-06T00:00:00Z",
            "end_utc": "2026-10-06T00:00:01Z",
            "origin": "HostObserved",
            "evidence_refs": [
                {"ref": name, "sha256": sha((run / name).read_bytes()), "origin": "HostObserved"}
            ],
        }
        for run_id, name in (("GOOD", "good.xml"), ("BAD", "bad.xml"))
    ]
    (run / "run.json").write_bytes(canonical(receipt))
    result = collect(root, run_root=run)
    assert {"RunEvidenceDigestMismatch", "TestEvidenceUnverified"} <= set(result["blockers"])
    assert result["continuation"]["last_test_run_id"] == "GOOD"
    assert result["host_observations"]["test_observations"] == receipt["test_observations"]


def test_current_mismatched_evidence_copy_race_keeps_failed_stage(tmp_path, monkeypatch):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, receipt = receipt_fixture(root, task)
    evidence = run / "evidence.txt"
    evidence.write_bytes(b"observed before copy")
    receipt["evidence_refs"] = [
        {"ref": "evidence.txt", "sha256": "0" * 64, "origin": "HostObserved"}
    ]
    (run / "run.json").write_bytes(canonical(receipt))
    original_copy = entry._copy

    def change_then_copy(path, target, stamp, deadline):
        if path == evidence:
            evidence.write_bytes(b"changed during copy")
        original_copy(path, target, stamp, deadline)

    monkeypatch.setattr(entry, "_copy", change_then_copy)
    with pytest.raises(TaskWorkspaceError) as caught:
        collect(root, run_root=run)
    assert caught.value.code == "InputChanged"
    assert not (tmp_path / "result").exists()
    assert (tmp_path / "result.staging" / "WORKSPACE-FAILED").exists()
    assert evidence.read_bytes() == b"changed during copy"


@pytest.mark.parametrize(
    "name", ["AGENTS.md", "nested/GEMINI.md", ".cursor/cli.json", ".gemini/settings.json"]
)
def test_input_control_conflict_not_executed(tmp_path, name):
    source, snapshot = snapshot_fixture(
        tmp_path, {name: b"synthetic conflict", "src/main.cs": b"source"}
    )
    task, note, profile, auth = documents(snapshot)
    with pytest.raises(TaskWorkspaceError, match="contract") as caught:
        prepare_task(
            snapshot_root=source,
            task_manifest=task,
            task_note=note,
            deployment_profile=profile,
            authorization=auth,
            task_root=tmp_path / "task",
        )
    assert caught.value.code == "InputControlConflict"
    assert not (tmp_path / "task").exists()


def test_coding_changes_rename_and_raw_candidate(tmp_path):
    root, task, _ = prepare(tmp_path)
    (root / "work" / "src" / "new.py").write_bytes(b"x = 1\r\n")
    (root / "work" / "old.txt").unlink()
    (root / "work" / "rename.txt").rename(root / "work" / "renamed.txt")
    (root / "work" / "blob.bin").write_bytes(b"\xff\x00binary")
    (root / "work" / "bom.txt").write_bytes(b"\xef\xbb\xbfnew\nno trailing LF")
    progress(root, task)
    result = collect(root)
    changes = {item["path"]: item for item in result["changes"]}
    assert changes["src/new.py"]["kind"] == "added"
    assert changes["old.txt"]["kind"] == "deleted"
    assert changes["renamed.txt"]["rename_from"] == "rename.txt"
    assert changes["blob.bin"]["before"] == {"bytes": 3, "sha256": sha(FILES["blob.bin"])}
    assert changes["blob.bin"]["after"]["sha256"] == sha(b"\xff\x00binary")
    assert result["host_observations"]["scope_status"] == "Pass"
    assert (
        tmp_path / "result" / "candidate" / "bom.txt"
    ).read_bytes() == b"\xef\xbb\xbfnew\nno trailing LF"
    assert json.loads((tmp_path / "result" / "changes.json").read_bytes()) == result["changes"]
    assert json.loads((tmp_path / "result" / "artifacts.json").read_bytes()) == result["artifacts"]
    for artifact in result["artifacts"]:
        raw = (tmp_path / "result" / artifact["path"]).read_bytes()
        assert artifact["bytes"] == len(raw) and artifact["sha256"] == sha(raw)


@pytest.mark.parametrize("edited,ambiguous", [(True, False), (False, True)])
def test_rename_does_not_guess(tmp_path, edited, ambiguous):
    files = {"one.txt": b"same", "two.txt": b"same"} if ambiguous else {"one.txt": b"same"}
    root, task, _ = prepare(tmp_path, files=files)
    (root / "work" / "one.txt").unlink()
    (root / "work" / "new.txt").write_bytes(b"edited" if edited else b"same")
    if ambiguous:
        (root / "work" / "two.txt").unlink()
    progress(root, task)
    result = collect(root)
    assert all(item["rename_from"] is None for item in result["changes"])


def test_review_cannot_modify_source_but_out_is_retained(tmp_path):
    root, task, snapshot = prepare(tmp_path, "Review")
    review_outputs(root, task, snapshot)
    (root / "work" / "src" / "main.cs").write_bytes(b"modified source")
    result = collect(root)
    assert result["worker_status"] == "Completed"
    assert result["host_observations"]["scope_status"] == "Fail"
    assert result["management_decision"] is None
    assert (tmp_path / "result" / "out" / "report.md").read_bytes().decode().startswith("# 中文")


def test_two_reviewer_copies_are_independent(tmp_path):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot, "Review")
    for name in ("one", "two"):
        prepare_task(
            snapshot_root=source,
            task_manifest=task,
            task_note=note,
            deployment_profile=profile,
            authorization=auth,
            task_root=tmp_path / name,
        )
    (tmp_path / "one" / "out" / "report.md").write_bytes(b"only one")
    assert not (tmp_path / "two" / "out" / "report.md").exists()
    assert not os.path.samefile(
        tmp_path / "one" / "work" / "old.txt", tmp_path / "two" / "work" / "old.txt"
    )


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "source-excluded",
        "duplicate",
        "denominator",
        "alias",
        "bad-line",
        "bad-json",
        "not-analyzed",
    ],
)
def test_coverage_and_finding_observations(tmp_path, kind):
    root, task, snapshot = prepare(tmp_path, "Review")
    review_outputs(root, task, snapshot)
    path = root / "out" / "coverage.json"
    coverage = json.loads(path.read_bytes())
    if kind == "missing":
        coverage["entries"].pop()
    elif kind == "source-excluded":
        next(item for item in coverage["entries"] if item["path"] == "src/main.cs")["state"] = (
            "Excluded"
        )
    elif kind == "duplicate":
        coverage["entries"].append(coverage["entries"][0])
    elif kind == "denominator":
        coverage["source_file_count"] -= 1
    elif kind == "alias":
        coverage["entries"][0]["path"] = "BLOB.BIN"
    elif kind == "not-analyzed":
        coverage["entries"][0]["state"] = "NotAnalyzed"
    elif kind == "bad-line":
        finding_path = root / "out" / "findings.json"
        finding = json.loads(finding_path.read_bytes())
        finding["findings"] = [
            {
                "id": "F1",
                "severity": "P2",
                "file": "src/main.cs",
                "line": 999,
                "evidence": "中文证据",
                "recommendation": "建议",
            }
        ]
        finding_path.write_bytes(canonical(finding))
    path.write_bytes(canonical(coverage))
    if kind == "bad-json":
        path.write_bytes(b'{"contract_version":1,"contract_version":1}')
    result = collect(root)
    expected = "Incomplete" if kind in {"source-excluded", "not-analyzed"} else "Invalid"
    assert result["host_observations"]["coverage_status"] == expected
    assert result["management_decision"] is None


def test_full_coverage_is_declaration_not_quality(tmp_path):
    root, task, snapshot = prepare(tmp_path, "Review")
    review_outputs(root, task, snapshot)
    result = collect(root)
    assert result["host_observations"]["coverage_status"] == "Complete"
    assert all(
        item["result"] == "Unrun" for item in result["host_observations"]["acceptance_observations"]
    )
    assert result["management_decision"] is None


@pytest.mark.parametrize(
    "field",
    [
        "task.json",
        "control/TASK.md",
        "control/authorization.json",
        "control/snapshot/source/old.txt",
    ],
)
def test_frozen_drift_is_rejected_or_scope_failed(tmp_path, field):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    (root / field).write_bytes(b"drift")
    if field in {"task.json", "control/snapshot/source/old.txt"}:
        with pytest.raises(TaskWorkspaceError):
            collect(root)
        assert not (tmp_path / "result").exists()
        assert (tmp_path / "result.staging" / "WORKSPACE-FAILED").exists()
    else:
        assert collect(root)["host_observations"]["scope_status"] == "Fail"


@pytest.mark.parametrize(
    "field,raw",
    [
        ("out/progress.json", b'{"contract_version":1,"contract_version":1}'),
        ("out/progress.json", b'{"x":NaN}'),
        ("out/progress.json", b"\xef\xbb\xbf{}"),
    ],
)
def test_worker_strict_json_failures_are_preserved(tmp_path, field, raw):
    root, _, _ = prepare(tmp_path)
    (root / field).write_bytes(raw)
    result = collect(root)
    assert result["worker_status"] is None
    assert result["host_observations"]["outputs_status"] == "Fail"
    assert (tmp_path / "result" / field).read_bytes() == raw


def test_partial_continuation_binds_artifact_bytes(tmp_path):
    root, task, _ = prepare(tmp_path)
    progress(root, task, "Partial", ["src/main.cs"])
    result = collect(root)
    continuation = result["continuation"]
    assert continuation["snapshot_id"] == task["snapshot_id"]
    assert continuation["task_manifest_sha256"] == sha(canonical(task))
    assert continuation["artifact_manifest_sha256"] == sha(
        (tmp_path / "result" / "artifacts.json").read_bytes()
    )
    assert continuation["remaining_paths"] == ["src/main.cs"]
    assert continuation["last_test_run_id"] is None
    assert continuation["session_id"] is None


def test_missing_required_output_is_not_completed(tmp_path):
    root, _, _ = prepare(tmp_path)
    result = collect(root)
    assert result["worker_status"] is None
    assert result["host_observations"]["outputs_status"] == "Fail"
    assert "RequiredOutputMissing" in result["blockers"]


@pytest.mark.parametrize("state", ["NotRun", "Completed", "Failed", "TimedOut"])
def test_run_receipt_fixture_keeps_transport_separate(tmp_path, state):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, _ = receipt_fixture(root, task, state)
    result = collect(root, run_root=run)
    assert result["host_observations"]["transport_state"] == state
    assert result["management_decision"] is None
    assert all(
        item["result"] != "Pass" for item in result["host_observations"]["acceptance_observations"]
    )


def test_unknown_launch_retains_receipt_and_tests_but_withholds_continuation(tmp_path):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, receipt = receipt_fixture(root, task, "Failed")
    receipt["launch_count"] = None
    receipt["blockers"] = ["LaunchUnverified"]
    observation = {
        "test_run_id": "reported-test",
        "phase": "regression",
        "recipe_id": "fixture",
        "toolchain_sha256": None,
        "source_tree_sha256": None,
        "exit_code": 0,
        "start_utc": None,
        "end_utc": None,
        "evidence_refs": [],
        "origin": "WorkerReported",
    }
    receipt["test_observations"] = [observation]
    raw = canonical(receipt)
    (run / "run.json").write_bytes(raw)
    result = collect(root, run_root=run)
    assert result["host_observations"]["transport_state"] == "Failed"
    assert result["host_observations"]["test_observations"] == [observation]
    assert {"LaunchUnverified", "TransportFailed", "TestEvidenceUnverified"} <= set(
        result["blockers"]
    )
    assert "RunReceiptInvalid" not in result["blockers"]
    assert result["continuation"] is None and result["management_decision"] is None
    assert (root.parent / "result/run/run.json").read_bytes() == raw


@pytest.mark.parametrize("state", ["NotRun", "Completed", "TimedOut", "Failed"])
@pytest.mark.parametrize("unknown_blocker", [False, True])
def test_null_launch_is_valid_only_for_failed_unverified(tmp_path, state, unknown_blocker):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, receipt = receipt_fixture(root, task, state)
    receipt["launch_count"] = None
    receipt["blockers"] = ["LaunchUnverified"] if unknown_blocker else []
    (run / "run.json").write_bytes(canonical(receipt))
    result = collect(root, run_root=run)
    valid = state == "Failed" and unknown_blocker
    assert ("RunReceiptInvalid" in result["blockers"]) is not valid
    assert result["host_observations"]["transport_state"] == "Failed"
    assert result["continuation"] is None


def test_blocked_plan_cannot_treat_null_launch_as_zero(tmp_path):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, receipt = receipt_fixture(root, task, "Failed")
    plan_path = root / "control/plan.json"
    plan = json.loads(plan_path.read_bytes())
    plan["preflight_status"] = "Blocked"
    plan["blockers"] = ["RuntimeAcceptanceUnverified"]
    plan_path.write_bytes(canonical(plan))
    receipt["plan_sha256"] = sha(canonical(plan))
    receipt["launch_count"] = None
    receipt["blockers"] = ["LaunchUnverified"]
    (run / "run.json").write_bytes(canonical(receipt))
    result = collect(root, run_root=run)
    assert "RunReceiptInvalid" in result["blockers"]
    assert result["continuation"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "OTHER"),
        ("plan_sha256", "0" * 64),
        ("launch_count", 2),
        ("launch_count", True),
        ("capture_uid", None),
        ("extra", 1),
    ],
)
def test_invalid_receipt_not_execution_proof(tmp_path, field, value):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, receipt = receipt_fixture(root, task)
    receipt[field] = value
    (run / "run.json").write_bytes(canonical(receipt))
    result = collect(root, run_root=run)
    assert result["host_observations"]["transport_state"] == "Failed"
    assert "RunReceiptInvalid" in result["blockers"]


def test_restore_capture_failures_not_hidden_by_completed(tmp_path):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, receipt = receipt_fixture(root, task)
    receipt["restore_state"] = "Failed"
    receipt["capture_state"] = "Incomplete"
    (run / "run.json").write_bytes(canonical(receipt))
    result = collect(root, run_root=run)
    assert {"RestoreFailed", "CaptureIncomplete"} <= set(result["blockers"])
    assert result["worker_status"] == "Completed"


@pytest.mark.parametrize(
    "origin,good_hash", [("WorkerReported", True), ("HostObserved", False), ("HostObserved", True)]
)
def test_test_evidence_origin_and_report_hash(tmp_path, origin, good_hash):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, receipt = receipt_fixture(root, task)
    (run / "junit.xml").write_bytes(b'<testsuite tests="1" failures="0"/>')
    receipt["test_observations"] = [
        {
            "test_run_id": "T1",
            "phase": "regression",
            "recipe_id": "registered-fixture",
            "toolchain_sha256": "3" * 64,
            "source_tree_sha256": task["snapshot_id"],
            "exit_code": 0,
            "start_utc": "2026-10-06T00:00:00Z",
            "end_utc": "2026-10-06T00:00:01Z",
            "evidence_refs": [
                {
                    "ref": "junit.xml",
                    "sha256": sha((run / "junit.xml").read_bytes()) if good_hash else "0" * 64,
                    "origin": origin,
                }
            ],
            "origin": origin,
        }
    ]
    (run / "run.json").write_bytes(canonical(receipt))
    result = collect(root, run_root=run)
    assert ("TestEvidenceUnverified" in result["blockers"]) == (
        origin != "HostObserved" or not good_hash
    )
    assert result["continuation"]["last_test_run_id"] == (
        "T1" if origin == "HostObserved" and good_hash else None
    )
    assert result["host_observations"]["test_observations"] == receipt["test_observations"]


def test_generated_roots_do_not_hide_new_source(tmp_path):
    root, task, _ = prepare(tmp_path)
    (root / "work" / ".venv").mkdir()
    (root / "work" / ".venv" / "generated.bin").write_bytes(b"cache")
    (root / "work" / "build").mkdir()
    (root / "work" / "build" / "new.cs").write_bytes(b"new source")
    progress(root, task)
    result = collect(root)
    assert "build/new.cs" in {item["path"] for item in result["changes"]}
    assert ".venv/generated.bin" not in {item["path"] for item in result["changes"]}
    artifact = next(
        item for item in result["artifacts"] if item["path"] == "generated/work/.venv/generated.bin"
    )
    assert artifact["origin"] == "WorkerOutput"
    assert not (tmp_path / "result" / "candidate" / ".venv").exists()
    assert (tmp_path / "result" / "validation" / "generated-roots.txt").read_text().find(
        "work/.venv"
    ) >= 0


def test_output_limit_failure_preserves_original(tmp_path):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot)
    task["source_output_bytes_limit"] = 300
    bind(task, profile, auth)
    root = tmp_path / "task"
    prepare_task(
        snapshot_root=source,
        task_manifest=task,
        task_note=note,
        deployment_profile=profile,
        authorization=auth,
        task_root=root,
    )
    (root / "out" / "large.bin").write_bytes(b"x" * 301)
    result = collect(root)
    assert result["host_observations"]["scope_status"] == "Fail"
    assert "ResourceLimitExceeded" in result["blockers"]
    assert (root / "out" / "large.bin").stat().st_size == 301


def test_hardlink_output_is_not_followed(tmp_path):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    other = tmp_path / "canary.bin"
    other.write_bytes(b"synthetic canary")
    os.link(other, root / "out" / "linked.bin")
    result = collect(root)
    assert result["host_observations"]["scope_status"] == "Fail"
    assert "PathRejected" in result["blockers"]
    assert not (tmp_path / "result" / "out" / "linked.bin").exists()


def test_fresh_roots_and_failed_publication_retained(tmp_path, monkeypatch):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    result = tmp_path / "result"
    original_rename = entry.os.rename

    def fail_result(source, target):
        if Path(target) == result:
            raise OSError("synthetic rename failure")
        return original_rename(source, target)

    monkeypatch.setattr(entry.os, "rename", fail_result)
    with pytest.raises(TaskWorkspaceError) as caught:
        collect(root)
    assert caught.value.code == "IoFailed"
    assert caught.value.__cause__ is not None
    assert not result.exists()
    assert (tmp_path / "result.staging" / "WORKSPACE-FAILED").exists()
    assert (tmp_path / "result.staging" / "result.json").exists()
    with pytest.raises(TaskWorkspaceError) as repeated:
        collect(root)
    assert repeated.value.code == "RootNotFresh"


def test_protected_source_scope_uses_logical_matching(tmp_path):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot)
    task["protected_paths"] = ["control", "task.json", "work/SRC"]
    bind(task, profile, auth)
    root = tmp_path / "task"
    prepare_task(
        snapshot_root=source,
        task_manifest=task,
        task_note=note,
        deployment_profile=profile,
        authorization=auth,
        task_root=root,
    )
    (root / "work" / "src" / "main.cs").write_bytes(b"changed")
    progress(root, task)
    assert collect(root)["host_observations"]["scope_status"] == "Fail"


def test_prepare_failure_keeps_staging_and_does_not_touch_source(tmp_path, monkeypatch):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot)
    real_copy = entry._copy

    def fail_work(path, target, stamp, deadline):
        if "work" in target.parts:
            raise OSError("synthetic copy failure")
        return real_copy(path, target, stamp, deadline)

    monkeypatch.setattr(entry, "_copy", fail_work)
    with pytest.raises(TaskWorkspaceError):
        prepare_task(
            snapshot_root=source,
            task_manifest=task,
            task_note=note,
            deployment_profile=profile,
            authorization=auth,
            task_root=tmp_path / "task",
        )
    assert not (tmp_path / "task").exists()
    assert (tmp_path / "task.staging" / "WORKSPACE-FAILED").exists()
    assert read_snapshot(snapshot_root=source) == snapshot


def test_rejected_work_inventory_does_not_fabricate_deletions(tmp_path):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    canary = tmp_path / "canary.bin"
    canary.write_bytes(b"synthetic canary")
    os.link(canary, root / "work" / "linked.bin")
    result = collect(root)
    assert result["changes"] == []
    assert result["continuation"] is None
    assert result["host_observations"]["scope_status"] == "Fail"
    assert (root / "work" / "old.txt").read_bytes() == FILES["old.txt"]


def test_cumulative_limit_withholds_copies_and_continuation(tmp_path):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot)
    task["source_output_bytes_limit"] = 400
    bind(task, profile, auth)
    root = tmp_path / "task"
    prepare_task(
        snapshot_root=source,
        task_manifest=task,
        task_note=note,
        deployment_profile=profile,
        authorization=auth,
        task_root=root,
    )
    progress(root, task)
    (root / "out" / "large.bin").write_bytes(b"x" * 250)
    result = collect(root)
    assert result["host_observations"]["scope_status"] == "Fail"
    assert result["continuation"] is None
    assert not (tmp_path / "result" / "candidate").exists()
    assert not (tmp_path / "result" / "out").exists()
    assert (root / "out" / "large.bin").stat().st_size == 250


def test_real_junction_collect_rejected_without_following(tmp_path):
    import _winapi

    root, task, _ = prepare(tmp_path)
    progress(root, task)
    canary = tmp_path / "canary"
    canary.mkdir()
    (canary / "outside.txt").write_bytes(b"synthetic canary")
    _winapi.CreateJunction(str(canary), str(root / "out" / "junction"))
    result = collect(root)
    assert result["host_observations"]["scope_status"] == "Fail"
    assert "PathRejected" in result["blockers"]
    assert not (tmp_path / "result" / "out" / "junction").exists()
    assert (canary / "outside.txt").read_bytes() == b"synthetic canary"


@pytest.mark.parametrize("target", ["task", "result"])
def test_output_parent_junction_rejected_before_writes(tmp_path, target):
    import _winapi

    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot)
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    _winapi.CreateJunction(str(real), str(alias))
    if target == "task":
        with pytest.raises(TaskWorkspaceError) as caught:
            prepare_task(
                snapshot_root=source,
                task_manifest=task,
                task_note=note,
                deployment_profile=profile,
                authorization=auth,
                task_root=alias / "task",
            )
    else:
        root = tmp_path / "task"
        prepare_task(
            snapshot_root=source,
            task_manifest=task,
            task_note=note,
            deployment_profile=profile,
            authorization=auth,
            task_root=root,
        )
        with pytest.raises(TaskWorkspaceError) as caught:
            collect(root, result=alias / "result")
    assert caught.value.code == "PathRejected"
    assert list(real.iterdir()) == []


def test_unicode_source_names_remain_exact(tmp_path):
    files = {"中文/说明.cs": b"source\r\n", "e\u0301.txt": b"nfd\x00"}
    root, task, _ = prepare(tmp_path, files=files)
    progress(root, task)
    result = collect(root)
    assert (tmp_path / "result" / "candidate" / "e\u0301.txt").read_bytes() == b"nfd\x00"
    assert "candidate/e\u0301.txt" in {item["path"] for item in result["artifacts"]}


def test_946_sources_963_files_do_not_hide_directory_denominator(tmp_path):
    files = {f"src/f{number:03d}.cs": b"source\n" for number in range(946)}
    files.update({f"aux{number:02d}.txt": b"auxiliary" for number in range(17)})
    root, task, snapshot = prepare(tmp_path, "Review", files=files)
    assert len(snapshot["source_paths"]) == 946
    assert sum(item["kind"] == "file" for item in snapshot["entries"]) == 963
    assert len(snapshot["entries"]) == 964  # Explicit src directory also counts.
    review_outputs(root, task, snapshot)
    result = collect(root)
    assert result["host_observations"]["coverage_status"] == "Complete"
    assert result["management_decision"] is None


def test_review_exclusions_preserve_source_denominator(tmp_path):
    files = {"src/kept.cs": b"source", "src/excluded.cs": b"excluded", "helper.txt": b"helper"}
    source, snapshot = snapshot_fixture(
        tmp_path, files, [{"path": "src/excluded.cs", "reason": "fixture exclusion"}]
    )
    task, note, profile, auth = documents(snapshot, "Review")
    root = tmp_path / "task"
    prepare_task(
        snapshot_root=source,
        task_manifest=task,
        task_note=note,
        deployment_profile=profile,
        authorization=auth,
        task_root=root,
    )
    review_outputs(root, task, snapshot)
    path = root / "out" / "coverage.json"
    coverage = json.loads(path.read_bytes())
    assert coverage["source_file_count"] == 2
    next(item for item in coverage["entries"] if item["path"] == "src/excluded.cs")["state"] = (
        "Excluded"
    )
    path.write_bytes(canonical(coverage))
    result = collect(root)
    assert result["host_observations"]["coverage_status"] == "Incomplete"
    assert result["continuation"]["remaining_paths"] == ["src/excluded.cs"]


def test_reproduce_and_regression_records_both_retained(tmp_path):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, receipt = receipt_fixture(root, task)
    for run_id, phase, code in (("T1", "reproduce", 1), ("T2", "regression", 0)):
        raw = f"synthetic {phase} exit {code}".encode()
        (run / f"{run_id}.txt").write_bytes(raw)
        receipt["test_observations"].append(
            {
                "test_run_id": run_id,
                "phase": phase,
                "recipe_id": "registered-fixture",
                "toolchain_sha256": "3" * 64,
                "source_tree_sha256": task["snapshot_id"],
                "exit_code": code,
                "start_utc": "2026-10-06T00:00:00Z",
                "end_utc": "2026-10-06T00:00:01Z",
                "evidence_refs": [
                    {"ref": f"{run_id}.txt", "sha256": sha(raw), "origin": "HostObserved"}
                ],
                "origin": "HostObserved",
            }
        )
    (run / "run.json").write_bytes(canonical(receipt))
    result = collect(root, run_root=run)
    assert [item["exit_code"] for item in result["host_observations"]["test_observations"]] == [
        1,
        0,
    ]
    assert result["continuation"]["last_test_run_id"] == "T2"
    assert result["management_decision"] is None


def test_case_only_rename_does_not_drop_bytes(tmp_path):
    root, task, _ = prepare(tmp_path, files={"original.txt": b"original"})
    (root / "work" / "original.txt").rename(root / "work" / "ORIGINAL.txt")
    progress(root, task)
    result = collect(root)
    added = next(item for item in result["changes"] if item["kind"] == "added")
    assert added["path"] == "ORIGINAL.txt" and added["rename_from"] == "original.txt"
    assert (tmp_path / "result" / "candidate" / "ORIGINAL.txt").read_bytes() == b"original"


def test_original_source_under_cache_name_is_not_excluded(tmp_path):
    root, task, _ = prepare(tmp_path, files={".venv/original.txt": b"synthetic frozen source"})
    (root / "work" / ".venv" / "original.txt").write_bytes(b"modified frozen source")
    progress(root, task)
    result = collect(root)
    assert result["changes"][0]["path"] == ".venv/original.txt"
    assert (
        tmp_path / "result" / "candidate" / ".venv" / "original.txt"
    ).read_bytes() == b"modified frozen source"


def cursor_host_fixture(tmp_path):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot)
    # Identity fixture only; C receipt/native-config acceptance is not asserted.
    raw_config = b'{ "offline_fixture": true }\r\n'
    opaque_receipt = {"configuration": {"cursor_project": {"sha256": sha(raw_config)}}}
    profile["host"] = "cursor"
    profile["receipt_sha256"] = sha(canonical(opaque_receipt))
    task["protected_paths"] = [".cursor", "control", "task.json"]
    bind(task, profile, auth)
    root = tmp_path / "task"
    prepare_task(
        snapshot_root=source,
        task_manifest=task,
        task_note=note,
        deployment_profile=profile,
        authorization=auth,
        task_root=root,
    )
    # Only the fixed post-prepare C/D additions; no native config is read.
    (root / "control" / "deployment-receipt.json").write_bytes(canonical(opaque_receipt))
    plan = {
        "contract_version": 1,
        "task_id": task["task_id"],
        "task_manifest_sha256": sha(canonical(task)),
        "deployment_receipt_sha256": profile["receipt_sha256"],
        "host": "cursor",
        "route": {"model": "grok-4.7-high", "effort": None},
        "execution_boundary": task["execution_boundary"],
        "capabilities": task["capabilities"],
        "preflight_status": "Ready",
        "blockers": [],
        "evidence_refs": [],
    }
    (root / "control" / "plan.json").write_bytes(canonical(plan))
    (root / ".cursor").mkdir()
    (root / ".cursor" / "cli.json").write_bytes(raw_config)
    progress(root, task)
    return root, task, raw_config


def test_cursor_fixed_host_control_is_retained_as_host_validation(tmp_path):
    root, _, raw = cursor_host_fixture(tmp_path)
    result = collect(root)
    assert result["host_observations"]["scope_status"] == "Pass"
    artifact = next(item for item in result["artifacts"] if item["path"] == "host/.cursor/cli.json")
    assert artifact["origin"] == "HostValidation" and artifact["sha256"] == sha(raw)
    assert (tmp_path / "result" / artifact["path"]).read_bytes() == raw
    assert all(not item["path"].startswith(".cursor") for item in result["changes"])


@pytest.mark.parametrize("host", ["agy", "cursor"])
@pytest.mark.parametrize(
    "state", ["prepare_only", "receipt_only", "plan_only", "cursor_only", "full_plan"]
)
def test_control_publication_requires_a_complete_plan(tmp_path, host, state):
    if host == "cursor":
        root, task, _ = cursor_host_fixture(tmp_path)
    else:
        root, task, _ = prepare(tmp_path)
        progress(root, task)
        receipt_fixture(root, task)
    retained = tmp_path / "retained-controls"
    retained.mkdir()
    for name, keep in (
        ("deployment-receipt.json", state in {"receipt_only", "full_plan"}),
        ("plan.json", state in {"plan_only", "full_plan"}),
    ):
        if not keep:
            (root / "control" / name).rename(retained / name)
    cursor = root / ".cursor"
    if host == "cursor" and state == "prepare_only":
        cursor.rename(retained / ".cursor")
    elif host == "agy" and state == "cursor_only":
        cursor.mkdir()
        (cursor / "cli.json").write_bytes(b"synthetic unexpected Host material")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    result = collect(root, run_root=None)
    valid = state in {"prepare_only", "full_plan"}
    assert result["host_observations"]["scope_status"] == ("Pass" if valid else "Fail")
    assert ("ControlChanged" in result["blockers"]) is not valid
    assert (result["continuation"] is None) is not valid
    assert result["management_decision"] is None and result["worker_status"] == "Completed"
    for path, raw in before.items():
        assert path.read_bytes() == raw


def test_null_receipt_file_does_not_become_pure_prepare(tmp_path):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot)
    # B owns presence/digest observation, while C owns the full receipt schema.
    profile["receipt_sha256"] = sha(b"null")
    bind(task, profile, auth)
    root = tmp_path / "task"
    prepare_task(
        snapshot_root=source,
        task_manifest=task,
        task_note=note,
        deployment_profile=profile,
        authorization=auth,
        task_root=root,
    )
    progress(root, task)
    (root / "control/deployment-receipt.json").write_bytes(b"null")
    result = collect(root, run_root=None)
    assert "ControlChanged" in result["blockers"]
    assert result["host_observations"]["scope_status"] == "Fail"
    assert result["continuation"] is None


@pytest.mark.parametrize("mutation", ["changed", "missing", "extra", "receipt-drift"])
def test_cursor_host_control_drift_is_scope_failure(tmp_path, mutation):
    root, _, _ = cursor_host_fixture(tmp_path)
    if mutation == "changed":
        (root / ".cursor" / "cli.json").write_bytes(b"changed")
    elif mutation == "missing":
        (root / ".cursor" / "cli.json").unlink()
    elif mutation == "extra":
        (root / ".cursor" / "other.json").write_bytes(b"unexpected")
    else:
        (root / "control" / "deployment-receipt.json").write_bytes(canonical({"other": True}))
    result = collect(root)
    assert result["host_observations"]["scope_status"] == "Fail"
    assert "ControlChanged" in result["blockers"]
    assert result["continuation"] is None


def test_unknown_control_member_remains_scope_failure(tmp_path):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    (root / "control" / "unknown.json").write_bytes(b"{}")
    result = collect(root)
    assert result["host_observations"]["scope_status"] == "Fail"
    assert not any("unknown.json" in item["path"] for item in result["artifacts"])


def test_run_unreferenced_files_are_not_read_or_collected(tmp_path, monkeypatch):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, _ = receipt_fixture(root, task)
    unreferenced = run / "unreferenced-settings.json"
    unreferenced.write_bytes(b"synthetic unrelated material")
    original_lstat = Path.lstat

    def guarded_lstat(path, *args, **kwargs):
        if path == unreferenced:
            raise AssertionError("unreferenced run material must not be inspected")
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", guarded_lstat)
    result = collect(root, run_root=run)
    assert not any("unreferenced" in item["path"] for item in result["artifacts"])


def test_missing_c_receipt_is_not_a_trusted_plan_addition(tmp_path):
    root, task, _ = prepare(tmp_path)
    progress(root, task)
    run, _ = receipt_fixture(root, task)
    (root / "control" / "deployment-receipt.json").unlink()
    result = collect(root, run_root=run)
    assert result["host_observations"]["scope_status"] == "Fail"
    assert "ControlChanged" in result["blockers"]


def test_no_required_enforcement_claim_from_profile_text(tmp_path):
    source, snapshot = snapshot_fixture(tmp_path)
    task, note, profile, auth = documents(snapshot)
    task["execution_boundary"] = auth["execution_boundary"] = "required_enforced"
    bind(task, profile, auth)
    root = tmp_path / "task"
    prepare_task(
        snapshot_root=source,
        task_manifest=task,
        task_note=note,
        deployment_profile=profile,
        authorization=auth,
        task_root=root,
    )
    progress(root, task)
    result = collect(root)
    assert result["host_observations"]["transport_state"] == "NotRun"
    assert all(
        item["result"] == "Unrun" for item in result["host_observations"]["acceptance_observations"]
    )


@pytest.mark.parametrize(
    "fault", ["missing", "task", "plan", "sha", "excess", "supported", "noncanonical"]
)
def test_r08_v6_collector_rejects_invalid_single_observation(tmp_path, monkeypatch, fault):
    import test_station_task as fixtures

    from local_agent_bridge.bridge import agy_host

    case, path, pin, _document, spec = fixtures.configured_stable(tmp_path, monkeypatch)
    fixtures.install_stable_host(case, monkeypatch)
    outcome = fixtures.dispatch(path, pin, spec, execute=True)
    assert outcome["release_state"] == "Released", outcome
    root = Path(outcome["task_root"])
    run_root = Path(outcome["terminal_path"]).parent / "run"
    observation_path = run_root / agy_host.OBSERVATION_REF
    observation = json.loads(observation_path.read_bytes())
    run = json.loads((run_root / "run.json").read_bytes())
    if fault == "missing":
        observation_path.unlink()
    elif fault == "sha":
        observation_path.write_bytes(observation_path.read_bytes() + b" ")
    else:
        if fault == "task":
            observation["task_id"] = "foreign"
        elif fault == "plan":
            observation["plan_sha256"] = "b" * 64
        elif fault == "excess":
            observation["diagnostics"].append(observation["diagnostics"][0])
        elif fault == "supported":
            observation["diagnostics"][0]["cleanup"]["job_closed"] = None
        raw = (
            canonical(observation) if fault != "noncanonical" else json.dumps(observation).encode()
        )
        observation_path.write_bytes(raw)
        for evidence in run["evidence_refs"]:
            if evidence["ref"] == agy_host.OBSERVATION_REF:
                evidence["sha256"] = sha(raw)
        (run_root / "run.json").write_bytes(canonical(run))
    task = json.loads((root / "task.json").read_bytes())
    blockers = []
    checked, _digest = entry._run_receipt(root, run_root, task, sha(canonical(task)), blockers)
    assert checked is None and "RunReceiptInvalid" in blockers


def test_r08_unsupported_is_valid_run_with_compatibility_blocker(tmp_path, monkeypatch):
    import test_agy_host as probes
    import test_station_task as fixtures

    case, path, pin, _document, spec = fixtures.configured_stable(tmp_path, monkeypatch)
    fixtures.install_stable_host(
        case, monkeypatch, help_text=probes.HELP.replace(b"--effort", b"--unused")
    )
    outcome = fixtures.dispatch(path, pin, spec, execute=True)
    root = Path(outcome["task_root"])
    run_root = Path(outcome["terminal_path"]).parent / "run"
    task = json.loads((root / "task.json").read_bytes())
    blockers = []
    checked, _digest = entry._run_receipt(root, run_root, task, sha(canonical(task)), blockers)
    assert checked is not None and checked["launch_count"] == 0
    assert "RequiredParametersMissing" in blockers
