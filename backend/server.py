import os
import logging
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import asyncio
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from core import db, client, ensure_indexes, hash_password, now_utc, iso, get_settings, ROLE_SUPERADMIN
import loan_service as LS
import auth_routes
import loan_routes
import admin_routes
import profit_routes
import collection_routes
from storage import init_storage, s3_required
from pymongo.errors import DuplicateKeyError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("app")

app = FastAPI(title="Loan Management API")

app.include_router(auth_routes.router)
app.include_router(loan_routes.router)
app.include_router(admin_routes.router)
app.include_router(profit_routes.router)
app.include_router(collection_routes.router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logger.exception("unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Terjadi kesalahan pada server"})


async def seed_superadmin():
    phone = os.environ.get("SUPERADMIN_PHONE")
    password = os.environ.get("SUPERADMIN_PASSWORD")
    if not phone or not password:
        logger.warning("SUPERADMIN_PHONE/PASSWORD not configured; skipping superadmin seed")
        return
    from core import normalize_phone

    phone = normalize_phone(phone)
    any_superadmin = await db.users.find_one({"role": ROLE_SUPERADMIN})
    if any_superadmin:
        # Superadmin may have changed its own login phone; never re-seed or overwrite it.
        return
    if await db.users.find_one({"phone": phone}):
        logger.warning("phone %s already used by a non-superadmin account; skipping seed", phone)
        return
    try:
        await db.users.insert_one(
            {
                "_id": str(uuid.uuid4()),
                "role": ROLE_SUPERADMIN,
                "full_name": os.environ.get("SUPERADMIN_NAME", "Super Admin"),
                "phone": phone,
                "email": os.environ.get("SUPERADMIN_EMAIL", "superadmin@local.app").lower(),
                "password_hash": hash_password(password),
                "is_active": True,
                "notify_telegram": True,
                "telegram_chat_id": None,
                "created_at": iso(now_utc()),
                "last_login_at": None,
            }
        )
    except DuplicateKeyError:
        # Proses lain sudah melakukan seed lebih dulu (startup bersamaan) — aman diabaikan.
        logger.info("superadmin already seeded by another process")
        return
    logger.info("superadmin seeded")


async def superadmin_recovery():
    """Break-glass: set SUPERADMIN_RECOVERY=true in backend/.env to force the primary
    Superadmin password back to SUPERADMIN_PASSWORD on the next backend start."""
    if (os.environ.get("SUPERADMIN_RECOVERY") or "").strip().lower() not in ("1", "true", "yes"):
        return
    password = os.environ.get("SUPERADMIN_PASSWORD")
    if not password:
        logger.warning("SUPERADMIN_RECOVERY set but SUPERADMIN_PASSWORD is empty")
        return
    from core import audit

    keeper = await db.users.find_one({"role": ROLE_SUPERADMIN}, sort=[("created_at", 1)])
    if not keeper:
        return
    await db.users.update_one(
        {"_id": keeper["_id"]},
        {"$set": {"password_hash": hash_password(password), "is_active": True, "must_change_password": False}},
    )
    await db.login_attempts.delete_many({})
    await audit(
        None, keeper, "SUPERADMIN_PASSWORD_RECOVERED", "user", str(keeper["_id"]),
        "Password Superadmin dipulihkan dari environment variable (SUPERADMIN_RECOVERY).",
    )
    logger.warning("superadmin password recovered from env; remove SUPERADMIN_RECOVERY from .env")


async def normalize_existing_phones():
    """Ensure every stored phone uses the single canonical format (0xxxxxxxxxx)."""
    from core import normalize_phone

    async for u in db.users.find({}, {"phone": 1}):
        raw = u.get("phone")
        canonical = normalize_phone(raw or "")
        if canonical and canonical != raw:
            clash = await db.users.find_one({"phone": canonical, "_id": {"$ne": u["_id"]}})
            if clash:
                logger.warning("phone normalization skipped for %s: %s already exists", u["_id"], canonical)
                continue
            await db.users.update_one({"_id": u["_id"]}, {"$set": {"phone": canonical}})
            logger.info("normalized phone %s -> %s", raw, canonical)


async def overdue_worker():
    while True:
        try:
            await LS.refresh_overdue_statuses()
        except Exception as e:
            logger.warning("overdue worker error: %s", e)
        await asyncio.sleep(300)


@app.on_event("startup")
async def startup():
    await ensure_indexes()
    await get_settings()
    await normalize_existing_phones()
    await seed_superadmin()
    await superadmin_recovery()
    try:
        await asyncio.to_thread(init_storage)
    except Exception as e:
        if s3_required():
            logger.error("storage init failed (REQUIRE_S3=true): %s", e)
            raise
        logger.warning("storage init failed: %s", e)
    asyncio.create_task(overdue_worker())


@app.on_event("shutdown")
async def shutdown():
    client.close()
