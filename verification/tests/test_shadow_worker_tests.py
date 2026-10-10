"""Real local Python public recipe; synthetic copies, no CLI/model or key IO."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest
from test_shadow_coding_live import SELECT, live, selected_files


@pytest.fixture
def work(tmp_path):
    source = tmp_path / "work"
    (source / "recipe").mkdir(parents=True)
    (tmp_path / "out").mkdir()
    for name, raw in selected_files().items():
        (source / name).write_bytes(raw)
    return source


def run(work, phase, *, out=None):
    output = work.parent / "out/worker-tests" / phase if out is None else out
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(work / "recipe/shadow_worker_tests.py"),
            "--task-id",
            "offline-wrapper",
            "--phase",
            phase,
            "--source",
            str(work),
            "--out",
            str(output),
        ],
        timeout=15,
        capture_output=True,
        check=False,
    )


def test_actual_unchanged_public_recipe_baseline_then_reference_candidate(work):
    baseline = run(work, "reproduce")
    assert baseline.returncode == 0, baseline.stderr
    first = json.loads(baseline.stdout[len(live.wrapper.PREFIX) :])
    assert (first["tests"], first["failures"], first["errors"], first["exit_code"]) == (8, 0, 4, 1)
    assert first["case_ids"] == live.wrapper.CASES and "Traceback" not in baseline.stdout.decode()
    shutil.copyfile(SELECT / "acceptance/reference/tool.py", work / "tool.py")
    candidate = run(work, "regression")
    assert candidate.returncode == 0, candidate.stderr
    final = json.loads(candidate.stdout[len(live.wrapper.PREFIX) :])
    assert (final["tests"], final["failures"], final["errors"], final["exit_code"]) == (8, 0, 0, 0)
    files, tree = live.wrapper.inventory(work)
    assert final["source_tree_sha256"] == tree and final["source_files"] == files
    repeat = run(work, "regression")
    assert repeat.returncode == 2 and repeat.stdout == b""
    assert (work.parent / "out/worker-tests/regression/summary.json").exists()


@pytest.mark.parametrize(
    "problem", ["private", "recipe", "baseline", "output", "regression_before_baseline"]
)
def test_wrong_input_phase_or_root_stops_before_summary(work, problem):
    if problem == "private":
        (work / "recipe/private_tests.py").write_bytes(b"never a Worker input")
    elif problem == "recipe":
        (work / "recipe/public_tests.py").write_bytes(b"changed")
    elif problem == "baseline":
        (work / "tool.py").write_bytes(b"fixed = True")
    result = run(
        work,
        "regression" if problem == "regression_before_baseline" else "reproduce",
        out=work.parent / "wrong-output" if problem == "output" else None,
    )
    assert result.returncode == 2 and result.stdout == b""
    assert not (work.parent / "out/worker-tests/reproduce/summary.json").exists()


@pytest.mark.parametrize(
    "raw",
    [
        b'<testsuite tests="8" failures="0" errors="0" skipped="0"/>',
        b"<!DOCTYPE testsuite><testsuite/>",
        b"<testsuite/>",
        b"\x00",
        b"x" * (live.wrapper.REPORT_LIMIT + 1),
    ],
    ids=["missing-cases", "doctype", "missing-counts", "nul", "byte-limit"],
)
def test_missing_cases_and_unbounded_xml_cannot_make_a_summary(tmp_path, raw):
    path = tmp_path / "report.xml"
    path.write_bytes(raw)
    with pytest.raises(live.wrapper.WrapperError):
        live.wrapper.report(path)
