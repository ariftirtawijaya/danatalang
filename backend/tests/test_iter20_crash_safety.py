"""Iteration 20: crash-safety (transaction jika tersedia + idempotent recovery),
cancel PREPARED remittance, dan pengamanan endpoint /finalize."""
import sys
import uuid
import pytest
import requests

sys.path.insert(0, "/app/backend")

from test_iter16_profit_sharing import API, MONGO, actors, su, loan_rates, sess, login, set_pcts  # noqa: E402,F401
from test_iter17_profit_hardening import wide_borrower_limit  # noqa: E402,F401
from test_iter19_admin_collection import activate_loan, collect, rates_and_bank  # noqa: E402,F401


def _recover(su):
    r = su.post(f"{API}/admin-remittances/recover-stale", timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- 1. crash-safe admin collection ----------
def test_recovery_forwards_pending_collection(su, actors):
    """Crash setelah payment PENDING dibuat tapi loan belum berpindah -> recovery melanjutkan."""
    lid = activate_loan(su, actors)
    r = collect(actors["admin"]["session"], lid)
    assert r.status_code == 200
    pid = r.json()["id"]
    # simulasi crash: kembalikan state ke tengah proses
    MONGO.payments.update_one({"_id": pid}, {"$set": {"commit_state": "PENDING",
                                                      "created_at": "2020-01-01T00:00:00+00:00"}})
    MONGO.loans.update_one({"_id": lid}, {"$set": {"status": "ACTIVE"},
                                          "$unset": {"collected_at": "", "collected_by": ""}})
    out = _recover(su)
    assert out["committed"] >= 1
    p = MONGO.payments.find_one({"_id": pid})
    assert p["commit_state"] == "COMMITTED"
    assert MONGO.loans.find_one({"_id": lid})["status"] == "PAYMENT_COLLECTED"


def test_pending_collection_hidden_and_aborted_when_loan_paid(su, actors):
    """Payment PENDING tidak boleh tampil di daftar; bila loan tidak lagi valid -> di-abort."""
    lid = activate_loan(su, actors)
    pid = collect(actors["admin"]["session"], lid).json()["id"]
    # created_at masih baru -> lease belum lewat, recovery tidak menyentuh; item wajib disembunyikan
    MONGO.payments.update_one({"_id": pid}, {"$set": {"commit_state": "PENDING"}})
    items = actors["admin"]["session"].get(f"{API}/admin-collections", timeout=30).json()["items"]
    assert pid not in [i["id"] for i in items], "koleksi PENDING tidak boleh terlihat"
    MONGO.payments.update_one({"_id": pid}, {"$set": {"created_at": "2020-01-01T00:00:00+00:00"}})
    # loan tidak lagi valid untuk penerimaan ini (dan tidak berkorelasi dengan payment tsb)
    MONGO.loans.update_one({"_id": lid}, {"$set": {"status": "PAID"}, "$unset": {"collection_payment_id": ""}})
    out = _recover(su)
    assert out["aborted"] >= 1
    p = MONGO.payments.find_one({"_id": pid})
    assert p["commit_state"] == "ABORTED" and p["collection_status"] == "REVERSED"


def test_no_orphan_loan_collected_without_payment(su, actors):
    """Invariant: tidak boleh ada loan PAYMENT_COLLECTED tanpa record payment ADMIN_COLLECTION."""
    for loan in MONGO.loans.find({"status": "PAYMENT_COLLECTED"}):
        p = MONGO.payments.find_one({"loan_id": loan["_id"], "payment_channel": "ADMIN_COLLECTION",
                                     "collection_status": {"$ne": "REVERSED"}})
        assert p, f"loan {loan.get('loan_number')} collected tanpa payment"


# ---------- 2. crash-safe bulk reservation ----------
def _prepare(session, ids):
    return session.post(f"{API}/admin-remittances", json={"collection_ids": ids}, timeout=60)


def test_stale_preparing_with_all_items_is_forwarded(su, actors):
    lid = activate_loan(su, actors)
    cid = collect(actors["admin"]["session"], lid).json()["id"]
    rem = _prepare(actors["admin"]["session"], [cid]).json()
    rid = rem["id"]
    assert rem["status"] == "PREPARED"
    # simulasi crash tepat sebelum PREPARING -> PREPARED
    MONGO.admin_remittances.update_one({"_id": rid}, {"$set": {"status": "PREPARING", "item_count": 0,
                                                               "total_amount": 0,
                                                               "created_at": "2020-01-01T00:00:00+00:00"}})
    out = _recover(su)
    assert out["prepare_finished"] >= 1
    fresh = MONGO.admin_remittances.find_one({"_id": rid})
    assert fresh["status"] == "PREPARED" and fresh["item_count"] == 1 and fresh["total_amount"] > 0


def test_stale_preparing_partial_reservation_is_rolled_back(su, actors):
    lid1 = activate_loan(su, actors)
    lid2 = activate_loan(su, actors)
    c1 = collect(actors["admin"]["session"], lid1).json()["id"]
    c2 = collect(actors["admin"]["session"], lid2).json()["id"]
    rid = _prepare(actors["admin"]["session"], [c1, c2]).json()["id"]
    # crash di tengah reservasi: hanya 1 item ter-reserve
    MONGO.payments.update_one({"_id": c2}, {"$set": {"remittance_id": None, "remittance_number": None,
                                                     "collection_status": "COLLECTED"},
                                            "$unset": {"reservation_token": "", "reserved_at": ""}})
    MONGO.admin_remittances.update_one({"_id": rid}, {"$set": {"status": "PREPARING",
                                                               "created_at": "2020-01-01T00:00:00+00:00"}})
    out = _recover(su)
    assert out["prepare_cancelled"] >= 1
    assert MONGO.admin_remittances.find_one({"_id": rid})["status"] == "CANCELLED"
    for cid in (c1, c2):
        p = MONGO.payments.find_one({"_id": cid})
        assert p["collection_status"] == "COLLECTED" and not p.get("remittance_id"), "item harus dilepas"


def test_orphan_reserved_item_released(su, actors):
    lid = activate_loan(su, actors)
    cid = collect(actors["admin"]["session"], lid).json()["id"]
    rid = _prepare(actors["admin"]["session"], [cid]).json()["id"]
    MONGO.admin_remittances.delete_one({"_id": rid})   # parent hilang total
    out = _recover(su)
    assert out["orphans_released"] >= 1
    p = MONGO.payments.find_one({"_id": cid})
    assert p["collection_status"] == "COLLECTED" and not p.get("remittance_id")


def test_valid_prepared_reservation_never_released(su, actors):
    """Reservasi PREPARED yang sah tidak boleh dilepas hanya karena sudah lama."""
    lid = activate_loan(su, actors)
    cid = collect(actors["admin"]["session"], lid).json()["id"]
    rid = _prepare(actors["admin"]["session"], [cid]).json()["id"]
    MONGO.admin_remittances.update_one({"_id": rid}, {"$set": {"created_at": "2020-01-01T00:00:00+00:00"}})
    _recover(su)
    assert MONGO.admin_remittances.find_one({"_id": rid})["status"] == "PREPARED"
    p = MONGO.payments.find_one({"_id": cid})
    assert p["collection_status"] == "RESERVED" and p["remittance_id"] == rid


def test_preparing_is_hidden_from_list(su, actors):
    lid = activate_loan(su, actors)
    cid = collect(actors["admin"]["session"], lid).json()["id"]
    rid = _prepare(actors["admin"]["session"], [cid]).json()["id"]
    MONGO.admin_remittances.update_one({"_id": rid}, {"$set": {"status": "PREPARING"}})
    items = su.get(f"{API}/admin-remittances", timeout=30).json()["items"]
    assert rid not in [i["id"] for i in items]
    MONGO.admin_remittances.update_one({"_id": rid}, {"$set": {"status": "PREPARED"}})


def test_recover_stale_requires_superadmin(actors):
    for role in ("admin", "lender", "borrower"):
        r = actors[role]["session"].post(f"{API}/admin-remittances/recover-stale", timeout=30)
        assert r.status_code == 403, f"{role}: {r.status_code}"
    assert requests.post(f"{API}/admin-remittances/recover-stale", timeout=30).status_code == 401


# ---------- 3. cancel PREPARED remittance ----------
def test_cancel_prepared_releases_items_and_keeps_audit(su, actors):
    lid = activate_loan(su, actors)
    cid = collect(actors["admin"]["session"], lid).json()["id"]
    rid = _prepare(actors["admin"]["session"], [cid]).json()["id"]

    assert actors["admin"]["session"].post(f"{API}/admin-remittances/{rid}/cancel",
                                          json={"reason": "abcd"}, timeout=30).status_code == 422
    r = actors["admin"]["session"].post(f"{API}/admin-remittances/{rid}/cancel",
                                        json={"reason": "salah pilih penerimaan"}, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CANCELLED"
    p = MONGO.payments.find_one({"_id": cid})
    assert p["collection_status"] == "COLLECTED" and not p.get("remittance_id")
    assert MONGO.admin_remittances.find_one({"_id": rid}), "record CANCELLED tetap disimpan untuk audit"
    assert MONGO.audit_logs.find_one({"action": "ADMIN_REMITTANCE_CANCELLED", "entity_id": rid})
    # tidak bisa dibatalkan dua kali / tidak bisa dikirim lagi
    assert actors["admin"]["session"].post(f"{API}/admin-remittances/{rid}/cancel",
                                           json={"reason": "coba lagi"}, timeout=30).status_code == 409
    # item bisa dipakai untuk setoran baru
    assert _prepare(actors["admin"]["session"], [cid]).status_code == 200


def test_cancel_rbac_and_state_guards(su, actors, tmp_path):
    lid = activate_loan(su, actors)
    cid = collect(actors["admin"]["session"], lid).json()["id"]
    rid = _prepare(actors["admin"]["session"], [cid]).json()["id"]
    for role in ("lender", "borrower"):
        r = actors[role]["session"].post(f"{API}/admin-remittances/{rid}/cancel",
                                         json={"reason": "tidak boleh"}, timeout=30)
        assert r.status_code == 403, f"{role} tidak boleh cancel: {r.status_code}"
    assert requests.post(f"{API}/admin-remittances/{rid}/cancel", json={"reason": "tanpa auth"},
                         timeout=30).status_code == 401
    # Superadmin boleh cancel
    assert su.post(f"{API}/admin-remittances/{rid}/cancel", json={"reason": "koreksi operasional"},
                   timeout=30).status_code == 200

    # remittance yang sudah dikirim tidak boleh dicancel
    rid2 = _prepare(actors["admin"]["session"], [cid]).json()["id"]
    files = {"proof": ("p.png", b"\x89PNG\r\n\x1a\n" + b"0" * 200, "image/png")}
    assert actors["admin"]["session"].post(f"{API}/admin-remittances/{rid2}/submit", files=files,
                                          timeout=60).status_code == 200
    assert actors["admin"]["session"].post(f"{API}/admin-remittances/{rid2}/cancel",
                                           json={"reason": "sudah dikirim"}, timeout=30).status_code == 409


def test_admin_cannot_cancel_other_admin_remittance(su, actors):
    from test_iter16_profit_sharing import create_staff
    other = create_staff(su, "admin", 91, "Admin Kedua")
    lid = activate_loan(su, actors)
    cid = collect(actors["admin"]["session"], lid).json()["id"]
    rid = _prepare(actors["admin"]["session"], [cid]).json()["id"]
    r = other["session"].post(f"{API}/admin-remittances/{rid}/cancel", json={"reason": "bukan milik saya"}, timeout=30)
    assert r.status_code == 403, r.text


# ---------- 4. /finalize security ----------
def test_finalize_cannot_bypass_lender_verification(su, actors):
    lid = activate_loan(su, actors)
    cid = collect(actors["admin"]["session"], lid).json()["id"]
    rid = _prepare(actors["admin"]["session"], [cid]).json()["id"]

    # PREPARED -> tidak boleh finalize
    assert su.post(f"{API}/admin-remittances/{rid}/finalize", timeout=30).status_code == 409
    files = {"proof": ("p.png", b"\x89PNG\r\n\x1a\n" + b"0" * 200, "image/png")}
    actors["admin"]["session"].post(f"{API}/admin-remittances/{rid}/submit", files=files, timeout=60)
    # WAITING_VERIFICATION -> tetap tidak boleh finalize (harus verifikasi Pendana)
    assert su.post(f"{API}/admin-remittances/{rid}/finalize", timeout=30).status_code == 409
    assert MONGO.loans.find_one({"_id": lid})["status"] == "PAYMENT_COLLECTED"
    # RBAC
    assert requests.post(f"{API}/admin-remittances/{rid}/finalize", timeout=30).status_code == 401
    assert actors["admin"]["session"].post(f"{API}/admin-remittances/{rid}/finalize", timeout=30).status_code == 403
    assert actors["borrower"]["session"].post(f"{API}/admin-remittances/{rid}/finalize", timeout=30).status_code == 403

    # Pendana lain tidak boleh
    from test_iter16_profit_sharing import create_staff
    other = create_staff(su, "lender", 92, "Pendana Lain")
    assert other["session"].post(f"{API}/admin-remittances/{rid}/finalize", timeout=30).status_code == 403

    # setelah state VERIFYING (crash saat verifikasi Pendana) -> recovery boleh dilanjutkan
    MONGO.admin_remittances.update_one({"_id": rid}, {"$set": {"status": "VERIFYING"}})
    r = su.post(f"{API}/admin-remittances/{rid}/finalize", timeout=60)
    assert r.status_code == 200, r.text
    assert MONGO.loans.find_one({"_id": lid})["status"] == "PAID"
    assert MONGO.admin_remittances.find_one({"_id": rid})["status"] == "VERIFIED"
    # idempoten
    assert su.post(f"{API}/admin-remittances/{rid}/finalize", timeout=60).status_code == 200


def test_lender_verify_resumes_stuck_verifying(su, actors):
    lid = activate_loan(su, actors)
    cid = collect(actors["admin"]["session"], lid).json()["id"]
    rid = _prepare(actors["admin"]["session"], [cid]).json()["id"]
    files = {"proof": ("p.png", b"\x89PNG\r\n\x1a\n" + b"0" * 200, "image/png")}
    actors["admin"]["session"].post(f"{API}/admin-remittances/{rid}/submit", files=files, timeout=60)
    MONGO.admin_remittances.update_one({"_id": rid}, {"$set": {"status": "VERIFYING"}})
    r = actors["lender"]["session"].post(f"{API}/admin-remittances/{rid}/verify", timeout=60)
    assert r.status_code == 200, r.text
    assert MONGO.loans.find_one({"_id": lid})["status"] == "PAID"


# ---------- 5. fallback NON-TRANSACTION: crash tepat saat mark COMMITTED ----------
def _assert_fallback_mode(su):
    mode = su.post(f"{API}/admin-remittances/recover-stale", timeout=60).json()["transaction_mode"]
    if mode:
        pytest.skip("environment mendukung transaction; jalur fallback tidak aktif")


def test_non_tx_crash_at_mark_committed_keeps_payment(su, actors):
    """Loan sudah diklaim (collection_payment_id) tapi payment belum COMMITTED:
    payment TIDAK boleh hilang, recovery harus meneruskannya."""
    _assert_fallback_mode(su)
    lid = activate_loan(su, actors)
    c = collect(actors["admin"]["session"], lid).json()
    pid = c["id"]
    loan = MONGO.loans.find_one({"_id": lid})
    assert loan["collection_payment_id"] == pid, "loan harus menyimpan korelasi payment pengklaim"

    # simulasi exception tepat saat mark COMMITTED (loan sudah berpindah + terklaim)
    MONGO.payments.update_one({"_id": pid}, {"$set": {"commit_state": "PENDING",
                                                      "created_at": "2020-01-01T00:00:00+00:00"}})
    before = MONGO.payments.find_one({"_id": pid})

    out = _recover(su)
    assert out["committed"] >= 1 and out["aborted"] == 0
    after = MONGO.payments.find_one({"_id": pid})
    fresh = MONGO.loans.find_one({"_id": lid})
    assert fresh["status"] == "PAYMENT_COLLECTED"
    assert fresh["collection_payment_id"] == pid
    assert after["commit_state"] == "COMMITTED" and after["collection_status"] == "COLLECTED"
    for k in ("principal_snapshot", "interest_snapshot", "late_days_snapshot", "late_fee_snapshot",
              "total_collected", "collection_number"):
        assert after[k] == before[k], f"snapshot {k} berubah"
    cols = list(MONGO.payments.find({"loan_id": lid, "payment_channel": "ADMIN_COLLECTION",
                                     "collection_status": {"$ne": "REVERSED"}}))
    assert len(cols) == 1, "tidak boleh ada duplikasi COL"


def test_non_tx_concurrent_loser_never_committed(su, actors):
    """Loser concurrent (payment PENDING yang tidak mengklaim loan) tidak boleh di-commit."""
    _assert_fallback_mode(su)
    lid = activate_loan(su, actors)
    winner = collect(actors["admin"]["session"], lid).json()
    a = winner["id"]
    assert MONGO.loans.find_one({"_id": lid})["collection_payment_id"] == a

    # loser B: payment PENDING untuk loan yang sama (seolah request paralel yang kalah)
    b = str(uuid.uuid4())
    doc = dict(MONGO.payments.find_one({"_id": a}))
    doc.update({"_id": b, "commit_state": "PENDING",
                "created_at": "2020-01-01T00:00:00+00:00",
                "collection_number": f"COL-LOSER-{uuid.uuid4().hex[:8]}"})
    MONGO.payments.insert_one(doc)

    out = _recover(su)
    assert out["aborted"] >= 1
    pb = MONGO.payments.find_one({"_id": b})
    assert pb["commit_state"] == "ABORTED" and pb["collection_status"] == "REVERSED"
    pa = MONGO.payments.find_one({"_id": a})
    assert pa["commit_state"] == "COMMITTED" and pa["collection_status"] == "COLLECTED"
    fresh = MONGO.loans.find_one({"_id": lid})
    assert fresh["collection_payment_id"] == a and fresh["status"] == "PAYMENT_COLLECTED"
    valid = list(MONGO.payments.find({"loan_id": lid, "payment_channel": "ADMIN_COLLECTION",
                                      "collection_status": {"$ne": "REVERSED"}}))
    assert len(valid) == 1 and str(valid[0]["_id"]) == a


def test_reversal_unsets_collection_payment_id(su, actors):
    _assert_fallback_mode(su)
    lid = activate_loan(su, actors)
    pid = collect(actors["admin"]["session"], lid).json()["id"]
    r = su.post(f"{API}/admin-collections/{pid}/reverse",
                json={"reason": "pembatalan uji regresi korelasi payment id", "confirmation": "BATALKAN PENERIMAAN"},
                timeout=30)
    assert r.status_code == 200, r.text
    loan = MONGO.loans.find_one({"_id": lid})
    assert "collection_payment_id" not in loan, "korelasi wajib di-unset saat reversal"
    assert loan["status"] in ("ACTIVE", "OVERDUE")
    # loan bisa di-collect ulang tanpa konflik
    r2 = collect(actors["admin"]["session"], lid)
    assert r2.status_code == 200, r2.text
    assert MONGO.loans.find_one({"_id": lid})["collection_payment_id"] == r2.json()["id"]


def test_no_collected_loan_without_valid_payment_correlation(su, actors):
    """Invariant global: setiap loan PAYMENT_COLLECTED punya payment valid yang berkorelasi."""
    for loan in MONGO.loans.find({"status": "PAYMENT_COLLECTED"}):
        pid = loan.get("collection_payment_id")
        if not pid:
            continue   # data lama sebelum korelasi diperkenalkan
        p = MONGO.payments.find_one({"_id": pid})
        assert p, f"loan {loan.get('loan_number')} menunjuk payment yang hilang"
        assert p.get("collection_status") != "REVERSED" and p.get("commit_state") != "ABORTED"
