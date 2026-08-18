"""Iteration 19: Admin Collection (koleksi lapangan) + Bulk Remittance."""
import concurrent.futures as cf
import io
import json
import subprocess
import sys
import uuid
import pytest
import requests

sys.path.insert(0, "/app/backend")

from test_iter16_profit_sharing import (  # noqa: E402
    API, MONGO, PASS, actors, su, loan_rates, sess, login, new_phone, proof_files, submit_loan, set_pcts,
    create_staff, CREATED_PHONES,
)
from test_iter17_profit_hardening import wide_borrower_limit  # noqa: E402,F401


def activate_loan(su, actors, principal=2_000_000, admin=None, late_days=0):
    admin_id = admin or actors["admin"]["id"]
    loan = submit_loan(actors["borrower"], principal=principal)
    lid = loan["id"]
    assert su.post(f"{API}/loans/{lid}/approve", json={"assigned_admin_id": admin_id}, timeout=30).status_code == 200
    actors["lender"]["session"].post(f"{API}/loans/{lid}/claim", timeout=30)
    actors["lender"]["session"].post(f"{API}/loans/{lid}/disburse",
                                     data={"amount": principal, "transfer_at": "2026-06-01T10:00", "notes": ""},
                                     files=proof_files(), timeout=60)
    assert su.post(f"{API}/loans/{lid}/confirm-disbursement", timeout=30).status_code == 200
    if late_days:
        from datetime import datetime, timezone, timedelta
        MONGO.loans.update_one({"_id": lid}, {"$set": {
            "due_date": (datetime.now(timezone.utc) - timedelta(days=late_days)).isoformat(), "status": "OVERDUE"}})
    return lid


def collect(session, loan_id, method="CASH"):
    return session.post(f"{API}/loans/{loan_id}/collect", data={"collection_method": method}, timeout=60)


@pytest.fixture(scope="module", autouse=True)
def rates_and_bank(su, actors):
    set_pcts(su, 60, 25, 15)
    MONGO.users.update_one({"_id": actors["lender"]["id"]},
                           {"$set": {"bank_name": "BCA", "account_number": "1122334455", "account_holder": "PENDANA SATU"}})
    yield


# ---------------- collect ----------------
def test_collect_active_and_overdue_snapshot(su, actors):
    lid = activate_loan(su, actors)
    r = collect(actors["admin"]["session"], lid)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["collection_number"].startswith("COL-") and c["late_fee_snapshot"] == 0
    assert c["total_collected"] == c["principal_snapshot"] + c["interest_snapshot"]
    assert MONGO.loans.find_one({"_id": lid})["status"] == "PAYMENT_COLLECTED"

    lid2 = activate_loan(su, actors, principal=2_000_000, late_days=5)
    c2 = collect(actors["admin"]["session"], lid2, "TRANSFER_TO_ADMIN").json()
    assert c2["late_days_snapshot"] == 5 and c2["late_fee_snapshot"] == 100_000
    assert c2["total_collected"] == 2_000_000 + 400_000 + 100_000
    assert c2["collection_number"] != c["collection_number"]


def test_collect_rbac_and_guards(su, actors):
    lid = activate_loan(su, actors)
    assert collect(actors["admin2"]["session"], lid).status_code == 403
    assert collect(actors["lender"]["session"], lid).status_code == 403
    assert collect(actors["borrower"]["session"], lid).status_code == 403
    assert requests.post(f"{API}/loans/{lid}/collect", data={"collection_method": "CASH"}, timeout=30).status_code == 401
    # ada pembayaran langsung PENDING -> collection ditolak
    total = actors["borrower"]["session"].get(f"{API}/loans/{lid}", timeout=30).json()["total_due"]
    actors["borrower"]["session"].post(f"{API}/loans/{lid}/pay",
                                       data={"amount": total, "paid_at": "2026-06-20T10:00", "notes": ""},
                                       files=proof_files(), timeout=60)
    r = collect(actors["admin"]["session"], lid)
    assert r.status_code == 409 and ("menunggu verifikasi" in r.text or "tidak dalam status" in r.text)


def test_concurrent_collect_single_success(su, actors):
    lid = activate_loan(su, actors)
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        codes = sorted(pool.map(lambda _: collect(actors["admin"]["session"], lid).status_code, range(3)))
    assert codes.count(200) == 1 and codes.count(409) == 2, codes
    assert MONGO.payments.count_documents({"loan_id": lid, "payment_channel": "ADMIN_COLLECTION"}) == 1


def test_collect_effects_limit_freeze_and_borrower_blocked(su, actors):
    lid = activate_loan(su, actors, principal=2_000_000, late_days=3)
    before = su.get(f"{API}/loans/{lid}", timeout=30).json()["borrower_credit"]
    credit_before, active_before = before["available_limit"], before["active_loans"]

    c = collect(actors["admin"]["session"], lid).json()
    d = su.get(f"{API}/loans/{lid}", timeout=30).json()
    assert d["status"] == "PAYMENT_COLLECTED" and d["payment_frozen"] is True
    assert d["late_days"] == c["late_days_snapshot"] and d["late_fee_amount"] == c["late_fee_snapshot"]
    assert d["borrower_credit"]["available_limit"] > credit_before          # limit kembali
    assert d["borrower_credit"]["active_loans"] == active_before - 1        # tidak lagi dihitung aktif
    assert d["borrower_credit"]["outstanding_principal"] < before["outstanding_principal"]
    assert d["collection"]["collection_number"] == c["collection_number"]
    # borrower tidak bisa bayar lagi
    r = actors["borrower"]["session"].post(f"{API}/loans/{lid}/pay",
                                          data={"amount": c["total_collected"], "paid_at": "2026-06-20T10:00", "notes": ""},
                                          files=proof_files(), timeout=60)
    assert r.status_code == 409
    # denda tidak bertambah walau waktu berjalan (snapshot final)
    MONGO.loans.update_one({"_id": lid}, {"$set": {"due_date": "2020-01-01T00:00:00+00:00"}})
    d2 = su.get(f"{API}/loans/{lid}", timeout=30).json()
    assert d2["late_fee_amount"] == c["late_fee_snapshot"] and d2["total_due"] == c["total_collected"]
    # assigned admin terkunci
    ch = su.put(f"{API}/loans/{lid}/assigned-admin",
                json={"admin_id": actors["admin2"]["id"], "reason": "Percobaan mengubah setelah collection"}, timeout=30)
    assert ch.status_code == 409 and "dana titipan" in ch.text
    # payment channel ADMIN_COLLECTION tidak bisa diverifikasi via endpoint payment normal
    pay = MONGO.payments.find_one({"loan_id": lid, "payment_channel": "ADMIN_COLLECTION"})
    v = actors["lender"]["session"].post(f"{API}/payments/{pay['_id']}/verify", timeout=30)
    assert v.status_code == 409 and "Setoran Admin" in v.text


# ---------------- bulk remittance ----------------
def _fresh_collections(su, actors, n=3, admin=None, principal=1_000_000):
    ids = []
    for _ in range(n):
        lid = activate_loan(su, actors, principal=principal, admin=admin)
        c = collect((actors["admin2"] if admin == actors["admin2"]["id"] else actors["admin"])["session"], lid).json()
        ids.append(c["id"])
    return ids


def test_bulk_prepare_and_totals(su, actors):
    ids = _fresh_collections(su, actors, 3)
    r = actors["admin"]["session"].post(f"{API}/admin-remittances", json={"collection_ids": ids[:2]}, timeout=60)
    assert r.status_code == 200, r.text
    rem = r.json()
    assert rem["remittance_number"].startswith("REM-")
    assert rem["item_count"] == 2 and rem["status"] == "PREPARED"
    expected = sum(MONGO.payments.find_one({"_id": i})["total_collected"] for i in ids[:2])
    assert rem["total_amount"] == expected == rem["computed_total"]
    assert rem["lender_bank"]["account_number"] == "1122334455"
    # partial selection: sisa tetap bisa dibuat batch lain
    r2 = actors["admin"]["session"].post(f"{API}/admin-remittances", json={"collection_ids": [ids[2]]}, timeout=60)
    assert r2.status_code == 200
    # collection tidak bisa masuk dua remittance
    dup = actors["admin"]["session"].post(f"{API}/admin-remittances", json={"collection_ids": [ids[0]]}, timeout=60)
    assert dup.status_code == 409
    # admin lain tidak bisa memakai collection ini
    assert actors["admin2"]["session"].post(f"{API}/admin-remittances", json={"collection_ids": [ids[0]]}, timeout=30).status_code in (403, 409)


def test_bulk_multi_lender_rejected(su, actors):
    lid = activate_loan(su, actors, principal=1_000_000)
    c1 = collect(actors["admin"]["session"], lid).json()
    # collection kedua dengan lender berbeda
    lid2 = submit_loan(actors["borrower"], principal=1_000_000)["id"]
    su.post(f"{API}/loans/{lid2}/approve", json={"assigned_admin_id": actors["admin"]["id"]}, timeout=30)
    actors["lender2"]["session"].post(f"{API}/loans/{lid2}/claim", timeout=30)
    actors["lender2"]["session"].post(f"{API}/loans/{lid2}/disburse",
                                      data={"amount": 1_000_000, "transfer_at": "2026-06-01T10:00", "notes": ""},
                                      files=proof_files(), timeout=60)
    su.post(f"{API}/loans/{lid2}/confirm-disbursement", timeout=30)
    c2 = collect(actors["admin"]["session"], lid2).json()
    r = actors["admin"]["session"].post(f"{API}/admin-remittances", json={"collection_ids": [c1["id"], c2["id"]]}, timeout=60)
    assert r.status_code == 400 and "satu Pendana" in r.text
    # tidak ada collection yang terkunci akibat kegagalan
    assert MONGO.payments.find_one({"_id": c1["id"]})["remittance_id"] is None
    assert MONGO.payments.find_one({"_id": c2["id"]})["remittance_id"] is None


def test_concurrent_prepare_single_claim(su, actors):
    ids = _fresh_collections(su, actors, 2)

    def prep(_):
        return actors["admin"]["session"].post(f"{API}/admin-remittances", json={"collection_ids": ids}, timeout=90).status_code

    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        codes = sorted(pool.map(prep, range(3)))
    assert codes.count(200) == 1, codes
    assert all(c in (200, 409) for c in codes), codes
    rem_ids = {MONGO.payments.find_one({"_id": i})["remittance_id"] for i in ids}
    assert len(rem_ids) == 1 and None not in rem_ids
    assert MONGO.admin_remittances.count_documents({"status": {"$ne": "PREPARED"}, "_id": {"$in": list(rem_ids)}}) == 0


@pytest.fixture(scope="module")
def submitted_rem(su, actors):
    ids = _fresh_collections(su, actors, 3, principal=1_500_000)
    rem = actors["admin"]["session"].post(f"{API}/admin-remittances", json={"collection_ids": ids}, timeout=90).json()
    r = actors["admin"]["session"].post(f"{API}/admin-remittances/{rem['id']}/submit", files=proof_files(), timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def test_submit_rbac_and_file_privacy(su, actors, submitted_rem):
    rid, proof = submitted_rem["id"], submitted_rem["proof_file_id"]
    assert submitted_rem["status"] == "WAITING_VERIFICATION"
    assert submitted_rem["remittance_attempt_count"] == 1
    assert actors["admin2"]["session"].get(f"{API}/admin-remittances/{rid}", timeout=30).status_code == 403
    assert actors["lender2"]["session"].get(f"{API}/admin-remittances/{rid}", timeout=30).status_code == 403
    assert actors["borrower"]["session"].get(f"{API}/admin-remittances/{rid}", timeout=30).status_code == 403
    assert actors["lender"]["session"].get(f"{API}/admin-remittances/{rid}", timeout=30).status_code == 200
    assert su.get(f"{API}/admin-remittances/{rid}", timeout=30).status_code == 200
    # RBAC file bukti setoran
    assert requests.get(f"{API}/files/{proof}", timeout=30).status_code == 401
    assert actors["borrower"]["session"].get(f"{API}/files/{proof}", timeout=30).status_code == 403
    assert actors["lender2"]["session"].get(f"{API}/files/{proof}", timeout=30).status_code == 403
    assert actors["admin2"]["session"].get(f"{API}/files/{proof}", timeout=30).status_code == 403
    assert actors["admin"]["session"].get(f"{API}/files/{proof}", timeout=30).status_code == 200
    assert actors["lender"]["session"].get(f"{API}/files/{proof}", timeout=30).status_code == 200
    assert su.get(f"{API}/files/{proof}", timeout=30).status_code == 200
    # admin & superadmin tidak boleh verify
    assert actors["admin"]["session"].post(f"{API}/admin-remittances/{rid}/verify", timeout=30).status_code == 403
    assert su.post(f"{API}/admin-remittances/{rid}/verify", timeout=30).status_code == 403


def test_reject_then_resubmit_attempt_history(su, actors):
    ids = _fresh_collections(su, actors, 2, principal=1_200_000)
    rem = actors["admin"]["session"].post(f"{API}/admin-remittances", json={"collection_ids": ids}, timeout=90).json()
    rid = rem["id"]
    actors["admin"]["session"].post(f"{API}/admin-remittances/{rid}/submit", files=proof_files(), timeout=60)
    assert actors["lender"]["session"].post(f"{API}/admin-remittances/{rid}/reject", json={"reason": "pendek"}, timeout=30).status_code == 422
    assert actors["lender2"]["session"].post(f"{API}/admin-remittances/{rid}/reject", json={"reason": "Bukan setoran saya sama sekali"}, timeout=30).status_code == 403
    rej = actors["lender"]["session"].post(f"{API}/admin-remittances/{rid}/reject",
                                           json={"reason": "Nominal transfer tidak sesuai total"}, timeout=30).json()
    assert rej["status"] == "REJECTED"
    for i in ids:
        p = MONGO.payments.find_one({"_id": i})
        assert p["remittance_id"] == rid  # tetap terikat
        assert MONGO.loans.find_one({"_id": p["loan_id"]})["status"] == "PAYMENT_COLLECTED"  # tidak kembali aktif
        assert p["late_fee_snapshot"] == MONGO.loans.find_one({"_id": p["loan_id"]})["late_fee_final"]
    again = actors["admin"]["session"].post(f"{API}/admin-remittances/{rid}/submit", files=proof_files(), timeout=60).json()
    attempts = again["remittance_attempts"]
    assert again["remittance_attempt_count"] == 2 and len(attempts) == 2
    assert attempts[0]["status"] == "REJECTED" and attempts[0]["rejection_reason"] == "Nominal transfer tidak sesuai total"
    assert attempts[1]["status"] == "SUBMITTED" and attempts[1]["proof_file_id"] != attempts[0]["proof_file_id"]
    v = actors["lender"]["session"].post(f"{API}/admin-remittances/{rid}/verify", timeout=90).json()
    assert v["status"] == "VERIFIED"
    assert v["remittance_attempts"][0]["status"] == "REJECTED"   # attempt lama immutable
    assert v["remittance_attempts"][1]["status"] == "VERIFIED"


def test_verify_batch_all_paid_with_distribution(su, actors, submitted_rem):
    rid = submitted_rem["id"]
    items = submitted_rem["items"]
    r = actors["lender"]["session"].post(f"{API}/admin-remittances/{rid}/verify", timeout=120)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "VERIFIED"
    for i in items:
        loan = MONGO.loans.find_one({"_id": i["loan_id"]})
        assert loan["status"] == "PAID"
        assert loan["paid_at"] == i["collected_at"]                    # paid_at = collected_at
        assert loan["payment_verified_at"] and loan["payment_verified_at"] != loan["paid_at"]
        assert loan["late_fee_final"] == i["late_fee_snapshot"]
        assert loan["actual_payment_amount"] == i["total_collected"]
        assert MONGO.profit_distributions.count_documents({"loan_id": i["loan_id"]}) == 1
    # idempotent: verify ulang 409, tidak ada distribusi ganda
    assert actors["lender"]["session"].post(f"{API}/admin-remittances/{rid}/verify", timeout=30).status_code == 409
    assert actors["lender"]["session"].post(f"{API}/admin-remittances/{rid}/finalize", timeout=60).status_code == 200
    for i in items:
        assert MONGO.profit_distributions.count_documents({"loan_id": i["loan_id"]}) == 1
    # profit distribution per loan (bukan per remittance) & full amount disetor (tanpa potongan hak admin)
    total_items = sum(i["total_collected"] for i in items)
    assert submitted_rem["total_amount"] == total_items


def test_crash_midway_recovered_by_finalize(su, actors):
    """Simulasi crash: state VERIFYING dengan sebagian item selesai -> finalize menuntaskan semuanya."""
    ids = _fresh_collections(su, actors, 3, principal=1_100_000)
    rem = actors["admin"]["session"].post(f"{API}/admin-remittances", json={"collection_ids": ids}, timeout=90).json()
    rid = rem["id"]
    actors["admin"]["session"].post(f"{API}/admin-remittances/{rid}/submit", files=proof_files(), timeout=60)
    # simulasikan proses terhenti setelah 1 item selesai
    MONGO.admin_remittances.update_one({"_id": rid}, {"$set": {"status": "VERIFYING"}})
    first = MONGO.payments.find_one({"_id": ids[0]})
    MONGO.payments.update_one({"_id": ids[0]}, {"$set": {"status": "VERIFIED", "collection_status": "VERIFIED"}})
    MONGO.loans.update_one({"_id": first["loan_id"]}, {"$set": {
        "status": "PAID", "paid_at": first["collected_at"], "late_fee_final": first["late_fee_snapshot"],
        "actual_payment_amount": first["total_collected"]}})
    # verify (retry) harus menyelesaikan seluruh batch tanpa state finansial parsial
    r = actors["lender"]["session"].post(f"{API}/admin-remittances/{rid}/verify", timeout=120)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "VERIFIED"
    for i in ids:
        p = MONGO.payments.find_one({"_id": i})
        assert p["status"] == "VERIFIED"
        assert MONGO.loans.find_one({"_id": p["loan_id"]})["status"] == "PAID"
        assert MONGO.profit_distributions.count_documents({"loan_id": p["loan_id"]}) == 1


def test_no_orphan_proof_on_concurrent_submit(su, actors):
    ids = _fresh_collections(su, actors, 1, principal=1_050_000)
    rem = actors["admin"]["session"].post(f"{API}/admin-remittances", json={"collection_ids": ids}, timeout=60).json()
    rid = rem["id"]
    files_before = MONGO.files.count_documents({"kind": "remittance"})

    def send(_):
        return actors["admin"]["session"].post(f"{API}/admin-remittances/{rid}/submit", files=proof_files(), timeout=90).status_code

    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        codes = sorted(pool.map(send, range(3)))
    assert codes.count(200) == 1 and codes.count(409) == 2, codes
    assert MONGO.files.count_documents({"kind": "remittance"}) == files_before + 1
    assert MONGO.files.count_documents({"kind": "remittance", "cleanup_pending": True}) == 0


def test_collection_reversal_superadmin_only(su, actors):
    ids = _fresh_collections(su, actors, 1, principal=1_060_000)
    cid = ids[0]
    loan_id = MONGO.payments.find_one({"_id": cid})["loan_id"]
    body = {"reason": "Penerimaan tercatat pada pinjaman yang salah", "confirmation": "BATALKAN PENERIMAAN"}
    assert actors["admin"]["session"].post(f"{API}/admin-collections/{cid}/reverse", json=body, timeout=30).status_code == 403
    assert su.post(f"{API}/admin-collections/{cid}/reverse", json={**body, "confirmation": "salah"}, timeout=30).status_code == 400
    r = su.post(f"{API}/admin-collections/{cid}/reverse", json=body, timeout=30)
    assert r.status_code == 200, r.text
    assert MONGO.loans.find_one({"_id": loan_id})["status"] in ("ACTIVE", "OVERDUE")
    assert MONGO.payments.find_one({"_id": cid})["collection_status"] == "REVERSED"  # histori tidak dihapus
    assert MONGO.audit_logs.find_one({"action": "ADMIN_COLLECTION_REVERSED", "entity_id": cid})


def test_summary_reports_and_rbac(su, actors):
    admin_sum = actors["admin"]["session"].get(f"{API}/admin-collections/summary", timeout=30).json()
    assert admin_sum["cash_in_hand"] >= 0 and "per_admin" not in admin_sum
    sup_sum = su.get(f"{API}/admin-collections/summary", timeout=30).json()
    assert any(a["admin_name"] for a in sup_sum["per_admin"])
    assert actors["borrower"]["session"].get(f"{API}/admin-collections/summary", timeout=30).status_code == 403
    assert actors["borrower"]["session"].get(f"{API}/admin-collections", timeout=30).status_code == 403
    assert actors["borrower"]["session"].get(f"{API}/admin-remittances", timeout=30).status_code == 403
    # admin hanya melihat miliknya
    mine = actors["admin"]["session"].get(f"{API}/admin-collections", timeout=30).json()
    assert all(i["collector_admin_id"] == actors["admin"]["id"] for i in mine["items"])
    # CSV superadmin
    for path in ("admin-collections", "admin-remittances"):
        csv_resp = su.get(f"{API}/{path}/export.csv", timeout=60)
        assert csv_resp.status_code == 200 and "number" in csv_resp.text
        assert actors["admin"]["session"].get(f"{API}/{path}/export.csv", timeout=30).status_code == 403


def test_admin_bank_profile_editable_and_private(su, actors):
    r = actors["admin"]["session"].put(f"{API}/auth/profile", json={
        "full_name": "Admin Satu Bank", "bank_name": "BCA", "account_number": "9090909090",
        "account_holder": "ADMIN SATU"}, timeout=30)
    assert r.status_code == 200, r.text
    doc = MONGO.users.find_one({"_id": actors["admin"]["id"]})
    assert doc["account_number"] == "9090909090"
    # tidak bocor ke Pendana/Peminjam melalui API umum
    lender_view = actors["lender"]["session"].get(f"{API}/profit-distributions", params={"page_size": 20}, timeout=30).json()
    assert all("admin_bank" not in i for i in lender_view["items"])
    rems = actors["lender"]["session"].get(f"{API}/admin-remittances", timeout=30).json()
    assert all("admin_bank" not in r for r in rems["items"])


def test_factory_reset_isolated_covers_collections():
    proc = subprocess.run([sys.executable, "/app/backend/tests/_factory_reset_isolated.py"],
                          capture_output=True, text=True, timeout=240)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    result = json.loads([l for l in proc.stdout.splitlines() if l.startswith("FACTORY_RESET_ISOLATED_RESULT")][-1].split(" ", 1)[1])
    assert result["reset"]["status"] == "SUCCESS"
    assert result["after"]["storage_objects"] == 0
    import admin_routes
    assert "admin_remittances" in admin_routes.WIPE_COLLECTIONS and "payments" in admin_routes.WIPE_COLLECTIONS


def test_indexes_exist():
    idx = MONGO.admin_remittances.index_information()
    assert any(v.get("unique") and v["key"][0][0] == "remittance_number" for v in idx.values())
    pidx = {v["key"][0][0] for v in MONGO.payments.index_information().values()}
    for f in ("payment_channel", "collector_admin_id", "remittance_id", "collection_number"):
        assert f in pidx
