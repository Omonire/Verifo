"""Secure file storage abstraction.

Provides a pluggable StorageBackend (local disk for the MVP, object stores
later) with:
  * tenant-scoped path layout  storage/orgs/<org_id>/...
  * traversal-safe writes       (always write under the tenant root)
  * optional Fernet encryption at rest
  * short-lived download tokens (signed JWT, never raw filesystem paths)
"""
import io
import os
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from .security import sanitize_basename


def _fernet(key: str | None) -> Fernet | None:
    if not key:
        return None
    try:
        return Fernet(key.encode("utf-8"))
    except Exception:  # noqa: BLE001
        raise RuntimeError("VERIFO_STORAGE_KEY is not a valid Fernet key (run `python -m cryptography.fernet`).")


class StorageBackend(ABC):
    @abstractmethod
    def save(self, tenant_id: str, scope: str, filename: str, data: bytes) -> str:
        """Persist bytes under tenant/scope, return storage path/name."""

    @abstractmethod
    def read(self, tenant_id: str, storage_path: str) -> bytes:
        """Return raw bytes for an existing stored file."""

    @abstractmethod
    def delete(self, tenant_id: str, storage_path: str) -> None:
        pass

    @abstractmethod
    def exists(self, tenant_id: str, storage_path: str) -> bool:
        pass

    @abstractmethod
    def resolve(self, tenant_id: str, storage_path: str) -> Path:
        """Return the absolute, tamper-checked file path for a stored item."""
        pass

    @abstractmethod
    def materialize(self, tenant_id: str, storage_path: str) -> tuple[str, Callable | None]:
        """Return a filesystem path whose bytes are readable by downstream tools.

        For non-encrypted backends this is the stored file itself (cleanup None).
        For encrypted at-rest backends this writes a temporary decrypted copy and
        returns a cleanup callable; callers must invoke it once done.
        """
        pass


class LocalStorage(StorageBackend):
    """Disk-based storage. Paths are internal keys, never user input."""

    def __init__(self, root: str | Path, encrypt: bool = False, key: str = ""):
        self.root = Path(root)
        self.encrypt = encrypt
        self.cipher = _fernet(key) if encrypt else None
        if encrypt and self.cipher is None:
            raise RuntimeError("Encryption enabled but no valid key provided.")
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, tenant_id: str, storage_path: str) -> Path:
        safe = storage_path.lstrip("/").replace("\\", "/")
        if ".." in Path(safe).parts:
            raise ValueError("Unsafe storage path.")
        return (self.root / "orgs" / tenant_id / safe).resolve()

    def save(self, tenant_id: str, scope: str, filename: str, data: bytes) -> str:
        name = sanitize_basename(filename)
        key = f"{scope}/{uuid.uuid4().hex[:12]}-{name}"
        target = self._resolve(tenant_id, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.cipher.encrypt(data) if self.cipher else data
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(payload)
        tmp.replace(target)
        return key

    def read(self, tenant_id: str, storage_path: str) -> bytes:
        target = self._resolve(tenant_id, storage_path)
        if not target.is_file():
            raise FileNotFoundError(storage_path)
        raw = target.read_bytes()
        if self.cipher:
            try:
                return self.cipher.decrypt(raw)
            except InvalidToken as exc:
                raise ValueError("Stored file could not be decrypted.") from exc
        return raw

    def delete(self, tenant_id: str, storage_path: str) -> None:
        target = self._resolve(tenant_id, storage_path)
        if target.is_file():
            target.unlink()

    def exists(self, tenant_id: str, storage_path: str) -> bool:
        target = self._resolve(tenant_id, storage_path)
        return target.is_file()

    def resolve(self, tenant_id: str, storage_path: str) -> Path:
        """Return the absolute filesystem path for a stored item (safe)."""
        return self._resolve(tenant_id, storage_path)

    def materialize(self, tenant_id: str, storage_path: str) -> tuple[str, Callable | None]:
        """Readable path for parsers; decrypts to a temp copy when encrypted."""
        target = self._resolve(tenant_id, storage_path)
        if not target.is_file():
            raise FileNotFoundError(storage_path)
        if not self.cipher or not self.encrypt:
            return str(target), None
        raw = self.cipher.decrypt(target.read_bytes())
        tmp_dir = self.root / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / f"{uuid.uuid4().hex}{target.suffix}"
        tmp.write_bytes(raw)

        def cleanup():
            if tmp.is_file():
                tmp.unlink(missing_ok=True)

        return str(tmp), cleanup


def get_storage() -> StorageBackend:
    """Return the configured backend (cached on the app)."""
    app = current_app._get_current_object()
    if "storage" not in app.extensions:
        cfg = app.config
        app.extensions["storage"] = LocalStorage(
            cfg["STORAGE_DIR"],
            encrypt=cfg["STORAGE_ENCRYPT"],
            key=cfg.get("STORAGE_KEY", ""),
        )
    return app.extensions["storage"]


def sign_download_token(tenant_id: str, storage_path: str) -> str:
    """Short-lived signed token granting read access to one stored file."""
    from ..auth.tokens import issue_download_token

    return issue_download_token(tenant_id, storage_path)


def resolve_download_token(token: str) -> dict:
    """Validate a download token; returns {'org_id', 'path'} or raises."""
    from ..auth.tokens import decode_download_token

    return decode_download_token(token)


def extract_zip_entries(zip_bytes: bytes, tenant_id: str, scope: str, allowed_exts: set[str]):
    """Safely extract a validated archive to storage item-by-item.

    Returns a list of dicts: {filename, storage_path, size, ext}. Uses an
    allowlist of extensions; never uses member names as filesystem paths.
    """
    import zipfile
    from io import BytesIO
    from pathlib import Path as _Path

    from .security import check_zip_safety

    check_zip_safety(zip_bytes)
    storage = get_storage()
    entries = []
    seen: dict[str, int] = {}

    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            base = sanitize_basename(_Path(member.filename).name)
            ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
            if ext not in allowed_exts:
                continue
            data = zf.read(member)
            if not data:
                continue

            # De-duplicate identical basenames (zip bombs / collisions).
            count = seen.get(base, 0)
            seen[base] = count + 1
            stored_name = f"{count:03d}-{base}" if count else base

            storage_path = storage.save(tenant_id, scope, stored_name, data)
            entries.append(
                {
                    "filename": base,
                    "storage_path": storage_path,
                    "size": len(data),
                    "ext": ext,
                }
            )
    return entries


# Small helper used by tests and seeds to read a file cleanly.
def bytes_stream(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)
