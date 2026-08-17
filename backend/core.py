import os
import jwt
import bcrypt
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from fastapi import HTTPException, Request, Depends
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

logger = logging.getLogger("app")

ROOT_DIR = Path(__file__).parent

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]

JWT_ALGORITHM = "HS256"
ACCESS_TTL_MINUTES = 60 * 12

ROLE_SUPERADMIN = "superadmin"
ROLE_ADMIN = "admin"
ROLE_LENDER = "lender"
ROLE_BORROWER = "borrower"

DEFAULT_SETTINGS = {
    "_id": "app",
    "app_name": "PinjamKu",
    "app_description": "Sistem Manajemen Pinjaman",
    "logo_url": None,
    "favicon_url": None,
    "interest_rate": 10.0,
    "late_fee_rate_per_day": 1.0,
    "telegram_reg_enabled": False,
    "telegram_reg_token": None,
    "telegram_loan_enabled": False,
    "telegram_loan_token": None,
    "profit_share_lender_pct": 60.0,
    "profit_share_admin_pct": 25.0,
    "profit_share_platform_pct": 15.0,
    "settlement_account_type": None,
    "settlement_account_number": None,
    "settlement_account_holder": None,
    "settlement_account_bank_name": None,
    "settlement_instructions": None,
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def create_access_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "exp": now_utc() + timedelta(minutes=ACCESS_TTL_MINUTES),
    }
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def normalize_phone(phone: str) -> str:
    """Canonical Indonesian format: 08xxxxxxxxxx. Accepts 08.., 628.., +628.., 00628.., 8.."""
    p = "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "+")
    p = p.lstrip("+")
    if p.startswith("0062"):
        p = p[4:]
    elif p.startswith("62"):
        p = p[2:]
    elif p.startswith("0"):
        p = p[1:]
    return ("0" + p.lstrip("0")) if p else ""


async def get_settings() -> dict:
    """Race-safe: atomic upsert, aman bila beberapa proses start bersamaan."""
    defaults = {k: v for k, v in DEFAULT_SETTINGS.items() if k != "_id"}
    doc = await db.settings.find_one_and_update(
        {"_id": "app"},
        {"$setOnInsert": defaults},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    merged = dict(DEFAULT_SETTINGS)
    merged.update(doc)
    return merged


def public_settings(s: dict) -> dict:
    return {
        "app_name": s.get("app_name"),
        "app_description": s.get("app_description"),
        "logo_url": s.get("logo_url"),
        "favicon_url": s.get("favicon_url"),
        "interest_rate": s.get("interest_rate"),
        "late_fee_rate_per_day": s.get("late_fee_rate_per_day"),
    }


def sanitize_user(u: dict) -> dict:
    out = {k: v for k, v in (u or {}).items() if k not in ("password_hash", "_id")}
    out["id"] = str(u.get("_id") or u.get("id"))
    return out


async def _token_user(token: str) -> dict:
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sesi telah berakhir, silakan login kembali")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token tidak valid")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Token tidak valid")
    user = await db.users.find_one({"_id": payload["sub"]})
    if not user:
        raise HTTPException(status_code=401, detail="User tidak ditemukan")
    if user.get("is_active") is False:
        raise HTTPException(status_code=403, detail="Akun Anda dinonaktifkan")
    return user


PASSWORD_CHANGE_ALLOWED_PATHS = (
    "/api/auth/me",
    "/api/auth/password",
    "/api/auth/logout",
    "/api/public/settings",
)


async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.query_params.get("auth")
    if not token:
        raise HTTPException(status_code=401, detail="Belum terautentikasi")
    user = await _token_user(token)
    if user.get("must_change_password") and request.url.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
        raise HTTPException(status_code=403, detail="Anda wajib membuat password baru sebelum melanjutkan")
    return user


def generate_temp_password() -> str:
    import secrets
    import string

    alphabet = string.ascii_uppercase + string.digits
    return "Pk" + "".join(secrets.choice(alphabet) for _ in range(8)) + "!"


def require_roles(*roles):
    async def dep(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Anda tidak memiliki akses untuk aksi ini")
        return user

    return dep


require_staff = require_roles(ROLE_SUPERADMIN, ROLE_ADMIN)
require_superadmin = require_roles(ROLE_SUPERADMIN)
require_lender = require_roles(ROLE_LENDER)
require_borrower = require_roles(ROLE_BORROWER)


async def audit(
    request: Optional[Request],
    user: Optional[dict],
    action: str,
    entity_type: str,
    entity_id: Optional[str],
    description: str = "",
    old_value=None,
    new_value=None,
):
    import uuid

    doc = {
        "_id": str(uuid.uuid4()),
        "user_id": str(user.get("_id")) if user else None,
        "user_name": (user or {}).get("full_name"),
        "role": (user or {}).get("role"),
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "old_value": old_value,
        "new_value": new_value,
        "description": description,
        "ip_address": (request.client.host if request and request.client else None),
        "user_agent": (request.headers.get("user-agent") if request else None),
        "created_at": iso(now_utc()),
    }
    await db.audit_logs.insert_one(doc)


async def ensure_indexes():
    await db.users.create_index("phone", unique=True)
    await db.users.create_index("email", unique=True, sparse=True)
    await db.users.create_index("nik", unique=True, sparse=True)
    await db.users.create_index("role")
    await db.loans.create_index("loan_number", unique=True)
    await db.loans.create_index("borrower_id")
    await db.loans.create_index("funded_by")
    await db.loans.create_index("status")
    await db.payments.create_index("loan_id")
    await db.audit_logs.create_index("created_at")
    await db.login_attempts.create_index("identifier")
    await db.notifications.create_index("created_at")
    await db.profit_distributions.create_index("loan_id", unique=True)
    await db.profit_distributions.create_index("lender_id")
    await db.profit_distributions.create_index("assigned_admin_id")
    await db.profit_distributions.create_index("created_at")
    await db.profit_distributions.create_index("lender_settlement_status")
    await db.profit_distributions.create_index("admin_payout_status")
