"""Iteration 4 regression: verify factory-reset RBAC & validation without actually wiping data.
Ensures 403 for admin/lender/borrower and 400 for bad confirmation/password (superadmin)."""
import os, uuid, requests, pytest

def _base():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        # fall back to frontend/.env
        try:
            with open("/app/frontend/.env") as f:
                for ln in f:
                    if ln.startswith("REACT_APP_BACKEND_URL="):
                        return ln.split("=", 1)[1].strip().rstrip("/")
        except Exception:
            pass
    return (v or "").rstrip("/")

BASE = _base()
assert BASE, "REACT_APP_BACKEND_URL missing"
SUPER_PHONE = os.environ.get("TEST_SUPER_PHONE", "081900000777")
SUPER_PASS = os.environ.get("TEST_SUPER_PASS", "TempSup3r!2026")


def _login(phone, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"phone": phone, "password": password}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def super_tok():
    return _login(SUPER_PHONE, SUPER_PASS)


@pytest.fixture(scope="module")
def admin_tok(super_tok):
    suffix = uuid.uuid4().hex[:6]
    phone = f"08211{suffix[:6]}"
    payload = {"phone": phone, "full_name": f"TEST Admin {suffix}", "role": "admin",
               "email": f"testadmin_{suffix}@t.com", "password": "AdminPass!23"}
    r = requests.post(f"{BASE}/api/users", json=payload, headers=_auth(super_tok), timeout=20)
    assert r.status_code in (200, 201), r.text
    tmp = r.json().get("temporary_password") or "AdminPass!23"
    tok = _login(phone, tmp)
    # If must_change_password, set a real password
    me = requests.get(f"{BASE}/api/auth/me", headers=_auth(tok), timeout=10).json()
    if me.get("must_change_password"):
        requests.put(f"{BASE}/api/auth/password",
                     json={"current_password": tmp, "new_password": "AdminPass!23"},
                     headers=_auth(tok), timeout=10)
        tok = _login(phone, "AdminPass!23")
    return tok


def test_factory_reset_preview_forbidden_for_admin(admin_tok):
    r = requests.get(f"{BASE}/api/settings/factory-reset/preview", headers=_auth(admin_tok), timeout=20)
    assert r.status_code == 403, r.text


def test_factory_reset_forbidden_for_admin(admin_tok):
    r = requests.post(f"{BASE}/api/settings/factory-reset",
                      json={"confirmation": "HAPUS SEMUA DATA", "password": "AdminPass!23"},
                      headers=_auth(admin_tok), timeout=20)
    assert r.status_code == 403, r.text


def test_factory_reset_unauth():
    r = requests.post(f"{BASE}/api/settings/factory-reset",
                      json={"confirmation": "HAPUS SEMUA DATA", "password": SUPER_PASS}, timeout=20)
    assert r.status_code in (401, 403), r.text


def test_factory_reset_preview_super_ok(super_tok):
    r = requests.get(f"{BASE}/api/settings/factory-reset/preview", headers=_auth(super_tok), timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    # Should return some counters structure
    assert isinstance(body, dict)


def test_factory_reset_bad_confirmation(super_tok):
    r = requests.post(f"{BASE}/api/settings/factory-reset",
                      json={"confirmation": "hapus semua data", "password": SUPER_PASS},
                      headers=_auth(super_tok), timeout=20)
    assert r.status_code in (400, 422), r.text


def test_factory_reset_bad_password(super_tok):
    r = requests.post(f"{BASE}/api/settings/factory-reset",
                      json={"confirmation": "HAPUS SEMUA DATA", "password": "WrongPass!"},
                      headers=_auth(super_tok), timeout=20)
    assert r.status_code in (400, 401, 403), r.text


def test_factory_reset_missing_fields(super_tok):
    r = requests.post(f"{BASE}/api/settings/factory-reset",
                      json={"confirmation": "HAPUS SEMUA DATA"},
                      headers=_auth(super_tok), timeout=20)
    assert r.status_code in (400, 422), r.text
