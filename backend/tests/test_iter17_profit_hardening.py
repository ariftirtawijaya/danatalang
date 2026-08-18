"""Iteration 17: hardening modul bagi hasil.

1. Reversal guard (SETTLED / payout PAID → 409) + koreksi finansial eksplisit
2. Rekening payout Admin wajib lengkap
3. Factory Reset integration test TERISOLASI (subprocess, DB + bucket + prefix khusus test)
4. Riwayat attempt settlement immutable
"""
import json
import subprocess
import sys
import pytest
import requests

from test_iter16_profit_sharing import (  # noqa: E402
    API, MONGO, PASS, actors, su, loan_rates, sess, login, new_phone, proof_files,
    submit_loan, to_paid, distribution_of, set_pcts, create_staff, create_borrower, CREATED_PHONES,
)


@pytest.fixture(scope="module", autouse=True)
def wide_borrower_limit(su, actors):
    """Iterasi ini membuat banyak pinjaman; naikkan batas pinjaman aktif peminjam uji."""
    MONGO.users.update_one(
        {"_id": actors["borrower"]["id"]},
        {"$set": {"borrower_limit": 500_000_000, "max_duration_days": 120, "max_active_loans": 99}},
    )
    yield


def _dist_to_settled(su, actors, admin_id=None):
    loan = submit_loan(actors["borrower"], principal=2_000_000)
    to_paid(actors, su, loan["id"], assigned_admin_id=admin_id or actors["admin"]["id"])
    d = distribution_of(su, loan["id"])
    r = actors["lender"]["session"].post(f"{API}/profit-distributions/{d['id']}/settlement", files=proof_files(), timeout=60)
    assert r.status_code == 200, r.text
    r = su.post(f"{API}/profit-distributions/{d['id']}/settlement/verify", timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------- 1. REVERSAL GUARD ----------------
def test_reversal_blocked_when_waiting_verification(su, actors):
    loan = submit_loan(actors["borrower"], principal=1_500_000)
    to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"])
    d = distribution_of(su, loan["id"])
    actors["lender"]["session"].post(f"{API}/profit-distributions/{d['id']}/settlement", files=proof_files(), timeout=60)
    r = su.post(f"{API}/profit-distributions/{d['id']}/reverse", json={"reason": "Uji guard reversal menunggu verifikasi"}, timeout=30)
    assert r.status_code == 409 and "Tolak setoran" in r.text
    assert MONGO.profit_distributions.find_one({"_id": d["id"]}).get("is_reversed") is not True


def test_reversal_blocked_when_settled(su, actors):
    d = _dist_to_settled(su, actors)
    r = su.post(f"{API}/profit-distributions/{d['id']}/reverse", json={"reason": "Uji guard reversal setelah settled"}, timeout=30)
    assert r.status_code == 409 and "Koreksi Finansial" in r.text
    assert MONGO.profit_distributions.find_one({"_id": d["id"]}).get("is_reversed") is not True


def test_reversal_blocked_when_payout_paid(su, actors):
    d = _dist_to_settled(su, actors)
    paid = su.post(f"{API}/profit-distributions/{d['id']}/admin-payout/mark-paid", files=proof_files(), timeout=60)
    assert paid.status_code == 200 and paid.json()["admin_payout_status"] == "PAID"
    r = su.post(f"{API}/profit-distributions/{d['id']}/reverse", json={"reason": "Uji guard reversal setelah payout"}, timeout=30)
    assert r.status_code == 409 and "sudah DIBAYAR" in r.text
    assert MONGO.profit_distributions.find_one({"_id": d["id"]}).get("is_reversed") is not True


def test_financial_correction_flow(su, actors):
    d = _dist_to_settled(su, actors)
    url = f"{API}/profit-distributions/{d['id']}/financial-correction"
    good_reason = "Koreksi karena pembayaran peminjam tercatat ganda pada sistem lama"
    # validasi input
    assert su.post(url, json={"reason": "pendek", "confirmation": "KOREKSI FINANSIAL", "acknowledge_funds_moved": True}, timeout=30).status_code == 422
    assert su.post(url, json={"reason": good_reason, "confirmation": "salah", "acknowledge_funds_moved": True}, timeout=30).status_code == 400
    assert su.post(url, json={"reason": good_reason, "confirmation": "KOREKSI FINANSIAL", "acknowledge_funds_moved": False}, timeout=30).status_code == 400
    # RBAC
    for actor in ("admin", "lender", "borrower"):
        assert actors[actor]["session"].post(
            url, json={"reason": good_reason, "confirmation": "KOREKSI FINANSIAL", "acknowledge_funds_moved": True}, timeout=30
        ).status_code == 403
    # sukses
    r = su.post(url, json={"reason": good_reason, "confirmation": "KOREKSI FINANSIAL", "acknowledge_funds_moved": True}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_reversed"] is True and body["reversal_type"] == "FINANCIAL_CORRECTION"
    assert body["correction_settlement_status_at_correction"] == "SETTLED"
    # tidak dobel & tidak menghapus histori
    assert su.post(url, json={"reason": good_reason, "confirmation": "KOREKSI FINANSIAL", "acknowledge_funds_moved": True}, timeout=30).status_code == 409
    assert MONGO.profit_distributions.find_one({"_id": d["id"]}) is not None
    assert MONGO.audit_logs.find_one({"action": "PROFIT_DISTRIBUTION_CORRECTED", "entity_id": d["id"]})
    listed = su.get(f"{API}/profit-distributions", params={"page_size": 100}, timeout=30).json()
    assert d["id"] not in [i["id"] for i in listed["items"]]


def test_financial_correction_rejected_when_no_money_moved(su, actors):
    loan = submit_loan(actors["borrower"], principal=1_300_000)
    to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"])
    d = distribution_of(su, loan["id"])
    r = su.post(
        f"{API}/profit-distributions/{d['id']}/financial-correction",
        json={"reason": "Mencoba koreksi padahal belum ada perpindahan uang", "confirmation": "KOREKSI FINANSIAL",
              "acknowledge_funds_moved": True},
        timeout=30,
    )
    assert r.status_code == 409 and "reversal biasa" in r.text.lower()
    # reversal biasa tetap boleh pada status PENDING
    ok = su.post(f"{API}/profit-distributions/{d['id']}/reverse", json={"reason": "Pembatalan karena salah input data"}, timeout=30)
    assert ok.status_code == 200 and ok.json()["reversal_type"] == "REVERSAL"


# ---------------- 2. REKENING PAYOUT ADMIN ----------------
@pytest.fixture(scope="module")
def admin_no_bank(su):
    """Admin dibuat tanpa rekening payout (rekening Admin opsional saat pembuatan akun)."""
    phone = new_phone(9)
    CREATED_PHONES.append(phone)
    r = su.post(
        f"{API}/users",
        json={"full_name": "Admin Tanpa Rekening", "phone": phone, "email": f"nobank{phone}@danatalang-test.com",
              "password": PASS, "role": "admin"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    uid = MONGO.users.find_one({"phone": phone})["_id"]
    admin_doc = MONGO.users.find_one({"_id": uid})
    assert not admin_doc.get("account_number")
    yield {"id": uid, "phone": phone}
    MONGO.users.delete_many({"phone": phone})


def test_admin_payout_requires_complete_bank_account(su, actors, admin_no_bank):
    d = _dist_to_settled(su, actors, admin_id=admin_no_bank["id"])
    assert d["admin_bank"]["complete"] is False
    r = su.post(f"{API}/profit-distributions/{d['id']}/admin-payout/mark-paid", files=proof_files(), timeout=60)
    assert r.status_code == 409 and "Rekening payout Admin belum lengkap" in r.text
    assert MONGO.profit_distributions.find_one({"_id": d["id"]})["admin_payout_status"] == "PENDING"

    MONGO.users.update_one(
        {"_id": admin_no_bank["id"]},
        {"$set": {"bank_name": "BCA", "account_number": "555444333", "account_holder": "ADMIN TANPA REKENING"}},
    )
    detail = su.get(f"{API}/profit-distributions/{d['id']}", timeout=30).json()
    assert detail["admin_bank"]["complete"] is True
    assert detail["admin_bank"]["account_number"] == "555444333"
    ok = su.post(f"{API}/profit-distributions/{d['id']}/admin-payout/mark-paid", files=proof_files(), timeout=60)
    assert ok.status_code == 200, ok.text
    assert ok.json()["admin_payout_status"] == "PAID" and ok.json()["admin_payout_amount"] == detail["admin_profit"]


# ---------------- 4. SETTLEMENT ATTEMPT HISTORY ----------------
def test_settlement_attempt_history_immutable(su, actors):
    loan = submit_loan(actors["borrower"], principal=1_700_000)
    to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"])
    d = distribution_of(su, loan["id"])
    dist_id = d["id"]

    a1 = actors["lender"]["session"].post(f"{API}/profit-distributions/{dist_id}/settlement", files=proof_files(), timeout=60).json()
    proof_a = a1["settlement_proof_file_id"]
    assert a1["settlement_attempt_count"] == 1
    assert a1["settlement_attempts"][0]["attempt_no"] == 1 and a1["settlement_attempts"][0]["status"] == "SUBMITTED"

    rejected = su.post(f"{API}/profit-distributions/{dist_id}/settlement/reject",
                       json={"reason": "Bukti transfer tidak terbaca dengan jelas"}, timeout=30).json()
    assert rejected["lender_settlement_status"] == "PENDING"
    assert rejected["settlement_attempts"][0]["status"] == "REJECTED"
    assert rejected["settlement_attempts"][0]["rejection_reason"] == "Bukti transfer tidak terbaca dengan jelas"
    assert rejected["settlement_attempts"][0]["proof_file_id"] == proof_a

    a2 = actors["lender"]["session"].post(f"{API}/profit-distributions/{dist_id}/settlement", files=proof_files(), timeout=60).json()
    proof_b = a2["settlement_proof_file_id"]
    assert proof_b != proof_a
    assert a2["settlement_attempt_count"] == 2 and len(a2["settlement_attempts"]) == 2

    verified = su.post(f"{API}/profit-distributions/{dist_id}/settlement/verify", timeout=30).json()
    attempts = verified["settlement_attempts"]
    assert verified["lender_settlement_status"] == "SETTLED"
    assert len(attempts) == 2
    # attempt #1 tetap utuh (tidak dioverwrite / dihapus)
    assert attempts[0]["attempt_no"] == 1 and attempts[0]["status"] == "REJECTED"
    assert attempts[0]["rejection_reason"] == "Bukti transfer tidak terbaca dengan jelas"
    assert attempts[0]["proof_file_id"] == proof_a
    assert attempts[1]["attempt_no"] == 2 and attempts[1]["status"] == "VERIFIED" and attempts[1]["verified_at"]
    assert attempts[1]["proof_file_id"] == proof_b
    assert all(a["amount"] == verified["lender_settlement_due"] for a in attempts)

    # bukti attempt lama tetap dapat diaudit Superadmin & pemiliknya, tetap tertutup untuk pihak lain
    assert su.get(f"{API}/files/{proof_a}", timeout=30).status_code == 200
    assert actors["lender"]["session"].get(f"{API}/files/{proof_a}", timeout=30).status_code == 200
    assert actors["lender2"]["session"].get(f"{API}/files/{proof_a}", timeout=30).status_code == 403
    assert actors["borrower"]["session"].get(f"{API}/files/{proof_a}", timeout=30).status_code == 403
    assert requests.get(f"{API}/files/{proof_a}", timeout=30).status_code == 401
    # audit menyimpan kedua attempt + alasan penolakan
    logs = list(MONGO.audit_logs.find({"entity_id": dist_id}))
    assert len([l for l in logs if l["action"] == "LENDER_SETTLEMENT_SUBMITTED"]) == 2
    assert any(l["action"] == "LENDER_SETTLEMENT_REJECTED" for l in logs)


# ---------------- 3. FACTORY RESET ISOLATED INTEGRATION ----------------
def test_factory_reset_isolated_integration():
    """DB + bucket + prefix khusus test (moto S3 in-process). Data preview tidak tersentuh."""
    proc = subprocess.run(
        [sys.executable, "/app/backend/tests/_factory_reset_isolated.py"],
        capture_output=True, text=True, timeout=240,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    line = [l for l in proc.stdout.splitlines() if l.startswith("FACTORY_RESET_ISOLATED_RESULT")]
    assert line, proc.stdout[-2000:]
    result = json.loads(line[-1].split(" ", 1)[1])
    assert result["storage_mode"] == "s3"
    assert result["before"]["profit_distributions"] == 1
    assert result["before"]["settlement_proofs"] == 1 and result["before"]["admin_payout_proofs"] == 1
    assert result["before"]["storage_objects"] >= 2
    after = result["after"]
    assert after["profit_distributions"] == 0
    assert after["files"] == 0 and after["loans"] == 0
    assert after["storage_objects"] == 0
    assert after["profit_share"] == [60.0, 25.0, 15.0]
    assert after["settlement_account_number"] is None
    assert after["keeper_exists"] is True and after["users"] == 1
    assert result["reset"]["storage"]["remaining_objects"] == 0 and result["reset"]["storage"]["purged"] >= 2
    # database preview tetap ada (tidak tersentuh)
    assert MONGO.name != result["db"]
