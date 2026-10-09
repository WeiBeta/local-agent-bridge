"""Explicit, narrow trusted Coding acceptance, independent of strict runtime R.

This module performs no IO. Evidence and authority come from the management
caller, not from hashes or self-assigned origin labels. Evaluation produces an
eligible candidate, never a production Accepted record or Worker execution.
"""

from __future__ import annotations

from datetime import datetime

METHOD = "trusted_coding_v1"
COMPOSITION = {"status": "Unknown", "scope": "FixedEntryKnown"}
CAPABILITIES = {"execute": True, "web_reference": False, "prepare_dependencies": False}
REQUIRED_LAYERS = ("code_delivery", "manager_retest", "host_lifecycle")
LAYERS = {*REQUIRED_LAYERS, "worker_execution"}
EVALUATION_KEYS = {
    "contract_version",
    "acceptance_method",
    "receipt_binding_sha256",
    "task_scope_sha256",
    "candidate_tree_sha256",
    "layers",
    "status",
    "strict_r_status",
}
RECORD_KEYS = {
    "role",
    "capabilities",
    "execution_boundary",
    "receipt_binding_sha256",
    "task_scope_sha256",
    "status",
    "evaluation",
    "management_acceptance_ref",
}
COMMAND_KEYS = {
    "actor",
    "task_id",
    "source_tree_sha256",
    "recipe_sha256",
    "toolchain_sha256",
    "executable_identity",
    "worker_shell_identity",
    "argv",
    "cwd",
    "start_utc",
    "end_utc",
    "exit_code",
    "tests",
    "failures",
    "errors",
}
LIFECYCLE_KEYS = {
    "task_id",
    "plan_sha256",
    "transport_state",
    "launch_count",
    "capture_uid",
    "capture_state",
    "restore_state",
    "owned_process_cleanup",
    "exit_code",
    "blockers",
}
COLLECTION_KEYS = {
    "contract_version",
    "task_id",
    "snapshot_id",
    "task_manifest_sha256",
    "plan_sha256",
    "worker_status",
    "host_observations",
    "changes",
    "artifacts",
    "blockers",
    "continuation",
    "management_decision",
}
CONTINUATION_KEYS = {
    "snapshot_id",
    "candidate_tree_sha256",
    "artifact_manifest_sha256",
    "task_manifest_sha256",
    "remaining_acceptance_ids",
    "remaining_paths",
    "last_test_run_id",
    "blocker",
    "next_action",
    "session_id",
}
CHANGE_KEYS = {
    "path",
    "kind",
    "before",
    "after",
    "rename_from",
}


def scope_digest(task: dict) -> str:
    """Exact task projection; omit only circular profile/authorization digests."""
    from . import task_run as runner

    return runner._digest(
        runner._canonical(
            {
                key: value
                for key, value in task.items()
                if key not in {"deployment_profile_sha256", "authorization_sha256"}
            }
        )
    )


def receipt_binding(receipt: dict) -> str:
    from . import task_run as runner

    return runner._digest(
        runner._canonical(
            {
                key: value
                for key, value in receipt.items()
                if key not in {"runtime_acceptances", "layered_acceptances", "provenance_refs"}
            }
        )
    )


def _status(layers: dict) -> str:
    required = [layers[name] for name in REQUIRED_LAYERS]
    if any(layer["result"] == "Fail" for layer in required):
        return "Blocked"
    if all(
        layer["result"] == "Pass" and layer["origin"] == "HostObserved" and layer["evidence_refs"]
        for layer in required
    ):
        return "Eligible"
    return "Unverified"


def validate_evaluation(value: dict) -> None:
    from . import task_run as runner

    runner._object(value, EVALUATION_KEYS)
    runner._version(value)
    if value["acceptance_method"] != METHOD or value["strict_r_status"] != "Unverified":
        raise runner.TaskRunError("InvalidContract")
    for key in ("receipt_binding_sha256", "task_scope_sha256", "candidate_tree_sha256"):
        runner._hash(value[key])
    runner._object(value["layers"], LAYERS)
    for name, layer in value["layers"].items():
        runner._object(layer, {"result", "origin", "evidence_refs"})
        runner._enum(layer["result"], {"Pass", "Fail", "Unknown"})
        origins = {"Unknown", "HostObserved"}
        if name == "worker_execution":
            origins |= {"WorkerReported", "CliDeclared"}
        runner._enum(layer["origin"], origins)
        _refs(layer["evidence_refs"])
        if layer["origin"] == "Unknown":
            if layer["result"] != "Unknown" or layer["evidence_refs"]:
                raise runner.TaskRunError("InvalidContract")
        elif (
            layer["origin"] == "HostObserved" and not runner._observed(layer["evidence_refs"])
        ) or any(ref["origin"] != layer["origin"] for ref in layer["evidence_refs"]):
            raise runner.TaskRunError("InvalidContract")
        if (
            name == "worker_execution"
            and layer["origin"] != "HostObserved"
            and layer["result"] != "Unknown"
        ):
            raise runner.TaskRunError("InvalidContract")
    if value["status"] != _status(value["layers"]):
        raise runner.TaskRunError("InvalidContract")


def validate_records(records: list) -> None:
    from . import task_run as runner

    seen = []
    for record in runner._list(records):
        runner._object(record, RECORD_KEYS)
        if (
            record["role"] != "Coding"
            or runner._caps(record["capabilities"]) != CAPABILITIES
            or record["execution_boundary"] != "declared_scope"
        ):
            raise runner.TaskRunError("InvalidContract")
        for key in ("receipt_binding_sha256", "task_scope_sha256"):
            runner._hash(record[key])
        runner._enum(record["status"], {"Accepted", "Blocked", "Unverified"})
        validate_evaluation(record["evaluation"])
        if any(
            record[key] != record["evaluation"][key]
            for key in ("receipt_binding_sha256", "task_scope_sha256")
        ):
            raise runner.TaskRunError("InvalidContract")
        runner._evidence([record["management_acceptance_ref"]])
        if record["status"] == "Accepted" and (
            record["evaluation"]["status"] != "Eligible"
            or not runner._observed([record["management_acceptance_ref"]])
        ):
            raise runner.TaskRunError("InvalidContract")
        seen.append(record["task_scope_sha256"])
    if seen != sorted(set(seen)):
        raise runner.TaskRunError("InvalidContract")


def _refs(value: list) -> None:
    from . import task_run as runner

    for ref in runner._list(value):
        runner._object(ref, {"ref", "sha256", "origin"})
        runner._text(ref["ref"])
        runner._hash(ref["sha256"])
        runner._enum(ref["origin"], {"HostObserved", "WorkerReported", "CliDeclared"})
    runner._strings([ref["ref"] for ref in value])


def _evidence(item: dict | None) -> tuple[dict | None, dict | None]:
    from . import task_run as runner

    if item is None:
        return None, None
    runner._object(item, {"value", "evidence_ref"})
    ref = item["evidence_ref"]
    _refs([ref])
    if type(item["value"]) is not dict or ref["sha256"] != runner._digest(
        runner._canonical(item["value"])
    ):
        raise runner.TaskRunError("EvidenceBindingMismatch")
    return item["value"], ref


def _layer(result: str = "Unknown", ref: dict | None = None) -> dict:
    return {
        "result": result,
        "origin": "Unknown" if ref is None else ref["origin"],
        "evidence_refs": [] if ref is None else [ref.copy()],
    }


def _command_matches(value: dict, task: dict, candidate: str, recipes: dict, actor: str) -> bool:
    from . import task_run as runner

    runner._object(value, COMMAND_KEYS)
    for key in ("source_tree_sha256", "recipe_sha256", "toolchain_sha256"):
        runner._hash(value[key])
    runner._identity(value["executable_identity"])
    shell_valid = (
        value["worker_shell_identity"] is None if actor == "ManagementIndependent" else False
    )

    if actor == "Worker" and value["worker_shell_identity"] is not None:
        runner._identity(value["worker_shell_identity"])
        shell_valid = True
    runner._text(value["actor"])
    runner._text(value["task_id"])
    if type(value["argv"]) is not list or not value["argv"]:
        raise runner.TaskRunError("InvalidContract")
    for argument in value["argv"]:
        runner._text(argument)
    runner.task_input._validate_absolute_path(value["cwd"], label="retest cwd")
    for key in ("exit_code", "tests", "failures", "errors"):
        if type(value[key]) is not int or (key != "exit_code" and value[key] < 0):
            raise runner.TaskRunError("InvalidContract")
    try:
        start = datetime.fromisoformat(runner._text(value["start_utc"]))
        end = datetime.fromisoformat(runner._text(value["end_utc"]))
        times_valid = start.utcoffset() is not None and end.utcoffset() is not None and end >= start
    except ValueError:
        times_valid = False
    return (
        value["actor"] == actor
        and value["task_id"] == task["task_id"]
        and value["source_tree_sha256"] == candidate
        and value["recipe_sha256"] == recipes["recipe_sha256"]
        and value["toolchain_sha256"] == recipes["toolchain_sha256"]
        and value["executable_identity"] == recipes["executable_identity"]
        and value["argv"] == recipes["argv"]
        and value["cwd"] == recipes["cwd"]
        and times_valid
        and shell_valid
        and value["exit_code"] == 0
        and value["tests"] > 0
        and value["failures"] == value["errors"] == 0
    )


def _validate_recipe(recipes: dict, receipt: dict) -> None:
    from . import task_run as runner

    runner._object(
        recipes, {"recipe_sha256", "toolchain_sha256", "executable_identity", "argv", "cwd"}
    )
    for key in ("recipe_sha256", "toolchain_sha256"):
        runner._hash(recipes[key])
    runner._identity(recipes["executable_identity"])
    if type(recipes["argv"]) is not list or not recipes["argv"]:
        raise runner.TaskRunError("InvalidContract")
    for argument in recipes["argv"]:
        runner._text(argument)
    runner.task_input._validate_absolute_path(recipes["cwd"], label="retest cwd")
    if recipes["argv"][0] != recipes["executable_identity"]["path"] or not any(
        runner._digest(runner._canonical(tool)) == recipes["toolchain_sha256"]
        and recipes["executable_identity"] in tool["identity_files"]
        for tool in receipt["toolchains"]
    ):
        raise runner.TaskRunError("ToolchainUnverified")


def evaluate_delivery(
    *,
    task: dict,
    receipt: dict,
    candidate_tree_sha256: str,
    recipes: dict,
    collection: dict | None,
    manager_retest: dict | None,
    host_lifecycle: dict | None,
    worker_execution: dict | None = None,
    worker_recipe: dict | None = None,
) -> dict:
    """Evaluate management-pinned synthetic or real evidence without producing authority.

    Each evidence input is {value, evidence_ref}; sha256 binds canonical value.
    recipes is a separately management-frozen regression command. No XML content
    or CLI declaration is treated as an independent management process result.
    """
    from . import task_run as runner

    runner._validate_task(task)
    runner._validate_receipt(receipt)
    if receipt["contract_version"] != 3 or task["role"] != "Coding":
        raise runner.TaskRunError("InvalidContract")
    if task["capabilities"] != CAPABILITIES or task["execution_boundary"] != "declared_scope":
        raise runner.TaskRunError("InvalidContract")
    runner._hash(candidate_tree_sha256)
    _validate_recipe(recipes, receipt)
    if worker_recipe is not None:
        _validate_recipe(worker_recipe, receipt)
    layers = {name: _layer() for name in LAYERS}
    collected, ref = _evidence(collection)
    if collected is not None:
        runner._object(collected, COLLECTION_KEYS)
        runner._version(collected)
        runner._object(
            collected["host_observations"],
            {
                "transport_state",
                "scope_status",
                "outputs_status",
                "coverage_status",
                "test_observations",
                "acceptance_observations",
            },
        )
        runner.task_workspace._tests(collected["host_observations"]["test_observations"])
        runner._strings(collected["blockers"])
        try:
            change_paths = []
            for change in runner._list(collected["changes"]):
                runner._object(change, CHANGE_KEYS)
                change_paths.append(change["path"])
                runner._enum(change["kind"], {"added", "modified", "deleted"})
                for stamp in (change["before"], change["after"]):
                    if stamp is not None:
                        runner._object(stamp, {"bytes", "sha256"})
                        if type(stamp["bytes"]) is not int or stamp["bytes"] < 0:
                            raise runner.TaskRunError("InvalidContract")
                        runner._hash(stamp["sha256"])
                if change["rename_from"] is not None:
                    runner._strings([change["rename_from"]], relative=True)
            runner._strings(change_paths, relative=True)
        except runner.task_input.TaskInputError as error:
            raise runner.TaskRunError("InvalidContract") from error
        for artifact in runner._list(collected["artifacts"]):
            runner._object(artifact, {"path", "bytes", "sha256", "origin"})
            runner._strings([artifact["path"]], relative=True)
            runner._hash(artifact["sha256"])
            if type(artifact["bytes"]) is not int or artifact["bytes"] < 0:
                raise runner.TaskRunError("InvalidContract")
            runner._enum(artifact["origin"], {"WorkerOutput", "CandidateTree", "HostValidation"})
        if collected["continuation"] is not None:
            runner._object(collected["continuation"], CONTINUATION_KEYS)
    if collected is not None and ref["origin"] == "HostObserved":
        continuation = collected.get("continuation")
        observations = collected["host_observations"]
        passed = (
            collected.get("contract_version") == 1
            and collected.get("task_id") == task["task_id"]
            and collected.get("snapshot_id") == task["snapshot_id"]
            and collected.get("task_manifest_sha256") == runner._digest(runner._canonical(task))
            and collected.get("worker_status") == "Completed"
            and collected.get("blockers") == []
            and observations.get("scope_status") == observations.get("outputs_status") == "Pass"
            and type(continuation) is dict
            and continuation.get("candidate_tree_sha256") == candidate_tree_sha256
            and continuation.get("task_manifest_sha256") == collected["task_manifest_sha256"]
            and continuation.get("snapshot_id") == task["snapshot_id"]
            and continuation.get("artifact_manifest_sha256")
            == runner._digest(runner._canonical(collected["artifacts"]))
            and continuation.get("remaining_paths") == []
        )
        layers["code_delivery"] = _layer("Pass" if passed else "Fail", ref)
    retest, ref = _evidence(manager_retest)
    if retest is not None and ref["origin"] == "HostObserved":
        passed = _command_matches(
            retest, task, candidate_tree_sha256, recipes, "ManagementIndependent"
        )
        layers["manager_retest"] = _layer("Pass" if passed else "Fail", ref)
    lifecycle, ref = _evidence(host_lifecycle)
    if lifecycle is not None and ref["origin"] == "HostObserved":
        runner._object(lifecycle, LIFECYCLE_KEYS)
        runner._hash(lifecycle["plan_sha256"])
        passed = (
            lifecycle["task_id"] == task["task_id"]
            and lifecycle["transport_state"] == "Completed"
            and type(lifecycle["launch_count"]) is int
            and lifecycle["launch_count"] == 1
            and type(lifecycle["exit_code"]) is int
            and lifecycle["exit_code"] == 0
            and type(lifecycle["capture_uid"]) is str
            and bool(lifecycle["capture_uid"])
            and lifecycle["capture_state"] == "Sealed"
            and lifecycle["restore_state"] in {"Unchanged", "Restored"}
            and lifecycle["owned_process_cleanup"] == "Pass"
            and lifecycle["blockers"] == []
            and collected is not None
            and collected.get("plan_sha256") == lifecycle["plan_sha256"]
            and type(collected.get("continuation")) is dict
            and collected["continuation"]["session_id"] == lifecycle["capture_uid"]
        )
        unknown = (
            lifecycle["launch_count"] is None
            or lifecycle["owned_process_cleanup"] == "Unknown"
            or lifecycle["transport_state"] == "NotRun"
        )
        failed = (
            lifecycle["transport_state"] in {"Failed", "TimedOut"}
            or lifecycle["capture_state"] == "Incomplete"
            or lifecycle["restore_state"] == "Failed"
            or lifecycle["owned_process_cleanup"] == "Fail"
            or (type(lifecycle["exit_code"]) is int and lifecycle["exit_code"] != 0)
            or bool(lifecycle["blockers"])
        )
        result = "Pass" if passed else "Unknown" if unknown and not failed else "Fail"
        layers["host_lifecycle"] = _layer(result, ref)
    execution, ref = _evidence(worker_execution)
    if execution is not None:
        if ref["origin"] == "HostObserved":
            expected = recipes if worker_recipe is None else worker_recipe
            passed = _command_matches(execution, task, candidate_tree_sha256, expected, "Worker")
            result = (
                "Unknown"
                if worker_recipe is None or execution["worker_shell_identity"] is None
                else "Pass"
                if passed
                else "Fail"
            )
            layers["worker_execution"] = _layer(result, ref)
        else:
            layers["worker_execution"] = _layer(ref=ref)
    result = {
        "contract_version": 1,
        "acceptance_method": METHOD,
        "receipt_binding_sha256": receipt_binding(receipt),
        "task_scope_sha256": scope_digest(task),
        "candidate_tree_sha256": candidate_tree_sha256,
        "layers": layers,
        "status": _status(layers),
        "strict_r_status": "Unverified",
    }
    validate_evaluation(result)
    return result
