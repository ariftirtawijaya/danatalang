"""
Iteration 3 — Factory Reset / Clean Install (Superadmin only).

Order:
  A. RBAC & validation checks that MUST NOT delete data.
  B. Build a full data set (admin + 2 lenders + verified borrower + 1 PAID loan
     + 1 ACTIVE loan with disbursement & payment proof files).
  C. Mutate settings (app_name/bunga/denda/Telegram) so we can prove reset restores defaults.
  D. Execute the real factory reset with correct credentials.
  E. Verify clean install (users, collections, storage bytes, settings, superadmin login,
     dashboard zeros, old file endpoints now 404, only SYSTEM_FACTORY_RESET in audit log).
  F. Rebuild sistem to PAID after reset — proves counter reset (PIN-0001) and full usability.
  G. Double-submit factory reset — must not 500.
"""
import concurrent.futures
import io
import os
import random
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://utang-tracker-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

SUPERADMIN_PHONE = "081200000001"
SUPERADMIN_PASS = "Sup3rAdmin!2026"

STATE = {}


def _s(token=None):
    s = requests.Session()
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _login(phone, password):
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {phone}: {r.status_code} {r.text}"
    return r.json()["token"]


def _rand_digits(n):
    return "".join(str(random.randint(0, 9)) for _ in range(n))


def _uniq_phone():
    return "0812" + _rand_digits(9)


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
    tok = _login(SUPERADMIN_PHONE, SUPERADMIN_PASS)
    STATE["super_token"] = tok
    return tok


# =========================================================================
# PHASE A — RBAC & validation (must NOT delete data)
# =========================================================================
class TestA_RBAC:
    def test_preview_unauth_401(self):
        r = requests.get(f"{API}/settings/factory-reset/preview")
        assert r.status_code == 401

    def test_reset_unauth_401(self):
        r = requests.post(f"{API}/settings/factory-reset",
                          json={"confirmation": "HAPUS SEMUA DATA", "password": SUPERADMIN_PASS})
        assert r.status_code == 401

    def test_superadmin_preview_ok(self, super_token):
        r = _s(super_token).get(f"{API}/settings/factory-reset/preview")
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("admins", "lenders", "borrowers", "loans", "disbursements", "payments",
                  "loan_status_histories", "notifications", "admin_notes", "audit_logs",
                  "files", "counters", "storage_objects", "storage_bytes", "total_records", "keeper"):
            assert k in d, f"preview missing {k}"
        assert d["keeper"]["phone"] == SUPERADMIN_PHONE

    def test_bootstrap_admin_lender_borrower(self, super_token):
        """Create a temporary admin + lender + borrower to exercise RBAC 403 paths."""
        s = _s(super_token)
        # admin
        aphone = _uniq_phone()
        r = s.post(f"{API}/users", json={
            "full_name": "TEST A Admin", "phone": aphone,
            "email": f"a_adm_{uuid.uuid4().hex[:6]}@t.com",
            "password": "AdminPass1!", "role": "admin",
        })
        assert r.status_code == 200, r.text
        STATE["adminA"] = {"phone": aphone, "password": "AdminPass1!", "id": r.json()["id"],
                            "token": _login(aphone, "AdminPass1!")}
        # lender
        lphone = _uniq_phone()
        r = s.post(f"{API}/users", json={
            "full_name": "TEST A Lender", "phone": lphone,
            "email": f"a_len_{uuid.uuid4().hex[:6]}@t.com",
            "password": "LenderA1!", "role": "lender",
            "bank_name": "BCA", "account_number": "1234567890", "account_holder": "TEST",
        })
        assert r.status_code == 200
        STATE["lenderA"] = {"phone": lphone, "password": "LenderA1!", "id": r.json()["id"],
                             "token": _login(lphone, "LenderA1!")}
        # borrower
        bphone = _uniq_phone()
        r = requests.post(f"{API}/auth/register", json={
            "nik": _rand_digits(16), "full_name": "TEST A Borrower", "birth_date": "1995-01-01",
            "phone": bphone, "email": f"a_bor_{uuid.uuid4().hex[:6]}@t.com",
            "password": "Borrower1!", "confirm_password": "Borrower1!",
            "bank_name": "BCA", "account_number": "1122334455", "account_holder": "TEST",
        })
        assert r.status_code == 200
        STATE["borrowerA"] = {"phone": bphone, "password": "Borrower1!",
                               "id": r.json()["user"]["id"], "token": r.json()["token"]}

    @pytest.mark.parametrize("role", ["adminA", "lenderA", "borrowerA"])
    def test_preview_403(self, role):
        r = _s(STATE[role]["token"]).get(f"{API}/settings/factory-reset/preview")
        assert r.status_code == 403, f"{role}: {r.status_code}"

    @pytest.mark.parametrize("role", ["adminA", "lenderA", "borrowerA"])
    def test_reset_403(self, role):
        r = _s(STATE[role]["token"]).post(f"{API}/settings/factory-reset",
                                          json={"confirmation": "HAPUS SEMUA DATA", "password": SUPERADMIN_PASS})
        assert r.status_code == 403

    def test_bad_confirmation_400_no_deletion(self, super_token):
        s = _s(super_token)
        before = s.get(f"{API}/settings/factory-reset/preview").json()
        for bad in ("hapus semua data", "Hapus Semua Data", "HAPUS", "", "DELETE ALL"):
            r = s.post(f"{API}/settings/factory-reset",
                       json={"confirmation": bad, "password": SUPERADMIN_PASS})
            assert r.status_code == 400, f"{bad!r} -> {r.status_code}"
        after = s.get(f"{API}/settings/factory-reset/preview").json()
        assert after["total_records"] == before["total_records"], "bad confirmation deleted data!"

    def test_bad_password_401_no_deletion(self, super_token):
        s = _s(super_token)
        before = s.get(f"{API}/settings/factory-reset/preview").json()
        r = s.post(f"{API}/settings/factory-reset",
                   json={"confirmation": "HAPUS SEMUA DATA", "password": "WrongPassword!"})
        assert r.status_code == 401
        after = s.get(f"{API}/settings/factory-reset/preview").json()
        assert after["total_records"] == before["total_records"], "bad password deleted data!"


# =========================================================================
# PHASE B — Build a full dataset (paid + active loans w/ proof files)
# =========================================================================
class TestB_BuildData:
    def test_create_users(self, super_token):
        s = _s(super_token)
        # Fresh admin + 2 lenders + verified borrower dedicated to this suite
        aphone = _uniq_phone()
        r = s.post(f"{API}/users", json={
            "full_name": "TEST B Admin", "phone": aphone,
            "email": f"b_adm_{uuid.uuid4().hex[:6]}@t.com",
            "password": "AdminPass1!", "role": "admin"})
        assert r.status_code == 200
        STATE["admin"] = {"phone": aphone, "password": "AdminPass1!",
                           "id": r.json()["id"], "token": _login(aphone, "AdminPass1!")}
        for key in ("lender1", "lender2"):
            lp = _uniq_phone()
            r = s.post(f"{API}/users", json={
                "full_name": f"TEST B {key}", "phone": lp,
                "email": f"b_{key}_{uuid.uuid4().hex[:6]}@t.com",
                "password": "LenderP1!", "role": "lender",
                "bank_name": "BCA", "account_number": _rand_digits(10), "account_holder": "TEST"})
            assert r.status_code == 200
            STATE[key] = {"phone": lp, "password": "LenderP1!",
                           "id": r.json()["id"], "token": _login(lp, "LenderP1!")}
        # borrower
        bp = _uniq_phone()
        r = requests.post(f"{API}/auth/register", json={
            "nik": _rand_digits(16), "full_name": "TEST B Borrower", "birth_date": "1990-01-01",
            "phone": bp, "email": f"b_bor_{uuid.uuid4().hex[:6]}@t.com",
            "password": "Borrower1!", "confirm_password": "Borrower1!",
            "bank_name": "BCA", "account_number": _rand_digits(10), "account_holder": "TEST"})
        assert r.status_code == 200
        STATE["borrower"] = {"phone": bp, "password": "Borrower1!",
                              "id": r.json()["user"]["id"], "token": r.json()["token"]}
        # admin verifies borrower
        r = _s(STATE["admin"]["token"]).post(f"{API}/borrowers/{STATE['borrower']['id']}/verify", json={
            "approve": True, "borrower_limit": 10000000, "max_duration_days": 30, "max_active_loans": 3})
        assert r.status_code == 200
        # refresh borrower token (status changed)
        STATE["borrower"]["token"] = _login(bp, "Borrower1!")

    def test_loan_paid(self):
        """Loan 1: submit → approve → claim → disburse → confirm → pay → verify (PAID)."""
        s_b = _s(STATE["borrower"]["token"])
        s_ad = _s(STATE["admin"]["token"])
        s_l1 = _s(STATE["lender1"]["token"])
        r = s_b.post(f"{API}/loans", json={"principal_amount": 500000, "duration_days": 10})
        assert r.status_code == 200
        lid = r.json()["id"]
        assert s_ad.post(f"{API}/loans/{lid}/approve").status_code == 200
        assert s_l1.post(f"{API}/loans/{lid}/claim").status_code == 200
        files = {"proof": ("p.png", _png(), "image/png")}
        r = s_l1.post(f"{API}/loans/{lid}/disburse",
                       data={"amount": "500000", "transfer_at": "2026-01-15T10:00:00Z"}, files=files)
        assert r.status_code == 200, r.text
        assert s_ad.post(f"{API}/loans/{lid}/confirm-disbursement").status_code == 200
        # total = principal + 10% interest
        det = s_b.get(f"{API}/loans/{lid}").json()
        files = {"proof": ("p.png", _png(), "image/png")}
        r = s_b.post(f"{API}/loans/{lid}/pay",
                     data={"amount": str(det["total_due"]), "paid_at": "2026-01-16T10:00:00Z"}, files=files)
        assert r.status_code == 200
        pay_id = r.json()["payments"][-1]["id"]
        r = s_l1.post(f"{API}/payments/{pay_id}/verify")
        assert r.status_code == 200 and r.json()["status"] == "PAID"

    def test_loan_active_with_proofs(self):
        """Loan 2 kept in ACTIVE with disbursement proof + a pending payment proof."""
        s_b = _s(STATE["borrower"]["token"])
        s_ad = _s(STATE["admin"]["token"])
        s_l2 = _s(STATE["lender2"]["token"])
        r = s_b.post(f"{API}/loans", json={"principal_amount": 700000, "duration_days": 14})
        assert r.status_code == 200
        lid = r.json()["id"]
        STATE["active_loan_id"] = lid
        assert s_ad.post(f"{API}/loans/{lid}/approve").status_code == 200
        assert s_l2.post(f"{API}/loans/{lid}/claim").status_code == 200
        files = {"proof": ("p.png", _png(), "image/png")}
        assert s_l2.post(f"{API}/loans/{lid}/disburse",
                          data={"amount": "700000", "transfer_at": "2026-01-15T10:00:00Z"},
                          files=files).status_code == 200
        assert s_ad.post(f"{API}/loans/{lid}/confirm-disbursement").status_code == 200
        # partial payment proof (should be rejected as short, but at least exercises upload)
        det = s_b.get(f"{API}/loans/{lid}").json()
        files = {"proof": ("p.png", _png(), "image/png")}
        r = s_b.post(f"{API}/loans/{lid}/pay",
                     data={"amount": str(det["total_due"]), "paid_at": "2026-01-16T10:00:00Z"}, files=files)
        assert r.status_code == 200
        # leave it pending (loan is now WAITING_PAYMENT_VERIFICATION with 1 pending payment attempt)

    def test_pending_file_exists(self, mongo):
        n_files = mongo.files.count_documents({"is_deleted": False})
        assert n_files >= 4, f"expected >=4 proof files, got {n_files}"
        # grab a file_id to test 404 after reset
        f = mongo.files.find_one({"is_deleted": False})
        STATE["some_file_id"] = f["_id"]


# =========================================================================
# PHASE C — Mutate settings so reset must restore defaults
# =========================================================================
class TestC_MutateSettings:
    def test_mutate(self, super_token):
        s = _s(super_token)
        assert s.put(f"{API}/settings/general",
                      json={"app_name": "MUTATED APP", "app_description": "mut"}).status_code == 200
        assert s.put(f"{API}/settings/loan",
                      json={"interest_rate": 12.0, "late_fee_rate_per_day": 1.5}).status_code == 200
        assert s.put(f"{API}/settings/telegram", json={
            "telegram_reg_enabled": True, "telegram_loan_enabled": True,
            "telegram_reg_token": "1234567890:DUMMY_REG_TOKEN_" + uuid.uuid4().hex,
            "telegram_loan_token": "1234567890:DUMMY_LOAN_TOKEN_" + uuid.uuid4().hex,
        }).status_code == 200

    def test_preview_reflects_data(self, super_token):
        d = _s(super_token).get(f"{API}/settings/factory-reset/preview").json()
        assert d["admins"] >= 1
        assert d["lenders"] >= 2
        assert d["borrowers"] >= 1
        assert d["loans"] >= 2
        assert d["disbursements"] >= 2
        assert d["payments"] >= 2
        assert d["files"] >= 4
        assert d["counters"] >= 1
        # storage should also have >0 objects and >0 bytes
        assert (d["storage_objects"] or 0) >= 4
        assert (d["storage_bytes"] or 0) > 0
        STATE["preview_before"] = d


# =========================================================================
# PHASE D — Execute factory reset
# =========================================================================
class TestD_ExecuteReset:
    def test_reset_success(self, super_token):
        r = _s(super_token).post(f"{API}/settings/factory-reset",
                                  json={"confirmation": "HAPUS SEMUA DATA", "password": SUPERADMIN_PASS})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert j["status"] in ("SUCCESS", "PARTIAL")  # PARTIAL only if storage listing errored
        assert j["kept_superadmin"]["phone"] == SUPERADMIN_PHONE
        # settings returned should already be default
        assert j["settings"]["app_name"] == "PinjamKu"
        assert j["settings"]["interest_rate"] == 10.0
        assert j["settings"]["late_fee_rate_per_day"] == 1.0
        STATE["reset_response"] = j


# =========================================================================
# PHASE E — Verify clean install
# =========================================================================
class TestE_VerifyClean:
    def test_only_superadmin_left(self, mongo):
        users = list(mongo.users.find({}))
        assert len(users) == 1, f"users left: {[u.get('phone') for u in users]}"
        u = users[0]
        assert u["role"] == "superadmin"
        assert u["phone"] == SUPERADMIN_PHONE

    @pytest.mark.parametrize("col", [
        "loans", "disbursements", "payments", "loan_status_histories",
        "notifications", "admin_notes", "files", "counters", "login_attempts",
    ])
    def test_collection_empty(self, mongo, col):
        assert mongo[col].count_documents({}) == 0

    def test_audit_log_only_reset_entry(self, mongo):
        docs = list(mongo.audit_logs.find({}))
        assert len(docs) == 1, [d.get("action") for d in docs]
        a = docs[0]
        assert a["action"] == "SYSTEM_FACTORY_RESET"
        assert a.get("created_at")
        # keeper (superadmin utama) is user pelaksana
        assert a.get("user_name") or a.get("user_id")

    def test_settings_default(self, mongo, super_token):
        r = _s(super_token).get(f"{API}/settings")
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["app_name"] == "PinjamKu"
        assert s["interest_rate"] == 10.0
        assert s["late_fee_rate_per_day"] == 1.0
        assert s["logo_url"] in (None, "")
        assert s["favicon_url"] in (None, "")
        assert s.get("telegram_reg_enabled") is False
        assert s.get("telegram_loan_enabled") is False
        # tokens should be cleared (masked returns None when empty)
        assert s.get("telegram_reg_token_masked") in (None, "")
        assert s.get("telegram_loan_token_masked") in (None, "")

    def test_storage_zero_bytes(self):
        # verify via preview after reset - storage_bytes should be 0
        r = _s(STATE["super_token"]).get(f"{API}/settings/factory-reset/preview")
        assert r.status_code == 200
        d = r.json()
        assert (d.get("storage_bytes") or 0) == 0, f"storage_bytes={d.get('storage_bytes')}"

    def test_old_file_endpoint_404(self):
        fid = STATE.get("some_file_id")
        if not fid:
            pytest.skip("no file id recorded")
        r = _s(STATE["super_token"]).get(f"{API}/files/{fid}")
        assert r.status_code == 404

    def test_superadmin_can_login(self):
        tok = _login(SUPERADMIN_PHONE, SUPERADMIN_PASS)
        STATE["super_token"] = tok  # refresh in-memory token for downstream tests
        assert tok

    def test_dashboard_zeros(self):
        r = _s(STATE["super_token"]).get(f"{API}/dashboard")
        assert r.status_code == 200
        d = r.json()
        for k in ("total_borrowers", "total_loans", "waiting_approval", "active_loans",
                  "overdue_loans", "paid_loans", "total_admins", "total_lenders"):
            assert d.get(k) == 0, f"{k}={d.get(k)}"

    def test_old_tokens_now_invalid(self):
        """Admin/lender/borrower tokens issued before reset must be unusable."""
        for key in ("admin", "lender1", "lender2", "borrower"):
            if key not in STATE:
                continue
            r = _s(STATE[key]["token"]).get(f"{API}/auth/me")
            # user record deleted so JWT sub no longer resolves — must be 401
            assert r.status_code == 401, f"{key}: {r.status_code}"


# =========================================================================
# PHASE F — Rebuild sistem post-reset up to PAID (proves usability)
# =========================================================================
class TestF_PostResetUsability:
    def test_create_admin_lender_borrower(self):
        s = _s(STATE["super_token"])
        aphone = _uniq_phone()
        assert s.post(f"{API}/users", json={
            "full_name": "TEST F Admin", "phone": aphone,
            "email": f"f_adm_{uuid.uuid4().hex[:6]}@t.com",
            "password": "AdminPass1!", "role": "admin"}).status_code == 200
        STATE["fAdmin"] = {"phone": aphone, "token": _login(aphone, "AdminPass1!")}
        lphone = _uniq_phone()
        r = s.post(f"{API}/users", json={
            "full_name": "TEST F Lender", "phone": lphone,
            "email": f"f_len_{uuid.uuid4().hex[:6]}@t.com",
            "password": "LenderP1!", "role": "lender",
            "bank_name": "BCA", "account_number": _rand_digits(10), "account_holder": "TEST"})
        assert r.status_code == 200
        STATE["fLender"] = {"phone": lphone, "token": _login(lphone, "LenderP1!"), "id": r.json()["id"]}
        bp = _uniq_phone()
        r = requests.post(f"{API}/auth/register", json={
            "nik": _rand_digits(16), "full_name": "TEST F Borrower", "birth_date": "1990-01-01",
            "phone": bp, "email": f"f_bor_{uuid.uuid4().hex[:6]}@t.com",
            "password": "Borrower1!", "confirm_password": "Borrower1!",
            "bank_name": "BCA", "account_number": _rand_digits(10), "account_holder": "TEST"})
        assert r.status_code == 200
        STATE["fBorrower"] = {"phone": bp, "id": r.json()["user"]["id"], "token": r.json()["token"]}
        # verify
        assert _s(STATE["fAdmin"]["token"]).post(
            f"{API}/borrowers/{STATE['fBorrower']['id']}/verify",
            json={"approve": True, "borrower_limit": 5000000, "max_duration_days": 30, "max_active_loans": 2}
        ).status_code == 200
        STATE["fBorrower"]["token"] = _login(bp, "Borrower1!")

    def test_loan_number_starts_from_0001(self):
        r = _s(STATE["fBorrower"]["token"]).post(f"{API}/loans",
                                                   json={"principal_amount": 400000, "duration_days": 7})
        assert r.status_code == 200, r.text
        j = r.json()
        # first loan after counter reset must end with 0001
        assert j["loan_number"].endswith("0001"), f"loan_number={j['loan_number']}"
        STATE["fLoanId"] = j["id"]

    def test_full_flow_to_paid(self):
        lid = STATE["fLoanId"]
        s_ad = _s(STATE["fAdmin"]["token"])
        s_l = _s(STATE["fLender"]["token"])
        s_b = _s(STATE["fBorrower"]["token"])
        assert s_ad.post(f"{API}/loans/{lid}/approve").status_code == 200
        assert s_l.post(f"{API}/loans/{lid}/claim").status_code == 200
        files = {"proof": ("p.png", _png(), "image/png")}
        assert s_l.post(f"{API}/loans/{lid}/disburse",
                         data={"amount": "400000", "transfer_at": "2026-01-15T10:00:00Z"},
                         files=files).status_code == 200
        assert s_ad.post(f"{API}/loans/{lid}/confirm-disbursement").status_code == 200
        det = s_b.get(f"{API}/loans/{lid}").json()
        files = {"proof": ("p.png", _png(), "image/png")}
        r = s_b.post(f"{API}/loans/{lid}/pay",
                     data={"amount": str(det["total_due"]), "paid_at": "2026-01-16T10:00:00Z"}, files=files)
        assert r.status_code == 200
        pid = r.json()["payments"][-1]["id"]
        r = s_l.post(f"{API}/payments/{pid}/verify")
        assert r.status_code == 200 and r.json()["status"] == "PAID"


# =========================================================================
# PHASE G — Double submission robustness
# =========================================================================
class TestG_DoubleSubmit:
    def test_two_parallel_resets_no_500(self):
        tok = STATE["super_token"]

        def call():
            return requests.post(
                f"{API}/settings/factory-reset",
                headers={"Authorization": f"Bearer {tok}"},
                json={"confirmation": "HAPUS SEMUA DATA", "password": SUPERADMIN_PASS},
                timeout=120,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(call)
            f2 = ex.submit(call)
            r1, r2 = f1.result(), f2.result()

        statuses = sorted([r1.status_code, r2.status_code])
        # neither may be 500; at least one should have completed OK (200)
        assert 500 not in statuses, f"got 5xx: {statuses} — {r1.text} / {r2.text}"
        assert 200 in statuses, f"neither succeeded: {statuses}"
        # the other one must be either 200 (idempotent) or 409 (lock)
        assert all(s in (200, 409) for s in statuses), statuses

    def test_superadmin_intact_after_double(self, mongo):
        users = list(mongo.users.find({}))
        assert len(users) == 1 and users[0]["phone"] == SUPERADMIN_PHONE

    def test_settings_still_default_after_double(self):
        r = _s(STATE["super_token"]).get(f"{API}/settings")
        assert r.status_code == 200
        s = r.json()
        assert s["app_name"] == "PinjamKu"
        assert s["interest_rate"] == 10.0
