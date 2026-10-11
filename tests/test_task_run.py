"""Synthetic trusted-input and fake-launch tests, never real host/config/key IO."""

from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_agent_bridge.bridge import slice_run, task_workspace
from local_agent_bridge.bridge import task_run as runner
from local_agent_bridge.capture.session import SessionStore

KEY = bytes(range(32))
H = "a" * 64


def canonical(value):
    return runner._canonical(value)


def digest(value):
    return runner._digest(canonical(value))


def observed(ref="fixture/r-acceptance.json"):
    return {"ref": ref, "sha256": H, "origin": "HostObserved"}


def identity(path):
    return {"path": str(path), "sha256": slice_run._sha256_file(path)}


def write_json(path, value):
    path.write_bytes(canonical(value))


def prepare_snapshot(root):
    """The same public A format retained by B, from a tiny synthetic tree."""
    raw = (root / "work" / "source.py").read_bytes()
    entry = {"path": "source.py", "kind": "file", "bytes": len(raw), "sha256": runner._digest(raw)}
    inventory = {"contract_version": 1, "entries": [entry]}
    selection = {"source_paths": ["source.py"], "excluded_paths": []}
    snapshot = {
        "contract_version": 1,
        "snapshot_id": digest(inventory),
        "source": {"kind": "zip", "identity": H, "selection_sha256": digest(selection)},
        "entries": [{**entry, "git_mode": None}],
        **selection,
    }
    target = root / "control" / "snapshot"
    (target / "source").mkdir(parents=True)
    (target / "source" / "source.py").write_bytes(raw)
    write_json(target / "manifest.json", snapshot)
    (target / "SEALED").write_bytes(digest(snapshot).encode("ascii"))
    return snapshot


def prepare(
    tmp_path,
    monkeypatch,
    *,
    host="agy",
    role="Coding",
    caps=None,
    boundary="declared_scope",
    accepted=True,
    actual_b=False,
    files=None,
    publish=True,
    note=None,
):
    """The test itself explicitly injects trust; nothing is a real grant or R."""
    caps = caps or {"execute": True, "web_reference": False, "prepare_dependencies": False}
    parent = tmp_path / "tasks"
    root = parent / "fixture"
    parent.mkdir()
    if not actual_b:
        for name in ("control", "work", "out", "scratch"):
            (root / name).mkdir(parents=True)
    trust = tmp_path / "trusted"
    trust.mkdir()
    note = "离线工程任务\n".encode() if note is None else note
    if not publish and not actual_b:
        raise ValueError("unpublished fixtures require an actual A snapshot")
    files = {"source.py": b"n = 0\r\n"} if files is None else files
    rules = {
        path: runner._digest(raw)
        for path, raw in files.items()
        if path.rsplit("/", 1)[-1] in {"AGENTS.md", "GEMINI.md", "CLAUDE.md", ".cursorrules"}
    }
    if actual_b:
        package = tmp_path / "input.zip"
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, raw in files.items():
                archive.writestr(path, raw)
        snapshot_root = tmp_path / "input-snapshot"
        snapshot = runner.task_input.import_snapshot(
            source={
                "kind": "zip",
                "path": str(package),
                "sha256": runner._digest(package.read_bytes()),
                "strip_prefix": None,
            },
            policy={
                "source_paths": sorted(path for path in files if path.endswith(".py")),
                "excluded_paths": [],
                "sensitive_paths": [],
                "trusted_control_files": rules,
            },
            snapshot_root=snapshot_root,
        )
    else:
        (root / "control" / "TASK.md").write_bytes(note)
        (root / "work" / "source.py").write_bytes(files["source.py"])
        snapshot = prepare_snapshot(root)
    host_root = tmp_path / "fake-host"
    host_root.mkdir()
    host_entry = host_root / ("agy.exe" if host == "agy" else "agent.ps1")
    host_entry.write_bytes(b"offline fake entry, never execute")
    bridge_entry = host_root / "local-agent-bridge.exe"
    bridge_entry.write_bytes(b"fake Bridge entry")
    marker = host_root / "backend.json"
    marker.write_bytes(b'{"version":"offline-fake"}')
    executable = host_root / "python.exe"
    executable.write_bytes(b"registered fake toolchain identity only")
    settings = host_root / "settings.json"
    settings.write_bytes(b'{ "user": 7 }\r\n')
    shell = host_root / "pwsh.exe"
    shell.write_bytes(b"fake launch shell identity")
    monkeypatch.setattr(slice_run, "_pwsh_path", lambda: str(shell))
    config = {"agy_settings": identity(settings), "cursor_global": None, "cursor_project": None}
    if host == "cursor":
        project_raw = b'{"permissions":{"allow":["Read(work/**)"],"deny":["Mcp(*)"]}}'
        project = root / ".cursor" / "cli.json"
        config = {
            "agy_settings": None,
            "cursor_global": {"path": str(host_root / "global.json"), "sha256": None},
            "cursor_project": {"path": str(project), "sha256": runner._digest(project_raw)},
        }
    write_roots = ["out", "scratch", "work"] if role == "Coding" else ["out", "scratch"]
    profile = {
        "contract_version": 1,
        "id": "fixture-deployment",
        "host": host,
        "receipt_sha256": H,
        "roles": ["Coding", "Review"],
        "supported_capabilities": {key: True for key in runner._CAPABILITIES},
        "execution_modes": ["declared_scope", "required_enforced"],
        "read_roots": ["control", "out", "scratch", "work"],
        "write_roots": ["out", "scratch", "work"],
        "toolchain_refs": ["fixture-python"],
        "enforcement": {
            "method": "fake-test-evidence-only",
            "file_scope": "Enforced" if boundary == "required_enforced" else "Declared",
            "network_scope": "Enforced" if boundary == "required_enforced" else "Unverified",
            "evidence_refs": [observed()],
        },
    }
    receipt = {
        "contract_version": 1,
        "id": profile["id"],
        "host": host,
        "adapter": host + "_task_v1",
        "workspace_parent": str(parent),
        "bridge": {
            "version": "fixture-not-deployed",
            "entry": identity(bridge_entry),
            "wheel_sha256": H,
            "product_files": sorted(
                (identity(path) for path in runner._runtime_files()),
                key=lambda item: item["path"].encode(),
            ),
        },
        "host_entry": identity(host_entry),
        "launch_shell": identity(shell) if host == "cursor" else None,
        "host_version": "fixture-not-current-evidence",
        "host_identity_files": [identity(marker)],
        "configuration": config,
        "profile_fields_sha256": H,
        "toolchains": [
            {
                "ref": "fixture-python",
                "identity_files": [identity(executable)],
                "recipe_refs": ["fixture-test"],
            }
        ],
        "runtime_acceptances": [],
        "provenance_refs": [observed("fixture/deployment.json")],
    }
    auth = {
        "contract_version": 1,
        "task_id": "fixture-task",
        "grant_ref": "fake-management-injection-no-real-authority",
        "receipt_sha256": H,
        "capabilities": dict(caps),
        "execution_boundary": boundary,
        "read_roots": profile["read_roots"].copy(),
        "write_roots": write_roots.copy(),
        "web_scope": "fixture-readonly-query" if caps["web_reference"] else None,
        "dependency_scope": "fixture-locked-scratch" if caps["prepare_dependencies"] else None,
        "input_control_bindings": {"task_fields_sha256": H, "files": rules},
    }
    task = {
        "contract_version": 1,
        "task_id": auth["task_id"],
        "role": role,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_manifest_sha256": digest(snapshot),
        "instructions_sha256": runner._digest(note),
        "deployment_profile_id": profile["id"],
        "deployment_profile_sha256": H,
        "authorization_sha256": H,
        "capabilities": dict(caps),
        "execution_boundary": boundary,
        "read_roots": profile["read_roots"].copy(),
        "write_roots": write_roots.copy(),
        "protected_paths": sorted(
            ["control", "task.json", "work/vendor"]
            + ["work/" + path for path in rules]
            + ([".cursor"] if host == "cursor" else [])
        ),
        "required_outputs": ["out/progress.json"],
        "acceptance_ids": ["TEST-01"],
        "deadline_seconds": 12,
        "source_output_bytes_limit": 100000,
    }
    case = SimpleNamespace(
        root=root,
        trust=trust,
        receipt=receipt,
        profile=profile,
        auth=auth,
        task=task,
        settings=settings,
        host_entry=host_entry,
        store=SessionStore(KEY, root=tmp_path / "fake-sessions"),
        calls=[],
        accepted=accepted,
        snapshot=snapshot,
    )
    monkeypatch.setattr(slice_run, "_protect_directory", lambda _path: None)
    monkeypatch.setattr(slice_run, "_session_store", lambda: case.store)
    sync(case, refresh_r=True, persist_task=not actual_b)
    if actual_b and publish:
        assert (
            task_workspace.prepare_task(
                snapshot_root=snapshot_root,
                task_manifest=task,
                task_note=note,
                deployment_profile=profile,
                authorization=auth,
                task_root=root,
            )
            == task
        )
    if host == "cursor" and publish:
        (root / ".cursor").mkdir()
        project.write_bytes(project_raw)
    return case


def sync(case, *, refresh_r=False, persist_task=True):
    receipt, profile = case.receipt, case.profile
    receipt["profile_fields_sha256"] = digest(
        {key: value for key, value in profile.items() if key != "receipt_sha256"}
    )
    binding = digest(
        {
            key: value
            for key, value in receipt.items()
            if key not in {"runtime_acceptances", "provenance_refs"}
        }
    )
    if refresh_r:
        required = {"R-RUNTIME-01"}
        if case.task["capabilities"]["web_reference"]:
            required.add("WEB-01")
        if case.task["capabilities"]["prepare_dependencies"]:
            required.add("DEPS-01")
        if case.task["execution_boundary"] == "required_enforced":
            required |= {"BOUNDARY-02", "BOUNDARY-03", "NETWORK-01"}
        receipt["runtime_acceptances"] = (
            [
                {
                    "role": case.task["role"],
                    "capabilities": case.task["capabilities"].copy(),
                    "execution_boundary": case.task["execution_boundary"],
                    "receipt_binding_sha256": binding,
                    "status": "Accepted",
                    "gates": [
                        {
                            "id": key,
                            "result": "Pass",
                            "evidence_refs": [observed(f"fixture/{key}.json")],
                        }
                        for key in sorted(required)
                    ],
                    "management_acceptance_ref": observed("fixture/management.json"),
                }
            ]
            if case.accepted
            else []
        )
    profile["receipt_sha256"] = case.auth["receipt_sha256"] = digest(receipt)
    case.task["deployment_profile_sha256"] = digest(profile)
    case.auth["input_control_bindings"]["task_fields_sha256"] = digest(
        {key: value for key, value in case.task.items() if key != "authorization_sha256"}
    )
    case.task["authorization_sha256"] = digest(case.auth)
    bundle = {
        "deployment_receipt": receipt,
        "deployment_profile": profile,
        "authorization": case.auth,
    }
    case.expected = digest(bundle)
    for filename, value in (
        ("deployment-receipt.json", receipt),
        ("deployment-profile.json", profile),
        ("authorization.json", case.auth),
    ):
        write_json(case.trust / filename, value)
        if persist_task and filename != "deployment-receipt.json":
            write_json(case.root / "control" / filename, value)
    if persist_task:
        write_json(case.root / "task.json", case.task)
        (case.root / "SEALED").write_bytes(digest(case.task).encode("ascii"))


def plan(case):
    return runner.plan_task(
        task_root=case.root,
        host=case.receipt["host"],
        trusted_control_root=case.trust,
        trusted_inputs_sha256=case.expected,
    )


def first_observation_receipt(case):
    """Synthetic v2 declaration, without a fake backend or accepted R."""
    case.receipt.update(
        contract_version=2,
        host_composition=runner.FIRST_OBSERVATION_COMPOSITION.copy(),
        host_identity_files=[],
        runtime_acceptances=[],
    )


def run(case, frozen, target, *, execute=False):
    return runner.run_task(
        task_root=case.root,
        plan=frozen,
        run_root=target,
        trusted_control_root=case.trust,
        trusted_inputs_sha256=case.expected,
        execute=execute,
    )


class FakeProcess:
    def __init__(self, *, exit_code=0, wait_error=None):
        self.pid = 9183
        self.stdout = io.BytesIO(
            b'{"phase":"reproduce","exit_code":1}\n{"phase":"regression","exit_code":0}\n'
        )
        self.stderr = io.BytesIO(b"synthetic stderr\n")
        self.returncode = exit_code
        self.wait_error = wait_error
        self.closed = False
        self.terminated = False

    def wait(self, timeout=None):
        error, self.wait_error = self.wait_error, None
        if error is not None:
            raise error
        return self.returncode

    def terminate_once(self):
        self.terminated = True

    def close_job(self):
        self.closed = True


def fake_spawn(case, monkeypatch, behavior=None, **process_args):
    process = FakeProcess(**process_args)

    def spawn(argv, cwd, *, lifecycle, env=None):
        case.calls.append((argv, cwd))
        lifecycle.execution_state = "confirmed"
        lifecycle.pid = process.pid
        if behavior:
            behavior()
        return process

    monkeypatch.setattr(slice_run, "spawn_suspended_in_job", spawn)
    return process


@pytest.mark.parametrize("moment", ["after_read_observation", "after_path_observation"])
def test_reader_observes_changes_until_final_handle_check(tmp_path, monkeypatch, moment):
    """Review R01 equivalent: actual same-length writes, with mtime restored."""
    target = tmp_path / "spec.json"
    original, changed = b'{"v":1}', b'{"v":2}'
    target.write_bytes(original)
    before = target.stat()
    real_fstat, real_stat = os.fstat, Path.stat
    handles, facts = [], []

    def mutate():
        time.sleep(0.05)  # Separate actual filesystem change clocks in this fixture.
        target.write_bytes(changed)
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))

    def observe(descriptor):
        info = real_fstat(descriptor)
        handles.append(descriptor)
        facts.append({"call": len(handles), "ctime_ns": info.st_ctime_ns})
        if moment == "after_read_observation" and len(handles) == 2:
            mutate()
        return info

    def path_observation(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        if path == target and len(handles) == 2:
            # The reader must retain the same usable descriptor through this observation.
            real_fstat(handles[0])
            if moment == "after_path_observation":
                mutate()
        return info

    monkeypatch.setattr(os, "fstat", observe)
    monkeypatch.setattr(Path, "stat", path_observation)
    returned, code = None, None
    try:
        returned = runner.read_host_input_bytes(path=str(target))
    except runner.TaskRunError as error:
        code = error.code
    (tmp_path / "reader-facts.json").write_text(
        json.dumps(
            {
                "moment": moment,
                "code": code,
                "returned": None if returned is None else returned.decode(),
                "current": target.read_bytes().decode(),
                "mtime_restored": real_stat(target).st_mtime_ns == before.st_mtime_ns,
                "handle_observations": facts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    assert code == "InputChanged", facts
    assert returned is None and len(handles) == 3


@pytest.mark.parametrize("host", ["agy", "cursor"])
@pytest.mark.parametrize("role", ["Coding", "Review"])
@pytest.mark.parametrize(
    "caps",
    [
        {"execute": False, "web_reference": False, "prepare_dependencies": False},
        {"execute": False, "web_reference": True, "prepare_dependencies": False},
        {"execute": True, "web_reference": False, "prepare_dependencies": False},
        {"execute": True, "web_reference": True, "prepare_dependencies": False},
        {"execute": True, "web_reference": False, "prepare_dependencies": True},
        {"execute": True, "web_reference": True, "prepare_dependencies": True},
    ],
)
@pytest.mark.parametrize("boundary", ["declared_scope", "required_enforced"])
def test_plan_combinations_and_dry_run(tmp_path, monkeypatch, host, role, caps, boundary):
    case = prepare(tmp_path, monkeypatch, host=host, role=role, caps=caps, boundary=boundary)

    def forbidden(*_args, **_kwargs):
        pytest.fail("dry run accessed a key, configuration or process")

    monkeypatch.setattr(slice_run, "_session_store", forbidden)
    monkeypatch.setattr(runner, "_read_configuration", forbidden)
    monkeypatch.setattr(slice_run, "spawn_suspended_in_job", forbidden)
    frozen = plan(case)
    assert frozen["preflight_status"] == "Ready"
    assert frozen["route"] == runner._ROUTES[host]
    result = run(case, frozen, tmp_path / "dry")
    assert (
        result["transport_state"],
        result["capture_state"],
        result["restore_state"],
        result["launch_count"],
    ) == ("NotRun", "NotRun", "NotRun", 0)
    assert case.settings.read_bytes() == b'{ "user": 7 }\r\n'
    assert (tmp_path / "dry" / "run.json").read_bytes() == canonical(result)
    assert result["test_observations"] == []


def test_request_states_the_daily_coding_scope(tmp_path, monkeypatch):
    case = prepare(tmp_path, monkeypatch)
    context = {
        "task": case.task,
        "bundle": {"authorization": case.auth},
        "note": (case.root / "control" / "TASK.md").read_bytes(),
    }
    request = runner._request(context)

    assert "Coding may inspect authorized files, verify hashes" in request
    assert "create/edit/delete/rename authorized ordinary copies" in request
    assert "necessary local tests, builds, diagnostics, authorized helper scripts" in request
    assert "No credentials, host changes, publishing, other tasks" in request
    assert "declared_scope is not an OS sandbox" in request


@pytest.mark.parametrize("host", ["agy", "cursor"])
def test_missing_task_r_blocks_even_explicit_execute(tmp_path, monkeypatch, host):
    case = prepare(tmp_path, monkeypatch, host=host, accepted=False)
    monkeypatch.setattr(slice_run, "_session_store", lambda: pytest.fail("key requested"))
    monkeypatch.setattr(
        slice_run, "spawn_suspended_in_job", lambda *_: pytest.fail("host requested")
    )
    frozen = plan(case)
    assert frozen["preflight_status"] == "Blocked"
    assert "RuntimeAcceptanceUnverified" in frozen["blockers"]
    result = run(case, frozen, tmp_path / "not-started", execute=True)
    assert result["launch_count"] == 0
    assert result["transport_state"] == "NotRun"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c.task.update(contract_version=True),
        lambda c: c.task["capabilities"].update(execute=1),
        lambda c: c.task["capabilities"].update(execute=False, prepare_dependencies=True),
        lambda c: c.task.update(role="Repair"),
        lambda c: c.task.update(write_roots=["control"]),
        lambda c: c.task.update(read_roots=["../work"]),
        lambda c: c.task.update(deadline_seconds=3601),
        lambda c: c.receipt.update(argv=["arbitrary"]),
        lambda c: c.receipt.update(adapter="other"),
        lambda c: c.profile.update(url="https://example.invalid"),
    ],
)
def test_closed_contract_rejections(tmp_path, monkeypatch, mutation):
    case = prepare(tmp_path, monkeypatch)
    mutation(case)
    sync(case)
    with pytest.raises(runner.TaskRunError) as error:
        plan(case)
    assert error.value.code
    assert str(tmp_path) not in str(error.value)
    assert not case.calls


@pytest.mark.parametrize(
    "field,value", [("status", "Unverified"), ("receipt_binding_sha256", "b" * 64)]
)
def test_r_not_accepted(tmp_path, monkeypatch, field, value):
    case = prepare(tmp_path, monkeypatch)
    case.receipt["runtime_acceptances"][0][field] = value
    sync(case)
    assert plan(case)["preflight_status"] == "Blocked"


@pytest.mark.parametrize(
    "change",
    [
        "reported",
        "hash_null",
        "gate_missing",
        "wrong_role",
        "scope_missing",
        "unsupported",
        "enforcement",
    ],
)
def test_r_authorization_and_boundary_gates(tmp_path, monkeypatch, change):
    case = prepare(
        tmp_path,
        monkeypatch,
        boundary="required_enforced",
        caps={"execute": True, "web_reference": True, "prepare_dependencies": True},
    )
    record = case.receipt["runtime_acceptances"][0]
    if change == "reported":
        record["management_acceptance_ref"]["origin"] = "WorkerReported"
    if change == "hash_null":
        record["gates"][0]["evidence_refs"][0]["sha256"] = None
    if change == "gate_missing":
        record["gates"] = record["gates"][:-1]
    if change == "wrong_role":
        record["role"] = "Review"
    if change == "scope_missing":
        case.auth["web_scope"] = None
    if change == "unsupported":
        case.auth["capabilities"]["web_reference"] = False
    if change == "enforcement":
        case.profile["enforcement"]["network_scope"] = "Unverified"
    sync(case)
    if change in {"scope_missing", "unsupported"}:
        # B rejects incompatible prepare authorization before C generates a Plan.
        with pytest.raises(runner.TaskRunError, match="AuthorizationMismatch"):
            plan(case)
    else:
        assert plan(case)["preflight_status"] == "Blocked"


@pytest.mark.parametrize("target", ["receipt", "note", "plan", "control"])
def test_plan_to_run_drift_refused_without_overwrite(tmp_path, monkeypatch, target):
    case = prepare(tmp_path, monkeypatch)
    frozen = plan(case)
    stored = (case.root / "control" / "plan.json").read_bytes()
    if target == "receipt":
        case.receipt["host_version"] = "changed"
        sync(case)
    if target == "note":
        (case.root / "control" / "TASK.md").write_bytes(b"changed")
    if target == "plan":
        frozen = copy.deepcopy(frozen)
        frozen["route"]["model"] = "other"
    if target == "control":
        (case.root / "control" / "deployment-receipt.json").write_bytes(b"{}")
    with pytest.raises(runner.TaskRunError):
        run(case, frozen, tmp_path / "refused", execute=True)
    assert (case.root / "control" / "plan.json").read_bytes() == stored
    assert not case.calls


@pytest.mark.parametrize("payload", [b'{"id":1,"id":2}', b'{"x":NaN}', b"{}\n", b"\xef\xbb\xbf{}"])
def test_strict_json_and_canonical_bytes(tmp_path, monkeypatch, payload):
    case = prepare(tmp_path, monkeypatch)
    (case.trust / "deployment-receipt.json").write_bytes(payload)
    with pytest.raises(runner.TaskRunError):
        plan(case)


def test_trusted_digest_and_root_boundary(tmp_path, monkeypatch):
    case = prepare(tmp_path, monkeypatch)
    with pytest.raises(runner.TaskRunError, match="TrustedInputChanged"):
        runner.plan_task(
            task_root=case.root,
            host="agy",
            trusted_control_root=case.trust,
            trusted_inputs_sha256="b" * 64,
        )
    with pytest.raises(runner.TaskRunError, match="TrustedRootRejected"):
        runner.plan_task(
            task_root=case.root,
            host="agy",
            trusted_control_root=case.root / "control",
            trusted_inputs_sha256=case.expected,
        )


@pytest.mark.parametrize("missing", ["product", "backend", "toolchain"])
def test_current_identity_missing_or_drift_is_blocked(tmp_path, monkeypatch, missing):
    case = prepare(tmp_path, monkeypatch)
    if missing == "product":
        case.receipt["bridge"]["product_files"] = case.receipt["bridge"]["product_files"][:-1]
        sync(case, refresh_r=True)
    if missing == "backend":
        Path(case.receipt["host_identity_files"][0]["path"]).write_bytes(b"drift")
    if missing == "toolchain":
        Path(case.receipt["toolchains"][0]["identity_files"][0]["path"]).write_bytes(b"drift")
    assert "RuntimeIdentityUnverified" in plan(case)["blockers"]


@pytest.mark.parametrize("host", ["agy", "cursor"])
def test_one_fake_launch_sealed_capture_and_business_unknown(tmp_path, monkeypatch, host):
    case = prepare(tmp_path, monkeypatch, host=host)
    original = case.settings.read_bytes()
    frozen = plan(case)
    process = fake_spawn(case, monkeypatch)
    result = run(case, frozen, tmp_path / "executed", execute=True)
    assert result["launch_count"] == len(case.calls) == 1
    assert result["transport_state"] == "Completed"
    assert result["capture_state"] == "Sealed"
    assert result["restore_state"] == ("Restored" if host == "agy" else "Unchanged")
    assert case.settings.read_bytes() == original and process.closed
    assert result["test_observations"] == []  # CLI event text is not a verified test recipe.
    sealed = case.store.reader(result["capture_uid"]).manifest()
    assert sealed["metadata"]["plan_sha256"] == digest(frozen)
    assert sealed["metadata"]["input_sources"]["task"] == "control/TASK.md"
    opaque = [item for item in result["evidence_refs"] if item["ref"].startswith("session:")]
    assert opaque == [
        {
            "ref": "session:" + result["capture_uid"],
            "sha256": digest(sealed),
            "origin": "HostObserved",
        }
    ]
    for item in result["evidence_refs"]:
        if item not in opaque:
            assert (
                runner._digest((tmp_path / "executed" / item["ref"]).read_bytes()) == item["sha256"]
            )
    raw_stdout = b"".join(case.store.reader(result["capture_uid"]).iter_stream("stdout"))
    assert b'"reproduce"' in raw_stdout and b'"regression"' in raw_stdout
    argv, cwd = case.calls[0]
    assert cwd == str(case.root)
    assert runner._ROUTES[host]["model"] in argv
    assert "management_decision" not in result


def test_existing_permissions_merged_and_original_bytes_restored(tmp_path, monkeypatch):
    case = prepare(tmp_path, monkeypatch)
    original = (
        b'{ "extra": false, "permissions": {"allow":["read_file(C:/Unrelated/**)"], '
        b'"deny":["write_file(C:/Unrelated/**)"]}}\r\n'
    )
    case.settings.write_bytes(original)
    case.receipt["configuration"]["agy_settings"] = identity(case.settings)
    sync(case, refresh_r=True)

    def inspect_patch():
        settings = json.loads(case.settings.read_bytes())
        assert settings["extra"] is False
        assert "write_file(C:/Unrelated/**)" in settings["permissions"]["deny"]
        assert "read_file(C:/Unrelated/**)" in settings["permissions"]["allow"]

    fake_spawn(case, monkeypatch, inspect_patch)
    assert run(case, plan(case), tmp_path / "merge", execute=True)["restore_state"] == "Restored"
    assert case.settings.read_bytes() == original


@pytest.mark.parametrize(
    "kind",
    [
        "deny",
        "config_drift",
        "semantic_drift",
        "layout_drift",
        "restore_failure",
        "capture_failure",
        "exit_failure",
        "timeout",
        "interrupt",
    ],
)
@pytest.mark.parametrize("seconds", [12, 3600])
def test_failure_lifecycle_preserves_counts_and_config(tmp_path, monkeypatch, kind, seconds):
    case = prepare(tmp_path, monkeypatch)
    case.task["deadline_seconds"] = seconds
    sync(case, refresh_r=True)
    original = case.settings.read_bytes()
    if kind == "deny":
        case.settings.write_bytes(b'{"permissions":{"deny":["command(*)"]}}')
        case.receipt["configuration"]["agy_settings"] = identity(case.settings)
        sync(case, refresh_r=True)
    frozen = plan(case)
    if kind == "config_drift":
        case.settings.write_bytes(b'{"changed":1}')

    def behavior():
        if kind == "semantic_drift":
            case.settings.write_bytes(b'{"unexpected":true}')
        if kind == "layout_drift":
            case.settings.write_bytes(
                json.dumps(json.loads(case.settings.read_bytes()), indent=4).encode()
            )

    process = fake_spawn(
        case,
        monkeypatch,
        behavior,
        exit_code=1 if kind == "exit_failure" else 0,
        wait_error=subprocess.TimeoutExpired("fake", 1)
        if kind == "timeout"
        else KeyboardInterrupt()
        if kind == "interrupt"
        else None,
    )
    if kind == "restore_failure":
        monkeypatch.setattr(
            slice_run, "_restore_settings", lambda *_: {"restored_original_bytes": False}
        )
    if kind == "capture_failure":
        monkeypatch.setattr(
            slice_run, "_drain_stream", lambda *_: (_ for _ in ()).throw(OSError("fixture-only"))
        )
    if kind == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            run(case, frozen, tmp_path / "failure", execute=True)
        result = json.loads((tmp_path / "failure" / "run.json").read_bytes())
    else:
        result = run(case, frozen, tmp_path / "failure", execute=True)
    assert result["launch_count"] == (0 if kind in {"deny", "config_drift"} else 1)
    assert len(case.calls) == result["launch_count"]
    if kind == "layout_drift":
        assert result["restore_state"] == "Restored"
    elif kind in {"semantic_drift", "restore_failure"}:
        assert result["restore_state"] == "Failed"
    elif kind == "timeout":
        assert result["transport_state"] == "TimedOut" and process.terminated
    else:
        assert result["transport_state"] == "Failed"
    if kind not in {"deny", "config_drift", "semantic_drift", "restore_failure"}:
        assert case.settings.read_bytes() == original
    assert "fixture-only" not in json.dumps(result)


def test_control_repeat_and_run_root_reuse_rejected(tmp_path, monkeypatch):
    case = prepare(tmp_path, monkeypatch)
    frozen = plan(case)
    assert plan(case) == frozen
    run(case, frozen, tmp_path / "run")
    with pytest.raises(runner.TaskRunError, match="RunRootRejected"):
        run(case, frozen, tmp_path / "run")
    with pytest.raises(runner.TaskRunError, match="RunRootRejected"):
        run(case, frozen, case.root / "child")


@pytest.mark.parametrize("target", ["work", "snapshot", "seal", "control", "root"])
def test_prepared_workspace_drift_prevents_launch(tmp_path, monkeypatch, target):
    case = prepare(tmp_path, monkeypatch)
    frozen = plan(case)
    paths = {
        "work": "work/source.py",
        "snapshot": "control/snapshot/source/source.py",
        "seal": "SEALED",
        "control": "control/unknown.json",
        "root": "AGENTS.md",
    }
    (case.root / paths[target]).write_bytes(b"synthetic drift")
    monkeypatch.setattr(
        slice_run, "_session_store", lambda: pytest.fail("key access before drift gate")
    )
    with pytest.raises(runner.TaskRunError):
        run(case, frozen, tmp_path / "drift", execute=True)
    assert not (tmp_path / "drift").exists()


@pytest.mark.parametrize("target", ["protection", "missing", "drift", "extra", "postlaunch"])
def test_cursor_control_integrity(tmp_path, monkeypatch, target):
    case = prepare(tmp_path, monkeypatch, host="cursor")
    project = case.root / ".cursor" / "cli.json"
    if target == "protection":
        case.task["protected_paths"].remove(".cursor")
        sync(case)
        with pytest.raises(runner.TaskRunError, match="InvalidScope"):
            plan(case)
        return
    if target == "missing":
        # Preserve the file as an explicitly retained fixture rather than delete it.
        project.rename(tmp_path / "preserved-cli.json")
    if target == "drift":
        project.write_bytes(b"{}")
    if target == "extra":
        (project.parent / "other.json").write_bytes(b"{}")
    frozen = plan(case)
    if target != "postlaunch":
        assert frozen["preflight_status"] == "Blocked"
        assert run(case, frozen, tmp_path / "blocked", execute=True)["launch_count"] == 0
    else:
        fake_spawn(case, monkeypatch, lambda: project.write_bytes(b'{"changed":true}'))
        result = run(case, frozen, tmp_path / "post", execute=True)
        assert result["launch_count"] == 1 and result["restore_state"] == "Failed"
        assert result["transport_state"] == "Failed"
        assert project.read_bytes() == b'{"changed":true}'


@pytest.mark.parametrize("kind", ["key", "input_capture", "backup", "patch", "metadata"])
def test_prelaunch_failures_and_postrestore_metadata_failure(tmp_path, monkeypatch, kind):
    case = prepare(tmp_path, monkeypatch)
    original = case.settings.read_bytes()
    frozen = plan(case)
    fake_spawn(case, monkeypatch)

    def fail(*_args, **_kwargs):
        raise OSError("fixture secret detail must not appear")

    if kind == "key":
        monkeypatch.setattr(slice_run, "_session_store", fail)
    if kind == "input_capture":
        monkeypatch.setattr(runner, "_capture_bytes", fail)
    if kind == "backup":
        monkeypatch.setattr(slice_run, "_write_new", fail)
        monkeypatch.setattr(slice_run, "_session_store", lambda: pytest.fail("key before backup"))
    if kind == "patch":

        def patch_then_fail(path, _before, after):
            path.write_bytes(after)
            fail()

        monkeypatch.setattr(slice_run, "_apply_settings_patch", patch_then_fail)
    if kind == "metadata":
        persist = runner._persist

        def fail_restore_record(path, value, **kwargs):
            if path.name == "config-restore.json":
                fail()
            return persist(path, value, **kwargs)

        monkeypatch.setattr(runner, "_persist", fail_restore_record)
    result = run(case, frozen, tmp_path / "failure", execute=True)
    assert result["transport_state"] == "Failed"
    assert result["launch_count"] == (1 if kind == "metadata" else 0)
    assert case.settings.read_bytes() == original
    if kind in {"patch", "metadata"}:
        assert result["restore_state"] == "Restored"
    assert "fixture secret" not in json.dumps(result)


def test_control_hardlink_rejected(tmp_path, monkeypatch):
    case = prepare(tmp_path, monkeypatch)
    path = case.trust / "authorization.json"
    os.link(path, tmp_path / "auth-alias.json")
    with pytest.raises(runner.TaskRunError, match="PathRejected"):
        plan(case)


def test_configuration_mutex_blocks_another_thread_and_releases(tmp_path, monkeypatch):
    case = prepare(tmp_path, monkeypatch)
    held = threading.Event()
    release = threading.Event()
    errors = []

    def hold():
        try:
            with runner._configuration_lease(case.settings):
                held.set()
                assert release.wait(10)
        except BaseException as error:
            errors.append(error)
            held.set()

    owner = threading.Thread(target=hold)
    owner.start()
    try:
        assert held.wait(10) and not errors
        with (
            pytest.raises(runner.TaskRunError, match="ConfigurationBusy"),
            runner._configuration_lease(case.settings),
        ):
            pytest.fail("the second task acquired a held configuration")
    finally:
        release.set()
        owner.join(timeout=10)
    assert not owner.is_alive() and not errors
    with runner._configuration_lease(case.settings):
        pass


def test_capture_time_drift_rechecked_before_configuration_write(tmp_path, monkeypatch):
    case = prepare(tmp_path, monkeypatch)
    frozen = plan(case)
    original = case.settings.read_bytes()
    capture = runner._capture_bytes

    def drift(writer, name, raw):
        capture(writer, name, raw)
        (case.root / "work" / "source.py").write_bytes(b"late drift")

    monkeypatch.setattr(runner, "_capture_bytes", drift)
    result = run(case, frozen, tmp_path / "late", execute=True)
    assert result["launch_count"] == 0 and result["capture_state"] == "Incomplete"
    assert case.settings.read_bytes() == original and not case.calls


@pytest.mark.parametrize("host", ["agy", "cursor"])
@pytest.mark.parametrize("seconds", [12, 3600])
def test_task_deadline_passed_to_shared_launcher(tmp_path, monkeypatch, host, seconds):
    case = prepare(tmp_path, monkeypatch, host=host)
    case.task["deadline_seconds"] = seconds
    sync(case, refresh_r=True)
    frozen = plan(case)
    timeouts = []
    process = fake_spawn(case, monkeypatch)
    wait = process.wait

    def record(timeout=None):
        timeouts.append(timeout)
        return wait(timeout)

    monkeypatch.setattr(process, "wait", record)
    assert run(case, frozen, tmp_path / "bounded", execute=True)["launch_count"] == 1
    assert 0 < timeouts[0] <= case.task["deadline_seconds"]
    assert len(timeouts) == 1 and not process.terminated and process.closed


@pytest.mark.parametrize("role", ["Coding", "Review"])
@pytest.mark.parametrize("seconds", [1, 300, 1020, 3600, 0, -1, 3601, True, 3600.0, "3600", None])
def test_runner_deadline_schema_all_existing_roles(tmp_path, monkeypatch, role, seconds):
    case = prepare(tmp_path, monkeypatch)
    case.task.update(role=role, deadline_seconds=seconds)
    if role == "Review":
        case.task["write_roots"] = ["out", "scratch"]
    if type(seconds) is int and 1 <= seconds <= 3600:
        runner._validate_task(case.task)
    else:
        with pytest.raises(runner.TaskRunError, match="InvalidContract"):
            runner._validate_task(case.task)
    assert not case.calls


@pytest.mark.parametrize("role", ["Coding", "Review"])
@pytest.mark.parametrize("host", ["agy", "cursor"])
@pytest.mark.parametrize(
    ("seconds", "elapsed", "native_minutes"),
    [(1, 0.25, 1), (300, 13.25, 5), (1020, 60.25, 16), (3600, 13.25, 60), (3600, 60, 59)],
)
def test_host_deadlines_use_same_remaining_budget(
    monkeypatch, role, host, seconds, elapsed, native_minutes
):
    context = {
        "bundle": {"deployment_receipt": {"host": host, "host_entry": {"path": "frozen-entry"}}},
        "task": {"role": role, "deadline_seconds": seconds},
        "task_root": Path("C:/synthetic-task"),
    }
    calls = []
    monkeypatch.setattr(runner.time, "monotonic", lambda: 100 + elapsed)

    def capture(*args, **kwargs):
        calls.append((args, kwargs))
        return {"fake": True}

    monkeypatch.setattr(slice_run, "_launch_and_capture", capture)
    writer = SimpleNamespace(stream=lambda name: name)
    assert runner._launch(context, writer, "frozen request", 100, SimpleNamespace()) == {
        "fake": True
    }
    ((args, kwargs),) = calls
    remaining = seconds - elapsed
    assert kwargs["timeout_seconds"] == remaining
    if host == "agy":
        assert args[1] == [
            "frozen-entry",
            "--print",
            "frozen request",
            *slice_run.FIXED_ARGV_TAIL[:-1],
            f"{native_minutes}m",
        ]
        assert remaining <= native_minutes * 60 < remaining + 60
    else:
        assert args[1] == runner.cursor_run._cursor_argv(
            "frozen-entry", "C:\\synthetic-task", "frozen request"
        )
        assert "--print-timeout" not in args[1]
    assert slice_run.FIXED_ARGV_TAIL[-2:] == ["--print-timeout", "15m"]
    assert slice_run.OBSERVATION_TIMEOUT_SECONDS == 1020
    assert slice_run.KILL_GRACE_SECONDS == slice_run.CAPTURE_JOIN_SECONDS == 30


@pytest.mark.parametrize("host", ["agy", "cursor"])
def test_expired_work_budget_refuses_before_shared_launcher(monkeypatch, host):
    context = {
        "bundle": {"deployment_receipt": {"host": host, "host_entry": {"path": "unused"}}},
        "task": {"deadline_seconds": 12},
    }
    monkeypatch.setattr(runner.time, "monotonic", lambda: 112)
    monkeypatch.setattr(slice_run, "_launch_and_capture", lambda *a, **k: pytest.fail("no launch"))
    with pytest.raises(runner.TaskRunError, match="DeadlineExceeded"):
        runner._launch(context, SimpleNamespace(), "unused", 100, SimpleNamespace())


@pytest.mark.parametrize("outcome", ["normal", "error", "interrupt"])
@pytest.mark.parametrize("drift", ["none", "project", "global", "io", "check_interrupt"])
def test_cursor_configuration_finalized_on_all_launch_paths(tmp_path, monkeypatch, outcome, drift):
    case = prepare(tmp_path, monkeypatch, host="cursor")
    project = case.root / ".cursor" / "cli.json"
    global_path = Path(case.receipt["configuration"]["cursor_global"]["path"])
    original_project = project.read_bytes()
    frozen = plan(case)
    original_error = KeyboardInterrupt() if outcome == "interrupt" else ValueError()
    process = fake_spawn(
        case, monkeypatch, wait_error=original_error if outcome == "interrupt" else None
    )
    verify = runner._verify_file_identity

    def verify_after_launch(identity_record):
        if case.calls and identity_record["path"] == str(project):
            if drift == "io":
                raise OSError("synthetic readonly configuration error")
            if drift == "check_interrupt":
                raise KeyboardInterrupt()
        return verify(identity_record)

    monkeypatch.setattr(runner, "_verify_file_identity", verify_after_launch)
    shared_launcher = slice_run._launch_and_capture

    def launch_then_fail(*args, **kwargs):
        result = shared_launcher(*args, **kwargs)
        if outcome == "error":
            raise original_error
        return result

    monkeypatch.setattr(slice_run, "_launch_and_capture", launch_then_fail)
    wait = process.wait

    def wait_with_drift(timeout=None):
        if drift == "project":
            project.write_bytes(b'{"modified":true}')
        if drift == "global":
            global_path.write_bytes(b'{"modified":true}')
        return wait(timeout)

    monkeypatch.setattr(process, "wait", wait_with_drift)
    target = tmp_path / "finalized"
    if outcome == "interrupt" or (outcome == "normal" and drift == "check_interrupt"):
        with pytest.raises(KeyboardInterrupt) as error:
            run(case, frozen, target, execute=True)
        if outcome == "interrupt":
            assert error.value is original_error
        result = json.loads((target / "run.json").read_bytes())
    else:
        result = run(case, frozen, target, execute=True)
    assert result["launch_count"] == len(case.calls) == 1 and process.closed
    assert result["restore_state"] == ("Unchanged" if drift == "none" else "Failed")
    assert ("RestoreFailed" in result["blockers"]) == (drift != "none")
    assert result["transport_state"] == (
        "Completed" if outcome == "normal" and drift == "none" else "Failed"
    )
    assert project.read_bytes() == (
        b'{"modified":true}' if drift == "project" else original_project
    )
    assert global_path.exists() == (drift == "global")
    if outcome == "error":
        failure = json.loads((target / "lifecycle-failure.json").read_bytes())
        assert failure["exception_type"] == "ValueError"  # Cleanup does not replace the error.


@pytest.mark.parametrize("target", ["provenance", "gate", "enforcement", "caller_plan"])
@pytest.mark.parametrize("malformation", ["unsorted", "duplicate", "conflicting"])
def test_evidence_lists_reject_invalid_order_or_repeated_ref(
    tmp_path, monkeypatch, target, malformation
):
    case = prepare(tmp_path, monkeypatch)
    evidence = [observed("a.json"), observed("z.json")]
    if malformation == "unsorted":
        evidence.reverse()
    else:
        evidence = [observed("a.json"), observed("a.json")]
        if malformation == "conflicting":
            evidence[1]["sha256"] = "b" * 64
    if target == "caller_plan":
        frozen = copy.deepcopy(plan(case))
        frozen["evidence_refs"] = evidence
        with pytest.raises(runner.TaskRunError, match="InvalidContract"):
            run(case, frozen, tmp_path / "invalid")
        assert not (tmp_path / "invalid").exists()
        return
    if target == "provenance":
        case.receipt["provenance_refs"] = evidence
    if target == "gate":
        case.receipt["runtime_acceptances"][0]["gates"][0]["evidence_refs"] = evidence
    if target == "enforcement":
        case.profile["enforcement"]["evidence_refs"] = evidence
    sync(case, refresh_r=target == "enforcement")
    with pytest.raises(runner.TaskRunError, match="InvalidContract"):
        plan(case)


@pytest.mark.parametrize("declaration", ["same", "hash", "origin", "unverified_hash"])
def test_plan_combines_exact_refs_without_losing_conflicting_declarations(
    tmp_path, monkeypatch, declaration
):
    case = prepare(tmp_path, monkeypatch)
    record = case.receipt["runtime_acceptances"][0]
    shared = observed("shared.json")
    case.receipt["provenance_refs"] = [shared]
    record["management_acceptance_ref"] = copy.deepcopy(shared)
    record["gates"][0]["evidence_refs"] = [copy.deepcopy(shared)]
    if declaration == "hash":
        case.receipt["provenance_refs"][0]["sha256"] = "b" * 64
    if declaration == "origin":
        case.receipt["provenance_refs"][0]["origin"] = "WorkerReported"
    if declaration == "unverified_hash":
        case.receipt["provenance_refs"][0]["sha256"] = None
    sync(case)
    if declaration == "same":
        assert plan(case)["evidence_refs"] == [observed("shared.json")]
    else:
        with pytest.raises(runner.TaskRunError, match="ConflictingEvidence"):
            plan(case)


def test_exact_unicode_ref_identity_and_output_order(tmp_path, monkeypatch):
    case = prepare(tmp_path, monkeypatch)
    refs = ["Z.json", "a.json", "cafe\u0301.json", "caf\u00e9.json"]
    case.receipt["provenance_refs"] = [observed(ref) for ref in refs]
    sync(case)
    frozen = plan(case)
    output = [item["ref"] for item in frozen["evidence_refs"]]
    assert output == sorted(set(output), key=lambda ref: ref.encode("utf-8"))
    assert all(ref in output for ref in refs)
    fake_spawn(case, monkeypatch)
    result = run(case, frozen, tmp_path / "ordered", execute=True)
    output = [item["ref"] for item in result["evidence_refs"]]
    assert output == sorted(set(output), key=lambda ref: ref.encode("utf-8"))
    runner._evidence(result["evidence_refs"])


@pytest.mark.parametrize("execute", [False, True])
@pytest.mark.parametrize("role", ["Coding", "Review"])
def test_first_observation_is_never_an_ordinary_execution(tmp_path, monkeypatch, execute, role):
    case = prepare(tmp_path, monkeypatch, accepted=False, role=role)
    first_observation_receipt(case)
    sync(case)
    before = case.settings.read_bytes()
    monkeypatch.setattr(runner, "_execute_once", lambda *_: pytest.fail("ordinary execution"))
    monkeypatch.setattr(slice_run, "_session_store", lambda: pytest.fail("key read"))
    frozen = plan(case)
    assert frozen["preflight_status"] == "Blocked"
    assert frozen["blockers"] == [
        runner.FIRST_OBSERVATION_BLOCKER,
        "RuntimeAcceptanceUnverified",
    ]
    result = run(case, frozen, tmp_path / "ordinary", execute=execute)
    assert result["transport_state"] == "NotRun" and result["launch_count"] == 0
    assert case.settings.read_bytes() == before and not case.calls


@pytest.mark.parametrize(
    "fault",
    [
        "legacy_empty",
        "legacy_extra",
        "bool_version",
        "future_version",
        "missing_composition",
        "extra_field",
        "known_composition",
        "ordinary_scope",
        "composition_extra",
        "composition_null",
        "files_null",
        "files_unknown",
        "repeated_entry",
        "accepted",
        "cursor",
    ],
)
def test_observation_receipt_is_closed_and_does_not_relax_v1(tmp_path, monkeypatch, fault):
    case = prepare(tmp_path, monkeypatch)
    acceptance = case.receipt["runtime_acceptances"]
    first_observation_receipt(case)
    receipt = case.receipt
    if fault == "legacy_empty":
        receipt["contract_version"] = 1
        receipt.pop("host_composition")
    elif fault == "legacy_extra":
        receipt["contract_version"] = 1
    elif fault == "bool_version":
        receipt["contract_version"] = True
    elif fault == "future_version":
        receipt["contract_version"] = 3
    elif fault == "missing_composition":
        receipt.pop("host_composition")
    elif fault == "extra_field":
        receipt["skip_identity"] = True
    elif fault == "known_composition":
        receipt["host_composition"]["status"] = "Known"
    elif fault == "ordinary_scope":
        receipt["host_composition"]["scope"] = "OrdinaryRun"
    elif fault == "composition_extra":
        receipt["host_composition"]["backend"] = "placeholder"
    elif fault == "composition_null":
        receipt["host_composition"] = None
    elif fault == "files_null":
        receipt["host_identity_files"] = None
    elif fault == "files_unknown":
        receipt["host_identity_files"] = "Unknown"
    elif fault == "repeated_entry":
        receipt["host_identity_files"] = [receipt["host_entry"]]
    elif fault == "accepted":
        receipt["runtime_acceptances"] = acceptance
    else:
        receipt["host"] = "cursor"
    sync(case)
    with pytest.raises(runner.TaskRunError, match="InvalidContract"):
        plan(case)
    assert not (case.root / "control/plan.json").exists() and not case.calls


def test_observation_cannot_use_a_counterfeit_ready_plan(tmp_path, monkeypatch):
    case = prepare(tmp_path, monkeypatch, accepted=False)
    first_observation_receipt(case)
    sync(case)
    frozen = plan(case)
    counterfeit = {**frozen, "preflight_status": "Ready", "blockers": []}
    write_json(case.root / "control/plan.json", counterfeit)
    monkeypatch.setattr(runner, "_execute_once", lambda *_: pytest.fail("execution"))
    with pytest.raises(runner.TaskRunError, match="PlanChanged"):
        run(case, counterfeit, tmp_path / "refused", execute=True)
    assert not (tmp_path / "refused").exists() and not case.calls
