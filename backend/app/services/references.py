"""Reference document processing (Phase 2): extract + fingerprint + persist.

A reference is a *trusted verified original*. Processing captures what is
observable about the document (structured fields, text-layer fingerprint,
PDF metadata) so later submissions can be compared both field-by-field and
structurally. Nothing here asserts a document is "real" — it only records
what the trusted copy looks like.
"""
import hashlib

import fitz

from ..extensions import db
from ..models.domain import ReferenceDocument, ReferenceStatus
from .storage import get_storage
from .verification.concrete import TextLayerOCR, sha256_hex


def capture_baseline(asset_path: str) -> dict:
    """Observe a document's structure + metadata without judging it."""
    meta = {}
    try:
        with fitz.open(asset_path) as doc:
            meta = {k: v for k, v in (doc.metadata or {}).items() if v}
            meta["page_count"] = doc.page_count
            meta["text_chars"] = sum(len(p.get_text("text") or "") for p in doc)
            meta["producer"] = (meta.get("producer") or meta.get("creator") or "").strip()
    except Exception:
        meta = {"page_count": 0, "text_chars": 0, "producer": ""}
    return meta


def process_reference(organization_id, *, filename: str, data: bytes,
                      document_type_id: str | None, title: str, ref_code: str,
                      fields_config: list | None) -> dict:
    """Store + analyze a trusted copy. Returns dict ready for a ReferenceDocument row."""
    storage = get_storage()
    path = storage.save(organization_id, "references", filename, data)
    checksum = sha256_hex(data)
    asset_path, cleanup = storage.materialize(organization_id, path)

    ocr = TextLayerOCR()
    try:
        fields = [f for f in ocr.extract(asset_path) if not f.key.startswith("doc_")]
        baseline = capture_baseline(asset_path)
    finally:
        if cleanup:
            cleanup()
    # All-matches textual fingerprint of the reference document.
    canonical = "\n".join(f"{f.key}={normalize_value(f.value)}" for f in fields)
    fingerprint = {
        "text": sha256_hex(canonical.encode()),
        "fields": [f.key for f in fields],
        "baseline": baseline,
    }

    return {
        "organization_id": organization_id,
        "document_type_id": document_type_id,
        "title": title,
        "ref_code": ref_code,
        "filename": filename,
        "storage_path": path,
        "checksum": checksum,
        "fingerprint": fingerprint,
        "extracted_fields": [
            {"key": f.key, "value": f.value, "confidence": f.confidence} for f in fields
        ],
        "status": ReferenceStatus.ACTIVE,
    }


def normalize_value(value) -> str:
    import re as _re

    return _re.sub(r"[\s\-_/.,:;']+", "", (str(value) or "").lower())


def next_ref_code(document_type_code: str, count: int) -> str:
    return f"REF-{document_type_code.upper()}-{count + 1:04d}"