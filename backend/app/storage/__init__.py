"""Document repository.

Originals are stored byte-for-byte, encrypted at rest with a key held only by the backend,
under random object keys. The original filename lives only in the database. A different
backend (S3-compatible object storage on a private network, an SMB share on an approved
file server) implements the same three methods.
"""

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class StorageUnavailable(Exception):
    """Transient: the repository could not be reached. Jobs retry on this."""


class StorageCorrupted(Exception):
    """Permanent: the stored object does not decrypt or does not match its hash."""


class DocumentStore(Protocol):
    def put(self, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def healthy(self) -> bool: ...


class EncryptedFileStore:
    def __init__(self, root: Path, key: str):
        self.root = root
        self._fernet = Fernet(key.encode())

    def _path(self, key: str) -> Path:
        if len(key) != 48 or not all(c in "0123456789abcdef" for c in key):
            raise StorageCorrupted("invalid storage key")
        return self.root / key[:2] / key[2:4] / key

    def put(self, data: bytes) -> str:
        key = secrets.token_hex(24)
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "wb") as fh:
                fh.write(self._fernet.encrypt(data))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except OSError as exc:
            raise StorageUnavailable(str(exc)) from exc
        return key

    def get(self, key: str) -> bytes:
        try:
            blob = self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise StorageCorrupted("object missing") from exc
        except OSError as exc:
            raise StorageUnavailable(str(exc)) from exc
        try:
            return self._fernet.decrypt(blob)
        except InvalidToken as exc:
            raise StorageCorrupted("object does not decrypt with the configured key") from exc

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageUnavailable(str(exc)) from exc

    def healthy(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".probe"
            probe.write_bytes(b"ok")
            probe.unlink()
            return True
        except OSError:
            return False


@lru_cache
def get_store() -> DocumentStore:
    s = get_settings()
    return EncryptedFileStore(s.storage_dir, s.storage_encryption_key)
