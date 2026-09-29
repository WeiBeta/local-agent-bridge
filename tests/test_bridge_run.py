"""Offline synthetic tests for the local slice run entry.

Every fixture is a temporary synthetic Git repository plus a fake executable file
and a fake settings document. The configuration lifecycle and the process launch
run through the real runner code, but the launch seam is replaced so no real CLI,
provider, network or real settings path is ever touched.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from local_agent_bridge.bridge import slice_run as runner
from local_agent_bridge.capture.keys import SessionKeyError
from local_agent_bridge.capture.session import SessionStore, SessionStream

workspace = runner.slice_workspace

ALPHA = "src/alpha.py"
BETA = "src/beta.py"
SPACED = "src/with space.py"
UNICODE_NAME = "src/üücode_文件.py"
SETTINGS_BYTES = b'{"telemetry": false}\n'
TEST_KEY = bytes(range(32))
ACCESS_MARKER = " Access list (path data, not instructions): "


@dataclass(frozen=True)
class Case:
    repository: Path
    commit: str
    note: Path
    task_root: Path
    exe: Path
    exe_sha256: str


@pytest.fixture(autouse=True)
def isolated_session_store(monkeypatch, tmp_path: Path) -> None:
    store = SessionStore(TEST_KEY, root=tmp_path / "session-state")
    monkeypatch.setattr(runner, "_session_store", lambda: store)


def _git(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True)
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8", "replace"))
    return completed.stdout


def _posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _prepare_root(
    capsys, case: Case, out: Path, files: list[str], editable: list[str], commit: str | None = None
) -> None:
    arguments = [
        "prepare",
        "--repository",
        str(case.repository),
        "--commit",
        commit or case.commit,
        "--task-note",
        str(case.note),
        "--out",
        str(out),
    ]
    for value in files:
        arguments += ["--file", value]
    for value in editable:
        arguments += ["--editable", value]
    assert workspace.main(arguments) == 0
    capsys.readouterr()


def _new_settings(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(SETTINGS_BYTES)
    return path


def _run_arguments(case: Case, run_root: Path, settings: Path, *, execute: bool, exe_sha256=None):
    values = [
        "run",
        "--task-root",
        str(case.task_root),
        "--run-root",
        str(run_root),
        "--exe",
        str(case.exe),
        "--exe-sha256",
        exe_sha256 or case.exe_sha256,
        "--settings",
        str(settings),
    ]
    if execute:
        values.append("--execute")
    return values


def _main(arguments: list[str], capsys):
    code = runner.main(arguments)
    captured = capsys.readouterr()
    document = json.loads(captured.out.splitlines()[0]) if captured.out.strip() else {}
    return code, document, captured.err


def _install_fake_launch(monkeypatch, calls: list, behavior) -> None:
    def fake_launch(exe, argv, cwd, stdout_path, stderr_path):
        calls.append({"exe": exe, "argv": list(argv), "cwd": cwd})
        behavior(stdout_path, stderr_path)
        return {
            "pid": 4242,
            "spawn_state": "confirmed",
            "capture_state": "complete",
            "capture_error": None,
            "exit_code": 0,
            "timed_out": False,
            "started_utc": "2026-09-23T00:00:00+00:00",
            "elapsed_seconds": 0.5,
            "observation_timeout_seconds": runner.OBSERVATION_TIMEOUT_SECONDS,
            "stdout_bytes": stdout_path.stat().st_size,
            "stdout_sha256": runner._sha256_file(stdout_path),
            "stdout_truncated": False,
            "stderr_bytes": stderr_path.stat().st_size,
            "stderr_sha256": runner._sha256_file(stderr_path),
            "stderr_truncated": False,
        }

    monkeypatch.setattr(runner, "_launch_and_capture", fake_launch)


def _write_success(stdout_path: Path, stderr_path: Path) -> None:
    stdout_path.write_bytes(
        b'{"type":"init","model":"gemini-3.8-flash-high"}\n{"type":"result","status":"SUCCESS"}\n'
    )
    stderr_path.write_bytes(b"")


class _FakeStream:
    def __init__(self, chunks: list[bytes] | None = None, error: Exception | None = None):
        self._chunks = list(chunks or [])
        self._error = error

    def read(self, size: int = -1) -> bytes:
        if self._error is not None:
            raise self._error
        if self._chunks:
            return self._chunks.pop(0)
        return b""


class _StalledStream:
    def __init__(self, delay: float) -> None:
        self._delay = delay

    def read(self, size: int = -1) -> bytes:
        time.sleep(self._delay)
        return b""


class _FakeProcess:
    def __init__(self, stdout_stream, stderr_stream) -> None:
        self.stdout = stdout_stream
        self.stderr = stderr_stream
        self.pid = 5353
        self.returncode = 0
        self.closed_job = False
        self.terminated = False

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def terminate_once(self) -> bool:
        self.terminated = True
        return True

    def close_job(self) -> bool:
        self.closed_job = True
        return True


@pytest.fixture
def case(tmp_path: Path, capsys) -> Case:
    repository = tmp_path / "source-repo"
    (repository / "src").mkdir(parents=True)
    _git(repository, "init")
    _git(repository, "config", "user.email", "tests@example.invalid")
    _git(repository, "config", "user.name", "Ask AI Tests")
    (repository / "src" / "alpha.py").write_bytes(b"def alpha():\n    return 1\n")
    (repository / "src" / "beta.py").write_bytes(b"def beta():\n    return 2\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "base")
    commit = _git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    note = tmp_path / "note.md"
    note.write_bytes(b"synthetic runner note\n")
    task_root = tmp_path / "slice-task"
    case = Case(
        repository=repository,
        commit=commit,
        note=note,
        task_root=task_root,
        exe=tmp_path / "fake-agy.exe",
        exe_sha256="",
    )
    case.exe.write_bytes(b"fake agy cli payload\n")
    object.__setattr__(case, "exe_sha256", runner._sha256_file(case.exe))
    _prepare_root(capsys, case, task_root, [ALPHA, BETA], [ALPHA])
    return case


def test_preflight_reports_and_changes_nothing(case, capsys, monkeypatch, tmp_path) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    run_root = tmp_path / "run-root"
    monkeypatch.setattr(
        runner,
        "_launch_and_capture",
        lambda *arguments, **keywords: pytest.fail("preflight must not launch"),
    )
    code, document, err = _main(_run_arguments(case, run_root, settings, execute=False), capsys)
    assert (code, err) == (0, "")
    assert document["mode"] == "preflight"
    assert document["execute"] is False
    assert document["run_root_would_create"].endswith("run-root")
    assert document["executable"]["sha256"] == case.exe_sha256
    assert document["settings"]["permissions_absent"] is True
    assert settings.read_bytes() == SETTINGS_BYTES
    assert not run_root.exists()


def test_execute_completes_for_two_different_slices(case, capsys, monkeypatch, tmp_path) -> None:
    second_root = tmp_path / "slice-task-b"
    _prepare_root(capsys, case, second_root, [ALPHA, BETA], [BETA])
    monkeypatch.delenv(runner.AUTO_UPDATE_VARIABLE, raising=False)
    calls: list = []
    _install_fake_launch(monkeypatch, calls, _write_success)
    expected_layout = {
        "plan.json",
        "config-patch.json",
        "config-restore.json",
        "run.json",
        "capture",
        "private",
    }
    for index, (task_root, settings_name) in enumerate(
        [(case.task_root, "settings-a.json"), (second_root, "settings-b.json")]
    ):
        settings = _new_settings(tmp_path, settings_name)
        run_root = tmp_path / f"run-{index}"
        arguments = _run_arguments(
            Case(
                case.repository,
                case.commit,
                case.note,
                task_root,
                case.exe,
                case.exe_sha256,
            ),
            run_root,
            settings,
            execute=True,
        )
        code, document, err = _main(arguments, capsys)
        assert (code, err) == (0, ""), document
        assert document["launches"] == 1
        assert document["coding"]["outcome"] == "provider_completed"
        assert document["restore"]["status"] == "restored"
        assert settings.read_bytes() == SETTINGS_BYTES
        assert {entry.name for entry in run_root.iterdir()} == expected_layout
        receipt = json.loads((run_root / "run.json").read_bytes())
        assert receipt["launches"] == 1
        assert receipt["coding"] == {"outcome": "provider_completed", "result_status": "SUCCESS"}
        assert receipt["spawn_state"] == "confirmed"
        assert receipt["restore"]["restored_original_bytes"] is True
        patch = json.loads((run_root / "config-patch.json").read_bytes())
        plan = workspace.build_plan(str(task_root))
        assert patch["rules"] == [
            *plan["permission_rules"]["read_file"],
            *plan["permission_rules"]["write_file"],
        ]
        assert patch["rule_counts"]["command"] == 0
        assert patch["only_permissions_added"] is True
        assert not list((run_root / "capture").iterdir())
        assert (
            SessionStore(TEST_KEY, root=tmp_path / "session-state")
            .reader(document["session"]["session_id"])
            .read_stream("stdout")
            .endswith(b'"status":"SUCCESS"}\n')
        )
    assert len(calls) == 2
    first, second = calls
    assert _posix(Path(first["cwd"])).endswith("/slice-task/work")
    assert first["argv"][0] == str(case.exe)
    assert first["argv"][1] == "--print"
    assert len(first["argv"]) == 12
    assert first["argv"] != second["argv"]
    assert os.environ.get(runner.AUTO_UPDATE_VARIABLE) is None


def test_execute_keeps_space_and_unicode_paths_in_one_argv_element(
    case: Case, capsys, monkeypatch, tmp_path: Path
) -> None:
    (case.repository / "src" / "with space.py").write_bytes(b"spaced = 1\n")
    (case.repository / "src" / "üücode_文件.py").write_bytes(b"unicode = 1\n")
    _git(case.repository, "add", ".")
    _git(case.repository, "commit", "-m", "odd names")
    commit = _git(case.repository, "rev-parse", "HEAD").decode("ascii").strip()
    odd_root = tmp_path / "slice-odd"
    _prepare_root(capsys, case, odd_root, [SPACED, UNICODE_NAME], [SPACED, UNICODE_NAME], commit)
    calls: list = []
    _install_fake_launch(monkeypatch, calls, _write_success)
    odd_case = Case(case.repository, case.commit, case.note, odd_root, case.exe, case.exe_sha256)
    settings = _new_settings(tmp_path, "settings-odd.json")
    code, document, err = _main(
        _run_arguments(odd_case, tmp_path / "run-odd", settings, execute=True), capsys
    )
    assert (code, err) == (0, ""), document
    argv = calls[0]["argv"]
    assert len(argv) == 12
    assert argv[1] == "--print"
    prompt = argv[2]
    assert prompt.count(ACCESS_MARKER) == 1
    _, _, payload_text = prompt.partition(ACCESS_MARKER)
    payload = json.loads(payload_text)
    assert payload["writable"] == [
        _posix(odd_root) + "/work/" + SPACED,
        _posix(odd_root) + "/work/" + UNICODE_NAME,
    ]


def test_input_drift_refuses_with_zero_launches(case: Case, capsys, monkeypatch, tmp_path) -> None:
    (case.task_root / "work" / "src" / "alpha.py").write_bytes(b"def alpha():\n    return 9\n")
    settings = _new_settings(tmp_path, "settings.json")
    monkeypatch.setattr(
        runner,
        "_launch_and_capture",
        lambda *arguments, **keywords: pytest.fail("drifted input must not launch"),
    )
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 2
    assert document == {}
    assert "untouched work tree" in err
    assert settings.read_bytes() == SETTINGS_BYTES
    assert not run_root.exists()


def test_unknown_executable_refuses_with_zero_launches(case, capsys, monkeypatch, tmp_path) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    monkeypatch.setattr(
        runner,
        "_launch_and_capture",
        lambda *arguments, **keywords: pytest.fail("unknown executable must not launch"),
    )
    run_root = tmp_path / "run-root"
    arguments = _run_arguments(case, run_root, settings, execute=True, exe_sha256="0" * 64)
    code, _document, err = _main(arguments, capsys)
    assert code == 2
    assert "executable sha256 mismatch" in err
    assert settings.read_bytes() == SETTINGS_BYTES
    assert not run_root.exists()


@pytest.mark.parametrize("execute", [False, True])
def test_existing_permissions_are_refused_without_launch(
    case: Case, capsys, monkeypatch, tmp_path, execute: bool
) -> None:
    polluted_bytes = b'{"permissions": {"allow": ["read_file(C:/other/TASK.md)"]}}\n'
    settings = tmp_path / "settings-polluted.json"
    settings.write_bytes(polluted_bytes)
    monkeypatch.setattr(
        runner,
        "_launch_and_capture",
        lambda *arguments, **keywords: pytest.fail("polluted settings must not launch"),
    )
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(case, run_root, settings, execute=execute), capsys)
    assert code == 2
    assert document == {}
    assert "already carries a permissions key" in err
    assert settings.read_bytes() == polluted_bytes
    assert not run_root.exists()


def test_existing_run_output_is_refused(case: Case, capsys, monkeypatch, tmp_path) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    run_root = tmp_path / "run-root"
    calls: list = []
    _install_fake_launch(monkeypatch, calls, _write_success)
    assert runner.main(_run_arguments(case, run_root, settings, execute=True)) == 0
    capsys.readouterr()
    receipt_bytes = (run_root / "run.json").read_bytes()
    code, _document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 2
    assert "already exists" in err
    assert (run_root / "run.json").read_bytes() == receipt_bytes
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("writer", "outcome"),
    [
        (b'{"type":"result","status":"ERROR"}\n', "model_error"),
        (b'{"type":"step_update"}\n', "result_missing"),
    ],
)
def test_model_failure_and_missing_result_restore_settings(
    case: Case, capsys, monkeypatch, tmp_path, writer: bytes, outcome: str
) -> None:
    settings = _new_settings(tmp_path, "settings.json")

    def behavior(stdout_path: Path, stderr_path: Path) -> None:
        stdout_path.write_bytes(writer)
        stderr_path.write_bytes(b"")

    calls: list = []
    _install_fake_launch(monkeypatch, calls, behavior)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert (code, err) == (0, ""), document
    assert document["coding"]["outcome"] == outcome
    assert document["restore"]["status"] == "restored"
    assert settings.read_bytes() == SETTINGS_BYTES


def test_timeout_restores_settings(case: Case, capsys, monkeypatch, tmp_path) -> None:
    settings = _new_settings(tmp_path, "settings.json")

    def fake_launch(exe, argv, cwd, stdout_path, stderr_path):
        stdout_path.write_bytes(b'{"type":"init"}\n')
        stderr_path.write_bytes(b"")
        return {
            "pid": 4242,
            "spawn_state": "confirmed",
            "capture_state": "complete",
            "capture_error": None,
            "exit_code": None,
            "timed_out": True,
            "started_utc": "2026-09-23T00:00:00+00:00",
            "elapsed_seconds": runner.OBSERVATION_TIMEOUT_SECONDS,
            "observation_timeout_seconds": runner.OBSERVATION_TIMEOUT_SECONDS,
            "stdout_bytes": stdout_path.stat().st_size,
            "stdout_sha256": runner._sha256_file(stdout_path),
            "stdout_truncated": False,
            "stderr_bytes": 0,
            "stderr_sha256": runner._sha256_file(stderr_path),
            "stderr_truncated": False,
        }

    monkeypatch.setattr(runner, "_launch_and_capture", fake_launch)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert (code, err) == (0, ""), document
    assert document["coding"]["outcome"] == "observation_timeout"
    assert document["restore"]["status"] == "restored"
    assert settings.read_bytes() == SETTINGS_BYTES


def test_capture_exception_restores_and_reports_failure(
    case, capsys, monkeypatch, tmp_path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")

    def fake_launch(exe, argv, cwd, stdout_path, stderr_path):
        raise RuntimeError("capture exploded")

    monkeypatch.setattr(runner, "_launch_and_capture", fake_launch)
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 3
    assert document["lifecycle_exception"] == "RuntimeError"
    assert document["restore"]["status"] == "restored"
    assert settings.read_bytes() == SETTINGS_BYTES
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert receipt["launch_attempts"] == 1
    assert receipt["launches"] == 0
    assert receipt["spawn_state"] == "not_confirmed"


def test_semantic_config_drift_is_not_overwritten(case, capsys, monkeypatch, tmp_path) -> None:
    settings = _new_settings(tmp_path, "settings.json")

    def behavior(stdout_path: Path, stderr_path: Path) -> None:
        _write_success(stdout_path, stderr_path)
        settings.write_bytes(b'{"telemetry": false, "extra": true}\n')

    calls: list = []
    _install_fake_launch(monkeypatch, calls, behavior)
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 3
    assert document["restore"]["status"] == "restore_blocked_semantic_or_invalid_drift"
    assert settings.read_bytes() == b'{"telemetry": false, "extra": true}\n'
    assert (run_root / "private" / "settings.drift-01.bin").exists()


def test_json_layout_drift_restores_original(case: Case, capsys, monkeypatch, tmp_path) -> None:
    settings = _new_settings(tmp_path, "settings.json")

    def behavior(stdout_path: Path, stderr_path: Path) -> None:
        _write_success(stdout_path, stderr_path)
        patched_text = settings.read_text(encoding="utf-8")
        settings.write_bytes(patched_text.replace(",", " , ").encode("utf-8"))

    calls: list = []
    _install_fake_launch(monkeypatch, calls, behavior)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert (code, err) == (0, ""), document
    assert document["restore"]["status"] == "restored_json_legal_layout_drift"
    assert settings.read_bytes() == SETTINGS_BYTES
    assert (run_root / "private" / "settings.drift-01.bin").exists()


def test_restore_failure_is_visible(case: Case, capsys, monkeypatch, tmp_path) -> None:
    settings = _new_settings(tmp_path, "settings.json")

    def behavior(stdout_path: Path, stderr_path: Path) -> None:
        _write_success(stdout_path, stderr_path)
        os.chmod(settings, stat.S_IREAD)

    calls: list = []
    _install_fake_launch(monkeypatch, calls, behavior)
    run_root = tmp_path / "run-root"
    try:
        code, document, _err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    finally:
        os.chmod(settings, stat.S_IWRITE)
    assert code == 3
    assert document["restore"]["status"] == "restore_failed"
    assert document["restore"]["restored_original_bytes"] is False


def test_real_seam_runs_one_local_child_once(tmp_path: Path) -> None:
    store = SessionStore(TEST_KEY, root=tmp_path / "session-state")
    writer = store.start()
    stdout_path = writer.stream("stdout")
    stderr_path = writer.stream("stderr")
    program = "import json; print(json.dumps({'type': 'result', 'status': 'SUCCESS'}))"
    record = runner._launch_and_capture(
        sys.executable,
        [sys.executable, "-c", program],
        str(tmp_path),
        stdout_path,
        stderr_path,
    )
    assert record["exit_code"] == 0
    assert record["timed_out"] is False
    assert record["capture_state"] == "complete"
    assert record["spawn_state"] == "confirmed"
    captured = stdout_path.read_bytes()
    assert b'"status": "SUCCESS"' in captured
    assert stderr_path.read_bytes() == b""
    writer.seal({"process_exit_code": 0})
    assert store.reader(writer.session_id).read_stream("stdout") == captured
    assert not list(tmp_path.glob("*.raw"))


def test_full_synthetic_process_restores_and_seals_without_raw_copies(
    case: Case, capsys, monkeypatch, tmp_path: Path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    run_root = tmp_path / "run-root"
    synthetic_exe = Path(sys.executable)
    # The fixed Bridge flags make Python exit nonzero; that is a model outcome,
    # while the real child/Job/pipe/settings lifecycle still completes.
    synthetic_case = Case(
        case.repository,
        case.commit,
        case.note,
        case.task_root,
        synthetic_exe,
        runner._sha256_file(synthetic_exe),
    )
    code, document, err = _main(
        _run_arguments(synthetic_case, run_root, settings, execute=True), capsys
    )
    assert (code, err) == (0, ""), document
    assert document["launches"] == 1
    assert document["spawn_state"] == "confirmed"
    assert document["coding"]["outcome"] == "nonzero_exit"
    assert document["restore"]["restored_original_bytes"] is True
    assert settings.read_bytes() == SETTINGS_BYTES
    assert document["session"]["sealed"] is True
    store = SessionStore(TEST_KEY, root=tmp_path / "session-state")
    reader = store.reader(document["session"]["session_id"])
    assert reader.read_stream("task") == b"synthetic runner note\n"
    assert (
        reader.read_stream("request")
        == workspace.build_plan(str(case.task_root))["argv"][1].encode()
    )
    assert len(reader.read_stream("stderr")) > 0
    assert not list((run_root / "capture").glob("*.raw"))


def test_missing_session_key_refuses_before_run_root_or_spawn(
    case: Case, capsys, monkeypatch, tmp_path: Path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    run_root = tmp_path / "run-root"
    monkeypatch.setattr(
        runner,
        "_session_store",
        lambda: (_ for _ in ()).throw(SessionKeyError("session key missing")),
    )
    monkeypatch.setattr(runner, "_launch_and_capture", lambda *args: pytest.fail("must not spawn"))
    code, _document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 2
    assert "session key missing" in err
    assert not run_root.exists()
    assert settings.read_bytes() == SETTINGS_BYTES


def test_prelaunch_session_over_limit_reports_no_content_reason(
    case: Case, capsys, monkeypatch, tmp_path: Path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    store = SessionStore(
        TEST_KEY,
        root=tmp_path / "session-state",
        limit=600,
        terminal_reserve=256,
        receipt_reserve=128,
    )
    monkeypatch.setattr(runner, "_session_store", lambda: store)
    monkeypatch.setattr(runner, "_launch_and_capture", lambda *args: pytest.fail("must not spawn"))
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 2
    assert document["setup_reason"] == "over_limit"
    assert document["capture_state"] == "incomplete"
    assert "synthetic runner note" not in json.dumps(document)
    assert settings.read_bytes() == SETTINGS_BYTES


def test_no_room_for_roll_receipt_reports_over_limit_before_spawn(
    case: Case, capsys, monkeypatch, tmp_path: Path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    root = tmp_path / "session-state"
    original = SessionStore(TEST_KEY, root=root, limit=20_000)
    writer = original.start()
    assert writer.append("task", b"x" * 2000)
    writer.seal({})
    tight = SessionStore(TEST_KEY, root=root, limit=original.domain.used_bytes() + 1)
    monkeypatch.setattr(runner, "_session_store", lambda: tight)
    monkeypatch.setattr(runner, "_launch_and_capture", lambda *args: pytest.fail("must not spawn"))
    code, document, _err = _main(
        _run_arguments(case, tmp_path / "run-root", settings, execute=True), capsys
    )
    assert code == 2
    assert document["setup_reason"] == "over_limit"
    assert document["capture_state"] == "incomplete"
    assert writer.path.exists()
    assert settings.read_bytes() == SETTINGS_BYTES


def test_task_note_drift_between_plan_and_capture_refuses_spawn(
    case: Case, capsys, monkeypatch, tmp_path: Path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    store = SessionStore(TEST_KEY, root=tmp_path / "session-state")

    def changed_note_store():
        (case.task_root / "work" / "TASK.md").write_bytes(b"changed after plan\n")
        return store

    monkeypatch.setattr(runner, "_session_store", changed_note_store)
    monkeypatch.setattr(runner, "_launch_and_capture", lambda *args: pytest.fail("must not spawn"))
    code, document, _err = _main(
        _run_arguments(case, tmp_path / "run-root", settings, execute=True), capsys
    )
    assert code == 2
    assert document["setup_reason"] == "capture_unavailable"
    assert settings.read_bytes() == SETTINGS_BYTES


@pytest.mark.parametrize("failure", ["over_limit", "disk_write"])
def test_capture_failure_drains_pipe_and_restores(
    case: Case, capsys, monkeypatch, tmp_path: Path, failure: str
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    store = SessionStore(
        TEST_KEY,
        root=tmp_path / "session-state",
        limit=2500,
        terminal_reserve=512,
        receipt_reserve=512,
    )
    monkeypatch.setattr(runner, "_session_store", lambda: store)
    output = b"z" * 2000
    process = _FakeProcess(_FakeStream(chunks=[output]), _FakeStream())
    monkeypatch.setattr(runner, "spawn_suspended_in_job", lambda argv, cwd: process)
    if failure == "disk_write":
        original_reserve = store.domain.reserve
        calls = {"count": 0}

        def reserve(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] >= 4:
                raise OSError("synthetic disk error")
            return original_reserve(*args, **kwargs)

        monkeypatch.setattr(store.domain, "reserve", reserve)
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 3
    assert document["launches"] == 1
    assert document["coding"]["outcome"] == "capture_incomplete"
    assert document["restore"]["restored_original_bytes"] is True
    assert settings.read_bytes() == SETTINGS_BYTES
    assert process.closed_job is True
    assert document["session"]["sealed"] is False
    assert not list((run_root / "capture").glob("*.raw"))


def test_encrypted_frames_preserve_wrapped_event_across_chunk_boundary(tmp_path: Path) -> None:
    store = SessionStore(TEST_KEY, root=tmp_path / "session-state")
    writer = store.start()
    sink = writer.stream("stdout")
    assert sink.append(b'{"event":"result","result":{"sta')
    assert sink.append(b'tus":"SUCCESS"}}\n')
    launch = {
        "capture_state": "complete",
        "timed_out": False,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "exit_code": 0,
    }
    assert runner._classify_coding(sink, launch) == {
        "outcome": "provider_completed",
        "result_status": "SUCCESS",
    }


@pytest.mark.parametrize(
    ("stream_bytes", "record_overrides", "outcome"),
    [
        (
            b'{"type":"step_update","denied_actions":["write_file(deny)"]}\n'
            b'{"type":"result","status":"SUCCESS"}\n',
            {},
            "denied_actions",
        ),
        (
            b'{"type":"result","status":"SUCCESS"}\n',
            {"exit_code": 1},
            "nonzero_exit",
        ),
        (
            b'{"type":"result","status":"SUCCESS"}\n',
            {"stdout_truncated": True},
            "capture_truncated",
        ),
        (
            b'{"type":"result","status":"SUCCESS"}\n{"type":"result","status":"ERROR"}\n',
            {},
            "conflicting_terminal_states",
        ),
        (
            b'{"type":"result","status":"SUCCESS"}\n',
            {"capture_state": "incomplete", "capture_error": "OSError"},
            "capture_incomplete",
        ),
    ],
)
def test_provider_completed_requires_clean_capture_exit_and_single_terminal(
    case, capsys, monkeypatch, tmp_path, stream_bytes: bytes, record_overrides, outcome: str
) -> None:
    settings = _new_settings(tmp_path, "settings.json")

    def behavior(stdout_path: Path, stderr_path: Path) -> None:
        stdout_path.write_bytes(stream_bytes)
        stderr_path.write_bytes(b"")

    calls: list = []
    _install_fake_launch(monkeypatch, calls, behavior)
    if record_overrides:
        original = runner._launch_and_capture

        def patched(*arguments, **keywords):
            record = original(*arguments, **keywords)
            if isinstance(record, dict):
                record.update(record_overrides)
            return record

        monkeypatch.setattr(runner, "_launch_and_capture", patched)
    run_root = tmp_path / "run-root"
    _code, document, _err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert document["coding"]["outcome"] == outcome
    assert document["coding"]["outcome"] != "provider_completed"
    assert document["restore"]["status"] == "restored"
    assert settings.read_bytes() == SETTINGS_BYTES


def test_build_patched_settings_supports_empty_and_non_empty_objects() -> None:
    rules = ["read_file(C:/work/TASK.md)", "write_file(C:/work/a.py)"]
    for before in (b"{}\n", b"{}", b'{"telemetry": false}\n'):
        patched = runner._build_patched_settings(before, rules)
        value = runner._parse_or_none(patched)
        assert isinstance(value, dict)
        assert value["permissions"] == {"allow": rules}
        assert "telemetry" not in value or value["telemetry"] is False


def test_empty_settings_object_executes_and_restores(case, capsys, monkeypatch, tmp_path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_bytes(b"{}\n")
    calls: list = []
    _install_fake_launch(monkeypatch, calls, _write_success)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert (code, err) == (0, ""), document
    assert document["coding"]["outcome"] == "provider_completed"
    assert settings.read_bytes() == b"{}\n"


def test_patch_construction_failure_leaves_no_run_root(case, capsys, monkeypatch, tmp_path) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    monkeypatch.setattr(
        runner,
        "_build_patched_settings",
        lambda *arguments, **keywords: (_ for _ in ()).throw(RuntimeError("unpatchable")),
    )
    monkeypatch.setattr(
        runner,
        "_launch_and_capture",
        lambda *arguments, **keywords: pytest.fail("unpatchable settings must not launch"),
    )
    run_root = tmp_path / "run-root"
    code, _document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 2
    assert "settings patch could not be constructed: RuntimeError" in err
    assert not run_root.exists()
    assert settings.read_bytes() == SETTINGS_BYTES


def test_acl_failure_means_zero_sensitive_writes_and_zero_launch(
    case, capsys, monkeypatch, tmp_path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")

    def failing_protect(path):
        raise runner.SliceRunError("owner-only directory ACL helper failed")

    monkeypatch.setattr(runner, "_protect_directory", failing_protect)
    monkeypatch.setattr(
        runner,
        "_launch_and_capture",
        lambda *arguments, **keywords: pytest.fail("ACL failure must not launch"),
    )
    run_root = tmp_path / "run-root"
    code, _document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 2
    assert "ACL helper failed" in err
    assert settings.read_bytes() == SETTINGS_BYTES
    assert list((run_root / "private").iterdir()) == []
    assert list((run_root / "capture").iterdir()) == []
    assert not (run_root / "private" / "settings.original.bin").exists()


def test_spawn_confirmed_capture_failure_reports_one_launch(
    case, capsys, monkeypatch, tmp_path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    process = _FakeProcess(_FakeStream(error=OSError("broken pipe")), _FakeStream(chunks=[b""]))
    monkeypatch.setattr(runner, "spawn_suspended_in_job", lambda argv, cwd: process)
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 3
    assert document["coding"]["outcome"] == "capture_incomplete"
    assert document["restore"]["status"] == "restored"
    assert settings.read_bytes() == SETTINGS_BYTES
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert receipt["launches"] == 1
    assert receipt["spawn_state"] == "confirmed"
    assert receipt["launch"]["pid"] == 5353
    assert receipt["launch"]["capture_error"] == "OSError"
    assert process.closed_job is True


def test_stalled_reader_is_reported_incomplete_without_hash(
    case, capsys, monkeypatch, tmp_path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    process = _FakeProcess(_StalledStream(0.5), _StalledStream(0.5))
    monkeypatch.setattr(runner, "spawn_suspended_in_job", lambda argv, cwd: process)
    monkeypatch.setattr(runner, "CAPTURE_JOIN_SECONDS", 0.1)
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 3
    assert document["coding"]["outcome"] == "capture_incomplete"
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert receipt["launch"]["capture_error"] == "reader_join_timeout"
    assert receipt["launch"].get("stdout_sha256") is None
    assert process.closed_job is True


def test_reader_start_failure_closes_job_and_reports(case, capsys, monkeypatch, tmp_path) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    process = _FakeProcess(_FakeStream(chunks=[b""]), _FakeStream(chunks=[b""]))

    real_thread = threading.Thread

    class _FailingThread:
        def __init__(self, *arguments, **keywords) -> None:
            target = keywords.get("target") or (arguments[0] if arguments else None)
            if getattr(target, "__name__", "") == "collect":
                raise RuntimeError("thread start unavailable")
            self._real = real_thread(*arguments, **keywords)

        def __getattr__(self, name):
            return getattr(self._real, name)

    monkeypatch.setattr(runner, "spawn_suspended_in_job", lambda argv, cwd: process)
    monkeypatch.setattr(threading, "Thread", _FailingThread)
    run_root = tmp_path / "run-root"
    code, _document, _err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 3
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert receipt["launches"] == 1
    assert receipt["launch"]["capture_error"] == "RuntimeError"
    assert receipt["launch"]["capture_state"] == "incomplete"
    assert process.closed_job is True


def test_restore_hash_read_failure_is_restore_failed(case, capsys, monkeypatch, tmp_path) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    original_hash = runner._sha256_file
    settings_reads = {"count": 0}

    def counted_hash(path: Path) -> str:
        if str(path) == str(settings):
            settings_reads["count"] += 1
            if settings_reads["count"] > 1:
                raise OSError("hash read failed")
        return original_hash(path)

    calls: list = []
    _install_fake_launch(monkeypatch, calls, _write_success)
    monkeypatch.setattr(runner, "_sha256_file", counted_hash)
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 3
    assert document["restore"]["status"] == "restore_failed"
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert receipt["lifecycle_exception"] is None


def test_final_capture_hash_failure_preserves_confirmed_spawn(
    case, capsys, monkeypatch, tmp_path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    process = _FakeProcess(
        _FakeStream(chunks=[b'{"type":"result","status":"SUCCESS"}\n']),
        _FakeStream(),
    )
    monkeypatch.setattr(runner, "spawn_suspended_in_job", lambda argv, cwd: process)
    original_hash = SessionStream.sha256.fget

    def fail_capture_hash(path: SessionStream) -> str:
        if path.name == "stdout":
            raise OSError("capture hash unavailable")
        return original_hash(path)

    monkeypatch.setattr(SessionStream, "sha256", property(fail_capture_hash))
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 3
    assert document["coding"]["outcome"] == "capture_incomplete"
    assert settings.read_bytes() == SETTINGS_BYTES
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert receipt["launches"] == 1
    assert receipt["spawn_state"] == "confirmed"
    assert receipt["launch"]["capture_error"] == "OSError"
    assert "stdout_sha256" not in receipt["launch"]
    assert process.closed_job is True


def test_result_scan_failure_preserves_receipt_and_fails_lifecycle(
    case, capsys, monkeypatch, tmp_path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    calls: list = []
    _install_fake_launch(monkeypatch, calls, _write_success)

    def fail_scan(path: Path):
        raise OSError("result scan unavailable")

    monkeypatch.setattr(runner, "_scan_stream", fail_scan)
    run_root = tmp_path / "run-root"
    code, document, _err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 3
    assert document["coding"]["outcome"] == "capture_incomplete"
    assert settings.read_bytes() == SETTINGS_BYTES
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert receipt["launches"] == 1
    assert receipt["spawn_state"] == "confirmed"
    assert receipt["launch"]["capture_error"] == "OSError"
    assert "stdout_sha256" not in receipt["launch"]


@pytest.mark.parametrize(
    ("stream_bytes", "coding"),
    [
        pytest.param(
            b'{"type":"result","status":"SUCCESS"}\n{"type":"result","status":"SUCCESS"}\n',
            {"outcome": "provider_completed", "result_status": "SUCCESS"},
            id="repeated-identical-success-completes",
        ),
        pytest.param(
            b'{"type":"result","status":"SUCCESS"}\n{"type":"result","status":"ERROR"}\n',
            {"outcome": "conflicting_terminal_states", "result_status": None},
            id="conflicting-statuses-are-refused",
        ),
    ],
)
def test_one_distinct_terminal_status_rule(
    case, capsys, monkeypatch, tmp_path, stream_bytes: bytes, coding: dict
) -> None:
    """F-2: the rule counts distinct terminal statuses, not result lines."""
    settings = _new_settings(tmp_path, "settings.json")

    def behavior(stdout_path: Path, stderr_path: Path) -> None:
        stdout_path.write_bytes(stream_bytes)
        stderr_path.write_bytes(b"")

    calls: list = []
    _install_fake_launch(monkeypatch, calls, behavior)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert (code, err) == (0, ""), document
    assert document["coding"] == coding
    assert settings.read_bytes() == SETTINGS_BYTES


@pytest.mark.parametrize(
    ("stream_bytes", "outcome", "status"),
    [
        pytest.param(
            b'{"event":"init","init":{}}\n'
            b'{"event":"step_update","step_update":{"state":"DONE"}}\n'
            b'{"event":"result","result":{"status":"SUCCESS"}}\n',
            "provider_completed",
            "SUCCESS",
            id="wrapped-success",
        ),
        pytest.param(
            b'{"event":"result","result":{"status":"SUCCESS","denied_actions":["synthetic"]}}\n',
            "denied_actions",
            "SUCCESS",
            id="wrapped-denied-actions",
        ),
        pytest.param(
            b'{"event":"step_update","step_update":{"error":true}}\n'
            b'{"event":"result","result":{"status":"SUCCESS"}}\n',
            "model_error",
            "SUCCESS",
            id="wrapped-error-flag",
        ),
        pytest.param(
            b'{"event":"result","result":{"status":"ERROR"}}\n',
            "model_error",
            "ERROR",
            id="wrapped-error-status",
        ),
        pytest.param(
            b'{"event":"result","result":{"status":"SUCCESS"}}\n'
            b'{"event":"result","result":{"status":"ERROR"}}\n',
            "conflicting_terminal_states",
            None,
            id="wrapped-conflicting-statuses",
        ),
        pytest.param(
            b'{"event":"result","result":{"status":"SUCCESS"}}\n'
            b'{"event":"step_update","step_update":',
            "stream_malformed",
            None,
            id="damaged-line-after-success",
        ),
        pytest.param(
            b'{"event":"result","result":{}}\n',
            "stream_malformed",
            None,
            id="result-without-status",
        ),
        pytest.param(
            b'{"event":"init","init":{}}\n',
            "result_missing",
            None,
            id="missing-terminal-event",
        ),
        pytest.param(
            b'{"event":["result"],"result":{"status":"SUCCESS"}}\n',
            "stream_malformed",
            None,
            id="invalid-event-kind",
        ),
        pytest.param(
            b'{"type":"result","status":"SUCCESS"}\n',
            "provider_completed",
            "SUCCESS",
            id="legacy-flat-success",
        ),
    ],
)
def test_stream_classification_supports_wrapped_and_flat_events(
    tmp_path, stream_bytes: bytes, outcome: str, status: str | None
) -> None:
    """Content-free stream shapes retain the old format and fail closed on damage."""
    stdout_path = tmp_path / "stdout.raw"
    stdout_path.write_bytes(stream_bytes)
    launch_record = {
        "capture_state": "complete",
        "timed_out": False,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "exit_code": 0,
    }
    assert runner._classify_coding(stdout_path, launch_record) == {
        "outcome": outcome,
        "result_status": status,
    }


def test_wrapped_stream_result_is_recorded_without_real_launch(
    case, capsys, monkeypatch, tmp_path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")

    def behavior(stdout_path: Path, stderr_path: Path) -> None:
        stdout_path.write_bytes(b'{"event":"result","result":{"status":"SUCCESS"}}\n')
        stderr_path.write_bytes(b"")

    calls: list = []
    _install_fake_launch(monkeypatch, calls, behavior)
    run_root = tmp_path / "run-root"
    code, document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert (code, err) == (0, ""), document
    assert document["coding"] == {"outcome": "provider_completed", "result_status": "SUCCESS"}
    assert settings.read_bytes() == SETTINGS_BYTES
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert receipt["coding"] == document["coding"]


def _block_run_root_creation(monkeypatch, run_root: Path) -> None:
    """Make exactly the run root mkdir step fail, without touching the file system."""
    real_path_class = runner.Path

    class _UncreatablePath(type(run_root)):
        def mkdir(self, *arguments, **keywords):
            raise OSError("synthetic mkdir failure")

    def path_factory(value):
        created = real_path_class(value)
        return _UncreatablePath(created) if str(created) == str(run_root) else created

    monkeypatch.setattr(runner, "Path", path_factory)


def test_prelaunch_acl_timeout_is_a_controlled_refusal(case, capsys, monkeypatch, tmp_path) -> None:
    settings = _new_settings(tmp_path, "settings.json")

    def failing_protect(path: Path) -> None:
        raise subprocess.TimeoutExpired(["pwsh"], 60)

    monkeypatch.setattr(runner, "_protect_directory", failing_protect)
    monkeypatch.setattr(
        runner,
        "_launch_and_capture",
        lambda *arguments, **keywords: pytest.fail("pre-launch failure must not launch"),
    )
    run_root = tmp_path / "run-root"
    code = runner.main(_run_arguments(case, run_root, settings, execute=True))
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out.count("\n") == 1
    document = json.loads(captured.out)
    assert document["setup_stage"] == "private directory protection"
    assert document["setup_error"] == "TimeoutExpired"
    assert document["receipt_persisted"] is False
    assert document["exit_code"] == 2
    assert "Traceback" not in captured.err
    assert settings.read_bytes() == SETTINGS_BYTES
    assert list((run_root / "private").iterdir()) == []
    assert list((run_root / "capture").iterdir()) == []
    assert not (run_root / "run.json").exists()


def test_prelaunch_run_root_mkdir_failure_is_a_controlled_refusal(
    case, capsys, monkeypatch, tmp_path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    run_root = tmp_path / "run-root"
    _block_run_root_creation(monkeypatch, run_root)
    monkeypatch.setattr(
        runner,
        "_launch_and_capture",
        lambda *arguments, **keywords: pytest.fail("pre-launch failure must not launch"),
    )
    code = runner.main(_run_arguments(case, run_root, settings, execute=True))
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out.count("\n") == 1
    document = json.loads(captured.out)
    assert document["setup_stage"] == "run root creation"
    assert document["setup_error"] == "OSError"
    assert document["receipt_persisted"] is False
    assert "Traceback" not in captured.err
    assert settings.read_bytes() == SETTINGS_BYTES
    assert not run_root.exists()


def test_prelaunch_backup_write_failure_is_a_controlled_refusal(
    case, capsys, monkeypatch, tmp_path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")

    def failing_write(path: Path, payload: bytes) -> None:
        raise OSError("synthetic disk full")

    monkeypatch.setattr(runner, "_write_new", failing_write)
    monkeypatch.setattr(
        runner,
        "_launch_and_capture",
        lambda *arguments, **keywords: pytest.fail("pre-launch failure must not launch"),
    )
    run_root = tmp_path / "run-root"
    code = runner.main(_run_arguments(case, run_root, settings, execute=True))
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out.count("\n") == 1
    document = json.loads(captured.out)
    assert document["setup_stage"] == "plan receipt write"
    assert document["setup_error"] == "OSError"
    assert document["receipt_persisted"] is False
    assert "synthetic disk full" not in captured.out
    assert "Traceback" not in captured.err
    assert settings.read_bytes() == SETTINGS_BYTES
    assert list((run_root / "private").iterdir()) == []
    assert list((run_root / "capture").iterdir()) == []


@pytest.mark.parametrize(
    ("failure_target", "expected_stage"),
    [
        ("private/settings.original.bin", "original settings backup"),
        ("private/settings.patched.bin", "patched settings backup"),
    ],
)
def test_prelaunch_private_settings_backup_write_failure_is_a_controlled_refusal(
    case, capsys, monkeypatch, tmp_path, failure_target: str, expected_stage: str
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    run_root = tmp_path / "run-root"
    blocked = run_root / failure_target
    original_write = runner._write_new

    def failing_write(path: Path, payload: bytes) -> None:
        if path == blocked or str(path) == str(blocked) or _posix(path).endswith(failure_target):
            raise OSError("synthetic disk full")
        original_write(path, payload)

    monkeypatch.setattr(runner, "_write_new", failing_write)
    monkeypatch.setattr(
        runner,
        "_launch_and_capture",
        lambda *arguments, **keywords: pytest.fail("pre-launch failure must not launch"),
    )
    code = runner.main(_run_arguments(case, run_root, settings, execute=True))
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out.count("\n") == 1
    document = json.loads(captured.out)
    assert document["setup_stage"] == expected_stage
    assert document["setup_error"] == "OSError"
    assert document["receipt_persisted"] is False
    assert document["exit_code"] == 2
    assert "synthetic disk full" not in captured.out
    assert "Traceback" not in captured.err
    assert settings.read_bytes() == SETTINGS_BYTES
    assert (run_root / "plan.json").exists()
    assert not blocked.exists()
    assert not (run_root / "run.json").exists()
    assert list((run_root / "capture").iterdir()) == []
    if failure_target == "private/settings.original.bin":
        assert list((run_root / "private").iterdir()) == []
    else:
        assert (run_root / "private" / "settings.original.bin").read_bytes() == SETTINGS_BYTES
        assert not (run_root / "private" / "settings.patched.bin").exists()


def _block_one_json_write(monkeypatch, blocked: Path) -> None:
    """Fail exactly one evidence write, leaving every other write untouched."""
    original_write = runner._write_json_new

    def failing_write(path: Path, document: object) -> None:
        if str(path) == str(blocked):
            raise OSError("synthetic disk full")
        original_write(path, document)

    monkeypatch.setattr(runner, "_write_json_new", failing_write)


def test_config_restore_receipt_write_failure_keeps_restore_status(
    case, capsys, monkeypatch, tmp_path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    calls: list = []
    _install_fake_launch(monkeypatch, calls, _write_success)
    run_root = tmp_path / "run-root"
    blocked = run_root / "config-restore.json"
    _block_one_json_write(monkeypatch, blocked)
    code, document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 3
    assert document["launches"] == 1
    assert document["spawn_state"] == "confirmed"
    assert document["restore"]["status"] == "restored"
    assert document["restore"]["restored_original_bytes"] is True
    assert document["receipt_persisted"] is True
    assert document["evidence_write_failures"] == [
        {"stage": "config-restore.json", "error": "OSError"}
    ]
    assert "synthetic disk full" not in json.dumps(document)
    assert "Traceback" not in err
    assert settings.read_bytes() == SETTINGS_BYTES
    assert not blocked.exists()
    receipt = json.loads((run_root / "run.json").read_bytes())
    assert receipt["restore"]["status"] == "restored"
    assert receipt["evidence_write_failures"] == [
        {"stage": "config-restore.json", "error": "OSError"}
    ]


def test_run_receipt_write_failure_emits_minimal_result(
    case, capsys, monkeypatch, tmp_path
) -> None:
    settings = _new_settings(tmp_path, "settings.json")
    calls: list = []
    _install_fake_launch(monkeypatch, calls, _write_success)
    run_root = tmp_path / "run-root"
    blocked = run_root / "run.json"
    _block_one_json_write(monkeypatch, blocked)
    code, document, err = _main(_run_arguments(case, run_root, settings, execute=True), capsys)
    assert code == 3
    assert document["receipt_persisted"] is False
    assert document["run_receipt"] is None
    assert document["evidence_write_failures"] == [{"stage": "run.json", "error": "OSError"}]
    assert document["launches"] == 1
    assert document["spawn_state"] == "confirmed"
    assert document["coding"]["outcome"] == "provider_completed"
    assert document["restore"]["status"] == "restored"
    assert "synthetic disk full" not in json.dumps(document)
    assert "Traceback" not in err
    assert settings.read_bytes() == SETTINGS_BYTES
    assert not blocked.exists()
    assert (run_root / "config-patch.json").exists()
    assert (run_root / "config-restore.json").exists()
