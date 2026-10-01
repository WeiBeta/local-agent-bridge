"""Offline synthetic tests for the fixed Cursor entry; no real CLI or model."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_agent_bridge import cli
from local_agent_bridge.bridge import cursor_run as cursor
from local_agent_bridge.bridge import slice_run as runner
from local_agent_bridge.bridge import slice_workspace
from local_agent_bridge.capture.keys import SessionKeyError
from local_agent_bridge.capture.session import SessionStore

TEST_KEY = bytes(range(32))
NOTE_BYTES = b"cursor adapter synthetic note\n"
PROMPT_TEXT = NOTE_BYTES[:-1].decode("utf-8")
CONFIG_BYTES = (
    b'{"permissions": {"allow": ["Read(INPUT.txt)", "Write(OUTPUT.txt)"], '
    b'"deny": ["Shell(*)", "Mcp(*:*)", "WebFetch(*)"]}}\n'
)


@pytest.fixture(autouse=True)
def isolated_session_store(monkeypatch, tmp_path: Path) -> SessionStore:
    store = SessionStore(TEST_KEY, root=tmp_path / "session-state")
    monkeypatch.setattr(cursor, "_session_store", lambda: store)
    return store


@pytest.fixture
def cursor_case(tmp_path: Path) -> SimpleNamespace:
    repository = tmp_path / "source-repo"
    (repository / "src").mkdir(parents=True)
    (repository / ".cursor").mkdir()
    (repository / "src" / "alpha.py").write_bytes(b"def alpha():\n    return 1\n")
    (repository / ".cursor" / "cli.json").write_bytes(CONFIG_BYTES)

    def git(*arguments: str) -> bytes:
        done = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "-c",
                "user.email=tests@example.invalid",
                "-c",
                "user.name=tests",
                *arguments,
            ],
            capture_output=True,
        )
        assert done.returncode == 0, done.stderr
        return done.stdout

    git("init", "-q")
    git("add", ".")
    git("commit", "-q", "-m", "base")
    commit = git("rev-parse", "HEAD").decode("ascii").strip()
    note = tmp_path / "note.md"
    note.write_bytes(NOTE_BYTES)
    task_root = tmp_path / "slice-task"
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = cli.main(
            [
                "prepare",
                "--repository",
                str(repository),
                "--commit",
                commit,
                "--task-note",
                str(note),
                "--file",
                "src/alpha.py",
                "--editable",
                "src/alpha.py",
                "--file",
                ".cursor/cli.json",
                "--out",
                str(task_root),
            ]
        )
    assert code == 0, buffer.getvalue()
    exe = tmp_path / "agent.ps1"
    exe.write_bytes(b"# synthetic cursor launcher\n")
    return SimpleNamespace(
        task_root=task_root,
        exe=exe,
        exe_sha256=runner._sha256_file(exe),
        config_path=task_root / "work" / ".cursor" / "cli.json",
    )


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    def read(self, size: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _FakeProcess:
    def __init__(self, exit_code: int = 0, stdout_chunks=(), stderr_chunks=()) -> None:
        self.pid = 43041
        self.uses_job = True
        self.stdout = _FakeStream(stdout_chunks)
        self.stderr = _FakeStream(stderr_chunks)
        self.returncode = exit_code

    def wait(self, timeout=None) -> int:
        return self.returncode

    def terminate_once(self) -> None:
        return None

    def close_job(self) -> None:
        return None


def _main(argv: list[str], capsys) -> tuple[int, dict, str]:
    code = cursor.main(argv)
    captured = capsys.readouterr()
    document = json.loads(captured.out) if captured.out.strip() else {}
    return code, document, captured.err


def _run_arguments(case: SimpleNamespace, run_root: Path, *, execute: bool) -> list[str]:
    values = [
        "run",
        "--task-root",
        str(case.task_root),
        "--run-root",
        str(run_root),
        "--exe",
        str(case.exe),
        "--exe-sha256",
        case.exe_sha256,
    ]
    if execute:
        values.append("--execute")
    return values


def _expected_argv(case: SimpleNamespace) -> list[str]:
    plan = slice_workspace.build_plan(str(case.task_root))
    return [
        str(runner._pwsh_path()),
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(case.exe),
        "--workspace",
        str(plan["cwd"]),
        "-p",
        "--model",
        cursor.CURSOR_MODEL,
        "--output-format",
        "stream-json",
        "--force",
        PROMPT_TEXT,
    ]


def _no_launch(monkeypatch) -> list:
    calls: list = []

    def fail(*arguments):
        calls.append(arguments)
        raise AssertionError("must not launch")

    monkeypatch.setattr(runner, "spawn_suspended_in_job", fail)
    return calls


def test_preflight_reports_without_side_effects(cursor_case, capsys, monkeypatch, tmp_path):
    _no_launch(monkeypatch)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(cursor_case, run_root, execute=False), capsys)
    assert (code, err) == (0, "")
    assert document["execute"] is False
    assert document["execution_authorized"] is False
    assert document["model_requested"] == cursor.CURSOR_MODEL
    assert "fast" not in document["model_requested"].casefold()
    assert document["provider_calls"] == 0
    assert document["cursor_cli_invocations"] == 0
    assert document["launcher"]["sha256"] == cursor_case.exe_sha256
    assert document["cursor_config"]["sha256"] == runner._sha256_file(cursor_case.config_path)
    assert document["fixed_argv_elements"] == 13
    assert PROMPT_TEXT not in json.dumps(document)
    assert not run_root.exists()


def test_preflight_refuses_launcher_hash_mismatch(cursor_case, capsys, monkeypatch, tmp_path):
    _no_launch(monkeypatch)
    run_root = tmp_path / "run-root"
    argv = _run_arguments(cursor_case, run_root, execute=False)
    argv[argv.index("--exe-sha256") + 1] = "0" * 64
    code, document, err = _main(argv, capsys)
    assert code == 2 and document == {}
    assert "mismatch" in err
    assert not run_root.exists()


def test_missing_cursor_project_config_refuses(cursor_case, capsys, monkeypatch, tmp_path):
    cursor_case.config_path.unlink()
    _no_launch(monkeypatch)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert code == 2 and document == {}
    assert ".cursor/cli.json" in err
    assert "does not match the manifest" in err
    assert not run_root.exists()


def test_execute_spawns_once_with_fixed_argv_and_seals(cursor_case, capsys, monkeypatch, tmp_path):
    spawn_calls: list = []

    def fake_spawn(argv, cwd):
        spawn_calls.append((list(argv), cwd))
        return _FakeProcess(stdout_chunks=[b'{"type":"result","subtype":"success"}\n'])

    monkeypatch.setattr(runner, "spawn_suspended_in_job", fake_spawn)
    env_before = os.environ.get(runner.AUTO_UPDATE_VARIABLE)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert (code, err) == (0, "")
    assert document["result"] == "lifecycle_complete_capture_sealed"
    assert document["launches"] == 1 and document["spawn_state"] == "confirmed"
    assert document["session"]["sealed"] is True
    assert document["receipt_persisted"] is True
    assert "not a" in document["note"] and "coding" in document["note"]
    assert len(spawn_calls) == 1
    assert spawn_calls[0][0] == _expected_argv(cursor_case)
    assert spawn_calls[0][1] == slice_workspace.build_plan(str(cursor_case.task_root))["cwd"]
    assert os.environ.get(runner.AUTO_UPDATE_VARIABLE) == env_before
    assert sorted(path.name for path in run_root.iterdir()) == ["plan.json", "run.json"]
    receipt = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert receipt["model_requested"] == cursor.CURSOR_MODEL
    assert PROMPT_TEXT not in json.dumps(receipt)
    assert PROMPT_TEXT not in (run_root / "plan.json").read_text(encoding="utf-8")
    store = SessionStore(TEST_KEY, root=tmp_path / "session-state")
    reader = store.reader(document["session"]["session_id"])
    assert reader.read_stream("task") == NOTE_BYTES
    assert reader.read_stream("request") == PROMPT_TEXT.encode("utf-8")
    assert reader.read_stream("stdout") == b'{"type":"result","subtype":"success"}\n'


def test_child_nonzero_exit_is_recorded_not_claimed(cursor_case, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(
        runner,
        "spawn_suspended_in_job",
        lambda argv, cwd: _FakeProcess(exit_code=2, stdout_chunks=[b"partial\n"]),
    )
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert code == 0
    assert document["process_exit_code"] == 2
    assert document["result"] == "lifecycle_complete_capture_sealed"
    receipt = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert receipt["launch"]["exit_code"] == 2
    assert "coding" in document["note"]


def test_missing_session_key_refuses_before_writes(cursor_case, capsys, monkeypatch, tmp_path):
    def missing_key():
        raise SessionKeyError("session key missing; run local-agent-bridge session-key-init")

    monkeypatch.setattr(cursor, "_session_store", missing_key)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert code == 2 and document == {}
    assert "session key" in err
    assert not run_root.exists()


def test_task_note_drift_refuses_before_spawn(cursor_case, capsys, monkeypatch, tmp_path):
    store = SessionStore(TEST_KEY, root=tmp_path / "session-state")

    def drifted_store():
        (cursor_case.task_root / "work" / "TASK.md").write_bytes(b"changed after inputs\n")
        return store

    monkeypatch.setattr(cursor, "_session_store", drifted_store)
    calls = _no_launch(monkeypatch)
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert code == 2
    assert document["setup_stage"] == "cursor session input capture"
    assert document["setup_reason"] == "capture_unavailable"
    assert document["capture_state"] == "incomplete"
    assert not calls
    assert not (run_root / "run.json").exists()


def test_input_drift_guard_covers_all_frozen_inputs(cursor_case, monkeypatch, tmp_path):
    plan = slice_workspace.build_plan(str(cursor_case.task_root))
    task_root = Path(str(plan["task_root"]))
    launcher = runner._verify_executable(str(cursor_case.exe), cursor_case.exe_sha256)
    config = cursor._cursor_config(task_root, plan)
    inputs = cursor._cursor_inputs(task_root, plan)
    cursor._verify_inputs_unchanged(task_root, plan, launcher, config, inputs["task_bytes"])
    original = cursor_case.config_path.read_bytes()
    cursor_case.config_path.write_bytes(b'{"permissions": {"allow": []}}\n')
    with pytest.raises(runner.SliceRunError, match="project config drifted"):
        cursor._verify_inputs_unchanged(task_root, plan, launcher, config, inputs["task_bytes"])
    cursor_case.config_path.write_bytes(original)
    cursor._verify_inputs_unchanged(task_root, plan, launcher, config, inputs["task_bytes"])


def test_capture_failure_drains_and_stays_unsealed(cursor_case, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(
        cursor,
        "_session_store",
        lambda: SessionStore(
            TEST_KEY,
            root=tmp_path / "session-state",
            limit=2500,
            terminal_reserve=512,
            receipt_reserve=512,
        ),
    )
    spawned: list = []

    def fake_spawn(argv, cwd):
        spawned.append(argv)
        return _FakeProcess(stdout_chunks=[b"z" * 2000])

    monkeypatch.setattr(runner, "spawn_suspended_in_job", fake_spawn)
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert code == 3
    assert document["result"] == "capture_incomplete"
    assert document["launches"] == 1
    assert document["session"]["sealed"] is False
    assert len(spawned) == 1
    assert not list(run_root.rglob("*.raw"))


def test_cli_surface_and_agy_surface_unchanged(cursor_case, capsys):
    assert "cursor" in cli.SUBCOMMANDS
    assert cli.main(["--help"]) == 0
    assert "cursor" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exit_info:
        cursor._build_parser().parse_args(
            [
                "run",
                "--task-root",
                "x",
                "--run-root",
                "y",
                "--exe",
                "z",
                "--exe-sha256",
                "0" * 64,
                "--model",
                "evil",
            ]
        )
    assert exit_info.value.code == 2
    assert "gemini-3.8-flash-high" in runner.FIXED_ARGV_TAIL
    assert cursor.CURSOR_MODEL not in runner.FIXED_ARGV_TAIL
    assert not hasattr(runner, "CURSOR_MODEL")


def test_run_root_reuse_and_task_overlap_refused(cursor_case, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(
        runner,
        "spawn_suspended_in_job",
        lambda argv, cwd: _FakeProcess(stdout_chunks=[b"{}\n"]),
    )
    run_root = tmp_path / "run-root"
    first = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert first[0] == 0
    second = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert second[0] == 2 and second[1] == {}
    inside = cursor_case.task_root / "nested-run"
    third = _main(_run_arguments(cursor_case, inside, execute=False), capsys)
    assert third[0] == 2 and "task root" in third[2]


def test_config_drift_between_verified_plan_and_read_is_refused(
    cursor_case, capsys, monkeypatch, tmp_path
):
    """A config changed after the plan was verified cannot supply its own baseline.

    `build_plan` verifies the work tree against the prepared manifest, but the
    config bytes are read afterwards. Rewriting the config in that window must
    still be refused against the frozen manifest entry, not accepted as the new
    comparison basis.
    """
    verified_build_plan = slice_workspace.build_plan
    changed_config = b'{"permissions":{"allow":["Shell(*)"],"deny":[]}}\n'
    evidence: dict = {}

    def mutate_after_verified_plan(task_root):
        plan = verified_build_plan(task_root)
        manifest = json.loads((Path(task_root) / "manifest.json").read_bytes())
        frozen = next(
            item for item in manifest["files"] if item["path"] == cursor.CURSOR_CONFIG_RELATIVE
        )
        evidence["manifest_config_sha256"] = frozen["sha256"]
        cursor_case.config_path.write_bytes(changed_config)
        evidence["config_after_plan_sha256"] = runner._sha256_file(cursor_case.config_path)
        assert evidence["config_after_plan_sha256"] != frozen["sha256"]
        return plan

    calls = _no_launch(monkeypatch)
    monkeypatch.setattr(slice_workspace, "build_plan", mutate_after_verified_plan)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert (code, document, len(calls)) == (2, {}, 0)
    assert "differs from the prepared manifest" in err
    assert not run_root.exists()
    assert evidence["manifest_config_sha256"] != evidence["config_after_plan_sha256"]


def test_config_swapped_manifest_is_not_accepted_as_the_frozen_source(
    cursor_case, capsys, monkeypatch, tmp_path
):
    """A manifest swapped after verification cannot re-freeze a changed config."""
    verified_build_plan = slice_workspace.build_plan
    changed_config = b'{"permissions":{"allow":["Shell(*)"],"deny":[]}}\n'

    def swap_manifest_after_verified_plan(task_root):
        plan = verified_build_plan(task_root)
        task_root = Path(str(plan["task_root"]))
        manifest_path = task_root / "manifest.json"
        document = json.loads(manifest_path.read_bytes())
        for item in document["files"]:
            if item["path"] == cursor.CURSOR_CONFIG_RELATIVE:
                item["bytes"] = len(changed_config)
                item["sha256"] = runner._sha256_hex(changed_config)
        manifest_path.write_bytes(
            json.dumps(
                document, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            + b"\n"
        )
        cursor_case.config_path.write_bytes(changed_config)
        return plan

    calls = _no_launch(monkeypatch)
    monkeypatch.setattr(slice_workspace, "build_plan", swap_manifest_after_verified_plan)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert (code, document, len(calls)) == (2, {}, 0)
    assert "no longer matches the verified plan" in err
    assert not run_root.exists()


def test_cursor_config_bytes_must_match_the_frozen_manifest_entry(
    cursor_case, monkeypatch, tmp_path
):
    """The reported config identity is the frozen entry, not whatever is on disk."""
    plan = slice_workspace.build_plan(str(cursor_case.task_root))
    task_root = Path(str(plan["task_root"]))
    expected = runner._sha256_file(cursor_case.config_path)
    recorded = cursor._cursor_config(task_root, plan)
    assert recorded["sha256"] == expected
    assert recorded["size_bytes"] == len(cursor_case.config_path.read_bytes())
    cursor_case.config_path.write_bytes(b'{"permissions": {"allow": []}}\n')
    with pytest.raises(runner.SliceRunError, match="differs from the prepared manifest"):
        cursor._cursor_config(task_root, plan)


def _prepare_task_with_config_bytes(tmp_path: Path, config_bytes: bytes) -> Path:
    """Prepare a real task whose frozen config carries the given exact bytes."""
    repository = tmp_path / "invalid-config-repo"
    (repository / "src").mkdir(parents=True)
    (repository / ".cursor").mkdir()
    (repository / "src" / "alpha.py").write_bytes(b"def alpha():\n    return 1\n")
    (repository / ".cursor" / "cli.json").write_bytes(config_bytes)

    def git(*arguments: str) -> bytes:
        done = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "-c",
                "user.email=tests@example.invalid",
                "-c",
                "user.name=tests",
                *arguments,
            ],
            capture_output=True,
        )
        assert done.returncode == 0, done.stderr
        return done.stdout

    git("init", "-q")
    git("add", ".")
    git("commit", "-q", "-m", "base")
    commit = git("rev-parse", "HEAD").decode("ascii").strip()
    note = tmp_path / "note.md"
    note.write_bytes(NOTE_BYTES)
    task_root = tmp_path / "invalid-config-task"
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = cli.main(
            [
                "prepare",
                "--repository",
                str(repository),
                "--commit",
                commit,
                "--task-note",
                str(note),
                "--file",
                "src/alpha.py",
                "--editable",
                "src/alpha.py",
                "--file",
                ".cursor/cli.json",
                "--out",
                str(task_root),
            ]
        )
    assert code == 0, buffer.getvalue()
    return task_root


def test_invalid_but_prepared_config_is_a_controlled_refusal(
    cursor_case, capsys, monkeypatch, tmp_path
):
    """A frozen config that is not strict JSON must refuse, not raise.

    `prepare` accepts any existing text file, so a syntactically invalid
    config can be frozen legitimately. Its length and hash then match the
    manifest, and only the strict decode fails. That failure must reach the
    documented refusal path instead of escaping as an uncaught error.
    """
    cursor_case.task_root = _prepare_task_with_config_bytes(tmp_path, b"{\n")
    calls = _no_launch(monkeypatch)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert code == 2 and document == {}
    assert "not one strict JSON document" in err
    assert "{" not in err
    assert not calls
    assert not run_root.exists()


def test_invalid_prepared_config_does_not_touch_the_session_key(
    cursor_case, capsys, monkeypatch, tmp_path
):
    cursor_case.task_root = _prepare_task_with_config_bytes(tmp_path, b"{\n")

    def forbidden_key() -> None:
        raise AssertionError("the invalid config must be refused before any key is read")

    monkeypatch.setattr(cursor, "_session_store", forbidden_key)
    _no_launch(monkeypatch)
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert code == 2 and document == {}
    assert not run_root.exists()


def test_preflight_also_refuses_invalid_prepared_config(cursor_case, capsys, monkeypatch, tmp_path):
    cursor_case.task_root = _prepare_task_with_config_bytes(tmp_path, b'{"permissions": }\n')
    calls = _no_launch(monkeypatch)
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(cursor_case, run_root, execute=False), capsys)
    assert code == 2 and document == {}
    assert not calls
    assert not run_root.exists()


def test_valid_prepared_config_still_passes(cursor_case, capsys, monkeypatch, tmp_path):
    """The strict-JSON refusal must not disturb the ordinary valid path."""
    configured = _prepare_task_with_config_bytes(tmp_path, CONFIG_BYTES)
    cursor_case.task_root = configured
    monkeypatch.setattr(
        runner, "spawn_suspended_in_job", lambda argv, cwd: _FakeProcess(stdout_chunks=[b"{}\n"])
    )
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert (code, err) == (0, "")
    assert document["result"] == "lifecycle_complete_capture_sealed"
    assert document["session"]["sealed"] is True
    receipt = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert receipt["cursor_config"]["sha256"] == runner._sha256_file(
        configured / "work" / ".cursor" / "cli.json"
    )


def test_duplicate_key_manifest_that_verifies_is_a_controlled_refusal(
    cursor_case, capsys, monkeypatch, tmp_path
):
    """A manifest that passes the slice parser but not the strict decoder refuses."""
    manifest_path = cursor_case.task_root / "manifest.json"
    good = manifest_path.read_bytes().decode("utf-8")
    duplicated = good.replace('{"editable":', '{"manifest_version":1,"editable":', 1)
    assert duplicated != good
    manifest_path.write_bytes(duplicated.encode("utf-8"))
    calls = _no_launch(monkeypatch)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(cursor_case, run_root, execute=True), capsys)
    assert code == 2 and document == {}
    assert "local-agent-bridge:" in err
    assert "manifest_version" not in err
    assert not calls
    assert not run_root.exists()
