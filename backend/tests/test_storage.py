"""Storage backend: traversal safety, round trips, download tokens."""
import pytest
from cryptography.fernet import Fernet

from app.services.storage import LocalStorage, get_storage, sign_download_token, resolve_download_token
from app.services.storage import extract_zip_entries


def test_roundtrip_and_traversal_safety(app):
    with app.app_context():
        storage = get_storage()
        key = storage.save("orgA", "refs", "certificate.pdf", b"%PDF-1.7 data")
        assert storage.exists("orgA", key)
        assert storage.read("orgA", key) == b"%PDF-1.7 data"

        # Read attempts outside the tenant root are refused.
        with pytest.raises(ValueError):
            storage.read("orgA", "../orgB/" + key)
        with pytest.raises(ValueError):
            storage.read("orgA", "../../secret")

        # A different tenant cannot read org A's file.
        assert not storage.exists("orgB", key)
        with pytest.raises(FileNotFoundError):
            storage.read("orgB", key)


def test_download_tokens_are_org_scoped(app):
    with app.app_context():
        token = sign_download_token("orgA", "refs/cert.pdf")
        payload = resolve_download_token(token)
        assert payload == {"org_id": "orgA", "path": "refs/cert.pdf"}

        storage = get_storage()
        storage.save("orgB", "refs", "other.pdf", b"x")
        with pytest.raises(Exception):
            resolve_download_token(token + "tampered")


def test_encryption_at_rest(tmp_path):
    key = Fernet.generate_key().decode()
    storage = LocalStorage(tmp_path, encrypt=True, key=key)
    spath = storage.save("t", "docs", "doc.bin", b"top-secret")
    # File on disk must be ciphertext.
    raw = next(tmp_path.rglob("*.bin")).read_bytes()
    assert raw != b"top-secret"
    assert storage.read("t", spath) == b"top-secret"


def test_encryption_requires_valid_key(tmp_path):
    with pytest.raises(RuntimeError):
        LocalStorage(tmp_path, encrypt=True, key="not-a-fernert-key")


def test_materialize_returns_readable_plaintext(tmp_path):
    """Parsers must get plain bytes even when storage is encrypted at rest."""
    key = Fernet.generate_key().decode()
    storage = LocalStorage(tmp_path, encrypt=True, key=key)
    spath = storage.save("t", "docs", "doc.pdf", b"%PDF-1.7 payload")
    readable, cleanup = storage.materialize("t", spath)
    try:
        assert open(readable, "rb").read() == b"%PDF-1.7 payload"
        # The materialized copy is plaintext, not ciphertext.
        assert b"payload" in open(readable, "rb").read()
    finally:
        if cleanup:
            cleanup()
    assert not __import__("os").path.exists(readable)


def test_materialize_plain_backend_returns_stored_path(tmp_path):
    storage = LocalStorage(tmp_path, encrypt=False)
    spath = storage.save("t", "docs", "doc.pdf", b"%PDF-1.7 payload")
    readable, cleanup = storage.materialize("t", spath)
    assert readable == str(storage.resolve("t", spath))
    assert cleanup is None


def test_zip_extraction_preserves_allowed_exts_only(app):
    import io
    import zipfile

    with app.app_context():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("cert.pdf", b"%PDF-1.7")
            zf.writestr("notes.md", b"# not allowed")
        entries = extract_zip_entries(buf.getvalue(), "orgA", "subs", {"pdf"})
        assert [e["ext"] for e in entries] == ["pdf"]
        assert entries[0]["storage_path"].startswith("subs/")