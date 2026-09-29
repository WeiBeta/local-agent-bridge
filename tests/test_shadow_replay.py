"""Offline shadow snapshots use synthetic keys and never start a CLI or model."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from local_agent_bridge import cli
from local_agent_bridge.bridge import slice_run
from local_agent_bridge.capture.retention import StorageError
from local_agent_bridge.capture.session import SessionError, SessionStore
from local_agent_bridge.shadow import replay as shadow

KEY = bytes(range(32))
TASK = b"synthetic offline task"
REQUEST = b"synthetic fixed request"


def _sealed(
    store: SessionStore,
    *,
    status: str = "SUCCESS",
    usage: dict | None = None,
    scopes: bool = True,
    task: bytes = TASK,
):
    writer = store.start()
    assert writer.append("task", task)
    assert writer.append("request", REQUEST)
    result: dict[str, object] = {"status": status}
    if usage is not None:
        result["usage"] = usage
    if scopes:
        result["tool_calls"] = [{"name": "read_file"}]
        result["files"] = [{"path": "C:/synthetic/input.txt"}]
    event = json.dumps({"event": "result", "result": result}).encode() + b"\n"
    assert writer.append("stdout", event[:25])
    assert writer.append("stdout", event[25:])
    assert writer.append("stderr", b"synthetic diagnostic")
    writer.seal({"process_exit_code": 0})
    return writer


def _digest(store: SessionStore, uid: str) -> str:
    return shadow.fingerprint(store, uid)["input_sha256"]


def test_self_comparison_and_different_terminal_are_content_free(tmp_path: Path) -> None:
    store = SessionStore(KEY, root=tmp_path / "sessions")
    first = _sealed(store, usage={"input_tokens": 3, "output_tokens": 4})
    second = _sealed(store, status="ERROR", usage={"input_tokens": 3, "output_tokens": 5})
    digest = _digest(store, first.session_id)
    first_report = shadow.replay(store, first.session_id, digest)
    second_report = shadow.replay(store, second.session_id, digest)
    self_compare = shadow.compare(first_report, first_report)
    assert all(item["state"] == "equal" for item in self_compare["fields"].values())
    comparison = shadow.compare(first_report, second_report)
    assert comparison["fields"]["terminal"]["state"] == "different"
    assert comparison["fields"]["usage"]["state"] == "different"
    assert comparison["fields"]["tool_scope"]["state"] == "equal"
    assert comparison["fields"]["file_scope"]["state"] == "equal"
    assert first_report["terminal"]["label"] == "SUCCESS"
    assert "synthetic offline task" not in json.dumps(first_report)
    assert "C:/synthetic/input.txt" not in json.dumps(first_report)


def test_missing_fields_and_different_inputs_are_incomparable(tmp_path: Path) -> None:
    store = SessionStore(KEY, root=tmp_path / "sessions")
    first = _sealed(store, scopes=False)
    second = _sealed(store, scopes=False)
    digest = _digest(store, first.session_id)
    result = shadow.compare(
        shadow.replay(store, first.session_id, digest),
        shadow.replay(store, second.session_id, digest),
    )
    for name in ("tool_scope", "file_scope", "usage"):
        assert result["fields"][name] == {
            "state": "incomparable",
            "reason": "missing_observation",
        }
    different = _sealed(store, task=b"different task")
    other_digest = _digest(store, different.session_id)
    mismatch = shadow.compare(
        shadow.replay(store, first.session_id, digest),
        shadow.replay(store, different.session_id, other_digest),
    )
    assert mismatch["input"]["state"] == "different"
    assert all(item["reason"] == "input_differs" for item in mismatch["fields"].values())


def test_usage_comparison_keeps_missing_fields_explicit(tmp_path: Path) -> None:
    store = SessionStore(KEY, root=tmp_path / "sessions")
    first = _sealed(store, usage={"input_tokens": 3})
    second = _sealed(store, usage={"input_tokens": 3, "output_tokens": 5})
    digest = _digest(store, first.session_id)
    comparison = shadow.compare(
        shadow.replay(store, first.session_id, digest),
        shadow.replay(store, second.session_id, digest),
    )
    usage = comparison["fields"]["usage"]
    assert usage["state"] == "incomparable"
    assert usage["fields"] == {"input_tokens": "equal", "output_tokens": "incomparable"}


def test_wrong_digest_cross_domain_old_format_and_partial_refused(tmp_path: Path) -> None:
    sessions = SessionStore(KEY, root=tmp_path / "sessions")
    shadow_store = SessionStore(KEY, domain_name="shadow", root=tmp_path / "shadow")
    writer = _sealed(sessions)
    digest = _digest(sessions, writer.session_id)
    with pytest.raises(shadow.ShadowError, match="input digest differs"):
        shadow.replay(sessions, writer.session_id, "0" * 64)
    with pytest.raises(shadow.ShadowError, match="input digest differs"):
        shadow.snapshot(sessions, shadow_store, writer.session_id, "0" * 64)
    assert not shadow_store.domain.root.exists()
    shadow_store.domain.root.mkdir(exist_ok=True)
    shutil.copytree(writer.path, shadow_store.domain.root / writer.session_id)
    with pytest.raises(SessionError, match="identity mismatch"):
        shadow_store.reader(writer.session_id).manifest()
    with pytest.raises(SessionError, match="identity mismatch"):
        shadow.replay(shadow_store, writer.session_id, digest)
    seal = writer.path / "seal.json"
    envelope = json.loads(seal.read_bytes())
    envelope["schema_version"] = 1
    seal.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(SessionError, match="unsupported session format version"):
        sessions.reader(writer.session_id).manifest()
    partial = sessions.start()
    with pytest.raises(SessionError, match="seal"):
        shadow.replay(sessions, partial.session_id, digest)


def test_snapshot_tamper_truncation_and_incomplete_refused(tmp_path: Path) -> None:
    sessions = SessionStore(KEY, root=tmp_path / "sessions")
    shadows = SessionStore(KEY, domain_name="shadow", root=tmp_path / "shadow")
    source = _sealed(sessions)
    digest = _digest(sessions, source.session_id)
    uid = shadow.snapshot(sessions, shadows, source.session_id, digest)
    assert shadow.replay(shadows, uid, digest)["source"]["uid"] == source.session_id
    stream = shadows.domain.root / uid / "stdout.enc"
    original = stream.read_bytes()
    stream.write_bytes(original[:-1])
    with pytest.raises(SessionError, match="length or hash"):
        shadow.replay(shadows, uid, digest)
    stream.write_bytes(original[:-15] + bytes([original[-15] ^ 1]) + original[-14:])
    with pytest.raises(SessionError, match="hash"):
        shadow.replay(shadows, uid, digest)
    stream.write_bytes(original)
    partial = shadows.start()
    with pytest.raises(SessionError, match="seal"):
        shadow.replay(shadows, partial.session_id, digest)
    assert shadows.domain.status()["active_or_partial"] == 1


def test_shadow_over_limit_leaves_counted_partial_without_seal(tmp_path: Path) -> None:
    sessions = SessionStore(KEY, root=tmp_path / "sessions")
    shadows = SessionStore(
        KEY,
        domain_name="shadow",
        root=tmp_path / "shadow",
        limit=600,
        terminal_reserve=256,
        receipt_reserve=128,
    )
    source = _sealed(sessions)
    digest = _digest(sessions, source.session_id)
    with pytest.raises(shadow.ShadowError, match="over_limit"):
        shadow.snapshot(sessions, shadows, source.session_id, digest)
    assert shadows.domain.status()["active_or_partial"] == 1
    assert shadows.domain.used_bytes() <= 600
    assert not list(shadows.domain.root.glob("*/seal.json"))
    assert source.path.exists()


def test_shadow_quota_rolls_whole_snapshots(tmp_path: Path) -> None:
    sessions = SessionStore(KEY, root=tmp_path / "sessions")
    shadows = SessionStore(
        KEY,
        domain_name="shadow",
        root=tmp_path / "shadow",
        limit=20_000,
        terminal_reserve=512,
        receipt_reserve=512,
    )
    sources = [_sealed(sessions, task=f"task-{index}".encode()) for index in range(3)]
    digests = [_digest(sessions, writer.session_id) for writer in sources]
    first = shadow.snapshot(sessions, shadows, sources[0].session_id, digests[0])
    second = shadow.snapshot(sessions, shadows, sources[1].session_id, digests[1])
    tight_shadow = SessionStore(
        KEY,
        domain_name="shadow",
        root=shadows.domain.root,
        limit=shadows.domain.used_bytes() + 500,
        terminal_reserve=512,
        receipt_reserve=512,
    )
    third = shadow.snapshot(sessions, tight_shadow, sources[2].session_id, digests[2])
    assert not (shadows.domain.root / first).exists()
    assert second != third
    assert tight_shadow.domain.used_bytes() <= tight_shadow.domain.limit
    assert shadow.replay(tight_shadow, third, digests[2])["source"]["uid"] == sources[2].session_id


def test_self_contained_snapshot_replays_after_source_session_rolls(tmp_path: Path) -> None:
    sessions = SessionStore(KEY, root=tmp_path / "sessions")
    shadows = SessionStore(KEY, domain_name="shadow", root=tmp_path / "shadow")
    source = _sealed(sessions)
    digest = _digest(sessions, source.session_id)
    snapshot_uid = shadow.snapshot(sessions, shadows, source.session_id, digest)

    tight_sessions = SessionStore(
        KEY,
        root=sessions.domain.root,
        limit=sessions.domain.used_bytes() + 500,
        terminal_reserve=512,
        receipt_reserve=512,
    )
    tight_sessions.start()
    assert not source.path.exists()
    result = shadow.replay(shadows, snapshot_uid, digest)
    assert result["source"]["uid"] == source.session_id
    assert result["terminal"]["label"] == "SUCCESS"


def test_shadow_cli_uses_only_injected_key_and_never_launches(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(shadow, "load_key", lambda: KEY)
    monkeypatch.setattr(
        slice_run, "command_run", lambda *_args: (_ for _ in ()).throw(AssertionError("CLI launch"))
    )
    sessions = SessionStore(KEY)
    source = _sealed(sessions)
    digest = _digest(sessions, source.session_id)
    assert cli.main(["shadow", "fingerprint", "sessions", source.session_id]) == 0
    assert json.loads(capsys.readouterr().out)["input_sha256"] == digest
    assert cli.main(["shadow", "snapshot", source.session_id, digest]) == 0
    snapshot_uid = json.loads(capsys.readouterr().out)["uid"]
    assert cli.main(["shadow", "replay", "shadow", snapshot_uid, digest]) == 0
    assert json.loads(capsys.readouterr().out)["source"]["uid"] == source.session_id
    assert (
        cli.main(
            [
                "shadow",
                "compare",
                "sessions",
                source.session_id,
                digest,
                "shadow",
                snapshot_uid,
                digest,
            ]
        )
        == 0
    )
    compared = json.loads(capsys.readouterr().out)
    assert compared["fields"]["terminal"]["state"] == "equal"
    assert cli.main(["shadow", "replay", "sessions", source.session_id, "0" * 64]) == 2
    assert json.loads(capsys.readouterr().err)["reason"] == "input_or_provenance_mismatch"


def test_h1_invalid_uid_and_missing_bundle_are_input_or_bundle_reasons(
    monkeypatch, tmp_path, capsys
) -> None:
    """A caller input error or an absent bundle is not a storage failure."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(shadow, "load_key", lambda: KEY)
    sessions = SessionStore(KEY)
    source = _sealed(sessions)
    digest = _digest(sessions, source.session_id)
    absent = "0f0f0f0f-0f0f-4f0f-8f0f-0f0f0f0f0f0f"

    # A well-formed but non-canonical identifier is a caller input error.
    assert cli.main(["shadow", "replay", "sessions", "ABC", digest]) == 2
    assert json.loads(capsys.readouterr().err)["reason"] == "input_or_provenance_mismatch"
    # A canonical identifier that addresses no bundle is not a storage fault.
    assert cli.main(["shadow", "replay", "sessions", absent, digest]) == 2
    assert json.loads(capsys.readouterr().err)["reason"] == "invalid_or_incomplete_bundle"
    assert cli.main(["shadow", "fingerprint", "shadow", absent]) == 2
    assert json.loads(capsys.readouterr().err)["reason"] == "invalid_or_incomplete_bundle"


def test_h1_real_storage_failures_stay_storage_unavailable(monkeypatch, tmp_path, capsys) -> None:
    """A genuine read or lock failure still reports storage, without content."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(shadow, "load_key", lambda: KEY)
    sessions = SessionStore(KEY)
    source = _sealed(sessions)
    digest = _digest(sessions, source.session_id)

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(shadow.SessionStore, "reader", denied)
    assert cli.main(["shadow", "replay", "sessions", source.session_id, digest]) == 2
    reported = json.loads(capsys.readouterr().err)
    assert reported == {"state": "refused", "reason": "storage_unavailable"}
    assert str(tmp_path) not in json.dumps(reported)

    def locked(*_args, **_kwargs):
        raise StorageError("session quota lock unavailable")

    monkeypatch.setattr(shadow.SessionStore, "reader", locked)
    assert cli.main(["shadow", "fingerprint", "sessions", source.session_id]) == 2
    assert json.loads(capsys.readouterr().err)["reason"] == "storage_unavailable"


def test_h1_reason_mapping_keeps_the_other_categories() -> None:
    """The narrow reclassification does not disturb the existing categories."""
    from local_agent_bridge.capture.keys import SessionKeyError

    assert shadow._refusal_reason(StorageError("over_limit: no room")) == "over_limit"
    assert shadow._refusal_reason(SessionKeyError("session key missing")) == "key_unavailable"
    assert shadow._refusal_reason(SessionError("unsupported session format version")) == (
        "invalid_or_incomplete_bundle"
    )
    assert shadow._refusal_reason(shadow.ShadowError("input digest differs")) == (
        "input_or_provenance_mismatch"
    )
    assert shadow._refusal_reason(OSError("storage_write_failed")) == "storage_unavailable"
    assert shadow._refusal_reason(FileNotFoundError(2, "No such file")) == (
        "invalid_or_incomplete_bundle"
    )
    assert shadow._refusal_reason(ValueError("unexpected value")) == "storage_unavailable"
