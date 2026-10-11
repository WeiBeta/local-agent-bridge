"""Protected four-file Shadow input wrapper; invokes the unchanged public recipe.

Only a completed native CLI tool result can establish the CLI provenance of this
summary. A Worker-writable summary file alone is not execution evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

PREFIX = "SHADOW_PUBLIC_RESULT_V1 "
LIMIT = 8 * 1024 * 1024
REPORT_LIMIT = 512 * 1024
TIMEOUT = 10
BASELINE_SHA = "fdecaccf115229e86c834dcaa30e533bf0bc2869625c02009da49d1a9e9285cd"
RECIPE_HASHES = {
    "recipe/run_tests.py": "9e7a261b7221e6f2218445c73a4930faf45eeb7b34f450c5aad68c644cde4a11",
    "recipe/public_tests.py": "811d8d292d9e7e4e42d52a4b8b3c376c1749a3f6812c306a9a803d7bb5106562",
}
CASES = sorted(
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
BASELINE_ERRORS = {
    "public_tests.PublicPackageTests.test_" + name
    for name in (
        "default_range_has_numeric_source_order",
        "repeatable_json_bytes",
        "sparse_inclusive_filter",
        "valid_archive_and_input_digest",
    )
}


def expected_outcomes(phase: str) -> dict[str, str]:
    require(phase in {"reproduce", "regression"}, "PhaseInvalid")
    return {
        name: "error" if phase == "reproduce" and name in BASELINE_ERRORS else "pass"
        for name in CASES
    }


class WrapperError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise WrapperError(code)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def plain(path: Path, *, directory: bool = False) -> None:
    for parent in (path, *path.parents):
        info = parent.lstat()
        require(
            not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
            "PathAlias",
        )
    info = path.stat()
    require(
        stat.S_ISDIR(info.st_mode)
        if directory
        else stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
        "NotPlainFile",
    )


def read(path: Path, limit: int) -> bytes:
    plain(path)
    require(path.stat().st_size <= limit, "ByteLimit")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "ByteLimit")
    return raw


def inventory(root: Path) -> tuple[dict, str]:
    plain(root, directory=True)
    names = {"tool.py", "recipe/shadow_worker_tests.py", *RECIPE_HASHES}
    found = set()
    directories = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            plain(path, directory=True)
            directories.add(relative)
        else:
            plain(path)
            found.add(relative)
        require(len(found) + len(directories) <= 5, "SourceScopeChanged")
    require(found == names and directories == {"recipe"}, "SourceScopeChanged")
    files = {}
    total = 0
    for name in sorted(names):
        raw = read(root / name, LIMIT - total)
        total += len(raw)
        files[name] = {"bytes": len(raw), "sha256": sha(raw)}
    require(
        all(files[name]["sha256"] == pin for name, pin in RECIPE_HASHES.items()), "RecipeChanged"
    )
    entries = [{"path": "recipe", "kind": "directory", "bytes": 0, "sha256": None}]
    entries.extend({"path": name, "kind": "file", **stamp} for name, stamp in files.items())
    entries.sort(key=lambda item: item["path"].encode("utf-8"))
    return files, sha(canonical({"contract_version": 1, "entries": entries}))


def report(path: Path) -> dict:
    raw = read(path, REPORT_LIMIT)
    require(
        not any(token in raw.upper() for token in (b"<!DOCTYPE", b"<!ENTITY", b"\x00")),
        "InvalidReport",
    )
    root = ET.fromstring(raw)
    require(root.tag == "testsuite", "InvalidReport")
    counts = {}
    for key in ("tests", "failures", "errors", "skipped"):
        value = root.get(key)
        require(
            type(value) is str and re.fullmatch(r"[0-9]{1,2}", value) is not None, "InvalidReport"
        )
        counts[key] = int(value)
    cases = list(root)
    require(
        counts["tests"] == len(cases) == 8
        and counts["skipped"] == 0
        and all(case.tag == "testcase" for case in cases)
        and sorted(case.get("name") for case in cases) == CASES,
        "CaseSetChanged",
    )
    actual = {"failures": 0, "errors": 0}
    outcomes = {}
    for case in cases:
        require(len(case) <= 1, "InvalidReport")
        outcomes[case.get("name")] = case[0].tag if len(case) else "pass"
        for outcome in case:
            require(outcome.tag in {"failure", "error"}, "InvalidReport")
            actual["failures" if outcome.tag == "failure" else "errors"] += 1
    require(all(counts[key] == value for key, value in actual.items()), "InvalidReport")
    return {
        **counts,
        "case_ids": CASES.copy(),
        "case_outcomes": {name: outcomes[name] for name in CASES},
        "report_sha256": sha(raw),
    }


def run_public(*, task_id: str, phase: str, source: Path, out: Path) -> dict:
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id) is not None, "TaskIdInvalid")
    require(phase in {"reproduce", "regression"}, "PhaseInvalid")
    require(source.is_absolute() and out.is_absolute(), "AbsolutePathsRequired")
    require(out == source.parent / "out/worker-tests" / phase, "OutputScopeChanged")
    require(
        Path(__file__).absolute() == source / "recipe/shadow_worker_tests.py",
        "WrapperLocationChanged",
    )
    before, tree = inventory(source)
    if phase == "reproduce":
        require(before["tool.py"]["sha256"] == BASELINE_SHA, "BaselineChanged")
    else:
        read(out.parent / "reproduce/summary.json", 16384)
    plain(source.parent / "out", directory=True)
    out.parent.mkdir(exist_ok=True)
    plain(out.parent, directory=True)
    out.mkdir(exist_ok=False)  # A failed or completed phase stays reserved.
    executable = Path(sys.executable).absolute()
    python_sha = sha(read(executable, 16 * 1024 * 1024))
    argv = [
        str(executable),
        "-I",
        "-B",
        str(source / "recipe/run_tests.py"),
        "--source",
        str(source),
        "--out",
        str(out / "report"),
        "--suite",
        "public",
    ]
    started = datetime.now(UTC).isoformat()
    process = subprocess.run(
        argv,
        cwd=source,
        timeout=TIMEOUT,
        shell=False,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ended = datetime.now(UTC).isoformat()
    require(inventory(source) == (before, tree), "SourceChangedDuringTests")
    require(sha(read(executable, 16 * 1024 * 1024)) == python_sha, "PythonChanged")
    counts = report(out / "report/tests.xml")
    require(counts["case_outcomes"] == expected_outcomes(phase), "CaseOutcomesChanged")
    require(
        type(process.returncode) is int
        and process.returncode == (1 if counts["errors"] or counts["failures"] else 0),
        "ExitReportConflict",
    )
    result = {
        "contract_version": 1,
        "kind": "ShadowPublicResult",
        "task_id": task_id,
        "phase": phase,
        "source_tree_sha256": tree,
        "source_files": before,
        "recipe_sha256": RECIPE_HASHES["recipe/run_tests.py"],
        "python_sha256": python_sha,
        "argv": argv,
        "cwd": str(source),
        "start_utc": started,
        "end_utc": ended,
        "exit_code": process.returncode,
        **counts,
    }
    with (out / "summary.json").open("xb") as stream:
        stream.write(canonical(result))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--phase", choices=("reproduce", "regression"), required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    options = parser.parse_args(argv)
    try:
        value = run_public(**vars(options))
    except Exception as error:
        code = str(error) if isinstance(error, WrapperError) else type(error).__name__
        sys.stderr.write(json.dumps({"status": "Unknown", "error_code": code}) + "\n")
        return 2
    sys.stdout.write(PREFIX + canonical(value).decode() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
