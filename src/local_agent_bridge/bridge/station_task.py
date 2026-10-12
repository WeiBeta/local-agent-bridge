"""Synchronous, per-request import/prepare/plan/run/collect under one station lease.

Configured policy authorizes execution within its declared scope. It is neither
legacy runtime acceptance nor management acceptance of a task's business result.
"""

from __future__ import annotations

import copy
import hashlib
import time
import uuid
from pathlib import Path

from . import contract, station_pool, task_input, task_run, task_workspace

_SPEC_FIELDS = {
    "cli_contract_version",
    "source",
    "policy",
    "instructions_path",
    "instructions_sha256",
    "task",
    "admission_timeout_seconds",
}
_TASK_FIELDS = {
    "role",
    "capabilities",
    "read_roots",
    "write_roots",
    "protected_paths",
    "required_outputs",
    "acceptance_ids",
    "deadline_seconds",
    "source_output_bytes_limit",
}


def validate_spec(spec: object, policy: dict) -> dict:
    require = station_pool.require
    require(type(spec) is dict and set(spec) == _SPEC_FIELDS, "StationSpecInvalid")
    spec = copy.deepcopy(spec)
    require(
        type(spec["cli_contract_version"]) is int and spec["cli_contract_version"] == 1,
        "StationSpecInvalid",
    )
    require(type(spec["source"]) is dict and type(spec["policy"]) is dict, "StationSpecInvalid")
    task = spec["task"]
    require(type(task) is dict and set(task) == _TASK_FIELDS, "StationSpecInvalid")
    require(task["role"] in policy["roles"], "StationTaskUnauthorized")
    require(
        type(task["capabilities"]) is dict
        and set(task["capabilities"]) == set(policy["capabilities"])
        and all(type(value) is bool for value in task["capabilities"].values()),
        "StationTaskUnauthorized",
    )
    require(
        all(
            not enabled or policy["capabilities"][key]
            for key, enabled in task["capabilities"].items()
        ),
        "StationTaskUnauthorized",
    )
    # The minimal station policy has no external web/dependency grant. Existing
    # legacy tasks retain their explicit scopes; a station does not invent them.
    require(
        not task["capabilities"]["web_reference"]
        and not task["capabilities"]["prepare_dependencies"],
        "StationTaskUnauthorized",
    )
    for field, maximum in (
        ("deadline_seconds", policy["max_deadline_seconds"]),
        ("source_output_bytes_limit", policy["source_output_bytes_limit"]),
    ):
        require(type(task[field]) is int and 1 <= task[field] <= maximum, "StationTaskUnauthorized")
    for field in ("read_roots", "write_roots", "protected_paths", "required_outputs"):
        task_run._strings(task[field], relative=True)
    task_run._strings(task["acceptance_ids"])
    timeout = spec["admission_timeout_seconds"]
    require(
        timeout is None or (type(timeout) is int and 0 <= timeout <= 86400), "StationWaitInvalid"
    )
    note_path = task_run.checked_host_path(path=spec["instructions_path"])
    note = task_run.read_host_input_bytes(path=str(note_path))
    task_run._hash(spec["instructions_sha256"])
    require(hashlib.sha256(note).hexdigest() == spec["instructions_sha256"], "StationNoteChanged")
    note.decode("utf-8", "strict")
    return {"spec": spec, "note": note}


def _materialize(lease: station_pool.Lease, frozen: dict, request_root: Path) -> dict:
    lease.verify()
    registry = lease.pool.registry
    document, station = registry["document"], lease.station
    policy = document["policy"]
    task_root = station.root / "jobs" / str(uuid.uuid4())
    lease.bind_task(task_root)
    task_input._assert_plain_target(task_root.parent, label="station jobs")
    task_root.parent.mkdir(exist_ok=True)
    trust = request_root / "trusted"
    trust.mkdir()
    imported = task_input.import_snapshot(
        source=frozen["spec"]["source"],
        policy=frozen["spec"]["policy"],
        snapshot_root=request_root / "snapshot",
    )
    receipt = copy.deepcopy(document["deployment_receipt"])
    # Only fields of the existing deployment identity surface are retained.
    receipt = {key: receipt[key] for key in task_run._RECEIPT_KEYS}
    record_raw = task_run.read_host_input_bytes(path=str(station.record))
    receipt.update(
        {
            "contract_version": 4,
            "host": "agy",
            "adapter": "agy_task_v1",
            "workspace_parent": str(task_root.parent),
            "launch_shell": None,
            "configuration": {"agy_settings": None, "cursor_global": None, "cursor_project": None},
            "runtime_acceptances": [],
            "native_project": {
                "id": station.native_id,
                "root": str(station.root),
                "record": {
                    "path": str(station.record),
                    "sha256": hashlib.sha256(record_raw).hexdigest(),
                },
            },
            "station_binding": {
                "station_id": station.id,
                "root_identity": station.root_identity,
                "policy_sha256": station_pool.digest(policy),
                "grant_ref": policy["grant_ref"],
            },
        }
    )
    task_run._validate_receipt(receipt)
    task_run._verify_native_project(receipt, pinned=True)
    profile = {
        "contract_version": 1,
        "id": receipt["id"],
        "host": "agy",
        "receipt_sha256": "0" * 64,
        "roles": policy["roles"],
        "supported_capabilities": policy["capabilities"],
        "execution_modes": ["declared_scope"],
        "read_roots": ["out", "scratch", "work"],
        "write_roots": ["out", "scratch", "work"],
        "toolchain_refs": [item["ref"] for item in receipt["toolchains"]],
        "enforcement": {
            "method": "ConfiguredNativeStation",
            "file_scope": "Declared",
            "network_scope": "Unverified",
            "evidence_refs": [],
        },
    }
    receipt["profile_fields_sha256"] = station_pool.digest(
        {key: value for key, value in profile.items() if key != "receipt_sha256"}
    )
    profile["receipt_sha256"] = station_pool.digest(receipt)
    fields = frozen["spec"]["task"]
    protected = sorted(set(fields["protected_paths"]) | {"control", "task.json"})
    baseline, _directories, _total = task_input._validate_snapshot_manifest(imported)
    source_controls = {name: baseline[name][1] for name in task_workspace._rule_paths(baseline)}
    protected = sorted(set(protected) | {"work/" + name for name in source_controls})
    task = {
        "contract_version": 1,
        **fields,
        "protected_paths": protected,
        "task_id": lease.request_id,
        "snapshot_id": imported["snapshot_id"],
        "snapshot_manifest_sha256": station_pool.digest(imported),
        "instructions_sha256": hashlib.sha256(frozen["note"]).hexdigest(),
        "deployment_profile_id": profile["id"],
        "deployment_profile_sha256": station_pool.digest(profile),
        "authorization_sha256": "0" * 64,
        "execution_boundary": "declared_scope",
    }
    auth = {
        "contract_version": 1,
        "task_id": task["task_id"],
        "grant_ref": policy["grant_ref"],
        "receipt_sha256": profile["receipt_sha256"],
        "capabilities": fields["capabilities"],
        "execution_boundary": "declared_scope",
        "read_roots": fields["read_roots"],
        "write_roots": fields["write_roots"],
        "web_scope": None,
        "dependency_scope": None,
        "input_control_bindings": {
            "task_fields_sha256": station_pool.digest(
                {key: value for key, value in task.items() if key != "authorization_sha256"}
            ),
            "files": source_controls,
        },
    }
    task["authorization_sha256"] = station_pool.digest(auth)
    bundle = {"deployment_receipt": receipt, "deployment_profile": profile, "authorization": auth}
    for name, value in bundle.items():
        task_run._persist(trust / (name.replace("_", "-") + ".json"), value)
    expected = station_pool.digest(bundle)
    task_run.load_trusted_inputs(
        trusted_control_root=trust,
        trusted_inputs_sha256=expected,
        task_root=task_root,
        snapshot_root=request_root / "snapshot",
    )
    task_workspace.prepare_task(
        snapshot_root=request_root / "snapshot",
        task_manifest=task,
        task_note=frozen["note"],
        deployment_profile=profile,
        authorization=auth,
        task_root=task_root,
    )
    plan = task_run.plan_task(
        task_root=task_root, host="agy", trusted_control_root=trust, trusted_inputs_sha256=expected
    )
    return {
        "task_root": task_root,
        "task": task,
        "plan": plan,
        "trusted": trust,
        "trusted_sha256": expected,
        "receipt": receipt,
        "native_policy": _native_policy(station.record),
    }


def _native_policy(path: Path) -> str:
    raw = task_run.read_host_input_bytes(path=str(path))
    value = contract.decode_strict_json_bytes(raw, label="native project")
    return station_pool.digest(
        {
            key: value.get(key)
            for key in ("id", "projectResources", "permissionGrants", "permissions", "settings")
        }
    )


def _control_complete(run: dict, run_root: Path) -> bool:
    if run["launch_count"] == 0:
        return run["capture_state"] != "Incomplete" and run["restore_state"] != "Failed"
    if (
        run["launch_count"] != 1
        or run["capture_state"] != "Sealed"
        or run["restore_state"] != "Unchanged"
    ):
        return False
    launch = task_run._read(run_root / "launch.json")
    return launch.get("capture_state") == "complete" and all(
        launch.get("cleanup", {}).get(key) is True
        for key in ("child_exit_observed", "pipes_closed", "job_closed")
    )


def dispatch_task(
    *,
    spec: dict,
    registry_path: Path,
    registry_sha256: str,
    execute: bool = False,
    cancellation: station_pool.Cancellation | None = None,
) -> dict:
    """One worker performs the complete chain; no CLI/model retry is hidden here."""
    registry = station_pool.load_registry(registry_path, registry_sha256)
    station_pool.require(type(execute) is bool, "StationSpecInvalid")
    frozen = validate_spec(spec, registry["document"]["policy"])
    request_id = str(uuid.uuid4())
    if not execute:
        return {
            "request_id": request_id,
            "status": "PreparedOnly",
            "launch_count": 0,
            "task_root": None,
            "capacity": len(registry["stations"]),
        }
    pool = station_pool.Pool(registry)
    lease = None
    started = time.monotonic()
    request_root = registry["control_root"] / "requests" / request_id
    outcome = {
        "contract_version": 1,
        "request_id": request_id,
        "status": "Unknown",
        "launch_count": 0,
        "task_root": None,
        "station_id": None,
        "blockers": [],
        "business": None,
        "control_complete": False,
        "management_decision": None,
    }
    context = None
    call_entered = False
    interrupted = None
    finalization_error = None
    try:
        lease = pool.acquire(
            request_id,
            timeout_seconds=frozen["spec"]["admission_timeout_seconds"],
            cancellation=cancellation,
        )
        outcome["admission_seconds"] = round(time.monotonic() - started, 3)
        outcome["station_id"] = lease.station.id
        request_root.mkdir(parents=True)
        context = _materialize(lease, frozen, request_root)
        outcome["task_root"] = str(context["task_root"])
        outcome["native_project_id"] = lease.station.native_id
        outcome["station_root"] = str(lease.station.root)
        outcome["control_complete"] = True  # No host invocation has been entered yet.
        lease.verify(context["task_root"])
        station_pool.require(
            hashlib.sha256(registry_path.read_bytes()).hexdigest() == registry_sha256,
            "StationRegistryChanged",
        )
        lease.running()
        call_entered = True
        run = task_run.run_task(
            task_root=context["task_root"],
            plan=context["plan"],
            run_root=request_root / "run",
            trusted_control_root=context["trusted"],
            trusted_inputs_sha256=context["trusted_sha256"],
            execute=True,
            station_lease=lease,
        )
        outcome["launch_count"] = run["launch_count"]
        outcome["run"] = run
        complete = _control_complete(run, request_root / "run")
        outcome["control_complete"] = complete
        station_pool.require(
            _native_policy(lease.station.record) == context["native_policy"],
            "StationNativePolicyChanged",
        )
        collection = task_workspace.collect_task(
            task_root=context["task_root"],
            run_root=request_root / "run",
            result_root=request_root / "result",
        )
        outcome["result_root"] = str(request_root / "result")
        outcome["business"] = {
            "state": "Candidate" if not collection["blockers"] else "Incomplete",
            "worker_status": collection["worker_status"],
            "blockers": collection["blockers"],
            "host_observations": collection["host_observations"],
            "management_decision": None,
        }
        conversation = request_root / "run/native-conversation.json"
        outcome["native_conversation"] = (
            task_run._read(conversation)
            if conversation.is_file()
            else {"status": "Unknown", "conversation_id": None}
        )
        outcome["control_complete"] = complete
        outcome["status"] = "Collected" if complete else "ControlUnconfirmed"
    except BaseException as error:
        if lease is not None and lease.task_root is not None:
            outcome["task_root"] = str(lease.task_root)
        outcome["blockers"].append(getattr(error, "code", type(error).__name__))
        outcome["status"] = "Stopped"
        identity_unconfirmed = getattr(error, "code", None) in {
            "StationRootChanged",
            "NativeProjectBindingMismatch",
            "StationNativePolicyChanged",
        }
        if identity_unconfirmed:
            outcome["control_complete"] = False
        elif not call_entered:
            outcome["control_complete"] = True
        if call_entered:
            saved = request_root / "run/run.json"
            outcome["launch_count"] = None
            try:
                if saved.is_file():
                    saved_run = task_run._read(saved)
                    outcome["launch_count"] = saved_run["launch_count"]
                    if not identity_unconfirmed:
                        outcome["control_complete"] = _control_complete(
                            saved_run, request_root / "run"
                        )
            except (OSError, task_run.TaskRunError):
                outcome["blockers"].append("DispatchRunEvidenceUnavailable")
        if not isinstance(error, Exception):
            interrupted = error
    finally:
        outcome["elapsed_seconds"] = round(time.monotonic() - started, 3)
        terminal = request_root / "dispatch.json"
        outcome["release_state"] = "Pending" if lease is not None else "NotAcquired"
        outcome["terminal_path"] = str(request_root / "dispatch-final.json")
        try:
            task_input._assert_plain_target(request_root, label="station request")
            request_root.mkdir(parents=True, exist_ok=True)
            task_run._persist(terminal, outcome)
            if lease is not None:
                lease.finish(control_complete=outcome["control_complete"], terminal=terminal)
                outcome["release_state"] = (
                    "Released" if outcome["control_complete"] else "Suspended"
                )
            task_run._persist(request_root / "dispatch-final.json", outcome)
        except BaseException as error:
            finalization_error = error
        finally:
            try:
                if lease is not None and not lease.closed:
                    lease.abandon()
            except BaseException as error:
                if finalization_error is None:
                    finalization_error = error
            finally:
                try:
                    pool.close()
                except BaseException as error:
                    if finalization_error is None:
                        finalization_error = error
    if interrupted is not None:
        raise interrupted
    if finalization_error is not None:
        raise finalization_error
    return outcome
