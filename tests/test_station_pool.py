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
from local_agent_bridge.bridge import task_input, task_run


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


@pytest.mark.parametrize("record_index,root_index", [(0, 1), (1, 0)])
def test_registry_rejects_record_inside_any_station_root_without_reading_records(
    tmp_path, monkeypatch, record_index, root_index
):
    path, _pin, document = registry(tmp_path, 2)
    item = document["stations"][record_index]
    nested = Path(document["stations"][root_index]["root"]) / (item["native_id"] + ".json")
    item["record"] = str(nested)
    pin = save_registry(path, document)
    original_open = Path.open

    def opening(target, *args, **kwargs):
        assert target not in [Path(s["record"]) for s in document["stations"]]
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opening)
    with pytest.raises(pool.StationError) as caught:
        pool.load_registry(path, pin)
    assert caught.value.code == "StationRecordRootOverlap"


def test_registry_allows_external_records_under_control_without_reading_them(tmp_path, monkeypatch):
    path, _pin, document = registry(tmp_path, 2)
    item = document["stations"][1]
    item["record"] = str(Path(document["control_root"]) / (item["native_id"] + ".json"))
    pin = save_registry(path, document)
    original_open = Path.open

    def opening(target, *args, **kwargs):
        assert target not in [Path(s["record"]) for s in document["stations"]]
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opening)
    loaded = pool.load_registry(path, pin)
    assert len(loaded["stations"]) == 2


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


def test_review_f02_state_path_rejection_preserves_bytes_and_admits_healthy(tmp_path, monkeypatch):
    path, pin, document = registry(tmp_path, 2)
    manager = pool.Pool(pool.load_registry(path, pin))
    bad = manager._state_path(manager.registry["stations"][0])
    bad.parent.mkdir()
    raw = b"  original rejected state evidence\r\n"
    bad.write_bytes(raw)
    original = task_input._assert_plain_target

    def reject_bad_state(target, *, label):
        if target == bad:
            raise task_input.TaskInputError("PathRejected", "synthetic selected state rejection")
        return original(target, label=label)

    monkeypatch.setattr(task_input, "_assert_plain_target", reject_bad_state)
    lease = None
    try:
        lease = manager.acquire(str(uuid.uuid4()), timeout_seconds=1)
        assert lease.station.id == document["stations"][1]["id"]
        assert bad.read_bytes() == raw
    finally:
        if lease is not None and not lease.closed:
            lease.finish(control_complete=True, terminal=terminal(lease))
        manager.close()


def test_review_f03_acquire_preserves_primary_interrupt_and_releases_once(tmp_path, monkeypatch):
    path, pin, _document = registry(tmp_path, 1)
    primary = KeyboardInterrupt("synthetic original interrupt")

    class Kernel:
        releases = 0

        def mutex(self, name):
            return 1

        def wait(self, handles, milliseconds):
            return 0

        def release(self, handle):
            self.releases += 1
            raise pool.StationError("SyntheticSecondaryReleaseFailed")

        def close(self, handle):
            pass

    kernel = Kernel()
    manager = pool.Pool(pool.load_registry(path, pin), kernel=kernel)

    def interrupted(station):
        raise primary

    monkeypatch.setattr(manager, "_read_state", interrupted)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            manager.acquire(str(uuid.uuid4()))
        assert caught.value is primary
        assert kernel.releases == 1
        assert manager.release_unconfirmed
        assert manager.cleanup_diagnostics == [
            {
                "station_id": manager.registry["stations"][0].id,
                "stage": "release",
                "error_type": "StationError",
            }
        ]
    finally:
        manager.close()
    assert kernel.releases == 1


@pytest.mark.parametrize("damage", ["missing_root", "record_directory", "missing_record"])
def test_station_unavailable_before_registry_load_is_local(tmp_path, damage):
    path, pin, document = registry(tmp_path, 2)
    broken, healthy = document["stations"]
    if damage == "missing_root":
        Path(broken["root"]).rename(tmp_path / "retained-root")
    elif damage == "missing_record":
        record = Path(broken["record"])
        record.rename(record.with_suffix(".json.retained"))
    else:
        record = Path(broken["record"])
        record.rename(record.with_suffix(".json.retained"))
        record.mkdir()
    manager = pool.Pool(pool.load_registry(path, pin))
    lease = None
    try:
        lease = manager.acquire(str(uuid.uuid4()), timeout_seconds=1)
        assert lease.station.id == healthy["id"]
        assert not (Path(broken["root"]) / "jobs").exists()
    finally:
        if lease is not None and not lease.closed:
            lease.finish(control_complete=True, terminal=terminal(lease))
        manager.close()


def test_rejected_reservation_write_preserves_state_and_skips_only_its_station(
    tmp_path, monkeypatch
):
    path, pin, document = registry(tmp_path, 2)
    manager = pool.Pool(pool.load_registry(path, pin))
    broken = manager.registry["stations"][0]
    state_path = manager._state_path(broken)
    state_path.parent.mkdir()
    raw = b'{ "station_id": "' + broken.id.encode() + b'", "state": "Idle" }\r\n'
    state_path.write_bytes(raw)
    original = manager._write_state

    def reject_selected_write(station, value):
        if station.id == broken.id:
            raise task_input.TaskInputError("PathRejected", "synthetic write rejection")
        return original(station, value)

    monkeypatch.setattr(manager, "_write_state", reject_selected_write)
    lease = None
    try:
        lease = manager.acquire(str(uuid.uuid4()), timeout_seconds=1)
        assert lease.station.id == document["stations"][1]["id"]
        assert state_path.read_bytes() == raw
        assert manager.cleanup_diagnostics == [
            {"station_id": broken.id, "stage": "suspend", "error_type": "TaskInputError"}
        ]
    finally:
        if lease is not None and not lease.closed:
            lease.finish(control_complete=True, terminal=terminal(lease))
        manager.close()


def test_bad_global_policy_still_rejects_when_one_station_is_unavailable(tmp_path):
    path, _pin, document = registry(tmp_path, 2)
    Path(document["stations"][0]["root"]).rename(tmp_path / "retained-root")
    document["policy"]["capabilities"]["execute"] = "true"
    pin = save_registry(path, document)
    with pytest.raises(pool.StationError, match="StationPolicyInvalid"):
        pool.load_registry(path, pin)
    assert not (Path(document["control_root"]) / "states").exists()


class ReleaseFailureKernel:
    """Synthetic handles only; no deliberately failed native ReleaseMutex."""

    def __init__(self):
        self.created = []
        self.releases = []
        self.closes = []
        self.waits = 0
        self.fail_release = False

    def mutex(self, name):
        self.created.append(name)
        return len(self.created)

    def wait(self, handles, milliseconds):
        self.waits += 1
        return 0

    def release(self, handle):
        self.releases.append(handle)
        if self.fail_release:
            raise pool.StationError("SyntheticReleaseFailed")

    def close(self, handle):
        self.closes.append(handle)


@pytest.mark.parametrize("ending", ["finish", "abandon"])
@pytest.mark.parametrize("primary_type", [None, KeyboardInterrupt, SystemExit])
def test_lease_release_failure_is_attempted_once_and_preserves_primary(
    tmp_path, monkeypatch, ending, primary_type
):
    path, pin, _document = registry(tmp_path, 1)
    kernel = ReleaseFailureKernel()
    manager = pool.Pool(pool.load_registry(path, pin), kernel=kernel)
    lease = manager.acquire(str(uuid.uuid4()))
    owned_terminal = terminal(lease)
    original = manager._write_state
    primary = primary_type("synthetic primary") if primary_type is not None else None

    def interrupted_write(station, value):
        if primary is not None and value.get("reason") != "ReleaseUnconfirmed":
            raise primary
        return original(station, value)

    monkeypatch.setattr(manager, "_write_state", interrupted_write)
    kernel.fail_release = True
    try:
        expected = primary_type if primary is not None else pool.StationError
        with pytest.raises(expected) as caught:
            if ending == "finish":
                lease.finish(control_complete=True, terminal=owned_terminal)
            else:
                lease.abandon()
        if primary is not None:
            assert caught.value is primary
        else:
            assert caught.value.code == "SyntheticReleaseFailed"
        assert lease.closed and lease.released is False
        assert kernel.releases == [lease.handle]
        assert manager._read_state(lease.station)["reason"] == "ReleaseUnconfirmed"
        assert manager.cleanup_diagnostics == [
            {"station_id": lease.station.id, "stage": "release", "error_type": "StationError"}
        ]
        with pytest.raises(pool.StationError, match="StationReleaseUnconfirmed"):
            manager.acquire(str(uuid.uuid4()))
        assert kernel.waits == 1
        lease.abandon()
    finally:
        manager.close()
    assert kernel.releases == [lease.handle]


def test_suspended_candidate_release_failure_stops_without_trying_healthy_slot(tmp_path):
    path, pin, _document = registry(tmp_path, 2)
    kernel = ReleaseFailureKernel()
    manager = pool.Pool(pool.load_registry(path, pin), kernel=kernel)
    broken = manager.registry["stations"][0]
    manager._write_state(broken, {"station_id": broken.id, "state": "Suspended"})
    kernel.fail_release = True
    try:
        with pytest.raises(pool.StationError, match="SyntheticReleaseFailed"):
            manager.acquire(str(uuid.uuid4()))
        assert kernel.waits == 1 and kernel.releases == [manager.handles[broken.id]]
        assert manager.release_unconfirmed == {broken.id}
    finally:
        manager.close()


def test_pool_close_preserves_first_interrupt_and_does_not_repeat_handles(tmp_path):
    path, pin, _document = registry(tmp_path, 2)
    kernel = ReleaseFailureKernel()
    primary = KeyboardInterrupt("synthetic first close")

    def broken_close(handle):
        kernel.closes.append(handle)
        if len(kernel.closes) == 1:
            raise primary
        raise OSError("synthetic secondary close")

    kernel.close = broken_close
    manager = pool.Pool(pool.load_registry(path, pin), kernel=kernel)
    with pytest.raises(KeyboardInterrupt) as caught:
        manager.close()
    assert caught.value is primary
    assert kernel.closes == [1, 2]
    assert [item["error_type"] for item in manager.cleanup_diagnostics] == [
        "KeyboardInterrupt",
        "OSError",
    ]
    manager.close()
    assert kernel.closes == [1, 2]


def test_pool_creation_interrupt_survives_close_failure(tmp_path):
    path, pin, _document = registry(tmp_path, 2)
    kernel = ReleaseFailureKernel()
    primary = SystemExit("synthetic second mutex")
    original = kernel.mutex

    def interrupted_mutex(name):
        if kernel.created:
            raise primary
        return original(name)

    def broken_close(handle):
        kernel.closes.append(handle)
        raise OSError("synthetic secondary close")

    kernel.mutex = interrupted_mutex
    kernel.close = broken_close
    with pytest.raises(SystemExit) as caught:
        pool.Pool(pool.load_registry(path, pin), kernel=kernel)
    assert caught.value is primary and kernel.closes == [1]


@pytest.mark.parametrize("code", ["IoFailed", "InputChanged"])
def test_selected_native_reader_rejection_is_local_and_retains_record(tmp_path, monkeypatch, code):
    path, pin, document = registry(tmp_path, 2)
    manager = pool.Pool(pool.load_registry(path, pin))
    broken, healthy = document["stations"]
    record = Path(broken["record"])
    raw = record.read_bytes()
    original = task_run.read_host_input_bytes
    observed = []

    def reject_selected_record(*, path):
        observed.append(Path(path))
        if Path(path) == record:
            assert not (Path(broken["root"]) / "jobs").exists()
            raise task_run.TaskRunError(code)
        return original(path=path)

    monkeypatch.setattr(task_run, "read_host_input_bytes", reject_selected_record)
    lease = None
    try:
        lease = manager.acquire(str(uuid.uuid4()), timeout_seconds=1)
        assert lease.station.id == healthy["id"]
        assert observed == [record, Path(healthy["record"])]
        assert record.read_bytes() == raw
        assert manager._read_state(manager.registry["stations"][0])["state"] == "Suspended"
    finally:
        if lease is not None and not lease.closed:
            lease.finish(control_complete=True, terminal=terminal(lease))
        manager.close()
