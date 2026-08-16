import io
import os
import csv
import uuid
import asyncio
import re
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, UploadFile, File, Response
from pydantic import BaseModel, Field, EmailStr
from core import (
    db, now_utc, iso, parse_dt, audit, get_settings, public_settings, get_current_user, require_staff,
    require_superadmin, sanitize_user, hash_password, verify_password, normalize_phone,
    generate_temp_password, DEFAULT_SETTINGS, ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_LENDER, ROLE_BORROWER,
)
from notif import _send_sync, rp
from storage import save_upload, list_objects, purge_prefix
import loan_service as LS

router = APIRouter(prefix="/api", tags=["management"])


def mask_nik(nik: Optional[str]) -> Optional[str]:
    if not nik or len(nik) < 8:
        return nik
    return nik[:4] + "*" * 8 + nik[-4:]


def mask_account(acc: Optional[str]) -> Optional[str]:
    if not acc or len(acc) < 6:
        return acc
    return acc[:3] + "*" * (len(acc) - 6) + acc[-3:]


# ---------------- public settings ----------------
@router.get("/public/settings")
async def get_public_settings():
    return public_settings(await get_settings())


# ---------------- dashboards ----------------
async def _count(query):
    return await db.loans.count_documents(query)


async def _sum_principal(query) -> int:
    total = 0
    async for l in db.loans.find(query, {"principal_amount": 1}):
        total += LS.money(l["principal_amount"])
    return total


@router.get("/dashboard")
async def dashboard(user: dict = Depends(get_current_user)):
    role = user["role"]
    await LS.refresh_overdue_statuses()
    if role in (ROLE_SUPERADMIN, ROLE_ADMIN):
        out = {
            "total_borrowers": await db.users.count_documents({"role": ROLE_BORROWER}),
            "active_borrowers": await db.users.count_documents({"role": ROLE_BORROWER, "account_status": "ACTIVE"}),
            "waiting_verification": await db.users.count_documents(
                {"role": ROLE_BORROWER, "account_status": "WAITING_VERIFICATION"}
            ),
            "total_admins": await db.users.count_documents({"role": ROLE_ADMIN}),
            "total_lenders": await db.users.count_documents({"role": ROLE_LENDER}),
            "total_loans": await _count({}),
            "waiting_approval": await _count({"status": LS.S_WAITING_ADMIN}),
            "waiting_funding": await _count({"status": LS.S_WAITING_FUNDING}),
            "funding_claimed": await _count({"status": LS.S_FUNDING_CLAIMED}),
            "waiting_disbursement": await _count({"status": LS.S_WAITING_DISB}),
            "active_loans": await _count({"status": LS.S_ACTIVE}),
            "overdue_loans": await _count({"status": LS.S_OVERDUE}),
            "waiting_payment_verification": await _count({"status": LS.S_WAITING_PAYMENT}),
            "paid_loans": await _count({"status": LS.S_PAID}),
            "rejected_loans": await _count({"status": LS.S_REJECTED}),
            "total_outstanding_principal": await _sum_principal(LS.OUTSTANDING_QUERY),
            "total_disbursed": await _sum_principal({"disbursed_at": {"$ne": None}}),
        }
        paid_total = 0
        interest_total = 0
        late_total = 0
        async for l in db.loans.find({"status": LS.S_PAID}):
            paid_total += LS.money(l["principal_amount"])
            interest_total += LS.money(l["interest_amount"])
            late_total += LS.money(l.get("late_fee_final"))
        out["total_principal_paid"] = paid_total
        out["total_interest_paid"] = interest_total
        out["total_late_fee_paid"] = late_total
        out["total_payments"] = paid_total + interest_total + late_total
        monthly = {}
        async for l in db.loans.find({}, {"submitted_at": 1, "principal_amount": 1, "disbursed_at": 1, "status": 1}):
            key = (l.get("submitted_at") or "")[:7]
            if not key:
                continue
            m = monthly.setdefault(key, {"month": key, "count": 0, "principal": 0, "disbursed": 0})
            m["count"] += 1
            m["principal"] += LS.money(l["principal_amount"])
            if l.get("disbursed_at"):
                m["disbursed"] += LS.money(l["principal_amount"])
        out["monthly"] = sorted(monthly.values(), key=lambda x: x["month"])[-6:]
        out["status_breakdown"] = [
            {"name": "Aktif", "value": out["active_loans"]},
            {"name": "Overdue", "value": out["overdue_loans"]},
            {"name": "Lunas", "value": out["paid_loans"]},
            {"name": "Menunggu", "value": out["waiting_approval"] + out["waiting_funding"]},
        ]
        return out
    if role == ROLE_LENDER:
        me = str(user["_id"])
        active_q = {"funded_by": me, "status": {"$in": [LS.S_ACTIVE, LS.S_OVERDUE, LS.S_WAITING_PAYMENT]}}
        paid = await db.loans.find({"funded_by": me, "status": LS.S_PAID}).to_list(1000)
        return {
            "available_loans": await _count({"status": LS.S_WAITING_FUNDING, "funded_by": None}),
            "claimed_not_disbursed": await _count({"funded_by": me, "status": LS.S_FUNDING_CLAIMED}),
            "waiting_disbursement_confirmation": await _count({"funded_by": me, "status": LS.S_WAITING_DISB}),
            "active_loans": await _count(active_q),
            "overdue_loans": await _count({"funded_by": me, "status": LS.S_OVERDUE}),
            "waiting_payment_verification": await db.payments.count_documents({"lender_id": me, "status": "PENDING"}),
            "total_active_principal": await _sum_principal(active_q),
            "total_disbursed": await _sum_principal({"funded_by": me, "disbursed_at": {"$ne": None}}),
            "total_principal_returned": sum(LS.money(l["principal_amount"]) for l in paid),
            "total_interest_earned": sum(LS.money(l["interest_amount"]) + LS.money(l.get("late_fee_final")) for l in paid),
            "paid_loans": len(paid),
        }
    credit = await LS.borrower_credit(user)
    credit["account_status"] = user.get("account_status")
    return credit


# ---------------- borrowers ----------------
@router.get("/borrowers")
async def list_borrowers(
    user: dict = Depends(require_staff),
    q: Optional[str] = None,
    account_status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    query: dict = {"role": ROLE_BORROWER}
    if account_status:
        query["account_status"] = {"$in": [s.strip() for s in account_status.split(",") if s.strip()]}
    if q:
        rx = re.escape(q)
        query["$or"] = [
            {"full_name": {"$regex": rx, "$options": "i"}},
            {"nik": {"$regex": rx}},
            {"phone": {"$regex": rx}},
            {"email": {"$regex": rx, "$options": "i"}},
        ]
    total = await db.users.count_documents(query)
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    docs = (
        await db.users.find(query).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    )
    items = []
    for d in docs:
        stats = await LS.borrower_credit(d)
        items.append(
            {
                "id": str(d["_id"]),
                "full_name": d.get("full_name"),
                "nik_masked": mask_nik(d.get("nik")),
                "phone": d.get("phone"),
                "email": d.get("email"),
                "account_status": d.get("account_status"),
                "borrower_limit": stats["borrower_limit"],
                "outstanding_principal": stats["outstanding_principal"],
                "available_limit": stats["available_limit"],
                "active_loans": stats["active_loans"],
                "max_active_loans": stats["max_active_loans"],
                "completed_loans": stats["completed_loans"],
                "paid_late": stats["paid_late"],
                "created_at": d.get("created_at"),
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/borrowers/{borrower_id}")
async def borrower_detail(borrower_id: str, user: dict = Depends(require_staff)):
    b = await db.users.find_one({"_id": borrower_id, "role": ROLE_BORROWER})
    if not b:
        raise HTTPException(status_code=404, detail="Peminjam tidak ditemukan")
    loans = await db.loans.find({"borrower_id": borrower_id}).sort("submitted_at", -1).to_list(500)
    notes = await db.admin_notes.find({"borrower_id": borrower_id}).sort("created_at", -1).to_list(200)
    logs = await db.audit_logs.find({"entity_id": borrower_id}).sort("created_at", -1).to_list(100)
    return {
        "profile": sanitize_user(b),
        "credit": await LS.borrower_credit(b),
        "loans": [await LS.serialize_loan(l) for l in loans],
        "notes": [
            {"id": str(n["_id"]), "note": n["note"], "author": n.get("author_name"), "created_at": n["created_at"]}
            for n in notes
        ],
        "audit": [
            {
                "action": a["action"],
                "description": a.get("description"),
                "user_name": a.get("user_name"),
                "created_at": a["created_at"],
            }
            for a in logs
        ],
    }


class VerifyIn(BaseModel):
    approve: bool
    borrower_limit: Optional[int] = None
    max_duration_days: Optional[int] = None
    max_active_loans: Optional[int] = None
    reason: Optional[str] = None


@router.post("/borrowers/{borrower_id}/verify")
async def verify_borrower(borrower_id: str, payload: VerifyIn, request: Request, user: dict = Depends(require_staff)):
    b = await db.users.find_one({"_id": borrower_id, "role": ROLE_BORROWER})
    if not b:
        raise HTTPException(status_code=404, detail="Peminjam tidak ditemukan")
    if b.get("account_status") != "WAITING_VERIFICATION":
        raise HTTPException(status_code=409, detail="Peminjam ini sudah diverifikasi sebelumnya")
    if payload.approve:
        if not payload.borrower_limit or payload.borrower_limit <= 0:
            raise HTTPException(status_code=400, detail="Limit pinjaman wajib diisi")
        if not payload.max_duration_days or payload.max_duration_days <= 0:
            raise HTTPException(status_code=400, detail="Durasi maksimal wajib diisi")
        if not payload.max_active_loans or payload.max_active_loans <= 0:
            raise HTTPException(status_code=400, detail="Maksimal pinjaman aktif wajib diisi")
        updates = {
            "account_status": "ACTIVE",
            "borrower_limit": LS.money(payload.borrower_limit),
            "max_duration_days": payload.max_duration_days,
            "max_active_loans": payload.max_active_loans,
            "verified_by": str(user["_id"]),
            "verified_by_name": user.get("full_name"),
            "verified_at": iso(now_utc()),
        }
        await db.users.update_one({"_id": borrower_id}, {"$set": updates})
        await audit(
            request, user, "BORROWER_VERIFIED", "user", borrower_id,
            f"Peminjam {b.get('full_name')} disetujui dengan limit {rp(payload.borrower_limit)}",
            {"account_status": "WAITING_VERIFICATION"}, updates,
        )
    else:
        if not payload.reason:
            raise HTTPException(status_code=400, detail="Alasan penolakan wajib diisi")
        updates = {
            "account_status": "REJECTED",
            "rejection_reason": payload.reason,
            "verified_by": str(user["_id"]),
            "verified_at": iso(now_utc()),
        }
        await db.users.update_one({"_id": borrower_id}, {"$set": updates})
        await audit(
            request, user, "BORROWER_REJECTED", "user", borrower_id,
            f"Peminjam {b.get('full_name')} ditolak: {payload.reason}", None, updates,
        )
    fresh = await db.users.find_one({"_id": borrower_id})
    return sanitize_user(fresh)


class LimitsIn(BaseModel):
    borrower_limit: int = Field(ge=0)
    max_duration_days: int = Field(ge=1)
    max_active_loans: int = Field(ge=1)


@router.put("/borrowers/{borrower_id}/limits")
async def update_limits(borrower_id: str, payload: LimitsIn, request: Request, user: dict = Depends(require_staff)):
    b = await db.users.find_one({"_id": borrower_id, "role": ROLE_BORROWER})
    if not b:
        raise HTTPException(status_code=404, detail="Peminjam tidak ditemukan")
    old = {
        "borrower_limit": b.get("borrower_limit"),
        "max_duration_days": b.get("max_duration_days"),
        "max_active_loans": b.get("max_active_loans"),
    }
    new = payload.model_dump()
    await db.users.update_one({"_id": borrower_id}, {"$set": new})
    await audit(request, user, "BORROWER_LIMITS_UPDATED", "user", borrower_id, f"Limit {b.get('full_name')} diperbarui", old, new)
    return sanitize_user(await db.users.find_one({"_id": borrower_id}))


class StatusIn(BaseModel):
    account_status: str
    reason: Optional[str] = None


@router.put("/borrowers/{borrower_id}/status")
async def update_borrower_status(borrower_id: str, payload: StatusIn, request: Request, user: dict = Depends(require_staff)):
    if payload.account_status not in ("ACTIVE", "SUSPENDED", "BLOCKED", "REJECTED", "WAITING_VERIFICATION"):
        raise HTTPException(status_code=400, detail="Status tidak valid")
    b = await db.users.find_one({"_id": borrower_id, "role": ROLE_BORROWER})
    if not b:
        raise HTTPException(status_code=404, detail="Peminjam tidak ditemukan")
    await db.users.update_one({"_id": borrower_id}, {"$set": {"account_status": payload.account_status}})
    await audit(
        request, user, "BORROWER_STATUS_CHANGED", "user", borrower_id,
        f"Status {b.get('full_name')} diubah menjadi {payload.account_status}. {payload.reason or ''}".strip(),
        {"account_status": b.get("account_status")}, {"account_status": payload.account_status},
    )
    return sanitize_user(await db.users.find_one({"_id": borrower_id}))


class NoteIn(BaseModel):
    note: str = Field(min_length=2, max_length=1000)


@router.post("/borrowers/{borrower_id}/notes")
async def add_note(borrower_id: str, payload: NoteIn, request: Request, user: dict = Depends(require_staff)):
    doc = {
        "_id": str(uuid.uuid4()),
        "borrower_id": borrower_id,
        "note": payload.note,
        "author_id": str(user["_id"]),
        "author_name": user.get("full_name"),
        "created_at": iso(now_utc()),
    }
    await db.admin_notes.insert_one(doc)
    await audit(request, user, "ADMIN_NOTE_ADDED", "user", borrower_id, "Catatan internal ditambahkan")
    return {"id": doc["_id"], "note": doc["note"], "author": doc["author_name"], "created_at": doc["created_at"]}


# ---------------- users (admin & lender management) ----------------
class UserIn(BaseModel):
    full_name: str = Field(min_length=3)
    phone: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: str
    telegram_chat_id: Optional[str] = None
    notify_telegram: bool = True
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    account_holder: Optional[str] = None


@router.get("/users")
async def list_users(
    user: dict = Depends(require_staff),
    role: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    query: dict = {}
    if role:
        query["role"] = {"$in": [r.strip() for r in role.split(",")]}
    else:
        query["role"] = {"$in": [ROLE_ADMIN, ROLE_LENDER, ROLE_SUPERADMIN, ROLE_BORROWER]}
    if user["role"] == ROLE_ADMIN:
        query["role"] = {"$in": [ROLE_LENDER, ROLE_BORROWER]}
    if q:
        rx = re.escape(q)
        query["$or"] = [
            {"full_name": {"$regex": rx, "$options": "i"}},
            {"email": {"$regex": rx, "$options": "i"}},
            {"phone": {"$regex": rx}},
        ]
    total = await db.users.count_documents(query)
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    docs = (
        await db.users.find(query).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    )
    items = []
    for d in docs:
        u = sanitize_user(d)
        u["nik"] = mask_nik(d.get("nik"))
        u["account_number"] = mask_account(d.get("account_number"))
        u["has_telegram"] = bool(d.get("telegram_chat_id"))
        items.append(u)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/users")
async def create_user(payload: UserIn, request: Request, user: dict = Depends(require_superadmin)):
    if payload.role not in (ROLE_ADMIN, ROLE_LENDER):
        raise HTTPException(status_code=400, detail="Role hanya boleh admin atau pendana")
    phone = normalize_phone(payload.phone)
    if await db.users.find_one({"phone": phone}):
        raise HTTPException(status_code=400, detail="Nomor HP sudah terdaftar")
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")
    if payload.role == ROLE_LENDER and not (payload.bank_name and payload.account_number and payload.account_holder):
        raise HTTPException(status_code=400, detail="Data rekening Pendana wajib diisi")
    uid = str(uuid.uuid4())
    doc = {
        "_id": uid,
        "role": payload.role,
        "full_name": payload.full_name.strip(),
        "phone": phone,
        "email": email,
        "password_hash": hash_password(payload.password),
        "telegram_chat_id": (payload.telegram_chat_id or "").strip() or None,
        "notify_telegram": payload.notify_telegram,
        "bank_name": payload.bank_name,
        "account_number": payload.account_number,
        "account_holder": (payload.account_holder or "").upper() or None,
        "is_active": True,
        "created_at": iso(now_utc()),
        "last_login_at": None,
    }
    await db.users.insert_one(doc)
    await audit(request, user, "USER_CREATED", "user", uid, f"{payload.role} baru dibuat: {doc['full_name']}")
    return sanitize_user(doc)


class UserUpdateIn(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    telegram_chat_id: Optional[str] = None
    notify_telegram: Optional[bool] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    account_holder: Optional[str] = None
    is_active: Optional[bool] = None
    new_password: Optional[str] = None


@router.put("/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdateIn, request: Request, user: dict = Depends(require_superadmin)):
    target = await db.users.find_one({"_id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    updates = {}
    for f in ("full_name", "telegram_chat_id", "bank_name", "account_number", "account_holder"):
        v = getattr(payload, f)
        if v is not None:
            updates[f] = v.strip() or None
    if payload.phone:
        phone = normalize_phone(payload.phone)
        if await db.users.find_one({"phone": phone, "_id": {"$ne": user_id}}):
            raise HTTPException(status_code=400, detail="Nomor HP sudah digunakan")
        updates["phone"] = phone
    if payload.email:
        email = payload.email.lower()
        if await db.users.find_one({"email": email, "_id": {"$ne": user_id}}):
            raise HTTPException(status_code=400, detail="Email sudah digunakan")
        updates["email"] = email
    if payload.notify_telegram is not None:
        updates["notify_telegram"] = payload.notify_telegram
    if payload.is_active is not None:
        if user_id == str(user["_id"]) and payload.is_active is False:
            raise HTTPException(status_code=400, detail="Tidak dapat menonaktifkan akun sendiri")
        updates["is_active"] = payload.is_active
    if payload.new_password:
        if len(payload.new_password) < 8:
            raise HTTPException(status_code=400, detail="Password minimal 8 karakter")
        updates["password_hash"] = hash_password(payload.new_password)
    if not updates:
        return sanitize_user(target)
    await db.users.update_one({"_id": user_id}, {"$set": updates})
    logged = {k: v for k, v in updates.items() if k != "password_hash"}
    if "password_hash" in updates:
        logged["password"] = "***reset***"
    await audit(request, user, "USER_UPDATED", "user", user_id, f"User {target.get('full_name')} diperbarui", None, logged)
    return sanitize_user(await db.users.find_one({"_id": user_id}))


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: str, request: Request, user: dict = Depends(require_staff)):
    """Generate a system temporary password. Resetter never learns the old password and the
    target user is forced to set a new one at next login."""
    target = await db.users.find_one({"_id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    if user["role"] == ROLE_ADMIN and target.get("role") != ROLE_BORROWER:
        raise HTTPException(status_code=403, detail="Admin hanya dapat mereset password Peminjam")
    if str(target["_id"]) == str(user["_id"]):
        raise HTTPException(status_code=400, detail="Gunakan menu Profil untuk mengubah password Anda sendiri")
    temp = generate_temp_password()
    await db.users.update_one(
        {"_id": user_id}, {"$set": {"password_hash": hash_password(temp), "must_change_password": True}}
    )
    await audit(
        request, user, "PASSWORD_RESET", "user", user_id,
        f"Password {target.get('full_name')} direset. Pengguna wajib membuat password baru saat login.",
        None, {"must_change_password": True},
    )
    return {"temporary_password": temp, "must_change_password": True, "full_name": target.get("full_name"), "phone": target.get("phone")}


@router.get("/lenders/{lender_id}")
async def lender_detail(lender_id: str, user: dict = Depends(require_staff)):
    l = await db.users.find_one({"_id": lender_id, "role": ROLE_LENDER})
    if not l:
        raise HTTPException(status_code=404, detail="Pendana tidak ditemukan")
    loans = await db.loans.find({"funded_by": lender_id}).sort("funded_at", -1).to_list(500)
    paid = [x for x in loans if x["status"] == LS.S_PAID]
    active = [x for x in loans if x["status"] in (LS.S_ACTIVE, LS.S_OVERDUE, LS.S_WAITING_PAYMENT)]
    profile = sanitize_user(l)
    return {
        "profile": profile,
        "stats": {
            "active_loans": len(active),
            "total_active_principal": sum(LS.money(x["principal_amount"]) for x in active),
            "total_disbursed": sum(LS.money(x["principal_amount"]) for x in loans if x.get("disbursed_at")),
            "total_principal_returned": sum(LS.money(x["principal_amount"]) for x in paid),
            "total_interest_earned": sum(LS.money(x["interest_amount"]) + LS.money(x.get("late_fee_final")) for x in paid),
            "overdue_loans": len([x for x in loans if x["status"] == LS.S_OVERDUE]),
            "paid_loans": len(paid),
        },
        "loans": [await LS.serialize_loan(x) for x in loans],
    }


# ---------------- settings ----------------
def _mask_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    return token[:6] + "••••••" + token[-4:] if len(token) > 12 else "••••••"


@router.get("/settings")
async def get_full_settings(user: dict = Depends(require_superadmin)):
    s = await get_settings()
    out = public_settings(s)
    out["telegram_reg_enabled"] = s.get("telegram_reg_enabled")
    out["telegram_loan_enabled"] = s.get("telegram_loan_enabled")
    out["telegram_reg_token_masked"] = _mask_token(s.get("telegram_reg_token"))
    out["telegram_loan_token_masked"] = _mask_token(s.get("telegram_loan_token"))
    return out


class GeneralIn(BaseModel):
    app_name: str = Field(min_length=2, max_length=60)
    app_description: Optional[str] = Field(default="", max_length=200)


@router.put("/settings/general")
async def update_general(payload: GeneralIn, request: Request, user: dict = Depends(require_superadmin)):
    s = await get_settings()
    new = {"app_name": payload.app_name.strip(), "app_description": (payload.app_description or "").strip()}
    await db.settings.update_one({"_id": "app"}, {"$set": new}, upsert=True)
    await audit(request, user, "SETTINGS_GENERAL_UPDATED", "settings", "app", "Pengaturan umum diperbarui",
                {"app_name": s.get("app_name")}, new)
    return public_settings(await get_settings())


@router.post("/settings/logo")
async def upload_logo(request: Request, kind: str = "logo", file: UploadFile = File(...), user: dict = Depends(require_superadmin)):
    if kind not in ("logo", "favicon"):
        raise HTTPException(status_code=400, detail="Jenis file tidak valid")
    up = await save_upload(db, file, str(user["_id"]), "branding")
    url = f"/api/branding/{up['file_id']}"
    field = "logo_url" if kind == "logo" else "favicon_url"
    await db.settings.update_one({"_id": "app"}, {"$set": {field: url}}, upsert=True)
    await audit(request, user, "SETTINGS_BRANDING_UPDATED", "settings", "app", f"{kind} aplikasi diperbarui", None, {field: url})
    return public_settings(await get_settings())


@router.get("/branding/{file_id}")
async def branding_file(file_id: str):
    from storage import get_object

    rec = await db.files.find_one({"_id": file_id, "is_deleted": False, "kind": "branding"})
    if not rec:
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    data, ct = get_object(rec["storage_path"])
    return Response(content=data, media_type=rec.get("content_type") or ct, headers={"Cache-Control": "public, max-age=3600"})


class LoanSettingsIn(BaseModel):
    interest_rate: float = Field(ge=0, le=100)
    late_fee_rate_per_day: float = Field(ge=0, le=100)


@router.put("/settings/loan")
async def update_loan_settings(payload: LoanSettingsIn, request: Request, user: dict = Depends(require_superadmin)):
    s = await get_settings()
    old = {"interest_rate": s.get("interest_rate"), "late_fee_rate_per_day": s.get("late_fee_rate_per_day")}
    new = payload.model_dump()
    await db.settings.update_one({"_id": "app"}, {"$set": new}, upsert=True)
    await audit(request, user, "SETTINGS_LOAN_UPDATED", "settings", "app",
                f"Bunga {new['interest_rate']}%, denda {new['late_fee_rate_per_day']}%/hari", old, new)
    return public_settings(await get_settings())


class TelegramIn(BaseModel):
    telegram_reg_enabled: bool
    telegram_loan_enabled: bool
    telegram_reg_token: Optional[str] = None
    telegram_loan_token: Optional[str] = None


@router.put("/settings/telegram")
async def update_telegram(payload: TelegramIn, request: Request, user: dict = Depends(require_superadmin)):
    new = {
        "telegram_reg_enabled": payload.telegram_reg_enabled,
        "telegram_loan_enabled": payload.telegram_loan_enabled,
    }
    if payload.telegram_reg_token:
        new["telegram_reg_token"] = payload.telegram_reg_token.strip()
    if payload.telegram_loan_token:
        new["telegram_loan_token"] = payload.telegram_loan_token.strip()
    await db.settings.update_one({"_id": "app"}, {"$set": new}, upsert=True)
    await audit(request, user, "SETTINGS_TELEGRAM_UPDATED", "settings", "app", "Pengaturan Telegram diperbarui", None,
                {k: ("***" if "token" in k else v) for k, v in new.items()})
    return await get_full_settings(user)


class TestTelegramIn(BaseModel):
    bot: str
    chat_id: Optional[str] = None


@router.post("/settings/telegram/test")
async def test_telegram(payload: TestTelegramIn, user: dict = Depends(require_superadmin)):
    s = await get_settings()
    token = s.get("telegram_reg_token") if payload.bot == "reg" else s.get("telegram_loan_token")
    if not token:
        raise HTTPException(status_code=400, detail="Bot token belum diatur")
    chat_id = (payload.chat_id or user.get("telegram_chat_id") or "").strip()
    if not chat_id:
        raise HTTPException(status_code=400, detail="Chat ID tujuan belum diatur pada profil Anda")
    label = "Registrasi" if payload.bot == "reg" else "Pinjaman"
    try:
        await asyncio.to_thread(_send_sync, token, chat_id, f"✅ Telegram Bot {label} berhasil terhubung.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal terhubung: {e}")
    return {"ok": True, "message": "✅ Telegram Bot berhasil terhubung."}


# ---------------- audit & notifications ----------------
WIPE_COLLECTIONS = [
    "loans", "loan_status_histories", "disbursements", "payments", "notifications",
    "admin_notes", "audit_logs", "files", "counters", "login_attempts",
]


async def _primary_superadmin() -> dict:
    phone = normalize_phone(os.environ.get("SUPERADMIN_PHONE", ""))
    keeper = await db.users.find_one({"phone": phone, "role": ROLE_SUPERADMIN}) if phone else None
    if not keeper:
        keeper = await db.users.find_one({"role": ROLE_SUPERADMIN}, sort=[("created_at", 1)])
    if not keeper:
        raise HTTPException(status_code=500, detail="Akun Superadmin utama tidak ditemukan")
    return keeper


@router.get("/settings/factory-reset/preview")
async def factory_reset_preview(user: dict = Depends(require_superadmin)):
    keeper = await _primary_superadmin()
    counts = {
        "admins": await db.users.count_documents({"role": ROLE_ADMIN}),
        "lenders": await db.users.count_documents({"role": ROLE_LENDER}),
        "borrowers": await db.users.count_documents({"role": ROLE_BORROWER}),
        "other_superadmins": await db.users.count_documents({"role": ROLE_SUPERADMIN, "_id": {"$ne": keeper["_id"]}}),
        "loans": await db.loans.count_documents({}),
        "disbursements": await db.disbursements.count_documents({}),
        "payments": await db.payments.count_documents({}),
        "loan_status_histories": await db.loan_status_histories.count_documents({}),
        "notifications": await db.notifications.count_documents({}),
        "admin_notes": await db.admin_notes.count_documents({}),
        "audit_logs": await db.audit_logs.count_documents({}),
        "files": await db.files.count_documents({}),
        "counters": await db.counters.count_documents({}),
    }
    try:
        objects = await asyncio.to_thread(list_objects, "pinjamku/")
        counts["storage_objects"] = len(objects)
        counts["storage_bytes"] = sum(o.get("size", 0) for o in objects)
    except Exception:
        counts["storage_objects"] = None
        counts["storage_bytes"] = None
    counts["total_records"] = sum(v for k, v in counts.items() if isinstance(v, int) and k != "storage_bytes")
    counts["keeper"] = {"full_name": keeper.get("full_name"), "phone": keeper.get("phone")}
    return counts


class FactoryResetIn(BaseModel):
    confirmation: str
    password: str


@router.post("/settings/factory-reset")
async def factory_reset(payload: FactoryResetIn, request: Request, user: dict = Depends(require_superadmin)):
    if payload.confirmation.strip() != "HAPUS SEMUA DATA":
        raise HTTPException(status_code=400, detail="Ketik persis: HAPUS SEMUA DATA")
    if not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Password Superadmin salah")

    from pymongo.errors import DuplicateKeyError
    try:
        lock = await db.system_locks.find_one_and_update(
            {"_id": "factory_reset", "running": {"$ne": True}},
            {"$set": {"running": True, "started_at": iso(now_utc()), "by": str(user["_id"])}},
            upsert=True,
            return_document=True,
        )
    except DuplicateKeyError:
        # Another concurrent request already acquired the lock.
        raise HTTPException(status_code=409, detail="Factory reset sedang berjalan")
    if not lock or lock.get("by") != str(user["_id"]):
        raise HTTPException(status_code=409, detail="Factory reset sedang berjalan")

    keeper = await _primary_superadmin()
    before = await factory_reset_preview(user)
    storage_result = {"purged": 0, "failed": 0, "remaining_bytes": 0}
    success = False
    try:
        try:
            storage_result = await asyncio.to_thread(purge_prefix, "pinjamku/")
        except Exception as e:
            storage_result = {"purged": 0, "failed": -1, "error": str(e)}
        for name in set(WIPE_COLLECTIONS):
            await db[name].delete_many({})
        await db.users.delete_many({"_id": {"$ne": keeper["_id"]}})
        await db.settings.delete_many({})
        await db.settings.insert_one(dict(DEFAULT_SETTINGS))
        await db.users.update_one({"_id": keeper["_id"]}, {"$unset": {"must_change_password": ""}})
        success = storage_result.get("failed", 0) <= 0 and (storage_result.get("remaining_bytes") or 0) == 0
        await audit(
            request, keeper, "SYSTEM_FACTORY_RESET", "system", "app",
            f"Factory reset dijalankan oleh {keeper.get('full_name')}. Status: {'BERHASIL' if success else 'SELESAI DENGAN PERINGATAN'}. "
            f"Objek storage dihapus: {storage_result.get('purged')}, gagal: {storage_result.get('failed')}.",
            {"deleted": {k: v for k, v in before.items() if isinstance(v, int)}},
            {"status": "SUCCESS" if success else "PARTIAL", "storage": storage_result, "kept_superadmin": keeper.get("phone")},
        )
    finally:
        await db.system_locks.update_one(
            {"_id": "factory_reset"}, {"$set": {"running": False, "finished_at": iso(now_utc())}}
        )

    return {
        "ok": True,
        "status": "SUCCESS" if success else "PARTIAL",
        "deleted": {k: v for k, v in before.items() if isinstance(v, int)},
        "storage": storage_result,
        "kept_superadmin": {"full_name": keeper.get("full_name"), "phone": keeper.get("phone")},
        "settings": public_settings(await get_settings()),
    }


@router.get("/audit-logs")
async def audit_logs(
    user: dict = Depends(require_superadmin),
    q: Optional[str] = None,
    action: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
):
    query: dict = {}
    if action:
        query["action"] = {"$in": [a.strip() for a in action.split(",")]}
    if q:
        rx = re.escape(q)
        query["$or"] = [
            {"description": {"$regex": rx, "$options": "i"}},
            {"user_name": {"$regex": rx, "$options": "i"}},
            {"action": {"$regex": rx, "$options": "i"}},
        ]
    total = await db.audit_logs.count_documents(query)
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    docs = (
        await db.audit_logs.find(query).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    )
    items = [{**{k: v for k, v in d.items() if k != "_id"}, "id": str(d["_id"])} for d in docs]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/notifications")
async def notifications(user: dict = Depends(require_staff), page: int = 1, page_size: int = 25):
    total = await db.notifications.count_documents({})
    docs = (
        await db.notifications.find({}).sort("sent_at", -1).skip((max(1, page) - 1) * page_size).limit(page_size).to_list(page_size)
    )
    return {
        "items": [{**{k: v for k, v in d.items() if k != "_id"}, "id": str(d["_id"])} for d in docs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------- reports ----------------
@router.get("/reports")
async def reports(user: dict = Depends(require_staff)):
    loans = await db.loans.find({}).to_list(5000)
    paid = [l for l in loans if l["status"] == LS.S_PAID]
    lenders = await db.users.find({"role": ROLE_LENDER}).to_list(200)
    per_lender = []
    for l in lenders:
        lid = str(l["_id"])
        mine = [x for x in loans if x.get("funded_by") == lid]
        mine_paid = [x for x in mine if x["status"] == LS.S_PAID]
        per_lender.append(
            {
                "id": lid,
                "name": l.get("full_name"),
                "loans_funded": len(mine),
                "total_disbursed": sum(LS.money(x["principal_amount"]) for x in mine if x.get("disbursed_at")),
                "principal_returned": sum(LS.money(x["principal_amount"]) for x in mine_paid),
                "interest_earned": sum(LS.money(x["interest_amount"]) + LS.money(x.get("late_fee_final")) for x in mine_paid),
                "active_loans": len([x for x in mine if x["status"] in (LS.S_ACTIVE, LS.S_OVERDUE, LS.S_WAITING_PAYMENT)]),
                "overdue_loans": len([x for x in mine if x["status"] == LS.S_OVERDUE]),
            }
        )
    return {
        "total_principal_disbursed": sum(LS.money(l["principal_amount"]) for l in loans if l.get("disbursed_at")),
        "total_outstanding_principal": sum(LS.money(l["principal_amount"]) for l in loans if l["status"] not in LS.CLOSED_STATUSES),
        "total_principal_paid": sum(LS.money(l["principal_amount"]) for l in paid),
        "total_interest_paid": sum(LS.money(l["interest_amount"]) for l in paid),
        "total_late_fee_paid": sum(LS.money(l.get("late_fee_final")) for l in paid),
        "active_loans": len([l for l in loans if l["status"] == LS.S_ACTIVE]),
        "overdue_loans": len([l for l in loans if l["status"] == LS.S_OVERDUE]),
        "paid_loans": len(paid),
        "lender_performance": per_lender,
        "borrower_count": await db.users.count_documents({"role": ROLE_BORROWER}),
        "active_borrower_count": await db.users.count_documents({"role": ROLE_BORROWER, "account_status": "ACTIVE"}),
    }


@router.get("/export/{entity}")
async def export_csv(entity: str, user: dict = Depends(require_staff)):
    buf = io.StringIO()
    writer = csv.writer(buf)
    if entity == "borrowers":
        writer.writerow(["Nama", "NIK", "No HP", "Email", "Status", "Limit", "Outstanding", "Tersedia", "Registrasi"])
        async for b in db.users.find({"role": ROLE_BORROWER}):
            c = await LS.borrower_credit(b)
            writer.writerow([b.get("full_name"), b.get("nik"), b.get("phone"), b.get("email"),
                             b.get("account_status"), c["borrower_limit"], c["outstanding_principal"],
                             c["available_limit"], b.get("created_at")])
    elif entity == "loans":
        writer.writerow(["Nomor", "Peminjam", "Pendana", "Pokok", "Bunga%", "Bunga", "Total", "Durasi", "Status", "Diajukan", "Cair", "Jatuh Tempo", "Lunas"])
        async for l in db.loans.find({}):
            b = await db.users.find_one({"_id": l["borrower_id"]})
            le = await db.users.find_one({"_id": l["funded_by"]}) if l.get("funded_by") else None
            writer.writerow([l["loan_number"], (b or {}).get("full_name"), (le or {}).get("full_name"),
                             LS.money(l["principal_amount"]), l["interest_rate"], LS.money(l["interest_amount"]),
                             LS.money(l["base_repayment_amount"]), l["duration_days"], l["status"],
                             l.get("submitted_at"), l.get("disbursed_at"), l.get("due_date"), l.get("paid_at")])
    elif entity == "payments":
        writer.writerow(["Loan", "Peminjam", "Pendana", "Attempt", "Dibayar", "Tagihan", "Denda", "Status", "Dilaporkan", "Diverifikasi"])
        async for p in db.payments.find({}):
            l = await db.loans.find_one({"_id": p["loan_id"]})
            b = await db.users.find_one({"_id": p["borrower_id"]})
            le = await db.users.find_one({"_id": p["lender_id"]}) if p.get("lender_id") else None
            writer.writerow([(l or {}).get("loan_number"), (b or {}).get("full_name"), (le or {}).get("full_name"),
                             p.get("attempt_no"), LS.money(p["amount_paid"]), LS.money(p["amount_due_at_submission"]),
                             LS.money(p.get("late_fee_at_submission")), p["status"], p.get("payment_submitted_at"), p.get("verified_at")])
    elif entity == "fundings":
        writer.writerow(["Loan", "Pendana", "Nominal", "Transfer", "Dikonfirmasi"])
        async for d in db.disbursements.find({}):
            l = await db.loans.find_one({"_id": d["loan_id"]})
            le = await db.users.find_one({"_id": d["lender_id"]})
            writer.writerow([(l or {}).get("loan_number"), (le or {}).get("full_name"), LS.money(d["amount"]),
                             d.get("transfer_at"), d.get("confirmed_at")])
    else:
        raise HTTPException(status_code=404, detail="Entitas export tidak dikenal")
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={entity}.csv"},
    )
