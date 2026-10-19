"""AES-256-GCM framed Bridge I/O with authenticated whole-session sealing.

Only four accessible inputs/outputs are retained: TASK.md, the exact --print
argument, and raw stdout/stderr bytes. Settings contents are never a stream.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_bytes
from types import SimpleNamespace
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from local_agent_bridge.capture.retention import (
    DEFAULT_LIMIT,
    RetentionDomain,
    StorageError,
    _canonical_uuid,
)

STREAMS = ("task", "request", "stdout", "stderr")
SOURCES = {
    "task": "verified task root work/TASK.md",
    "request": "regenerated plan argv[1] (--print argument UTF-8)",
    "stdout": "CLI stdout pipe raw bytes",
    "stderr": "CLI stderr pipe raw bytes",
}
SHADOW_SOURCES = {name: "verified source session stream, re-encrypted" for name in STREAMS}
FORMAT_VERSION = 2
MAGIC = b"LABFRAME2\n"
FRAME_HEADER = struct.Struct(">IQ12s")  # ciphertext length, sequence, random nonce
FRAME_MAX_PLAINTEXT = 65536
_SEAL_AAD = b"LocalAgentBridge/session-seal/v2/"
_FRAME_AAD = b"LocalAgentBridge/session-frame/v2/"


class SessionError(RuntimeError):
    """Capture is incomplete, corrupted, or has no usable storage budget."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _aad(domain: str, session_id: str, stream: str, sequence: int) -> bytes:
    return _FRAME_AAD + f"{domain}/{session_id}/{stream}/{sequence}".encode("ascii")


def _seal_aad(domain: str, manifest: dict) -> bytes:
    return _SEAL_AAD + domain.encode("ascii") + b"/" + _canonical(manifest)


def _frames(path: Path, key: bytes, domain: str, session_id: str, stream: str) -> Iterator[bytes]:
    cipher = AESGCM(key)
    with path.open("rb") as source:
        if source.read(len(MAGIC)) != MAGIC:
            raise SessionError("encrypted stream header is missing")
        sequence = 0
        while header := source.read(FRAME_HEADER.size):
            if len(header) != FRAME_HEADER.size:
                raise SessionError("encrypted frame header is truncated")
            length, found_sequence, nonce = FRAME_HEADER.unpack(header)
            if found_sequence != sequence or not 16 <= length <= FRAME_MAX_PLAINTEXT + 16:
                raise SessionError("encrypted frame sequence or length is invalid")
            encrypted = source.read(length)
            if len(encrypted) != length:
                raise SessionError("encrypted frame is truncated")
            try:
                yield cipher.decrypt(nonce, encrypted, _aad(domain, session_id, stream, sequence))
            except InvalidTag as error:
                raise SessionError("encrypted frame authentication failed") from error
            sequence += 1


class SessionStore:
    """A single domain; tests inject a key and root, production uses load_key."""

    def __init__(
        self,
        key: bytes,
        *,
        domain_name: str = "sessions",
        root: Path | None = None,
        limit: int = DEFAULT_LIMIT,
        terminal_reserve: int = 4096,
        receipt_reserve: int = 4096,
        protect_directory: Callable[[Path], None] | None = None,
        verify_directory: Callable[[Path], None] | None = None,
    ) -> None:
        if len(key) != 32:
            raise SessionError("session key must contain exactly 32 bytes")
        if domain_name not in {"sessions", "shadow"}:
            raise SessionError("unsupported session storage domain")
        self.key = key
        self.domain = RetentionDomain(
            domain_name,
            root=root,
            limit=limit,
            terminal_reserve=terminal_reserve,
            receipt_reserve=receipt_reserve,
            protect_directory=protect_directory,
            verify_directory=verify_directory,
            verify_bundle=self._verify_bundle,
        )

    def start(self) -> SessionWriter:
        """Retain failed bundles and bind their UID to the original exception."""
        session_id = str(uuid4())
        created_utc = datetime.now(UTC).isoformat()
        open_record = {
            "schema_version": FORMAT_VERSION,
            "domain": self.domain.domain,
            "session_id": session_id,
            "created_utc": created_utc,
            "state": "partial",
        }
        payload = _canonical(open_record) + b"\n"
        path = self.domain.root / session_id
        mkdir_attempted = created = False
        try:
            with self.domain.locked():
                self.domain.reserve(len(payload) + len(MAGIC) * len(STREAMS), new_active=True)
                mkdir_attempted = True
                path.mkdir()
                created = True
                with (path / "open.json").open("xb") as stream:
                    stream.write(payload)
                for name in STREAMS:
                    with (path / f"{name}.partial").open("xb") as stream:
                        stream.write(MAGIC)
            return SessionWriter(self, session_id, created_utc)
        except BaseException as error:
            if mkdir_attempted and not created:
                # mkdir may have created the bundle before raising. Only a
                # confirmed absence can rule out residue; retain the primary
                # exception even if the observation itself fails or interrupts.
                try:
                    path.lstat()
                except FileNotFoundError:
                    pass
                except BaseException:
                    created = True
                else:
                    created = True
            if created:
                error.capture_start_uid = session_id
            raise

    def _verify_bundle(self, path: Path) -> dict:
        if (
            path.is_symlink()
            or getattr(path.lstat(), "st_file_attributes", 0) & 0x400
            or path.parent != self.domain.root
            or path.resolve(strict=True).parent != self.domain.root.resolve(strict=True)
        ):
            raise SessionError("session bundle path is invalid")
        _canonical_uuid(path.name)
        seal_path = path / "seal.json"
        if (
            seal_path.is_symlink()
            or not seal_path.is_file()
            or getattr(seal_path.lstat(), "st_file_attributes", 0) & 0x400
        ):
            raise SessionError("session seal is not a regular file")
        if seal_path.stat().st_size > 32768:
            raise SessionError("session seal is oversized")
        envelope = json.loads(seal_path.read_bytes())
        if not isinstance(envelope, dict):
            raise SessionError("session seal shape is invalid")
        if envelope.get("schema_version") != FORMAT_VERSION:
            raise SessionError("unsupported session format version")
        if not isinstance(envelope.get("manifest"), dict):
            raise SessionError("session seal shape is invalid")
        manifest = envelope["manifest"]
        if manifest.get("schema_version") != FORMAT_VERSION:
            raise SessionError("unsupported session format version")
        if manifest.get("session_id") != path.name or manifest.get("domain") != self.domain.domain:
            raise SessionError("session identity mismatch")
        if manifest.get("state") != "complete":
            raise SessionError("session seal is incomplete")
        try:
            nonce = base64.b64decode(envelope["nonce"], validate=True)
            tag = base64.b64decode(envelope["tag"], validate=True)
            AESGCM(self.key).decrypt(nonce, tag, _seal_aad(self.domain.domain, manifest))
        except (InvalidTag, KeyError, TypeError, ValueError) as error:
            raise SessionError("session seal authentication failed") from error
        expected = {"open.json", *(f"{name}.enc" for name in STREAMS)}
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != expected:
            raise SessionError("session file inventory is invalid")
        streams = manifest.get("streams")
        if not isinstance(streams, dict) or set(streams) != set(STREAMS):
            raise SessionError("session stream inventory is invalid")
        if {item.name for item in path.iterdir()} != expected | {"seal.json"}:
            raise SessionError("unexpected or missing session file")
        for name, expected_file in files.items():
            if not isinstance(expected_file, dict):
                raise SessionError("session file inventory is invalid")
            item = path / name
            if (
                item.is_symlink()
                or not item.is_file()
                or getattr(item.lstat(), "st_file_attributes", 0) & 0x400
            ):
                raise SessionError("session file is not regular")
            if (
                item.stat().st_size != expected_file["bytes"]
                or _digest(item) != expected_file["sha256"]
            ):
                raise SessionError("session file length or hash differs")
        opening = json.loads((path / "open.json").read_bytes())
        if opening.get("schema_version") != FORMAT_VERSION:
            raise SessionError("unsupported session format version")
        if opening.get("session_id") != path.name or opening.get("domain") != self.domain.domain:
            raise SessionError("session opening identity mismatch")
        for name in STREAMS:
            expected_stream = streams[name]
            if not isinstance(expected_stream, dict):
                raise SessionError("session stream inventory is invalid")
            if expected_stream.get("complete") is not True:
                raise SessionError("session stream is incomplete")
            digest = hashlib.sha256()
            frames = length = 0
            for chunk in _frames(
                path / f"{name}.enc", self.key, self.domain.domain, path.name, name
            ):
                digest.update(chunk)
                frames += 1
                length += len(chunk)
            if (frames, length, digest.hexdigest()) != (
                expected_stream["frames"],
                expected_stream["bytes"],
                expected_stream["sha256"],
            ):
                raise SessionError("session stream frame count or digest differs")
        return manifest

    def reader(self, session_id: str) -> SessionReader:
        _canonical_uuid(session_id)
        return SessionReader(self, session_id)


class SessionWriter:
    def __init__(self, store: SessionStore, session_id: str, created_utc: str) -> None:
        self.store = store
        self.session_id = session_id
        self.created_utc = created_utc
        self.path = store.domain.root / session_id
        self._counts = {name: 0 for name in STREAMS}
        self._lengths = {name: 0 for name in STREAMS}
        self._hashes = {name: hashlib.sha256() for name in STREAMS}
        self.incomplete_reason: str | None = None
        self.sealed = False

    def stream(self, name: str) -> SessionStream:
        if name not in STREAMS:
            raise SessionError("unknown session stream")
        return SessionStream(self, name)

    def append(self, stream: str, data: bytes) -> bool:
        if stream not in STREAMS or self.sealed:
            raise SessionError("invalid or sealed session stream")
        if self.incomplete_reason is not None:
            return False
        if not data:
            return True
        if len(data) > FRAME_MAX_PLAINTEXT:
            raise SessionError("session frame exceeds the bounded size")
        sequence = self._counts[stream]
        nonce = token_bytes(12)
        encrypted = AESGCM(self.store.key).encrypt(
            nonce, data, _aad(self.store.domain.domain, self.session_id, stream, sequence)
        )
        frame = FRAME_HEADER.pack(len(encrypted), sequence, nonce) + encrypted
        try:
            with self.store.domain.locked():
                self.store.domain.reserve(len(frame))
                with (self.path / f"{stream}.partial").open("ab") as target:
                    target.write(frame)
                    target.flush()
                    os.fsync(target.fileno())
        except (OSError, StorageError) as error:
            self.incomplete_reason = (
                "over_limit"
                if isinstance(error, StorageError) and str(error).startswith("over_limit")
                else "storage_write_failed"
            )
            return False
        self._counts[stream] += 1
        self._lengths[stream] += len(data)
        self._hashes[stream].update(data)
        return True

    def iter_stream(self, stream: str) -> Iterator[bytes]:
        """Internal authenticated read before seal, after all pipe readers joined."""
        if stream not in STREAMS or self.incomplete_reason is not None:
            raise SessionError("session stream is incomplete")
        path = self.path / f"{stream}.partial"
        digest = hashlib.sha256()
        count = length = 0
        for chunk in _frames(
            path, self.store.key, self.store.domain.domain, self.session_id, stream
        ):
            digest.update(chunk)
            count += 1
            length += len(chunk)
            yield chunk
        if (count, length, digest.hexdigest()) != (
            self._counts[stream],
            self._lengths[stream],
            self._hashes[stream].hexdigest(),
        ):
            raise SessionError("session stream frame count or digest differs")

    def seal(self, metadata: dict[str, object]) -> dict:
        if self.incomplete_reason is not None or self.sealed:
            raise SessionError("incomplete session cannot be sealed")
        with self.store.domain.locked():
            for name in STREAMS:
                for _chunk in self.iter_stream(name):
                    pass
            for name in STREAMS:
                # All four streams have an explicit header, even when empty.
                (self.path / f"{name}.partial").rename(self.path / f"{name}.enc")
            files = {
                name: {
                    "bytes": (self.path / name).stat().st_size,
                    "sha256": _digest(self.path / name),
                }
                for name in ["open.json", *(f"{stream}.enc" for stream in STREAMS)]
            }
            manifest = {
                "schema_version": FORMAT_VERSION,
                "domain": self.store.domain.domain,
                "session_id": self.session_id,
                "created_utc": self.created_utc,
                "sealed_utc": datetime.now(UTC).isoformat(),
                "state": "complete",
                "sources": SOURCES if self.store.domain.domain == "sessions" else SHADOW_SOURCES,
                "streams": {
                    name: {
                        "frames": self._counts[name],
                        "bytes": self._lengths[name],
                        "sha256": self._hashes[name].hexdigest(),
                        "complete": True,
                    }
                    for name in STREAMS
                },
                "metadata": metadata,
                "files": files,
            }
            nonce = token_bytes(12)
            tag = AESGCM(self.store.key).encrypt(
                nonce, b"", _seal_aad(self.store.domain.domain, manifest)
            )
            envelope = {
                "schema_version": FORMAT_VERSION,
                "manifest": manifest,
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "tag": base64.b64encode(tag).decode("ascii"),
            }
            payload = _canonical(envelope) + b"\n"
            self.store.domain.reserve(len(payload), release_active=True)
            temporary_seal = self.path / "seal.tmp"
            with temporary_seal.open("xb") as target:
                target.write(payload)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary_seal, self.path / "seal.json")
        self.sealed = True
        return manifest


class SessionStream:
    """A pipe sink backed only by ciphertext files in the session domain."""

    def __init__(self, writer: SessionWriter, name: str) -> None:
        self.writer = writer
        self.name = name

    def append(self, data: bytes) -> bool:
        return self.writer.append(self.name, data)

    def iter_chunks(self) -> Iterator[bytes]:
        return self.writer.iter_stream(self.name)

    def write_bytes(self, data: bytes) -> int:
        """One-shot adapter for synthetic tests; production uses append()."""
        for offset in range(0, len(data), FRAME_MAX_PLAINTEXT):
            if not self.append(data[offset : offset + FRAME_MAX_PLAINTEXT]):
                raise SessionError("session capture incomplete")
        return len(data)

    def read_bytes(self) -> bytes:
        return b"".join(self.iter_chunks())

    def stat(self):
        return SimpleNamespace(st_size=self.writer._lengths[self.name])

    @property
    def sha256(self) -> str:
        return self.writer._hashes[self.name].hexdigest()


class SessionReader:
    """Authenticated read surface for sealed sessions and shadow snapshots."""

    def __init__(self, store: SessionStore, session_id: str) -> None:
        self.store = store
        self.session_id = session_id

    def manifest(self) -> dict:
        with self.store.domain.locked():
            return self.store._verify_bundle(self.store.domain.root / self.session_id)

    def iter_stream(self, name: str) -> Iterator[bytes]:
        if name not in STREAMS:
            raise SessionError("unknown session stream")
        with self.store.domain.locked():
            manifest = self.store._verify_bundle(self.store.domain.root / self.session_id)
            expected = manifest["streams"][name]
            digest = hashlib.sha256()
            count = length = 0
            path = self.store.domain.root / self.session_id / f"{name}.enc"
            for chunk in _frames(
                path, self.store.key, self.store.domain.domain, self.session_id, name
            ):
                digest.update(chunk)
                count += 1
                length += len(chunk)
                yield chunk
            if (count, length, digest.hexdigest()) != (
                expected["frames"],
                expected["bytes"],
                expected["sha256"],
            ):
                raise SessionError("session stream frame count or digest differs")

    def read_stream(self, name: str) -> bytes:
        return b"".join(self.iter_stream(name))
