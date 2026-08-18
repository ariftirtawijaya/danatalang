import csv
import io
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Response
from pydantic import BaseModel, Field
from core import (
    db, now_utc, iso, audit, get_current_user, require_superadmin, require_lender, require_roles,
    ROLE_ADMIN, ROLE_SUPERADMIN, ROLE_LENDER,
)
from notif import notify_user, notify_superadmins, rp
from storage import save_upload, purge_object
import loan_service as LS
import collection_service as CS

router = APIRouter(prefix="/api", tags=["admin-collection"])

require_admin_role = require_roles(ROLE_ADMIN)
require_staff = require_roles(ROLE_ADMIN, ROLE_SUPERADMIN)


async def _discard_upload(file_id: str):
    """Fail-safe storage-first cleanup (sama seperti modul bagi hasil)."""
    import asyncio
    rec = await db.files.find_one({"_id": file_id})
    if not rec:
        return
    path, error, removed = rec.get("storage_path"), None, False
    if path:
        try:
            removed = bool(await asyncio.to_thread(purge_object, path))
            if not removed:
                error = "object masih terdeteksi di storage setelah penghapusan"
        except Exception as e:
            error = str(e)
    else:
        removed = True
    if removed and not error:
        await db.files.delete_one({"_id": file_id})
        return
    await db.files.update_one({"_id": file_id}, {"$set": {
        "is_deleted": True, "cleanup_pending": True, "cleanup_error": error,
        "cleanup_requested_at": iso(now_utc())}})


# ---------------- collect ----------------
@router.post("/loans/{loan_id}/collect")
async def collect_payment(
    loan_id: str,
    request: Request,
    collection_method: str = Form(...),
    notes: Optional[str] = Form(None),
    proof: Optional[UploadFile] = File(None),
    user: dict = Depends(require_admin_role),
):
    if collection_method not in CS.METHODS:
        raise HTTPException(status_code=400, detail="Metode penerimaan tidak valid")
    loan = await db.loans.find_one({"_id": loan_id})
    if not loan:
        raise HTTPException(status_code=404, detail="Pinjaman tidak ditemukan")
    if loan.get("assigned_admin_id") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Anda bukan Admin penanggung jawab pinjaman ini")
    if loan["status"] not in (LS.S_ACTIVE, LS.S_OVERDUE):
        raise HTTPException(status_code=409, detail="Pinjaman ini tidak dalam status dapat menerima pembayaran")
    if await db.payments.find_one({"loan_id": loan_id, "status": "PENDING"}):
        raise HTTPException(status_code=409, detail="Ada laporan pembayaran langsung ke Pendana yang masih menunggu verifikasi")
    await CS.recover_pending_collections(user, request)
    if await db.payments.find_one({"loan_id": loan_id, "payment_channel": CS.CH_ADMIN,
                                   "collection_status": {"$nin": [CS.COL_REVERSED]}}):
        raise HTTPException(status_code=409, detail="Pembayaran pinjaman ini sudah diterima Admin sebelumnya")

    at = now_utc()
    snap = CS.snapshot_amounts(loan, at)

    upload = None
    if proof is not None and getattr(proof, "filename", None):
        upload = await save_upload(db, proof, str(user["_id"]), "collection")
    collection_number = await CS.next_number("COL")
    payment_id = str(uuid.uuid4())
    attempt_no = await db.payments.count_documents({"loan_id": loan_id}) + 1
    doc = {
        "_id": payment_id,
        "loan_id": loan_id,
        "loan_number": loan["loan_number"],
        "borrower_id": loan["borrower_id"],
        "lender_id": loan.get("funded_by"),
        "attempt_no": attempt_no,
        "payment_channel": CS.CH_ADMIN,
        "collection_number": collection_number,
        "collection_method": collection_method,
        "collector_admin_id": str(user["_id"]),
        "collection_status": CS.COL_COLLECTED,
        "remittance_id": None,
        "remittance_number": None,
        "amount_paid": snap["total_collected"],
        "amount_due_at_submission": snap["total_collected"],
        "late_days_at_submission": snap["late_days_snapshot"],
        "late_fee_at_submission": snap["late_fee_snapshot"],
        "status": "COLLECTED",
        "notes": (notes or "").strip() or None,
        "proof_file_id": (upload or {}).get("file_id"),
        "collected_at": iso(at),
        "created_at": iso(at),
        "commit_state": CS.COMMIT_PENDING,
        **snap,
    }

    async def _op(session):
        # 1) payment dulu (PENDING) supaya tidak pernah ada loan COLLECTED tanpa record pembayaran
        if not await db.payments.find_one({"_id": payment_id}, session=session):
            await db.payments.insert_one(doc, session=session)
        res = await db.loans.update_one(
            {"_id": loan_id, "status": {"$in": [LS.S_ACTIVE, LS.S_OVERDUE]}},
            {"$set": {
                "status": LS.S_COLLECTED,
                "collected_at": iso(at),
                "collected_by": str(user["_id"]),
                "late_days_final": snap["late_days_snapshot"],
                "late_fee_final": snap["late_fee_snapshot"],
                "actual_payment_amount": snap["total_collected"],
                "collection_payment_id": payment_id,      # korelasi eksplisit pengklaim loan
            }}, session=session,
        )
        if res.modified_count == 0:
            raise HTTPException(status_code=409, detail="Pembayaran pinjaman ini sudah diproses")
        await db.payments.update_one({"_id": payment_id}, {"$set": {"commit_state": CS.COMMIT_DONE}}, session=session)

    try:
        await CS.atomic(_op)
    except Exception:
        # Jika payment ini SUDAH berhasil mengklaim loan, jangan pernah hapus recordnya:
        # invariant "tidak ada loan PAYMENT_COLLECTED tanpa payment" harus tetap terjaga.
        claimed = await db.loans.find_one({"_id": loan_id, "collection_payment_id": payment_id})
        if claimed:
            await CS.recover_pending_collections(user, request, payment_id=payment_id)
        else:
            await db.payments.delete_one({"_id": payment_id, "commit_state": CS.COMMIT_PENDING})
            if upload:
                await _discard_upload(upload["file_id"])
        raise
    if upload:
        await db.files.update_one({"_id": upload["file_id"]}, {"$set": {"loan_id": loan_id, "payment_id": payment_id}})
    await LS.record_status(loan_id, loan["status"], LS.S_COLLECTED, user,
                           f"Pembayaran diterima Admin ({collection_number})")
    await audit(request, user, "ADMIN_COLLECTION_CREATED", "payment", payment_id,
                f"Pembayaran {loan['loan_number']} sebesar {rp(snap['total_collected'])} diterima Admin "
                f"({collection_method}), bukti {collection_number}. Denda dibekukan pada "
                f"{snap['late_days_snapshot']} hari ({rp(snap['late_fee_snapshot'])}).",
                {"status": loan["status"]}, {"status": LS.S_COLLECTED, **snap, "collection_number": collection_number})
    await notify_user(loan["borrower_id"], "loan",
                      f"✅ <b>PEMBAYARAN DITERIMA</b>\n\nPinjaman {loan['loan_number']}\nNo Bukti: {collection_number}\n"
                      f"Total: {rp(snap['total_collected'])}\nDiterima: {user.get('full_name')}\n\n"
                      "Pembayaran Anda telah diterima. Tidak ada denda tambahan.", "ADMIN_COLLECTION_CREATED", loan_id)
    if loan.get("funded_by"):
        await notify_user(loan["funded_by"], "loan",
                          f"📥 <b>PEMBAYARAN DITERIMA ADMIN</b>\n\n{loan['loan_number']}\n"
                          f"Total: {rp(snap['total_collected'])}\nAdmin: {user.get('full_name')}\n\n"
                          "Dana akan disetorkan Admin ke rekening Anda.", "ADMIN_COLLECTION_CREATED", loan_id)
    return await CS.serialize_collection(await db.payments.find_one({"_id": payment_id}))


# ---------------- collections ----------------
def _collection_query(user: dict) -> dict:
    q = CS.visible_collection_filter()
    if user["role"] == ROLE_ADMIN:
        q["collector_admin_id"] = str(user["_id"])
    elif user["role"] == ROLE_LENDER:
        q["lender_id"] = str(user["_id"])
    elif user["role"] != ROLE_SUPERADMIN:
        raise HTTPException(status_code=403, detail="Tidak memiliki akses")
    return q


@router.get("/admin-collections/summary")
async def collections_summary(user: dict = Depends(require_staff)):
    if user["role"] == ROLE_ADMIN:
        return await CS.admin_cash_summary(str(user["_id"]))
    admins = await db.users.find({"role": ROLE_ADMIN}).to_list(200)
    per_admin = []
    for a in admins:
        s = await CS.admin_cash_summary(str(a["_id"]))
        if s["collections"]:
            per_admin.append({"admin_id": str(a["_id"]), "admin_name": a.get("full_name"), **s})
    return {**(await CS.admin_cash_summary()), "per_admin": per_admin}


@router.get("/admin-collections")
async def list_collections(
    user: dict = Depends(get_current_user),
    status: Optional[str] = None,
    lender_id: Optional[str] = None,
    admin_id: Optional[str] = None,
    unremitted_only: bool = False,
    page_size: int = 100,
):
    if user["role"] == ROLE_ADMIN:
        await CS.recover_stale_reservations(user, admin_id=str(user["_id"]))
        await CS.recover_pending_collections(user)
    query = _collection_query(user)
    if status:
        query["collection_status"] = status
    if lender_id:
        query["lender_id"] = lender_id
    if admin_id and user["role"] == ROLE_SUPERADMIN:
        query["collector_admin_id"] = admin_id
    if unremitted_only:
        query["remittance_id"] = None
    docs = await db.payments.find(query).sort("collected_at", -1).limit(min(500, page_size)).to_list(500)
    return {"items": [await CS.serialize_collection(p) for p in docs], "total": len(docs)}


@router.get("/admin-collections/export.csv")
async def export_collections(user: dict = Depends(require_superadmin)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["collection_number", "collected_at", "loan_number", "borrower_name", "lender_name", "admin_name",
                "method", "principal", "interest", "late_days", "late_fee", "total_collected",
                "collection_status", "remittance_number"])
    async for p in db.payments.find({"payment_channel": CS.CH_ADMIN}).sort("collected_at", -1):
        i = await CS.serialize_collection(p)
        w.writerow([i["collection_number"], i["collected_at"], i["loan_number"], i["borrower_name"], i["lender_name"],
                    i["admin_name"], i["collection_method"], i["principal_snapshot"], i["interest_snapshot"],
                    i["late_days_snapshot"], i["late_fee_snapshot"], i["total_collected"], i["collection_status"],
                    i["remittance_number"]])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=koleksi-lapangan.csv"})


class ReverseCollectionIn(BaseModel):
    reason: str = Field(min_length=20, max_length=1000)
    confirmation: str


@router.post("/admin-collections/{payment_id}/reverse")
async def reverse_collection(payment_id: str, payload: ReverseCollectionIn, request: Request,
                             user: dict = Depends(require_superadmin)):
    if payload.confirmation.strip() != "BATALKAN PENERIMAAN":
        raise HTTPException(status_code=400, detail="Ketik persis: BATALKAN PENERIMAAN")
    p = await db.payments.find_one({"_id": payment_id, "payment_channel": CS.CH_ADMIN})
    if not p:
        raise HTTPException(status_code=404, detail="Data penerimaan tidak ditemukan")
    if p.get("collection_status") == CS.COL_VERIFIED:
        raise HTTPException(status_code=409, detail="Setoran sudah diverifikasi dan pinjaman sudah LUNAS. "
                                                   "Gunakan koreksi finansial eksplisit, bukan pembatalan sederhana.")
    if p.get("collection_status") == CS.COL_REVERSED:
        raise HTTPException(status_code=409, detail="Penerimaan ini sudah dibatalkan")
    if p.get("remittance_id"):
        raise HTTPException(status_code=409, detail="Penerimaan ini terikat pada setoran bulk. "
                                                   "Selesaikan atau batalkan setoran tersebut terlebih dahulu.")
    now = iso(now_utc())
    res = await db.payments.update_one(
        {"_id": payment_id, "collection_status": CS.COL_COLLECTED},
        {"$set": {"collection_status": CS.COL_REVERSED, "status": "REVERSED", "reversed_at": now,
                  "reversed_by": str(user["_id"]), "reversal_reason": payload.reason}},
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Penerimaan ini tidak dapat dibatalkan pada status saat ini")
    loan = await db.loans.find_one({"_id": p["loan_id"]})
    due = loan.get("due_date")
    new_status = LS.S_OVERDUE if due and now_utc() > LS.parse_dt(due) else LS.S_ACTIVE
    await db.loans.update_one({"_id": p["loan_id"]}, {
        "$set": {"status": new_status},
        "$unset": {"collected_at": "", "collected_by": "", "late_days_final": "", "late_fee_final": "",
                   "actual_payment_amount": "", "collection_payment_id": ""},
    })
    await LS.record_status(p["loan_id"], LS.S_COLLECTED, new_status, user, f"Pembatalan penerimaan: {payload.reason}")
    await audit(request, user, "ADMIN_COLLECTION_REVERSED", "payment", payment_id,
                f"Penerimaan {p.get('collection_number')} ({rp(p.get('total_collected'))}) dibatalkan Superadmin: {payload.reason}",
                {"collection_status": CS.COL_COLLECTED, "loan_status": LS.S_COLLECTED},
                {"collection_status": CS.COL_REVERSED, "loan_status": new_status, "reason": payload.reason})
    return await CS.serialize_collection(await db.payments.find_one({"_id": payment_id}))


# ---------------- remittance ----------------
class PrepareIn(BaseModel):
    collection_ids: List[str] = Field(min_length=1)


@router.post("/admin-remittances")
async def prepare_remittance(payload: PrepareIn, request: Request, user: dict = Depends(require_admin_role)):
    await CS.recover_stale_reservations(user, request, admin_id=str(user["_id"]))
    ids = list(dict.fromkeys(payload.collection_ids))
    docs = await db.payments.find({"_id": {"$in": ids}, "payment_channel": CS.CH_ADMIN}).to_list(200)
    if len(docs) != len(ids):
        raise HTTPException(status_code=404, detail="Sebagian data penerimaan tidak ditemukan")
    for p in docs:
        if p.get("collector_admin_id") != str(user["_id"]):
            raise HTTPException(status_code=403, detail="Terdapat penerimaan milik Admin lain")
        if p.get("collection_status") != CS.COL_COLLECTED or p.get("remittance_id"):
            raise HTTPException(status_code=409, detail="Terdapat penerimaan yang sudah masuk setoran lain")
        if p.get("commit_state") in (CS.COMMIT_PENDING, CS.COMMIT_ABORTED):
            raise HTTPException(status_code=409, detail="Terdapat penerimaan yang belum selesai diproses")
    lenders = {p.get("lender_id") for p in docs}
    if len(lenders) != 1 or None in lenders:
        raise HTTPException(status_code=400, detail="Satu setoran hanya boleh untuk satu Pendana")
    lender_id = lenders.pop()

    remittance_id = str(uuid.uuid4())
    number = await CS.next_number("REM")
    now = iso(now_utc())
    token = str(uuid.uuid4())

    async def _op(session):
        # 1) parent dulu (PREPARING + token) → tidak akan pernah ada item RESERVED tanpa parent recoverable
        if not await db.admin_remittances.find_one({"_id": remittance_id}, session=session):
            await db.admin_remittances.insert_one({
                "_id": remittance_id,
                "remittance_number": number,
                "admin_id": str(user["_id"]),
                "lender_id": lender_id,
                "status": CS.REM_PREPARING,
                "reservation_token": token,
                "requested_ids": ids,
                "item_count": 0,
                "total_amount": 0,
                "proof_file_id": None,
                "remittance_attempt_count": 0,
                "remittance_attempts": [],
                "submitted_at": None,
                "verified_at": None,
                "verified_by": None,
                "rejected_at": None,
                "rejected_by": None,
                "rejection_reason": None,
                "cancel_reason": None,
                "cancelled_at": None,
                "cancelled_by": None,
                "created_at": now,
                "updated_at": now,
            }, session=session)
        for p in docs:
            res = await db.payments.update_one(
                {"_id": str(p["_id"]), "remittance_id": None, "collection_status": CS.COL_COLLECTED},
                {"$set": {"remittance_id": remittance_id, "remittance_number": number,
                          "collection_status": CS.COL_RESERVED, "reservation_token": token,
                          "reserved_at": now}}, session=session,
            )
            if res.modified_count == 0 and not await db.payments.find_one(
                    {"_id": str(p["_id"]), "reservation_token": token}, session=session):
                raise HTTPException(status_code=409,
                                    detail="Penerimaan sudah diklaim setoran lain, silakan muat ulang")
        return await CS.finish_prepare(await db.admin_remittances.find_one({"_id": remittance_id}, session=session),
                                      session=session)

    try:
        await CS.atomic(_op)
    except Exception:
        released = await CS.release_reservations(remittance_id, token)
        await db.admin_remittances.update_one(
            {"_id": remittance_id, "status": CS.REM_PREPARING},
            {"$set": {"status": CS.REM_CANCELLED, "item_count": 0, "total_amount": 0,
                      "cancel_reason": "Penyiapan setoran gagal, seluruh reservasi dilepas",
                      "cancelled_at": iso(now_utc()), "cancelled_by": str(user["_id"]),
                      "updated_at": iso(now_utc())}})
        await audit(request, user, "ADMIN_REMITTANCE_PREPARE_ROLLED_BACK", "admin_remittance", remittance_id,
                    f"Penyiapan setoran {number} gagal; {released} reservasi dilepas kembali menjadi COLLECTED",
                    {"status": CS.REM_PREPARING}, {"status": CS.REM_CANCELLED})
        raise

    items = await db.payments.find({"remittance_id": remittance_id}).to_list(200)
    total = sum(LS.money(p.get("total_collected")) for p in items)
    await audit(request, user, "ADMIN_REMITTANCE_PREPARED", "admin_remittance", remittance_id,
                f"Setoran bulk {number} disiapkan: {len(items)} pinjaman, total {rp(total)}",
                None, {"total_amount": total, "items": [p.get("collection_number") for p in items]})
    return await CS.serialize_remittance(await db.admin_remittances.find_one({"_id": remittance_id}), viewer=user)


@router.get("/admin-remittances")
async def list_remittances(user: dict = Depends(get_current_user), status: Optional[str] = None):
    role, uid = user["role"], str(user["_id"])
    query: dict = {}
    if role == ROLE_ADMIN:
        await CS.recover_stale_reservations(user, admin_id=uid)
        query["admin_id"] = uid
    elif role == ROLE_LENDER:
        query["lender_id"] = uid
    elif role != ROLE_SUPERADMIN:
        raise HTTPException(status_code=403, detail="Tidak memiliki akses")
    if status:
        query["status"] = {"$in": [s.strip() for s in status.split(",") if s.strip()]}
    else:
        query["status"] = {"$ne": CS.REM_PREPARING}   # state transient internal, tidak ditampilkan
    docs = await db.admin_remittances.find(query).sort("created_at", -1).limit(200).to_list(200)
    return {"items": [await CS.serialize_remittance(r, viewer=user) for r in docs], "total": len(docs)}


@router.get("/admin-remittances/export.csv")
async def export_remittances(user: dict = Depends(require_superadmin)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["remittance_number", "created_at", "admin_name", "lender_name", "status", "item_count",
                "total_amount", "submitted_at", "verified_at", "rejection_reason"])
    async for r in db.admin_remittances.find({}).sort("created_at", -1):
        i = await CS.serialize_remittance(r, viewer=user, with_items=False)
        w.writerow([i["remittance_number"], i["created_at"], i["admin_name"], i["lender_name"], i["status"],
                    i["item_count"], i["total_amount"], i.get("submitted_at"), i.get("verified_at"),
                    i.get("rejection_reason")])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=setoran-admin.csv"})


@router.get("/admin-remittances/{remittance_id}")
async def get_remittance(remittance_id: str, user: dict = Depends(get_current_user)):
    r = await db.admin_remittances.find_one({"_id": remittance_id})
    if not r:
        raise HTTPException(status_code=404, detail="Setoran tidak ditemukan")
    CS.assert_can_read_remittance(r, user)
    return await CS.serialize_remittance(r, viewer=user)


@router.post("/admin-remittances/{remittance_id}/submit")
async def submit_remittance(remittance_id: str, request: Request, proof: UploadFile = File(...),
                            user: dict = Depends(require_admin_role)):
    r = await db.admin_remittances.find_one({"_id": remittance_id})
    if not r:
        raise HTTPException(status_code=404, detail="Setoran tidak ditemukan")
    if r.get("admin_id") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Bukan setoran Anda")
    if r["status"] not in (CS.REM_PREPARED, CS.REM_REJECTED):
        raise HTTPException(status_code=409, detail="Setoran ini sudah dikirim atau sudah diverifikasi")
    up = await save_upload(db, proof, str(user["_id"]), "remittance")
    await db.files.update_one({"_id": up["file_id"]}, {"$set": {"remittance_id": remittance_id}})
    now = iso(now_utc())
    attempt = {
        "attempt_no": int(r.get("remittance_attempt_count") or 0) + 1,
        "amount": LS.money(r.get("total_amount")),
        "proof_file_id": up["file_id"],
        "submitted_at": now,
        "submitted_by": str(user["_id"]),
        "status": "SUBMITTED",
        "verified_at": None, "verified_by": None,
        "rejected_at": None, "rejected_by": None, "rejection_reason": None,
    }
    res = await db.admin_remittances.update_one(
        {"_id": remittance_id, "status": {"$in": [CS.REM_PREPARED, CS.REM_REJECTED]}},
        {"$set": {"status": CS.REM_WAITING, "proof_file_id": up["file_id"], "submitted_at": now,
                  "submitted_by": str(user["_id"]), "updated_at": now},
         "$push": {"remittance_attempts": attempt},
         "$inc": {"remittance_attempt_count": 1}},
    )
    if res.modified_count == 0:
        await _discard_upload(up["file_id"])
        raise HTTPException(status_code=409, detail="Setoran ini sudah dikirim sebelumnya")
    await audit(request, user, "ADMIN_REMITTANCE_SUBMITTED", "admin_remittance", remittance_id,
                f"Bukti setoran {r['remittance_number']} sebesar {rp(r.get('total_amount'))} dikirim Admin "
                f"(attempt #{attempt['attempt_no']})",
                {"status": r["status"]}, {"status": CS.REM_WAITING, "attempt": attempt})
    await notify_user(r["lender_id"], "loan",
                      f"📥 <b>SETORAN ADMIN</b>\n\n{r['remittance_number']}\nAdmin: {user.get('full_name')}\n"
                      f"Total: {rp(r.get('total_amount'))}\n{r.get('item_count')} pinjaman\n\n"
                      "Mohon verifikasi setoran melalui menu Setoran Admin.", "ADMIN_REMITTANCE_SUBMITTED", None)
    await notify_superadmins("loan", f"ℹ️ Setoran {r['remittance_number']} dikirim {user.get('full_name')} "
                                     f"sebesar {rp(r.get('total_amount'))}", "ADMIN_REMITTANCE_SUBMITTED", None)
    return await CS.serialize_remittance(await db.admin_remittances.find_one({"_id": remittance_id}), viewer=user)


@router.post("/admin-remittances/{remittance_id}/verify")
async def verify_remittance(remittance_id: str, request: Request, user: dict = Depends(require_lender)):
    r = await db.admin_remittances.find_one({"_id": remittance_id})
    if not r:
        raise HTTPException(status_code=404, detail="Setoran tidak ditemukan")
    if r.get("lender_id") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Bukan setoran untuk Anda")
    if r["status"] == CS.REM_VERIFIED:
        raise HTTPException(status_code=409, detail="Setoran ini sudah diverifikasi")
    if r["status"] not in (CS.REM_WAITING, CS.REM_VERIFYING):
        raise HTTPException(status_code=409, detail="Setoran ini tidak sedang menunggu verifikasi")
    if r["status"] == CS.REM_WAITING:
        claim = await db.admin_remittances.update_one(
            {"_id": remittance_id, "status": CS.REM_WAITING},
            {"$set": {"status": CS.REM_VERIFYING, "verifying_at": iso(now_utc())}},
        )
        if claim.modified_count == 0:
            raise HTTPException(status_code=409, detail="Setoran ini sedang diproses")
    await CS.finalize_remittance(remittance_id, user, request)
    return await CS.serialize_remittance(await db.admin_remittances.find_one({"_id": remittance_id}), viewer=user)


@router.post("/admin-remittances/{remittance_id}/finalize")
async def finalize_pending(remittance_id: str, request: Request, user: dict = Depends(require_roles(ROLE_SUPERADMIN, ROLE_LENDER))):
    """Recovery TEKNIS saja: melanjutkan verifikasi yang terhenti di state VERIFYING.

    Bukan endpoint bisnis. Tidak bisa dipakai untuk melewati verifikasi Pendana: state harus
    sudah VERIFYING (artinya Pendana pemilik memang sudah menekan verifikasi).
    """
    r = await db.admin_remittances.find_one({"_id": remittance_id})
    if not r:
        raise HTTPException(status_code=404, detail="Setoran tidak ditemukan")
    CS.assert_can_read_remittance(r, user)
    if r["status"] == CS.REM_VERIFIED:
        return await CS.serialize_remittance(r, viewer=user)
    if r["status"] != CS.REM_VERIFYING:
        raise HTTPException(status_code=409, detail="Setoran ini tidak sedang dalam proses verifikasi Pendana")
    await CS.finalize_remittance(remittance_id, user, request)
    return await CS.serialize_remittance(await db.admin_remittances.find_one({"_id": remittance_id}), viewer=user)


class CancelRemittanceIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/admin-remittances/{remittance_id}/cancel")
async def cancel_remittance(remittance_id: str, payload: CancelRemittanceIn, request: Request,
                            user: dict = Depends(require_staff)):
    r = await db.admin_remittances.find_one({"_id": remittance_id})
    if not r:
        raise HTTPException(status_code=404, detail="Setoran tidak ditemukan")
    if user["role"] == ROLE_ADMIN and r.get("admin_id") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Bukan setoran Anda")
    if r["status"] != CS.REM_PREPARED:
        raise HTTPException(status_code=409, detail="Hanya setoran berstatus Siap Disetor yang dapat dibatalkan")
    if int(r.get("remittance_attempt_count") or 0) > 0 or r.get("proof_file_id"):
        raise HTTPException(status_code=409, detail="Setoran sudah pernah dikirim, gunakan alur verifikasi/penolakan")
    now = iso(now_utc())
    res = await db.admin_remittances.update_one(
        {"_id": remittance_id, "status": CS.REM_PREPARED, "remittance_attempt_count": 0},
        {"$set": {"status": CS.REM_CANCELLED, "cancel_reason": payload.reason.strip(), "cancelled_at": now,
                  "cancelled_by": str(user["_id"]), "updated_at": now}},
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Setoran ini tidak dapat dibatalkan pada status saat ini")
    released = await CS.release_reservations(remittance_id)
    await audit(request, user, "ADMIN_REMITTANCE_CANCELLED", "admin_remittance", remittance_id,
                f"Setoran {r['remittance_number']} ({rp(r.get('total_amount'))}) dibatalkan: {payload.reason.strip()}. "
                f"{released} penerimaan kembali menjadi dana titipan Admin.",
                {"status": CS.REM_PREPARED, "item_count": r.get("item_count")},
                {"status": CS.REM_CANCELLED, "released": released, "reason": payload.reason.strip()})
    if user["role"] == ROLE_SUPERADMIN and r.get("admin_id"):
        await notify_user(r["admin_id"], "loan",
                          f"⚠️ <b>SETORAN DIBATALKAN</b>\n\n{r['remittance_number']} dibatalkan Superadmin.\n"
                          f"Alasan: {payload.reason.strip()}\n\nPenerimaan kembali menjadi dana titipan Anda.",
                          "ADMIN_REMITTANCE_CANCELLED", None)
    return await CS.serialize_remittance(await db.admin_remittances.find_one({"_id": remittance_id}), viewer=user)


@router.post("/admin-remittances/recover-stale")
async def recover_stale(request: Request, user: dict = Depends(require_superadmin)):
    """Bersihkan HANYA reservasi yang memenuhi kriteria stale/orphan (bukan force-unlock)."""
    rem = await CS.recover_stale_reservations(user, request)
    col = await CS.recover_pending_collections(user, request)
    return {**rem, **col, "transaction_mode": await CS.transaction_supported()}


class RejectIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


@router.post("/admin-remittances/{remittance_id}/reject")
async def reject_remittance(remittance_id: str, payload: RejectIn, request: Request, user: dict = Depends(require_lender)):
    r = await db.admin_remittances.find_one({"_id": remittance_id})
    if not r:
        raise HTTPException(status_code=404, detail="Setoran tidak ditemukan")
    if r.get("lender_id") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Bukan setoran untuk Anda")
    now = iso(now_utc())
    last = int(r.get("remittance_attempt_count") or 0) - 1
    res = await db.admin_remittances.update_one(
        {"_id": remittance_id, "status": CS.REM_WAITING},
        {"$set": {
            "status": CS.REM_REJECTED, "rejected_at": now, "rejected_by": str(user["_id"]),
            "rejection_reason": payload.reason, "updated_at": now,
            **({f"remittance_attempts.{last}.status": "REJECTED",
                f"remittance_attempts.{last}.rejected_at": now,
                f"remittance_attempts.{last}.rejected_by": str(user["_id"]),
                f"remittance_attempts.{last}.rejection_reason": payload.reason} if last >= 0 else {}),
        }},
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Setoran ini tidak sedang menunggu verifikasi")
    await audit(request, user, "ADMIN_REMITTANCE_REJECTED", "admin_remittance", remittance_id,
                f"Setoran {r['remittance_number']} ditolak Pendana: {payload.reason}. "
                "Pinjaman tetap Pembayaran Diterima Admin, tidak ada denda baru.",
                {"status": CS.REM_WAITING}, {"status": CS.REM_REJECTED, "reason": payload.reason})
    await notify_user(r["admin_id"], "loan",
                      f"⚠️ <b>SETORAN DITOLAK</b>\n\n{r['remittance_number']}\nAlasan: {payload.reason}\n\n"
                      "Silakan unggah ulang bukti setoran.", "ADMIN_REMITTANCE_REJECTED", None)
    await notify_superadmins("loan", f"⚠️ Setoran {r['remittance_number']} ditolak Pendana: {payload.reason}",
                             "ADMIN_REMITTANCE_REJECTED", None)
    return await CS.serialize_remittance(await db.admin_remittances.find_one({"_id": remittance_id}), viewer=user)
