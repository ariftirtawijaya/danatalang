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
    assert result["reset"]["ok"] is False
    assert result["reset"]["aborted_before_db_wipe"] is True
    assert result["reset"]["storage"]["error"]
    # object memang masih tertinggal -> status wajib bukan SUCCESS
    assert result["after"]["storage_objects_left"] >= 2
    # FAIL-SAFE: MongoDB tidak boleh dihapus ketika storage gagal
    a = result["after"]
    assert a["profit_distributions"] == 1 and a["loans"] == 1 and a["files"] == 2
    assert a["users"] == 4 and a["keeper_exists"] is True
    assert a["profit_share"] == [70.0, 20.0, 10.0]
    assert a["settlement_account_number"] == "999888777"
    # retry setelah storage sehat menghasilkan reset lengkap
    assert result["retry"]["status"] == "SUCCESS"
    assert result["retry"]["profit_distributions"] == 0 and result["retry"]["users"] == 1
    assert result["retry"]["storage_objects"] == 0


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
    """A. Normal race: object & metadata loser benar-benar hilang, hanya proof winner tersisa."""
    import storage as ST

    loan = submit_loan(actors["borrower"], principal=2_300_000)
    to_paid(actors, su, loan["id"], assigned_admin_id=actors["admin"]["id"])
    dist_id = distribution_of(su, loan["id"])["id"]

    objects_before = {o["path"] for o in ST.list_objects(f"{ST.APP_PREFIX}/settlement/")}
    files_before = MONGO.files.count_documents({"kind": "settlement"})
    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _submit(actors["lender"]["session"], dist_id), range(2)))
    assert sorted(c for c, _ in results) == [200, 409], results

    objects_after = {o["path"] for o in ST.list_objects(f"{ST.APP_PREFIX}/settlement/")}
    winner = MONGO.profit_distributions.find_one({"_id": dist_id})["settlement_proof_file_id"]
    winner_path = MONGO.files.find_one({"_id": winner})["storage_path"]
    added = objects_after - objects_before
    assert added == {winner_path}, added
    assert MONGO.files.count_documents({"kind": "settlement"}) == files_before + 1
    assert MONGO.files.count_documents({"kind": "settlement", "cleanup_pending": True}) == 0


def _isolated_discard(kind: str, mode: str) -> dict:
    """Jalankan _discard_upload di subprocess dengan purge_object yang sengaja dibuat gagal."""
    script = f'''
import asyncio, io, json, os, sys
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
import storage as ST, profit_routes as PR
from core import db

class FakeUpload:
    def __init__(self, name, content, ct="image/png"):
        self.filename, self.content_type, self._b = name, ct, io.BytesIO(content)
    async def read(self, size=-1):
        return self._b.read() if size == -1 else self._b.read(size)
    async def seek(self, p):
        self._b.seek(p)
    async def close(self):
        self._b.close()

PNG = (b"\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x08\\x06\\x00\\x00\\x00"
       b"\\x1f\\x15\\xc4\\x89\\x00\\x00\\x00\\nIDATx\\x9cc\\x00\\x01\\x00\\x00\\x05\\x00\\x01\\r\\n-\\xb4\\x00\\x00\\x00\\x00IEND\\xaeB`\\x82")

async def main():
    up = await ST.save_upload(db, FakeUpload("loser.png", PNG), "race-test-user", "{kind}")
    rec = await db.files.find_one({{"_id": up["file_id"]}})
    path = rec["storage_path"]
    if "{mode}" == "fail":
        def boom(key):
            raise RuntimeError("simulasi kegagalan hapus object storage")
        PR.purge_object = boom
    await PR._discard_upload(up["file_id"])
    after = await db.files.find_one({{"_id": up["file_id"]}})
    exists = True
    try:
        ST.get_object(path)
    except Exception:
        exists = False
    print("DISCARD_RESULT " + json.dumps({{
        "file_id": up["file_id"], "path": path, "object_exists": exists,
        "metadata_exists": after is not None,
        "is_deleted": (after or {{}}).get("is_deleted"),
        "cleanup_pending": (after or {{}}).get("cleanup_pending"),
        "cleanup_error": (after or {{}}).get("cleanup_error"),
        "cleanup_requested_at": (after or {{}}).get("cleanup_requested_at"),
    }}))

asyncio.run(main())
'''
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    line = [l for l in proc.stdout.splitlines() if l.startswith("DISCARD_RESULT")]
    assert line, proc.stdout[-2000:]
    return json.loads(line[-1].split(" ", 1)[1])


@pytest.mark.parametrize("kind", ["settlement", "admin_payout"])
def test_discard_upload_keeps_metadata_when_purge_fails(su, kind):
    """B. purge_object gagal -> metadata dipertahankan, ditandai cleanup_pending, file tak bisa diakses."""
    res = _isolated_discard(kind, "fail")
    assert res["object_exists"] is True, "object memang masih ada karena purge sengaja dibuat gagal"
    assert res["metadata_exists"] is True, "metadata tidak boleh hilang saat purge gagal"
    assert res["is_deleted"] is True and res["cleanup_pending"] is True
    assert res["cleanup_error"] and res["cleanup_requested_at"]
    # file tidak dapat diakses lewat endpoint terautentikasi
    assert su.get(f"{API}/files/{res['file_id']}", timeout=30).status_code == 404
    # bersihkan sisa object test
    MONGO.files.delete_one({"_id": res["file_id"]})
    import storage as ST
    try:
        ST.purge_object(res["path"])
    except Exception:
        pass


@pytest.mark.parametrize("kind", ["settlement", "admin_payout"])
def test_discard_upload_removes_metadata_when_purge_succeeds(kind):
    res = _isolated_discard(kind, "ok")
    assert res["object_exists"] is False, "object harus terhapus dari storage"
    assert res["metadata_exists"] is False, "metadata harus terhapus setelah object benar-benar hilang"
