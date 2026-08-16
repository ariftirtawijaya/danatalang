"""Iteration 2 tests: phone normalization, superadmin payment override,
password reset with must_change_password gating, object storage & file ACL."""
import os
import io
import time
import uuid
import random
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://utang-tracker-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
SUPER_PHONE = os.environ.get("TEST_SUPER_PHONE", "081900000777")
SUPER_PASS = os.environ.get("TEST_SUPER_PASS", "TempSup3r!2026")

STATE = {}


def _rand(n=9):
    return "".join(str(random.randint(0, 9)) for _ in range(n))


def _uphone():
    return "0812" + _rand(8)


def _login(phone, password, expect=200):
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": password}, timeout=20)
    assert r.status_code == expect, f"login {phone} -> {r.status_code} {r.text}"
    return r.json() if r.status_code == 200 else None


def _s(tok=None):
    s = requests.Session()
    if tok:
        s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


def _png():
    return bytes.fromhex(
        "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
        "0000000A49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
    )


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def super_token():
    j = _login(SUPER_PHONE, SUPER_PASS)
    return j["token"]


# ============== 1. PHONE NORMALIZATION ==============
class TestPhoneNormalization:
    def test_super_login_08_format(self):
        assert _login(SUPER_PHONE, SUPER_PASS)["user"]["phone"] == SUPER_PHONE

    def test_super_login_62_format(self):
        p62 = "62" + SUPER_PHONE[1:]
        assert _login(p62, SUPER_PASS)["user"]["phone"] == SUPER_PHONE

    def test_super_login_plus62_format(self):
        p = "+62" + SUPER_PHONE[1:]
        assert _login(p, SUPER_PASS)["user"]["phone"] == SUPER_PHONE

    def test_super_login_0062_format(self):
        p = "0062" + SUPER_PHONE[1:]
        assert _login(p, SUPER_PASS)["user"]["phone"] == SUPER_PHONE

    def test_register_dup_phone_via_diff_format(self, super_token):
        # register borrower with +62 format
        phone_08 = _uphone()
        phone_plus = "+62" + phone_08[1:]
        nik1 = _rand(16)
        email1 = f"n1_{uuid.uuid4().hex[:6]}@t.com"
        r = requests.post(f"{API}/auth/register", json={
            "nik": nik1, "full_name": "TEST Norm", "birth_date": "1995-01-01",
            "phone": phone_plus, "email": email1,
            "password": "Passw0rd!", "confirm_password": "Passw0rd!",
            "bank_name": "BCA", "account_number": "1122334455", "account_holder": "TEST",
        })
        assert r.status_code == 200, r.text
        # duplicate register with 08 format -> should reject
        r2 = requests.post(f"{API}/auth/register", json={
            "nik": _rand(16), "full_name": "TEST Norm2", "birth_date": "1995-01-01",
            "phone": phone_08, "email": f"n2_{uuid.uuid4().hex[:6]}@t.com",
            "password": "Passw0rd!", "confirm_password": "Passw0rd!",
            "bank_name": "BCA", "account_number": "1122334455", "account_holder": "TEST",
        })
        assert r2.status_code == 400, r2.text

    def test_create_lender_with_62_format_stored_as_08(self, super_token):
        digits = _rand(8)
        phone_08 = "0812" + digits
        phone_62 = "62812" + digits
        r = _s(super_token).post(f"{API}/users", json={
            "full_name": "TEST Lender Norm", "phone": phone_62,
            "email": f"ln_{uuid.uuid4().hex[:6]}@t.com",
            "password": "LenderX1!", "role": "lender",
            "bank_name": "BCA", "account_number": "1234567890", "account_holder": "TEST",
        })
        assert r.status_code == 200, r.text
        assert r.json()["phone"] == phone_08


# ============== 2. RESET PASSWORD ==============
class TestResetPassword:
    def test_setup_users(self, super_token):
        s = _s(super_token)
        # create admin, lender, and register a borrower
        admin_phone = _uphone()
        r = s.post(f"{API}/users", json={
            "full_name": "TEST RP Admin", "phone": admin_phone,
            "email": f"rpa_{uuid.uuid4().hex[:6]}@t.com",
            "password": "AdminPass1!", "role": "admin",
        })
        assert r.status_code == 200
        STATE["admin"] = {"phone": admin_phone, "password": "AdminPass1!", "id": r.json()["id"]}
        STATE["admin"]["token"] = _login(admin_phone, "AdminPass1!")["token"]

        lender_phone = _uphone()
        r = s.post(f"{API}/users", json={
            "full_name": "TEST RP Lender", "phone": lender_phone,
            "email": f"rpl_{uuid.uuid4().hex[:6]}@t.com",
            "password": "LenderPass1!", "role": "lender",
            "bank_name": "BCA", "account_number": "9988776655", "account_holder": "TEST",
        })
        assert r.status_code == 200
        STATE["lender"] = {"phone": lender_phone, "password": "LenderPass1!", "id": r.json()["id"]}
        STATE["lender"]["token"] = _login(lender_phone, "LenderPass1!")["token"]

        # borrower via register
        b_phone = _uphone()
        r = requests.post(f"{API}/auth/register", json={
            "nik": _rand(16), "full_name": "TEST RP Borr", "birth_date": "1995-01-01",
            "phone": b_phone, "email": f"rpb_{uuid.uuid4().hex[:6]}@t.com",
            "password": "Borrower1!", "confirm_password": "Borrower1!",
            "bank_name": "BCA", "account_number": "1122334455", "account_holder": "TEST",
        })
        assert r.status_code == 200
        STATE["borrower"] = {"phone": b_phone, "password": "Borrower1!", "id": r.json()["user"]["id"], "token": r.json()["token"]}

    def test_super_reset_borrower_and_gate(self, super_token):
        bid = STATE["borrower"]["id"]
        r = _s(super_token).post(f"{API}/users/{bid}/reset-password")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["must_change_password"] is True
        assert isinstance(j["temporary_password"], str) and len(j["temporary_password"]) >= 8
        STATE["borrower"]["temp"] = j["temporary_password"]

    def test_login_with_temp_then_forced_gate(self):
        j = _login(STATE["borrower"]["phone"], STATE["borrower"]["temp"])
        tok = j["token"]
        STATE["borrower"]["temp_token"] = tok
        s = _s(tok)
        # allowed endpoints
        r = s.get(f"{API}/auth/me")
        assert r.status_code == 200
        assert r.json()["must_change_password"] is True
        # blocked endpoints
        assert s.get(f"{API}/dashboard").status_code == 403
        assert s.get(f"{API}/loans").status_code == 403
        assert s.post(f"{API}/loans", json={"principal_amount": 100000, "duration_days": 5}).status_code == 403

    def test_change_password_clears_flag(self):
        tok = STATE["borrower"]["temp_token"]
        new_pw = "NewBorrower1!"
        r = _s(tok).put(f"{API}/auth/password", json={
            "current_password": STATE["borrower"]["temp"],
            "new_password": new_pw,
        })
        assert r.status_code == 200, r.text
        STATE["borrower"]["password"] = new_pw
        # login again fresh
        j = _login(STATE["borrower"]["phone"], new_pw)
        assert j["user"].get("must_change_password") in (False, None)
        tok2 = j["token"]
        STATE["borrower"]["token"] = tok2
        # now normal endpoints work
        r = _s(tok2).get(f"{API}/auth/me")
        assert r.status_code == 200
        assert r.json()["must_change_password"] is False
        assert _s(tok2).get(f"{API}/dashboard").status_code == 200

    def test_admin_can_reset_borrower_only(self):
        atok = STATE["admin"]["token"]
        # borrower ok
        r = _s(atok).post(f"{API}/users/{STATE['borrower']['id']}/reset-password")
        assert r.status_code == 200
        # restore borrower
        temp = r.json()["temporary_password"]
        tt = _login(STATE["borrower"]["phone"], temp)["token"]
        _s(tt).put(f"{API}/auth/password", json={"current_password": temp, "new_password": STATE["borrower"]["password"]})
        # lender forbidden
        r = _s(atok).post(f"{API}/users/{STATE['lender']['id']}/reset-password")
        assert r.status_code == 403, r.text

    def test_admin_cannot_reset_another_admin(self, super_token):
        # create another admin
        s = _s(super_token)
        aphone = _uphone()
        r = s.post(f"{API}/users", json={
            "full_name": "TEST Admin2", "phone": aphone,
            "email": f"a2_{uuid.uuid4().hex[:6]}@t.com",
            "password": "AdminPass1!", "role": "admin",
        })
        assert r.status_code == 200
        aid2 = r.json()["id"]
        # admin1 tries to reset admin2 -> 403
        r = _s(STATE["admin"]["token"]).post(f"{API}/users/{aid2}/reset-password")
        assert r.status_code == 403

    def test_super_cannot_reset_self(self, super_token):
        me = _s(super_token).get(f"{API}/auth/me").json()
        r = _s(super_token).post(f"{API}/users/{me['id']}/reset-password")
        assert r.status_code == 400

    def test_borrower_cannot_call(self):
        r = _s(STATE["borrower"]["token"]).post(f"{API}/users/{STATE['admin']['id']}/reset-password")
        assert r.status_code == 403

    def test_lender_cannot_call(self):
        r = _s(STATE["lender"]["token"]).post(f"{API}/users/{STATE['borrower']['id']}/reset-password")
        assert r.status_code == 403


# ============== 3. EMERGENCY OVERRIDE ==============
class TestEmergencyOverride:
    def _prep_loan_to_waiting_payment(self, super_token, principal=500000):
        """Return payment_id of a PENDING payment. Reuses admin/lender/borrower from STATE."""
        s_sup = _s(super_token)
        # verify borrower if not yet
        b = STATE["borrower"]
        atok = STATE["admin"]["token"]
        me = _s(atok).get(f"{API}/auth/me").json()
        borrower_meta = _s(atok).get(f"{API}/borrowers/{b['id']}").json()
        if borrower_meta["profile"].get("account_status") != "ACTIVE":
            r = _s(atok).post(f"{API}/borrowers/{b['id']}/verify", json={
                "approve": True, "borrower_limit": 5000000,
                "max_duration_days": 30, "max_active_loans": 5,
            })
            assert r.status_code == 200
            # refresh borrower token
            STATE["borrower"]["token"] = _login(b["phone"], b["password"])["token"]
        # apply loan
        btok = STATE["borrower"]["token"]
        r = _s(btok).post(f"{API}/loans", json={"principal_amount": principal, "duration_days": 7})
        assert r.status_code == 200, r.text
        loan_id = r.json()["id"]
        # approve
        assert _s(atok).post(f"{API}/loans/{loan_id}/approve").status_code == 200
        # claim by lender
        ltok = STATE["lender"]["token"]
        assert _s(ltok).post(f"{API}/loans/{loan_id}/claim").status_code == 200
        # disburse
        files = {"proof": ("p.png", _png(), "image/png")}
        data = {"amount": str(principal), "transfer_at": "2026-01-15T10:00:00Z", "notes": "T"}
        assert _s(ltok).post(f"{API}/loans/{loan_id}/disburse", data=data, files=files).status_code == 200
        # confirm
        assert _s(atok).post(f"{API}/loans/{loan_id}/confirm-disbursement").status_code == 200
        # borrower pay
        detail = _s(btok).get(f"{API}/loans/{loan_id}").json()
        total = detail["total_due"]
        data2 = {"amount": str(total), "paid_at": "2026-01-16T10:00:00Z", "notes": "T"}
        r = _s(btok).post(f"{API}/loans/{loan_id}/pay", data={"amount": str(total), "paid_at": "2026-01-16T10:00:00Z", "notes": "T"},
                          files={"proof": ("p.png", _png(), "image/png")})
        assert r.status_code == 200, r.text
        pays = r.json()["payments"]
        pid = [p for p in pays if p["status"] == "PENDING"][-1]["id"]
        return loan_id, pid

    def test_override_verify_flow(self, super_token, mongo):
        loan_id, pid = self._prep_loan_to_waiting_payment(super_token)
        STATE["ov_loan1"] = loan_id
        STATE["ov_pay1"] = pid
        # RBAC negatives
        assert _s(STATE["admin"]["token"]).post(f"{API}/payments/{pid}/override",
                                                json={"action": "verify", "reason": "alasan cukup panjang"}).status_code == 403
        assert _s(STATE["lender"]["token"]).post(f"{API}/payments/{pid}/override",
                                                 json={"action": "verify", "reason": "alasan cukup panjang"}).status_code == 403
        assert _s(STATE["borrower"]["token"]).post(f"{API}/payments/{pid}/override",
                                                   json={"action": "verify", "reason": "alasan cukup panjang"}).status_code == 403

        # short reason -> validation error
        r_short = _s(super_token).post(f"{API}/payments/{pid}/override",
                                       json={"action": "verify", "reason": "short"})
        assert r_short.status_code in (400, 422), r_short.text

        # invalid action
        r_bad = _s(super_token).post(f"{API}/payments/{pid}/override",
                                     json={"action": "invalidX", "reason": "alasan cukup panjang"})
        assert r_bad.status_code in (400, 422), r_bad.text

        # borrower outstanding before
        c_before = _s(STATE["borrower"]["token"]).get(f"{API}/auth/me").json()["credit"]

        # successful verify
        r = _s(super_token).post(f"{API}/payments/{pid}/override",
                                 json={"action": "verify", "reason": "Bukti sudah divalidasi manual oleh Superadmin"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "PAID"

        # outstanding decreased
        c_after = _s(STATE["borrower"]["token"]).get(f"{API}/auth/me").json()["credit"]
        assert c_after["outstanding_principal"] < c_before["outstanding_principal"]

        # payment marked VERIFIED with override flag in DB
        p_doc = mongo.payments.find_one({"_id": pid})
        assert p_doc["status"] == "VERIFIED"
        assert p_doc.get("override") is True

        # audit log entry
        a = mongo.audit_logs.find_one({"action": "SUPERADMIN_PAYMENT_OVERRIDE_VERIFY", "entity_id": pid})
        assert a and "Bukti sudah divalidasi" in a.get("description", "")

        # loan_status_histories entry with OVERRIDE
        hist = list(mongo.loan_status_histories.find({"loan_id": loan_id}))
        assert any("OVERRIDE SUPERADMIN" in (h.get("reason") or h.get("note") or h.get("description") or "") for h in hist), hist

        # override again on already-processed -> 409
        r2 = _s(super_token).post(f"{API}/payments/{pid}/override",
                                  json={"action": "verify", "reason": "alasan cukup panjang lagi"})
        assert r2.status_code == 409

    def test_override_reject_flow(self, super_token, mongo):
        # create another loan and payment
        loan_id, pid = self._prep_loan_to_waiting_payment(super_token, principal=700000)
        STATE["ov_loan2"] = loan_id
        STATE["ov_pay2"] = pid
        # push due_date to past to force OVERDUE post-reject
        # do it BEFORE reject
        from datetime import datetime, timezone, timedelta
        # but loan is in WAITING_PAYMENT; reject will set based on now vs due_date
        r = _s(super_token).post(f"{API}/payments/{pid}/override",
                                 json={"action": "reject", "reason": "Bukti tidak sesuai, tolong ulang"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] in ("ACTIVE", "OVERDUE")

        p_doc = mongo.payments.find_one({"_id": pid})
        assert p_doc["status"] == "REJECTED"
        assert p_doc.get("override") is True

        a = mongo.audit_logs.find_one({"action": "SUPERADMIN_PAYMENT_OVERRIDE_REJECT", "entity_id": pid})
        assert a is not None

        # borrower can submit a new payment
        btok = STATE["borrower"]["token"]
        detail = _s(btok).get(f"{API}/loans/{loan_id}").json()
        assert detail["payment_frozen"] in (False, None)
        r = _s(btok).post(f"{API}/loans/{loan_id}/pay",
                          data={"amount": str(detail["total_due"]),
                                "paid_at": "2026-01-20T10:00:00Z", "notes": "retry"},
                          files={"proof": ("p.png", _png(), "image/png")})
        assert r.status_code == 200, r.text


# ============== 4. OBJECT STORAGE ==============
class TestObjectStorage:
    def test_files_have_pinjamku_prefix(self, mongo):
        # any file uploaded during earlier tests
        docs = list(mongo.files.find({}).limit(10))
        assert docs, "no files uploaded yet"
        assert all(str(d.get("storage_path", "")).startswith("pinjamku/") for d in docs), \
            [d.get("storage_path") for d in docs]

    def test_file_requires_auth(self, mongo):
        rec = mongo.files.find_one({})
        r = requests.get(f"{API}/files/{rec['_id']}")
        assert r.status_code == 401

    def test_file_forbidden_for_unrelated_borrower(self, super_token, mongo):
        # create fresh unrelated borrower
        phone = _uphone()
        r = requests.post(f"{API}/auth/register", json={
            "nik": _rand(16), "full_name": "TEST Unrelated", "birth_date": "1995-01-01",
            "phone": phone, "email": f"u_{uuid.uuid4().hex[:6]}@t.com",
            "password": "Unrelated1!", "confirm_password": "Unrelated1!",
            "bank_name": "BCA", "account_number": "1122334455", "account_holder": "TT",
        })
        assert r.status_code == 200
        tok = r.json()["token"]
        # pick a file linked to a loan the unrelated borrower is NOT part of
        rec = mongo.files.find_one({"loan_id": {"$ne": None}})
        assert rec, "need a loan-linked file"
        r2 = _s(tok).get(f"{API}/files/{rec['_id']}")
        assert r2.status_code == 403

    def test_file_ok_for_superadmin(self, super_token, mongo):
        rec = mongo.files.find_one({"loan_id": {"$ne": None}})
        r = _s(super_token).get(f"{API}/files/{rec['_id']}")
        assert r.status_code == 200
        assert (r.headers.get("Content-Type") or "").startswith("image/")
        cc = r.headers.get("Cache-Control", "").lower()
        assert "private" in cc or "no-store" in cc

    def test_upload_rejects_bad_mime(self, super_token):
        # branding endpoint reuses save_upload; use text/plain
        files = {"file": ("bad.txt", b"hello", "text/plain")}
        r = _s(super_token).post(f"{API}/settings/logo?kind=logo", files=files)
        assert r.status_code == 400
