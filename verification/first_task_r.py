"""One trusted, frozen Task runtime validation; never a production run or R verdict.

This sdist-only program has no host/model/argv override and no offline bypass.
Unit tests inject fake lifecycle boundaries; actual use requires a separately
approved management permit and a non-editable, frozen wheel installation.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from local_agent_bridge.bridge import contract, layered_acceptance, paths, task_run, task_workspace

MANAGEMENT_TASK = "019fe10b-df55-7b82-a9ba-3702dc08c55f"
CAPABILITIES = {"execute": True, "web_reference": False, "prepare_dependencies": False}
RECIPE_REF = "first_task_r_unittest_v1"
MISSING_R = "RuntimeAcceptanceUnverified"
WHEEL_MAX_ENTRIES = 128
WHEEL_MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
PERMISSIONS = {
    "synthetic_copies",
    "same_user_declared_scope",
    "configuration_lease",
    "owned_job_termination",
    "capture_key_read",
    "isolated_capture_write",
}
SHEET_FIELDS = {
    "contract_version",
    "kind",
    "permit_id",
    "task_id",
    "management_task_id",
    "approval",
    "grant_ref",
    "budget_ref",
    "max_host_launches",
    "host",
    "role",
    "capabilities",
    "execution_boundary",
    "task_root",
    "trusted_control_root",
    "run_root",
    "result_root",
    "task_manifest_sha256",
    "plan_sha256",
    "trusted_inputs_sha256",
    "receipt_binding_sha256",
    "deadline_seconds",
    "validator",
    "installation",
    "environment",
    "recipes",
    "permissions",
}


class ValidationError(RuntimeError):
    """Fixed, non-sensitive validation error; never expose an exception body."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValidationError(code)


def _digest(value: object) -> str:
    return task_run._digest(task_run._canonical(value))


def _read_pinned(identity: dict) -> bytes:
    task_run._identity(identity)
    raw = task_run.read_host_input_bytes(path=identity["path"])
    _require(task_run._digest(raw) == identity["sha256"], "IdentityChanged")
    return raw


def _sheet(path: Path, expected_sha256: str) -> dict:
    task_run._hash(expected_sha256)
    raw = task_run.read_host_input_bytes(path=str(path))
    _require(task_run._digest(raw) == expected_sha256, "PermitChanged")
    sheet = contract.decode_strict_json_bytes(raw, label="runtime validation permit")
    task_run._object(
        sheet,
        task_run.FIRST_LAYERED_PERMIT_KEYS
        if type(sheet) is dict and sheet.get("contract_version") == 3
        else SHEET_FIELDS,
    )
    _require(
        type(sheet["contract_version"]) is int and sheet["contract_version"] in {1, 2, 3},
        "PermitInvalid",
    )
    _require(sheet["kind"] == "TaskRuntimeValidationPermit", "PermitInvalid")
    for key in ("permit_id", "task_id", "grant_ref"):
        task_run._text(sheet[key])
    _require(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", sheet["permit_id"]) is not None, "PermitInvalid")
    _require(sheet["management_task_id"] == MANAGEMENT_TASK, "PermitInvalid")
    approval = task_run._object(sheet["approval"], {"status", "author_confirmed"})
    task_run._enum(approval["status"], {"Proposed", "Approved"})
    _require(type(approval["author_confirmed"]) is bool, "PermitInvalid")
    _require(approval == {"status": "Approved", "author_confirmed": True}, "PermissionUnverified")
    budget = task_run._evidence([sheet["budget_ref"]])
    _require(task_run._observed(budget), "BudgetUnverified")
    _require(
        type(sheet["max_host_launches"]) is int and sheet["max_host_launches"] == 1, "PermitInvalid"
    )
    task_run._caps(sheet["capabilities"])
    _require(
        sheet["host"] == "agy"
        and sheet["role"] == "Coding"
        and sheet["capabilities"] == CAPABILITIES
        and sheet["execution_boundary"] == "declared_scope",
        "ValidationScopeRejected",
    )
    for key in (
        "task_manifest_sha256",
        "plan_sha256",
        "trusted_inputs_sha256",
        "receipt_binding_sha256",
    ):
        task_run._hash(sheet[key])
    _require(
        type(sheet["deadline_seconds"]) is int
        and 1 <= sheet["deadline_seconds"] <= contract.TASK_DEADLINE_MAX_SECONDS,
        "PermitInvalid",
    )
    permissions = task_run._object(
        sheet["permissions"],
        PERMISSIONS | ({"management_local_retest"} if sheet["contract_version"] == 3 else set()),
    )
    _require(
        all(type(value) is bool and value for value in permissions.values()), "PermissionUnverified"
    )
    task_run._identity(sheet["validator"])
    _require(Path(sheet["validator"]["path"]) == Path(__file__).absolute(), "ValidatorChanged")
    _read_pinned(sheet["validator"])
    installation = task_run._object(sheet["installation"], {"root", "python", "wheel"})
    for key in ("python", "wheel"):
        task_run._identity(installation[key])
    task_run._identity(sheet["environment"])
    recipes = task_run._list(sheet["recipes"])
    _require(len(recipes) == 1, "RecipeUnverified")
    recipe = task_run._object(recipes[0], {"ref", "identity"})
    _require(recipe["ref"] == RECIPE_REF, "RecipeUnverified")
    task_run._identity(recipe["identity"])
    if sheet["contract_version"] == 3:
        _require(
            sheet["acceptance_method"] == layered_acceptance.METHOD
            and sheet["waived_blockers"] == [task_run.FIRST_LAYERED_BLOCKER],
            "ValidationScopeRejected",
        )
        retest = task_run._object(
            sheet["manager_retest"],
            {"root", "timeout_seconds", "baseline_tests", "candidate_tests"},
        )
        task_run._absolute(retest["root"])
        _require(
            type(retest["timeout_seconds"]) is int
            and 1 <= retest["timeout_seconds"] <= 60
            and type(retest["baseline_tests"]) is int
            and retest["baseline_tests"] == 1
            and type(retest["candidate_tests"]) is int
            and retest["candidate_tests"] == 6,
            "RecipeUnverified",
        )
    return sheet


def _environment(sheet: dict) -> dict:
    raw = _read_pinned(sheet["environment"])
    value = contract.decode_strict_json_bytes(raw, label="runtime validation environment")
    fields = {"contract_version", "kind", "local_appdata", "worker_shell"}
    if sheet["contract_version"] >= 2:
        fields.add("scope")
    task_run._object(value, fields)
    _require(
        type(value["contract_version"]) is int
        and value["contract_version"] == sheet["contract_version"],
        "EnvironmentUnverified",
    )
    _require(value["kind"] == "TaskRuntimeValidationEnvironment", "EnvironmentUnverified")
    task_run._absolute(value["local_appdata"])
    shell = value["worker_shell"]
    if sheet["contract_version"] >= 2:
        _require(
            value["scope"]
            == ("LayeredFirstExecution" if sheet["contract_version"] == 3 else "FirstObservation"),
            "EnvironmentUnverified",
        )
        task_run._object(shell, {"status", "identity"})
        task_run._enum(shell["status"], {"Known", "Unknown"})
        if shell["status"] == "Unknown":
            _require(shell["identity"] is None, "EnvironmentUnverified")
            return value
        shell = shell["identity"]
    task_run._identity(shell)
    task_run._verify_file_identity(shell)
    return value


def _expected_blockers(sheet: dict) -> list[str]:
    if sheet["contract_version"] == 3:
        return [task_run.FIRST_LAYERED_BLOCKER]
    if sheet["contract_version"] == 2:
        return sorted([MISSING_R, task_run.FIRST_OBSERVATION_BLOCKER])
    return [MISSING_R]


def _overlaps(left: Path, right: Path) -> bool:
    return paths._is_within(left, right) or paths._is_within(right, left)


def _roots(sheet: dict, environment: dict, sheet_path: Path, *, initial: bool) -> dict[str, Path]:
    roots = {
        key: task_run._absolute(sheet[key])
        for key in ("task_root", "trusted_control_root", "run_root", "result_root")
    }
    roots["installation"] = task_run._directory(task_run._absolute(sheet["installation"]["root"]))
    roots["local_appdata"] = task_run._absolute(environment["local_appdata"])
    if sheet["contract_version"] == 3:
        roots["manager_retest"] = task_run._absolute(sheet["manager_retest"]["root"])
    for key, root in roots.items():
        task_run._directory(root.parent)
        if root.exists():
            task_run._directory(root)
        if initial and key in {"run_root", "result_root", "local_appdata", "manager_retest"}:
            _require(not os.path.lexists(root), "OutputExists")
    for index, left in enumerate(roots.values()):
        for right in list(roots.values())[index + 1 :]:
            _require(not _overlaps(left, right), "ValidationRootRejected")
    mutable = [roots[key] for key in ("task_root", "run_root", "result_root", "local_appdata")]
    if "manager_retest" in roots:
        mutable.append(roots["manager_retest"])
    for identity in (sheet["validator"], sheet["environment"], sheet["installation"]["wheel"]):
        path = task_run._absolute(identity["path"])
        _require(
            not any(paths._is_within(path, root) for root in mutable), "ValidationRootRejected"
        )
    _require(
        not any(paths._is_within(sheet_path, root) for root in mutable), "ValidationRootRejected"
    )
    code_root = Path(task_run.__file__).absolute().parents[3]
    _require(
        not any(_overlaps(root, code_root) for root in mutable if root != roots["task_root"]),
        "ValidationRootRejected",
    )
    marker = roots["run_root"].parent / (sheet["permit_id"] + ".consumed.json")
    _require(
        not any(paths._is_within(marker, root) for key, root in roots.items() if key != "run_root"),
        "ValidationRootRejected",
    )
    _require(
        marker
        not in {
            sheet_path,
            Path(sheet["validator"]["path"]),
            Path(sheet["environment"]["path"]),
            Path(sheet["installation"]["wheel"]["path"]),
        },
        "ValidationRootRejected",
    )
    if initial:
        _require(not os.path.lexists(marker), "PermitConsumed")
    roots["marker"] = marker
    return roots


def _verify_installation(sheet: dict, receipt: dict) -> None:
    installation = sheet["installation"]
    root = task_run._directory(task_run._absolute(installation["root"]))
    _require(
        root == Path(sys.prefix).absolute()
        and Path(installation["python"]["path"]) == Path(sys.executable).absolute(),
        "InstallationUnverified",
    )
    task_run._verify_file_identity(installation["python"])
    _require(
        installation["wheel"]["sha256"] == receipt["bridge"]["wheel_sha256"],
        "InstallationUnverified",
    )
    wheel_raw = _read_pinned(installation["wheel"])
    distribution = metadata.distribution("local-agent-bridge")
    package_root = task_run._directory(root / "Lib" / "site-packages" / "local_agent_bridge")
    _require(
        Path(distribution.locate_file("local_agent_bridge")) == package_root
        and distribution.version == receipt["bridge"]["version"],
        "InstallationUnverified",
    )
    direct_url = distribution.read_text("direct_url.json")
    if direct_url is not None:
        value = contract.decode_strict_json_bytes(direct_url.encode(), label="installation origin")
        _require(
            type(value) is dict and not value.get("dir_info", {}).get("editable", False),
            "InstallationUnverified",
        )
    entry = Path(receipt["bridge"]["entry"]["path"])
    _require(entry == root / "Scripts" / "local-agent-bridge.exe", "InstallationUnverified")
    products = {Path(item["path"]): item for item in receipt["bridge"]["product_files"]}
    _require(
        all(paths._is_within(path, package_root) for path in products), "InstallationUnverified"
    )
    _require(
        all(paths._is_within(path, package_root) for path in task_run._runtime_files()),
        "InstallationUnverified",
    )
    with zipfile.ZipFile(io.BytesIO(wheel_raw)) as wheel:
        members = wheel.infolist()
        _require(
            len(members) <= WHEEL_MAX_ENTRIES
            and len({item.filename for item in members}) == len(members)
            and sum(item.file_size for item in members) <= WHEEL_MAX_PAYLOAD_BYTES,
            "InstallationUnverified",
        )
        payload = {
            item.filename: item
            for item in members
            if item.filename.startswith("local_agent_bridge/") and not item.is_dir()
        }
        installed = {
            "local_agent_bridge/" + path.relative_to(package_root).as_posix(): identity
            for path, identity in products.items()
        }
        _require(payload.keys() == installed.keys(), "InstallationUnverified")
        for name, identity in installed.items():
            _require(
                task_run._digest(wheel.read(name)) == identity["sha256"], "InstallationUnverified"
            )
            task_run._verify_file_identity(identity)
    task_run._verify_runtime_identity(receipt)


def _verify_context(
    sheet: dict, roots: dict, environment: dict, *, context: dict | None = None
) -> tuple[dict, dict]:
    if context is None:
        context = task_run._load_inputs(
            roots["task_root"],
            roots["trusted_control_root"],
            sheet["trusted_inputs_sha256"],
            run_root=roots["run_root"],
        )
    task = context["task"]
    receipt = context["bundle"]["deployment_receipt"]
    profile = context["bundle"]["deployment_profile"]
    authorization = context["bundle"]["authorization"]
    _require(
        task["task_id"] == sheet["task_id"]
        and authorization["grant_ref"] == sheet["grant_ref"]
        and task["deadline_seconds"] == sheet["deadline_seconds"],
        "PermitBindingMismatch",
    )
    _require(
        task["role"] == sheet["role"]
        and task["capabilities"] == CAPABILITIES
        and authorization["capabilities"] == CAPABILITIES
        and task["execution_boundary"] == sheet["execution_boundary"]
        and profile["roles"] == ["Coding"]
        and profile["supported_capabilities"] == CAPABILITIES
        and profile["execution_modes"] == ["declared_scope"],
        "ValidationScopeRejected",
    )
    if sheet["contract_version"] == 3:
        _require(receipt["layered_acceptances"] == [], "ValidationScopeRejected")
    _require(
        receipt["host"] == "agy"
        and receipt["runtime_acceptances"] == []
        and receipt["contract_version"] == sheet["contract_version"],
        "ValidationScopeRejected",
    )
    binding = (
        layered_acceptance.receipt_binding(receipt)
        if sheet["contract_version"] == 3
        else _digest(
            {
                key: value
                for key, value in receipt.items()
                if key not in {"runtime_acceptances", "provenance_refs"}
            }
        )
    )
    _require(
        binding == sheet["receipt_binding_sha256"]
        and _digest(task) == sheet["task_manifest_sha256"],
        "PermitBindingMismatch",
    )
    plan = task_run._make_plan(context, "agy")
    _require(
        plan["preflight_status"] == "Blocked" and plan["blockers"] == _expected_blockers(sheet),
        "NonRGateBlocked",
    )
    _require(
        _digest(plan) == sheet["plan_sha256"]
        and task_run._read(roots["task_root"] / "control" / "plan.json") == plan
        and task_run._read(roots["task_root"] / "control" / "deployment-receipt.json") == receipt,
        "ControlChanged",
    )
    environment_ref = {
        "ref": sheet["environment"]["path"],
        "sha256": sheet["environment"]["sha256"],
        "origin": "HostObserved",
    }
    _require(environment_ref in profile["enforcement"]["evidence_refs"], "EnvironmentUnverified")
    _require(environment["local_appdata"] == str(roots["local_appdata"]), "EnvironmentUnverified")
    recipe = sheet["recipes"][0]
    _read_pinned(recipe["identity"])
    recipe_path = task_run._absolute(recipe["identity"]["path"])
    _require(paths._is_within(recipe_path, roots["task_root"] / "work"), "RecipeUnverified")
    relative = recipe_path.relative_to(roots["task_root"]).as_posix()
    _require(
        any(task_run.task_input._scope_covers(path, relative) for path in task["protected_paths"]),
        "RecipeUnverified",
    )
    tools = receipt["toolchains"]
    _require(len(tools) == 1 and tools[0]["recipe_refs"] == [RECIPE_REF], "ToolchainUnverified")
    executables = [
        item
        for item in tools[0]["identity_files"]
        if Path(item["path"]).suffix.casefold() == ".exe"
    ]
    _require(executables == [sheet["installation"]["python"]], "ToolchainUnverified")
    # A Blocked production Plan intentionally did not check these identities.
    _verify_installation(sheet, receipt)
    return context, plan


def _error_code(error: BaseException) -> str:
    if isinstance(
        error, (ValidationError, task_run.TaskRunError, task_workspace.TaskWorkspaceError)
    ):
        return error.code
    return "Interrupted" if not isinstance(error, Exception) else "ValidationFailed"


def _checked_lifecycle_receipt(value: dict, sheet: dict) -> dict:
    """Bind the run body before using facts; attached evidence is checked separately."""
    task_run._object(value, task_workspace._RUN_KEYS)
    task_run._version(value)
    _require(
        value["task_id"] == sheet["task_id"] and value["plan_sha256"] == sheet["plan_sha256"],
        "RunBindingMismatch",
    )
    count = value["launch_count"]
    _require(count is None or (type(count) is int and count in {0, 1}), "RunReceiptInvalid")
    task_run._enum(value["transport_state"], {"NotRun", "Completed", "Failed", "TimedOut"})
    task_run._enum(value["capture_state"], {"NotRun", "Sealed", "Incomplete"})
    task_run._enum(value["restore_state"], {"NotRun", "Unchanged", "Restored", "Failed"})
    if value["capture_uid"] is not None:
        task_run._text(value["capture_uid"])
    task_run._strings(value["blockers"])
    _require(
        count is not None
        or (value["transport_state"] == "Failed" and "LaunchUnverified" in value["blockers"]),
        "RunReceiptInvalid",
    )
    _require(value["transport_state"] != "Completed" or count == 1, "RunReceiptInvalid")
    _require(value["transport_state"] != "TimedOut" or count == 1, "RunReceiptInvalid")
    if value["transport_state"] == "NotRun":
        _require(
            count == 0
            and value["capture_state"] == "NotRun"
            and value["restore_state"] == "NotRun"
            and value["capture_uid"] is None
            and value["test_observations"] == [],
            "RunReceiptInvalid",
        )
    _require(
        value["capture_state"] != "Sealed"
        or (type(value["capture_uid"]) is str and bool(value["capture_uid"])),
        "RunReceiptInvalid",
    )
    return value


def _saved_json(path: Path) -> tuple[object, bytes]:
    """C's bounded, descriptor-identity-checked read; hashes use these raw bytes."""
    raw = task_run.read_host_input_bytes(path=str(path))
    value = contract.decode_strict_json_bytes(raw, label="saved validation evidence")
    _require(raw == task_run._canonical(value), "EvidenceNotCanonical")
    return value, raw


def _launch_fact(value: object, fallback: int | None) -> int | None:
    """Use only this invocation's C return, never an unchecked saved run."""
    if type(value) is dict and set(value) == task_workspace._RUN_KEYS:
        count = value["launch_count"]
        if count is None or (type(count) is int and count in {0, 1}):
            return count
    return fallback


def _saved_launch_fact(roots: dict) -> int | None:
    value, _ = _saved_json(roots["run_root"] / "launch.json")
    _require(type(value) is dict, "LaunchEvidenceMismatch")
    task_run._enum(value.get("spawn_state"), {"not_attempted", "confirmed", "unknown"})
    count = task_run.winjob.LaunchLifecycle(execution_state=value["spawn_state"]).launch_count
    _require(contract.deep_equal_strict(count, value.get("launch_count")), "LaunchEvidenceMismatch")
    # A fixed-root local launch fact is not a verified task-bound run receipt.
    return count


def _local_facts(ref: str, value: dict, run: dict, context: dict, roots: dict) -> None:
    _require(type(value) is dict, "RunEvidenceInvalid")
    if ref == "launch.json":
        task_run._enum(value.get("spawn_state"), {"not_attempted", "confirmed", "unknown"})
        lifecycle = task_run.winjob.LaunchLifecycle(execution_state=value["spawn_state"])
        _require(
            contract.deep_equal_strict(value.get("launch_count"), run["launch_count"])
            and lifecycle.launch_count == run["launch_count"],
            "LaunchEvidenceMismatch",
        )
        if run["transport_state"] == "Completed":
            cleanup = value.get("cleanup", {})
            _require(
                type(value.get("exit_code")) is int
                and value["exit_code"] == 0
                and value.get("timed_out") is False
                and value.get("capture_state") == "complete"
                and type(cleanup) is dict
                and all(
                    cleanup.get(key) is True
                    for key in ("child_exit_observed", "pipes_closed", "job_closed")
                )
                and type(cleanup.get("thread_close_observations")) is list
                and all(item is True for item in cleanup["thread_close_observations"]),
                "LaunchEvidenceMismatch",
            )
        if run["transport_state"] == "TimedOut":
            _require(value.get("timed_out") is True, "LaunchEvidenceMismatch")
    elif ref == "config-restore.json":
        restored = run["restore_state"] == "Restored"
        _require(value.get("restored_original_bytes") is restored, "RestoreEvidenceMismatch")
        if restored:
            config = context["bundle"]["deployment_receipt"]["configuration"]["agy_settings"]
            _require(config is not None, "RestoreEvidenceMismatch")
            _require(
                value.get("status")
                in {"restored", "restored_already_original", "restored_json_legal_layout_drift"}
                and value.get("before_sha256") == config["sha256"]
                and value.get("final_sha256") == config["sha256"],
                "RestoreEvidenceMismatch",
            )
            _read_pinned(config)
            for filename, expected in (
                ("settings.original.bin", config["sha256"]),
                ("settings.patched.bin", value.get("patched_sha256")),
            ):
                _read_pinned(
                    {"path": str(roots["run_root"] / "private" / filename), "sha256": expected}
                )
    else:
        if ref == "first-execution.json":
            expected = context["first_execution"]
            _require(_digest(value) == expected["sha256"], "FirstExecutionChanged")
            task_run._verify_first_execution(
                expected, roots["task_root"], context["task"], context["plan"], roots["run_root"]
            )
            return
        task_run._object(value, {"exception_type", "launch_count"})
        task_run._text(value["exception_type"])
        _require(
            contract.deep_equal_strict(value["launch_count"], run["launch_count"]),
            "FailureEvidenceMismatch",
        )


def _saved_run(
    sheet: dict, roots: dict, context: dict, returned: dict | None
) -> tuple[dict, str, list]:
    value, raw = _saved_json(roots["run_root"] / "run.json")
    run = _checked_lifecycle_receipt(value, sheet)
    _require(returned is None or contract.deep_equal_strict(returned, run), "RunReturnMismatch")
    # Reference gaps must not erase the count from an otherwise bound run body.
    # B's shape checker preserves duplicate declarations for individual verification.
    task_workspace._evidence(run["evidence_refs"])
    task_workspace._tests(run["test_observations"])
    checks = []
    local_refs = set()
    opaque_refs = set()
    refs = list(run["evidence_refs"])
    refs.extend(evidence for test in run["test_observations"] for evidence in test["evidence_refs"])
    for evidence in refs:
        ref = evidence["ref"]
        if evidence["origin"] != "HostObserved":
            checks.append({**evidence, "check": "WorkerReportedUnverified"})
            continue
        task_run._hash(evidence["sha256"])
        if ref.startswith("session:"):
            _require(ref == "session:" + (run["capture_uid"] or ""), "SessionBindingMismatch")
            opaque_refs.add(ref)
            checks.append({**evidence, "check": "OpaqueDeclarationOnly"})
            continue
        # Never join unknown refs to a filesystem root, even when syntactically relative.
        _require(
            ref in {"launch.json", "config-restore.json", "lifecycle-failure.json"}
            or (sheet["contract_version"] == 3 and ref == "first-execution.json"),
            "RunEvidenceRefRejected",
        )
        evidence_value, evidence_raw = _saved_json(roots["run_root"] / ref)
        _require(task_run._digest(evidence_raw) == evidence["sha256"], "RunEvidenceDigestMismatch")
        _local_facts(ref, evidence_value, run, context, roots)
        local_refs.add(ref)
        checks.append(
            {**evidence, "actual_sha256": task_run._digest(evidence_raw), "check": "Match"}
        )
    if run["launch_count"] != 0 or run["transport_state"] == "Completed":
        _require("launch.json" in local_refs, "LaunchEvidenceMissing")
    if run["restore_state"] in {"Restored", "Failed"}:
        _require("config-restore.json" in local_refs, "RestoreEvidenceMissing")
    if run["capture_state"] == "Sealed":
        _require(bool(opaque_refs), "SessionBindingMismatch")
    if sheet["contract_version"] == 3:
        _require("first-execution.json" in local_refs, "FirstExecutionBindingMismatch")
    return run, task_run._digest(raw), checks


def _saved_collection(
    sheet: dict, roots: dict, context: dict, returned: dict, run: dict | None = None
) -> str:
    result, result_raw = _saved_json(roots["result_root"] / "result.json")
    _require(contract.deep_equal_strict(result, returned), "CollectionReturnMismatch")
    task_workspace._version(result)
    task = context["task"]
    _require(
        result["task_id"] == task["task_id"]
        and result["snapshot_id"] == task["snapshot_id"]
        and result["task_manifest_sha256"] == sheet["task_manifest_sha256"]
        and result["plan_sha256"]
        == (sheet["plan_sha256"] if sheet["contract_version"] == 3 else None)
        and result["management_decision"] is None,
        "CollectionBindingMismatch",
    )
    artifacts, artifact_raw = _saved_json(roots["result_root"] / "artifacts.json")
    changes, changes_raw = _saved_json(roots["result_root"] / "changes.json")
    _require(
        contract.deep_equal_strict(artifacts, result["artifacts"])
        and contract.deep_equal_strict(changes, result["changes"]),
        "ArtifactBindingMismatch",
    )
    expected = {
        "result.json": (len(result_raw), task_run._digest(result_raw)),
        "artifacts.json": (len(artifact_raw), task_run._digest(artifact_raw)),
        "changes.json": (len(changes_raw), task_run._digest(changes_raw)),
    }
    for artifact in task_run._list(artifacts):
        task_workspace._object(artifact, {"path", "bytes", "sha256", "origin"})
        relative = task_workspace._path(artifact["path"])
        task_workspace._integer(
            artifact["bytes"], 0, task["source_output_bytes_limit"] + task_run._JSON_LIMIT
        )
        task_workspace._hash(artifact["sha256"])
        task_workspace._enum(
            artifact["origin"], {"HostValidation", "WorkerOutput", "CandidateTree"}
        )
        _require(relative not in expected, "ArtifactBindingMismatch")
        expected[relative] = (artifact["bytes"], artifact["sha256"])
    deadline = task_run.task_input._Deadline.starting_now(sheet["deadline_seconds"])
    # The actual set and byte total must equal B's already bounded publication.
    files, result_directories = task_workspace._inventory(
        roots["result_root"], sum(size for size, _ in expected.values()), deadline
    )
    _require(files == expected, "ArtifactBindingMismatch")
    for relative, value in (
        ("host/control/plan.json", context["plan"]),
        ("host/control/deployment-receipt.json", context["bundle"]["deployment_receipt"]),
    ):
        frozen = task_run._canonical(value)
        _require(
            files.get(relative) == (len(frozen), task_run._digest(frozen)),
            "CollectedControlChanged",
        )
    candidate, directories = task_workspace._inventory(
        roots["result_root"] / "candidate", task["source_output_bytes_limit"], deadline
    )
    continuation = result["continuation"]
    _require(
        type(continuation) is dict
        and continuation["snapshot_id"] == task["snapshot_id"]
        and continuation["task_manifest_sha256"] == sheet["task_manifest_sha256"]
        and continuation["artifact_manifest_sha256"] == task_run._digest(artifact_raw)
        and continuation["candidate_tree_sha256"]
        == task_workspace._tree_sha(candidate, directories),
        "CollectionBindingMismatch",
    )
    if sheet["contract_version"] == 3:
        _require(
            run is not None and continuation["session_id"] == run["capture_uid"],
            "SessionBindingMismatch",
        )
    snapshot = task_run.task_input.read_snapshot(
        snapshot_root=roots["task_root"] / "control" / "snapshot"
    )
    baseline, baseline_dirs, _ = task_run.task_input._validate_snapshot_manifest(snapshot)
    work, work_dirs = task_workspace._inventory(
        roots["task_root"] / "work", task["source_output_bytes_limit"], deadline
    )
    generated = task_workspace._generated_work_roots(work_dirs, baseline, baseline_dirs)
    authored_work = {
        path: stamp for path, stamp in work.items() if not task_workspace._under(path, generated)
    }
    authored_directories = {
        path for path in work_dirs if not task_workspace._under(path, generated)
    }
    _require(
        task_workspace._tree_sha(authored_work, authored_directories)
        == continuation["candidate_tree_sha256"],
        "CollectedSourceChanged",
    )
    source_files = {
        ("generated/work/" if task_workspace._under(path, generated) else "candidate/")
        + path: stamp
        for path, stamp in work.items()
    }
    source_directories = {"candidate", "out", "scratch"}
    source_directories.update(
        ("generated/work/" if task_workspace._under(path, generated) else "candidate/") + path
        for path in work_dirs
    )
    for name in ("out", "scratch"):
        source, directories = task_workspace._inventory(
            roots["task_root"] / name, task["source_output_bytes_limit"], deadline
        )
        source_files.update({name + "/" + path: stamp for path, stamp in source.items()})
        source_directories.update(name + "/" + path for path in directories)
    collected_source = {
        artifact["path"]: files[artifact["path"]]
        for artifact in artifacts
        if artifact["origin"] in {"CandidateTree", "WorkerOutput"}
    }
    _require(source_files == collected_source, "CollectedSourceChanged")
    # B copies every source directory, creates its three roots, and creates only
    # the ancestors needed by copied directories and declared artifact files.
    expected_directories = source_directories | {
        "/".join(relative.split("/")[:index])
        for relative in expected.keys() | source_directories
        for index in range(1, len(relative.split("/")))
    }
    _require(result_directories == expected_directories, "CollectedDirectoriesChanged")
    return task_run._digest(result_raw)


def _final_context(
    sheet: dict, roots: dict, environment: dict, path: Path, expected: str, context: dict
) -> None:
    current = _sheet(path, expected)
    current_environment = _environment(current)
    _require(
        current == sheet
        and current_environment == environment
        and _roots(current, current_environment, path, initial=False) == roots,
        "PermitChanged",
    )
    _require(os.environ.get("LOCALAPPDATA") == str(roots["local_appdata"]), "EnvironmentUnverified")
    bundle = task_run.load_trusted_inputs(
        trusted_control_root=roots["trusted_control_root"],
        trusted_inputs_sha256=sheet["trusted_inputs_sha256"],
        task_root=roots["task_root"],
        run_root=roots["run_root"],
    )
    _require(
        contract.deep_equal_strict(bundle, context["bundle"])
        and task_run._read(roots["task_root"] / "task.json") == context["task"],
        "ControlChanged",
    )
    # Public B checks frozen controls/rules; Worker-authored source may legitimately change.
    task_workspace.verify_input_controls(
        task_root=roots["task_root"],
        task_manifest=context["task"],
        deployment_profile=bundle["deployment_profile"],
        authorization=bundle["authorization"],
    )
    _verify_context(sheet, roots, environment, context=context)


def _observation(
    sheet: dict,
    environment: dict,
    expected: str,
    run: dict | None,
    collection: dict | None,
    error: BaseException | None,
    *,
    launch_count: int | None,
    run_sha256: str | None,
    collection_sha256: str | None,
    evidence_checks: list,
    first_execution: dict | None = None,
    manager_evidence: dict | None = None,
) -> dict:
    recorded = (
        error is None
        and run_sha256 is not None
        and collection_sha256 is not None
        and run is not None
        and run["launch_count"] == 1
        and run["transport_state"] == "Completed"
        and run["capture_state"] == "Sealed"
        and run["restore_state"]
        in ({"Restored", "Unchanged"} if sheet["contract_version"] == 3 else {"Restored"})
        and run["blockers"] == ([] if sheet["contract_version"] == 3 else _expected_blockers(sheet))
        and collection is not None
        and collection["host_observations"]["scope_status"] == "Pass"
        and collection["host_observations"]["outputs_status"] == "Pass"
        and collection["host_observations"]["transport_state"]
        == ("Completed" if sheet["contract_version"] == 3 else "NotRun")
        and (
            sheet["contract_version"] != 3
            or (
                manager_evidence is not None
                and collection["blockers"] == []
                and collection["worker_status"] == "Completed"
            )
        )
    )
    observation = {
        "contract_version": sheet["contract_version"],
        "kind": "TaskRuntimeValidation",
        "permit_id": sheet["permit_id"],
        "task_id": sheet["task_id"],
        "permit_sha256": expected,
        "task_manifest_sha256": sheet["task_manifest_sha256"],
        "plan_sha256": sheet["plan_sha256"],
        "receipt_binding_sha256": sheet["receipt_binding_sha256"],
        "normal_plan_status": "Blocked",
        "status": "Interrupted"
        if error is not None and not isinstance(error, Exception)
        else "ObservationRecorded"
        if recorded
        else "Failed",
        "launch_count": launch_count,
        "run_receipt_sha256": run_sha256,
        "collection_sha256": collection_sha256,
        "run_evidence_checks": evidence_checks,
        "collection_mode": "BoundFirstExecution"
        if sheet["contract_version"] == 3
        else "ArtifactsOnlyNullRun",
        "error_code": _error_code(error) if error is not None else None,
        "runtime_acceptance": "Unverified",
        "management_decision": None,
    }
    if sheet["contract_version"] == 2:
        observation.update(
            host_composition=task_run.FIRST_OBSERVATION_COMPOSITION.copy(),
            expected_worker_shell=environment["worker_shell"],
            actual_worker_shell={"status": "Unknown", "identity": None},
            command_evidence_status="Unverified",
            acceptance_requirements=[
                "ActualWorkerShellIdentity",
                "RecipeCommandCompletionEvidence",
            ],
        )
    elif sheet["contract_version"] == 3:
        observation.update(
            acceptance_method=layered_acceptance.METHOD,
            layered_acceptance="Unverified",
            original_plan_blockers=_expected_blockers(sheet),
            first_execution=first_execution,
            manager_evidence=manager_evidence,
            strict_r_status="Unverified",
            actual_worker_shell={"status": "Unknown", "identity": None},
            command_evidence_status="Unverified",
        )
    return observation


def _new_first_execution(
    sheet: dict, sheet_path: Path, expected: str, roots: dict, context: dict
) -> dict:
    value = {
        "contract_version": 1,
        "kind": "LayeredFirstExecution",
        "permit_identity": {"path": str(sheet_path), "sha256": expected},
        "consumption_identity": {
            "path": str(roots["marker"]),
            "sha256": task_run._digest(task_run.read_host_input_bytes(path=str(roots["marker"]))),
        },
        "task_id": sheet["task_id"],
        "task_manifest_sha256": sheet["task_manifest_sha256"],
        "task_scope_sha256": layered_acceptance.scope_digest(context["task"]),
        "receipt_binding_sha256": sheet["receipt_binding_sha256"],
        "plan_sha256": sheet["plan_sha256"],
        "waived_blockers": sheet["waived_blockers"].copy(),
    }
    path = roots["run_root"] / "first-execution.json"
    task_run._persist(path, value)
    return {"path": str(path), "sha256": _digest(value)}


def _manager_report(path: Path, limit: int) -> tuple[dict, dict]:
    _require(path.stat().st_size <= limit, "ResourceLimitExceeded")
    raw = task_run.read_host_input_bytes(path=str(path))
    _require(
        len(raw) <= limit
        and b"\x00" not in raw
        and b"<!DOCTYPE" not in raw.upper()
        and b"<!ENTITY" not in raw.upper(),
        "ManagerReportInvalid",
    )
    try:
        suite = ET.fromstring(raw.decode("utf-8"))
        counts = {name: int(suite.attrib[name]) for name in ("tests", "failures", "errors")}
        cases = list(suite)
        _require(
            suite.tag == "testsuite"
            and all(case.tag == "testcase" for case in cases)
            and counts["tests"] == len(cases)
            and all(number >= 0 for number in counts.values())
            and int(suite.get("skipped", "0")) == 0
            and counts["failures"] == sum(len(case.findall("failure")) for case in cases)
            and counts["errors"] == sum(len(case.findall("error")) for case in cases)
            and all(child.tag in {"failure", "error"} for case in cases for child in case),
            "ManagerReportInvalid",
        )
    except (ET.ParseError, KeyError, ValueError) as error:
        raise ValidationError("ManagerReportInvalid") from error
    return counts, {"path": str(path), "sha256": task_run._digest(raw)}


def _manager_retests(sheet: dict, roots: dict, context: dict, collection: dict, run: dict) -> dict:
    """Two fixed management commands on isolated source copies; never Worker XML."""
    task = context["task"]
    policy = sheet["manager_retest"]
    parent = roots["manager_retest"]
    task_run._absolute(parent)
    parent.mkdir()
    recipe_identity = sheet["recipes"][0]["identity"]
    relative = Path(recipe_identity["path"]).relative_to(roots["task_root"]).as_posix()
    executable = sheet["installation"]["python"]
    tool = context["bundle"]["deployment_receipt"]["toolchains"][0]
    facts = {}
    for name, phase, source in (
        ("baseline", "reproduce", roots["task_root"] / "control/snapshot/source"),
        ("candidate", "regression", roots["result_root"] / "candidate"),
    ):
        stage = parent / name
        stage.mkdir()
        work = stage / "work"
        work.mkdir()
        (stage / "out").mkdir()
        deadline = task_run.task_input._Deadline.starting_now(policy["timeout_seconds"])
        files, directories = task_workspace._inventory(
            source, task["source_output_bytes_limit"], deadline
        )
        tree = task_workspace._tree_sha(files, directories)
        if name == "candidate":
            _require(
                tree == collection["continuation"]["candidate_tree_sha256"],
                "CollectedSourceChanged",
            )
        for directory in sorted(directories, key=lambda item: (item.count("/"), item)):
            (work / directory).mkdir()
        for filename, stamp in files.items():
            task_workspace._copy(source / filename, work / filename, stamp, deadline)
        _require(
            task_workspace._inventory(source, task["source_output_bytes_limit"], deadline)
            == (files, directories),
            "CollectedSourceChanged",
        )
        _read_pinned({"path": str(stage / relative), "sha256": recipe_identity["sha256"]})
        task_run._verify_file_identity(executable)
        _require(
            task_workspace._inventory(work, task["source_output_bytes_limit"], deadline)
            == (files, directories),
            "ManagerSourceChanged",
        )
        argv = [executable["path"], "-I", "-B", relative, phase]
        start = datetime.now(UTC).isoformat()
        try:
            process = subprocess.run(
                argv,
                cwd=str(stage),
                timeout=policy["timeout_seconds"],
                shell=False,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            end = datetime.now(UTC).isoformat()
            _require(type(process.returncode) is int, "ManagerRetestFailed")
            task_run._verify_file_identity(executable)
            _read_pinned({"path": str(stage / relative), "sha256": recipe_identity["sha256"]})
            _require(
                task_workspace._inventory(work, task["source_output_bytes_limit"], deadline)
                == (files, directories),
                "ManagerSourceChanged",
            )
            _require(
                task_workspace._inventory(source, task["source_output_bytes_limit"], deadline)
                == (files, directories),
                "CollectedSourceChanged",
            )
            counts, report = _manager_report(
                stage / "out" / (phase + ".xml"), task["source_output_bytes_limit"]
            )
            fact = {
                "actor": "ManagementIndependent",
                "task_id": task["task_id"],
                "source_tree_sha256": tree,
                "recipe_sha256": recipe_identity["sha256"],
                "toolchain_sha256": _digest(tool),
                "executable_identity": executable.copy(),
                "worker_shell_identity": None,
                "argv": argv,
                "cwd": str(stage),
                "start_utc": start,
                "end_utc": end,
                "exit_code": process.returncode,
                **counts,
            }
            task_run._persist(stage / "command.json", fact)
            task_run._persist(stage / "report-identity.json", report)
            _require(
                counts
                == {
                    "tests": policy[name + "_tests"],
                    "failures": 1 if name == "baseline" else 0,
                    "errors": 0,
                }
                and process.returncode == (1 if name == "baseline" else 0),
                "ManagerRetestFailed",
            )
            facts[name] = {"path": str(stage / "command.json"), "sha256": _digest(fact)}
        except BaseException as error:
            # A retained diagnostic must not replace the original interrupt/failure.
            with contextlib.suppress(BaseException):
                task_run._persist(
                    stage / "failure.json",
                    {
                        "phase": phase,
                        "exception_type": type(error).__name__,
                        "start_utc": start,
                        "end_utc": datetime.now(UTC).isoformat(),
                    },
                )
            raise
    candidate = task_run._read(Path(facts["candidate"]["path"]))
    recipes = {
        key: candidate[key]
        for key in ("recipe_sha256", "toolchain_sha256", "executable_identity", "argv", "cwd")
    }
    task_run._persist(parent / "recipes.json", recipes)
    launch, _ = _saved_json(roots["run_root"] / "launch.json")
    lifecycle = {
        **{
            key: run[key]
            for key in (
                "task_id",
                "plan_sha256",
                "transport_state",
                "launch_count",
                "capture_uid",
                "capture_state",
                "restore_state",
                "blockers",
            )
        },
        "exit_code": launch["exit_code"],
        "owned_process_cleanup": "Pass",
    }
    # _saved_run checked exit/cleanup facts; never promote an unchecked declaration.
    task_run._persist(parent / "host-lifecycle.json", lifecycle)
    facts.update(
        recipes={"path": str(parent / "recipes.json"), "sha256": _digest(recipes)},
        host_lifecycle={"path": str(parent / "host-lifecycle.json"), "sha256": _digest(lifecycle)},
    )
    return facts


def _saved_manager_evidence(
    identities: dict, context: dict, collection: dict, roots: dict, *, recipe_identity: dict
) -> None:
    task_run._object(identities, {"baseline", "candidate", "recipes", "host_lifecycle"})
    values = {
        name: contract.decode_strict_json_bytes(_read_pinned(identity), label="management evidence")
        for name, identity in identities.items()
    }
    task_run._object(values["baseline"], layered_acceptance.COMMAND_KEYS)
    task_run._object(values["host_lifecycle"], layered_acceptance.LIFECYCLE_KEYS)
    layered_acceptance._validate_recipe(values["recipes"], context["bundle"]["deployment_receipt"])
    _require(
        layered_acceptance._command_matches(
            values["candidate"],
            context["task"],
            collection["continuation"]["candidate_tree_sha256"],
            values["recipes"],
            "ManagementIndependent",
        ),
        "ManagerRetestBindingMismatch",
    )
    deadline = task_run.task_input._Deadline.starting_now(context["task"]["deadline_seconds"])
    files, directories = task_workspace._inventory(
        roots["task_root"] / "control/snapshot/source",
        context["task"]["source_output_bytes_limit"],
        deadline,
    )
    expected_trees = {
        "baseline": task_workspace._tree_sha(files, directories),
        "candidate": collection["continuation"]["candidate_tree_sha256"],
    }
    relative_recipe = task_run._absolute(recipe_identity["path"]).relative_to(roots["task_root"])
    for name, phase in (("baseline", "reproduce"), ("candidate", "regression")):
        stage = roots["manager_retest"] / name
        _require(
            Path(identities[name]["path"]) == stage / "command.json",
            "ManagerRetestBindingMismatch",
        )
        # Recheck retained work at the terminal boundary, from frozen roots and
        # permit recipe identity rather than paths declared in command facts.
        current_files, current_directories = task_workspace._inventory(
            stage / "work", context["task"]["source_output_bytes_limit"], deadline
        )
        _require(
            task_workspace._tree_sha(current_files, current_directories) == expected_trees[name],
            "ManagerSourceChanged",
        )
        _read_pinned({"path": str(stage / relative_recipe), "sha256": recipe_identity["sha256"]})
        counts, report = _manager_report(
            stage / "out" / (phase + ".xml"), context["task"]["source_output_bytes_limit"]
        )
        _require(
            task_run._read(stage / "report-identity.json") == report
            and all(values[name][key] == number for key, number in counts.items()),
            "ManagerRetestBindingMismatch",
        )
    baseline = values["baseline"]
    baseline_recipe = {
        **values["recipes"],
        "argv": [*values["recipes"]["argv"][:-1], "reproduce"],
        "cwd": str(roots["manager_retest"] / "baseline"),
    }
    _require(
        baseline["tests"] == baseline["failures"] == baseline["exit_code"] == 1
        and baseline["errors"] == 0
        and values["candidate"]["tests"] == 6
        and layered_acceptance._command_matches(
            {**baseline, "exit_code": 0, "failures": 0},
            context["task"],
            expected_trees["baseline"],
            baseline_recipe,
            "ManagementIndependent",
        ),
        "ManagerRetestBindingMismatch",
    )

    def evidence(name: str) -> dict:
        return {
            "value": values[name],
            "evidence_ref": {
                "ref": identities[name]["path"],
                "sha256": identities[name]["sha256"],
                "origin": "HostObserved",
            },
        }

    evaluation = layered_acceptance.evaluate_delivery(
        task=context["task"],
        receipt=context["bundle"]["deployment_receipt"],
        candidate_tree_sha256=collection["continuation"]["candidate_tree_sha256"],
        recipes=values["recipes"],
        collection={
            "value": collection,
            "evidence_ref": {
                "ref": "result.json",
                "sha256": _digest(collection),
                "origin": "HostObserved",
            },
        },
        manager_retest=evidence("candidate"),
        host_lifecycle=evidence("host_lifecycle"),
    )
    _require(evaluation["status"] == "Eligible", "ManagerRetestBindingMismatch")


def validate_once(*, sheet_path: Path, expected_sha256: str) -> dict:
    """Consume one trusted permit, retaining every failure; no automatic retry."""
    started = time.monotonic()
    sheet_path = task_run._absolute(sheet_path)
    sheet = _sheet(sheet_path, expected_sha256)
    environment = _environment(sheet)
    roots = _roots(sheet, environment, sheet_path, initial=True)
    initial_context, initial_plan = _verify_context(sheet, roots, environment)
    initial_context["plan"] = initial_plan
    marker = {
        "kind": "ConsumedTaskRuntimeValidationPermit",
        "permit_sha256": expected_sha256,
        "permit_id": sheet["permit_id"],
        "task_id": sheet["task_id"],
        "consumed_utc": datetime.now(UTC).isoformat(),
    }
    # Exclusive creation is the only consumption operation; partial markers stay consumed.
    try:
        task_run._absolute(roots["marker"])
        with roots["marker"].open("xb") as target:
            target.write(task_run._canonical(marker))
            target.flush()
    except FileExistsError as error:
        raise ValidationError("PermitConsumed") from error

    run = collection = None
    run_sha256 = collection_sha256 = None
    first_execution = manager_evidence = None
    evidence_checks = []
    launch_count = 0
    error = None
    called = owned_run = False
    previous_appdata = os.environ.get("LOCALAPPDATA")

    def recheck() -> dict:
        _require(time.monotonic() - started < sheet["deadline_seconds"], "DeadlineExceeded")
        current = _sheet(sheet_path, expected_sha256)
        current_environment = _environment(current)
        current_roots = _roots(current, current_environment, sheet_path, initial=False)
        _require(
            current == sheet and current_environment == environment and current_roots == roots,
            "PermitChanged",
        )
        context, _ = _verify_context(current, current_roots, current_environment)
        # Read/merge only after explicit consumption and all other gates; never weaken deny/restore.
        task_run._read_configuration(context)
        if first_execution is not None:
            task_run._verify_first_execution(
                first_execution,
                roots["task_root"],
                context["task"],
                initial_plan,
                roots["run_root"],
            )
        return context

    try:
        task_run._absolute(roots["run_root"])
        roots["run_root"].mkdir()
        owned_run = True
        task_run._absolute(roots["local_appdata"])
        roots["local_appdata"].mkdir()
        os.environ["LOCALAPPDATA"] = str(roots["local_appdata"])
        context = recheck()
        plan = task_run._read(roots["task_root"] / "control" / "plan.json")
        if sheet["contract_version"] == 3:
            first_execution = _new_first_execution(
                sheet, sheet_path, expected_sha256, roots, context
            )
            initial_context["first_execution"] = first_execution
        called = True
        launch_count = None
        if first_execution is None:
            run = task_run._execute_once(context, plan, roots["run_root"], recheck, started)
        else:
            run = task_run._execute_once(
                context, plan, roots["run_root"], recheck, started, first_execution=first_execution
            )
    except BaseException as caught:
        error = caught
    finally:
        try:
            if owned_run:
                launch_count = _launch_fact(run, launch_count)
                if called and launch_count is None:
                    # No definite C return: only a bound, valid body may supply a count.
                    with contextlib.suppress(BaseException):
                        saved, _ = _saved_json(roots["run_root"] / "run.json")
                        launch_count = _checked_lifecycle_receipt(saved, sheet)["launch_count"]
                    # Either checked source can confirm execution. A local zero/unknown
                    # or an evidence gap cannot erase a bound body's confirmed launch.
                    with contextlib.suppress(BaseException):
                        local_count = _saved_launch_fact(roots)
                        if local_count == 1 or launch_count is None:
                            launch_count = local_count
                try:
                    run, run_sha256, evidence_checks = _saved_run(
                        sheet, roots, initial_context, run
                    )
                except BaseException as secondary:
                    if error is None:
                        error = secondary
                if called:
                    try:
                        collection = task_workspace.collect_task(
                            task_root=roots["task_root"],
                            # Legacy observations retain null-run collection. V3
                            # explicitly binds its separately permitted first execution.
                            run_root=roots["run_root"] if first_execution is not None else None,
                            result_root=roots["result_root"],
                            **(
                                {"first_execution": first_execution}
                                if first_execution is not None
                                else {}
                            ),
                        )
                        collection_sha256 = _saved_collection(
                            sheet, roots, initial_context, collection, run
                        )
                        _final_context(
                            sheet, roots, environment, sheet_path, expected_sha256, initial_context
                        )
                        # Collect must not create a window in which run/evidence can drift.
                        saved_run, saved_sha256, saved_checks = _saved_run(
                            sheet, roots, initial_context, run
                        )
                        _require(saved_sha256 == run_sha256, "RunEvidenceChanged")
                        run, evidence_checks = saved_run, saved_checks
                        if sheet["contract_version"] == 3 and error is None:
                            _require(
                                run["launch_count"] == 1
                                and run["transport_state"] == "Completed"
                                and run["capture_state"] == "Sealed"
                                and run["restore_state"] in {"Restored", "Unchanged"}
                                and run["blockers"] == []
                                and collection["blockers"] == []
                                and collection["worker_status"] == "Completed",
                                "FirstExecutionFailed",
                            )
                            manager_evidence = _manager_retests(
                                sheet, roots, initial_context, collection, run
                            )
                            _final_context(
                                sheet,
                                roots,
                                environment,
                                sheet_path,
                                expected_sha256,
                                initial_context,
                            )
                            _require(
                                _saved_collection(sheet, roots, initial_context, collection, run)
                                == collection_sha256,
                                "CollectionReturnMismatch",
                            )
                            _require(
                                _saved_run(sheet, roots, initial_context, run)[1] == run_sha256,
                                "RunEvidenceChanged",
                            )
                            _saved_manager_evidence(
                                manager_evidence,
                                initial_context,
                                collection,
                                roots,
                                recipe_identity=sheet["recipes"][0]["identity"],
                            )
                    except BaseException as secondary:
                        run_sha256 = collection_sha256 = None
                        if error is None:
                            error = secondary
                observation = _observation(
                    sheet,
                    environment,
                    expected_sha256,
                    run,
                    collection,
                    error,
                    launch_count=launch_count,
                    run_sha256=run_sha256,
                    collection_sha256=collection_sha256,
                    evidence_checks=evidence_checks,
                    first_execution=first_execution,
                    manager_evidence=manager_evidence,
                )
                try:
                    task_run._persist(roots["run_root"] / "validation.json", observation)
                except BaseException as secondary:
                    if error is None:
                        error = secondary
        finally:
            if previous_appdata is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous_appdata
    if error is not None and not isinstance(error, Exception):
        raise error
    return _observation(
        sheet,
        environment,
        expected_sha256,
        run,
        collection,
        error,
        launch_count=launch_count,
        run_sha256=run_sha256,
        collection_sha256=collection_sha256,
        evidence_checks=evidence_checks,
        first_execution=first_execution,
        manager_evidence=manager_evidence,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--acceptance-sheet", required=True)
    parser.add_argument("--expected-sha256", required=True)
    arguments = parser.parse_args(argv)
    try:
        result = validate_once(
            sheet_path=Path(arguments.acceptance_sheet), expected_sha256=arguments.expected_sha256
        )
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        result = {
            "kind": "TaskRuntimeValidation",
            "status": "Blocked",
            "error_code": _error_code(error),
            "runtime_acceptance": "Unverified",
        }
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0 if result["status"] == "ObservationRecorded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
