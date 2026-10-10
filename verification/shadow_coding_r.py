"""Management-only retests for the frozen Shadow PPTX package task.

This source-only component is not a launch permit or a Worker evidence producer.
The live entry point deliberately stops before touching the existing lifecycle.
After separately reviewed integration, a trusted caller may use the two retest
functions after first_task_r has checked run and collection evidence.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from local_agent_bridge.bridge import contract, layered_acceptance, task_run, task_workspace

RECIPE_REF = "shadow_pptx_package_v1"
TIMEOUT_SECONDS = 10
MAX_BYTES = 8 * 1024 * 1024
REPORT_MAX_BYTES = 512 * 1024
BASELINE_TOOL_SHA256 = "fdecaccf115229e86c834dcaa30e533bf0bc2869625c02009da49d1a9e9285cd"
RECIPE_HASHES = {
    "run_tests.py": "9e7a261b7221e6f2218445c73a4930faf45eeb7b34f450c5aad68c644cde4a11",
    "public_tests.py": "811d8d292d9e7e4e42d52a4b8b3c376c1749a3f6812c306a9a803d7bb5106562",
    "private_tests.py": "8e5111bf62799e4f72a4cb9d15c3c43a5a53c96313148c18644879f5cbb1ae23",
}
PUBLIC_CASES = frozenset(
    "public_tests.PublicPackageTests." + name
    for name in (
        "test_valid_archive_and_input_digest",
        "test_default_range_has_numeric_source_order",
        "test_sparse_inclusive_filter",
        "test_repeatable_json_bytes",
        "test_corrupt_archive_rejected",
        "test_invalid_range_rejected",
        "test_missing_opc_marker_rejected",
        "test_escaping_member_rejected",
    )
)
PRIVATE_CASES = frozenset(
    "private_tests.PrivatePackageTests." + name
    for name in (
        "test_large_sparse_upper_bound_is_finite",
        "test_multiple_inputs_index_and_source_bytes",
    )
)
PHASES = ("baseline_public", "candidate_public", "candidate_private")


class RetestError(RuntimeError):
    """Fixed, non-sensitive failure code; original evidence is retained."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise RetestError(code)


def _digest(value: object) -> str:
    return task_run._digest(task_run._canonical(value))


def _identity(path: Path) -> dict:
    raw = task_run.read_host_input_bytes(path=str(path))
    return {"path": str(path), "sha256": task_run._digest(raw)}


def _pinned(identity: dict) -> bytes:
    task_run._identity(identity)
    raw = task_run.read_host_input_bytes(path=identity["path"])
    _require(task_run._digest(raw) == identity["sha256"], "EvidenceChanged")
    return raw


def _inventory(root: Path, limit: int) -> tuple[dict, set]:
    return task_workspace._inventory(
        root, limit, task_run.task_input._Deadline.starting_now(TIMEOUT_SECONDS)
    )


def _source(root: Path, limit: int, *, baseline: bool) -> tuple[dict, set]:
    files, directories = _inventory(root, limit)
    _require(
        set(files) == {"tool.py", "recipe/run_tests.py", "recipe/public_tests.py"}
        and directories == {"recipe"},
        "SourceScopeChanged",
    )
    for name in ("run_tests.py", "public_tests.py"):
        _require(files["recipe/" + name][1] == RECIPE_HASHES[name], "RecipeChanged")
    if baseline:
        _require(files["tool.py"][1] == BASELINE_TOOL_SHA256, "BaselineChanged")
    return files, directories


def _recipe(root: Path, limit: int) -> tuple[dict, set]:
    files, directories = _inventory(root, limit)
    _require(set(files) == set(RECIPE_HASHES) and not directories, "RecipeScopeChanged")
    _require(
        all(files[name][1] == digest for name, digest in RECIPE_HASHES.items()),
        "RecipeChanged",
    )
    return files, directories


def _inputs(context: dict, roots: dict, collection: dict, recipe_root: Path) -> dict:
    """Bind retest inputs; the caller remains responsible for lifecycle authority."""
    task = context["task"]
    receipt = context["bundle"]["deployment_receipt"]
    task_run._text(task["task_id"])
    limit = task["source_output_bytes_limit"]
    _require(type(limit) is int and 1 <= limit <= MAX_BYTES, "ResourceLimitExceeded")
    parent = task_run._absolute(roots["manager_retest"])
    _require(
        parent not in {Path(parent.anchor), *task_run.task_input._broad_user_roots()},
        "RetestRootRejected",
    )
    if parent.exists():
        task_run.task_input._reject_broad_root(parent, "management retest root")
    baseline = task_run._directory(roots["task_root"] / "control/snapshot/source")
    candidate = task_run._directory(roots["result_root"] / "candidate")
    recipe = task_run._directory(recipe_root)
    # All four roots must be disjoint. Recipe and retained evidence never enter
    # the source copy, and an output root cannot overwrite either source tree.
    for i, left in enumerate((parent, baseline, candidate, recipe)):
        for right in (parent, baseline, candidate, recipe)[i + 1 :]:
            _require(
                not left.is_relative_to(right) and not right.is_relative_to(left),
                "RetestRootOverlap",
            )
    tools = receipt["toolchains"]
    _require(
        len(tools) == 1
        and tools[0]["recipe_refs"] == [RECIPE_REF]
        and len(tools[0]["identity_files"]) == 1,
        "ToolchainUnverified",
    )
    executable = tools[0]["identity_files"][0]
    task_run._verify_file_identity(executable)
    base_files, base_dirs = _source(baseline, limit, baseline=True)
    final_files, final_dirs = _source(candidate, limit, baseline=False)
    candidate_tree = task_workspace._tree_sha(final_files, final_dirs)
    _require(
        collection["task_id"] == task["task_id"]
        and candidate_tree == collection["continuation"]["candidate_tree_sha256"],
        "CollectedSourceChanged",
    )
    _recipe(recipe, limit)
    return {
        "task_id": task["task_id"],
        "task_sha256": _digest(task),
        "receipt_sha256": _digest(receipt),
        "collection_sha256": _digest(collection),
        "baseline_source": str(baseline),
        "candidate_source": str(candidate),
        "baseline_tree_sha256": task_workspace._tree_sha(base_files, base_dirs),
        "candidate_tree_sha256": candidate_tree,
        "recipe_root": str(recipe),
        "output_root": str(parent),
        "executable_identity": executable.copy(),
        "toolchain_sha256": _digest(tools[0]),
        "source_output_bytes_limit": limit,
        "timeout_seconds": TIMEOUT_SECONDS,
        "recipe_hashes": RECIPE_HASHES.copy(),
    }


def _command(binding: dict, phase: str) -> dict:
    stage = Path(binding["output_root"]) / phase
    return {
        "recipe_sha256": RECIPE_HASHES["run_tests.py"],
        "toolchain_sha256": binding["toolchain_sha256"],
        "executable_identity": binding["executable_identity"].copy(),
        "argv": [
            binding["executable_identity"]["path"],
            "-I",
            "-B",
            str(stage / "acceptance/run_tests.py"),
            "--source",
            str(stage / "work"),
            "--out",
            str(stage / "out"),
            "--suite",
            "private" if phase == "candidate_private" else "public",
        ],
        "cwd": str(stage),
    }


def _counts(phase: str) -> dict:
    return {
        "tests": 2 if phase == "candidate_private" else 8,
        "failures": 0,
        "errors": 4 if phase == "baseline_public" else 0,
    }


def _report(path: Path, phase: str) -> tuple[dict, dict]:
    _require(path.stat().st_size <= REPORT_MAX_BYTES, "ResourceLimitExceeded")
    raw = task_run.read_host_input_bytes(path=str(path))
    _require(
        len(raw) <= REPORT_MAX_BYTES
        and b"\x00" not in raw
        and b"<!DOCTYPE" not in raw.upper()
        and b"<!ENTITY" not in raw.upper(),
        "ManagerReportInvalid",
    )
    try:
        suite = ET.fromstring(raw.decode("utf-8"))
        counts = {key: int(suite.attrib[key]) for key in ("tests", "failures", "errors")}
        cases = list(suite)
        expected_names = PRIVATE_CASES if phase == "candidate_private" else PUBLIC_CASES
        _require(
            suite.tag == "testsuite"
            and set(suite.attrib) == {"tests", "failures", "errors", "skipped"}
            and int(suite.attrib["skipped"]) == 0
            and counts == _counts(phase)
            and len(cases) == counts["tests"]
            and {case.get("name") for case in cases} == expected_names
            and all(case.tag == "testcase" and set(case.attrib) == {"name"} for case in cases)
            and all(len(case) <= 1 for case in cases)
            and all(child.tag in {"error", "failure"} for case in cases for child in case)
            and counts["errors"] == sum(len(case.findall("error")) for case in cases)
            and counts["failures"] == sum(len(case.findall("failure")) for case in cases),
            "ManagerReportInvalid",
        )
    except (ET.ParseError, UnicodeError, KeyError, ValueError) as error:
        raise RetestError("ManagerReportInvalid") from error
    return counts, {"path": str(path), "sha256": task_run._digest(raw)}


def _copy_tree(source: Path, target: Path, limit: int) -> tuple[dict, set]:
    files, directories = _inventory(source, limit)
    target.mkdir()
    deadline = task_run.task_input._Deadline.starting_now(TIMEOUT_SECONDS)
    for directory in sorted(directories, key=lambda item: (item.count("/"), item)):
        (target / directory).mkdir()
    for name, stamp in files.items():
        task_workspace._copy(source / name, target / name, stamp, deadline)
    _require(_inventory(source, limit) == (files, directories), "RetestInputChanged")
    _require(_inventory(target, limit) == (files, directories), "ManagerSourceChanged")
    return files, directories


def run_manager_retests(*, context: dict, roots: dict, collection: dict, recipe_root: Path) -> dict:
    """Three fixed management subprocesses. No Worker/host launch or acceptance."""
    binding = _inputs(context, roots, collection, recipe_root)
    parent = Path(binding["output_root"])
    parent.mkdir()  # Exclusive reservation; never reuse partial or failed output.
    task_run._persist(parent / "binding.json", binding)
    identities = {"binding": _identity(parent / "binding.json")}
    limit = binding["source_output_bytes_limit"]
    for phase in PHASES:
        stage = parent / phase
        stage.mkdir()
        started = datetime.now(UTC).isoformat()
        operation_error = None
        console_cleanup_exception_type = None
        try:
            baseline = phase == "baseline_public"
            source = Path(binding["baseline_source" if baseline else "candidate_source"])
            source_inventory = _copy_tree(source, stage / "work", limit)
            recipe_inventory = _copy_tree(recipe_root, stage / "acceptance", limit)
            _require(_inputs(context, roots, collection, recipe_root) == binding, "BindingChanged")
            command = _command(binding, phase)
            task_run._verify_file_identity(binding["executable_identity"])
            started = datetime.now(UTC).isoformat()
            try:
                with contextlib.ExitStack() as consoles:
                    try:
                        stdout = consoles.enter_context((stage / "stdout.txt").open("xb"))
                        stderr = consoles.enter_context((stage / "stderr.txt").open("xb"))
                        process = subprocess.run(
                            command["argv"],
                            cwd=command["cwd"],
                            timeout=TIMEOUT_SECONDS,
                            shell=False,
                            check=False,
                            stdout=stdout,
                            stderr=stderr,
                        )
                    except BaseException as error:
                        # Save the original before either stream's fallible exit.
                        operation_error = error
                        raise
            except BaseException as error:
                if operation_error is None:
                    raise
                if error is not operation_error:
                    console_cleanup_exception_type = type(error).__name__
            # Leave the cleanup handler before re-raising the original, so its
            # cause is not replaced by the secondary error's exception context.
            if operation_error is not None:
                raise operation_error
            ended = datetime.now(UTC).isoformat()
            _require(_inputs(context, roots, collection, recipe_root) == binding, "BindingChanged")
            _require(_inventory(stage / "work", limit) == source_inventory, "ManagerSourceChanged")
            _require(
                _inventory(stage / "acceptance", limit) == recipe_inventory, "ManagerRecipeChanged"
            )
            counts, report = _report(stage / "out/tests.xml", phase)
            fact = {
                "actor": "ManagementIndependent",
                "task_id": binding["task_id"],
                "source_tree_sha256": binding[
                    "baseline_tree_sha256" if baseline else "candidate_tree_sha256"
                ],
                "worker_shell_identity": None,
                "start_utc": started,
                "end_utc": ended,
                "exit_code": process.returncode,
                **command,
                **counts,
            }
            task_run._persist(stage / "command.json", fact)
            task_run._persist(stage / "report-identity.json", report)
            _check_fact(fact, binding, phase, context)
            identities[phase] = {"command": _identity(stage / "command.json"), "report": report}
        except BaseException as error:
            with contextlib.suppress(BaseException):
                failure = {
                    "phase": phase,
                    "exception_type": type(error).__name__,
                    "start_utc": started,
                }
                if console_cleanup_exception_type is not None:
                    failure["console_cleanup_exception_type"] = console_cleanup_exception_type
                task_run._persist(stage / "failure.json", failure)
            raise
    read_manager_evidence(
        identities=identities,
        context=context,
        roots=roots,
        collection=collection,
        recipe_root=recipe_root,
    )
    return identities


def _check_fact(fact: dict, binding: dict, phase: str, context: dict) -> None:
    command = _command(binding, phase)
    layered_acceptance._validate_recipe(command, context["bundle"]["deployment_receipt"])
    _require(
        all(
            type(fact[key]) is int and fact[key] == number for key, number in _counts(phase).items()
        )
        and type(fact["exit_code"]) is int
        and fact["exit_code"] == (1 if phase == "baseline_public" else 0),
        "ManagerRetestFailed",
    )
    tree = binding[
        "baseline_tree_sha256" if phase == "baseline_public" else "candidate_tree_sha256"
    ]
    # Reuse the existing command binding/time validator. Normalize only its
    # success predicate for the expected failing baseline; retain the real fact.
    _require(
        layered_acceptance._command_matches(
            {**fact, "exit_code": 0, "failures": 0, "errors": 0},
            context["task"],
            tree,
            command,
            "ManagementIndependent",
        ),
        "ManagerRetestBindingMismatch",
    )


def read_manager_evidence(
    *, identities: dict, context: dict, roots: dict, collection: dict, recipe_root: Path
) -> dict:
    """Re-read retained facts and their inputs; hashes never establish authority."""
    task_run._object(identities, {"binding", *PHASES})
    binding = _inputs(context, roots, collection, recipe_root)
    parent = Path(binding["output_root"])
    _require(Path(identities["binding"]["path"]) == parent / "binding.json", "EvidencePathChanged")
    saved = contract.decode_strict_json_bytes(
        _pinned(identities["binding"]), label="retest binding"
    )
    _require(saved == binding, "BindingChanged")
    for phase in PHASES:
        stage = parent / phase
        task_run._object(identities[phase], {"command", "report"})
        _require(
            Path(identities[phase]["command"]["path"]) == stage / "command.json"
            and Path(identities[phase]["report"]["path"]) == stage / "out/tests.xml",
            "EvidencePathChanged",
        )
        fact = contract.decode_strict_json_bytes(
            _pinned(identities[phase]["command"]), label="manager command"
        )
        _check_fact(fact, binding, phase, context)
        files, directories = _source(
            stage / "work",
            binding["source_output_bytes_limit"],
            baseline=phase == "baseline_public",
        )
        tree = binding[
            "baseline_tree_sha256" if phase == "baseline_public" else "candidate_tree_sha256"
        ]
        _require(task_workspace._tree_sha(files, directories) == tree, "ManagerSourceChanged")
        _recipe(stage / "acceptance", binding["source_output_bytes_limit"])
        _pinned(identities[phase]["report"])
        counts, report = _report(stage / "out/tests.xml", phase)
        _require(
            identities[phase]["report"] == task_run._read(stage / "report-identity.json") == report
            and all(fact[key] == number for key, number in counts.items()),
            "ManagerReportChanged",
        )
    _require(_inputs(context, roots, collection, recipe_root) == binding, "BindingChanged")
    return {
        "status": "ManagementRetestsPass",
        "origin": "HostObserved",
        "actor": "ManagementIndependent",
        "worker_execution": "Unknown",
        "worker_shell_identity": "Unknown",
        "runtime_acceptance": "Unverified",
        "accepted": False,
    }


def main() -> int:
    # No launch arguments, permit consumption, key access or configuration IO.
    # Neither a caller label nor synthetic evidence can enable this entry point.
    sys.stdout.write(
        json.dumps(
            {
                "status": "Blocked",
                "error_code": "WorkerTestEvidenceInterfaceUnverified",
                "launch_count": 0,
                "worker_execution": "Unknown",
                "accepted": False,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
