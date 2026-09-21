"""Demo sample documents (Phase 9): deterministic, on-demand fixtures.

Concern: any logged-in member can download the walkthrough sample PDFs,
so they can upload a genuine and a counterfeit copy and watch the pipeline
handle both. The "counterfeits" are clearly titled demo documents and are
never presented as real records.
"""
import io

from flask import Blueprint, request, send_file

from ...auth import require_org, roles_required
from ...models.common import RoleCode
from ...services.demo import (
    ADMISSION_GENUINE,
    COUNTERFEIT_ADMISSION,
    COUNTERFEIT_TRANSCRIPT,
    TRANSCRIPT_GENUINE,
    make_counterfeit,
    render_admission_pdf,
    render_transcript_pdf,
)
from ...utils.response import api_error

demo_bp = Blueprint("demo", __name__)

_KINDS = {
    "transcript-genuine": (
        "demo-transcript-genuine.pdf",
        lambda: render_transcript_pdf(TRANSCRIPT_GENUINE),
    ),
    "transcript-counterfeit": (
        "demo-transcript-counterfeit.pdf",
        lambda: make_counterfeit("transcript", COUNTERFEIT_TRANSCRIPT),
    ),
    "admission-genuine": (
        "demo-admission-genuine.pdf",
        lambda: render_admission_pdf(ADMISSION_GENUINE),
    ),
    "admission-counterfeit": (
        "demo-admission-counterfeit.pdf",
        lambda: make_counterfeit("admission", COUNTERFEIT_ADMISSION),
    ),
}


@demo_bp.get("/sample")
@roles_required(RoleCode.ADMIN.value, RoleCode.OPERATOR.value, RoleCode.SUBMITTER.value)
def sample_document():
    require_org()
    kind = request.args.get("kind", "transcript-genuine")
    entry = _KINDS.get(kind)
    if not entry:
        return api_error("NOT_FOUND", f"Unknown demo kind '{kind}'.", status=404)
    filename, render = entry
    data = render()
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
        max_age=0,
    )