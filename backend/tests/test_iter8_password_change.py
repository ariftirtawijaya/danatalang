"""Iteration 8: password-change flow, lockout messages, break-glass recovery."""
import os, time, uuid, requests, pytest, subprocess
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path("/app/frontend/.env"))
load_dotenv(Path("/app/backend/.env"))
BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://utang-tracker-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

SUPER_PHONE = "081200000001"
SUPER_PASS = "Sup3rAdmin!2026"
BILLY_PHONE = "082130018893"
BILLY_TEMP = "Pk5DRIEHO5!"

STATE = {}


def _s(tok):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


def _login(phone, password, expect=200):
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": password}, timeout=20)
    assert r.status_code == expect, f"login {phone} expected {expect} got {r.status_code}: {r.text}"
    return r


def _uphone():
    # unique phone starting with 08, 11 digits
    return "089" + str(uuid.uuid4().int)[:8]


async def _mongo():
    c = AsyncIOMotorClient(MONGO_URL)
    return c[DB_NAME], c


async def _clear_attempts_for(phone):
    db, c = await _mongo()
    await db.login_attempts.delete_many({"_id": {"$regex": f":{phone}$"}})
    c.close()


def _run_async(coro):
    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def clear_attempts(phone):
    _run_async(_clear_attempts_for(phone))


@pytest.fixture(scope="module")
def super_token():
    clear_attempts(SUPER_PHONE)
    r = _login(SUPER_PHONE, SUPER_PASS)
    return r.json()["token"]


def _create_user(super_token, role):
    phone = _uphone()
    payload = {
        "full_name": f"TEST_{role}_{uuid.uuid4().hex[:6]}",
        "phone": phone,
        "email": f"test_{uuid.uuid4().hex[:8]}@example.com",
        "password": "InitPass1!",
        "role": role,
    }
    if role == "lender":
        payload.update({
            "bank_name": "BCA",
            "account_number": "1234567890",
            "account_holder": "TEST LENDER",
        })
    r = _s(super_token).post(f"{API}/users", json=payload)
    assert r.status_code == 200, r.text
    return {"id": r.json()["id"], "phone": phone, "password": "InitPass1!"}


# --- Bug fix: password change actually persists ---
class TestChangePasswordFlow:
    @pytest.mark.parametrize("role", ["admin", "lender"])
    def test_change_password_persists(self, super_token, role):
        u = _create_user(super_token, role)
        tok = _login(u["phone"], u["password"]).json()["token"]
        new_pw = "NewPass9!" + uuid.uuid4().hex[:4]
        r = _s(tok).put(f"{API}/auth/password", json={
            "current_password": u["password"], "new_password": new_pw,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True and body.get("relogin_required") is True

        # (a) old password -> 401
        r_old = requests.post(f"{API}/auth/login", json={"phone": u["phone"], "password": u["password"]})
        assert r_old.status_code == 401

        clear_attempts(u["phone"])
        # (b) new password -> 200
        r_new = _login(u["phone"], new_pw)
        assert r_new.json()["user"]["phone"] == u["phone"]

        # (c) audit log has PASSWORD_CHANGED entry for this user
        stok = super_token
        r_audit = _s(stok).get(f"{API}/audit-logs?user_id={u['id']}&action=PASSWORD_CHANGED")
        # try alternate endpoint if the above doesn't support filters
        found = False
        if r_audit.status_code == 200:
            data = r_audit.json()
            items = data if isinstance(data, list) else data.get("items", [])
            found = any(x.get("action") == "PASSWORD_CHANGED" and str(x.get("actor_id") or x.get("user_id") or "") == u["id"] for x in items)
        if not found:
            # fallback: full listing
            r2 = _s(stok).get(f"{API}/audit-logs")
            if r2.status_code == 200:
                items = r2.json() if isinstance(r2.json(), list) else r2.json().get("items", [])
                found = any(x.get("action") == "PASSWORD_CHANGED" and (u["id"] in str(x)) for x in items)
        assert found, "PASSWORD_CHANGED audit entry not found"

        # cleanup
        _s(super_token).delete(f"{API}/users/{u['id']}")

    def test_change_password_borrower(self, super_token):
        # register borrower
        phone = _uphone()
        payload = {
            "nik": str(uuid.uuid4().int)[:16],
            "full_name": f"TEST_borrower_{uuid.uuid4().hex[:6]}",
            "birth_date": "1995-01-01",
            "phone": phone,
            "email": f"b_{uuid.uuid4().hex[:8]}@example.com",
            "password": "Borrow1!X", "confirm_password": "Borrow1!X",
            "bank_name": "BCA", "account_number": "1234567890", "account_holder": "TEST BORROWER",
        }
        r = requests.post(f"{API}/auth/register", json=payload)
        assert r.status_code == 200, r.text
        tok = r.json()["token"]; uid = r.json()["user"]["id"]
        new_pw = "NewBorrow2!X"
        r = _s(tok).put(f"{API}/auth/password", json={"current_password": "Borrow1!X", "new_password": new_pw})
        assert r.status_code == 200
        # old fails, new works
        assert requests.post(f"{API}/auth/login", json={"phone": phone, "password": "Borrow1!X"}).status_code == 401
        clear_attempts(phone)
        _login(phone, new_pw)
        _s(super_token).delete(f"{API}/users/{uid}")

    def test_same_password_rejected(self, super_token):
        u = _create_user(super_token, "admin")
        tok = _login(u["phone"], u["password"]).json()["token"]
        r = _s(tok).put(f"{API}/auth/password", json={
            "current_password": u["password"], "new_password": u["password"],
        })
        assert r.status_code == 400
        assert "berbeda" in r.text.lower() or "sama" in r.text.lower()
        _s(super_token).delete(f"{API}/users/{u['id']}")


# --- Login lockout messages ---
class TestLoginLockout:
    def test_progressive_messages(self, super_token):
        u = _create_user(super_token, "admin")
        clear_attempts(u["phone"])
        # Fire up to 15 wrong attempts; behind Kubernetes ingress, request.client.host
        # is the internal proxy IP (may vary between pods), so lockout key = ip:phone
        # can split across buckets. We assert at minimum "Sisa" text appears and that
        # eventually 429 is returned within reasonable retries.
        saw_sisa = False
        saw_429 = False
        for _ in range(15):
            r = requests.post(f"{API}/auth/login", json={"phone": u["phone"], "password": "WRONG!!"})
            if r.status_code == 401 and "Sisa" in r.text:
                saw_sisa = True
            if r.status_code == 429:
                saw_429 = True
                assert "menit" in r.text.lower()
                break
        assert saw_sisa, "Expected 'Sisa N percobaan' progressive message"
        assert saw_429, "Expected 429 lockout after repeated wrong attempts (BUG: rate limiter uses proxy IP, may split buckets across ingress pods)"
        clear_attempts(u["phone"])
        _s(super_token).delete(f"{API}/users/{u['id']}")


# --- change password clears lock ---
class TestChangePasswordClearsLock:
    def test_lock_cleared(self, super_token):
        u = _create_user(super_token, "admin")
        clear_attempts(u["phone"])
        # 3 wrong attempts
        for _ in range(3):
            r = requests.post(f"{API}/auth/login", json={"phone": u["phone"], "password": "BAD!!"})
            assert r.status_code == 401
        # login correctly
        tok = _login(u["phone"], u["password"]).json()["token"]
        # change password -> should clear login_attempts
        new_pw = "Cleared9!X"
        r = _s(tok).put(f"{API}/auth/password", json={"current_password": u["password"], "new_password": new_pw})
        assert r.status_code == 200
        # verify collection cleared
        async def _count():
            db, c = await _mongo()
            n = await db.login_attempts.count_documents({"_id": {"$regex": f":{u['phone']}$"}})
            c.close()
            return n
        n = _run_async(_count())
        assert n == 0, f"login_attempts not cleared: {n}"
        # login with new password directly works
        _login(u["phone"], new_pw)
        _s(super_token).delete(f"{API}/users/{u['id']}")


# --- must_change_password gating for Billy Aldy ---
class TestBillyMustChangePassword:
    def test_billy_gated(self):
        clear_attempts(BILLY_PHONE)
        r = _login(BILLY_PHONE, BILLY_TEMP)
        j = r.json()
        assert j["user"].get("must_change_password") is True
        tok = j["token"]
        # /auth/me allowed
        assert _s(tok).get(f"{API}/auth/me").status_code == 200
        # other endpoints -> 403
        for ep in ("/dashboard", "/users", "/loans"):
            rr = _s(tok).get(f"{API}{ep}")
            assert rr.status_code == 403, f"{ep} expected 403 got {rr.status_code}"


# --- Idempotency: superadmin count stays 1 ---
class TestSuperadminIdempotent:
    def test_only_one_superadmin(self, super_token):
        async def _count():
            db, c = await _mongo()
            n = await db.users.count_documents({"role": "superadmin"})
            u = await db.users.find_one({"role": "superadmin"})
            c.close()
            return n, u
        n, u = _run_async(_count())
        assert n == 1
        assert u["phone"] == SUPER_PHONE
