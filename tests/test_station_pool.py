"""Real Windows mutexes, synthetic owners only; no host/model/config/key IO."""

from __future__ import annotations

import copy
import json
import multiprocessing
import os
import uuid
from pathlib import Path

import pytest

from local_agent_bridge.bridge import station_pool as pool
from local_agent_bridge.bridge import task_input


def registry(tmp_path, count=4, receipt=None):
    control = tmp_path / "station-control"
    records = tmp_path / "native-records"
    control.mkdir()
    records.mkdir()
    entries = []
    for index in range(count):
        root = tmp_path / ("station-" + str(index))
        root.mkdir()
        native = str(uuid.uuid4())
        record = records / (native + ".json")
        record.write_bytes(
            task_input._canonical_json_bytes(
                {
                    "id": native,
                    "projectResources": {"resources": [{"folderUri": root.as_uri()}]},
                    "permissionGrants": {"mode": "synthetic-only"},
                }
            )
        )
        entries.append(
            {
                "id": str(uuid.uuid4()),
                "native_id": native,
                "root": str(root),
                "record": str(record),
                "root_identity": pool.physical_identity(root),
            }
        )
    document = {
        "contract_version": 1,
        "id": "offline-station-pool",
        "control_root": str(control),
        "deployment_receipt": {} if receipt is None else receipt,
        "policy": {
            "grant_ref": "synthetic-injected-policy-not-real-authority",
            "roles": ["Coding", "Review"],
            "capabilities": {
                "execute": True,
                "web_reference": False,
                "prepare_dependencies": False,
            },
            "max_deadline_seconds": 30,
            "source_output_bytes_limit": 1000000,
        },
        "stations": entries,
    }
    path = tmp_path / "station-registry.json"
    pin = save_registry(path, document)
    return path, pin, document


def save_registry(path, document):
    path.write_bytes(task_input._canonical_json_bytes(document))
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def terminal(lease):
    root = lease.pool.registry["control_root"] / "requests" / lease.request_id
    root.mkdir(parents=True, exist_ok=True)
    target = root / "terminal.json"
    target.write_bytes(b'{"synthetic":true}')
    return target


def owner_process(path, pin, acquired, release, connection, crash=False):
    """A separate OS owner creates its synthetic job only after native admission."""
    configured = pool.load_registry(Path(path), pin)
    manager = pool.Pool(configured)
    lease = None
    try:
        connection.send({"state": "waiting", "pid": os.getpid()})
        lease = manager.acquire(str(uuid.uuid4()), timeout_seconds=20)
        root = lease.station.root / "jobs" / str(uuid.uuid4())
        lease.bind_task(root)
        root.mkdir(parents=True)
        (root / "synthetic-launch-marker").write_text(lease.request_id, encoding="ascii")
        lease.running()
        connection.send(
            {"state": "owned", "station": lease.station.id, "root": str(root), "pid": os.getpid()}
        )
        acquired.set()
        if crash:
            os._exit(7)
        if not release.wait(20):
            raise RuntimeError("synthetic-owner-release-timeout")
        lease.finish(control_complete=True, terminal=terminal(lease))
        connection.send({"state": "released", "station": lease.station.id})
    finally:
        if lease is not None and not lease.closed:
            lease.abandon()
        manager.close()
        connection.close()


def start_owner(context, path, pin, *, crash=False):
    acquired, release = context.Event(), context.Event()
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=owner_process, args=(str(path), pin, acquired, release, sender, crash)
    )
    process.start()
    sender.close()
    assert receiver.poll(12), "child never reached admission"
    assert receiver.recv()["state"] == "waiting"
    return process, acquired, release, receiver


def finish_owners(owners):
    for _process, _acquired, release, _receiver in owners:
        release.set()
    for process, _acquired, _release, receiver in owners:
        process.join(10)
        # Only this test's exact Process handle can be terminated after a bounded failure.
        if process.is_alive():
            process.terminate()
            process.join(5)
            pytest.fail("synthetic owner did not finish; its evidence is retained")
        receiver.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows native mutex contract")
def test_four_process_owners_fifth_waits_before_job_then_reuses_first_release(tmp_path):
    path, pin, document = registry(tmp_path)
    context = multiprocessing.get_context("spawn")
    owners = []
    claims = []
    try:
        for _ in range(4):
            owner = start_owner(context, path, pin)
            owners.append(owner)
            assert owner[1].wait(12), "owner never acquired"
            claims.append(owner[3].recv())
        assert len({claim["station"] for claim in claims}) == 4
        assert len({claim["pid"] for claim in claims}) == 4
        fifth = start_owner(context, path, pin)
        owners.append(fifth)
        assert not fifth[1].wait(0.25), "fifth acquired while four owned"
        jobs = [
            item for entry in document["stations"] for item in Path(entry["root"]).glob("jobs/*")
        ]
        assert {str(item) for item in jobs} == {claim["root"] for claim in claims}
        owners[2][2].set()
        assert owners[2][3].poll(10)
        released = owners[2][3].recv()
        assert released["state"] == "released"
        assert fifth[1].wait(10), "one release did not wake fifth"
        replacement = fifth[3].recv()
        assert replacement["station"] == claims[2]["station"]
        assert replacement["root"] != claims[2]["root"]
        assert Path(claims[2]["root"]).is_dir()
        for index in (0, 1, 3):
            assert owners[index][0].is_alive()
            state = json.loads(
                (
                    Path(document["control_root"]) / "states" / (claims[index]["station"] + ".json")
                ).read_bytes()
            )
            assert state["state"] == "Running" and state["owner"]["pid"] == claims[index]["pid"]
    finally:
        finish_owners(owners)
    assert all(owner[0].exitcode == 0 for owner in owners)


@pytest.mark.skipif(os.name != "nt", reason="Windows native mutex contract")
def test_one_station_two_processes_one_owner_and_cancelled_admission(tmp_path):
    path, pin, document = registry(tmp_path, 1)
    context = multiprocessing.get_context("spawn")
    owners = []
    manager = pool.Pool(pool.load_registry(path, pin))
    cancellation = pool.Cancellation()
    try:
        first = start_owner(context, path, pin)
        owners.append(first)
        assert first[1].wait(12)
        claim = first[3].recv()
        second = start_owner(context, path, pin)
        owners.append(second)
        assert not second[1].wait(0.2)
        cancellation.cancel()
        with pytest.raises(pool.StationError, match="StationAdmissionCancelled"):
            manager.acquire(str(uuid.uuid4()), cancellation=cancellation)
        with pytest.raises(pool.StationError, match="StationCapacityWaitExpired"):
            manager.acquire(str(uuid.uuid4()), timeout_seconds=0.03)
        assert len(list(Path(document["stations"][0]["root"]).glob("jobs/*"))) == 1
        first[2].set()
        assert second[1].wait(10)
        assert second[3].recv()["station"] == claim["station"]
    finally:
        cancellation.close()
        manager.close()
        finish_owners(owners)
    assert all(owner[0].exitcode == 0 for owner in owners)


@pytest.mark.skipif(os.name != "nt", reason="Windows native mutex contract")
@pytest.mark.parametrize("keep_handles", [False, True])
def test_lost_owner_only_disqualifies_its_station(tmp_path, keep_handles):
    path, pin, document = registry(tmp_path, 4)
    configured = pool.load_registry(path, pin)
    manager = pool.Pool(configured) if keep_handles else None
    context = multiprocessing.get_context("spawn")
    owner = start_owner(context, path, pin, crash=True)
    assert owner[1].wait(12)
    lost = owner[3].recv()
    owner[0].join(10)
    assert owner[0].exitcode == 7
    owner[3].close()
    if manager is None:
        manager = pool.Pool(configured)
    try:
        lease = manager.acquire(str(uuid.uuid4()), timeout_seconds=2)
        assert lease.station.id != lost["station"]
        state = json.loads(
            (Path(document["control_root"]) / "states" / (lost["station"] + ".json")).read_bytes()
        )
        assert state["state"] == "Suspended"
        lease.finish(control_complete=True, terminal=terminal(lease))
    finally:
        manager.close()


@pytest.mark.parametrize("damage", ["malformed", "oversize", "missing_root", "wrong_identity"])
def test_damaged_selected_station_does_not_block_healthy_station(tmp_path, damage):
    path, pin, document = registry(tmp_path, 2)
    first = document["stations"][0]
    configured = pool.load_registry(path, pin)
    states = Path(document["control_root"]) / "states"
    states.mkdir()
    bad = states / (first["id"] + ".json")
    if damage in {"malformed", "oversize"}:
        raw = b"invalid recovery evidence" if damage == "malformed" else b"x" * 65537
        bad.write_bytes(raw)
    elif damage == "missing_root":
        Path(first["root"]).rmdir()
    else:
        first["root_identity"]["st_ino"] += 1
        pin = save_registry(path, document)
        configured = pool.load_registry(path, pin)
    manager = pool.Pool(configured)
    try:
        lease = manager.acquire(str(uuid.uuid4()), timeout_seconds=2)
        assert lease.station.id == document["stations"][1]["id"]
        if damage in {"malformed", "oversize"}:
            assert bad.read_bytes() == raw
        lease.finish(control_complete=True, terminal=terminal(lease))
    finally:
        manager.close()


def test_closed_business_failure_reuses_but_unconfirmed_control_suspends(tmp_path):
    path, pin, document = registry(tmp_path, 2)
    manager = pool.Pool(pool.load_registry(path, pin))
    try:
        first = manager.acquire(str(uuid.uuid4()))
        same = first.station.id
        with pytest.raises(pool.StationError, match="StationReentrantAcquire"):
            manager.acquire(str(uuid.uuid4()), timeout_seconds=0)
        with pytest.raises(pool.StationError, match="StationLeaseOutstanding"):
            manager.close()
        first.finish(control_complete=True, terminal=terminal(first))
        red = manager.acquire(str(uuid.uuid4()))
        assert red.station.id == same
        red.finish(control_complete=False, terminal=terminal(red))
        next_job = manager.acquire(str(uuid.uuid4()))
        assert next_job.station.id == document["stations"][1]["id"]
        next_job.finish(control_complete=True, terminal=terminal(next_job))
    finally:
        manager.close()


@pytest.mark.parametrize("mutation", ["physical_alias", "native_duplicate", "capacity", "overlap"])
def test_registry_rejects_unusable_capacity_before_any_handle(tmp_path, mutation):
    path, _pin, document = registry(tmp_path, 2)
    if mutation == "physical_alias":
        document["stations"][1]["root_identity"] = document["stations"][0]["root_identity"]
    elif mutation == "native_duplicate":
        document["stations"][1]["native_id"] = document["stations"][0]["native_id"]
        document["stations"][1]["record"] = document["stations"][0]["record"]
    elif mutation == "capacity":
        document["stations"] *= 3
    else:
        document["stations"][1]["root"] = str(Path(document["stations"][0]["root"]) / "nested")
        Path(document["stations"][1]["root"]).mkdir()
    pin = save_registry(path, document)
    with pytest.raises(pool.StationError):
        pool.load_registry(path, pin)
    assert not (Path(document["control_root"]) / "states").exists()


def test_lock_identity_not_pool_name_or_station_spelling(tmp_path):
    path, pin, _document = registry(tmp_path, 1)
    station = pool.load_registry(path, pin)["stations"][0]
    other = copy.copy(station)
    object.__setattr__(other, "id", str(uuid.uuid4()))
    assert other.lock_name == station.lock_name
