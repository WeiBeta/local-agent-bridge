"""Dedicated Windows Credential Manager key for local Bridge sessions."""

from __future__ import annotations

import base64
import binascii
import platform
from secrets import token_bytes

import keyring

SERVICE_NAME = "LocalAgentBridge.SessionCapture.v1"
KEY_ACCOUNT = "aes256gcm-session-v1"


class SessionKeyError(RuntimeError):
    """The local session key is missing or unavailable."""


def _backend():
    if platform.system() != "Windows":
        raise SessionKeyError("session capture requires Windows Credential Manager")
    try:
        backend = keyring.get_keyring()
    except Exception as error:
        raise SessionKeyError("Windows Credential Manager is unavailable") from error
    if not type(backend).__module__.casefold().startswith("keyring.backends.windows"):
        raise SessionKeyError("session capture requires Windows Credential Manager")
    return backend


def load_key() -> bytes:
    """Read only this product's key; never silently create or fall back."""
    backend = _backend()
    try:
        encoded = backend.get_password(SERVICE_NAME, KEY_ACCOUNT)
    except Exception as error:
        raise SessionKeyError("session key is unavailable") from error
    if encoded is None:
        raise SessionKeyError("session key missing; run local-agent-bridge session-key-init")
    try:
        key = base64.b64decode(encoded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError, TypeError) as error:
        raise SessionKeyError("session key has an invalid shape") from error
    if len(key) != 32:
        raise SessionKeyError("session key has an invalid shape")
    return key


def initialize_key() -> bool:
    """Explicit local installation step. False means a valid key already exists."""
    backend = _backend()
    try:
        existing = backend.get_password(SERVICE_NAME, KEY_ACCOUNT)
        if existing is not None:
            # Malformed credentials must be diagnosed, never replaced implicitly.
            load_key()
            return False
        key = token_bytes(32)
        backend.set_password(
            SERVICE_NAME, KEY_ACCOUNT, base64.urlsafe_b64encode(key).decode("ascii")
        )
        if load_key() != key:
            raise SessionKeyError("session key initialization could not be verified")
    except SessionKeyError:
        raise
    except Exception as error:
        raise SessionKeyError("session key initialization failed") from error
    return True
