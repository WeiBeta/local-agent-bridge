"""One process owns one configured station through a native Windows mutex.

Waiting is WaitAny on kernel handles, not a queue service or a state-file poll.
State is recovery evidence; the mutex, held by the acquiring thread, is ownership.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import threading
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from . import contract, paths, task_input


class StationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def require(condition: object, code: str) -> None:
    if not condition:
        raise StationError(code)


def digest(value: object) -> str:
    return hashlib.sha256(task_input._canonical_json_bytes(value)).hexdigest()


def physical_identity(root: Path) -> dict:
    try:
        task_input._assert_plain_target(root, label="station root")
        require(root.is_dir(), "StationRootUnavailable")
        info = root.stat()
    except (OSError, task_input.TaskInputError) as error:
        raise StationError("StationRootUnavailable") from error
    return {"st_dev": info.st_dev, "st_ino": info.st_ino}


def ordinary_path(value: object) -> Path:
    root = task_input._validate_absolute_path(value, label="station path")
    task_input._assert_plain_target(root, label="station path")
    task_input._reject_broad_root(root, "station path")
    return root


class WindowsHandles:
    """Typed handles with no fallback to process-local synchronization."""

    def __init__(self) -> None:
        require(os.name == "nt", "StationWindowsRequired")
        self.dll = ctypes.WinDLL("kernel32", use_last_error=True)
        self.dll.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.dll.CreateMutexW.restype = wintypes.HANDLE
        self.dll.CreateEventW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        self.dll.CreateEventW.restype = wintypes.HANDLE
        self.dll.WaitForMultipleObjects.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.dll.WaitForMultipleObjects.restype = wintypes.DWORD
        for name in ("ReleaseMutex", "CloseHandle", "SetEvent"):
            function = getattr(self.dll, name)
            function.argtypes = [wintypes.HANDLE]
            function.restype = wintypes.BOOL

    def mutex(self, name: str) -> int:
        handle = self.dll.CreateMutexW(None, False, name)
        require(handle, "StationLockUnavailable")
        return handle

    def event(self) -> int:
        handle = self.dll.CreateEventW(None, True, False, None)
        require(handle, "StationCancellationUnavailable")
        return handle

    def wait(self, handles: list[int], milliseconds: int) -> int:
        array = (wintypes.HANDLE * len(handles))(*handles)
        return self.dll.WaitForMultipleObjects(len(handles), array, False, milliseconds)

    def release(self, handle: int) -> None:
        require(self.dll.ReleaseMutex(handle), "StationReleaseFailed")

    def close(self, handle: int) -> None:
        require(self.dll.CloseHandle(handle), "StationHandleCloseFailed")


class Cancellation:
    """A caller-owned event; keep it open until acquire has returned."""

    def __init__(self) -> None:
        self.kernel = WindowsHandles()
        self.handle = self.kernel.event()

    def cancel(self) -> None:
        require(self.kernel.dll.SetEvent(self.handle), "StationCancellationFailed")

    def close(self) -> None:
        self.kernel.close(self.handle)


@dataclass(frozen=True)
class Station:
    id: str
    native_id: str
    root: Path
    record: Path
    root_identity: dict

    @property
    def lock_name(self) -> str:
        # Physical root identity is shared by all managers, independent of pool/id spelling.
        return "Global\\LocalAgentBridgeStation-" + digest(self.root_identity)


def load_registry(path: Path, expected: str) -> dict:
    task_input._assert_plain_target(path, label="station registry")
    with path.open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    require(len(raw) <= 1024 * 1024, "StationRegistryTooLarge")
    require(hashlib.sha256(raw).hexdigest() == expected, "StationRegistryChanged")
    value = contract.decode_strict_json_bytes(raw, label="station registry")
    require(
        type(value) is dict
        and set(value)
        == {
            "contract_version",
            "id",
            "control_root",
            "deployment_receipt",
            "policy",
            "stations",
        },
        "StationRegistryInvalid",
    )
    require(
        type(value["contract_version"]) is int and value["contract_version"] == 1,
        "StationRegistryInvalid",
    )
    require(type(value["id"]) is str and bool(value["id"]), "StationRegistryInvalid")
    control = ordinary_path(value["control_root"])
    require(control.is_dir(), "StationControlUnavailable")
    policy = value["policy"]
    require(
        type(policy) is dict
        and set(policy)
        == {
            "grant_ref",
            "roles",
            "capabilities",
            "max_deadline_seconds",
            "source_output_bytes_limit",
        },
        "StationPolicyInvalid",
    )
    require(type(policy["grant_ref"]) is str and bool(policy["grant_ref"]), "StationPolicyInvalid")
    require(policy["roles"] == ["Coding", "Review"], "StationPolicyInvalid")
    caps = policy["capabilities"]
    require(
        type(caps) is dict
        and set(caps)
        == {
            "execute",
            "web_reference",
            "prepare_dependencies",
        }
        and all(type(item) is bool for item in caps.values()),
        "StationPolicyInvalid",
    )
    for field, maximum in (
        ("max_deadline_seconds", 3600),
        ("source_output_bytes_limit", 1024 * 1024 * 1024),
    ):
        require(
            type(policy[field]) is int and 1 <= policy[field] <= maximum, "StationPolicyInvalid"
        )
    require(type(value["deployment_receipt"]) is dict, "StationRegistryInvalid")
    entries = value["stations"]
    require(type(entries) is list and 1 <= len(entries) <= 4, "StationCapacityInvalid")
    stations = []
    for item in entries:
        require(
            type(item) is dict
            and set(item)
            == {
                "id",
                "native_id",
                "root",
                "record",
                "root_identity",
            },
            "StationRegistryInvalid",
        )
        try:
            require(str(uuid.UUID(item["id"])) == item["id"], "StationRegistryInvalid")
        except (ValueError, TypeError, AttributeError) as error:
            raise StationError("StationRegistryInvalid") from error
        require(
            type(item["native_id"]) is str and bool(item["native_id"]), "StationRegistryInvalid"
        )
        root, record = ordinary_path(item["root"]), ordinary_path(item["record"])
        identity = item["root_identity"]
        require(
            type(identity) is dict
            and set(identity) == {"st_dev", "st_ino"}
            and all(type(number) is int and number >= 0 for number in identity.values()),
            "StationRegistryInvalid",
        )
        require(record.name == item["native_id"] + ".json", "StationRegistryInvalid")
        require(not paths._is_within(record, root), "StationRegistryInvalid")
        require(
            not paths._is_within(control, root) and not paths._is_within(root, control),
            "StationControlOverlap",
        )
        stations.append(Station(item["id"], item["native_id"], root, record, identity))
    require(
        len({entry.id for entry in stations}) == len(stations)
        and len({entry.native_id for entry in stations}) == len(stations)
        and len({entry.lock_name for entry in stations}) == len(stations)
        and len({entry.root for entry in stations}) == len(stations),
        "StationDuplicate",
    )
    require(
        not any(
            paths._is_within(left.root, right.root) or paths._is_within(right.root, left.root)
            for index, left in enumerate(stations)
            for right in stations[index + 1 :]
        ),
        "StationRootOverlap",
    )
    return {
        "document": value,
        "stations": stations,
        "control_root": control,
        "path": path,
        "sha256": expected,
    }


class Pool:
    def __init__(self, registry: dict, *, kernel=None) -> None:
        self.registry = registry
        self.kernel = WindowsHandles() if kernel is None else kernel
        self.handles = {}
        self.leases = set()
        try:
            for station in registry["stations"]:
                self.handles[station.id] = self.kernel.mutex(station.lock_name)
        except BaseException:
            self.close()
            raise

    def _state_path(self, station: Station) -> Path:
        return self.registry["control_root"] / "states" / (station.id + ".json")

    def _read_state(self, station: Station) -> dict:
        path = self._state_path(station)
        task_input._assert_plain_target(path, label="station state")
        if not path.exists():
            return {"state": "Idle", "station_id": station.id}
        try:
            with path.open("rb") as stream:
                raw = stream.read(65537)
            require(len(raw) <= 65536, "StationStateInvalid")
            value = contract.decode_strict_json_bytes(raw, label="station state")
        except (OSError, contract.BridgeContractError) as error:
            raise StationError("StationStateInvalid") from error
        require(
            type(value) is dict
            and value.get("station_id") == station.id
            and value.get("state") in {"Idle", "Reserved", "Running", "Suspended"},
            "StationStateInvalid",
        )
        return value

    def _write_state(self, station: Station, value: dict) -> None:
        path = self._state_path(station)
        task_input._assert_plain_target(path, label="station state")
        path.parent.mkdir(exist_ok=True)
        temporary = path.with_name(path.name + "." + str(uuid.uuid4()) + ".tmp")
        with temporary.open("xb") as stream:
            stream.write(task_input._canonical_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        task_input._assert_plain_target(path, label="station state")
        os.replace(temporary, path)

    def acquire(
        self,
        request_id: str,
        *,
        timeout_seconds: float | None = None,
        cancellation: Cancellation | None = None,
    ) -> Lease:
        require(type(request_id) is str and bool(request_id), "StationRequestInvalid")
        require(
            timeout_seconds is None
            or (type(timeout_seconds) in {int, float} and 0 <= timeout_seconds <= 86400),
            "StationWaitInvalid",
        )
        candidates = list(self.registry["stations"])
        started = time.monotonic()
        while candidates:  # Each unhealthy candidate is removed once; busy slots use kernel wait.
            handles = [self.handles[station.id] for station in candidates]
            if cancellation is not None:
                handles.insert(0, cancellation.handle)
            remaining = (
                None
                if timeout_seconds is None
                else max(0, timeout_seconds - (time.monotonic() - started))
            )
            milliseconds = (
                0xFFFFFFFF if remaining is None else min(0xFFFFFFFE, int(remaining * 1000))
            )
            result = self.kernel.wait(handles, milliseconds)
            if result == 0x102:
                raise StationError("StationCapacityWaitExpired")
            require(result != 0xFFFFFFFF, "StationWaitFailed")
            abandoned = 0x80 <= result < 0x80 + len(handles)
            index = result - (0x80 if abandoned else 0)
            require(0 <= index < len(handles), "StationWaitFailed")
            if cancellation is not None:
                if index == 0:
                    raise StationError("StationAdmissionCancelled")
                index -= 1
            station = candidates[index]
            handle = self.handles[station.id]
            try:
                state = self._read_state(station)
                if state["state"] in {"Reserved", "Running"} and state.get("owner") == {
                    "pid": os.getpid(),
                    "thread": threading.get_ident(),
                }:
                    raise StationError("StationReentrantAcquire")
                if abandoned or state["state"] != "Idle":
                    if state["state"] != "Suspended":
                        self._write_state(
                            station,
                            {
                                "state": "Suspended",
                                "station_id": station.id,
                                "reason": "OwnershipUnconfirmed",
                                "previous": state,
                            },
                        )
                    self.kernel.release(handle)
                    candidates.pop(index)
                    continue
                require(
                    physical_identity(station.root) == station.root_identity, "StationRootChanged"
                )
                lease = Lease(self, station, handle, request_id)
                lease._write("Reserved")
                self.leases.add(lease.id)
                return lease
            except StationError as error:
                if error.code not in {
                    "StationRootChanged",
                    "StationRootUnavailable",
                    "StationStateInvalid",
                }:
                    self.kernel.release(handle)
                    raise
                try:
                    # Malformed recovery evidence is retained byte-for-byte. It
                    # stays ineligible on later admission until deliberate repair.
                    if error.code != "StationStateInvalid":
                        self._write_state(
                            station,
                            {"state": "Suspended", "station_id": station.id, "reason": error.code},
                        )
                finally:
                    self.kernel.release(handle)
                candidates.pop(index)
            except BaseException:
                self.kernel.release(handle)
                raise
        raise StationError("StationNoAvailableSlot")

    def close(self) -> None:
        require(not self.leases, "StationLeaseOutstanding")
        for handle in self.handles.values():
            self.kernel.close(handle)
        self.handles.clear()


class Lease:
    def __init__(self, pool: Pool, station: Station, handle: int, request_id: str) -> None:
        self.pool, self.station, self.handle = pool, station, handle
        self.request_id, self.id = request_id, str(uuid.uuid4())
        self.owner = {"pid": os.getpid(), "thread": threading.get_ident()}
        self.task_root = None
        self.closed = False

    def _write(self, state: str, **extra) -> None:
        self.pool._write_state(
            self.station,
            {
                "state": state,
                "station_id": self.station.id,
                "request_id": self.request_id,
                "lease_id": self.id,
                "owner": self.owner,
                "task_root": str(self.task_root) if self.task_root else None,
                **extra,
            },
        )

    def verify(self, task_root: Path | None = None) -> None:
        require(
            not self.closed
            and self.owner
            == {
                "pid": os.getpid(),
                "thread": threading.get_ident(),
            },
            "StationLeaseRequired",
        )
        state = self.pool._read_state(self.station)
        require(
            state.get("lease_id") == self.id
            and state.get("owner") == self.owner
            and state["state"] in {"Reserved", "Running"},
            "StationLeaseRequired",
        )
        if task_root is not None:
            require(task_root == self.task_root, "StationLeaseRequired")
        require(
            physical_identity(self.station.root) == self.station.root_identity, "StationRootChanged"
        )

    def bind_task(self, root: Path) -> None:
        self.verify()
        require(root.parent == self.station.root / "jobs", "StationTaskScopeInvalid")
        try:
            require(str(uuid.UUID(root.name)) == root.name, "StationTaskScopeInvalid")
        except ValueError as error:
            raise StationError("StationTaskScopeInvalid") from error
        require(not os.path.lexists(root) and self.task_root is None, "StationTaskNotFresh")
        self.task_root = root
        self._write("Reserved")

    def running(self) -> None:
        self.verify(self.task_root)
        self._write("Running")

    def finish(self, *, control_complete: bool, terminal: Path) -> None:
        self.verify(self.task_root)
        require(
            terminal.is_file()
            and paths._is_within(
                terminal, self.pool.registry["control_root"] / "requests" / self.request_id
            ),
            "StationTerminalUnavailable",
        )
        try:
            self._write(
                "Idle" if control_complete else "Suspended",
                terminal=str(terminal),
                reason=None if control_complete else "ControlUnconfirmed",
            )
        finally:
            self.pool.kernel.release(self.handle)
            self.closed = True
            self.pool.leases.discard(self.id)

    def abandon(self) -> None:
        if not self.closed:
            try:
                self._write("Suspended", reason="TerminalUnavailable")
            finally:
                self.pool.kernel.release(self.handle)
                self.closed = True
                self.pool.leases.discard(self.id)
