import uuid
from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, UploadFile, File, Form, Query, Response
from pydantic import BaseModel, Field
from core import (
    db, now_utc, iso, parse_dt, audit, get_settings, get_current_user, require_staff, require_lender,
    require_borrower, ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_LENDER, ROLE_BORROWER,
)
from notif import notify_admins, notify_all_lenders, notify_user, rp, id_datetime
from storage import save_upload, get_object
import loan_service as LS

router = APIRouter(prefix="/api", tags=["loans"])


class LoanIn(BaseModel):
    principal_amount: int = Field(gt=0)
    duration_days: int = Field(gt=0)


async def _get_loan_or_404(loan_id: str) -> dict:
    loan = await db.loans.find_one({"_id": loan_id})
    if not loan:
        raise HTTPException(status_code=404, detail="Pinjaman tidak ditemukan")
    return loan


def _assert_loan_access(loan: dict, user: dict):
    role = user["role"]
    if role in (ROLE_SUPERADMIN, ROLE_ADMIN):
        return
    if role == ROLE_BORROWER and loan["borrower_id"] == str(user["_id"]):
        return
    if role == ROLE_LENDER:
        if loan.get("funded_by") == str(user["_id"]):
            return
        if loan["status"] == LS.S_WAITING_FUNDING and not loan.get("funded_by"):
            return
    raise HTTPException(status_code=403, detail="Anda tidak memiliki akses ke pinjaman ini")


@router.post("/loans")
async def create_loan(payload: LoanIn, request: Request, user: dict = Depends(require_borrower)):
    if user.get("account_status") != "ACTIVE":
        raise HTTPException(status_code=403, detail="Akun Anda belum aktif. Menunggu verifikasi Admin.")
    credit = await LS.borrower_credit(user)
    if payload.principal_amount > credit["available_limit"]:
        raise HTTPException(
            status_code=400,
            detail=f"Nominal melebihi limit tersedia Anda ({rp(credit['available_limit'])}).",
        )
    if payload.duration_days > credit["max_duration_days"]:
        raise HTTPException(
            status_code=400, detail=f"Durasi maksimal Anda adalah {credit['max_duration_days']} hari."
        )
    if credit["active_loans"] >= credit["max_active_loans"]:
        raise HTTPException(
            status_code=400,
            detail=f"Anda telah mencapai maksimal {credit['max_active_loans']} pinjaman aktif.",
        )

    recent = await db.loans.find_one(
        {
            "borrower_id": str(user["_id"]),
            "principal_amount": payload.principal_amount,
            "duration_days": payload.duration_days,
            "submitted_at": {"$gte": iso(now_utc() - timedelta(seconds=20))},
        }
    )
    if recent:
        return await LS.serialize_loan(recent)

    s = await get_settings()
    interest_rate = float(s["interest_rate"])
    late_fee_rate = float(s["late_fee_rate_per_day"])
    interest_amount = LS.calc_interest(payload.principal_amount, interest_rate)
    loan_id = str(uuid.uuid4())
    doc = {
        "_id": loan_id,
        "loan_number": await LS.next_loan_number(),
        "borrower_id": str(user["_id"]),
        "principal_amount": LS.money(payload.principal_amount),
        "duration_days": payload.duration_days,
        "interest_rate": interest_rate,
        "interest_amount": interest_amount,
        "late_fee_rate": late_fee_rate,
        "base_repayment_amount": LS.money(payload.principal_amount) + interest_amount,
        "status": LS.S_WAITING_ADMIN,
        "submitted_at": iso(now_utc()),
        "funded_by": None,
        "due_date": None,
    }
    await db.loans.insert_one(doc)
    await LS.record_status(loan_id, None, LS.S_WAITING_ADMIN, user, "Pengajuan pinjaman dibuat")
    await audit(
        request, user, "LOAN_SUBMITTED", "loan", loan_id,
        f"Pengajuan pinjaman {doc['loan_number']} sebesar {rp(doc['principal_amount'])}", None,
        {"principal_amount": doc["principal_amount"], "duration_days": doc["duration_days"]},
    )
    text = (
        "💰 <b>PENGAJUAN PINJAMAN BARU</b>\n\n"
        f"ID:\n{doc['loan_number']}\n\n"
        f"Peminjam:\n{user['full_name']}\n\n"
        f"Nominal:\n{rp(doc['principal_amount'])}\n\n"
        f"Durasi:\n{doc['duration_days']} Hari\n\n"
        f"Bunga:\n{interest_rate}%\n\n"
        f"Total Pengembalian:\n{rp(doc['base_repayment_amount'])}\n\n"
        "Status:\nMenunggu Persetujuan Admin"
    )
    await notify_admins("loan", text, "LOAN_SUBMITTED", loan_id)
    return await LS.serialize_loan(doc)


@router.get("/loans")
async def list_loans(
    user: dict = Depends(get_current_user),
    status: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    sort: str = "-submitted_at",
):
    query: dict = {}
    statuses = [s.strip() for s in status.split(",") if s.strip()] if status else []
    role = user["role"]
    if role == ROLE_BORROWER:
        query["borrower_id"] = str(user["_id"])
    elif role == ROLE_LENDER:
        if statuses == [LS.S_WAITING_FUNDING]:
            query["funded_by"] = None
        else:
            query["funded_by"] = str(user["_id"])
    if statuses:
        query["status"] = {"$in": statuses}
    if q:
        ids = [
            str(u["_id"])
            for u in await db.users.find(
                {"role": ROLE_BORROWER, "$or": [{"full_name": {"$regex": q, "$options": "i"}}, {"nik": {"$regex": q}}]},
                {"_id": 1},
            ).to_list(200)
        ]
        or_clause = [{"loan_number": {"$regex": q, "$options": "i"}}, {"borrower_id": {"$in": ids}}]
        if role == ROLE_BORROWER:
            or_clause = [{"loan_number": {"$regex": q, "$options": "i"}}]
        query["$and"] = [{"$or": or_clause}]
    total = await db.loans.count_documents(query)
    direction = -1 if sort.startswith("-") else 1
    field = sort.lstrip("-")
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    docs = (
        await db.loans.find(query)
        .sort(field, direction)
        .skip((page - 1) * page_size)
        .limit(page_size)
        .to_list(page_size)
    )
    items = [await LS.serialize_loan(d) for d in docs]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/loans/{loan_id}")
async def get_loan(loan_id: str, user: dict = Depends(get_current_user)):
    loan = await _get_loan_or_404(loan_id)
    _assert_loan_access(loan, user)
    out = await LS.serialize_loan(loan, deep=True)
    if user["role"] in (ROLE_SUPERADMIN, ROLE_ADMIN):
        borrower = await db.users.find_one({"_id": loan["borrower_id"]})
        out["borrower_credit"] = await LS.borrower_credit(borrower)
    if user["role"] == ROLE_BORROWER:
        out.pop("borrower_nik", None)
    if user["role"] == ROLE_LENDER and loan.get("funded_by") != str(user["_id"]):
        out.pop("borrower_bank", None)
        out.pop("borrower_nik", None)
    return out


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/loans/{loan_id}/approve")
async def approve_loan(loan_id: str, request: Request, user: dict = Depends(require_staff)):
    res = await db.loans.update_one(
        {"_id": loan_id, "status": LS.S_WAITING_ADMIN},
        {
            "$set": {
                "status": LS.S_WAITING_FUNDING,
                "approved_by": str(user["_id"]),
                "approved_by_name": user.get("full_name"),
                "approved_at": iso(now_utc()),
            }
        },
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Pengajuan ini sudah diproses sebelumnya")
    loan = await _get_loan_or_404(loan_id)
    await LS.record_status(loan_id, LS.S_WAITING_ADMIN, LS.S_WAITING_FUNDING, user, "Pengajuan disetujui")
    await audit(request, user, "LOAN_APPROVED", "loan", loan_id, f"Pinjaman {loan['loan_number']} disetujui")
    borrower = await db.users.find_one({"_id": loan["borrower_id"]})
    text = (
        "💵 <b>PINJAMAN SIAP DIDANAI</b>\n\n"
        f"ID:\n{loan['loan_number']}\n\n"
        f"Peminjam:\n{borrower.get('full_name')}\n\n"
        f"Nominal:\n{rp(loan['principal_amount'])}\n\n"
        f"Durasi:\n{loan['duration_days']} Hari\n\n"
        f"Total Pengembalian:\n{rp(loan['base_repayment_amount'])}\n\n"
        "Silakan login ke aplikasi apabila ingin mengambil pendanaan."
    )
    await notify_all_lenders(text, "LOAN_WAITING_FUNDING", loan_id)
    return await LS.serialize_loan(loan)


@router.post("/loans/{loan_id}/reject")
async def reject_loan(loan_id: str, payload: RejectIn, request: Request, user: dict = Depends(require_staff)):
    res = await db.loans.update_one(
        {"_id": loan_id, "status": LS.S_WAITING_ADMIN},
        {
            "$set": {
                "status": LS.S_REJECTED,
                "rejected_by": str(user["_id"]),
                "rejected_at": iso(now_utc()),
                "rejection_reason": payload.reason,
            }
        },
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Pengajuan ini sudah diproses sebelumnya")
    loan = await _get_loan_or_404(loan_id)
    await LS.record_status(loan_id, LS.S_WAITING_ADMIN, LS.S_REJECTED, user, payload.reason)
    await audit(request, user, "LOAN_REJECTED", "loan", loan_id, f"Pinjaman {loan['loan_number']} ditolak: {payload.reason}")
    return await LS.serialize_loan(loan)


@router.post("/loans/{loan_id}/claim")
async def claim_loan(loan_id: str, request: Request, user: dict = Depends(require_lender)):
    res = await db.loans.update_one(
        {"_id": loan_id, "status": LS.S_WAITING_FUNDING, "funded_by": None},
        {
            "$set": {
                "status": LS.S_FUNDING_CLAIMED,
                "funded_by": str(user["_id"]),
                "funded_at": iso(now_utc()),
            }
        },
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Pinjaman ini sudah diambil oleh Pendana lain.")
    loan = await _get_loan_or_404(loan_id)
    await LS.record_status(loan_id, LS.S_WAITING_FUNDING, LS.S_FUNDING_CLAIMED, user, "Pendanaan diambil")
    await audit(request, user, "FUNDING_CLAIMED", "loan", loan_id, f"Pendanaan {loan['loan_number']} diambil oleh {user.get('full_name')}")
    await notify_admins(
        "loan",
        f"📌 <b>PENDANAAN DIAMBIL</b>\n\n{loan['loan_number']}\nPendana: {user.get('full_name')}\nNominal: {rp(loan['principal_amount'])}",
        "FUNDING_CLAIMED",
        loan_id,
    )
    return await LS.serialize_loan(loan, deep=True)


@router.post("/loans/{loan_id}/disburse")
async def disburse_loan(
    loan_id: str,
    request: Request,
    amount: int = Form(...),
    transfer_at: str = Form(...),
    notes: str = Form(""),
    proof: UploadFile = File(...),
    user: dict = Depends(require_lender),
):
    loan = await _get_loan_or_404(loan_id)
    if loan.get("funded_by") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Hanya Pendana yang mengambil pinjaman ini yang dapat mencairkan")
    if loan["status"] != LS.S_FUNDING_CLAIMED:
        raise HTTPException(status_code=409, detail="Pinjaman ini tidak dalam status menunggu pencairan")
    if LS.money(amount) != LS.money(loan["principal_amount"]):
        raise HTTPException(
            status_code=400, detail=f"Nominal transfer harus sama dengan pokok pinjaman ({rp(loan['principal_amount'])})"
        )
    upload = await save_upload(db, proof, str(user["_id"]), "disbursement")
    res = await db.loans.update_one(
        {"_id": loan_id, "status": LS.S_FUNDING_CLAIMED},
        {"$set": {"status": LS.S_WAITING_DISB, "disbursed_reported_at": iso(now_utc())}},
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Pencairan sudah dilaporkan sebelumnya")
    disb_id = str(uuid.uuid4())
    await db.disbursements.insert_one(
        {
            "_id": disb_id,
            "loan_id": loan_id,
            "lender_id": str(user["_id"]),
            "amount": LS.money(amount),
            "transfer_at": transfer_at,
            "proof_file_id": upload["file_id"],
            "notes": notes,
            "created_at": iso(now_utc()),
            "confirmed_at": None,
        }
    )
    await db.files.update_one({"_id": upload["file_id"]}, {"$set": {"loan_id": loan_id}})
    await LS.record_status(loan_id, LS.S_FUNDING_CLAIMED, LS.S_WAITING_DISB, user, "Dana ditransfer, menunggu konfirmasi Admin")
    await audit(request, user, "DISBURSEMENT_REPORTED", "loan", loan_id, f"Pencairan {loan['loan_number']} dilaporkan sebesar {rp(amount)}")
    await notify_admins(
        "loan",
        f"📤 <b>PENCAIRAN DILAPORKAN</b>\n\n{loan['loan_number']}\nPendana: {user.get('full_name')}\nNominal: {rp(amount)}\n\nMenunggu konfirmasi Admin.",
        "DISBURSEMENT_REPORTED",
        loan_id,
    )
    return await LS.serialize_loan(await _get_loan_or_404(loan_id), deep=True)


@router.post("/loans/{loan_id}/confirm-disbursement")
async def confirm_disbursement(loan_id: str, request: Request, user: dict = Depends(require_staff)):
    loan = await _get_loan_or_404(loan_id)
    if loan["status"] != LS.S_WAITING_DISB:
        raise HTTPException(status_code=409, detail="Pencairan ini sudah dikonfirmasi atau belum dilaporkan")
    disbursed_at = now_utc()
    due_date = disbursed_at + timedelta(days=int(loan["duration_days"]))
    res = await db.loans.update_one(
        {"_id": loan_id, "status": LS.S_WAITING_DISB},
        {
            "$set": {
                "status": LS.S_ACTIVE,
                "disbursed_at": iso(disbursed_at),
                "due_date": iso(due_date),
                "disbursement_confirmed_by": str(user["_id"]),
                "disbursement_confirmed_at": iso(disbursed_at),
            }
        },
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Pencairan sudah dikonfirmasi")
    await db.disbursements.update_one({"loan_id": loan_id}, {"$set": {"confirmed_at": iso(disbursed_at)}})
    await LS.record_status(loan_id, LS.S_WAITING_DISB, LS.S_ACTIVE, user, "Pencairan dikonfirmasi Admin")
    await audit(request, user, "DISBURSEMENT_CONFIRMED", "loan", loan_id, f"Pencairan {loan['loan_number']} dikonfirmasi")
    text = (
        f"✅ <b>PINJAMAN AKTIF</b>\n\n{loan['loan_number']}\nJatuh Tempo: {id_datetime(due_date)}\n"
        f"Total Tagihan: {rp(loan['base_repayment_amount'])}"
    )
    if loan.get("funded_by"):
        await notify_user(loan["funded_by"], "loan", text, "LOAN_ACTIVE", loan_id)
    return await LS.serialize_loan(await _get_loan_or_404(loan_id), deep=True)


@router.post("/loans/{loan_id}/pay")
async def report_payment(
    loan_id: str,
    request: Request,
    amount: int = Form(...),
    paid_at: str = Form(...),
    notes: str = Form(""),
    proof: UploadFile = File(...),
    user: dict = Depends(require_borrower),
):
    loan = await _get_loan_or_404(loan_id)
    if loan["borrower_id"] != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Bukan pinjaman Anda")
    if loan["status"] not in (LS.S_ACTIVE, LS.S_OVERDUE):
        raise HTTPException(status_code=409, detail="Pinjaman ini tidak dalam status dapat dibayar")
    at = now_utc()
    due = parse_dt(loan.get("due_date"))
    late_days = LS.late_days_for(due, at)
    late_fee = LS.calc_late_fee(LS.money(loan["principal_amount"]), loan.get("late_fee_rate") or 0, late_days)
    amount_due = LS.money(loan["base_repayment_amount"]) + late_fee
    if LS.money(amount) < amount_due:
        raise HTTPException(
            status_code=400, detail=f"Pembayaran harus dilakukan sekaligus penuh sebesar {rp(amount_due)}"
        )
    upload = await save_upload(db, proof, str(user["_id"]), "payment")
    res = await db.loans.update_one(
        {"_id": loan_id, "status": loan["status"]}, {"$set": {"status": LS.S_WAITING_PAYMENT}}
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Laporan pembayaran sudah dikirim")
    attempt_no = await db.payments.count_documents({"loan_id": loan_id}) + 1
    payment_id = str(uuid.uuid4())
    await db.payments.insert_one(
        {
            "_id": payment_id,
            "loan_id": loan_id,
            "borrower_id": str(user["_id"]),
            "lender_id": loan.get("funded_by"),
            "attempt_no": attempt_no,
            "amount_paid": LS.money(amount),
            "amount_due_at_submission": amount_due,
            "late_days_at_submission": late_days,
            "late_fee_at_submission": late_fee,
            "payment_submitted_at": iso(at),
            "paid_at_reported": paid_at,
            "proof_file_id": upload["file_id"],
            "notes": notes,
            "status": "PENDING",
            "created_at": iso(at),
        }
    )
    await db.files.update_one({"_id": upload["file_id"]}, {"$set": {"loan_id": loan_id}})
    await LS.record_status(loan_id, loan["status"], LS.S_WAITING_PAYMENT, user, f"Pembayaran dilaporkan {rp(amount)}")
    await audit(request, user, "PAYMENT_SUBMITTED", "payment", payment_id, f"Pembayaran {loan['loan_number']} dilaporkan sebesar {rp(amount)}")
    lender = await db.users.find_one({"_id": loan.get("funded_by")}) if loan.get("funded_by") else None
    if lender:
        await notify_user(
            str(lender["_id"]), "loan",
            "💰 <b>PEMBAYARAN PINJAMAN</b>\n\n"
            f"Loan:\n{loan['loan_number']}\n\nPeminjam:\n{user['full_name']}\n\n"
            f"Tagihan:\n{rp(amount_due)}\n\nDilaporkan Dibayar:\n{rp(amount)}\n\n"
            "Silakan cek rekening Anda dan lakukan verifikasi melalui aplikasi.",
            "PAYMENT_SUBMITTED", loan_id,
        )
    await notify_admins(
        "loan",
        "💰 <b>PEMBAYARAN DILAPORKAN</b>\n\n"
        f"{user['full_name']} telah melaporkan pembayaran:\n\n{loan['loan_number']}\n{rp(amount)}\n\n"
        f"Pendana:\n{(lender or {}).get('full_name', '-')}\n\nStatus:\nMenunggu Verifikasi Pendana",
        "PAYMENT_SUBMITTED_ADMIN", loan_id,
    )
    return await LS.serialize_loan(await _get_loan_or_404(loan_id), deep=True)


@router.get("/payments")
async def list_payments(
    user: dict = Depends(get_current_user),
    status: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    query: dict = {}
    if user["role"] == ROLE_LENDER:
        query["lender_id"] = str(user["_id"])
    elif user["role"] == ROLE_BORROWER:
        query["borrower_id"] = str(user["_id"])
    if status:
        query["status"] = {"$in": [s.strip() for s in status.split(",") if s.strip()]}
    total = await db.payments.count_documents(query)
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    docs = (
        await db.payments.find(query).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    )
    items = []
    for p in docs:
        loan = await db.loans.find_one({"_id": p["loan_id"]})
        borrower = await db.users.find_one({"_id": p["borrower_id"]})
        lender = await db.users.find_one({"_id": p["lender_id"]}) if p.get("lender_id") else None
        if q and q.lower() not in (loan or {}).get("loan_number", "").lower() and q.lower() not in ((borrower or {}).get("full_name") or "").lower():
            continue
        items.append(
            {
                "id": str(p["_id"]),
                "loan_id": p["loan_id"],
                "loan_number": (loan or {}).get("loan_number"),
                "borrower_name": (borrower or {}).get("full_name"),
                "lender_name": (lender or {}).get("full_name"),
                "attempt_no": p.get("attempt_no"),
                "amount_paid": LS.money(p["amount_paid"]),
                "amount_due_at_submission": LS.money(p["amount_due_at_submission"]),
                "late_days_at_submission": p.get("late_days_at_submission"),
                "late_fee_at_submission": LS.money(p.get("late_fee_at_submission")),
                "payment_submitted_at": p.get("payment_submitted_at"),
                "proof_file_id": p.get("proof_file_id"),
                "notes": p.get("notes"),
                "status": p["status"],
                "rejection_reason": p.get("rejection_reason"),
                "verified_at": p.get("verified_at"),
                "lender_bank": (
                    {
                        "bank_name": (lender or {}).get("bank_name"),
                        "account_number": (lender or {}).get("account_number"),
                        "account_holder": (lender or {}).get("account_holder"),
                    }
                    if lender
                    else None
                ),
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/payments/{payment_id}/verify")
async def verify_payment(payment_id: str, request: Request, user: dict = Depends(require_lender)):
    payment = await db.payments.find_one({"_id": payment_id})
    if not payment:
        raise HTTPException(status_code=404, detail="Pembayaran tidak ditemukan")
    if payment.get("lender_id") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Hanya Pendana pemilik pinjaman ini yang dapat memverifikasi")
    res = await db.payments.update_one(
        {"_id": payment_id, "status": "PENDING"},
        {
            "$set": {
                "status": "VERIFIED",
                "verified_at": iso(now_utc()),
                "verified_by": str(user["_id"]),
                "verified_by_name": user.get("full_name"),
            }
        },
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Pembayaran ini sudah diverifikasi sebelumnya")
    loan = await _get_loan_or_404(payment["loan_id"])
    await db.loans.update_one(
        {"_id": loan["_id"]},
        {
            "$set": {
                "status": LS.S_PAID,
                "paid_at": iso(now_utc()),
                "payment_verified_at": iso(now_utc()),
                "payment_verified_by": str(user["_id"]),
                "actual_payment_amount": LS.money(payment["amount_paid"]),
                "late_days_final": payment.get("late_days_at_submission") or 0,
                "late_fee_final": LS.money(payment.get("late_fee_at_submission")),
            }
        },
    )
    await LS.record_status(str(loan["_id"]), loan["status"], LS.S_PAID, user, "Pembayaran diverifikasi Pendana")
    await audit(request, user, "PAYMENT_VERIFIED", "loan", str(loan["_id"]), f"Pembayaran {loan['loan_number']} diverifikasi, pinjaman LUNAS")
    await notify_admins(
        "loan",
        f"🎉 <b>PINJAMAN LUNAS</b>\n\n{loan['loan_number']}\nNominal: {rp(payment['amount_paid'])}\nDiverifikasi: {user.get('full_name')}",
        "LOAN_PAID", str(loan["_id"]),
    )
    return await LS.serialize_loan(await _get_loan_or_404(str(loan["_id"])), deep=True)


@router.post("/payments/{payment_id}/reject")
async def reject_payment(payment_id: str, payload: RejectIn, request: Request, user: dict = Depends(require_lender)):
    payment = await db.payments.find_one({"_id": payment_id})
    if not payment:
        raise HTTPException(status_code=404, detail="Pembayaran tidak ditemukan")
    if payment.get("lender_id") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Hanya Pendana pemilik pinjaman ini yang dapat menolak pembayaran")
    res = await db.payments.update_one(
        {"_id": payment_id, "status": "PENDING"},
        {
            "$set": {
                "status": "REJECTED",
                "rejection_reason": payload.reason,
                "verified_at": iso(now_utc()),
                "verified_by": str(user["_id"]),
                "verified_by_name": user.get("full_name"),
            }
        },
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Pembayaran ini sudah diproses sebelumnya")
    loan = await _get_loan_or_404(payment["loan_id"])
    due = parse_dt(loan.get("due_date"))
    new_status = LS.S_OVERDUE if due and now_utc() > due else LS.S_ACTIVE
    await db.loans.update_one({"_id": loan["_id"]}, {"$set": {"status": new_status}})
    await LS.record_status(str(loan["_id"]), LS.S_WAITING_PAYMENT, new_status, user, f"Pembayaran ditolak: {payload.reason}")
    await audit(request, user, "PAYMENT_REJECTED", "payment", payment_id, f"Pembayaran {loan['loan_number']} ditolak: {payload.reason}")
    return await LS.serialize_loan(await _get_loan_or_404(str(loan["_id"])), deep=True)


@router.get("/files/{file_id}")
async def download_file(file_id: str, user: dict = Depends(get_current_user)):
    rec = await db.files.find_one({"_id": file_id, "is_deleted": False})
    if not rec:
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    if user["role"] not in (ROLE_SUPERADMIN, ROLE_ADMIN) and rec.get("uploaded_by") != str(user["_id"]):
        loan = await db.loans.find_one({"_id": rec.get("loan_id")}) if rec.get("loan_id") else None
        allowed = loan and (loan["borrower_id"] == str(user["_id"]) or loan.get("funded_by") == str(user["_id"]))
        if not allowed:
            raise HTTPException(status_code=403, detail="Tidak memiliki akses ke file ini")
    try:
        data, content_type = get_object(rec["storage_path"])
    except Exception:
        raise HTTPException(status_code=502, detail="Gagal mengambil file")
    return Response(
        content=data,
        media_type=rec.get("content_type") or content_type,
        headers={"Cache-Control": "private, no-store"},
    )
