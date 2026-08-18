"""Admin Collection (koleksi lapangan) & Bulk Remittance.

Sumber kebenaran nominal TETAP satu: dokumen `payments` dengan
`payment_channel = "ADMIN_COLLECTION"` (alasan: payment history, audit, report,
loan detail, dan profit distribution existing semuanya sudah membaca `payments`,
sehingga tidak ada dua source-of-truth untuk nominal yang sama).
`admin_remittances` hanya menyimpan batch + attempt history dan mereferensikan
`payment_id`; totalnya selalu dihitung ulang dari snapshot payment.
"""

import logging
import uuid
from typing import Optional
from fastapi import HTTPException
from core import db, client, now_utc, iso, parse_dt, audit, ROLE_ADMIN, ROLE_SUPERADMIN, ROLE_LENDER
import loan_service as LS

logger = logging.getLogger("app")

CH_DIRECT = "DIRECT_TO_LENDER"
CH_ADMIN = "ADMIN_COLLECTION"

COL_COLLECTED = "COLLECTED"          # uang di tangan Admin
COL_RESERVED = "RESERVED"            # terikat pada remittance (PREPARED/WAITING/REJECTED)
COL_VERIFIED = "VERIFIED"            # setoran diverifikasi Pendana -> loan PAID
COL_REVERSED = "REVERSED"

REM_PREPARING = "PREPARING"          # transient: reservasi sedang dibuat
REM_PREPARED = "PREPARED"
REM_WAITING = "WAITING_VERIFICATION"
REM_VERIFYING = "VERIFYING"
REM_VERIFIED = "VERIFIED"
REM_REJECTED = "REJECTED"
REM_CANCELLED = "CANCELLED"

COMMIT_PENDING = "PENDING"
COMMIT_DONE = "COMMITTED"
COMMIT_ABORTED = "ABORTED"

# Reservation lease: hanya remittance PREPARING yang melewati batas ini boleh dianggap terlantar.
STALE_PREPARE_SECONDS = 120
STALE_COLLECT_SECONDS = 60

METHODS = ("CASH", "TRANSFER_TO_ADMIN")


_tx_supported: Optional[bool] = None


async def transaction_supported() -> bool:
    """Deteksi kapabilitas nyata (bukan asumsi konfigurasi): coba jalankan transaction sungguhan."""
    global _tx_supported
    if _tx_supported is None:
        try:
            async with await client.start_session() as s:
                async with s.start_transaction():
                    await db.tx_capability_probe.update_one(
                        {"_id": "probe"}, {"$set": {"at": iso(now_utc())}}, upsert=True, session=s)
                    await s.abort_transaction()
            _tx_supported = True
            logger.info("MongoDB transaction tersedia: dipakai untuk operasi atomik koleksi/setoran")
        except Exception as e:
            _tx_supported = False
            logger.warning("MongoDB transaction tidak tersedia (%s) — memakai idempotent recovery", e)
    return _tx_supported


def _tx_unsupported_error(e: Exception) -> bool:
    msg = str(e)
    return ("Transaction numbers are only allowed" in msg or "Transactions are not supported" in msg
            or "not supported" in msg and "transaction" in msg.lower())


async def atomic(op):
    """Jalankan `op(session)`.

    TRANSACTION bila tersedia, IDEMPOTENT RECOVERY sebagai safety net: `op` wajib ditulis
    idempoten sehingga tetap aman ketika session bernilai None.
    """
    global _tx_supported
    if await transaction_supported():
        try:
            async with await client.start_session() as s:
                async with s.start_transaction():
                    return await op(s)
        except HTTPException:
            raise
        except Exception as e:
            if _tx_unsupported_error(e):
                _tx_supported = False
                logger.warning("Fallback ke mode non-transaction: %s", e)
                return await op(None)
            raise
    return await op(None)


def visible_collection_filter() -> dict:
    """Koleksi yang boleh tampil/dipakai: bukan reversed, dan commit-nya tidak menggantung."""
    return {"payment_channel": CH_ADMIN,
            "collection_status": {"$ne": COL_REVERSED},
            "commit_state": {"$nin": [COMMIT_PENDING, COMMIT_ABORTED]}}


async def recover_pending_collections(actor=None, request=None, payment_id: Optional[str] = None,
                                      stale_seconds: int = STALE_COLLECT_SECONDS) -> dict:
    """Selesaikan (forward) atau batalkan penerimaan yang crash di tengah proses."""
    q = {"payment_channel": CH_ADMIN, "commit_state": COMMIT_PENDING}
    if payment_id:
        q["_id"] = payment_id
    docs = await db.payments.find(q).to_list(500)
    committed, aborted = 0, 0
    for p in docs:
        age = (now_utc() - parse_dt(p.get("created_at"))).total_seconds() if p.get("created_at") else 1e9
        if not payment_id and age < stale_seconds:
            continue
        loan = await db.loans.find_one({"_id": p.get("loan_id")})
        if loan and loan["status"] in (LS.S_ACTIVE, LS.S_OVERDUE, LS.S_COLLECTED):
            if loan["status"] != LS.S_COLLECTED:
                await db.loans.update_one(
                    {"_id": loan["_id"], "status": {"$in": [LS.S_ACTIVE, LS.S_OVERDUE]}},
                    {"$set": {"status": LS.S_COLLECTED, "collected_at": p.get("collected_at"),
                              "collected_by": p.get("collector_admin_id"),
                              "late_days_final": p.get("late_days_snapshot") or 0,
                              "late_fee_final": LS.money(p.get("late_fee_snapshot")),
                              "actual_payment_amount": LS.money(p.get("total_collected"))}})
                await LS.record_status(loan["_id"], loan["status"], LS.S_COLLECTED, actor,
                                       f"Recovery: penerimaan {p.get('collection_number')} dilanjutkan")
            await db.payments.update_one({"_id": str(p["_id"]), "commit_state": COMMIT_PENDING},
                                         {"$set": {"commit_state": COMMIT_DONE}})
            committed += 1
            await audit(request, actor, "ADMIN_COLLECTION_RECOVERED", "payment", str(p["_id"]),
                        f"Recovery: penerimaan {p.get('collection_number')} diselesaikan secara idempoten",
                        {"commit_state": COMMIT_PENDING}, {"commit_state": COMMIT_DONE})
        else:
            await db.payments.update_one({"_id": str(p["_id"]), "commit_state": COMMIT_PENDING},
                                         {"$set": {"commit_state": COMMIT_ABORTED, "collection_status": COL_REVERSED,
                                                   "status": "REVERSED",
                                                   "reversal_reason": "Recovery: proses penerimaan tidak selesai"}})
            aborted += 1
            await audit(request, actor, "ADMIN_COLLECTION_ABORTED", "payment", str(p["_id"]),
                        f"Recovery: penerimaan {p.get('collection_number')} dibatalkan karena proses tidak selesai",
                        {"commit_state": COMMIT_PENDING}, {"commit_state": COMMIT_ABORTED})
    return {"committed": committed, "aborted": aborted}


async def release_reservations(remittance_id: str, token: Optional[str] = None, session=None) -> int:
    q = {"remittance_id": remittance_id, "collection_status": COL_RESERVED}
    if token:
        q["reservation_token"] = token
    res = await db.payments.update_many(
        q, {"$set": {"remittance_id": None, "remittance_number": None, "collection_status": COL_COLLECTED},
            "$unset": {"reservation_token": "", "reserved_at": ""}}, session=session)
    return res.modified_count


async def finish_prepare(rem: dict, session=None) -> dict:
    """Idempotent: PREPARING -> PREPARED dengan total dihitung ulang dari item ter-reserve."""
    rid = str(rem["_id"])
    items = await db.payments.find({"remittance_id": rid}, session=session).to_list(200)
    total = sum(LS.money(p.get("total_collected")) for p in items)
    await db.admin_remittances.update_one(
        {"_id": rid, "status": REM_PREPARING},
        {"$set": {"status": REM_PREPARED, "item_count": len(items), "total_amount": total,
                  "updated_at": iso(now_utc())}}, session=session)
    return await db.admin_remittances.find_one({"_id": rid}, session=session)


async def recover_stale_reservations(actor=None, request=None, admin_id: Optional[str] = None,
                                     stale_seconds: int = STALE_PREPARE_SECONDS) -> dict:
    """Hanya menyentuh reservasi yang benar-benar stale/orphan.

    Kriteria aman: (a) parent remittance masih PREPARING melewati lease, atau (b) parent
    remittance tidak ada / sudah CANCELLED. Reservasi PREPARED yang valid TIDAK pernah dilepas.
    """
    finished, cancelled, released = 0, 0, 0
    q = {"status": REM_PREPARING}
    if admin_id:
        q["admin_id"] = admin_id
    for rem in await db.admin_remittances.find(q).to_list(200):
        created = parse_dt(rem.get("created_at")) if rem.get("created_at") else None
        if created and (now_utc() - created).total_seconds() < stale_seconds:
            continue
        rid, token = str(rem["_id"]), rem.get("reservation_token")
        reserved = await db.payments.count_documents({"remittance_id": rid, "reservation_token": token})
        requested = list(rem.get("requested_ids") or [])
        if requested and reserved == len(requested):
            await finish_prepare(rem)
            finished += 1
            await audit(request, actor, "ADMIN_REMITTANCE_PREPARE_RECOVERED", "admin_remittance", rid,
                        f"Recovery: penyiapan setoran {rem.get('remittance_number')} dilanjutkan sampai PREPARED "
                        f"({reserved} item)", {"status": REM_PREPARING}, {"status": REM_PREPARED})
        else:
            released += await release_reservations(rid, token)
            await db.admin_remittances.update_one(
                {"_id": rid, "status": REM_PREPARING},
                {"$set": {"status": REM_CANCELLED, "item_count": 0, "total_amount": 0,
                          "cancel_reason": "Recovery: penyiapan setoran tidak selesai",
                          "cancelled_at": iso(now_utc()),
                          "cancelled_by": str((actor or {}).get("_id")) if actor else None,
                          "updated_at": iso(now_utc())}})
            cancelled += 1
            await audit(request, actor, "ADMIN_REMITTANCE_PREPARE_ROLLED_BACK", "admin_remittance", rid,
                        f"Recovery: penyiapan setoran {rem.get('remittance_number')} dibatalkan, "
                        f"{reserved} reservasi dilepas kembali menjadi COLLECTED",
                        {"status": REM_PREPARING}, {"status": REM_CANCELLED})

    # Orphan: item RESERVED yang parent-nya hilang atau sudah CANCELLED.
    oq = {"payment_channel": CH_ADMIN, "collection_status": COL_RESERVED, "remittance_id": {"$ne": None}}
    if admin_id:
        oq["collector_admin_id"] = admin_id
    orphans = 0
    for p in await db.payments.find(oq).to_list(1000):
        rem = await db.admin_remittances.find_one({"_id": p.get("remittance_id")})
        if rem and rem.get("status") != REM_CANCELLED:
            continue
        await db.payments.update_one(
            {"_id": str(p["_id"]), "collection_status": COL_RESERVED},
            {"$set": {"remittance_id": None, "remittance_number": None, "collection_status": COL_COLLECTED},
             "$unset": {"reservation_token": "", "reserved_at": ""}})
        orphans += 1
        await audit(request, actor, "ADMIN_COLLECTION_RESERVATION_RELEASED", "payment", str(p["_id"]),
                    f"Recovery: reservasi terlantar pada {p.get('collection_number')} dilepas kembali",
                    {"collection_status": COL_RESERVED}, {"collection_status": COL_COLLECTED})
    return {"prepare_finished": finished, "prepare_cancelled": cancelled,
            "reservations_released": released, "orphans_released": orphans}


async def next_number(prefix: str) -> str:
    day = (now_utc() + LS.timedelta(hours=7)).strftime("%Y%m%d")
    doc = await db.counters.find_one_and_update(
        {"_id": f"{prefix.lower()}-{day}"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True
    )
    return f"{prefix}-{day}-{doc['seq']:04d}"


def snapshot_amounts(loan: dict, at) -> dict:
    """Server-side source of truth pada saat Admin menerima uang."""
    due = parse_dt(loan.get("due_date"))
    late_days = LS.late_days_for(due, at)
    late_fee = LS.calc_late_fee(LS.money(loan["principal_amount"]), loan.get("late_fee_rate") or 0, late_days)
    principal = LS.money(loan["principal_amount"])
    interest = LS.money(loan["interest_amount"])
    return {
        "principal_snapshot": principal,
        "interest_snapshot": interest,
        "late_days_snapshot": late_days,
        "late_fee_snapshot": late_fee,
        "total_collected": principal + interest + late_fee,
    }


async def serialize_collection(p: dict, with_names: bool = True) -> dict:
    out = {
        "id": str(p["_id"]),
        "loan_id": p.get("loan_id"),
        "loan_number": p.get("loan_number"),
        "collection_number": p.get("collection_number"),
        "collection_method": p.get("collection_method"),
        "collector_admin_id": p.get("collector_admin_id"),
        "borrower_id": p.get("borrower_id"),
        "lender_id": p.get("lender_id"),
        "principal_snapshot": LS.money(p.get("principal_snapshot")),
        "interest_snapshot": LS.money(p.get("interest_snapshot")),
        "late_days_snapshot": p.get("late_days_snapshot") or 0,
        "late_fee_snapshot": LS.money(p.get("late_fee_snapshot")),
        "total_collected": LS.money(p.get("total_collected")),
        "collected_at": p.get("collected_at"),
        "collection_status": p.get("collection_status"),
        "remittance_id": p.get("remittance_id"),
        "remittance_number": p.get("remittance_number"),
        "notes": p.get("notes"),
        "proof_file_id": p.get("proof_file_id"),
        "status": p.get("status"),
        "reversal_reason": p.get("reversal_reason"),
    }
    if with_names:
        for key, field in (("borrower_id", "borrower_name"), ("lender_id", "lender_name"),
                           ("collector_admin_id", "admin_name")):
            uid = p.get(key)
            u = await db.users.find_one({"_id": uid}) if uid else None
            out[field] = (u or {}).get("full_name")
    return out


async def serialize_remittance(r: dict, viewer: Optional[dict] = None, with_items: bool = True) -> dict:
    out = {k: v for k, v in r.items() if k != "_id"}
    out["id"] = str(r["_id"])
    admin = await db.users.find_one({"_id": r.get("admin_id")}) if r.get("admin_id") else None
    lender = await db.users.find_one({"_id": r.get("lender_id")}) if r.get("lender_id") else None
    out["admin_name"] = (admin or {}).get("full_name")
    out["lender_name"] = (lender or {}).get("full_name")
    role = (viewer or {}).get("role")
    if role in (ROLE_ADMIN, ROLE_SUPERADMIN, ROLE_LENDER) and lender:
        # rekening Pendana dibutuhkan Admin untuk transfer; tidak pernah dikirim ke Peminjam
        out["lender_bank"] = {
            "bank_name": lender.get("bank_name"),
            "account_number": lender.get("account_number"),
            "account_holder": lender.get("account_holder"),
        }
    if with_items:
        items = await db.payments.find({"remittance_id": str(r["_id"])}).sort("collected_at", 1).to_list(200)
        out["items"] = [await serialize_collection(p) for p in items]
        out["item_count"] = len(items)
        out["computed_total"] = sum(LS.money(p.get("total_collected")) for p in items)
    return out


def assert_can_read_remittance(r: dict, user: dict):
    role, uid = user.get("role"), str(user["_id"])
    if role == ROLE_SUPERADMIN:
        return
    if role == ROLE_ADMIN and r.get("admin_id") == uid:
        return
    if role == ROLE_LENDER and r.get("lender_id") == uid:
        return
    raise HTTPException(status_code=403, detail="Anda tidak memiliki akses ke setoran ini")


async def finalize_remittance(remittance_id: str, actor: Optional[dict], request=None) -> dict:
    """Idempotent all-or-nothing finalizer.

    Aman dipanggil ulang (double click, retry, recovery setelah crash): setiap langkah
    memakai conditional update, sehingga hasil akhirnya selalu konsisten: seluruh item
    VERIFIED + loan PAID + profit distribution dibuat, lalu remittance VERIFIED.
    """
    import profit_service as PS
    from notif import notify_user, rp

    rem = await db.admin_remittances.find_one({"_id": remittance_id})
    if not rem:
        raise HTTPException(status_code=404, detail="Setoran tidak ditemukan")
    if rem["status"] not in (REM_VERIFYING, REM_VERIFIED):
        raise HTTPException(status_code=409, detail="Setoran ini tidak sedang dalam proses verifikasi")

    now = iso(now_utc())
    items = await db.payments.find({"remittance_id": remittance_id}).to_list(200)
    for p in items:
        pid, loan_id = str(p["_id"]), p["loan_id"]
        await db.payments.update_one(
            {"_id": pid, "status": {"$ne": "VERIFIED"}},
            {"$set": {"status": "VERIFIED", "collection_status": COL_VERIFIED,
                      "verified_at": now, "verified_by": str((actor or {}).get("_id") or rem.get("lender_id"))}},
        )
        loan = await db.loans.find_one({"_id": loan_id})
        if loan and loan["status"] != LS.S_PAID:
            await db.loans.update_one(
                {"_id": loan_id, "status": {"$ne": LS.S_PAID}},
                {"$set": {
                    "status": LS.S_PAID,
                    "paid_at": p.get("collected_at"),                 # waktu Peminjam membayar Admin
                    "payment_verified_at": now,                        # waktu Pendana verifikasi setoran
                    "actual_payment_amount": LS.money(p.get("total_collected")),
                    "late_days_final": p.get("late_days_snapshot") or 0,
                    "late_fee_final": LS.money(p.get("late_fee_snapshot")),
                }},
            )
            await LS.record_status(loan_id, loan["status"], LS.S_PAID, actor,
                                   f"Setoran Admin {rem['remittance_number']} diverifikasi Pendana")
        fresh = await db.loans.find_one({"_id": loan_id})
        if fresh:
            await PS.ensure_profit_distribution_for_paid_loan(fresh, p, actor, request)

    res = await db.admin_remittances.update_one(
        {"_id": remittance_id, "status": REM_VERIFYING},
        {"$set": {"status": REM_VERIFIED, "verified_at": now,
                  "verified_by": str((actor or {}).get("_id") or rem.get("lender_id")), "updated_at": now}},
    )
    if res.modified_count:
        last = int(rem.get("remittance_attempt_count") or 0) - 1
        if last >= 0:
            await db.admin_remittances.update_one(
                {"_id": remittance_id},
                {"$set": {f"remittance_attempts.{last}.status": "VERIFIED",
                          f"remittance_attempts.{last}.verified_at": now,
                          f"remittance_attempts.{last}.verified_by": str((actor or {}).get("_id") or "")}},
            )
        await audit(request, actor, "ADMIN_REMITTANCE_VERIFIED", "admin_remittance", remittance_id,
                    f"Setoran {rem['remittance_number']} sebesar {rp(rem.get('total_amount'))} diverifikasi Pendana. "
                    f"{len(items)} pinjaman menjadi LUNAS.",
                    {"status": REM_WAITING}, {"status": REM_VERIFIED, "loans": [p['loan_number'] for p in items]})
        if rem.get("admin_id"):
            await notify_user(rem["admin_id"], "loan",
                              f"✅ <b>SETORAN DITERIMA</b>\n\nSetoran {rem['remittance_number']} sebesar "
                              f"{rp(rem.get('total_amount'))} telah diverifikasi Pendana. "
                              f"{len(items)} pinjaman kini LUNAS.", "ADMIN_REMITTANCE_VERIFIED", None)
        for p in items:
            if p.get("borrower_id"):
                await notify_user(p["borrower_id"], "loan",
                                  f"🎉 <b>PINJAMAN SELESAI</b>\n\nPinjaman {p.get('loan_number')} telah dinyatakan LUNAS. "
                                  "Terima kasih.", "LOAN_PAID", p["loan_id"])
    return await db.admin_remittances.find_one({"_id": remittance_id})


async def admin_cash_summary(admin_id: Optional[str] = None) -> dict:
    query = visible_collection_filter()
    if admin_id:
        query["collector_admin_id"] = admin_id
    docs = await db.payments.find(query).to_list(5000)
    rem_ids = {p.get("remittance_id") for p in docs if p.get("remittance_id")}
    rems = {str(r["_id"]): r for r in await db.admin_remittances.find({"_id": {"$in": list(rem_ids)}}).to_list(500)}

    def total(items):
        return sum(LS.money(p.get("total_collected")) for p in items)

    unremitted, waiting, done = [], [], []
    for p in docs:
        rem = rems.get(p.get("remittance_id") or "")
        status = rem["status"] if rem else None
        if p.get("collection_status") == COL_VERIFIED or status == REM_VERIFIED:
            done.append(p)
        elif status == REM_WAITING or status == REM_VERIFYING:
            waiting.append(p)
        else:
            unremitted.append(p)
    oldest = min([parse_dt(p.get("collected_at")) for p in unremitted if p.get("collected_at")], default=None)
    age_hours = round((now_utc() - oldest).total_seconds() / 3600, 1) if oldest else 0
    return {
        "collections": len(docs),
        "cash_in_hand": total(unremitted) + total(waiting),
        "unremitted_amount": total(unremitted),
        "unremitted_count": len(unremitted),
        "waiting_verification_amount": total(waiting),
        "waiting_verification_count": len(waiting),
        "verified_amount": total(done),
        "verified_count": len(done),
        "oldest_unremitted_at": iso(oldest) if oldest else None,
        "oldest_unremitted_hours": age_hours,
        "aging_warning": age_hours > 24,
    }
