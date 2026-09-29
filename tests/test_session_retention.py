"""File-length quota, partial protection and concurrent encrypted writers."""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from local_agent_bridge.capture.retention import StorageError
from local_agent_bridge.capture.session import SessionError, SessionStore

KEY = bytes(range(32))


def _worker(root: str, payload: bytes) -> str:
    store = SessionStore(
        KEY, root=Path(root), limit=32_000, terminal_reserve=512, receipt_reserve=512
    )
    writer = store.start()
    assert writer.append("task", payload)
    writer.seal({"process_exit_code": 0})
    return writer.session_id


def test_parallel_storage_writers_use_one_domain_budget(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    with ProcessPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(_worker, [str(root)] * 3, [b"a" * 512] * 3))
    store = SessionStore(KEY, root=root, limit=32_000, terminal_reserve=512, receipt_reserve=512)
    assert len(set(ids)) == 3
    assert all(store.reader(uid).read_stream("task") == b"a" * 512 for uid in ids)
    assert store.domain.used_bytes() <= 32_000


def test_whole_bundle_roll_oldest_and_reference_protection(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = SessionStore(KEY, root=root, limit=20_000, terminal_reserve=512, receipt_reserve=512)
    first = store.start()
    assert first.append("task", b"x" * 400)
    first.seal({})
    second = store.start()
    assert second.append("task", b"y" * 400)
    second.seal({})
    tight_limit = store.domain.used_bytes() + 500
    rolling = SessionStore(
        KEY, root=root, limit=tight_limit, terminal_reserve=512, receipt_reserve=512
    )
    third = rolling.start()
    assert not first.path.exists()
    assert second.path.exists()
    assert third.path.exists()
    assert list((root / "receipts").glob("roll-*.json"))
    third.seal({})
    # Starting a new writer must preserve an explicit shadow reference.
    rolling.domain.add_reference(second.session_id, "00000000-0000-0000-0000-000000000001")
    fourth = rolling.start()
    assert fourth.path.exists()
    assert second.path.exists()
    assert rolling.domain.used_bytes() <= tight_limit


def test_referenced_bundle_survives_protected_quota_exhaustion(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = SessionStore(KEY, root=root, limit=20_000, terminal_reserve=512, receipt_reserve=512)
    first = store.start()
    assert first.append("task", b"x" * 400)
    first.seal({})
    store.domain.add_reference(first.session_id, "00000000-0000-0000-0000-000000000001")
    tight = SessionStore(
        KEY,
        root=root,
        limit=store.domain.used_bytes() + 100,
        terminal_reserve=512,
        receipt_reserve=512,
    )
    with pytest.raises(StorageError, match="over_limit"):
        tight.start()
    assert first.path.exists()
    assert store.reader(first.session_id).read_stream("task") == b"x" * 400


def test_partial_and_unknown_bytes_are_counted_and_never_rolled(tmp_path: Path) -> None:
    store = SessionStore(
        KEY, root=tmp_path / "sessions", limit=1600, terminal_reserve=256, receipt_reserve=128
    )
    writer = store.start()
    partial = writer.path / "task.partial"
    assert partial.exists()
    (store.domain.root / "unknown.bin").write_bytes(b"q" * 900)
    with pytest.raises(StorageError, match="over_limit"):
        store.start()
    assert partial.exists()
    assert (store.domain.root / "unknown.bin").exists()


def test_stream_over_limit_is_incomplete_and_next_start_refused(tmp_path: Path) -> None:
    store = SessionStore(
        KEY, root=tmp_path / "sessions", limit=1000, terminal_reserve=256, receipt_reserve=128
    )
    writer = store.start()
    assert writer.append("task", b"a" * 100)
    assert writer.append("stdout", b"b" * 700) is False
    assert writer.incomplete_reason == "over_limit"
    with pytest.raises(SessionError, match="incomplete"):
        writer.seal({})
    with pytest.raises(StorageError, match="over_limit"):
        store.start()
    assert (writer.path / "stdout.partial").exists()
    assert store.domain.used_bytes() <= 1000


def test_file_length_quota_accepts_exact_boundary(tmp_path: Path) -> None:
    limit = 2000
    terminal_reserve = 256
    receipt_reserve = 128
    store = SessionStore(
        KEY,
        root=tmp_path / "sessions",
        limit=limit,
        terminal_reserve=terminal_reserve,
        receipt_reserve=receipt_reserve,
    )
    writer = store.start()
    frame_overhead = 24 + 16
    available = limit - terminal_reserve - receipt_reserve - store.domain.used_bytes()
    assert writer.append("stdout", b"x" * (available - frame_overhead))
    assert store.domain.used_bytes() == limit - terminal_reserve - receipt_reserve
    assert writer.append("stdout", b"y") is False
    assert writer.incomplete_reason == "over_limit"


def test_disk_write_exception_leaves_counted_partial(tmp_path: Path, monkeypatch) -> None:
    store = SessionStore(
        KEY, root=tmp_path / "sessions", limit=2000, terminal_reserve=256, receipt_reserve=128
    )
    writer = store.start()
    monkeypatch.setattr(
        store.domain,
        "reserve",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic disk failure")),
    )
    assert writer.append("stdout", b"some pipe bytes") is False
    assert writer.incomplete_reason == "storage_write_failed"
    assert (writer.path / "open.json").exists()
    assert not (writer.path / "seal.json").exists()
    # The read-only status path reports it as partial; recovery does not erase it.
    assert store.domain.status()["active_or_partial"] == 1


def test_quota_lock_must_be_a_regular_file(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    (root / ".quota.lock").mkdir()
    store = SessionStore(KEY, root=root)
    with pytest.raises(StorageError, match="non-regular"):
        store.start()
    assert (root / ".quota.lock").is_dir()


def test_reference_marker_must_match_before_release(tmp_path: Path) -> None:
    store = SessionStore(KEY, root=tmp_path / "sessions")
    writer = store.start()
    writer.seal({})
    ref_id = "00000000-0000-0000-0000-000000000001"
    store.domain.add_reference(writer.session_id, ref_id)
    marker = store.domain.root / "refs" / writer.session_id / f"{ref_id}.ref"
    marker.write_bytes(b"changed")
    with pytest.raises(StorageError, match="differs"):
        store.domain.remove_reference(writer.session_id, ref_id)
    assert marker.exists()
    marker.write_bytes((ref_id + "\n").encode("ascii"))
    store.domain.remove_reference(writer.session_id, ref_id)
    assert not marker.exists()


def test_no_space_for_rolling_receipt_is_over_limit_without_deletion(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = SessionStore(KEY, root=root, limit=20_000, terminal_reserve=512, receipt_reserve=512)
    writer = store.start()
    assert writer.append("task", b"x" * 2000)
    writer.seal({})
    # Simulate an external limit reduction: even a roll intent cannot fit.
    tight = SessionStore(
        KEY,
        root=root,
        limit=store.domain.used_bytes() + 1,
        terminal_reserve=512,
        receipt_reserve=512,
    )
    with pytest.raises(StorageError, match="over_limit: no room for rolling receipt"):
        tight.start()
    assert writer.path.exists()
    assert tight.reader(writer.session_id).read_stream("task") == b"x" * 2000


def test_unsupported_old_format_is_not_rolled_or_migrated(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = SessionStore(KEY, root=root, limit=20_000, terminal_reserve=512, receipt_reserve=512)
    writer = store.start()
    assert writer.append("task", b"old-format-sample" * 100)
    writer.seal({})
    seal = writer.path / "seal.json"
    envelope = json.loads(seal.read_bytes())
    envelope["schema_version"] = 1
    seal.write_text(json.dumps(envelope), encoding="utf-8")
    original = seal.read_bytes()
    tight = SessionStore(
        KEY,
        root=root,
        limit=store.domain.used_bytes() + 500,
        terminal_reserve=512,
        receipt_reserve=512,
    )
    with pytest.raises(StorageError, match="over_limit"):
        tight.start()
    assert seal.read_bytes() == original
    assert writer.path.exists()
