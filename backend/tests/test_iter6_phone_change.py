"""Iteration 6 - Superadmin can change own login phone; seed idempotent."""
import os
import time
import subprocess
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "https://utang-tracker-3.preview.emergentagent.com"
API = f"{BASE_URL}/api"

SUPER_PHONE = "081200000001"
SUPER_PASS = "Sup3rAdmin!2026"
NEW_PHONE = "081299990001"
OTHER_PHONE = "081299990099"

# Load MONGO env from backend/.env for direct db checks
def _load_env():
    env = {}
    with open("/app/backend/.env") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"')
    return env

_ENV = _load_env()
MONGO_URL = _ENV["MONGO_URL"]
DB_NAME = _ENV["DB_NAME"]


def _login(phone, password):
    return requests.post(f"{API}/auth/login", json={"phone": phone, "password": password}, timeout=15)


@pytest.fixture(scope="module")
def super_token():
    r = _login(SUPER_PHONE, SUPER_PASS)
    assert r.status_code == 200, f"Superadmin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def super_headers(super_token):
    return {"Authorization": f"Bearer {super_token}"}


def _put_profile(headers, body):
    return requests.put(f"{API}/auth/profile", json=body, headers=headers, timeout=15)


def _get_db_phone():
    async def run():
        client = AsyncIOMotorClient(MONGO_URL)
        u = await client[DB_NAME].users.find_one({"role": "superadmin"})
        client.close()
        return u.get("phone") if u else None
    return asyncio.get_event_loop().run_until_complete(run()) if False else asyncio.run(run())


def _count_superadmins():
    async def run():
        client = AsyncIOMotorClient(MONGO_URL)
        c = await client[DB_NAME].users.count_documents({"role": "superadmin"})
        client.close()
        return c
    return asyncio.run(run())


def _get_super_hash():
    async def run():
        client = AsyncIOMotorClient(MONGO_URL)
        u = await client[DB_NAME].users.find_one({"role": "superadmin"})
        client.close()
        return u.get("password_hash") if u else None
    return asyncio.run(run())


def _find_audit(actions, limit=50):
    async def run():
        client = AsyncIOMotorClient(MONGO_URL)
        cur = client[DB_NAME].audit_logs.find({"action": {"$in": actions}}).sort("created_at", -1).limit(limit)
        out = [d async for d in cur]
        client.close()
        return out
    return asyncio.run(run())


# ---------- Security negative tests (run first, ensure db unchanged) ----------

def test_change_phone_without_password(super_headers):
    r = _put_profile(super_headers, {"phone": NEW_PHONE})
    assert r.status_code == 400, r.text
    assert _get_db_phone() == SUPER_PHONE


def test_change_phone_wrong_password(super_headers):
    r = _put_profile(super_headers, {"phone": NEW_PHONE, "current_password": "wrong"})
    assert r.status_code == 400
    assert _get_db_phone() == SUPER_PHONE


def test_change_phone_invalid_format(super_headers):
    r = _put_profile(super_headers, {"phone": "123", "current_password": SUPER_PASS})
    assert r.status_code == 400
    assert _get_db_phone() == SUPER_PHONE


# ---------- Create Admin to test uniqueness & RBAC ----------

@pytest.fixture(scope="module")
def admin_account(super_headers):
    # Create an Admin via /api/users
    body = {
        "role": "admin",
        "full_name": "TEST_Admin_Iter6",
        "phone": OTHER_PHONE,
        "email": "test_admin_iter6@pinjamku.app",
        "password": "AdminIter6!23",
    }
    r = requests.post(f"{API}/users", json=body, headers=super_headers, timeout=15)
    assert r.status_code in (200, 201), r.text
    admin = r.json()
    yield {"phone": OTHER_PHONE, "password": "AdminIter6!23", "id": admin.get("id") or admin.get("_id")}
    # cleanup
    if admin.get("id") or admin.get("_id"):
        aid = admin.get("id") or admin.get("_id")
        try:
            requests.delete(f"{API}/users/{aid}", headers=super_headers, timeout=15)
        except Exception:
            pass


def test_change_phone_conflict(super_headers, admin_account):
    r = _put_profile(super_headers, {"phone": OTHER_PHONE, "current_password": SUPER_PASS})
    assert r.status_code == 400
    assert _get_db_phone() == SUPER_PHONE


# ---------- Positive change + normalization ----------

def test_change_phone_normalized_plus62(super_headers):
    r = _put_profile(super_headers, {"phone": "+62" + NEW_PHONE[1:], "current_password": SUPER_PASS})
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == NEW_PHONE
    assert _get_db_phone() == NEW_PHONE

    # Old phone must not login
    assert _login(SUPER_PHONE, SUPER_PASS).status_code == 401
    # New phone must login, with equivalent formats
    for p in [NEW_PHONE, "62" + NEW_PHONE[1:], "+62" + NEW_PHONE[1:], "00" + NEW_PHONE[1:]]:
        assert _login(p, SUPER_PASS).status_code == 200, f"login failed with {p}"


def test_audit_log_phone_change():
    logs = _find_audit(["LOGIN_PHONE_CHANGED", "PROFILE_UPDATED"], limit=10)
    actions = [l.get("action") for l in logs]
    assert "LOGIN_PHONE_CHANGED" in actions
    assert "PROFILE_UPDATED" in actions
    lc_all = [l for l in logs if l["action"] == "LOGIN_PHONE_CHANGED"]
    # Find the audit for the SUPER_PHONE -> NEW_PHONE change (order-independent)
    lc = next((l for l in lc_all if (l.get("old_value") or {}).get("phone") == SUPER_PHONE and (l.get("new_value") or {}).get("phone") == NEW_PHONE), None)
    assert lc is not None, f"no LOGIN_PHONE_CHANGED audit from {SUPER_PHONE} to {NEW_PHONE} found; got {lc_all}"
    before = lc.get("old_value") or {}
    after = lc.get("new_value") or {}
    assert before.get("phone") == SUPER_PHONE
    assert after.get("phone") == NEW_PHONE


# ---------- Factory reset keeper preview ----------

def test_factory_reset_preview_keeper_follows_current_super():
    # Re-login with new phone
    r = _login(NEW_PHONE, SUPER_PASS)
    assert r.status_code == 200
    tok = r.json()["token"]
    r = requests.get(f"{API}/settings/factory-reset/preview", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200
    keeper = r.json().get("keeper") or {}
    assert keeper.get("phone") == NEW_PHONE


# ---------- Seed idempotency across restart ----------

def test_seed_does_not_overwrite_after_restart():
    hash_before = _get_super_hash()
    count_before = _count_superadmins()
    assert count_before == 1

    subprocess.run(["sudo", "supervisorctl", "restart", "backend"], check=True, capture_output=True)
    # wait for readiness
    for _ in range(30):
        try:
            h = requests.get(f"{API}/auth/me", timeout=5)
            if h.status_code in (401, 403, 200):
                break
        except Exception:
            pass
        time.sleep(1)
    time.sleep(2)

    count_after = _count_superadmins()
    hash_after = _get_super_hash()
    assert count_after == 1, "seed created a second superadmin"
    assert hash_before == hash_after, "seed overwrote superadmin password"
    assert _get_db_phone() == NEW_PHONE

    # Superadmin can still login with new phone
    r = _login(NEW_PHONE, SUPER_PASS)
    assert r.status_code == 200


# ---------- RBAC: other roles cannot change phone ----------

@pytest.fixture(scope="module")
def lender_account(super_headers):
    body = {
        "role": "lender",
        "full_name": "TEST_Lender_Iter6",
        "phone": "081299990002",
        "email": "test_lender_iter6@pinjamku.app",
        "password": "LenderIter6!23",
        "bank_name": "BCA",
        "account_number": "1234567890",
        "account_holder": "TEST LENDER",
    }
    r = requests.post(f"{API}/users", json=body, headers=super_headers, timeout=15)
    assert r.status_code in (200, 201), r.text
    aid = r.json().get("id") or r.json().get("_id")
    yield {"phone": "081299990002", "password": "LenderIter6!23", "id": aid}
    if aid:
        try:
            requests.delete(f"{API}/users/{aid}", headers=super_headers, timeout=15)
        except Exception:
            pass


def test_admin_cannot_change_phone(admin_account):
    r = _login(admin_account["phone"], admin_account["password"])
    assert r.status_code == 200
    tok = r.json()["token"]
    orig_phone = admin_account["phone"]
    r = requests.put(f"{API}/auth/profile", json={"phone": "081200005555", "current_password": admin_account["password"]}, headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 403
    # phone unchanged
    me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
    assert me["phone"] == orig_phone
    # Non-phone updates still allowed
    r = requests.put(f"{API}/auth/profile", json={"full_name": "TEST_Admin_Iter6_Renamed"}, headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200


def test_lender_cannot_change_phone(lender_account):
    r = _login(lender_account["phone"], lender_account["password"])
    assert r.status_code == 200
    tok = r.json()["token"]
    r = requests.put(f"{API}/auth/profile", json={"phone": "081200006666", "current_password": lender_account["password"]}, headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 403
    # can still update bank
    r = requests.put(f"{API}/auth/profile", json={"account_holder": "TEST LENDER RENAMED"}, headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200


# ---------- Restore superadmin phone at the end (CRITICAL) ----------

def test_zz_restore_super_phone():
    tok = _login(NEW_PHONE, SUPER_PASS).json()["token"]
    r = requests.put(f"{API}/auth/profile", json={"phone": SUPER_PHONE, "current_password": SUPER_PASS}, headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200, r.text
    assert _get_db_phone() == SUPER_PHONE
    # can login again with original
    assert _login(SUPER_PHONE, SUPER_PASS).status_code == 200
