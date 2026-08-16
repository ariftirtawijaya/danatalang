import uuid
import re
from datetime import timedelta
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, EmailStr, field_validator
from core import (
    db, now_utc, iso, hash_password, verify_password, create_access_token, normalize_phone,
    sanitize_user, get_current_user, audit, get_settings, ROLE_BORROWER, ROLE_SUPERADMIN,
)
from notif import notify_admins, id_datetime
from loan_service import borrower_credit

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_ATTEMPTS = 5
LOCK_MINUTES = 15
BANK_TYPES = ["BCA", "GoPay", "DANA"]


class RegisterIn(BaseModel):
    nik: str
    full_name: str = Field(min_length=3, max_length=100)
    birth_date: str
    phone: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    confirm_password: str
    bank_name: str
    account_number: str
    account_holder: str = Field(min_length=2, max_length=100)

    @field_validator("nik")
    @classmethod
    def check_nik(cls, v):
        v = v.strip()
        if not re.fullmatch(r"\d{16}", v):
            raise ValueError("NIK harus 16 digit angka")
        return v

    @field_validator("bank_name")
    @classmethod
    def check_bank(cls, v):
        if v not in BANK_TYPES:
            raise ValueError("Jenis rekening tidak valid")
        return v

    @field_validator("account_number")
    @classmethod
    def check_acc(cls, v):
        v = v.strip()
        if not re.fullmatch(r"\d{8,20}", v):
            raise ValueError("Nomor rekening/e-wallet harus 8-20 digit angka")
        return v


class LoginIn(BaseModel):
    phone: str
    password: str


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def lock_key(phone: str) -> str:
    """Bucket brute-force attempts per account. Keyed by phone (not IP) because behind the
    ingress the socket peer is an internal proxy pod, which would split the counter."""
    return f"phone:{phone}"


async def _check_lock(identifier: str):
    rec = await db.login_attempts.find_one({"_id": identifier})
    if not rec:
        return
    if rec.get("count", 0) >= MAX_ATTEMPTS:
        from core import parse_dt

        last = parse_dt(rec.get("last_at"))
        if last and now_utc() - last < timedelta(minutes=LOCK_MINUTES):
            raise HTTPException(
                status_code=429,
                detail=f"Terlalu banyak percobaan login. Coba lagi dalam {LOCK_MINUTES} menit.",
            )
        await db.login_attempts.delete_one({"_id": identifier})


@router.post("/register")
async def register(payload: RegisterIn, request: Request):
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Konfirmasi password tidak sama")
    phone = normalize_phone(payload.phone)
    if not re.fullmatch(r"0\d{8,14}", phone):
        raise HTTPException(status_code=400, detail="Nomor HP tidak valid")
    email = payload.email.lower().strip()
    if await db.users.find_one({"nik": payload.nik}):
        raise HTTPException(status_code=400, detail="NIK sudah terdaftar")
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")
    if await db.users.find_one({"phone": phone}):
        raise HTTPException(status_code=400, detail="Nomor HP sudah terdaftar")

    user_id = str(uuid.uuid4())
    doc = {
        "_id": user_id,
        "role": ROLE_BORROWER,
        "full_name": payload.full_name.strip(),
        "nik": payload.nik,
        "birth_date": payload.birth_date,
        "phone": phone,
        "email": email,
        "password_hash": hash_password(payload.password),
        "bank_name": payload.bank_name,
        "account_number": payload.account_number,
        "account_holder": payload.account_holder.strip().upper(),
        "account_status": "WAITING_VERIFICATION",
        "is_active": True,
        "borrower_limit": 0,
        "max_duration_days": 0,
        "max_active_loans": 0,
        "created_at": iso(now_utc()),
        "last_login_at": None,
    }
    await db.users.insert_one(doc)
    await audit(request, doc, "BORROWER_REGISTERED", "user", user_id, f"Peminjam {doc['full_name']} melakukan registrasi")

    text = (
        "👤 <b>PEMINJAM BARU</b>\n\n"
        f"Nama: {doc['full_name']}\n"
        f"NIK: {doc['nik'][:4]}********{doc['nik'][-4:]}\n"
        f"No HP: {doc['phone']}\n"
        f"Email: {doc['email']}\n\n"
        "Status:\nMenunggu Verifikasi\n\n"
        f"Waktu:\n{id_datetime(now_utc())}"
    )
    await notify_admins("reg", text, "BORROWER_REGISTERED")

    token = create_access_token(user_id, ROLE_BORROWER)
    return {"token": token, "user": sanitize_user(doc)}


@router.post("/login")
async def login(payload: LoginIn, request: Request):
    phone = normalize_phone(payload.phone)
    ip = client_ip(request)
    identifier = lock_key(phone)
    await _check_lock(identifier)
    user = await db.users.find_one({"phone": phone})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        rec = await db.login_attempts.find_one_and_update(
            {"_id": identifier},
            {"$inc": {"count": 1}, "$set": {"last_at": iso(now_utc()), "ip": ip}},
            upsert=True,
            return_document=True,
        )
        count = (rec or {}).get("count", 1)
        if count >= MAX_ATTEMPTS:
            raise HTTPException(
                status_code=429,
                detail=f"Terlalu banyak percobaan login. Akun terkunci sementara, coba lagi dalam {LOCK_MINUTES} menit.",
            )
        left = MAX_ATTEMPTS - count
        raise HTTPException(
            status_code=401,
            detail=f"Nomor HP atau password salah. Sisa {left} percobaan sebelum akun terkunci {LOCK_MINUTES} menit.",
        )
    if user.get("is_active") is False:
        raise HTTPException(status_code=403, detail="Akun Anda dinonaktifkan. Hubungi Admin.")
    await db.login_attempts.delete_one({"_id": identifier})
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": iso(now_utc())}})
    await audit(request, user, "LOGIN", "user", str(user["_id"]), f"{user.get('full_name')} login")
    return {"token": create_access_token(str(user["_id"]), user["role"]), "user": sanitize_user(user)}


@router.post("/logout")
async def logout(request: Request, user: dict = Depends(get_current_user)):
    await audit(request, user, "LOGOUT", "user", str(user["_id"]), f"{user.get('full_name')} logout")
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    out = sanitize_user(user)
    out["must_change_password"] = bool(user.get("must_change_password"))
    if user["role"] == ROLE_BORROWER:
        out["credit"] = await borrower_credit(user)
    return out


class ProfileIn(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    bank_name: str | None = None
    account_number: str | None = None
    account_holder: str | None = None
    telegram_chat_id: str | None = None
    phone: str | None = None
    current_password: str | None = None


@router.put("/profile")
async def update_profile(payload: ProfileIn, request: Request, user: dict = Depends(get_current_user)):
    updates = {}
    if payload.full_name:
        updates["full_name"] = payload.full_name.strip()
    if payload.email:
        email = payload.email.lower().strip()
        existing = await db.users.find_one({"email": email, "_id": {"$ne": user["_id"]}})
        if existing:
            raise HTTPException(status_code=400, detail="Email sudah digunakan")
        updates["email"] = email
    for f in ("bank_name", "account_number", "account_holder", "telegram_chat_id"):
        v = getattr(payload, f)
        if v is not None:
            updates[f] = v.strip()
    if payload.phone is not None:
        new_phone = normalize_phone(payload.phone)
        if new_phone != user.get("phone"):
            if user["role"] != ROLE_SUPERADMIN:
                raise HTTPException(status_code=403, detail="Nomor HP hanya dapat diubah oleh Superadmin atau melalui Admin")
            if not re.fullmatch(r"0\d{8,14}", new_phone):
                raise HTTPException(status_code=400, detail="Nomor HP tidak valid")
            if not payload.current_password or not verify_password(payload.current_password, user.get("password_hash", "")):
                raise HTTPException(status_code=400, detail="Password Anda saat ini salah. Masukkan password yang benar untuk mengubah Nomor HP.")
            if await db.users.find_one({"phone": new_phone, "_id": {"$ne": user["_id"]}}):
                raise HTTPException(status_code=400, detail="Nomor HP sudah digunakan akun lain")
            updates["phone"] = new_phone
    if payload.bank_name and user["role"] == ROLE_BORROWER and payload.bank_name not in BANK_TYPES:
        raise HTTPException(status_code=400, detail="Jenis rekening tidak valid")
    if not updates:
        return sanitize_user(user)
    await db.users.update_one({"_id": user["_id"]}, {"$set": updates})
    if "phone" in updates:
        await audit(
            request, user, "LOGIN_PHONE_CHANGED", "user", str(user["_id"]),
            f"Nomor HP login diubah dari {user.get('phone')} menjadi {updates['phone']}",
            {"phone": user.get("phone")}, {"phone": updates["phone"]},
        )
    await audit(request, user, "PROFILE_UPDATED", "user", str(user["_id"]), "Profil diperbarui", None, updates)
    fresh = await db.users.find_one({"_id": user["_id"]})
    return sanitize_user(fresh)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)


@router.put("/password")
async def change_password(payload: PasswordIn, request: Request, user: dict = Depends(get_current_user)):
    if not verify_password(payload.current_password, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Password saat ini salah")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="Password baru harus berbeda dari password saat ini")
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"password_hash": hash_password(payload.new_password), "must_change_password": False}},
    )
    if user.get("phone"):
        await db.login_attempts.delete_many({"_id": lock_key(user["phone"])})
    await audit(request, user, "PASSWORD_CHANGED", "user", str(user["_id"]), "Password diubah")
    return {"ok": True, "relogin_required": True}
