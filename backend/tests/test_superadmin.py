"""Superadmin platform console: bootstrap token swap, settings, orgs, users."""


def _register_admin(client, auth):
    data = auth("acmeu", "admin@acme-u.edu")
    return data["token"]


def _existing_org() -> str:
    """Org created by the auth fixture, for membership assertions."""
    return "acmeu"


def _make_superadmin(app, client, auth):
    """Accept a workspace ADMIN and promote them to platform superadmin
    (the realistic demo path: admin@demo.edu is both)."""
    token = _register_admin(client, auth)
    with app.app_context():
        from app.extensions import db
        from app.models.user import User

        user = User.query.filter_by(email="admin@acme-u.edu").first()
        assert user is not None
        user.is_superadmin = True
        db.session.commit()
    return token


def _org_less_superadmin(app, client):
    """Standalone superadmin with no org membership at all."""
    with app.app_context():
        from app.extensions import db
        from app.models.user import User
        from app.repositories.index import UserRepository

        user = UserRepository().create_user("owner@platform.io", "Platform Owner", "verifo-platform-99")
        user.is_superadmin = True
        db.session.commit()
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@platform.io", "password": "verifo-platform-99"},
    )
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _platform_token(client, bearer, token):
    resp = client.get("/api/v1/superadmin/bootstrap", headers=bearer(token))
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["token"]


def test_bootstrap_exchanges_org_token_for_platform_token(app, client, auth, bearer):
    token = _make_superadmin(app, client, auth)
    plat = _platform_token(client, bearer, token)
    import jwt as _jwt

    decoded = _jwt.decode(plat, options={"verify_signature": False})
    assert decoded["role"] == "SUPERADMIN"
    assert "org" not in decoded


def test_org_less_superadmin_can_login(app, client):
    body = _org_less_superadmin(app, client)
    assert body.get("role") == "SUPERADMIN"
    import jwt as _jwt

    decoded = _jwt.decode(body["token"], options={"verify_signature": False})
    assert "org" not in decoded


def test_bootstrap_rejects_non_superadmin(client, auth, bearer):
    token = _register_admin(client, auth)
    resp = client.get("/api/v1/superadmin/bootstrap", headers=bearer(token))
    assert resp.status_code == 403


def test_bootstrap_requires_auth(client):
    assert client.get("/api/v1/superadmin/bootstrap").status_code in (401, 403)


def test_settings_get_and_update(app, client, auth, bearer):
    plat = _platform_token(client, bearer, _make_superadmin(app, client, auth))
    resp = client.get("/api/v1/superadmin/settings", headers=bearer(plat))
    assert resp.status_code == 200
    body = resp.get_json()["settings"]
    assert body["site_name"] == "Verifo"
    assert body["registration_open"] is True
    assert body["demo_mode"] is False

    resp = client.put(
        "/api/v1/superadmin/settings",
        headers=bearer(plat),
        json={"site_name": "ACMEPort", "registration_open": False, "announcement": "Maintenance on Sunday"},
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["settings"]["site_name"] == "ACMEPort"

    resp = client.get("/api/v1/superadmin/settings", headers=bearer(plat))
    assert resp.get_json()["settings"]["site_name"] == "ACMEPort"
    assert resp.get_json()["settings"]["registration_open"] is False


def test_settings_reject_unknown_key(app, client, auth, bearer):
    plat = _platform_token(client, bearer, _make_superadmin(app, client, auth))
    resp = client.put(
        "/api/v1/superadmin/settings", headers=bearer(plat), json={"haxx": "uh oh"}
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "INVALID_INPUT"


def test_registration_gate_blocks_self_serve(app, client, auth, bearer):
    plat = _platform_token(client, bearer, _make_superadmin(app, client, auth))
    resp = client.put(
        "/api/v1/superadmin/settings", headers=bearer(plat), json={"registration_open": False}
    )
    assert resp.status_code == 200
    resp = client.post(
        "/api/v1/auth/register",
        json={"org_name": "Blocked Inc", "org_slug": "blocked", "email": "n@b.com", "password": "password123"},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"]["code"] == "REGISTRATION_CLOSED"


def test_regular_admin_cannot_use_superadmin_api(client, auth, bearer):
    token = _register_admin(client, auth)
    resp = client.put(
        "/api/v1/superadmin/settings",
        headers=bearer(token),
        json={"site_name": "Hacked"},
    )
    assert resp.status_code in (403, 401)


def test_org_list_and_create(app, client, auth, bearer):
    plat = _platform_token(client, bearer, _make_superadmin(app, client, auth))

    resp = client.get("/api/v1/superadmin/organizations", headers=bearer(plat))
    assert resp.status_code == 200
    slugs = [o["slug"] for o in resp.get_json()["organizations"]]
    assert _existing_org() in slugs

    resp = client.post(
        "/api/v1/superadmin/organizations",
        headers=bearer(plat),
        json={"name": "Riverside College", "slug": "riverside"},
    )
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["organization"]["slug"] == "riverside"

    resp = client.post(
        "/api/v1/superadmin/organizations",
        headers=bearer(plat),
        json={"name": "Duplicate", "slug": "acmeu"},
    )
    assert resp.status_code == 400


def test_org_status_change(app, client, auth, bearer):
    plat = _platform_token(client, bearer, _make_superadmin(app, client, auth))
    resp = client.get("/api/v1/superadmin/organizations", headers=bearer(plat))
    assert resp.status_code == 200, resp.get_json()
    org_id = next(o["id"] for o in resp.get_json()["organizations"] if o["slug"] == "acmeu")

    resp = client.post(
        "/api/v1/superadmin/organizations/%s/status" % org_id,
        headers=bearer(plat),
        json={"status": "SUSPENDED"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["organization"]["status"] == "SUSPENDED"


def test_users_list_shows_memberships(app, client, auth, bearer):
    plat = _platform_token(client, bearer, _make_superadmin(app, client, auth))
    resp = client.get("/api/v1/superadmin/users", headers=bearer(plat))
    assert resp.status_code == 200
    users = {u["email"]: u for u in resp.get_json()["users"]}
    assert "admin@acme-u.edu" in users
    assert any(
        m["organization_name"] == "acmeu".title() and m["role"] == "ADMIN"
        for m in users["admin@acme-u.edu"]["memberships"]
    )


def test_user_status_and_promotion(app, client, auth, bearer):
    plat = _platform_token(client, bearer, _make_superadmin(app, client, auth))
    auth("secondu", "second@univ.edu")  # distinct user to promote/demote/suspend
    users = client.get("/api/v1/superadmin/users", headers=bearer(plat)).get_json()["users"]
    target = next(u for u in users if u["email"] == "second@univ.edu")

    resp = client.post(
        "/api/v1/superadmin/users/%s/superadmin" % target["id"],
        headers=bearer(plat),
        json={"is_superadmin": True},
    )
    assert resp.status_code == 200
    assert resp.get_json()["user"]["is_superadmin"] is True

    resp = client.post(
        "/api/v1/superadmin/users/%s/status" % target["id"],
        headers=bearer(plat),
        json={"status": "SUSPENDED"},
    )
    assert resp.status_code == 400  # superadmins must be demoted before suspension

    resp = client.post(
        "/api/v1/superadmin/users/%s/superadmin" % target["id"],
        headers=bearer(plat),
        json={"is_superadmin": False},
    )
    assert resp.status_code == 200
    resp = client.post(
        "/api/v1/superadmin/users/%s/status" % target["id"],
        headers=bearer(plat),
        json={"status": "SUSPENDED"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["user"]["status"] == "SUSPENDED"


def test_superadmin_page_renders_for_superadmin(app, client, auth, bearer):
    token = _make_superadmin(app, client, auth)
    resp = client.get("/superadmin", headers=bearer(token))
    assert resp.status_code == 200
    assert b"Superadmin console" in resp.data


def test_superadmin_page_redirects_non_superadmin(client, auth, bearer):
    token = _register_admin(client, auth)
    resp = client.get("/superadmin", headers=bearer(token))
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]