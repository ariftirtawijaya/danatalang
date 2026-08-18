"""Factory Reset — integration test TERISOLASI.

Dijalankan sebagai subprocess dengan DB_NAME dan S3_PREFIX khusus test, sehingga
database & prefix object storage preview/production TIDAK tersentuh.

Menguji perilaku purge/list/delete storage yang sebenarnya (bukan sekadar memastikan
fungsi dipanggil): object di-upload nyata, lalu dipastikan hilang setelah reset.
"""
import asyncio
import io
import json
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

RUN_ID = uuid.uuid4().hex[:8]
os.environ["DB_NAME"] = f"fr_isolated_{RUN_ID}"
os.environ["S3_PREFIX"] = f"fr-isolated-{RUN_ID}"
os.environ["SUPERADMIN_PHONE"] = "081000000001"
os.environ["SUPERADMIN_PASSWORD"] = "FrTest!2026"
os.environ["SUPERADMIN_NAME"] = "Primary Superadmin FR"
os.environ["SUPERADMIN_EMAIL"] = "fr-primary@test.local"
os.environ.pop("REQUIRE_S3", None)

# S3 sungguhan (in-process, moto) pada bucket khusus test: purge/list/delete diuji nyata,
# bukan di-mock pada level fungsi. Bucket & prefix preview/production tidak tersentuh.
import boto3  # noqa: E402
from moto.server import ThreadedMotoServer  # noqa: E402

MOTO = ThreadedMotoServer(port=0)
MOTO.start()
MOTO_PORT = MOTO.get_host_and_port()[1]
TEST_BUCKET = f"fr-test-{RUN_ID}"
os.environ["S3_ENDPOINT_URL"] = f"http://127.0.0.1:{MOTO_PORT}"
os.environ["S3_ACCESS_KEY_ID"] = "test"
os.environ["S3_SECRET_ACCESS_KEY"] = "test"
os.environ["S3_BUCKET_NAME"] = TEST_BUCKET
os.environ["S3_REGION"] = "us-east-1"
boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT_URL"],
    aws_access_key_id="test",
    aws_secret_access_key="test",
    region_name="us-east-1",
).create_bucket(Bucket=TEST_BUCKET)

sys.path.insert(0, "/app/backend")

import core  # noqa: E402
import storage  # noqa: E402
import admin_routes  # noqa: E402
import server  # noqa: E402
import profit_service as PS  # noqa: E402


class FakeUpload:
    """Minimal pengganti UploadFile untuk save_upload."""

    def __init__(self, name, content, content_type="image/png"):
        self.filename = name
        self.content_type = content_type
        self._buf = io.BytesIO(content)

    async def read(self, size=-1):
        return self._buf.read() if size == -1 else self._buf.read(size)

    async def seek(self, pos):
        self._buf.seek(pos)

    async def close(self):
        self._buf.close()


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    result = {"mode": mode, "db": os.environ["DB_NAME"], "prefix": os.environ["S3_PREFIX"], "storage_mode": None}
    db = core.db
    await core.ensure_indexes()
    result["storage_mode"] = storage.init_storage(force=True)
    await server.seed_superadmin()

    keeper = await db.users.find_one({"role": "superadmin"})
    assert keeper, "primary superadmin tidak terbentuk"
    keeper_id = keeper["_id"]

    # --- data dummy: user, loan, distribution, 2 bukti (settlement + admin payout) ---
    lender_id, admin_id, borrower_id, loan_id = (str(uuid.uuid4()) for _ in range(4))
    await db.users.insert_many([
        {"_id": lender_id, "role": "lender", "full_name": "FR Lender", "phone": "081000000002", "is_active": True},
        {"_id": admin_id, "role": "admin", "full_name": "FR Admin", "phone": "081000000003", "is_active": True,
         "bank_name": "BCA", "account_number": "1234567890", "account_holder": "FR ADMIN"},
        {"_id": borrower_id, "role": "borrower", "full_name": "FR Borrower", "phone": "081000000004", "is_active": True},
    ])
    await db.loans.insert_one({
        "_id": loan_id, "loan_number": "PIN-FR-0001", "borrower_id": borrower_id, "funded_by": lender_id,
        "assigned_admin_id": admin_id, "principal_amount": 2_000_000, "interest_amount": 400_000,
        "late_fee_final": 100_000, "status": "PAID",
        "profit_share_lender_pct_snapshot": 60.0, "profit_share_admin_pct_snapshot": 25.0,
        "profit_share_platform_pct_snapshot": 15.0, "profit_share_version": 1,
    })
    dist = await PS.ensure_profit_distribution_for_paid_loan(await db.loans.find_one({"_id": loan_id}), None, keeper, None)
    assert dist and dist["lender_settlement_due"] == 200_000, dist

    settlement_up = await storage.save_upload(db, FakeUpload("settlement.png", PNG), lender_id, "settlement")
    payout_up = await storage.save_upload(db, FakeUpload("payout.png", PNG), keeper_id, "admin_payout")
    settlement_path = (await db.files.find_one({"_id": settlement_up["file_id"]}))["storage_path"]
    payout_path = (await db.files.find_one({"_id": payout_up["file_id"]}))["storage_path"]
    await db.profit_distributions.update_one(
        {"_id": dist["_id"]},
        {"$set": {
            "lender_settlement_status": "SETTLED",
            "settlement_proof_file_id": settlement_up["file_id"],
            "settlement_attempt_count": 1,
            "settlement_attempts": [{"attempt_no": 1, "proof_file_id": settlement_up["file_id"], "status": "VERIFIED"}],
            "admin_payout_status": "PAID",
            "admin_payout_proof_file_id": payout_up["file_id"],
        }},
    )
    await db.settings.update_one(
        {"_id": "app"},
        {"$set": {
            "profit_share_lender_pct": 70.0, "profit_share_admin_pct": 20.0, "profit_share_platform_pct": 10.0,
            "settlement_account_type": "BCA", "settlement_account_number": "999888777",
            "settlement_account_holder": "PT DUMMY", "settlement_account_bank_name": "Bank Dummy",
            "settlement_instructions": "dummy",
        }},
        upsert=True,
    )

    before_objects = storage.list_objects(None)
    result["before"] = {
        "profit_distributions": await db.profit_distributions.count_documents({}),
        "settlement_proofs": await db.files.count_documents({"kind": "settlement"}),
        "admin_payout_proofs": await db.files.count_documents({"kind": "admin_payout"}),
        "loans": await db.loans.count_documents({}),
        "users": await db.users.count_documents({}),
        "storage_objects": len(before_objects),
    }
    assert result["before"]["profit_distributions"] == 1
    assert result["before"]["settlement_proofs"] == 1
    assert result["before"]["admin_payout_proofs"] == 1
    assert result["before"]["storage_objects"] >= 2, before_objects

    # --- eksekusi Factory Reset (logic asli, prefix & DB terisolasi) ---
    if mode == "storage-fail":
        def boom(prefix=None):
            raise RuntimeError("simulasi kegagalan koneksi object storage")

        admin_routes.purge_prefix = boom

    payload = admin_routes.FactoryResetIn(confirmation="HAPUS SEMUA DATA", password=os.environ["SUPERADMIN_PASSWORD"])
    reset = await admin_routes.factory_reset(payload, None, keeper)
    result["reset"] = reset if isinstance(reset, dict) else str(reset)

    if mode == "storage-fail":
        assert result["reset"]["status"] != "SUCCESS", result["reset"]
        assert result["reset"]["status"] == "FAILED", result["reset"]
        assert result["reset"]["storage_ok"] is False
        assert result["reset"]["ok"] is False
        assert result["reset"]["aborted_before_db_wipe"] is True
        assert result["reset"]["storage"].get("error"), result["reset"]["storage"]
        settings_after = await core.get_settings()
        result["after"] = {
            "storage_objects_left": len(storage.list_objects(None)),
            # FAIL-SAFE: MongoDB harus TETAP UTUH
            "profit_distributions": await db.profit_distributions.count_documents({}),
            "loans": await db.loans.count_documents({}),
            "files": await db.files.count_documents({}),
            "users": await db.users.count_documents({}),
            "keeper_exists": bool(await db.users.find_one({"_id": keeper_id})),
            "profit_share": [settings_after["profit_share_lender_pct"], settings_after["profit_share_admin_pct"],
                             settings_after["profit_share_platform_pct"]],
            "settlement_account_number": settings_after["settlement_account_number"],
        }
        a = result["after"]
        assert a["profit_distributions"] == 1, "distribusi tidak boleh terhapus saat storage gagal"
        assert a["loans"] == 1 and a["files"] == 2, a
        assert a["users"] == 4 and a["keeper_exists"] is True, a
        assert a["profit_share"] == [70.0, 20.0, 10.0], "settings tidak boleh direset saat storage gagal"
        assert a["settlement_account_number"] == "999888777", "rekening settlement tidak boleh direset"
        audit_doc = await db.audit_logs.find_one({"action": "SYSTEM_FACTORY_RESET"})
        assert audit_doc and audit_doc["new_value"]["status"] == "FAILED", audit_doc
        assert audit_doc["new_value"]["aborted_before_db_wipe"] is True
        assert "DIBATALKAN" in audit_doc["description"]
        # retry setelah storage sehat harus berhasil
        admin_routes.purge_prefix = storage.purge_prefix
        retry = await admin_routes.factory_reset(payload, None, keeper)
        result["retry"] = {"status": retry["status"], "storage_ok": retry["storage_ok"],
                           "profit_distributions": await db.profit_distributions.count_documents({}),
                           "users": await db.users.count_documents({}),
                           "storage_objects": len(storage.list_objects(None))}
        assert result["retry"]["status"] == "SUCCESS" and result["retry"]["storage_ok"] is True
        assert result["retry"]["profit_distributions"] == 0 and result["retry"]["users"] == 1
        assert result["retry"]["storage_objects"] == 0
        await core.client.drop_database(os.environ["DB_NAME"])
        MOTO.stop()
        result["cleanup"] = "test database dropped, moto s3 stopped"
        print("FACTORY_RESET_ISOLATED_RESULT " + json.dumps(result))
        return

    after_objects = storage.list_objects(None)
    settings = await core.get_settings()
    result["after"] = {
        "profit_distributions": await db.profit_distributions.count_documents({}),
        "files": await db.files.count_documents({}),
        "loans": await db.loans.count_documents({}),
        "payments": await db.payments.count_documents({}),
        "users": await db.users.count_documents({}),
        "storage_objects": len(after_objects),
        "profit_share": [settings["profit_share_lender_pct"], settings["profit_share_admin_pct"], settings["profit_share_platform_pct"]],
        "settlement_account_number": settings["settlement_account_number"],
        "keeper_exists": bool(await db.users.find_one({"_id": keeper_id})),
    }

    a = result["after"]
    assert a["profit_distributions"] == 0, "profit_distributions belum kosong"
    assert a["files"] == 0 and a["loans"] == 0 and a["payments"] == 0, "data transaksi belum bersih"
    assert a["storage_objects"] == 0, f"masih ada object storage: {after_objects}"
    assert a["profit_share"] == [60.0, 25.0, 15.0], a["profit_share"]
    assert a["settlement_account_number"] is None, "rekening settlement belum kosong"
    assert a["keeper_exists"] is True, "primary superadmin hilang"
    assert a["users"] == 1, "hanya primary superadmin yang boleh tersisa"

    # bukti file benar-benar hilang dari storage
    for label, path in (("settlement", settlement_path), ("admin_payout", payout_path)):
        try:
            storage.get_object(path)
            raise AssertionError(f"object {label} masih dapat diakses setelah reset")
        except AssertionError:
            raise
        except Exception:
            pass

    await core.client.drop_database(os.environ["DB_NAME"])
    MOTO.stop()
    result["cleanup"] = "test database dropped, moto s3 stopped"
    print("FACTORY_RESET_ISOLATED_RESULT " + json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
