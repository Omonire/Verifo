"""Demo fixture generation (Phase 9): genuine reference PDFs + controlled
counterfeits for the walkthrough. 

Honesty rule: the "counterfeits" are generated in-process, deterministically,
and marked as demo fixtures. They are never presented as real documents.
"""
import io
from dataclasses import dataclass

import fitz
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, PageTemplate, Paragraph, SimpleDocTemplate


@dataclass
class DemoRecord:
    name: str
    matric: str
    programme: str
    cgpa: str
    session: str
    level: str
    dob: str
    title: str


TRANSCRIPT_GENUINE = DemoRecord(
    name="Adaeze Okafor", matric="19/52HJ021", programme="B.Sc. Computer Science",
    cgpa="4.52", session="2022/2023", level="400L", dob="14/03/2001",
    title="Academic Transcript — 2026",
)

ADMISSION_GENUINE = DemoRecord(
    name="Adaeze Okafor", matric="19/52HJ021", programme="B.Sc. Computer Science",
    cgpa="", session="2019/2020", level="100L", dob="14/03/2001",
    title="Admission Letter — 2026",
)

COUNTERFEIT_TRANSCRIPT = DemoRecord(
    name="Adaeze Okafor", matric="19/52HJ021", programme="B.Sc. Computer Science",
    cgpa="4.88", session="2022/2023", level="400L", dob="14/03/2001",
    title="Counterfeit Transcript (demo)",
)

COUNTERFEIT_ADMISSION = DemoRecord(
    name="Adaeze Okafor", matric="19/52HJ021", programme="B.Sc. Computer Science",
    cgpa="", session="2019/2020", level="100L", dob="14/03/2001",
    title="Counterfeit Admission (demo)",
)


def render_transcript_pdf(record: DemoRecord, *, filename="demo-transcript.pdf") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=record.title, author="Verifo Demo",
        creator="VerifoDemoDocumentService",
        producer="ReportLab Demo",

    )
    styles = getSampleStyleSheet()
    sub = ParagraphStyle(
        "sub", parent=styles["Normal"], fontSize=9, textColor=colors.grey,
        spaceAfter=8 * mm,
    )
    body = ParagraphStyle(
        "body", parent=styles["Normal"], fontSize=10.5, leading=15, spaceAfter=5,
    )
    right = ParagraphStyle(
        "right", parent=body, alignment=TA_RIGHT, spaceAfter=10,
    )
    course = ParagraphStyle("course", parent=body, alignment=TA_CENTER)

    story = [
        Paragraph("DEMO UNIVERSITY OF TECHNOLOGY", styles["Title"]),
        Paragraph("Office of the Registrar — Academic Records", sub),
        Paragraph(record.title, styles["Heading2"]),
        Paragraph(f"Matric No: {record.matric}", right),
        Paragraph(f"Student Name: {record.name}", right),
        Paragraph(f"Programme: {record.programme}", right),
        Paragraph(f"Level: {record.level}   Session: {record.session}   DOB: {record.dob}", right),
        Paragraph("<br/>COURSEWORK RESULTS", styles["Heading3"]),
    ]
    courses = [
        ("CSC401 — Data Structures & Algorithms", "A", 4),
        ("CSC403 — Operating Systems", "A", 4),
        ("CSC405 — Compiler Construction", "B", 3),
        ("CSC407 — Software Engineering", "A", 4),
        ("CSC409 — Computer Networks", "B", 3),
        ("MTH407 — Numerical Methods", "A", 3),
    ]
    for name, grade, units in courses:
        story.append(Paragraph(
            f"Course: {name} &nbsp;&nbsp; Grade: <b>{grade}</b> &nbsp;&nbsp; Units: {units}",
            course))
    if record.cgpa:
        story.append(Paragraph(
            f"<br/><b>Cumulative Grade Point Average (CGPA): {record.cgpa} / 5.00</b>",
            ParagraphStyle("cgpa", parent=body, fontSize=12, spaceBefore=6)))
    story.append(Paragraph(
        f"<br/><font size=8>This is a machine-generated demo document for the Verifo "
        f"walkthrough. It is not an official record.</font>", sub))
    doc.build(story)
    return buf.getvalue()


def render_admission_pdf(record: DemoRecord, *, filename="demo-admission.pdf") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(record.title)
    c.setAuthor("Verifo Demo")
    c.setCreator("VerifoDemoDocumentService")
    c.setProducer("ReportLab Demo")
    w, h = A4
    c.setFont("Helvetica-Bold", 17)
    c.drawCentredString(w / 2, h - 60, "DEMO UNIVERSITY OF TECHNOLOGY")
    c.setFont("Helvetica", 11)
    c.drawCentredString(w / 2, h - 78, "Office of Admissions")
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(w / 2, h - 110, record.title)
    c.setFont("Helvetica", 11)
    left = 70
    lines = [
        ("Name:", record.name),
        ("Matric No:", record.matric),
        ("Programme:", record.programme),
        ("Session:", record.session),
        ("Level:", record.level),
        ("Date of Birth:", record.dob),
    ]
    y = h - 160
    for label, value in lines:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(left, y, label)
        c.setFont("Helvetica", 11)
        c.drawString(left + 120, y, value)
        y -= 30
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.grey)
    c.drawString(left, 40, "Machine-generated demo document for the Verifo walkthrough. Not official.")
    c.showPage()
    c.save()
    return buf.getvalue()


def render_certificate_pdf(record: DemoRecord, *, filename="demo-certificate.pdf") -> bytes:
    return render_transcript_pdf(record, filename=filename)


def make_counterfeit(kind: str, record: DemoRecord) -> bytes:
    """Render the same layout as a counterfeit: altered details + a
    photocopier-style producer, so both field comparison and integrity
    produce divergent-but-honest signals."""
    data = render_for_kind(kind, record)
    with fitz.open(stream=data, filetype="pdf") as doc:
        doc.set_metadata({
            "producer": "CamScanner-Mobile", "creator": "Scanner-Plus v4.2",
        })
        data = doc.tobytes()
    return data


def render_for_kind(kind: str, record: DemoRecord) -> bytes:
    if kind == "admission":
        return render_admission_pdf(record)
    if kind == "certificate":
        return render_certificate_pdf(record)
    return render_transcript_pdf(record)