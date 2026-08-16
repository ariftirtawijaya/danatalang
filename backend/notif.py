import uuid
import asyncio
import logging
import requests
from core import db, get_settings, now_utc, iso

logger = logging.getLogger("app")


def rp(amount) -> str:
    try:
        n = int(round(float(amount or 0)))
    except Exception:
        n = 0
    return "Rp" + f"{n:,}".replace(",", ".")


def id_datetime(dt) -> str:
    months = [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember",
    ]
    from datetime import timedelta

    local = dt + timedelta(hours=7)
    return f"{local.day} {months[local.month - 1]} {local.year} {local.hour:02d}:{local.minute:02d}"


def _send_sync(token: str, chat_id: str, text: str):
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    data = {}
    try:
        data = resp.json()
    except Exception:
        pass
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or f"HTTP {resp.status_code}")
    return data


async def _log_notification(ntype: str, recipient: str, loan_id, status: str, error=None):
    await db.notifications.insert_one(
        {
            "_id": str(uuid.uuid4()),
            "notification_type": ntype,
            "recipient": recipient,
            "loan_id": loan_id,
            "status": status,
            "sent_at": iso(now_utc()),
            "error_message": error,
        }
    )


async def send_telegram(bot: str, chat_id: str, text: str, ntype: str, loan_id=None, recipient_label=None):
    """bot: 'reg' or 'loan'. Never raises."""
    label = recipient_label or chat_id
    try:
        s = await get_settings()
        enabled = s.get("telegram_reg_enabled") if bot == "reg" else s.get("telegram_loan_enabled")
        token = s.get("telegram_reg_token") if bot == "reg" else s.get("telegram_loan_token")
        if not enabled or not token:
            await _log_notification(ntype, label, loan_id, "SKIPPED", "Bot tidak aktif atau token belum diatur")
            return
        if not chat_id:
            await _log_notification(ntype, label, loan_id, "SKIPPED", "Chat ID belum diatur")
            return
        await asyncio.to_thread(_send_sync, token, str(chat_id), text)
        await _log_notification(ntype, label, loan_id, "SENT")
    except Exception as e:
        logger.warning("telegram failed: %s", e)
        try:
            await _log_notification(ntype, label, loan_id, "FAILED", str(e))
        except Exception:
            pass


async def notify_admins(bot: str, text: str, ntype: str, loan_id=None):
    cursor = db.users.find(
        {"role": {"$in": ["admin", "superadmin"]}, "is_active": True, "notify_telegram": True}
    )
    async for u in cursor:
        await send_telegram(bot, u.get("telegram_chat_id"), text, ntype, loan_id, u.get("full_name"))


async def notify_all_lenders(text: str, ntype: str, loan_id=None):
    cursor = db.users.find({"role": "lender", "is_active": True})
    async for u in cursor:
        if u.get("telegram_chat_id"):
            await send_telegram("loan", u.get("telegram_chat_id"), text, ntype, loan_id, u.get("full_name"))


async def notify_user(user_id: str, bot: str, text: str, ntype: str, loan_id=None):
    u = await db.users.find_one({"_id": user_id})
    if u:
        await send_telegram(bot, u.get("telegram_chat_id"), text, ntype, loan_id, u.get("full_name"))
