"""Iteration 18: final hardening (5 temuan tambahan).

1. Factory Reset tidak boleh SUCCESS ketika purge storage melempar exception
2. admin_bank tidak boleh terkirim ke Pendana
3. Notifikasi settlement submitted hanya ke Superadmin
4. Rounding ekstrem: tidak pernah negatif, total selalu = profit_pool
5. Tidak ada orphan proof pada race/double submit
"""
import json
import subprocess
import sys
import concurrent.futures as cf
import pytest
import requests

sys.path.insert(0, "/app/backend")

from test_iter16_profit_sharing import (  # noqa: E402
    API, MONGO, PASS, actors, su, loan_rates, proof_files, submit_loan, to_paid, distribution_of, set_pcts,
)
from test_iter17_profit_hardening import wide_borrower_limit  # noqa: E402,F401


# ---------------- 1. FACTORY RESET STORAGE EXCEPTION ----------------
def test_factory_reset_storage_exception_never_success():
    proc = subprocess.run(
        [sys.executable, "/app/backend/tests/_factory_reset_isolated.py", "storage-fail"],
        capture_output=True, text=True, timeout=240,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    line = [l for l in proc.stdout.splitlines() if l.startswith("FACTORY_RESET_ISOLATED_RESULT")]
    assert line, proc.stdout[-2000:]
    result = json.loads(line[-1].split(" ", 1)[1])
    assert result["mode"] == "storage-fail"
    assert result["reset"]["status"] == "FAILED"
    assert result["reset"]["storage_ok"] is False
    assert result["reset"]["storage"]["error"]
    # object memang masih tertinggal -> status wajib bukan SUCCESS
    assert result["after"]["storage_objects_left"] >= 2


def test_factory_reset_success_path_still_ok():
    proc = subprocess.run(
        [sys.executable, "/app/backend/tests/_factory_reset_isolated.py"],
        capture_output=True, text=True, timeout=240,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    result = json.loads([l for l in proc.stdout.splitlines() if l.startswith("FACTORY_RESET_ISOLATED_RESULT")][-1].split(" ", 1)[1])
    assert result["reset"]["status"] == "SUCCESS" and result["reset"]["storage_ok"] is True
    assert result["after"]["storage_objects"] == 0 and result["after"]["profit_distributions"] == 0


# ---------------- 2. admin_bank RBAC ----------------
@pytest.fixture(scope="module")
def paid_dist(su, actors):
    set_pcts(su, 60, 25, 15)
    loan = submit_loan(actors["borrower"], principal=2_000_000)
    to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"])
    return distribution_of(su, loan["id"])


def test_admin_bank_hidden_from_lender(su, actors, paid_dist):
    dist_id = paid_dist["id"]
    assert "admin_bank" in paid_dist and paid_dist["admin_bank"]["account_number"]

    lender_view = actors["lender"]["session"].get(f"{API}/profit-distributions/{dist_id}", timeout=30).json()
    assert "admin_bank" not in lender_view
    assert lender_view["settlement_account"]["settlement_account_number"]  # rekening pusat tetap terlihat

    lender_list = actors["lender"]["session"].get(f"{API}/profit-distributions", params={"page_size": 50}, timeout=30).json()
    assert all("admin_bank" not in i for i in lender_list["items"])

    admin_view = actors["admin"]["session"].get(f"{API}/profit-distributions/{dist_id}", timeout=30).json()
    assert admin_view["admin_bank"]["account_number"]  # admin pemilik boleh melihat rekeningnya
    admin_list = actors["admin"]["session"].get(f"{API}/profit-distributions", params={"page_size": 50}, timeout=30).json()
    assert all("admin_bank" in i for i in admin_list["items"])

    assert actors["admin2"]["session"].get(f"{API}/profit-distributions/{dist_id}", timeout=30).status_code == 403
    assert actors["borrower"]["session"].get(f"{API}/profit-distributions/{dist_id}", timeout=30).status_code == 403

    # detail pinjaman: Pendana juga tidak menerima admin_bank
    loan_detail = actors["lender"]["session"].get(f"{API}/loans/{paid_dist['loan_id']}", timeout=30).json()
    assert "admin_bank" not in (loan_detail["profit_share"]["distribution"] or {})
    su_detail = su.get(f"{API}/loans/{paid_dist['loan_id']}", timeout=30).json()
    assert su_detail["profit_share"]["distribution"]["admin_bank"]["account_number"]


# ---------------- 3. NOTIFIKASI SETTLEMENT ----------------
def test_settlement_notification_only_superadmin(su, actors):
    MONGO.users.update_many(
        {"_id": {"$in": [actors["admin"]["id"], actors["admin2"]["id"], actors["lender"]["id"]]}},
        {"$set": {"notify_telegram": True, "telegram_chat_id": "111222333"}},
    )
    loan = submit_loan(actors["borrower"], principal=1_900_000)
    to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"])
    d = distribution_of(su, loan["id"])
    r = actors["lender"]["session"].post(f"{API}/profit-distributions/{d['id']}/settlement", files=proof_files(), timeout=60)
    assert r.status_code == 200, r.text

    notifs = list(MONGO.notifications.find({"notification_type": "LENDER_SETTLEMENT_SUBMITTED", "loan_id": loan["id"]}))
    assert notifs, "notifikasi setoran harus tercatat"
    roles = set()
    for n in notifs:
        target = MONGO.users.find_one({"full_name": n.get("recipient")}) if n.get("recipient") else None
        if target:
            roles.add(target["role"])
    assert "admin" not in roles, f"Admin biasa tidak boleh menerima notifikasi verifikasi settlement: {roles}"
    assert roles == {"superadmin"}, roles

    # setelah SETTLED, Admin pemilik baru diberi notifikasi payable
    su.post(f"{API}/profit-distributions/{d['id']}/settlement/verify", timeout=30)
    payable = list(MONGO.notifications.find({"notification_type": "ADMIN_PAYABLE_READY", "loan_id": loan["id"]}))
    assert payable, "Admin pemilik harus diberi notifikasi ketika bagi hasilnya menjadi payable"
    assert {p["recipient"] for p in payable} == {MONGO.users.find_one({"_id": actors["admin"]["id"]})["full_name"]}
    verified = list(MONGO.notifications.find({"notification_type": "LENDER_SETTLEMENT_VERIFIED", "loan_id": loan["id"]}))
    assert verified, "Pendana harus diberi notifikasi setelah setoran diverifikasi"


# ---------------- 4. ROUNDING EKSTREM ----------------
def test_rounding_never_negative_small_pools():
    import profit_service as PS

    combos = [
        [50, 50, 0], [60, 25, 15], [33.33, 33.33, 33.34], [0, 0, 100], [100, 0, 0],
        [0.01, 99.99, 0], [70.5, 19.25, 10.25], [50, 25, 25], [99.98, 0.01, 0.01],
    ]
    for pool in (0, 1, 2, 3, 4, 5, 7, 10, 99, 101, 12_345):
        for pcts in combos:
            parts = PS.split_pool(pool, pcts)
            assert all(p >= 0 for p in parts), (pool, pcts, parts)
            assert sum(parts) == pool, (pool, pcts, parts)
            # deterministik
            assert PS.split_pool(pool, pcts) == parts

    # kasus wajib pada permintaan: pool 1 dengan 50/50/0
    assert PS.split_pool(1, [50, 50, 0]) == [1, 0, 0]

    d = PS.compute_distribution(1_000_000, 1, 0, 50, 50, 0)
    assert (d["lender_profit"], d["admin_profit"], d["platform_profit"]) == (1, 0, 0)
    assert d["lender_profit"] + d["admin_profit"] + d["platform_profit"] == d["profit_pool"] == 1
    assert d["lender_total_entitlement"] + d["lender_settlement_due"] == d["total_received"]

    for interest, late_fee, pcts in [(1, 0, (50, 50, 0)), (1, 1, (33.33, 33.33, 33.34)), (3, 0, (60, 25, 15)),
                                     (0, 1, (0, 0, 100)), (5, 5, (99.99, 0.01, 0))]:
        d = PS.compute_distribution(500_000, interest, late_fee, *pcts)
        assert min(d["lender_profit"], d["admin_profit"], d["platform_profit"]) >= 0
        assert d["lender_profit"] + d["admin_profit"] + d["platform_profit"] == d["profit_pool"]
        assert d["lender_total_entitlement"] + d["lender_settlement_due"] == d["total_received"]


def test_rounding_small_pool_end_to_end(su, actors):
    """Pinjaman nyata dengan profit pool kecil: distribusi tetap konsisten dan non-negatif."""
    set_pcts(su, 50, 50, 0)
    loan = submit_loan(actors["borrower"], principal=100_000)
    MONGO.loans.update_one({"_id": loan["id"]}, {"$set": {"interest_amount": 1}})
    to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"])
    d = distribution_of(su, loan["id"])
    assert d["profit_pool"] >= 0
    assert min(d["lender_profit"], d["admin_profit"], d["platform_profit"]) >= 0
    assert d["lender_profit"] + d["admin_profit"] + d["platform_profit"] == d["profit_pool"]
    assert d["lender_total_entitlement"] + d["lender_settlement_due"] == d["total_received"]
    set_pcts(su, 60, 25, 15)


# ---------------- 5. ORPHAN PROOF PADA RACE / DOUBLE SUBMIT ----------------
def _submit(session, dist_id):
    r = session.post(f"{API}/profit-distributions/{dist_id}/settlement", files=proof_files(), timeout=90)
    return r.status_code, r.text


def test_no_orphan_proof_on_concurrent_settlement(su, actors):
    loan = submit_loan(actors["borrower"], principal=2_100_000)
    to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"])
    d = distribution_of(su, loan["id"])
    dist_id = d["id"]

    files_before = MONGO.files.count_documents({"kind": "settlement"})
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: _submit(actors["lender"]["session"], dist_id), range(3)))
    codes = sorted(c for c, _ in results)
    assert codes.count(200) == 1, results
    assert codes.count(409) == 2, results

    doc = MONGO.profit_distributions.find_one({"_id": dist_id})
    assert doc["lender_settlement_status"] == "WAITING_VERIFICATION"
    assert doc["settlement_attempt_count"] == 1 and len(doc["settlement_attempts"]) == 1
    winner_proof = doc["settlement_proof_file_id"]
    assert doc["settlement_attempts"][0]["proof_file_id"] == winner_proof

    # hanya proof pemenang yang tersisa, tidak ada file orphan
    assert MONGO.files.count_documents({"kind": "settlement"}) == files_before + 1
    orphans = list(MONGO.files.find({"profit_distribution_id": dist_id, "_id": {"$ne": winner_proof}}))
    assert orphans == [], orphans
    assert su.get(f"{API}/files/{winner_proof}", timeout=30).status_code == 200


def test_no_orphan_proof_on_concurrent_admin_payout(su, actors):
    loan = submit_loan(actors["borrower"], principal=2_200_000)
    to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"])
    d = distribution_of(su, loan["id"])
    dist_id = d["id"]
    actors["lender"]["session"].post(f"{API}/profit-distributions/{dist_id}/settlement", files=proof_files(), timeout=60)
    su.post(f"{API}/profit-distributions/{dist_id}/settlement/verify", timeout=30)

    files_before = MONGO.files.count_documents({"kind": "admin_payout"})

    def mark(_):
        r = su.post(f"{API}/profit-distributions/{dist_id}/admin-payout/mark-paid", files=proof_files(), timeout=90)
        return r.status_code

    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        codes = sorted(pool.map(mark, range(3)))
    assert codes.count(200) == 1 and codes.count(409) == 2, codes

    doc = MONGO.profit_distributions.find_one({"_id": dist_id})
    assert doc["admin_payout_status"] == "PAID"
    assert MONGO.files.count_documents({"kind": "admin_payout"}) == files_before + 1
    leftovers = list(MONGO.files.find({"profit_distribution_id": dist_id, "kind": "admin_payout",
                                       "_id": {"$ne": doc["admin_payout_proof_file_id"]}}))
    assert leftovers == [], leftovers
    assert su.get(f"{API}/files/{doc['admin_payout_proof_file_id']}", timeout=30).status_code == 200


def test_discarded_proof_object_removed_from_storage(su, actors):
    """Object dari request yang kalah benar-benar hilang dari storage (bukan hanya dari DB)."""
    import storage as ST

    loan = submit_loan(actors["borrower"], principal=2_300_000)
    to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"])
    dist_id = distribution_of(su, loan["id"])["id"]

    objects_before = {o["path"] for o in ST.list_objects(f"{ST.APP_PREFIX}/settlement/")}
    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _submit(actors["lender"]["session"], dist_id), range(2)))
    assert sorted(c for c, _ in results) == [200, 409], results

    objects_after = {o["path"] for o in ST.list_objects(f"{ST.APP_PREFIX}/settlement/")}
    winner = MONGO.profit_distributions.find_one({"_id": dist_id})["settlement_proof_file_id"]
    winner_path = MONGO.files.find_one({"_id": winner})["storage_path"]
    added = objects_after - objects_before
    assert added == {winner_path}, added
