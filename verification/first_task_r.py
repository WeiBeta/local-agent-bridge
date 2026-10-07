"""One trusted, frozen Task runtime validation; never a production run or R verdict.

This sdist-only program has no host/model/argv override and no offline bypass.
Unit tests inject fake lifecycle boundaries; actual use requires a separately
approved management permit and a non-editable, frozen wheel installation.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from local_agent_bridge.bridge import contract, paths, task_run, task_workspace

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
    task_run._object(sheet, SHEET_FIELDS)
    task_run._version(sheet)
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
        type(sheet["deadline_seconds"]) is int and 1 <= sheet["deadline_seconds"] <= 1020,
        "PermitInvalid",
    )
    permissions = task_run._object(sheet["permissions"], PERMISSIONS)
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
    return sheet


def _environment(sheet: dict) -> dict:
    raw = _read_pinned(sheet["environment"])
    value = contract.decode_strict_json_bytes(raw, label="runtime validation environment")
    task_run._object(value, {"contract_version", "kind", "local_appdata", "worker_shell"})
    task_run._version(value)
    _require(value["kind"] == "TaskRuntimeValidationEnvironment", "EnvironmentUnverified")
    task_run._absolute(value["local_appdata"])
    task_run._identity(value["worker_shell"])
    task_run._verify_file_identity(value["worker_shell"])
    return value


def _overlaps(left: Path, right: Path) -> bool:
    return paths._is_within(left, right) or paths._is_within(right, left)


def _roots(sheet: dict, environment: dict, sheet_path: Path, *, initial: bool) -> dict[str, Path]:
    roots = {
        key: task_run._absolute(sheet[key])
        for key in ("task_root", "trusted_control_root", "run_root", "result_root")
    }
    roots["installation"] = task_run._directory(task_run._absolute(sheet["installation"]["root"]))
    roots["local_appdata"] = task_run._absolute(environment["local_appdata"])
    for key, root in roots.items():
        task_run._directory(root.parent)
        if root.exists():
            task_run._directory(root)
        if initial and key in {"run_root", "result_root", "local_appdata"}:
            _require(not os.path.lexists(root), "OutputExists")
    for index, left in enumerate(roots.values()):
        for right in list(roots.values())[index + 1 :]:
            _require(not _overlaps(left, right), "ValidationRootRejected")
    mutable = [roots[key] for key in ("task_root", "run_root", "result_root", "local_appdata")]
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
        not any(
            _overlaps(roots[key], code_root) for key in ("run_root", "result_root", "local_appdata")
        ),
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


def _verify_context(sheet: dict, roots: dict, environment: dict) -> tuple[dict, dict]:
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
    _require(
        receipt["host"] == "agy" and receipt["runtime_acceptances"] == [], "ValidationScopeRejected"
    )
    binding = _digest(
        {
            key: value
            for key, value in receipt.items()
            if key not in {"runtime_acceptances", "provenance_refs"}
        }
    )
    _require(
        binding == sheet["receipt_binding_sha256"]
        and _digest(task) == sheet["task_manifest_sha256"],
        "PermitBindingMismatch",
    )
    plan = task_run._make_plan(context, "agy")
    _require(
        plan["preflight_status"] == "Blocked" and plan["blockers"] == [MISSING_R], "NonRGateBlocked"
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
    """Check independent lifecycle facts, without claiming B accepts a normal run."""
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
    task_run._strings(value["blockers"])
    task_run._evidence(value["evidence_refs"])
    task_workspace._tests(value["test_observations"])
    _require(
        count is not None
        or (value["transport_state"] == "Failed" and "LaunchUnverified" in value["blockers"]),
        "RunReceiptInvalid",
    )
    _require(value["transport_state"] != "Completed" or count == 1, "RunReceiptInvalid")
    _require(
        value["capture_state"] != "Sealed"
        or (type(value["capture_uid"]) is str and bool(value["capture_uid"])),
        "RunReceiptInvalid",
    )
    return value


def _observation(
    sheet: dict,
    expected: str,
    run: dict | None,
    collection: dict | None,
    error: BaseException | None,
    *,
    called: bool,
) -> dict:
    recorded = (
        error is None
        and run is not None
        and run["launch_count"] == 1
        and run["transport_state"] == "Completed"
        and run["capture_state"] == "Sealed"
        and run["restore_state"] == "Restored"
        and run["blockers"] == [MISSING_R]
        and collection is not None
        and collection["host_observations"]["scope_status"] == "Pass"
        and collection["host_observations"]["outputs_status"] == "Pass"
        and collection["host_observations"]["transport_state"] == "NotRun"
    )
    return {
        "contract_version": 1,
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
        "launch_count": run["launch_count"] if run is not None else None if called else 0,
        "run_receipt_sha256": _digest(run) if run is not None else None,
        "collection_sha256": _digest(collection) if collection is not None else None,
        "collection_mode": "ArtifactsOnlyNullRun",
        "error_code": _error_code(error) if error is not None else None,
        "runtime_acceptance": "Unverified",
        "management_decision": None,
    }


def validate_once(*, sheet_path: Path, expected_sha256: str) -> dict:
    """Consume one trusted permit, retaining every failure; no automatic retry."""
    started = time.monotonic()
    sheet_path = task_run._absolute(sheet_path)
    sheet = _sheet(sheet_path, expected_sha256)
    environment = _environment(sheet)
    roots = _roots(sheet, environment, sheet_path, initial=True)
    _verify_context(sheet, roots, environment)
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
        called = True
        run = task_run._execute_once(context, plan, roots["run_root"], recheck, started)
    except BaseException as caught:
        error = caught
    finally:
        try:
            if owned_run:
                try:
                    if run is None and (roots["run_root"] / "run.json").exists():
                        run = task_run._read(roots["run_root"] / "run.json")
                    if run is not None:
                        run = _checked_lifecycle_receipt(run, sheet)
                except BaseException as secondary:
                    run = None
                    if error is None:
                        error = secondary
                if run is not None:
                    try:
                        collection = task_workspace.collect_task(
                            task_root=roots["task_root"],
                            # B rejects any ordinary Blocked-Plan launch receipt.
                            # Collect artifacts through its existing null-run API;
                            # the validation lifecycle remains separate, unaccepted evidence.
                            run_root=None,
                            result_root=roots["result_root"],
                        )
                    except BaseException as secondary:
                        if error is None:
                            error = secondary
                observation = _observation(
                    sheet, expected_sha256, run, collection, error, called=called
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
    return _observation(sheet, expected_sha256, run, collection, error, called=called)


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
