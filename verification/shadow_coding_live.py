"""One task-specific Shadow execution, reusing the existing product lifecycle.

This reviewed source-only validator produces scoped evidence for management. It
does not publish a runtime acceptance or turn CLI-origin facts into HostObserved.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# -I intentionally excludes the script directory. Only the frozen sibling
# verification code is added; the product still comes from the bound installation.
sys.path.insert(0, str(Path(__file__).absolute().parent))
import first_task_r as lifecycle
import shadow_coding_r as retests
import shadow_worker_results as native
import shadow_worker_tests as wrapper

from local_agent_bridge.bridge import (
    contract,
    layered_acceptance,
    paths,
    task_run,
    task_workspace,
)
from local_agent_bridge.capture.keys import load_key

_require = lifecycle._require
_digest = lifecycle._digest
_read_pinned = lifecycle._read_pinned
_verify_installation = lifecycle._verify_installation
CAPABILITIES = lifecycle.CAPABILITIES
RECIPE_REF = retests.RECIPE_REF
MANAGEMENT_TASK = lifecycle.MANAGEMENT_TASK
PERMISSIONS = lifecycle.PERMISSIONS
BUDGET = {
    "host_launches": 1,
    "worker_public_runs": 2,
    "manager_public_runs": 2,
    "manager_private_runs": 1,
    "capture_key_reads": 1,
    "reader_key_reads": 1,
    "stdout_authentications": 1,
    "test_timeout_seconds": 10,
    "deadline_seconds": 300,
    "extra_egress": False,
}
VERIFIERS = {
    "shadow_coding_live.py",
    "shadow_coding_r.py",
    "shadow_worker_tests.py",
    "shadow_worker_results.py",
    "first_task_r.py",
    "agy_stdout_reanalysis.py",
}


def _task_contract(sheet: dict, roots: dict) -> dict:
    budget = sheet["budget_ref"]
    _require(budget["origin"] == "HostObserved", "BudgetUnverified")
    identity = {"path": budget["ref"], "sha256": budget["sha256"]}
    path = task_run._absolute(identity["path"])
    _require(
        not any(paths._is_within(path, root) for root in roots.values()), "ContractRootRejected"
    )
    value = contract.decode_strict_json_bytes(_read_pinned(identity), label="Shadow task contract")
    task_run._object(
        value,
        {
            "contract_version",
            "kind",
            "task_id",
            "input_files",
            "acceptance_recipe",
            "verifiers",
            "budget",
        },
    )
    _require(
        type(value["contract_version"]) is int
        and value["contract_version"] == 1
        and value["kind"] == "ShadowCodingContract"
        and value["task_id"] == sheet["task_id"],
        "ContractBindingMismatch",
    )
    _require(
        contract.deep_equal_strict(value["budget"], BUDGET)
        and sheet["deadline_seconds"] == BUDGET["deadline_seconds"],
        "BudgetUnverified",
    )
    verifiers = task_run._list(value["verifiers"])
    _require(len(verifiers) == len(VERIFIERS), "VerifierChanged")
    expected_paths = {str(Path(__file__).absolute().parent / name) for name in VERIFIERS}
    _require(
        {item.get("path") for item in verifiers if type(item) is dict} == expected_paths,
        "VerifierChanged",
    )
    for verifier in verifiers:
        _read_pinned(verifier)
    input_files = task_run._list(value["input_files"])
    _require(len(input_files) == 4, "InputManifestChanged")
    expected_files = {}
    for item in input_files:
        task_run._object(item, {"path", "bytes", "sha256"})
        task_run._hash(item["sha256"])
        _require(
            type(item["bytes"]) is int
            and 0 < item["bytes"] <= retests.MAX_BYTES
            and item["path"] not in expected_files,
            "InputManifestChanged",
        )
        expected_files[item["path"]] = (item["bytes"], item["sha256"])
    wrapper_sha = expected_files.get("recipe/shadow_worker_tests.py", (0, None))[1]
    _require(
        wrapper_sha is not None
        and wrapper_sha == retests._identity(Path(wrapper.__file__).absolute())["sha256"],
        "WrapperChanged",
    )
    baseline = roots["task_root"] / "control/snapshot/source"
    files, _ = retests._source(
        baseline, retests.MAX_BYTES, baseline=True, wrapper_sha256=wrapper_sha
    )
    _require(files == expected_files, "InputManifestChanged")
    retests._source(
        roots["task_root"] / "work", retests.MAX_BYTES, baseline=False, wrapper_sha256=wrapper_sha
    )
    recipe = task_run._directory(task_run._absolute(value["acceptance_recipe"]))
    task_run.task_input._reject_broad_root(recipe, "Shadow acceptance recipe")
    _require(
        not any(lifecycle._overlaps(recipe, root) for root in roots.values()),
        "PrivateRecipeExposed",
    )
    retests._recipe(recipe, retests.MAX_BYTES)
    return value


def _sheet(path: Path, expected: str) -> dict:
    task_run._hash(expected)
    raw = task_run.read_host_input_bytes(path=str(path))
    _require(task_run._digest(raw) == expected, "PermitChanged")
    sheet = contract.decode_strict_json_bytes(raw, label="Shadow runtime permit")
    task_run._object(sheet, task_run.FIRST_LAYERED_PERMIT_KEYS)
    task_run._caps(sheet["capabilities"])
    _require(
        type(sheet["contract_version"]) is int
        and sheet["contract_version"] == 3
        and sheet["kind"] == "TaskRuntimeValidationPermit",
        "PermitInvalid",
    )
    _require(
        sheet["approval"] == {"status": "Approved", "author_confirmed": True}
        and type(sheet["approval"]["author_confirmed"]) is bool,
        "PermissionUnverified",
    )
    _require(
        sheet["management_task_id"] == MANAGEMENT_TASK
        and sheet["host"] == "agy"
        and sheet["role"] == "Coding"
        and sheet["capabilities"] == CAPABILITIES
        and sheet["execution_boundary"] == "declared_scope",
        "ValidationScopeRejected",
    )
    _require(
        type(sheet["max_host_launches"]) is int and sheet["max_host_launches"] == 1, "PermitInvalid"
    )
    task_run._text(sheet["permit_id"])
    _require(
        lifecycle.re.fullmatch(r"[A-Za-z0-9_-]{1,64}", sheet["permit_id"]) is not None,
        "PermitInvalid",
    )
    for key in ("task_id", "grant_ref"):
        task_run._text(sheet[key])
    for key in (
        "task_manifest_sha256",
        "plan_sha256",
        "trusted_inputs_sha256",
        "receipt_binding_sha256",
    ):
        task_run._hash(sheet[key])
    _require(
        type(sheet["deadline_seconds"]) is int and sheet["deadline_seconds"] == 300,
        "BudgetUnverified",
    )
    permissions = task_run._object(sheet["permissions"], PERMISSIONS | {"management_local_retest"})
    _require(
        all(type(flag) is bool and flag for flag in permissions.values()), "PermissionUnverified"
    )
    _require(
        sheet["acceptance_method"] == layered_acceptance.METHOD
        and sheet["waived_blockers"] == [task_run.FIRST_LAYERED_BLOCKER],
        "ValidationScopeRejected",
    )
    task_run._evidence([sheet["budget_ref"]])
    _require(Path(sheet["validator"]["path"]) == Path(__file__).absolute(), "ValidatorChanged")
    _read_pinned(sheet["validator"])
    task_run._object(sheet["installation"], {"root", "python", "wheel"})
    for key in ("python", "wheel"):
        task_run._identity(sheet["installation"][key])
    task_run._identity(sheet["environment"])
    recipes = task_run._list(sheet["recipes"])
    _require(len(recipes) == 1, "RecipeUnverified")
    recipe = task_run._object(recipes[0], {"ref", "identity"})
    _require(recipe["ref"] == RECIPE_REF, "RecipeUnverified")
    task_run._identity(recipe["identity"])
    retest = task_run._object(
        sheet["manager_retest"], {"root", "timeout_seconds", "baseline_tests", "candidate_tests"}
    )
    task_run._absolute(retest["root"])
    _require(
        all(
            type(retest[key]) is int
            for key in ("timeout_seconds", "baseline_tests", "candidate_tests")
        )
        and (retest["timeout_seconds"], retest["baseline_tests"], retest["candidate_tests"])
        == (10, 8, 8),
        "RecipeUnverified",
    )
    return sheet


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
    auth = context["bundle"]["authorization"]
    _require(
        task["task_id"] == sheet["task_id"]
        and auth["grant_ref"] == sheet["grant_ref"]
        and task["deadline_seconds"] == sheet["deadline_seconds"],
        "PermitBindingMismatch",
    )
    _require(
        task["role"] == "Coding"
        and task["capabilities"] == auth["capabilities"] == CAPABILITIES
        and task["execution_boundary"] == "declared_scope"
        and profile["roles"] == ["Coding"]
        and profile["supported_capabilities"] == CAPABILITIES
        and profile["execution_modes"] == ["declared_scope"],
        "ValidationScopeRejected",
    )
    _require(
        receipt["host"] == "agy"
        and receipt["contract_version"] == 3
        and receipt["runtime_acceptances"] == receipt["layered_acceptances"] == [],
        "ValidationScopeRejected",
    )
    _require(
        layered_acceptance.receipt_binding(receipt) == sheet["receipt_binding_sha256"]
        and _digest(task) == sheet["task_manifest_sha256"],
        "PermitBindingMismatch",
    )
    plan = task_run._make_plan(context, "agy")
    _require(
        plan["preflight_status"] == "Blocked"
        and plan["blockers"] == [task_run.FIRST_LAYERED_BLOCKER],
        "NonRGateBlocked",
    )
    _require(
        _digest(plan) == sheet["plan_sha256"]
        and task_run._read(roots["task_root"] / "control/plan.json") == plan
        and task_run._read(roots["task_root"] / "control/deployment-receipt.json") == receipt,
        "ControlChanged",
    )
    _require(
        {
            "ref": sheet["environment"]["path"],
            "sha256": sheet["environment"]["sha256"],
            "origin": "HostObserved",
        }
        in profile["enforcement"]["evidence_refs"]
        and environment["local_appdata"] == str(roots["local_appdata"]),
        "EnvironmentUnverified",
    )
    recipe = sheet["recipes"][0]["identity"]
    _require(
        Path(recipe["path"]) == roots["task_root"] / "work/recipe/run_tests.py", "RecipeUnverified"
    )
    _read_pinned(recipe)
    _require(
        recipe["sha256"] == retests.RECIPE_HASHES["run_tests.py"]
        and any(
            task_run.task_input._scope_covers(path, "work/recipe")
            for path in task["protected_paths"]
        ),
        "RecipeUnverified",
    )
    tools = receipt["toolchains"]
    _require(
        len(tools) == 1
        and tools[0]["recipe_refs"] == [RECIPE_REF]
        and tools[0]["identity_files"] == [sheet["installation"]["python"]],
        "ToolchainUnverified",
    )
    task_contract = _task_contract(sheet, roots)
    context["shadow_contract"] = task_contract
    context["shadow_wrapper_sha256"] = next(
        item["sha256"]
        for item in task_contract["input_files"]
        if item["path"] == "recipe/shadow_worker_tests.py"
    )
    _verify_installation(sheet, receipt)
    return context, plan


def _final_context(
    sheet: dict, roots: dict, environment: dict, path: Path, expected: str, context: dict
) -> None:
    current = _sheet(path, expected)
    current_environment = lifecycle._environment(current)
    _require(
        current == sheet
        and current_environment == environment
        and lifecycle._roots(current, current_environment, path, initial=False) == roots,
        "PermitChanged",
    )
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
    task_workspace.verify_input_controls(
        task_root=roots["task_root"],
        task_manifest=context["task"],
        deployment_profile=bundle["deployment_profile"],
        authorization=bundle["authorization"],
    )
    _verify_context(sheet, roots, environment, context=context)


def expectations(context: dict, roots: dict, collection: dict) -> tuple[dict, dict]:
    commands, summaries = {}, {}
    python = context["bundle"]["deployment_receipt"]["toolchains"][0]["identity_files"][0]
    for phase in ("reproduce", "regression"):
        source = roots["task_root"] / "work"
        output = roots["task_root"] / "out/worker-tests" / phase
        files, directories = retests._source(
            roots["task_root"] / "control/snapshot/source"
            if phase == "reproduce"
            else roots["result_root"] / "candidate",
            retests.MAX_BYTES,
            baseline=phase == "reproduce",
            wrapper_sha256=context["shadow_wrapper_sha256"],
        )
        tree = task_workspace._tree_sha(files, directories)
        if phase == "regression":
            _require(
                tree == collection["continuation"]["candidate_tree_sha256"],
                "CollectedSourceChanged",
            )
        manager_phase = "baseline_public" if phase == "reproduce" else "candidate_public"
        counts, report = retests._report(
            roots["result_root"] / "out/worker-tests" / phase / "report/tests.xml", manager_phase
        )
        _require(counts == retests._counts(manager_phase), "WorkerReportChanged")
        argv = [
            python["path"],
            "-I",
            "-B",
            str(source / "recipe/shadow_worker_tests.py"),
            "--task-id",
            context["task"]["task_id"],
            "--phase",
            phase,
            "--source",
            str(source),
            "--out",
            str(output),
        ]
        commands[phase] = native.command_line(argv)
        summaries[phase] = {
            "contract_version": 1,
            "kind": "ShadowPublicResult",
            "task_id": context["task"]["task_id"],
            "phase": phase,
            "source_tree_sha256": tree,
            "source_files": {
                name: {"bytes": stamp[0], "sha256": stamp[1]} for name, stamp in files.items()
            },
            "recipe_sha256": retests.RECIPE_HASHES["run_tests.py"],
            "python_sha256": python["sha256"],
            "argv": [
                python["path"],
                "-I",
                "-B",
                str(source / "recipe/run_tests.py"),
                "--source",
                str(source),
                "--out",
                str(output / "report"),
                "--suite",
                "public",
            ],
            "cwd": str(source),
            "exit_code": 1 if phase == "reproduce" else 0,
            **counts,
            "skipped": 0,
            "case_ids": wrapper.CASES.copy(),
            "report_sha256": report["sha256"],
        }
    return commands, summaries


def _worker_evidence(context: dict, roots: dict, run: dict, collection: dict) -> dict:
    commands, summaries = expectations(context, roots, collection)
    value = native.read_capture_once(
        bundle=roots["local_appdata"] / "LocalAgentBridge/sessions" / run["capture_uid"],
        uid=run["capture_uid"],
        output=roots["run_root"] / "shadow-reader",
        commands=commands,
        summaries=summaries,
        key_loader=load_key,
    )
    if value["status"] == "CliPublicTestsMatch":
        for phase in ("reproduce", "regression"):
            raw = task_run.read_host_input_bytes(
                path=str(roots["result_root"] / "out/worker-tests" / phase / "summary.json")
            )
            summary = native.bounded._json(raw)
            _require(
                native.bounded._sha(native.bounded._canonical(summary))
                == value["phases"][phase]["summary_sha256"],
                "CliSummaryFileConflict",
            )
    return {
        "identity": retests._identity(roots["run_root"] / "shadow-reader/result.json"),
        "value": value,
    }


def _observation(
    sheet: dict,
    expected: str,
    run: dict | None,
    collection: dict | None,
    error: BaseException | None,
    *,
    launch_count: int | None,
    run_sha256: str | None,
    collection_sha256: str | None,
    manager_evidence: dict | None,
    worker_evidence: dict | None,
) -> dict:
    return {
        "contract_version": 1,
        "kind": "ShadowCodingObservation",
        "task_id": sheet["task_id"],
        "permit_sha256": expected,
        "status": "EvidenceReadyForManagement"
        if error is None and worker_evidence is not None
        else "Stopped",
        "error_code": lifecycle._error_code(error) if error is not None else None,
        "launch_count": launch_count,
        "run_sha256": run_sha256,
        "collection_sha256": collection_sha256,
        "transport_state": run["transport_state"] if run else "Unknown",
        "capture_state": run["capture_state"] if run else "Unknown",
        "restore_state": run["restore_state"] if run else "Unknown",
        "manager_evidence": manager_evidence,
        "worker_evidence": worker_evidence,
        "worker_execution": "Unknown",
        "runtime_acceptance": "Unverified",
        "accepted": False,
    }


def validate_once(*, sheet_path: Path, expected_sha256: str) -> dict:
    """Consume once, execute once, collect once, retain errors and restore env."""
    started = time.monotonic()
    sheet_path = task_run._absolute(sheet_path)
    sheet = _sheet(sheet_path, expected_sha256)
    environment = lifecycle._environment(sheet)
    roots = lifecycle._roots(sheet, environment, sheet_path, initial=True)
    context, plan = _verify_context(sheet, roots, environment)
    context["plan"] = plan
    marker = {
        "kind": "ConsumedTaskRuntimeValidationPermit",
        "permit_sha256": expected_sha256,
        "permit_id": sheet["permit_id"],
        "task_id": sheet["task_id"],
        "consumed_utc": datetime.now(UTC).isoformat(),
    }
    try:
        with roots["marker"].open("xb") as target:
            target.write(task_run._canonical(marker))
            target.flush()
    except FileExistsError as error:
        raise lifecycle.ValidationError("PermitConsumed") from error
    run = collection = first_execution = manager_evidence = worker_evidence = None
    run_sha256 = collection_sha256 = None
    launch_count = 0
    called = owned_run = False
    error = None
    previous_appdata = os.environ.get("LOCALAPPDATA")

    def recheck() -> dict:
        _require(time.monotonic() - started < sheet["deadline_seconds"], "DeadlineExceeded")
        _final_context(sheet, roots, environment, sheet_path, expected_sha256, context)
        task_run._read_configuration(context)
        if first_execution is not None:
            task_run._verify_first_execution(
                first_execution, roots["task_root"], context["task"], plan, roots["run_root"]
            )
        return context

    try:
        try:
            roots["run_root"].mkdir()
            owned_run = True
            roots["local_appdata"].mkdir()
            os.environ["LOCALAPPDATA"] = str(roots["local_appdata"])
            recheck()
            first_execution = lifecycle._new_first_execution(
                sheet, sheet_path, expected_sha256, roots, context
            )
            context["first_execution"] = first_execution
            called = True
            launch_count = None
            run = task_run._execute_once(
                context, plan, roots["run_root"], recheck, started, first_execution=first_execution
            )
        except BaseException as caught:
            error = caught  # Save before fallible evidence/collection/restore work.
        finally:
            if owned_run:
                launch_count = lifecycle._launch_fact(run, launch_count)
                if called and launch_count is None:
                    with contextlib.suppress(BaseException):
                        saved, _ = lifecycle._saved_json(roots["run_root"] / "run.json")
                        launch_count = lifecycle._checked_lifecycle_receipt(saved, sheet)[
                            "launch_count"
                        ]
                    with contextlib.suppress(BaseException):
                        local_count = lifecycle._saved_launch_fact(roots)
                        if local_count == 1 or launch_count is None:
                            launch_count = local_count
                try:
                    run, run_sha256, _ = lifecycle._saved_run(sheet, roots, context, run)
                except BaseException as secondary:
                    if error is None:
                        error = secondary
                if called:
                    try:
                        collection = task_workspace.collect_task(
                            task_root=roots["task_root"],
                            run_root=roots["run_root"],
                            result_root=roots["result_root"],
                            first_execution=first_execution,
                        )
                        collection_sha256 = lifecycle._saved_collection(
                            sheet, roots, context, collection, run
                        )
                        _final_context(
                            sheet, roots, environment, sheet_path, expected_sha256, context
                        )
                        _require(
                            lifecycle._saved_run(sheet, roots, context, run)[1] == run_sha256,
                            "RunEvidenceChanged",
                        )
                        if error is None:
                            _require(
                                run["launch_count"] == 1
                                and run["transport_state"] == "Completed"
                                and run["capture_state"] == "Sealed"
                                and run["restore_state"] in {"Restored", "Unchanged"}
                                and run["blockers"] == collection["blockers"] == []
                                and collection["worker_status"] == "Completed",
                                "FirstExecutionFailed",
                            )
                            recipe_root = Path(context["shadow_contract"]["acceptance_recipe"])
                            manager_evidence = retests.run_manager_retests(
                                context=context,
                                roots=roots,
                                collection=collection,
                                recipe_root=recipe_root,
                            )
                            worker_evidence = _worker_evidence(context, roots, run, collection)
                            _require(
                                worker_evidence["value"]["status"] == "CliPublicTestsMatch",
                                "CliEvidenceUnknown",
                            )
                            _final_context(
                                sheet, roots, environment, sheet_path, expected_sha256, context
                            )
                            _require(
                                lifecycle._saved_collection(sheet, roots, context, collection, run)
                                == collection_sha256
                                and lifecycle._saved_run(sheet, roots, context, run)[1]
                                == run_sha256,
                                "EvidenceChanged",
                            )
                            retests.read_manager_evidence(
                                identities=manager_evidence,
                                context=context,
                                roots=roots,
                                collection=collection,
                                recipe_root=recipe_root,
                            )
                    except BaseException as secondary:
                        if error is None:
                            error = secondary
    finally:
        try:
            if previous_appdata is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous_appdata
        except BaseException as secondary:
            if error is None:
                error = secondary
            if owned_run:
                with contextlib.suppress(BaseException):
                    task_run._persist(
                        roots["run_root"] / "environment-restore-failure.json",
                        {"exception_type": type(secondary).__name__},
                    )
    if owned_run:
        # Freeze the terminal observation after every owned restore attempt.
        # An environment restore failure must not leave a saved Ready result.
        try:
            task_run._persist(
                roots["run_root"] / "shadow-validation.json",
                _observation(
                    sheet,
                    expected_sha256,
                    run,
                    collection,
                    error,
                    launch_count=launch_count,
                    run_sha256=run_sha256,
                    collection_sha256=collection_sha256,
                    manager_evidence=manager_evidence,
                    worker_evidence=worker_evidence,
                ),
            )
        except BaseException as secondary:
            if error is None:
                error = secondary
    if error is not None and not isinstance(error, Exception):
        raise error
    return _observation(
        sheet,
        expected_sha256,
        run,
        collection,
        error,
        launch_count=launch_count,
        run_sha256=run_sha256,
        collection_sha256=collection_sha256,
        manager_evidence=manager_evidence,
        worker_evidence=worker_evidence,
    )


def read_saved(*, sheet_path: Path, expected_sha256: str, observation_sha256: str) -> dict:
    """Recheck saved bindings without execute, permit consumption or key access."""
    sheet = _sheet(sheet_path, expected_sha256)
    environment = lifecycle._environment(sheet)
    roots = lifecycle._roots(sheet, environment, sheet_path, initial=False)
    # The initial loader correctly requires the prepared work tree to equal the
    # snapshot. Saved candidates have changed legitimately: reload only frozen
    # controls, then apply public control and collected-candidate checks below.
    bundle = task_run.load_trusted_inputs(
        trusted_control_root=roots["trusted_control_root"],
        trusted_inputs_sha256=sheet["trusted_inputs_sha256"],
        task_root=roots["task_root"],
        run_root=roots["run_root"],
    )
    task = task_run._read(roots["task_root"] / "task.json")
    task_run._validate_task(task)
    for key, filename in (
        ("deployment_profile", "deployment-profile.json"),
        ("authorization", "authorization.json"),
    ):
        _require(
            task_run._read(roots["task_root"] / "control" / filename) == bundle[key],
            "ControlChanged",
        )
    note = task_run.read_host_input_bytes(path=str(roots["task_root"] / "control/TASK.md"))
    _require(task_run._digest(note) == task["instructions_sha256"], "ControlChanged")
    context = {"task": task, "bundle": bundle, "note": note, "task_root": roots["task_root"]}
    context, plan = _verify_context(sheet, roots, environment, context=context)
    context["plan"] = plan
    context["first_execution"] = retests._identity(roots["run_root"] / "first-execution.json")
    task_run._verify_first_execution(
        context["first_execution"], roots["task_root"], context["task"], plan, roots["run_root"]
    )
    task_run._hash(observation_sha256)
    raw = _read_pinned(
        {"path": str(roots["run_root"] / "shadow-validation.json"), "sha256": observation_sha256}
    )
    saved = contract.decode_strict_json_bytes(raw, label="frozen Shadow observation")
    _require(
        saved["kind"] == "ShadowCodingObservation"
        and saved["task_id"] == sheet["task_id"]
        and saved["permit_sha256"] == expected_sha256
        and saved["accepted"] is False
        and saved["worker_execution"] == "Unknown",
        "ObservationChanged",
    )
    run, run_sha, _ = lifecycle._saved_run(sheet, roots, context, None)
    collection, _ = lifecycle._saved_json(roots["result_root"] / "result.json")
    collection_sha = lifecycle._saved_collection(sheet, roots, context, collection, run)
    _require(
        (run_sha, collection_sha) == (saved["run_sha256"], saved["collection_sha256"]),
        "EvidenceChanged",
    )
    _final_context(sheet, roots, environment, sheet_path, expected_sha256, context)
    if saved["manager_evidence"] is not None:
        retests.read_manager_evidence(
            identities=saved["manager_evidence"],
            context=context,
            roots=roots,
            collection=collection,
            recipe_root=Path(context["shadow_contract"]["acceptance_recipe"]),
        )
    if saved["worker_evidence"] is not None:
        worker = saved["worker_evidence"]
        _require(
            Path(worker["identity"]["path"]) == roots["run_root"] / "shadow-reader/result.json",
            "EvidencePathChanged",
        )
        _require(
            contract.decode_strict_json_bytes(
                _read_pinned(worker["identity"]), label="CLI evidence"
            )
            == worker["value"]
            and worker["value"]["capture_uid"] == run["capture_uid"],
            "CliEvidenceChanged",
        )
    if saved["status"] == "EvidenceReadyForManagement":
        _require(
            saved["error_code"] is None
            and saved["launch_count"] == run["launch_count"] == 1
            and saved["manager_evidence"] is not None
            and saved["worker_evidence"]["value"]["status"] == "CliPublicTestsMatch",
            "ObservationChanged",
        )
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--permit", type=Path, required=True)
    parser.add_argument("--permit-sha256", required=True)
    parser.add_argument("--saved", action="store_true")
    parser.add_argument("--observation-sha256")
    options = parser.parse_args(argv)
    try:
        if options.saved:
            result = read_saved(
                sheet_path=options.permit,
                expected_sha256=options.permit_sha256,
                observation_sha256=options.observation_sha256,
            )
        else:
            _require(options.observation_sha256 is None, "UnexpectedSavedBinding")
            result = validate_once(sheet_path=options.permit, expected_sha256=options.permit_sha256)
    except Exception as error:
        result = {
            "status": "Stopped",
            "error_code": lifecycle._error_code(error),
            "launch_count": None,
            "accepted": False,
        }
    sys.stdout.write(task_run._canonical(result).decode() + "\n")
    return 0 if result["status"] == "EvidenceReadyForManagement" else 2


if __name__ == "__main__":
    raise SystemExit(main())
