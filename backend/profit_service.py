"""Profit sharing (pembagian hasil) & settlement.

Semua kalkulasi finansial dilakukan di sini (backend = source of truth).
Nominal selalu integer Rupiah, dihitung dengan Decimal + ROUND_HALF_UP,
dan platform_profit adalah sisa agar total distribusi SELALU = profit_pool.
"""

import uuid
import logging
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from typing import Optional
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from core import db, now_utc, iso, audit, get_settings, ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_LENDER
from notif import notify_user, notify_admins, rp
import loan_service as LS

logger = logging.getLogger("app")

SET_PENDING = "PENDING"
SET_WAITING = "WAITING_VERIFICATION"
SET_SETTLED = "SETTLED"

PAYOUT_NOT_READY = "NOT_READY"
PAYOUT_PENDING = "PENDING"
PAYOUT_PAID = "PAID"

SNAPSHOT_FIELDS = (
    "profit_share_lender_pct_snapshot",
    "profit_share_admin_pct_snapshot",
    "profit_share_platform_pct_snapshot",
)


def _d(value) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def validate_percentages(lender_pct, admin_pct, platform_pct) -> dict:
    parts = {"lender_pct": _d(lender_pct), "admin_pct": _d(admin_pct), "platform_pct": _d(platform_pct)}
    for key, value in parts.items():
        if value < 0 or value > 100:
            raise HTTPException(status_code=400, detail="Setiap persentase harus antara 0 dan 100")
        if value != value.quantize(Decimal("0.01")):
            raise HTTPException(status_code=400, detail="Persentase maksimal 2 angka desimal")
    total = sum(parts.values())
    if total != Decimal("100"):
        raise HTTPException(status_code=400, detail=f"Total persentase harus tepat 100% (saat ini {total}%)")
    return {k: float(v) for k, v in parts.items()}


def share_of(pool: int, percentage) -> int:
    return int((_d(int(pool)) * _d(percentage) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def split_pool(pool: int, percentages: list) -> list:
    """Largest remainder method: hasil selalu >= 0, deterministik, dan totalnya tepat = pool.

    Bagian bulat dihitung dengan floor, sisa Rupiah dibagikan ke remainder terbesar
    (tie-break: urutan indeks) sehingga tidak pernah muncul nilai negatif.
    """
    pool = int(pool)
    if pool <= 0:
        return [0 for _ in percentages]
    exact = [(_d(int(pool)) * _d(p) / Decimal(100)) for p in percentages]
    floors = [int(v.to_integral_value(rounding=ROUND_DOWN)) for v in exact]
    remainder = pool - sum(floors)
    order = sorted(range(len(exact)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in order[:remainder]:
        floors[i] += 1
    return floors


def compute_distribution(principal: int, interest_realized: int, late_fee_realized: int,
                         lender_pct, admin_pct, platform_pct) -> dict:
    principal = LS.money(principal)
    interest_realized = LS.money(interest_realized)
    late_fee_realized = LS.money(late_fee_realized)
    pool = interest_realized + late_fee_realized
    lender_profit, admin_profit, platform_profit = split_pool(pool, [lender_pct, admin_pct, platform_pct])
    return {
        "principal": principal,
        "interest_realized": interest_realized,
        "late_fee_realized": late_fee_realized,
        "profit_pool": pool,
        "total_received": principal + pool,
        "lender_pct_snapshot": float(_d(lender_pct)),
        "admin_pct_snapshot": float(_d(admin_pct)),
        "platform_pct_snapshot": float(_d(platform_pct)),
        "principal_return": principal,
        "lender_profit": lender_profit,
        "admin_profit": admin_profit,
        "platform_profit": platform_profit,
        "lender_total_entitlement": principal + lender_profit,
        "lender_settlement_due": admin_profit + platform_profit,
    }


async def snapshot_percentages() -> dict:
    s = await get_settings()
    return validate_percentages(
        s.get("profit_share_lender_pct"), s.get("profit_share_admin_pct"), s.get("profit_share_platform_pct")
    )


def loan_has_snapshot(loan: dict) -> bool:
    return all(loan.get(f) is not None for f in SNAPSHOT_FIELDS)


async def assert_ready_for_paid(loan: dict):
    """Loan dengan snapshot bagi hasil wajib punya Admin penanggung jawab sebelum bisa LUNAS."""
    if loan_has_snapshot(loan) and not loan.get("assigned_admin_id"):
        raise HTTPException(
            status_code=409,
            detail="Pinjaman ini belum memiliki Admin penanggung jawab. Superadmin harus menetapkannya terlebih dahulu.",
        )


async def resolve_assigned_admin(actor: dict, admin_id: Optional[str]) -> str:
    """Admin approve -> dirinya sendiri. Superadmin approve -> wajib memilih Admin aktif."""
    if actor.get("role") == ROLE_ADMIN:
        return str(actor["_id"])
    if not admin_id:
        raise HTTPException(
            status_code=400,
            detail="Superadmin wajib memilih Admin penanggung jawab (assigned_admin_id) sebelum menyetujui pinjaman.",
        )
    admin = await db.users.find_one({"_id": admin_id, "role": ROLE_ADMIN, "is_active": True})
    if not admin:
        raise HTTPException(status_code=400, detail="Admin penanggung jawab tidak ditemukan atau tidak aktif")
    return str(admin["_id"])


async def ensure_profit_distribution_for_paid_loan(loan: dict, payment: Optional[dict], actor: Optional[dict],
                                                  request=None) -> Optional[dict]:
    """Idempotent: aman dipanggil berulang, hanya menghasilkan SATU record per loan."""
    loan_id = str(loan["_id"])
    existing = await db.profit_distributions.find_one({"loan_id": loan_id})
    if existing:
        return existing
    if loan.get("status") != LS.S_PAID:
        return None
    if not loan_has_snapshot(loan):
        await db.loans.update_one({"_id": loan_id}, {"$set": {"profit_share_legacy": True}})
        logger.info("loan %s tanpa snapshot bagi hasil (legacy): distribusi tidak dibuat", loan.get("loan_number"))
        return None
    if not loan.get("assigned_admin_id"):
        logger.warning("loan %s PAID tanpa assigned_admin_id: distribusi ditunda", loan.get("loan_number"))
        return None

    calc = compute_distribution(
        loan["principal_amount"],
        loan.get("interest_amount"),
        loan.get("late_fee_final"),
        loan.get("profit_share_lender_pct_snapshot"),
        loan.get("profit_share_admin_pct_snapshot"),
        loan.get("profit_share_platform_pct_snapshot"),
    )
    now = iso(now_utc())
    doc = {
        "_id": str(uuid.uuid4()),
        "version": int(loan.get("profit_share_version") or 1),
        "loan_id": loan_id,
        "loan_number": loan.get("loan_number"),
        "payment_id": str(payment["_id"]) if payment else None,
        "borrower_id": loan.get("borrower_id"),
        "lender_id": loan.get("funded_by"),
        "assigned_admin_id": loan.get("assigned_admin_id"),
        **calc,
        "lender_settlement_status": SET_PENDING,
        "settlement_proof_file_id": None,
        "settlement_submitted_at": None,
        "settlement_submitted_by": None,
        "settlement_verified_at": None,
        "settlement_verified_by": None,
        "settlement_rejected_at": None,
        "settlement_rejected_by": None,
        "settlement_rejection_reason": None,
        "settlement_attempt_count": 0,
        "settlement_attempts": [],
        "admin_payout_status": PAYOUT_NOT_READY,
        "admin_payout_amount": calc["admin_profit"],
        "admin_payout_proof_file_id": None,
        "admin_payout_paid_at": None,
        "admin_payout_paid_by": None,
        "is_reversed": False,
        "reversed_at": None,
        "reversed_by": None,
        "reversal_reason": None,
        "paid_at": loan.get("paid_at"),
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db.profit_distributions.insert_one(doc)
    except DuplicateKeyError:
        return await db.profit_distributions.find_one({"loan_id": loan_id})

    await audit(
        request, actor, "PROFIT_DISTRIBUTION_CREATED", "profit_distribution", doc["_id"],
        f"Pembagian hasil {loan.get('loan_number')} dibuat. Profit pool {rp(calc['profit_pool'])}, "
        f"Pendana {rp(calc['lender_profit'])}, Admin {rp(calc['admin_profit'])}, Aplikator {rp(calc['platform_profit'])}. "
        f"Kewajiban setoran Pendana {rp(calc['lender_settlement_due'])}.",
        None,
        {k: doc[k] for k in ("profit_pool", "lender_profit", "admin_profit", "platform_profit", "lender_settlement_due")},
    )
    if doc["lender_id"]:
        await notify_user(
            doc["lender_id"], "loan",
            f"🎉 <b>PINJAMAN LUNAS</b>\n\nPinjaman {doc['loan_number']} telah lunas.\n\n"
            f"Profit Pool:\n{rp(calc['profit_pool'])}\n\n"
            f"Hak Anda (pokok + profit):\n{rp(calc['lender_total_entitlement'])}\n\n"
            f"Total setoran bagi hasil Anda:\n{rp(calc['lender_settlement_due'])}\n\n"
            "Silakan lakukan setoran melalui menu Bagi Hasil.",
            "PROFIT_DISTRIBUTION_CREATED", loan_id,
        )
    return doc


def admin_bank_complete(admin: Optional[dict]) -> bool:
    return bool(admin and admin.get("bank_name") and admin.get("account_number") and admin.get("account_holder"))


async def serialize_distribution(d: dict, with_names: bool = True, viewer: Optional[dict] = None) -> dict:
    """viewer menentukan visibilitas rekening payout Admin (tidak pernah dikirim ke Pendana)."""
    out = {k: v for k, v in d.items() if k != "_id"}
    out["id"] = str(d["_id"])
    if with_names:
        borrower = await db.users.find_one({"_id": d.get("borrower_id")}) if d.get("borrower_id") else None
        lender = await db.users.find_one({"_id": d.get("lender_id")}) if d.get("lender_id") else None
        admin = await db.users.find_one({"_id": d.get("assigned_admin_id")}) if d.get("assigned_admin_id") else None
        out["borrower_name"] = (borrower or {}).get("full_name")
        out["lender_name"] = (lender or {}).get("full_name")
        out["admin_name"] = (admin or {}).get("full_name")
        out["admin_bank"] = (
            {
                "bank_name": admin.get("bank_name"),
                "account_number": admin.get("account_number"),
                "account_holder": admin.get("account_holder"),
                "complete": admin_bank_complete(admin),
            }
            if admin
            else None
        )
        can_see_admin_bank = viewer is not None and (
            viewer.get("role") == ROLE_SUPERADMIN
            or (viewer.get("role") == ROLE_ADMIN and d.get("assigned_admin_id") == str(viewer["_id"]))
        )
        if not can_see_admin_bank:
            out.pop("admin_bank", None)
    return out


def settlement_account(settings: dict) -> dict:
    return {
        "settlement_account_type": settings.get("settlement_account_type"),
        "settlement_account_number": settings.get("settlement_account_number"),
        "settlement_account_holder": settings.get("settlement_account_holder"),
        "settlement_account_bank_name": settings.get("settlement_account_bank_name"),
        "settlement_instructions": settings.get("settlement_instructions"),
    }


def assert_can_read(d: dict, user: dict):
    role = user.get("role")
    uid = str(user["_id"])
    if role == ROLE_SUPERADMIN:
        return
    if role == ROLE_ADMIN and d.get("assigned_admin_id") == uid:
        return
    if role == ROLE_LENDER and d.get("lender_id") == uid:
        return
    raise HTTPException(status_code=403, detail="Anda tidak memiliki akses ke data pembagian hasil ini")


def role_query(user: dict) -> dict:
    role = user.get("role")
    uid = str(user["_id"])
    if role == ROLE_SUPERADMIN:
        return {}
    if role == ROLE_ADMIN:
        return {"assigned_admin_id": uid}
    if role == ROLE_LENDER:
        return {"lender_id": uid}
    raise HTTPException(status_code=403, detail="Anda tidak memiliki akses ke pembagian hasil")


async def summary_for(user: dict) -> dict:
    query = dict(role_query(user))
    query["is_reversed"] = {"$ne": True}
    docs = await db.profit_distributions.find(query).to_list(5000)
    settled = [d for d in docs if d.get("lender_settlement_status") == SET_SETTLED]
    total = lambda items, field: sum(LS.money(d.get(field)) for d in items)  # noqa: E731
    return {
        "count": len(docs),
        "interest_realized": total(docs, "interest_realized"),
        "late_fee_realized": total(docs, "late_fee_realized"),
        "profit_pool": total(docs, "profit_pool"),
        "principal_returned": total(docs, "principal_return"),
        "lender_profit": total(docs, "lender_profit"),
        "admin_profit": total(docs, "admin_profit"),
        "platform_profit": total(docs, "platform_profit"),
        "platform_earned": total(docs, "platform_profit"),
        "platform_collected": total(settled, "platform_profit"),
        "settlement_pending": total([d for d in docs if d.get("lender_settlement_status") == SET_PENDING], "lender_settlement_due"),
        "settlement_waiting": total([d for d in docs if d.get("lender_settlement_status") == SET_WAITING], "lender_settlement_due"),
        "settlement_settled": total(settled, "lender_settlement_due"),
        "count_settlement_pending": len([d for d in docs if d.get("lender_settlement_status") == SET_PENDING]),
        "count_settlement_waiting": len([d for d in docs if d.get("lender_settlement_status") == SET_WAITING]),
        "count_settlement_settled": len(settled),
        "admin_earned": total(docs, "admin_profit"),
        "admin_payable": total(
            [d for d in settled if d.get("admin_payout_status") != PAYOUT_PAID], "admin_profit"
        ),
        "admin_paid": total([d for d in docs if d.get("admin_payout_status") == PAYOUT_PAID], "admin_profit"),
        "admin_payout_not_ready": total([d for d in docs if d.get("admin_payout_status") == PAYOUT_NOT_READY], "admin_profit"),
    }
