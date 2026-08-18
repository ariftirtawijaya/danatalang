import uuid
from datetime import timedelta, timezone
from typing import Optional
from core import db, now_utc, iso, parse_dt

S_WAITING_ADMIN = "WAITING_ADMIN_APPROVAL"
S_REJECTED = "REJECTED"
S_WAITING_FUNDING = "WAITING_FUNDING"
S_FUNDING_CLAIMED = "FUNDING_CLAIMED"
S_WAITING_DISB = "WAITING_DISBURSEMENT_CONFIRMATION"
S_ACTIVE = "ACTIVE"
S_OVERDUE = "OVERDUE"
S_WAITING_PAYMENT = "WAITING_PAYMENT_VERIFICATION"
S_COLLECTED = "PAYMENT_COLLECTED"
S_PAID = "PAID"
S_CANCELLED = "CANCELLED"

CLOSED_STATUSES = [S_PAID, S_REJECTED, S_CANCELLED, S_COLLECTED]
OUTSTANDING_QUERY = {"status": {"$nin": CLOSED_STATUSES}}


def money(value) -> int:
    return int(round(float(value or 0)))


def calc_interest(principal: int, rate: float) -> int:
    return money(principal * float(rate) / 100.0)


def calc_late_fee(principal: int, rate: float, late_days: int) -> int:
    if late_days <= 0:
        return 0
    return money(principal * float(rate) / 100.0 * late_days)


JAKARTA = timezone(timedelta(hours=7))


def late_days_for(due_date, at) -> int:
    """Whole calendar days late, evaluated in Asia/Jakarta."""
    if not due_date:
        return 0
    if at <= due_date:
        return 0
    return max(1, (at.astimezone(JAKARTA).date() - due_date.astimezone(JAKARTA).date()).days)


async def next_loan_number() -> str:
    day = (now_utc() + timedelta(hours=7)).strftime("%Y%m%d")
    doc = await db.counters.find_one_and_update(
        {"_id": f"loan-{day}"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True
    )
    return f"PIN-{day}-{doc['seq']:04d}"


async def borrower_stats(borrower_id: str) -> dict:
    loans = await db.loans.find({"borrower_id": borrower_id}).to_list(2000)
    outstanding = sum(money(l["principal_amount"]) for l in loans if l["status"] not in CLOSED_STATUSES)
    active_count = len([l for l in loans if l["status"] not in CLOSED_STATUSES])
    paid = [l for l in loans if l["status"] == S_PAID]
    late_paid = [l for l in paid if (l.get("late_days_final") or 0) > 0]
    total_late_days = sum(l.get("late_days_final") or 0 for l in paid)
    return {
        "total_applications": len(loans),
        "total_approved": len([l for l in loans if l.get("approved_at")]),
        "total_rejected": len([l for l in loans if l["status"] == S_REJECTED]),
        "total_disbursed_count": len([l for l in loans if l.get("disbursed_at")]),
        "total_borrowed_amount": sum(money(l["principal_amount"]) for l in loans if l.get("disbursed_at")),
        "active_loans": active_count,
        "completed_loans": len(paid),
        "paid_on_time": len(paid) - len(late_paid),
        "paid_late": len(late_paid),
        "total_late_days": total_late_days,
        "longest_late_days": max([l.get("late_days_final") or 0 for l in paid], default=0),
        "outstanding_principal": outstanding,
    }


async def borrower_credit(borrower: dict) -> dict:
    stats = await borrower_stats(str(borrower["_id"]))
    limit = money(borrower.get("borrower_limit"))
    stats["borrower_limit"] = limit
    stats["available_limit"] = max(0, limit - stats["outstanding_principal"])
    stats["max_duration_days"] = borrower.get("max_duration_days") or 0
    stats["max_active_loans"] = borrower.get("max_active_loans") or 0
    return stats


async def get_pending_payment(loan_id: str) -> Optional[dict]:
    return await db.payments.find_one({"loan_id": loan_id, "status": "PENDING"})


async def serialize_loan(loan: dict, deep: bool = False) -> dict:
    at = now_utc()
    status = loan["status"]
    due_date = parse_dt(loan.get("due_date"))
    pending = await get_pending_payment(str(loan["_id"]))

    if status == S_WAITING_PAYMENT and pending:
        late_days = pending.get("late_days_at_submission") or 0
        late_fee = money(pending.get("late_fee_at_submission"))
        total_due = money(pending.get("amount_due_at_submission"))
        frozen = True
    elif status == S_COLLECTED:
        late_days = loan.get("late_days_final") or 0
        late_fee = money(loan.get("late_fee_final"))
        total_due = money(loan.get("actual_payment_amount") or loan.get("base_repayment_amount"))
        frozen = True
    elif status == S_PAID:
        late_days = loan.get("late_days_final") or 0
        late_fee = money(loan.get("late_fee_final"))
        total_due = money(loan.get("actual_payment_amount") or loan.get("base_repayment_amount"))
        frozen = False
    elif status in (S_ACTIVE, S_OVERDUE):
        late_days = late_days_for(due_date, at)
        late_fee = calc_late_fee(money(loan["principal_amount"]), loan.get("late_fee_rate") or 0, late_days)
        total_due = money(loan["base_repayment_amount"]) + late_fee
        frozen = False
    else:
        late_days, late_fee, frozen = 0, 0, False
        total_due = money(loan["base_repayment_amount"])

    effective = status
    if status == S_ACTIVE and late_days > 0:
        effective = S_OVERDUE

    borrower = await db.users.find_one({"_id": loan["borrower_id"]})
    lender = await db.users.find_one({"_id": loan["funded_by"]}) if loan.get("funded_by") else None

    out = {
        "id": str(loan["_id"]),
        "loan_number": loan["loan_number"],
        "borrower_id": loan["borrower_id"],
        "borrower_name": (borrower or {}).get("full_name"),
        "borrower_phone": (borrower or {}).get("phone"),
        "lender_id": loan.get("funded_by"),
        "lender_name": (lender or {}).get("full_name"),
        "principal_amount": money(loan["principal_amount"]),
        "duration_days": loan["duration_days"],
        "interest_rate": loan["interest_rate"],
        "interest_amount": money(loan["interest_amount"]),
        "late_fee_rate": loan["late_fee_rate"],
        "base_repayment_amount": money(loan["base_repayment_amount"]),
        "status": status,
        "effective_status": effective,
        "late_days": late_days,
        "late_fee_amount": late_fee,
        "total_due": total_due,
        "payment_frozen": frozen,
        "submitted_at": loan.get("submitted_at"),
        "approved_at": loan.get("approved_at"),
        "approved_by_name": loan.get("approved_by_name"),
        "rejection_reason": loan.get("rejection_reason"),
        "rejected_at": loan.get("rejected_at"),
        "funded_at": loan.get("funded_at"),
        "disbursed_at": loan.get("disbursed_at"),
        "disbursement_confirmed_at": loan.get("disbursement_confirmed_at"),
        "due_date": loan.get("due_date"),
        "paid_at": loan.get("paid_at"),
        "days_remaining": (
            (due_date - at).days if due_date and status in (S_ACTIVE, S_OVERDUE, S_WAITING_PAYMENT) else None
        ),
    }
    if deep:
        disb = await db.disbursements.find_one({"loan_id": str(loan["_id"])})
        payments = await db.payments.find({"loan_id": str(loan["_id"])}).sort("created_at", 1).to_list(100)
        history = await db.loan_status_histories.find({"loan_id": str(loan["_id"])}).sort("changed_at", 1).to_list(200)
        out["disbursement"] = (
            {
                "id": str(disb["_id"]),
                "amount": money(disb["amount"]),
                "transfer_at": disb.get("transfer_at"),
                "proof_file_id": disb.get("proof_file_id"),
                "notes": disb.get("notes"),
                "confirmed_at": disb.get("confirmed_at"),
            }
            if disb
            else None
        )
        out["payments"] = [
            {
                "id": str(p["_id"]),
                "attempt_no": p.get("attempt_no"),
                "amount_paid": money(p["amount_paid"]),
                "amount_due_at_submission": money(p["amount_due_at_submission"]),
                "late_days_at_submission": p.get("late_days_at_submission"),
                "late_fee_at_submission": money(p.get("late_fee_at_submission")),
                "payment_submitted_at": p.get("payment_submitted_at"),
                "proof_file_id": p.get("proof_file_id"),
                "notes": p.get("notes"),
                "status": p["status"],
                "rejection_reason": p.get("rejection_reason"),
                "verified_at": p.get("verified_at"),
                "verified_by_name": p.get("verified_by_name"),
            }
            for p in payments
        ]
        out["timeline"] = [
            {
                "from_status": h.get("from_status"),
                "to_status": h.get("to_status"),
                "changed_at": h.get("changed_at"),
                "changed_by_name": h.get("changed_by_name"),
                "reason": h.get("reason"),
            }
            for h in history
        ]
        if lender:
            out["lender_bank"] = {
                "bank_name": lender.get("bank_name"),
                "account_number": lender.get("account_number"),
                "account_holder": lender.get("account_holder"),
            }
        if borrower:
            out["borrower_bank"] = {
                "bank_name": borrower.get("bank_name"),
                "account_number": borrower.get("account_number"),
                "account_holder": borrower.get("account_holder"),
            }
            out["borrower_nik"] = borrower.get("nik")
            out["borrower_account_status"] = borrower.get("account_status")
    return out


async def record_status(loan_id: str, from_status, to_status, user: Optional[dict], reason=None, metadata=None):
    await db.loan_status_histories.insert_one(
        {
            "_id": str(uuid.uuid4()),
            "loan_id": loan_id,
            "from_status": from_status,
            "to_status": to_status,
            "changed_by": str(user["_id"]) if user else None,
            "changed_by_name": (user or {}).get("full_name") or "Sistem",
            "changed_at": iso(now_utc()),
            "reason": reason,
            "metadata": metadata,
        }
    )


async def refresh_overdue_statuses():
    at = now_utc()
    cursor = db.loans.find({"status": {"$in": [S_ACTIVE, S_OVERDUE]}})
    async for loan in cursor:
        due = parse_dt(loan.get("due_date"))
        if not due:
            continue
        should = S_OVERDUE if at > due else S_ACTIVE
        if loan["status"] != should:
            await db.loans.update_one({"_id": loan["_id"]}, {"$set": {"status": should}})
            await record_status(str(loan["_id"]), loan["status"], should, None, "Perubahan otomatis oleh sistem")
