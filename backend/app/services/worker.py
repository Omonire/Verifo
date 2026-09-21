"""Self-built background worker (Phase 4): polls queue_tasks rows and runs
verification pipelines in-process. No Redis/Celery required; SQLAlchemy rows
are the queue. Claim/lease semantics keep work safe under one process (and
scale to a few worker processes on Postgres).
"""
import threading
import time
from datetime import timedelta

from ..extensions import db
from ..models.common import utcnow
from ..models.domain import (
    ItemStatus,
    JobStatus,
    QueueState,
    QueueTask,
    ScreeningItem,
    Verification,
    VerificationStatus,
)
from .audit import AuditService
from .storage import get_storage
from .verification import build_engine
from .verification.signals import ExtractedField, FieldMatch


def build_lookup(organization_id: str):
    """Return a lookup(extracted_fields) -> records callback scoped to org."""
    from ..models.domain import ReferenceDocument

    def lookup(key_fields: dict):
        refs = ReferenceDocument.query.filter_by(
            organization_id=organization_id, status="ACTIVE").all()
        records = []
        for ref in refs:
            row = {f["key"]: f["value"] for f in (ref.extracted_fields or [])}
            hit = True
            for k, v in key_fields.items():
                if k.startswith("doc_") or not v:
                    continue
                if row.get(k) is not None and normalize(str(row[k])) == normalize(str(v)):
                    continue
                if row.get(k):
                    hit = False
            if hit and any(key_fields.get(k) for k in key_fields):
                records.append(row)
        return records

    def normalize(s):
        import re

        return re.sub(r"[\s\-_/.,:;']+", "", s.lower())

    return lookup


def _engine():
    from flask import current_app

    from ..services.ai import resolve_from_config

    provider = resolve_from_config(current_app.config)
    return build_engine(provider=provider)


def _materialize(org_id: str, storage_path: str) -> tuple[str, "Callable | None"]:
    """Readable path for the analyzers, with an optional temp cleanup to run."""
    return get_storage().materialize(org_id, storage_path)


def run_single_verification(verification_id: str, ai_evidence=None):
    from ..models.domain import ReferenceDocument

    ver = Verification.query.get(verification_id)
    if not ver:
        return
    ver.status = VerificationStatus.PROCESSING
    db.session.commit()

    asset_path, cleanup = _materialize(ver.organization_id, ver.storage_path)
    claimed = []
    ref = None
    if ver.reference_id:
        ref = ReferenceDocument.query.filter_by(
            id=ver.reference_id, organization_id=ver.organization_id).first()
        if ref:
            claimed.append({
                "extracted_fields": ref.extracted_fields or [],
                "metadata": ref.fingerprint.get("baseline", {}) if ref.fingerprint else {},
            })

    try:
        report = _engine().run(
            [asset_path], claimed, ver.organization_id,
            config=_org_config(ver.organization_id),
            database_lookup=build_lookup(ver.organization_id),
            supplemental_fields=_ai_evidence_fields(ai_evidence),
        )
    finally:
        if cleanup:
            cleanup()
    ver.status = (
        VerificationStatus.VERIFIED if report.verdict == "verified"
        else VerificationStatus.REVIEW)
    ver.score = report.breakdown.total
    bd = dict(report.breakdown.__dict__)
    bd["findings"] = [f.__dict__ for f in report.breakdown.findings]
    ver.breakdown = bd
    ver.breakdown["total"] = report.breakdown.total
    ver.conclusion = _field_conclusion(report.breakdown.findings)
    ver.issues = [f.__dict__ for f in report.breakdown.findings
                  if f.level in ("warning", "review")]
    ver.evidence = report.evidence
    AuditService.commit(
        organization_id=ver.organization_id, action="verification.processed",
        entity_type="Verification", entity_id=ver.id,
        summary=f"Verification scored {report.breakdown.total:.0f} "
                f"({report.verdict}).")
    db.session.commit()
    return report


def run_bulk_item(item_id: str):
    from ..models.domain import ReferenceDocument

    item = ScreeningItem.query.get(item_id)
    if not item:
        return
    job = None
    asset, cleanup = _materialize(item.organization_id, item.storage_path)
    claimed = []
    ref = None
    if item.reference_id:
        ref = ReferenceDocument.query.filter_by(
            id=item.reference_id, organization_id=item.organization_id).first()
        if ref:
            claimed.append({
                "extracted_fields": ref.extracted_fields or [],
                "metadata": ref.fingerprint.get("baseline", {}) if ref.fingerprint else {},
            })

    item.status = ItemStatus.PROCESSING
    db.session.commit()
    try:
        try:
            report = _engine().run(
                [asset], claimed, item.organization_id,
                config=_org_config(item.organization_id),
                database_lookup=build_lookup(item.organization_id),
            )
        finally:
            if cleanup:
                cleanup()
        item.score = report.breakdown.total
        item.snapshot = {
            "conclusion": _field_conclusion(report.breakdown.findings),
            "issues": [f.__dict__ for f in report.breakdown.findings
                       if f.level in ("warning", "review")],
        }
        item.status = ItemStatus.VERIFIED if report.verdict == "verified" else ItemStatus.REVIEW
        item.error = None
    except Exception as exc:
        item.status = ItemStatus.FAILED
        item.error = str(exc)[:800]
    _recount_job(item.job_id)
    db.session.commit()


def _recount_job(job_id: str):
    from ..models.domain import ScreeningJob

    job = ScreeningJob.query.get(job_id)
    if not job:
        return
    items = ScreeningItem.query.filter_by(job_id=job_id).all()
    done = [i for i in items if i.status != ItemStatus.PENDING]
    job.total_count = len(items)
    job.processed_count = len(done)
    job.verified_count = sum(1 for i in done if i.status == ItemStatus.VERIFIED)
    job.review_count = sum(1 for i in done if i.status == ItemStatus.REVIEW)
    job.failed_count = sum(1 for i in done if i.status == ItemStatus.FAILED)
    if len(items) and len(done) == len(items):
        job.status = JobStatus.COMPLETED if job.failed_count == 0 else JobStatus.PARTIAL


def _ai_evidence_fields(ai_evidence) -> list:
    """Turn sanitized browser-side Transformers.js evidence into engine fields."""
    fields = []
    for item in (ai_evidence or []) or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        value = str(item.get("value") or "").strip()
        if not key or not value:
            continue
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.7))))
        except (TypeError, ValueError):
            confidence = 0.7
        fields.append(ExtractedField(
            key=key, value=value, confidence=confidence, source="browser-nlp"))
    return fields


def _org_config(org_id: str):
    from ..models.organization import Organization

    org = Organization.query.get(org_id)
    if not org:
        return {}
    return org.verification_config or {}


def _field_conclusion(findings: list) -> list:
    rows = []
    for f in findings:
        det = (f.details or {}).copy()
        det["finding"] = f.message
        rows.append({"key": f.code, "status": _finding_status(f.level), **det})
    return rows


def _finding_status(level: str) -> str:
    return {"info": "match", "warning": "partial", "review": "mismatch"}.get(level, "missing")


HANDLERS = {
    "VERIFY_DOCUMENT": run_single_verification,
    "VERIFY_BULK_ITEM": run_bulk_item,
}


def process_task(task: QueueTask) -> None:
    handler = HANDLERS.get(task.kind)
    if not handler:
        task.status = QueueState.FAILED
        task.error = f"Unknown task kind: {task.kind}"
        return
    try:
        handler(**task.payload)
        task.status = QueueState.SUCCEEDED
        task.error = None
    except Exception as exc:  # noqa: BLE001 - worker layer must not die
        db.session.rollback()
        task.error = str(exc)[:800]
        if task.attempts >= task.max_attempts:
            task.status = QueueState.FAILED
        else:
            task.status = QueueState.RETRYING
            task.run_after = utcnow() + timedelta(seconds=min(60, 5 * task.attempts))


def worker_loop(app, *, stop_event: threading.Event | None = None, poll: float | None = None):
    """One worker pass body; run in a daemon thread (blocking poll)."""
    stop = stop_event or threading.Event()
    poll_s = poll if poll is not None else app.config.get("WORKER_POLL_INTERVAL_SECONDS", 2.0)
    concurrency = app.config.get("WORKER_CONCURRENCY", 2)
    while not stop.is_set():
        with app.app_context():
            lease = app.config.get("WORKER_POLL_INTERVAL_SECONDS", 2.0) * 10
            tasks = QueueTask.claim_batch(worker="thread", limit=concurrency, lease_seconds=int(lease or 20))
            for task in tasks:
                process_task(task)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        stop.wait(poll_s)


def start_worker(app) -> threading.Thread:
    from werkzeug.serving import is_running_from_reloader

    app.worker_stop = threading.Event()
    app.worker_started = False
    t = threading.Thread(
        target=worker_loop, args=(app,), kwargs={"stop_event": app.worker_stop},
        name="verifo-worker", daemon=True)
    t.start()
    app.worker_thread = t
    return t