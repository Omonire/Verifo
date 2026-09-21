"""Demo sample endpoint + full (SEED_SAMPLE=1) seeding behaviour."""


def _login(client, auth):
    auth("demoorg", "admin@demo.edu")
    data = client.post(
        "/api/v1/auth/login", json={"email": "admin@demo.edu", "password": "password123"}
    ).get_json()
    return data["token"]


def test_demo_sample_genuine_returns_pdf(client, auth, bearer):
    token = _login(client, auth)
    resp = client.get("/api/v1/demo/sample?kind=transcript-genuine", headers=bearer(token))
    assert resp.status_code == 200, resp.data[:200]
    assert resp.mimetype == "application/pdf"
    assert resp.data[:4] == b"%PDF"


def test_demo_sample_counterfeit_rewrites_producer(client, auth, bearer):
    token = _login(client, auth)
    resp = client.get(
        "/api/v1/demo/sample?kind=transcript-counterfeit", headers=bearer(token)
    )
    assert resp.status_code == 200, resp.data[:200]
    assert b"CamScanner-Mobile" in resp.data


def test_demo_sample_unknown_kind_404(client, auth, bearer):
    token = _login(client, auth)
    resp = client.get("/api/v1/demo/sample?kind=nope", headers=bearer(token))
    assert resp.status_code == 404


def test_demo_sample_requires_auth(client):
    assert client.get("/api/v1/demo/sample").status_code in (401, 403)


def test_references_page_renders_demo_samples(client, auth, bearer):
    token = _login(client, auth)
    resp = client.get("/references", headers=bearer(token))
    assert resp.status_code == 200
    assert "Demo samples" in resp.get_data(as_text=True)
    assert 'data-sample="transcript-counterfeit"' in resp.get_data(as_text=True)


def test_full_seed_registers_references(app, monkeypatch):
    """SEED_SAMPLE=1 seeds document types AND library references."""
    monkeypatch.setenv("VERIFO_DEMO_ADMIN_EMAIL", "admin@demo.edu")
    monkeypatch.setenv("VERIFO_DEMO_ADMIN_PASSWORD", "verifo-demo-admin")
    from app.models.domain import ReferenceDocument
    from app.extensions import db
    from seed_demo import run_seed

    with app.app_context():
        result = run_seed(sample=True)
        assert result["mode"] == "sample"

        refs = ReferenceDocument.query.all()
        assert len(refs) == 2, [r.ref_code for r in refs]
        assert {r.ref_code for r in refs} == {"DEMO-TRANSCRIPT_2026", "DEMO-ADMISSION_2026"}
        assert all((r.extracted_fields or []) for r in refs)
        assert all(r.status.value == "ACTIVE" for r in refs)