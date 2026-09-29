"""Offline session format and credential namespace tests; no real host key access."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from local_agent_bridge.capture import keys, session
from local_agent_bridge.capture.retention import StorageError
from local_agent_bridge.capture.session import SessionError, SessionStore

KEY = bytes(range(32))
TOKEN = b"synthetic-private-token-Do-Not-Store-In-Plaintext"


def _sealed(store: SessionStore, payload: bytes = TOKEN):
    writer = store.start()
    assert writer.append("task", payload)
    assert writer.append("request", b"fixed local request")
    assert writer.append("stdout", b'{"event":"result","result":{"status":"SUCCESS"}}\n')
    assert writer.append("stderr", b"diagnostic bytes")
    writer.seal({"process_exit_code": 0})
    return writer


def test_sealed_roundtrip_and_no_plaintext_disk(tmp_path: Path) -> None:
    store = SessionStore(KEY, root=tmp_path / "sessions")
    writer = _sealed(store)
    reader = store.reader(writer.session_id)
    assert reader.read_stream("task") == TOKEN
    assert reader.read_stream("request") == b"fixed local request"
    assert reader.read_stream("stdout").endswith(b'"status":"SUCCESS"}}\n')
    manifest = reader.manifest()
    assert manifest["streams"]["task"]["bytes"] == len(TOKEN)
    assert manifest["streams"]["task"]["complete"] is True
    for path in (tmp_path / "sessions").rglob("*"):
        if path.is_file():
            assert TOKEN not in path.read_bytes()
    assert {path.name for path in writer.path.iterdir()} == {
        "open.json",
        "task.enc",
        "request.enc",
        "stdout.enc",
        "stderr.enc",
        "seal.json",
    }


def test_wrong_key_and_cross_session_copy_fail(tmp_path: Path) -> None:
    store = SessionStore(KEY, root=tmp_path / "sessions")
    first = _sealed(store, b"first")
    second = _sealed(store, b"second")
    with pytest.raises(SessionError, match="authentication"):
        SessionStore(bytes(reversed(KEY)), root=store.domain.root).reader(
            first.session_id
        ).manifest()
    (second.path / "task.enc").write_bytes((first.path / "task.enc").read_bytes())
    with pytest.raises(SessionError, match="length or hash"):
        store.reader(second.session_id).read_stream("task")
    assert store.reader(first.session_id).read_stream("task") == b"first"
    with pytest.raises(StorageError, match="canonical"):
        store.reader(first.session_id.upper())


def test_frame_and_seal_aad_bind_expected_domain(tmp_path: Path) -> None:
    store = SessionStore(KEY, root=tmp_path / "sessions")
    writer = store.start()
    assert writer.append("task", b"domain-bound")
    raw = (writer.path / "task.partial").read_bytes()
    offset = len(session.MAGIC)
    length, sequence, nonce = session.FRAME_HEADER.unpack(
        raw[offset : offset + session.FRAME_HEADER.size]
    )
    encrypted = raw[offset + session.FRAME_HEADER.size :][:length]
    with pytest.raises(InvalidTag):
        AESGCM(KEY).decrypt(
            nonce, encrypted, session._aad("shadow", writer.session_id, "task", sequence)
        )
    writer.seal({})
    envelope = json.loads((writer.path / "seal.json").read_bytes())
    nonce = base64.b64decode(envelope["nonce"])
    tag = base64.b64decode(envelope["tag"])
    with pytest.raises(InvalidTag):
        AESGCM(KEY).decrypt(nonce, tag, session._seal_aad("shadow", envelope["manifest"]))


def test_partial_frame_aad_sequence_and_truncation(tmp_path: Path) -> None:
    store = SessionStore(KEY, root=tmp_path / "sessions")
    writer = store.start()
    assert writer.append("stdout", b"alpha")
    assert writer.append("stdout", b"bravo")
    path = writer.path / "stdout.partial"
    original = path.read_bytes()
    assert b"".join(writer.iter_stream("stdout")) == b"alphabravo"

    # Remove an entire frame; authenticated data alone cannot show this, but
    # the tracked count and digest do.
    path.write_bytes(original[: -(24 + 5 + 16)])
    with pytest.raises(SessionError, match="frame count"):
        b"".join(writer.iter_stream("stdout"))
    path.write_bytes(original[:-1])
    with pytest.raises(SessionError, match="truncated"):
        b"".join(writer.iter_stream("stdout"))
    path.write_bytes(original)
    second = store.start()
    assert second.append("stdout", b"alpha")
    (second.path / "stdout.partial").write_bytes(original)
    with pytest.raises(SessionError, match="authentication"):
        b"".join(second.iter_stream("stdout"))


def test_seal_rejects_unknown_file_and_changed_manifest(tmp_path: Path) -> None:
    store = SessionStore(KEY, root=tmp_path / "sessions")
    writer = _sealed(store)
    (writer.path / "unexpected.txt").write_bytes(b"x")
    with pytest.raises(SessionError, match="unexpected"):
        store.reader(writer.session_id).manifest()
    (writer.path / "unexpected.txt").unlink()
    seal = writer.path / "seal.json"
    envelope = json.loads(seal.read_bytes())
    envelope["manifest"]["streams"]["task"]["bytes"] = 0
    seal.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(SessionError, match="authentication"):
        store.reader(writer.session_id).manifest()


def test_authenticated_incomplete_stream_marker_is_refused(tmp_path: Path) -> None:
    store = SessionStore(KEY, root=tmp_path / "sessions")
    writer = _sealed(store)
    seal = writer.path / "seal.json"
    envelope = json.loads(seal.read_bytes())
    envelope["manifest"]["streams"]["stdout"]["complete"] = False
    nonce = base64.b64decode(envelope["nonce"])
    tag = AESGCM(KEY).encrypt(nonce, b"", session._seal_aad("sessions", envelope["manifest"]))
    envelope["tag"] = base64.b64encode(tag).decode("ascii")
    seal.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(SessionError, match="stream is incomplete"):
        store.reader(writer.session_id).manifest()


def test_interrupted_seal_keeps_counted_unsealed_residue(tmp_path: Path, monkeypatch) -> None:
    from local_agent_bridge.capture import session

    store = SessionStore(KEY, root=tmp_path / "sessions")
    writer = store.start()
    assert writer.append("stdout", b"synthetic output")
    replace = session.os.replace

    def fail_seal(source, destination):
        if Path(destination).name == "seal.json":
            raise OSError("synthetic seal interruption")
        return replace(source, destination)

    monkeypatch.setattr(session.os, "replace", fail_seal)
    with pytest.raises(OSError, match="interruption"):
        writer.seal({})
    assert not (writer.path / "seal.json").exists()
    assert (writer.path / "seal.tmp").exists()
    assert store.domain.status()["active_or_partial"] == 1


def test_dedicated_key_namespace_and_explicit_initialization(monkeypatch) -> None:
    calls: list[tuple] = []

    class FakeWindowsBackend:
        def __init__(self) -> None:
            self.value: str | None = None

        def get_password(self, service: str, account: str) -> str | None:
            calls.append(("get", service, account))
            return self.value

        def set_password(self, service: str, account: str, value: str) -> None:
            calls.append(("set", service, account))
            self.value = value

    FakeWindowsBackend.__module__ = "keyring.backends.windows"
    backend = FakeWindowsBackend()
    monkeypatch.setattr(keys.platform, "system", lambda: "Windows")
    monkeypatch.setattr(keys.keyring, "get_keyring", lambda: backend)
    with pytest.raises(keys.SessionKeyError, match="missing"):
        keys.load_key()
    assert calls == [("get", keys.SERVICE_NAME, keys.KEY_ACCOUNT)]
    assert keys.initialize_key() is True
    assert len(keys.load_key()) == 32
    assert keys.initialize_key() is False
    assert all(call[1] == keys.SERVICE_NAME for call in calls)
    assert "AskAIMCP" not in keys.SERVICE_NAME
