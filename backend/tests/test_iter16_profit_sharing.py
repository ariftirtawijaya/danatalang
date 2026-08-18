"""Iteration 16: modul Pembagian Hasil (profit sharing) + Settlement.

Menjalankan flow lengkap melalui preview URL (ingress) memakai superadmin sementara
dari conftest. Tidak memakai kredensial milik user.
"""
import io
import os
import uuid
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/frontend/.env"))
load_dotenv(Path("/app/backend/.env"))
BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"
MONGO = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

SUPER_PHONE = os.environ.get("TEST_SUPER_PHONE", "081900000777")
SUPER_PASS = os.environ.get("TEST_SUPER_PASS", "TempSup3r!2026")

PASS = "Test1234!ok"
TAG = uuid.uuid4().hex[:6]
PHONE_TAG = f"{uuid.uuid4().int % 10000:04d}"
CREATED_PHONES = []


def login(phone, password):
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def sess(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def new_phone(n):
    return f"0819{PHONE_TAG}{n:04d}"


def png_bytes():
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def proof_files():
    return {"proof": ("bukti.png", io.BytesIO(png_bytes()), "image/png")}


@pytest.fixture(scope="module")
def su():
    return sess(login(SUPER_PHONE, SUPER_PASS))


@pytest.fixture(scope="module", autouse=True)
def loan_rates(su):
    """Contoh perhitungan pada spesifikasi memakai bunga 20% dan denda 1%/hari."""
    before = su.get(f"{API}/settings", timeout=30).json()
    su.put(f"{API}/settings/loan", json={"interest_rate": 20, "late_fee_rate_per_day": 1}, timeout=30)
    yield
    su.put(
        f"{API}/settings/loan",
        json={
            "interest_rate": before.get("interest_rate", 10),
            "late_fee_rate_per_day": before.get("late_fee_rate_per_day", 1),
        },
        timeout=30,
    )


def create_staff(su, role, n, name):
    phone = new_phone(n)
    CREATED_PHONES.append(phone)
    r = su.post(
        f"{API}/users",
        json={
            "full_name": name,
            "phone": phone,
            "email": f"{role}{n}{TAG}@danatalang-test.com",
            "password": PASS,
            "role": role,
            "bank_name": "BCA",
            "account_number": "1234567890",
            "account_holder": name.upper(),
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    user_id = r.json().get("user", {}).get("id") or r.json().get("id")
    MONGO.users.update_one({"phone": phone}, {"$unset": {"must_change_password": ""}})
    return {"id": user_id, "phone": phone, "session": sess(login(phone, PASS))}


def create_borrower(su, n, name, limit=50_000_000):
    phone = new_phone(n)
    CREATED_PHONES.append(phone)
    nik = f"32{uuid.uuid4().int % 10**14:014d}"
    r = requests.post(
        f"{API}/auth/register",
        json={
            "nik": nik,
            "full_name": name,
            "birth_date": "1995-01-01",
            "phone": phone,
            "email": f"borrower{n}{TAG}@danatalang-test.com",
            "password": PASS,
            "confirm_password": PASS,
            "bank_name": "BCA",
            "account_number": "9876543210",
            "account_holder": name.upper(),
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    bid = r.json()["user"]["id"]
    v = su.post(
        f"{API}/borrowers/{bid}/verify",
        json={"approve": True, "borrower_limit": limit, "max_duration_days": 60, "max_active_loans": 5},
        timeout=30,
    )
    assert v.status_code == 200, v.text
    return {"id": bid, "phone": phone, "session": sess(login(phone, PASS))}


@pytest.fixture(scope="module")
def actors(su):
    admin = create_staff(su, "admin", 1, f"Admin Satu {TAG}")
    admin2 = create_staff(su, "admin", 2, f"Admin Dua {TAG}")
    lender = create_staff(su, "lender", 3, f"Pendana Satu {TAG}")
    lender2 = create_staff(su, "lender", 4, f"Pendana Dua {TAG}")
    borrower = create_borrower(su, 5, f"Peminjam Satu {TAG}")
    yield {"admin": admin, "admin2": admin2, "lender": lender, "lender2": lender2, "borrower": borrower}
    MONGO.users.delete_many({"phone": {"$in": CREATED_PHONES}})


def set_pcts(su, lender_pct, admin_pct, platform_pct, expect=200):
    r = su.put(
        f"{API}/settings/profit-sharing",
        json={"lender_pct": lender_pct, "admin_pct": admin_pct, "platform_pct": platform_pct},
        timeout=30,
    )
    assert r.status_code == expect, r.text
    return r


_DUR = [40]


def submit_loan(borrower, principal=2_000_000, duration=None):
    if duration is None:
        _DUR[0] += 1
        duration = _DUR[0]
    r = borrower["session"].post(f"{API}/loans", json={"principal_amount": principal, "duration_days": duration}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def to_paid(actors, su, loan_id, approver=None, assigned_admin_id=None, late_days=0, verify_twice=False):
    approver = approver or su
    payload = {"assigned_admin_id": assigned_admin_id} if assigned_admin_id else {}
    a = approver.post(f"{API}/loans/{loan_id}/approve", json=payload, timeout=30)
    assert a.status_code == 200, a.text
    c = actors["lender"]["session"].post(f"{API}/loans/{loan_id}/claim", timeout=30)
    assert c.status_code == 200, c.text
    loan = MONGO.loans.find_one({"_id": loan_id})
    d = actors["lender"]["session"].post(
        f"{API}/loans/{loan_id}/disburse",
        data={"amount": loan["principal_amount"], "transfer_at": "2026-06-01T10:00", "notes": "test"},
        files=proof_files(),
        timeout=60,
    )
    assert d.status_code == 200, d.text
    k = su.post(f"{API}/loans/{loan_id}/confirm-disbursement", timeout=30)
    assert k.status_code == 200, k.text
    if late_days:
        from datetime import datetime, timezone, timedelta

        past = (datetime.now(timezone.utc) - timedelta(days=late_days)).isoformat()
        MONGO.loans.update_one({"_id": loan_id}, {"$set": {"due_date": past, "status": "OVERDUE"}})
    detail = actors["borrower"]["session"].get(f"{API}/loans/{loan_id}", timeout=30).json()
    p = actors["borrower"]["session"].post(
        f"{API}/loans/{loan_id}/pay",
        data={"amount": detail["total_due"], "paid_at": "2026-06-20T10:00", "notes": "bayar"},
        files=proof_files(),
        timeout=60,
    )
    assert p.status_code == 200, p.text
    payment_id = [x for x in p.json()["payments"] if x["status"] == "PENDING"][0]["id"]
    v = actors["lender"]["session"].post(f"{API}/payments/{payment_id}/verify", timeout=60)
    assert v.status_code == 200, v.text
    second = None
    if verify_twice:
        second = actors["lender"]["session"].post(f"{API}/payments/{payment_id}/verify", timeout=30)
    return {"loan": v.json(), "payment_id": payment_id, "second_verify": second}


def distribution_of(su, loan_id):
    doc = MONGO.profit_distributions.find_one({"loan_id": loan_id})
    if not doc:
        return None
    r = su.get(f"{API}/profit-distributions/{doc['_id']}", timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------- A. SETTINGS ----------------
def test_a_settings_validation(su, actors):
    set_pcts(su, 60, 25, 15)
    got = su.get(f"{API}/settings/profit-sharing", timeout=30).json()
    assert (got["lender_pct"], got["admin_pct"], got["platform_pct"]) == (60, 25, 15)
    set_pcts(su, 60, 25, 14, expect=400)
    set_pcts(su, 60, 25, 16, expect=400)
    r = actors["admin"]["session"].put(
        f"{API}/settings/profit-sharing", json={"lender_pct": 50, "admin_pct": 30, "platform_pct": 20}, timeout=30
    )
    assert r.status_code == 403, r.text
    r = actors["admin"]["session"].get(f"{API}/settings/profit-sharing", timeout=30)
    assert r.status_code == 403


# ---------------- B. SNAPSHOT ----------------
def test_b_snapshot_immutability(su, actors):
    set_pcts(su, 60, 25, 15)
    loan_old = submit_loan(actors["borrower"])
    su.post(f"{API}/loans/{loan_old['id']}/approve", json={"assigned_admin_id": actors["admin"]["id"]}, timeout=30)
    set_pcts(su, 65, 20, 15)
    loan_new = submit_loan(actors["borrower"], principal=2_500_000)
    su.post(f"{API}/loans/{loan_new['id']}/approve", json={"assigned_admin_id": actors["admin"]["id"]}, timeout=30)

    old = su.get(f"{API}/loans/{loan_old['id']}", timeout=30).json()["profit_share"]
    new = su.get(f"{API}/loans/{loan_new['id']}", timeout=30).json()["profit_share"]
    assert (old["lender_pct"], old["admin_pct"], old["platform_pct"]) == (60, 25, 15)
    assert (new["lender_pct"], new["admin_pct"], new["platform_pct"]) == (65, 20, 15)
    set_pcts(su, 60, 25, 15)
    again = su.get(f"{API}/loans/{loan_old['id']}", timeout=30).json()["profit_share"]
    assert (again["lender_pct"], again["admin_pct"], again["platform_pct"]) == (60, 25, 15)


# ---------------- C. ADMIN ASSIGNMENT ----------------
def test_c_admin_assignment(su, actors):
    loan = submit_loan(actors["borrower"], principal=1_100_000)
    r = su.post(f"{API}/loans/{loan['id']}/approve", json={}, timeout=30)
    assert r.status_code == 400 and "Admin penanggung jawab" in r.text
    r = su.post(f"{API}/loans/{loan['id']}/approve", json={"assigned_admin_id": actors["admin"]["id"]}, timeout=30)
    assert r.status_code == 200, r.text
    assert MONGO.loans.find_one({"_id": loan["id"]})["assigned_admin_id"] == actors["admin"]["id"]

    loan2 = submit_loan(actors["borrower"], principal=1_200_000)
    r = actors["admin2"]["session"].post(f"{API}/loans/{loan2['id']}/approve", json={}, timeout=30)
    assert r.status_code == 200, r.text
    assert MONGO.loans.find_one({"_id": loan2["id"]})["assigned_admin_id"] == actors["admin2"]["id"]

    # Superadmin dapat mengubah selama belum PAID, wajib alasan >= 10 karakter
    r = su.put(f"{API}/loans/{loan2['id']}/assigned-admin", json={"admin_id": actors["admin"]["id"], "reason": "salah"}, timeout=30)
    assert r.status_code == 422
    r = su.put(
        f"{API}/loans/{loan2['id']}/assigned-admin",
        json={"admin_id": actors["admin"]["id"], "reason": "Koreksi penanggung jawab administratif"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    assert MONGO.loans.find_one({"_id": loan2["id"]})["assigned_admin_id"] == actors["admin"]["id"]
    assert MONGO.audit_logs.find_one({"action": "LOAN_ASSIGNED_ADMIN_CHANGED", "entity_id": loan2["id"]})


# ---------------- D. TANPA DENDA ----------------
def test_d_calculation_without_late_fee(su, actors):
    set_pcts(su, 60, 25, 15)
    loan = submit_loan(actors["borrower"], principal=2_000_000)
    to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"])
    d = distribution_of(su, loan["id"])
    assert d["principal"] == 2_000_000
    assert d["interest_realized"] == 400_000
    assert d["late_fee_realized"] == 0
    assert d["profit_pool"] == 400_000
    assert d["lender_profit"] == 240_000
    assert d["admin_profit"] == 100_000
    assert d["platform_profit"] == 60_000
    assert d["lender_total_entitlement"] == 2_240_000
    assert d["lender_settlement_due"] == 160_000
    assert d["lender_total_entitlement"] + d["lender_settlement_due"] == d["total_received"]
    assert d["lender_settlement_status"] == "PENDING"
    assert d["admin_payout_status"] == "NOT_READY"


# ---------------- E + G + H. DENGAN DENDA, FREEZE, DOUBLE VERIFY ----------------
@pytest.fixture(scope="module")
def paid_with_late_fee(su, actors):
    set_pcts(su, 60, 25, 15)
    loan = submit_loan(actors["borrower"], principal=2_000_000)
    res = to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"], late_days=5, verify_twice=True)
    return {"loan_id": loan["id"], **res}


def test_e_calculation_with_late_fee(su, paid_with_late_fee):
    d = distribution_of(su, paid_with_late_fee["loan_id"])
    assert d["principal"] == 2_000_000
    assert d["interest_realized"] == 400_000
    assert d["late_fee_realized"] == 100_000  # 1%/hari x 5 hari
    assert d["profit_pool"] == 500_000
    assert d["lender_profit"] == 300_000
    assert d["admin_profit"] == 125_000
    assert d["platform_profit"] == 75_000
    assert d["lender_total_entitlement"] == 2_300_000
    assert d["lender_settlement_due"] == 200_000
    assert d["total_received"] == 2_500_000


def test_g_payment_freeze_respected(su, paid_with_late_fee):
    payment = MONGO.payments.find_one({"_id": paid_with_late_fee["payment_id"]})
    d = distribution_of(su, paid_with_late_fee["loan_id"])
    assert d["late_fee_realized"] == payment["late_fee_at_submission"]


def test_h_double_verify_single_distribution(su, paid_with_late_fee):
    assert paid_with_late_fee["second_verify"].status_code == 409
    assert MONGO.profit_distributions.count_documents({"loan_id": paid_with_late_fee["loan_id"]}) == 1


# ---------------- F. ROUNDING ----------------
def test_f_rounding_always_matches_pool():
    import sys

    sys.path.insert(0, "/app/backend")
    import profit_service as PS

    cases = [
        (1_000_000, 100_001, 0, 60, 25, 15),
        (1_000_000, 33_333, 1, 33.33, 33.33, 33.34),
        (777_777, 12_345, 6_789, 70.5, 19.25, 10.25),
        (1, 1, 0, 60, 25, 15),
        (0, 0, 0, 60, 25, 15),
    ]
    for principal, interest, late_fee, lp, ap, pp in cases:
        d = PS.compute_distribution(principal, interest, late_fee, lp, ap, pp)
        assert d["lender_profit"] + d["admin_profit"] + d["platform_profit"] == d["profit_pool"]
        assert d["lender_total_entitlement"] + d["lender_settlement_due"] == d["total_received"]
        assert all(isinstance(d[k], int) for k in ("lender_profit", "admin_profit", "platform_profit", "profit_pool"))


# ---------------- I + J + K + L + M. SETTLEMENT & PAYOUT ----------------
def test_i_to_l_settlement_and_payout_flow(su, actors, paid_with_late_fee):
    d = distribution_of(su, paid_with_late_fee["loan_id"])
    dist_id = d["id"]

    # L: payout tidak boleh dibayar sebelum settlement diterima
    r = su.post(f"{API}/profit-distributions/{dist_id}/admin-payout/mark-paid", files=proof_files(), timeout=60)
    assert r.status_code == 409

    # I: Pendana lain 403
    r = actors["lender2"]["session"].post(f"{API}/profit-distributions/{dist_id}/settlement", files=proof_files(), timeout=60)
    assert r.status_code == 403
    # Peminjam & Admin tidak boleh submit
    assert actors["borrower"]["session"].post(f"{API}/profit-distributions/{dist_id}/settlement", files=proof_files(), timeout=60).status_code == 403
    assert actors["admin"]["session"].post(f"{API}/profit-distributions/{dist_id}/settlement", files=proof_files(), timeout=60).status_code == 403

    # J: submit oleh pemilik -> WAITING_VERIFICATION
    r = actors["lender"]["session"].post(f"{API}/profit-distributions/{dist_id}/settlement", files=proof_files(), timeout=60)
    assert r.status_code == 200, r.text
    assert r.json()["lender_settlement_status"] == "WAITING_VERIFICATION"
    first_proof = r.json()["settlement_proof_file_id"]
    # double submit ditolak
    assert actors["lender"]["session"].post(f"{API}/profit-distributions/{dist_id}/settlement", files=proof_files(), timeout=60).status_code == 409
    # Admin & Pendana tidak boleh verify
    assert actors["admin"]["session"].post(f"{API}/profit-distributions/{dist_id}/settlement/verify", timeout=30).status_code == 403
    assert actors["lender"]["session"].post(f"{API}/profit-distributions/{dist_id}/settlement/verify", timeout=30).status_code == 403

    # M: RBAC file bukti settlement
    assert requests.get(f"{API}/files/{first_proof}", timeout=30).status_code == 401
    assert actors["lender2"]["session"].get(f"{API}/files/{first_proof}", timeout=30).status_code == 403
    assert actors["borrower"]["session"].get(f"{API}/files/{first_proof}", timeout=30).status_code == 403
    assert actors["lender"]["session"].get(f"{API}/files/{first_proof}", timeout=30).status_code == 200
    assert actors["admin"]["session"].get(f"{API}/files/{first_proof}", timeout=30).status_code == 200  # admin penanggung jawab
    assert actors["admin2"]["session"].get(f"{API}/files/{first_proof}", timeout=30).status_code == 403
    assert su.get(f"{API}/files/{first_proof}", timeout=30).status_code == 200

    # K: reject -> kembali PENDING, alasan tersimpan, bisa upload ulang
    assert su.post(f"{API}/profit-distributions/{dist_id}/settlement/reject", json={"reason": "kurang"}, timeout=30).status_code == 422
    r = su.post(f"{API}/profit-distributions/{dist_id}/settlement/reject", json={"reason": "Nominal setoran tidak sesuai catatan"}, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["lender_settlement_status"] == "PENDING"
    assert r.json()["settlement_rejection_reason"] == "Nominal setoran tidak sesuai catatan"
    assert MONGO.audit_logs.find_one({"action": "LENDER_SETTLEMENT_REJECTED", "entity_id": dist_id})
    r = actors["lender"]["session"].post(f"{API}/profit-distributions/{dist_id}/settlement", files=proof_files(), timeout=60)
    assert r.status_code == 200 and r.json()["settlement_attempt_count"] == 2

    # verify -> SETTLED + payout PENDING
    r = su.post(f"{API}/profit-distributions/{dist_id}/settlement/verify", timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["lender_settlement_status"] == "SETTLED"
    assert r.json()["admin_payout_status"] == "PENDING"
    assert su.post(f"{API}/profit-distributions/{dist_id}/settlement/verify", timeout=30).status_code == 409

    # L: Admin tidak boleh menandai payout sendiri
    assert actors["admin"]["session"].post(
        f"{API}/profit-distributions/{dist_id}/admin-payout/mark-paid", files=proof_files(), timeout=60
    ).status_code == 403
    r = su.post(f"{API}/profit-distributions/{dist_id}/admin-payout/mark-paid", files=proof_files(), timeout=60)
    assert r.status_code == 200, r.text
    assert r.json()["admin_payout_status"] == "PAID"
    assert r.json()["admin_payout_amount"] == 125_000
    assert su.post(f"{API}/profit-distributions/{dist_id}/admin-payout/mark-paid", files=proof_files(), timeout=60).status_code == 409
    assert MONGO.audit_logs.find_one({"action": "ADMIN_PAYOUT_MARKED_PAID", "entity_id": dist_id})


def test_m_rbac_list_and_summary(su, actors, paid_with_late_fee):
    assert actors["borrower"]["session"].get(f"{API}/profit-distributions", timeout=30).status_code == 403
    assert actors["borrower"]["session"].get(f"{API}/profit-distributions/summary", timeout=30).status_code == 403

    mine = actors["lender"]["session"].get(f"{API}/profit-distributions", params={"page_size": 100}, timeout=30).json()
    assert all(i["lender_id"] == actors["lender"]["id"] for i in mine["items"])
    other = actors["lender2"]["session"].get(f"{API}/profit-distributions", params={"page_size": 100}, timeout=30).json()
    assert all(i["lender_id"] == actors["lender2"]["id"] for i in other["items"])

    admin_view = actors["admin"]["session"].get(f"{API}/profit-distributions", params={"page_size": 100}, timeout=30).json()
    assert all(i["assigned_admin_id"] == actors["admin"]["id"] for i in admin_view["items"])
    assert actors["admin2"]["session"].get(
        f"{API}/profit-distributions/{distribution_of(su, paid_with_late_fee['loan_id'])['id']}", timeout=30
    ).status_code == 403

    s = actors["admin"]["session"].get(f"{API}/profit-distributions/summary", timeout=30).json()
    assert s["admin_earned"] >= 125_000
    assert s["admin_paid"] >= 125_000
    sup = su.get(f"{API}/profit-distributions/summary", timeout=30).json()
    assert sup["platform_collected"] >= 75_000 and sup["platform_earned"] >= sup["platform_collected"]


def test_n_settlement_account_and_csv(su, actors):
    r = su.put(
        f"{API}/settings/settlement-account",
        json={
            "settlement_account_type": "BCA",
            "settlement_account_number": "1234567890",
            "settlement_account_holder": "PT DANA TALANG",
            "settlement_account_bank_name": "Bank Central Asia",
            "settlement_instructions": "Sertakan nomor pinjaman pada berita transfer.",
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    assert actors["lender"]["session"].get(f"{API}/settings/settlement-account", timeout=30).json()["settlement_account_number"] == "1234567890"
    assert actors["borrower"]["session"].get(f"{API}/settings/settlement-account", timeout=30).status_code == 403
    assert actors["admin"]["session"].put(
        f"{API}/settings/settlement-account",
        json={"settlement_account_type": "BRI", "settlement_account_number": "111", "settlement_account_holder": "X"},
        timeout=30,
    ).status_code == 403
    assert MONGO.audit_logs.find_one({"action": "SETTLEMENT_ACCOUNT_UPDATED"})

    csv_resp = su.get(f"{API}/profit-distributions/export.csv", timeout=60)
    assert csv_resp.status_code == 200 and "loan_number" in csv_resp.text
    assert actors["admin"]["session"].get(f"{API}/profit-distributions/export.csv", timeout=30).status_code == 403


# ---------------- O. LEGACY ----------------
def test_o_legacy_loan_without_snapshot(su, actors):
    """Loan lama tanpa snapshot: tidak crash, tidak dibuatkan distribusi finansial."""
    loan = submit_loan(actors["borrower"], principal=1_000_000)
    su.post(f"{API}/loans/{loan['id']}/approve", json={"assigned_admin_id": actors["admin"]["id"]}, timeout=30)
    MONGO.loans.update_one(
        {"_id": loan["id"]},
        {"$unset": {
            "profit_share_lender_pct_snapshot": "",
            "profit_share_admin_pct_snapshot": "",
            "profit_share_platform_pct_snapshot": "",
            "assigned_admin_id": "",
        }},
    )
    detail = su.get(f"{API}/loans/{loan['id']}", timeout=30).json()
    assert detail["profit_share"]["has_snapshot"] is False

    # lifecycle sampai PAID tetap berjalan
    actors["lender"]["session"].post(f"{API}/loans/{loan['id']}/claim", timeout=30)
    actors["lender"]["session"].post(
        f"{API}/loans/{loan['id']}/disburse",
        data={"amount": 1_000_000, "transfer_at": "2026-06-01T10:00", "notes": ""},
        files=proof_files(), timeout=60,
    )
    su.post(f"{API}/loans/{loan['id']}/confirm-disbursement", timeout=30)
    total = actors["borrower"]["session"].get(f"{API}/loans/{loan['id']}", timeout=30).json()["total_due"]
    pay = actors["borrower"]["session"].post(
        f"{API}/loans/{loan['id']}/pay",
        data={"amount": total, "paid_at": "2026-06-20T10:00", "notes": ""},
        files=proof_files(), timeout=60,
    ).json()
    pid = [x for x in pay["payments"] if x["status"] == "PENDING"][0]["id"]
    v = actors["lender"]["session"].post(f"{API}/payments/{pid}/verify", timeout=60)
    assert v.status_code == 200, v.text
    assert MONGO.profit_distributions.count_documents({"loan_id": loan["id"]}) == 0
    assert MONGO.loans.find_one({"_id": loan["id"]}).get("profit_share_legacy") is True


def test_o2_snapshot_without_admin_blocks_paid_and_backfill(su, actors):
    """Ada snapshot tapi assigned_admin_id hilang -> transisi PAID diblokir; migrasi melengkapi."""
    loan = submit_loan(actors["borrower"], principal=1_000_000)
    su.post(f"{API}/loans/{loan['id']}/approve", json={"assigned_admin_id": actors["admin"]["id"]}, timeout=30)
    MONGO.loans.update_one({"_id": loan["id"]}, {"$unset": {"assigned_admin_id": ""}})
    actors["lender"]["session"].post(f"{API}/loans/{loan['id']}/claim", timeout=30)
    actors["lender"]["session"].post(
        f"{API}/loans/{loan['id']}/disburse",
        data={"amount": 1_000_000, "transfer_at": "2026-06-01T10:00", "notes": ""},
        files=proof_files(), timeout=60,
    )
    su.post(f"{API}/loans/{loan['id']}/confirm-disbursement", timeout=30)
    total = actors["borrower"]["session"].get(f"{API}/loans/{loan['id']}", timeout=30).json()["total_due"]
    pay = actors["borrower"]["session"].post(
        f"{API}/loans/{loan['id']}/pay",
        data={"amount": total, "paid_at": "2026-06-20T10:00", "notes": ""},
        files=proof_files(), timeout=60,
    ).json()
    pid = [x for x in pay["payments"] if x["status"] == "PENDING"][0]["id"]
    blocked = actors["lender"]["session"].post(f"{API}/payments/{pid}/verify", timeout=30)
    assert blocked.status_code == 409 and "Admin penanggung jawab" in blocked.text
    assert MONGO.loans.find_one({"_id": loan["id"]})["status"] != "PAID"

    r = su.put(
        f"{API}/loans/{loan['id']}/assigned-admin",
        json={"admin_id": actors["admin2"]["id"], "reason": "Menetapkan penanggung jawab pinjaman lama"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    ok = actors["lender"]["session"].post(f"{API}/payments/{pid}/verify", timeout=60)
    assert ok.status_code == 200, ok.text
    d = MONGO.profit_distributions.find_one({"loan_id": loan["id"]})
    assert d and d["assigned_admin_id"] == actors["admin2"]["id"]


def test_p_reversal(su, actors):
    set_pcts(su, 60, 25, 15)
    loan = submit_loan(actors["borrower"], principal=1_000_000)
    to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"])
    d = distribution_of(su, loan["id"])
    assert su.post(f"{API}/profit-distributions/{d['id']}/reverse", json={"reason": "salah"}, timeout=30).status_code == 422
    r = su.post(f"{API}/profit-distributions/{d['id']}/reverse", json={"reason": "Kesalahan sistem pada pencatatan"}, timeout=30)
    assert r.status_code == 200 and r.json()["is_reversed"] is True
    assert su.post(f"{API}/profit-distributions/{d['id']}/reverse", json={"reason": "Kesalahan sistem pada pencatatan"}, timeout=30).status_code == 409
    listed = su.get(f"{API}/profit-distributions", params={"page_size": 100}, timeout=30).json()
    assert d["id"] not in [i["id"] for i in listed["items"]]
    with_rev = su.get(f"{API}/profit-distributions", params={"page_size": 100, "include_reversed": True}, timeout=30).json()
    assert d["id"] in [i["id"] for i in with_rev["items"]]
    assert MONGO.profit_distributions.find_one({"_id": d["id"]}) is not None  # tidak dihapus


def test_q_factory_reset_covers_new_data():
    """Verifikasi konfigurasi Factory Reset (tanpa mengeksekusi reset destruktif di preview)."""
    import sys

    sys.path.insert(0, "/app/backend")
    import admin_routes

    assert "profit_distributions" in admin_routes.WIPE_COLLECTIONS
    src = Path("/app/backend/admin_routes.py").read_text()
    assert "settlement_proofs" in src and "admin_payout_proofs" in src
    assert "purge_prefix" in src  # menghapus seluruh object prefix termasuk bukti settlement & payout
    import core

    assert core.DEFAULT_SETTINGS["profit_share_lender_pct"] == 60.0
    assert core.DEFAULT_SETTINGS["profit_share_admin_pct"] == 25.0
    assert core.DEFAULT_SETTINGS["profit_share_platform_pct"] == 15.0
    assert core.DEFAULT_SETTINGS["settlement_account_number"] is None


def test_r_indexes_exist():
    idx = MONGO.profit_distributions.index_information()
    assert any(v.get("unique") and v["key"][0][0] == "loan_id" for v in idx.values())
    keys = {v["key"][0][0] for v in idx.values()}
    for field in ("lender_id", "assigned_admin_id", "created_at", "lender_settlement_status", "admin_payout_status"):
        assert field in keys
