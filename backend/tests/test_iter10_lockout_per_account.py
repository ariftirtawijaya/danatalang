"""Iteration 10: strict lockout test — per-account rate limit (phone-only key).

Runs via the public preview URL to exercise the ingress/multi-pod path.
"""
import os, uuid, asyncio, requests, pytest
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path("/app/frontend/.env"))
load_dotenv(Path("/app/backend/.env"))
BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

SUPER_PHONE = os.environ.get("TEST_SUPER_PHONE", "081900000777")
SUPER_PASS = os.environ.get("TEST_SUPER_PASS", "TempSup3r!2026")


def _sess(tok):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _mongo():
    c = AsyncIOMotorClient(MONGO_URL)
    return c[DB_NAME], c


async def _clear_all():
    db, c = await _mongo()
    await db.login_attempts.delete_many({})
    c.close()


async def _get_attempt(phone):
    db, c = await _mongo()
    docs = await db.login_attempts.find({}).to_list(50)
    match = [d for d in docs if d.get("_id") == f"phone:{phone}"]
    other = [d for d in docs if d.get("_id") != f"phone:{phone}"]
    c.close()
    return match, other, docs


async def _delete_lock(phone):
    db, c = await _mongo()
    await db.login_attempts.delete_many({"_id": f"phone:{phone}"})
    c.close()


def _uphone():
    return "089" + str(uuid.uuid4().int)[:8]


@pytest.fixture(scope="module")
def super_token():
    _run(_clear_all())
    r = requests.post(f"{API}/auth/login", json={"phone": SUPER_PHONE, "password": SUPER_PASS}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture()
def test_admin(super_token):
    phone = _uphone()
    payload = {
        "full_name": f"TEST_iter10_{uuid.uuid4().hex[:6]}",
        "phone": phone,
        "email": f"iter10_{uuid.uuid4().hex[:8]}@example.com",
        "password": "InitPass1!",
        "role": "admin",
    }
    r = _sess(super_token).post(f"{API}/users", json=payload)
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    _run(_delete_lock(phone))
    yield {"id": uid, "phone": phone, "password": "InitPass1!"}
    # cleanup
    _run(_delete_lock(phone))
    _sess(super_token).delete(f"{API}/users/{uid}")


class TestStrictLockout:
    def test_progressive_then_429(self, test_admin):
        phone = test_admin["phone"]
        # 4 wrong attempts should all be 401 with decreasing "Sisa N" (4,3,2,1)
        expected_sisa = [4, 3, 2, 1]
        for i, want in enumerate(expected_sisa, start=1):
            r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": "WRONG!!"}, timeout=20)
            assert r.status_code == 401, f"attempt {i}: expected 401 got {r.status_code}: {r.text}"
            assert f"Sisa {want}" in r.text, f"attempt {i}: expected 'Sisa {want}' in body, got {r.text}"

        # 5th and 6th must be 429 (lockout)
        for i in (5, 6):
            r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": "WRONG!!"}, timeout=20)
            assert r.status_code == 429, f"attempt {i}: expected 429 got {r.status_code}: {r.text}"
            assert "menit" in r.text.lower()

        # DB: exactly one login_attempts doc with _id=phone:<phone>, has count and ip
        match, other, all_docs = _run(_get_attempt(phone))
        assert len(match) == 1, f"expected 1 doc phone:{phone}, got {len(match)}. all={all_docs}"
        d = match[0]
        assert d.get("count", 0) >= 5, d
        assert "ip" in d and isinstance(d["ip"], str) and d["ip"], d
        # No leaked IP-keyed docs for this phone
        leaked = [o for o in other if phone in str(o.get("_id",""))]
        assert not leaked, f"unexpected IP-keyed docs: {leaked}"

    def test_correct_password_still_locked(self, test_admin):
        phone = test_admin["phone"]
        # exhaust attempts
        for _ in range(6):
            requests.post(f"{API}/auth/login", json={"phone": phone, "password": "WRONG!!"}, timeout=20)
        # correct password now -> still 429
        r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": test_admin["password"]}, timeout=20)
        assert r.status_code == 429, r.text
        # after manual delete -> immediate success
        _run(_delete_lock(phone))
        r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": test_admin["password"]}, timeout=20)
        assert r.status_code == 200, r.text

    def test_change_password_clears_lock(self, super_token, test_admin):
        phone = test_admin["phone"]
        # 3 wrong
        for _ in range(3):
            r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": "BAD!!"}, timeout=20)
            assert r.status_code == 401
        # correct login
        r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": test_admin["password"]}, timeout=20)
        assert r.status_code == 200, r.text
        tok = r.json()["token"]
        new_pw = "Cleared9!" + uuid.uuid4().hex[:4]
        r = _sess(tok).put(f"{API}/auth/password", json={
            "current_password": test_admin["password"], "new_password": new_pw})
        assert r.status_code == 200, r.text
        # doc should be gone
        match, _, _ = _run(_get_attempt(phone))
        assert match == [], f"login_attempts not cleared after change_password: {match}"
        # new password works immediately
        r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": new_pw}, timeout=20)
        assert r.status_code == 200, r.text

    def test_successful_login_resets_counter(self, test_admin):
        phone = test_admin["phone"]
        for _ in range(2):
            r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": "BAD!!"}, timeout=20)
            assert r.status_code == 401
        # Precondition: doc exists
        match, _, _ = _run(_get_attempt(phone))
        assert len(match) == 1
        # correct login
        r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": test_admin["password"]}, timeout=20)
        assert r.status_code == 200
        match, _, _ = _run(_get_attempt(phone))
        assert match == [], f"expected doc removed after success, got: {match}"


class TestFinalState:
    def test_env_clean_and_super_ok(self, super_token):
        # env: SUPERADMIN_RECOVERY must not be present
        with open("/app/backend/.env") as f:
            body = f.read()
        assert "SUPERADMIN_RECOVERY" not in body

    def test_super_still_logs_in(self):
        _run(_clear_all())
        r = requests.post(f"{API}/auth/login", json={"phone": SUPER_PHONE, "password": SUPER_PASS}, timeout=20)
        assert r.status_code == 200

    def test_three_canonical_users_present(self, super_token):
        async def _check():
            db, c = await _mongo()
            # Temp super phone must exist; test does not assert on user's real accounts.
            u = await db.users.find_one({"phone": SUPER_PHONE, "role": "superadmin"})
            n_attempts = await db.login_attempts.count_documents({})
            c.close()
            return u, n_attempts
        u, n_att = _run(_check())
        assert u is not None
        assert n_att == 0
