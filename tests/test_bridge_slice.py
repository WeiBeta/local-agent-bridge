"""Behavior tests for the local slice workspace entry (synthetic repositories only).

Every fixture below is a small temporary Git repository plus temporary task roots
inside the pytest run root. No real Scratch, HOST or settings path is read or
written, and no provider, MCP surface, network or OS sandbox is involved.
"""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_agent_bridge.bridge import slice_workspace as entry

NOTE_TEXT = "Synthetic slice task note.\n"
ALPHA = "src/alpha.py"
BETA = "src/beta.py"
ALPHA_TEXT = b"def alpha():\n    return 1\n"
BETA_TEXT = b"def beta():\n    return 2\n"


@dataclass(frozen=True)
class Case:
    repository: Path
    commit: str
    note: Path
    out: Path


@dataclass(frozen=True)
class Result:
    code: int
    out: str
    err: str


def _git(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True)
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8", "replace"))
    return completed.stdout


def _blob(repository: Path, commit: str, relative: str) -> bytes:
    return _git(repository, "cat-file", "blob", f"{commit}:{relative}")


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _entries(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def _posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _prepare_arguments(
    case: Case, files: list[str], editable: list[str] | None = None
) -> list[str]:
    arguments = [
        "prepare",
        "--repository",
        str(case.repository),
        "--commit",
        case.commit,
        "--task-note",
        str(case.note),
        "--out",
        str(case.out),
    ]
    for value in files:
        arguments += ["--file", value]
    for value in editable or []:
        arguments += ["--editable", value]
    return arguments


def _collect_arguments(case: Case) -> list[str]:
    return ["collect", "--task-root", str(case.out)]


def _plan_arguments(root: Path) -> list[str]:
    return ["plan", "--task-root", str(root)]


def _plan_document(result: Result) -> dict:
    return json.loads(result.out)


def _prepare_into(case: Case, capsys, out: Path, files: list[str], editable: list[str]) -> None:
    arguments = _prepare_arguments(case, files, editable)
    arguments[arguments.index("--out") + 1] = str(out)
    prepared = _run(arguments, capsys)
    assert prepared.code == 0, prepared.err


def _run(arguments: list[str], capsys) -> Result:
    code = entry.main(arguments)
    captured = capsys.readouterr()
    return Result(code=code, out=captured.out, err=captured.err)


def _summary(result: Result) -> dict:
    return json.loads(result.out.splitlines()[0])


def _diff_body(result: Result) -> str:
    return result.out.split("\n", 1)[1]


def _reparse_lstat(target: Path):
    lstat = Path.lstat

    def metadata(self, *args, **kwargs):
        if self == target:
            return SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return lstat(self, *args, **kwargs)

    return metadata


@pytest.fixture
def case(tmp_path: Path) -> Case:
    repository = tmp_path / "source-repo"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "tests@example.invalid")
    _git(repository, "config", "user.name", "Ask AI Tests")
    (repository / "src").mkdir()
    (repository / "src" / "alpha.py").write_bytes(ALPHA_TEXT)
    (repository / "src" / "beta.py").write_bytes(BETA_TEXT)
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "base")
    commit = _git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    note = tmp_path / "task-note.md"
    note.write_bytes(NOTE_TEXT.encode("utf-8"))
    return Case(repository=repository, commit=commit, note=note, out=tmp_path / "slice-task")


def test_prepare_and_collect_round_trip(case: Case, capsys) -> None:
    prepared = _run(_prepare_arguments(case, [ALPHA, BETA], [ALPHA]), capsys)
    assert (prepared.code, prepared.err) == (0, "")
    summary = _summary(prepared)
    manifest_bytes = (case.out / "manifest.json").read_bytes()
    assert summary["command"] == "prepare"
    assert summary["source_commit"] == case.commit
    assert summary["files"] == 2
    assert summary["editable"] == [ALPHA]
    assert summary["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()

    alpha_blob = _blob(case.repository, case.commit, ALPHA)
    assert (case.out / "baseline" / "src" / "alpha.py").read_bytes() == alpha_blob
    assert (case.out / "work" / "src" / "alpha.py").read_bytes() == alpha_blob
    assert (case.out / "work" / "TASK.md").read_bytes() == case.note.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    assert [item["path"] for item in manifest["files"]] == [ALPHA, BETA]
    assert manifest["files"][0] == {
        "path": ALPHA,
        "bytes": len(alpha_blob),
        "sha256": hashlib.sha256(alpha_blob).hexdigest(),
    }
    assert manifest["editable"] == [ALPHA]
    note_bytes = case.note.read_bytes()
    assert manifest["task_note"] == {
        "bytes": len(note_bytes),
        "sha256": hashlib.sha256(note_bytes).hexdigest(),
    }

    (case.out / "work" / "src" / "alpha.py").write_bytes(b"def alpha():\n    return 3\n")
    before = _snapshot(case.out)
    collected = _run(_collect_arguments(case), capsys)
    assert (collected.code, collected.err) == (0, "")
    summary = _summary(collected)
    body = _diff_body(collected)
    assert summary["command"] == "collect"
    assert summary["source_commit"] == case.commit
    assert summary["files"] == 2
    assert summary["editable"] == 1
    assert summary["changed"] == [ALPHA]
    assert summary["diff_bytes"] == len(body.encode("utf-8"))
    assert summary["diff_sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert "--- baseline/src/alpha.py" in body
    assert "+++ work/src/alpha.py" in body
    assert "-    return 1" in body
    assert "+    return 3" in body
    assert "No newline at end of file" not in body
    assert _snapshot(case.out) == before


def test_collect_reports_no_change_for_an_untouched_work_tree(case: Case, capsys) -> None:
    prepared = _run(_prepare_arguments(case, [ALPHA], [ALPHA]), capsys)
    assert prepared.code == 0
    collected = _run(_collect_arguments(case), capsys)
    assert (collected.code, collected.err) == (0, "")
    assert _summary(collected)["changed"] == []
    assert _diff_body(collected) == ""


def test_prepare_leaves_the_source_repository_untouched(case: Case, capsys) -> None:
    before_alpha = (case.repository / "src" / "alpha.py").read_bytes()
    prepared = _run(_prepare_arguments(case, [ALPHA, BETA], [ALPHA]), capsys)
    assert prepared.code == 0
    collected = _run(_collect_arguments(case), capsys)
    assert collected.code == 0
    assert _git(case.repository, "status", "--porcelain") == b""
    assert (case.repository / "src" / "alpha.py").read_bytes() == before_alpha
    assert not case.out.is_relative_to(case.repository)


def test_prepare_reads_the_commit_blob_not_the_work_tree(case: Case, capsys) -> None:
    (case.repository / "src" / "alpha.py").write_bytes(b"def alpha():\n    return 99\n")
    prepared = _run(_prepare_arguments(case, [ALPHA], [ALPHA]), capsys)
    assert prepared.code == 0
    frozen = _blob(case.repository, case.commit, ALPHA)
    assert (case.out / "baseline" / "src" / "alpha.py").read_bytes() == frozen
    assert (case.out / "work" / "src" / "alpha.py").read_bytes() == frozen


def test_prepare_refuses_an_existing_task_root(case: Case, capsys) -> None:
    prepared = _run(_prepare_arguments(case, [ALPHA], [ALPHA]), capsys)
    assert prepared.code == 0
    before = _snapshot(case.out)
    repeated = _run(_prepare_arguments(case, [ALPHA, BETA], [ALPHA]), capsys)
    assert repeated.code == 2
    assert repeated.out == ""
    assert "already exists" in repeated.err
    assert _snapshot(case.out) == before


def test_prepare_refuses_a_task_root_inside_the_repository(case: Case, capsys) -> None:
    arguments = _prepare_arguments(case, [ALPHA], [])
    arguments[arguments.index("--out") + 1] = str(case.repository / "slice-task")
    refused = _run(arguments, capsys)
    assert refused.code == 2
    assert "outside the repository work tree" in refused.err
    assert not (case.repository / "slice-task").exists()


def test_collect_refuses_a_non_editable_change(case: Case, capsys) -> None:
    prepared = _run(_prepare_arguments(case, [ALPHA, BETA], [ALPHA]), capsys)
    assert prepared.code == 0
    (case.out / "work" / "src" / "beta.py").write_bytes(b"def beta():\n    return 20\n")
    refused = _run(_collect_arguments(case), capsys)
    assert refused.code == 2
    assert refused.out == ""
    assert "outside the editable set" in refused.err
    assert BETA in refused.err


def test_collect_refuses_baseline_drift(case: Case, capsys) -> None:
    prepared = _run(_prepare_arguments(case, [ALPHA], [ALPHA]), capsys)
    assert prepared.code == 0
    (case.out / "baseline" / "src" / "alpha.py").write_bytes(
        b"def alpha():\n    return 1  # drift\n"
    )
    refused = _run(_collect_arguments(case), capsys)
    assert refused.code == 2
    assert "baseline no longer matches the manifest" in refused.err


def test_collect_refuses_a_manifest_that_contradicts_the_baseline(case: Case, capsys) -> None:
    prepared = _run(_prepare_arguments(case, [ALPHA], [ALPHA]), capsys)
    assert prepared.code == 0
    manifest_path = case.out / "manifest.json"
    document = json.loads(manifest_path.read_bytes().decode("utf-8"))
    document["files"][0]["sha256"] = "0" * 64
    manifest_path.write_bytes(json.dumps(document).encode("utf-8"))
    refused = _run(_collect_arguments(case), capsys)
    assert refused.code == 2
    assert "baseline no longer matches the manifest" in refused.err


def test_collect_refuses_an_added_source_file(case: Case, capsys) -> None:
    prepared = _run(_prepare_arguments(case, [ALPHA], [ALPHA]), capsys)
    assert prepared.code == 0
    (case.out / "work" / "src" / "gamma.py").write_bytes(b"gamma = 1\n")
    refused = _run(_collect_arguments(case), capsys)
    assert refused.code == 2
    assert "unexpected file: src/gamma.py" in refused.err


def test_collect_refuses_a_missing_source_file(case: Case, capsys) -> None:
    prepared = _run(_prepare_arguments(case, [ALPHA, BETA], [ALPHA]), capsys)
    assert prepared.code == 0
    (case.out / "work" / "src" / "beta.py").unlink()
    refused = _run(_collect_arguments(case), capsys)
    assert refused.code == 2
    assert "missing: src/beta.py" in refused.err


def test_collect_refuses_a_modified_task_note(case: Case, capsys) -> None:
    prepared = _run(_prepare_arguments(case, [ALPHA], [ALPHA]), capsys)
    assert prepared.code == 0
    (case.out / "work" / "TASK.md").write_bytes(b"edited task note\n")
    refused = _run(_collect_arguments(case), capsys)
    assert refused.code == 2
    assert refused.out == ""
    assert "task note no longer matches the manifest" in refused.err


def test_collect_refuses_a_root_without_a_manifest(case: Case, capsys) -> None:
    case.out.mkdir()
    refused = _run(_collect_arguments(case), capsys)
    assert refused.code == 2
    assert "manifest" in refused.err


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        ("C:/src/alpha.py", "non-relative"),
        ("../src/alpha.py", "non-relative"),
        ("src\\alpha.py", "canonical"),
        ("src/./alpha.py", "canonical"),
        ("src/alpha.bin", "plain-text"),
        ("src/credentials.py", "secret-bearing"),
        (".git/hooks/pre-commit.py", "reserved or prohibited"),
        ("con.py", "reserved or prohibited"),
        ("TASK.md", "collides with"),
    ],
)
def test_prepare_refuses_unusable_source_paths(case: Case, capsys, value, fragment) -> None:
    refused = _run(_prepare_arguments(case, [value], []), capsys)
    assert refused.code == 2
    assert fragment in refused.err
    assert not case.out.exists()


def test_prepare_refuses_duplicate_and_case_colliding_paths(case: Case, capsys) -> None:
    repeated = _run(_prepare_arguments(case, [ALPHA, ALPHA], []), capsys)
    assert repeated.code == 2
    assert "repeats or case-collides" in repeated.err
    collided = _run(_prepare_arguments(case, [ALPHA, "SRC/Alpha.py"], []), capsys)
    assert collided.code == 2
    assert "repeats or case-collides" in collided.err


def test_prepare_refuses_an_editable_path_outside_the_file_list(case: Case, capsys) -> None:
    refused = _run(_prepare_arguments(case, [ALPHA], [BETA]), capsys)
    assert refused.code == 2
    assert "subset of the prepared files" in refused.err


def test_prepare_refuses_unknown_commits_and_paths(case: Case, capsys) -> None:
    arguments = _prepare_arguments(case, [ALPHA], [])
    arguments[arguments.index("--commit") + 1] = "0" * 40
    unknown_commit = _run(arguments, capsys)
    assert unknown_commit.code == 2
    assert "not present in this local repository" in unknown_commit.err

    arguments = _prepare_arguments(case, [ALPHA], [])
    arguments[arguments.index("--commit") + 1] = case.commit.upper()
    uppercase = _run(arguments, capsys)
    assert uppercase.code == 2
    assert "40-hex" in uppercase.err

    unknown_path = _run(_prepare_arguments(case, ["src/missing.py"], []), capsys)
    assert unknown_path.code == 2
    assert "not present at the frozen commit" in unknown_path.err


def test_prepare_refuses_a_git_symlink_entry(case: Case, capsys) -> None:
    object_id = _git(case.repository, "rev-parse", f"{case.commit}:{ALPHA}").decode("ascii").strip()
    _git(
        case.repository,
        "update-index",
        "--add",
        "--cacheinfo",
        f"120000,{object_id},src/link.py",
    )
    _git(case.repository, "commit", "-m", "symlink entry")
    commit = _git(case.repository, "rev-parse", "HEAD").decode("ascii").strip()
    arguments = _prepare_arguments(case, [ALPHA, "src/link.py"], [])
    arguments[arguments.index("--commit") + 1] = commit
    refused = _run(arguments, capsys)
    assert refused.code == 2
    assert "Git mode 120000" in refused.err


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        (b"\xff\xfe\x00binary\n", "Git blob read failed"),
        (b"alpha\x00beta\n", "contains NUL"),
    ],
)
def test_prepare_refuses_non_text_source_files(case: Case, capsys, payload, fragment) -> None:
    (case.repository / "src" / "blob.py").write_bytes(payload)
    _git(case.repository, "add", ".")
    _git(case.repository, "commit", "-m", "binary")
    commit = _git(case.repository, "rev-parse", "HEAD").decode("ascii").strip()
    arguments = _prepare_arguments(case, ["src/blob.py"], [])
    arguments[arguments.index("--commit") + 1] = commit
    refused = _run(arguments, capsys)
    assert refused.code == 2
    assert fragment in refused.err
    assert not case.out.exists()


def test_prepare_refuses_a_reparse_task_root(case: Case, capsys, monkeypatch) -> None:
    monkeypatch.setattr(Path, "lstat", _reparse_lstat(case.out))
    refused = _run(_prepare_arguments(case, [ALPHA], []), capsys)
    assert refused.code == 2
    assert "reparse" in refused.err
    assert not case.out.exists()


def test_collect_refuses_a_reparse_entry_in_the_work_tree(case: Case, capsys, monkeypatch) -> None:
    prepared = _run(_prepare_arguments(case, [ALPHA], [ALPHA]), capsys)
    assert prepared.code == 0
    monkeypatch.setattr(Path, "lstat", _reparse_lstat(case.out / "work" / "src" / "alpha.py"))
    refused = _run(_collect_arguments(case), capsys)
    assert refused.code == 2
    assert "reparse point is refused: src/alpha.py" in refused.err


def test_prepare_refuses_a_real_linked_parent(case: Case, capsys) -> None:
    real = case.out.parent / "real-parent"
    real.mkdir()
    link = case.out.parent / "linked-parent"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError as error:
        if error.winerror == 1314:
            pytest.skip("Real directory link unavailable: WinError 1314; permissions unchanged")
        raise
    arguments = _prepare_arguments(case, [ALPHA], [])
    arguments[arguments.index("--out") + 1] = str(link / "slice-task")
    refused = _run(arguments, capsys)
    assert refused.code == 2
    assert "reparse" in refused.err
    assert not (real / "slice-task").exists()


ENTRY = [sys.executable, "-m", "local_agent_bridge.cli"]


def test_entry_point_runs_as_a_subprocess(case: Case) -> None:
    prepared = subprocess.run(
        [*ENTRY, *_prepare_arguments(case, [ALPHA], [ALPHA])],
        capture_output=True,
        text=True,
        check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    assert json.loads(prepared.stdout.splitlines()[0])["files"] == 1

    (case.out / "work" / "src" / "alpha.py").write_bytes(b"def alpha():\n    return 7\n")
    collected = subprocess.run(
        [sys.executable, "-m", "local_agent_bridge.cli", *_collect_arguments(case)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert collected.returncode == 0, collected.stderr
    assert "+    return 7" in collected.stdout


def test_help_examples_use_a_generic_task_id(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        entry.main(["--help"])
    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "SLICE-DEMO-01" in help_text
    assert "HOST-03" not in help_text


def test_diff_marks_a_missing_trailing_newline_and_applies_cleanly(case: Case, capsys) -> None:
    frozen = {
        "src/plain.py": b"def plain():\n    return 1",
        "src/other.py": b"def other():\n    return 2\n",
        "src/gamma.py": b"def gamma():\n    return 3\n",
    }
    edited = {
        "src/plain.py": b"def plain():\n    return 11",
        "src/other.py": b"def other():\n    return 22\n",
        "src/gamma.py": b"def gamma():\n    return 33",
    }
    for relative, payload in frozen.items():
        (case.repository / relative).write_bytes(payload)
    _git(case.repository, "add", ".")
    _git(case.repository, "commit", "-m", "frozen no-newline fixtures")
    commit = _git(case.repository, "rev-parse", "HEAD").decode("ascii").strip()
    arguments = _prepare_arguments(case, list(frozen), list(frozen))
    arguments[arguments.index("--commit") + 1] = commit
    prepared = _run(arguments, capsys)
    assert prepared.code == 0
    for relative, payload in edited.items():
        (case.out / "work" / relative).write_bytes(payload)
    collected = _run(_collect_arguments(case), capsys)
    assert collected.code == 0
    body = _diff_body(collected)
    assert _summary(collected)["changed"] == ["src/gamma.py", "src/other.py", "src/plain.py"]
    assert body.count("\\ No newline at end of file") == 3
    assert (
        "-    return 1\n\\ No newline at end of file\n"
        "+    return 11\n\\ No newline at end of file\n"
    ) in body
    assert "-    return 3\n+    return 33\n\\ No newline at end of file\n" in body
    for relative in frozen:
        assert f"--- baseline/{relative}\n" in body
        assert f"+++ work/{relative}\n" in body
    apply_root = case.out.parent / "apply-check"
    (apply_root / "src").mkdir(parents=True)
    _git(apply_root, "init")
    for relative, payload in frozen.items():
        (apply_root / relative).write_bytes(payload)
    _git(apply_root, "add", ".")
    diff_file = case.out.parent / "collected.diff"
    diff_file.write_bytes(body.encode("utf-8"))
    applied = subprocess.run(
        ["git", "-C", str(apply_root), "apply", "-p1", "--check", str(diff_file)],
        capture_output=True,
    )
    assert applied.returncode == 0, applied.stderr.decode("utf-8", "replace")


def test_cli_stdout_bytes_match_the_reported_diff(case: Case, tmp_path: Path) -> None:
    prepared = subprocess.run(
        [*ENTRY, *_prepare_arguments(case, [ALPHA], [ALPHA])],
        capture_output=True,
        check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    (case.out / "work" / "src" / "alpha.py").write_bytes(b"def alpha():\n    return 7\n")
    target = tmp_path / "stdout.bin"
    with target.open("wb") as stream:
        completed = subprocess.run(
            [sys.executable, "-m", "local_agent_bridge.cli", *_collect_arguments(case)],
            stdout=stream,
            stderr=subprocess.PIPE,
            check=False,
        )
    assert completed.returncode == 0, completed.stderr
    payload = target.read_bytes()
    first, _, body = payload.partition(b"\n")
    summary = json.loads(first.decode("utf-8"))
    assert b"\r\n" not in payload
    assert summary["diff_bytes"] == len(body)
    assert summary["diff_sha256"] == hashlib.sha256(body).hexdigest()
    assert b"+    return 7\n" in body


def test_plan_reports_distinct_plans_for_two_task_roots(case: Case, capsys, tmp_path: Path) -> None:
    first, second = tmp_path / "plan-root-a", tmp_path / "plan-root-b"
    _prepare_into(case, capsys, first, [ALPHA], [ALPHA])
    _prepare_into(case, capsys, second, [ALPHA, BETA], [BETA])

    plan_a = _run(_plan_arguments(first), capsys)
    plan_b = _run(_plan_arguments(second), capsys)
    assert (plan_a.code, plan_a.err) == (0, "")
    assert (plan_b.code, plan_b.err) == (0, "")
    assert len(plan_a.out.splitlines()) == 1
    document_a, document_b = _plan_document(plan_a), _plan_document(plan_b)
    work_a, work_b = _posix(first / "work"), _posix(second / "work")

    assert document_a["task_root"] == _posix(first)
    assert document_b["task_root"] == _posix(second)
    assert document_a["manifest_sha256"] != document_b["manifest_sha256"]
    assert (
        document_a["manifest_sha256"]
        == hashlib.sha256((first / "manifest.json").read_bytes()).hexdigest()
    )
    assert document_a["source_commit"] == document_b["source_commit"] == case.commit
    assert document_a["read_file"] == [f"{work_a}/TASK.md", f"{work_a}/{ALPHA}"]
    assert document_b["read_file"] == [f"{work_b}/TASK.md", f"{work_b}/{ALPHA}", f"{work_b}/{BETA}"]
    assert document_a["write_file"] == [f"{work_a}/{ALPHA}"]
    assert document_b["write_file"] == [f"{work_b}/{BETA}"]
    assert document_a["model"] == document_b["model"] == "gemini-3.8-flash-high"
    assert document_a["effort"] == document_b["effort"] == "high"
    assert document_a["argv"][0] == document_b["argv"][0] == "--print"
    assert document_a["argv"][2:] == document_b["argv"][2:]
    assert document_a["argv"][1] != document_b["argv"][1]
    assert work_a in document_a["argv"][1]
    assert work_b not in document_a["argv"][1]
    assert work_b in document_b["argv"][1]
    assert work_a not in document_b["argv"][1]
    assert "def alpha" not in plan_a.out
    assert NOTE_TEXT.strip() not in plan_a.out


def test_plan_paths_rules_and_counts_are_exact(case: Case, capsys) -> None:
    prepared = _run(_prepare_arguments(case, [ALPHA, BETA], [ALPHA]), capsys)
    assert prepared.code == 0
    result = _run(_plan_arguments(case.out), capsys)
    assert (result.code, result.err) == (0, "")
    document = _plan_document(result)
    work = _posix(case.out / "work")
    note = f"{work}/TASK.md"

    assert document["cwd"] == work
    assert document["read_file"] == [note, f"{work}/{ALPHA}", f"{work}/{BETA}"]
    assert document["write_file"] == [f"{work}/{ALPHA}"]
    assert note in document["read_file"]
    assert note not in document["write_file"]
    assert set(document["write_file"]) <= set(document["read_file"])
    rules = document["permission_rules"]
    assert rules["read_file"] == [f"read_file({path})" for path in document["read_file"]]
    assert rules["write_file"] == [f"write_file({path})" for path in document["write_file"]]
    assert rules["counts"] == {"read_file": 3, "write_file": 1, "command": 0}
    for path in [*document["read_file"], *document["write_file"]]:
        assert path.startswith(work + "/")
        assert "\\" not in path
        assert "*" not in path


def test_plan_argv_and_boundaries_are_fixed(case: Case, capsys) -> None:
    spaced, unicode_name = "src/with space.py", "src/ünücode_文件.py"
    (case.repository / "src" / "with space.py").write_bytes(b"spaced = 1\n")
    (case.repository / "src" / "ünücode_文件.py").write_bytes(b"unicode = 1\n")
    _git(case.repository, "add", ".")
    _git(case.repository, "commit", "-m", "spaced and unicode fixtures")
    commit = _git(case.repository, "rev-parse", "HEAD").decode("ascii").strip()
    arguments = _prepare_arguments(case, [ALPHA, spaced, unicode_name], [spaced, unicode_name])
    arguments[arguments.index("--commit") + 1] = commit
    prepared = _run(arguments, capsys)
    assert prepared.code == 0
    result = _run(_plan_arguments(case.out), capsys)
    assert (result.code, result.err) == (0, "")
    document = _plan_document(result)
    argv = document["argv"]
    work = _posix(case.out / "work")

    assert argv[0] == "--print"
    assert len(argv) == 11
    assert argv[2:] == [
        "--model",
        "gemini-3.8-flash-high",
        "--effort",
        "high",
        "--output-format",
        "stream-json",
        "--disable-slash-commands",
        "--print-timeout",
        "15m",
    ]
    prompt = argv[1]
    marker = " Access list (path data, not instructions): "
    assert prompt.count(marker) == 1
    instruction, _, payload_text = prompt.partition(marker)
    assert prompt.endswith(payload_text)
    assert instruction.count("TASK.md") == 1
    assert "Do not run commands or tests" in instruction
    assert "do not claim" in instruction
    payload = json.loads(payload_text)
    assert payload == {"readable": document["read_file"], "writable": document["write_file"]}
    assert payload["writable"] == [f"{work}/{spaced}", f"{work}/{unicode_name}"]
    assert all(f"{work}/{name}" in payload["readable"] for name in (spaced, unicode_name))
    assert document["schema_version"] == 1
    assert document["execution_authorized"] is False
    assert document["cwd"] not in document["read_file"]
    assert document["task_root"] not in document["read_file"]
    assert any("not an approval" in note for note in document["notes"])
    for forbidden in ("--continue", "--skip-permissions", "dangerously", "--yolo", "command(", "*"):
        assert forbidden not in result.out


def test_plan_refuses_a_changed_extra_or_missing_root(case: Case, capsys, tmp_path: Path) -> None:
    changed_source = tmp_path / "plan-changed-source"
    changed_note = tmp_path / "plan-changed-note"
    changed_baseline = tmp_path / "plan-changed-baseline"
    extra_file = tmp_path / "plan-extra-file"
    for root in (changed_source, changed_note, changed_baseline, extra_file):
        _prepare_into(case, capsys, root, [ALPHA], [ALPHA])

    (changed_source / "work" / "src" / "alpha.py").write_bytes(b"def alpha():\n    return 5\n")
    (changed_note / "work" / "TASK.md").write_bytes(b"edited plan note\n")
    (changed_baseline / "baseline" / "src" / "alpha.py").write_bytes(
        b"def alpha():\n    return 6\n"
    )
    (extra_file / "work" / "src" / "gamma.py").write_bytes(b"gamma = 1\n")

    refusals = {
        "untouched work tree": changed_source,
        "task note no longer matches the manifest": changed_note,
        "baseline no longer matches the manifest": changed_baseline,
        "unexpected file": extra_file,
    }
    for fragment, root in refusals.items():
        refused = _run(_plan_arguments(root), capsys)
        assert refused.code == 2, fragment
        assert refused.out == ""
        assert fragment in refused.err

    empty = tmp_path / "plan-empty-root"
    empty.mkdir()
    refused = _run(_plan_arguments(empty), capsys)
    assert refused.code == 2
    assert "manifest" in refused.err


def test_plan_is_read_only_and_keeps_the_layout(case: Case, capsys) -> None:
    prepared = _run(_prepare_arguments(case, [ALPHA, BETA], [ALPHA]), capsys)
    assert prepared.code == 0
    before_files = _snapshot(case.out)
    before_entries = _entries(case.out)

    result = _run(_plan_arguments(case.out), capsys)

    assert (result.code, result.err) == (0, "")
    assert _snapshot(case.out) == before_files
    assert _entries(case.out) == before_entries
