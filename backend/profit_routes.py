import asyncio
import csv
import io
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, UploadFile, File, Query, Response
from pydantic import BaseModel, Field
from core import (
    db, now_utc, iso, audit, get_settings, get_current_user, require_superadmin, require_lender,
    ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_LENDER,
)
from notif import notify_user, notify_admins, rp
from storage import save_upload
import loan_service as LS
import profit_service as PS

router = APIRouter(prefix="/api", tags=["profit-sharing"])


# ---------------- settings ----------------
class ProfitSharingIn(BaseModel):
    lender_pct: float = Field(ge=0, le=100)
    admin_pct: float = Field(ge=0, le=100)
    platform_pct: float = Field(ge=0, le=100)


@router.get("/settings/profit-sharing")
async def get_profit_sharing(user: dict = Depends(require_superadmin)):
    s = await get_settings()
    return {
        "lender_pct": s.get("profit_share_lender_pct"),
        "admin_pct": s.get("profit_share_admin_pct"),
        "platform_pct": s.get("profit_share_platform_pct"),
    }


@router.put("/settings/profit-sharing")
async def update_profit_sharing(payload: ProfitSharingIn, request: Request, user: dict = Depends(require_superadmin)):
    valid = PS.validate_percentages(payload.lender_pct, payload.admin_pct, payload.platform_pct)
    s = await get_settings()
    old = {
        "lender_pct": s.get("profit_share_lender_pct"),
        "admin_pct": s.get("profit_share_admin_pct"),
        "platform_pct": s.get("profit_share_platform_pct"),
    }
    await db.settings.update_one(
        {"_id": "app"},
        {
            "$set": {
                "profit_share_lender_pct": valid["lender_pct"],
                "profit_share_admin_pct": valid["admin_pct"],
                "profit_share_platform_pct": valid["platform_pct"],
            }
        },
        upsert=True,
    )
    await audit(
        request, user, "PROFIT_SHARE_SETTINGS_UPDATED", "settings", "app",
        f"Persentase bagi hasil diubah menjadi Pendana {valid['lender_pct']}%, Admin {valid['admin_pct']}%, "
        f"Aplikator {valid['platform_pct']}%. Pinjaman yang sudah disetujui tetap memakai snapshot lama.",
        old, valid,
    )
    return await get_profit_sharing(user)


class SettlementAccountIn(BaseModel):
    settlement_account_type: str = Field(min_length=2, max_length=40)
    settlement_account_number: str = Field(min_length=4, max_length=40)
    settlement_account_holder: str = Field(min_length=2, max_length=80)
    settlement_account_bank_name: Optional[str] = Field(default="", max_length=80)
    settlement_instructions: Optional[str] = Field(default="", max_length=500)


@router.get("/settings/settlement-account")
async def get_settlement_account(user: dict = Depends(get_current_user)):
    if user.get("role") not in (ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_LENDER):
        raise HTTPException(status_code=403, detail="Anda tidak memiliki akses ke rekening settlement")
    return PS.settlement_account(await get_settings())


@router.put("/settings/settlement-account")
async def update_settlement_account(payload: SettlementAccountIn, request: Request, user: dict = Depends(require_superadmin)):
    s = await get_settings()
    old = PS.settlement_account(s)
    new = {
        "settlement_account_type": payload.settlement_account_type.strip(),
        "settlement_account_number": payload.settlement_account_number.strip(),
        "settlement_account_holder": payload.settlement_account_holder.strip(),
        "settlement_account_bank_name": (payload.settlement_account_bank_name or "").strip(),
        "settlement_instructions": (payload.settlement_instructions or "").strip(),
    }
    await db.settings.update_one({"_id": "app"}, {"$set": new}, upsert=True)
    await audit(request, user, "SETTLEMENT_ACCOUNT_UPDATED", "settings", "app",
                "Rekening settlement pusat diperbarui", old, new)
    return PS.settlement_account(await get_settings())


# ---------------- distributions ----------------
def _filters(settlement_status, payout_status, lender_id, admin_id, paid_from, paid_to, include_reversed) -> dict:
    query: dict = {}
    if settlement_status:
        query["lender_settlement_status"] = {"$in": [s.strip() for s in settlement_status.split(",") if s.strip()]}
    if payout_status:
        query["admin_payout_status"] = {"$in": [s.strip() for s in payout_status.split(",") if s.strip()]}
    if lender_id:
        query["lender_id"] = lender_id
    if admin_id:
        query["assigned_admin_id"] = admin_id
    if paid_from or paid_to:
        rng = {}
        if paid_from:
            rng["$gte"] = paid_from
        if paid_to:
            rng["$lte"] = paid_to + "T23:59:59+00:00"
        query["paid_at"] = rng
    if not include_reversed:
        query["is_reversed"] = {"$ne": True}
    return query


@router.get("/profit-distributions/summary")
async def distributions_summary(user: dict = Depends(get_current_user)):
    return await PS.summary_for(user)


@router.get("/profit-distributions/export.csv")
async def export_distributions(
    user: dict = Depends(require_superadmin),
    settlement_status: Optional[str] = None,
    payout_status: Optional[str] = None,
    lender_id: Optional[str] = None,
    admin_id: Optional[str] = None,
    paid_from: Optional[str] = None,
    paid_to: Optional[str] = None,
):
    query = _filters(settlement_status, payout_status, lender_id, admin_id, paid_from, paid_to, True)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "loan_number", "paid_at", "borrower_name", "lender_name", "admin_name", "principal",
        "interest_realized", "late_fee_realized", "profit_pool", "lender_pct", "admin_pct", "platform_pct",
        "lender_profit", "admin_profit", "platform_profit", "lender_settlement_due", "settlement_status",
        "settlement_submitted_at", "settlement_verified_at", "admin_payout_status", "admin_payout_paid_at",
        "is_reversed",
    ])
    async for d in db.profit_distributions.find(query).sort("created_at", -1):
        item = await PS.serialize_distribution(d)
        writer.writerow([
            item.get("loan_number"), item.get("paid_at"), item.get("borrower_name"), item.get("lender_name"),
            item.get("admin_name"), item.get("principal"), item.get("interest_realized"), item.get("late_fee_realized"),
            item.get("profit_pool"), item.get("lender_pct_snapshot"), item.get("admin_pct_snapshot"),
            item.get("platform_pct_snapshot"), item.get("lender_profit"), item.get("admin_profit"),
            item.get("platform_profit"), item.get("lender_settlement_due"), item.get("lender_settlement_status"),
            item.get("settlement_submitted_at"), item.get("settlement_verified_at"), item.get("admin_payout_status"),
            item.get("admin_payout_paid_at"), item.get("is_reversed"),
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bagi-hasil.csv", "Cache-Control": "private, no-store"},
    )


@router.get("/profit-distributions")
async def list_distributions(
    user: dict = Depends(get_current_user),
    settlement_status: Optional[str] = None,
    payout_status: Optional[str] = None,
    lender_id: Optional[str] = None,
    admin_id: Optional[str] = None,
    paid_from: Optional[str] = None,
    paid_to: Optional[str] = None,
    include_reversed: bool = False,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
):
    query = {**_filters(settlement_status, payout_status, lender_id, admin_id, paid_from, paid_to, include_reversed),
             **PS.role_query(user)}
    total = await db.profit_distributions.count_documents(query)
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    docs = (
        await db.profit_distributions.find(query)
        .sort("created_at", -1)
        .skip((page - 1) * page_size)
        .limit(page_size)
        .to_list(page_size)
    )
    items = [await PS.serialize_distribution(d) for d in docs]
    if q:
        needle = q.lower()
        items = [
            i for i in items
            if needle in (i.get("loan_number") or "").lower()
            or needle in (i.get("borrower_name") or "").lower()
            or needle in (i.get("lender_name") or "").lower()
            or needle in (i.get("admin_name") or "").lower()
        ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def _get_distribution(dist_id: str) -> dict:
    d = await db.profit_distributions.find_one({"_id": dist_id})
    if not d:
        raise HTTPException(status_code=404, detail="Data pembagian hasil tidak ditemukan")
    return d


@router.get("/profit-distributions/{dist_id}")
async def get_distribution(dist_id: str, user: dict = Depends(get_current_user)):
    d = await _get_distribution(dist_id)
    PS.assert_can_read(d, user)
    out = await PS.serialize_distribution(d)
    if user.get("role") in (ROLE_SUPERADMIN, ROLE_LENDER):
        out["settlement_account"] = PS.settlement_account(await get_settings())
    return out


# ---------------- lender settlement ----------------
@router.post("/profit-distributions/{dist_id}/settlement")
async def submit_settlement(
    dist_id: str,
    request: Request,
    proof: UploadFile = File(...),
    user: dict = Depends(require_lender),
):
    d = await _get_distribution(dist_id)
    if d.get("lender_id") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Anda hanya dapat menyetor bagi hasil milik Anda sendiri")
    if d.get("is_reversed"):
        raise HTTPException(status_code=409, detail="Pembagian hasil ini telah dibatalkan")
    if d.get("lender_settlement_status") != PS.SET_PENDING:
        raise HTTPException(status_code=409, detail="Setoran bagi hasil ini sudah diproses sebelumnya")
    up = await save_upload(db, proof, str(user["_id"]), "settlement")
    await db.files.update_one(
        {"_id": up["file_id"]},
        {"$set": {"loan_id": d.get("loan_id"), "profit_distribution_id": dist_id}},
    )
    res = await db.profit_distributions.update_one(
        {"_id": dist_id, "lender_settlement_status": PS.SET_PENDING},
        {
            "$set": {
                "lender_settlement_status": PS.SET_WAITING,
                "settlement_proof_file_id": up["file_id"],
                "settlement_submitted_at": iso(now_utc()),
                "settlement_submitted_by": str(user["_id"]),
                "settlement_rejection_reason": None,
                "updated_at": iso(now_utc()),
            },
            "$inc": {"settlement_attempts": 1},
        },
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Setoran bagi hasil ini sudah diproses sebelumnya")
    await audit(
        request, user, "LENDER_SETTLEMENT_SUBMITTED", "profit_distribution", dist_id,
        f"Setoran bagi hasil {d.get('loan_number')} sebesar {rp(d.get('lender_settlement_due'))} dilaporkan Pendana",
        {"lender_settlement_status": PS.SET_PENDING},
        {"lender_settlement_status": PS.SET_WAITING, "amount": LS.money(d.get("lender_settlement_due"))},
    )
    await notify_admins(
        "loan",
        f"📥 <b>SETORAN BAGI HASIL</b>\n\n{d.get('loan_number')}\nPendana: {user.get('full_name')}\n"
        f"Nominal: {rp(d.get('lender_settlement_due'))}\n\nMenunggu verifikasi Superadmin.",
        "LENDER_SETTLEMENT_SUBMITTED", d.get("loan_id"),
    )
    return await PS.serialize_distribution(await _get_distribution(dist_id))


@router.post("/profit-distributions/{dist_id}/settlement/verify")
async def verify_settlement(dist_id: str, request: Request, user: dict = Depends(require_superadmin)):
    d = await _get_distribution(dist_id)
    now = iso(now_utc())
    res = await db.profit_distributions.update_one(
        {"_id": dist_id, "lender_settlement_status": PS.SET_WAITING},
        {
            "$set": {
                "lender_settlement_status": PS.SET_SETTLED,
                "settlement_verified_at": now,
                "settlement_verified_by": str(user["_id"]),
                "admin_payout_status": PS.PAYOUT_PENDING,
                "updated_at": now,
            }
        },
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Setoran ini tidak sedang menunggu verifikasi")
    await audit(
        request, user, "LENDER_SETTLEMENT_VERIFIED", "profit_distribution", dist_id,
        f"Setoran bagi hasil {d.get('loan_number')} sebesar {rp(d.get('lender_settlement_due'))} diverifikasi Superadmin",
        {"lender_settlement_status": PS.SET_WAITING, "admin_payout_status": d.get("admin_payout_status")},
        {"lender_settlement_status": PS.SET_SETTLED, "admin_payout_status": PS.PAYOUT_PENDING},
    )
    if d.get("lender_id"):
        await notify_user(
            d["lender_id"], "loan",
            f"✅ <b>SETORAN DITERIMA</b>\n\nSetoran bagi hasil {d.get('loan_number')} sebesar "
            f"{rp(d.get('lender_settlement_due'))} telah diverifikasi. Terima kasih.",
            "LENDER_SETTLEMENT_VERIFIED", d.get("loan_id"),
        )
    if d.get("assigned_admin_id") and LS.money(d.get("admin_profit")) > 0:
        await notify_user(
            d["assigned_admin_id"], "loan",
            f"💼 <b>BAGI HASIL MASUK</b>\n\nBagi hasil {d.get('loan_number')} sebesar {rp(d.get('admin_profit'))} "
            "telah masuk dalam saldo payable Anda.",
            "ADMIN_PAYABLE_READY", d.get("loan_id"),
        )
    return await PS.serialize_distribution(await _get_distribution(dist_id))


class ReasonIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


@router.post("/profit-distributions/{dist_id}/settlement/reject")
async def reject_settlement(dist_id: str, payload: ReasonIn, request: Request, user: dict = Depends(require_superadmin)):
    d = await _get_distribution(dist_id)
    now = iso(now_utc())
    res = await db.profit_distributions.update_one(
        {"_id": dist_id, "lender_settlement_status": PS.SET_WAITING},
        {
            "$set": {
                "lender_settlement_status": PS.SET_PENDING,
                "settlement_rejected_at": now,
                "settlement_rejected_by": str(user["_id"]),
                "settlement_rejection_reason": payload.reason,
                "updated_at": now,
            }
        },
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Setoran ini tidak sedang menunggu verifikasi")
    await audit(
        request, user, "LENDER_SETTLEMENT_REJECTED", "profit_distribution", dist_id,
        f"Setoran bagi hasil {d.get('loan_number')} ditolak: {payload.reason}",
        {"lender_settlement_status": PS.SET_WAITING, "proof_file_id": d.get("settlement_proof_file_id")},
        {"lender_settlement_status": PS.SET_PENDING, "reason": payload.reason},
    )
    if d.get("lender_id"):
        await notify_user(
            d["lender_id"], "loan",
            f"⚠️ <b>SETORAN DITOLAK</b>\n\nSetoran bagi hasil {d.get('loan_number')} ditolak.\n"
            f"Alasan: {payload.reason}\n\nSilakan unggah ulang bukti setoran.",
            "LENDER_SETTLEMENT_REJECTED", d.get("loan_id"),
        )
    return await PS.serialize_distribution(await _get_distribution(dist_id))


# ---------------- admin payout ----------------
@router.post("/profit-distributions/{dist_id}/admin-payout/mark-paid")
async def mark_admin_payout_paid(
    dist_id: str,
    request: Request,
    proof: UploadFile = File(...),
    user: dict = Depends(require_superadmin),
):
    d = await _get_distribution(dist_id)
    if d.get("is_reversed"):
        raise HTTPException(status_code=409, detail="Pembagian hasil ini telah dibatalkan")
    if d.get("lender_settlement_status") != PS.SET_SETTLED:
        raise HTTPException(status_code=409, detail="Setoran Pendana belum diterima, payout Admin belum dapat dibayarkan")
    if d.get("admin_payout_status") == PS.PAYOUT_PAID:
        raise HTTPException(status_code=409, detail="Payout Admin sudah ditandai dibayar")
    up = await save_upload(db, proof, str(user["_id"]), "admin_payout")
    await db.files.update_one(
        {"_id": up["file_id"]},
        {"$set": {"loan_id": d.get("loan_id"), "profit_distribution_id": dist_id}},
    )
    now = iso(now_utc())
    res = await db.profit_distributions.update_one(
        {"_id": dist_id, "admin_payout_status": PS.PAYOUT_PENDING, "lender_settlement_status": PS.SET_SETTLED},
        {
            "$set": {
                "admin_payout_status": PS.PAYOUT_PAID,
                "admin_payout_amount": LS.money(d.get("admin_profit")),
                "admin_payout_proof_file_id": up["file_id"],
                "admin_payout_paid_at": now,
                "admin_payout_paid_by": str(user["_id"]),
                "updated_at": now,
            }
        },
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Payout Admin sudah diproses sebelumnya")
    await audit(
        request, user, "ADMIN_PAYOUT_MARKED_PAID", "profit_distribution", dist_id,
        f"Payout Admin {d.get('loan_number')} sebesar {rp(d.get('admin_profit'))} ditandai dibayar oleh Superadmin",
        {"admin_payout_status": PS.PAYOUT_PENDING},
        {"admin_payout_status": PS.PAYOUT_PAID, "amount": LS.money(d.get("admin_profit"))},
    )
    if d.get("assigned_admin_id"):
        await notify_user(
            d["assigned_admin_id"], "loan",
            f"💸 <b>PAYOUT DIBAYARKAN</b>\n\nBagi hasil {d.get('loan_number')} sebesar {rp(d.get('admin_profit'))} "
            "telah ditransfer ke rekening Anda.",
            "ADMIN_PAYOUT_MARKED_PAID", d.get("loan_id"),
        )
    return await PS.serialize_distribution(await _get_distribution(dist_id))


# ---------------- reversal ----------------
@router.post("/profit-distributions/{dist_id}/reverse")
async def reverse_distribution(dist_id: str, payload: ReasonIn, request: Request, user: dict = Depends(require_superadmin)):
    d = await _get_distribution(dist_id)
    if d.get("is_reversed"):
        raise HTTPException(status_code=409, detail="Pembagian hasil ini sudah dibatalkan sebelumnya")
    if d.get("admin_payout_status") == PS.PAYOUT_PAID:
        raise HTTPException(
            status_code=409,
            detail="Payout Admin sudah dibayarkan. Koreksi harus diselesaikan secara manual di luar aplikasi terlebih dahulu.",
        )
    now = iso(now_utc())
    res = await db.profit_distributions.update_one(
        {"_id": dist_id, "is_reversed": {"$ne": True}},
        {
            "$set": {
                "is_reversed": True,
                "reversed_at": now,
                "reversed_by": str(user["_id"]),
                "reversal_reason": payload.reason,
                "updated_at": now,
            }
        },
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Pembagian hasil ini sudah dibatalkan sebelumnya")
    await audit(
        request, user, "PROFIT_DISTRIBUTION_REVERSED", "profit_distribution", dist_id,
        f"Pembagian hasil {d.get('loan_number')} dibatalkan (reversal): {payload.reason}",
        {"is_reversed": False, "lender_settlement_status": d.get("lender_settlement_status")},
        {"is_reversed": True, "reason": payload.reason},
    )
    return await PS.serialize_distribution(await _get_distribution(dist_id))
