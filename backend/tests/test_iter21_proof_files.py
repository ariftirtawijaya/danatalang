"""Iteration 21: bukti (proof) file — content type JPG/PNG/WEBP/PDF, RBAC, dan
ketersediaan file existing untuk komponen ProofImage."""
import io
import sys
import uuid
import pytest
import requests

sys.path.insert(0, "/app/backend")

from test_iter16_profit_sharing import (  # noqa: E402
    API, MONGO, actors, su, loan_rates, sess, login, png_bytes, submit_loan, create_staff,
)
from test_iter17_profit_hardening import wide_borrower_limit  # noqa: E402,F401


def _real_image(fmt: str) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (120, 80), (30, 90, 160)).save(buf, format=fmt)
    return buf.getvalue()


def webp_bytes():
    return _real_image("WEBP")


def pdf_bytes():
    return b"%PDF-1.4\n" + b"0" * 300 + b"\n%%EOF"


VARIANTS = {
    "png": ("bukti.png", _real_image("PNG"), "image/png"),
    "jpg": ("bukti.jpg", _real_image("JPEG"), "image/jpeg"),
    "webp": ("bukti.webp", webp_bytes(), "image/webp"),
    "pdf": ("bukti.pdf", pdf_bytes(), "application/pdf"),
}


def _disbursed_loan(su, actors, kind):
    loan = submit_loan(actors["borrower"], principal=1_500_000)
    lid = loan["id"]
    assert su.post(f"{API}/loans/{lid}/approve",
                   json={"assigned_admin_id": actors["admin"]["id"]}, timeout=30).status_code == 200
    assert actors["lender"]["session"].post(f"{API}/loans/{lid}/claim", timeout=30).status_code == 200
    name, data, mime = VARIANTS[kind]
    r = actors["lender"]["session"].post(
        f"{API}/loans/{lid}/disburse",
        data={"amount": 1_500_000, "transfer_at": "2026-06-01T10:00", "notes": ""},
        files={"proof": (name, io.BytesIO(data), mime)}, timeout=60)
    assert r.status_code == 200, r.text
    return lid


@pytest.mark.parametrize("kind", list(VARIANTS))
def test_proof_upload_and_fetch_content_type(su, actors, kind):
    lid = _disbursed_loan(su, actors, kind)
    loan = su.get(f"{API}/loans/{lid}", timeout=30).json()
    fid = loan["disbursement"]["proof_file_id"]
    assert fid
    r = su.get(f"{API}/files/{fid}", timeout=30)
    assert r.status_code == 200, r.text
    assert (r.headers.get("Content-Type") or "").startswith(VARIANTS[kind][2].split("/")[0])
    assert r.headers["Content-Type"].startswith(VARIANTS[kind][2])
    assert len(r.content) > 0
    cc = (r.headers.get("Cache-Control") or "").lower()
    assert "private" in cc or "no-store" in cc


def test_file_requires_auth_and_blocks_unrelated(su, actors):
    lid = _disbursed_loan(su, actors, "png")
    fid = su.get(f"{API}/loans/{lid}", timeout=30).json()["disbursement"]["proof_file_id"]
    assert requests.get(f"{API}/files/{fid}", timeout=30).status_code == 401
    assert requests.get(f"{API}/files/{fid}", headers={"Authorization": "Bearer palsu"},
                        timeout=30).status_code == 401
    other = create_staff(su, "lender", 77, "Pendana Tak Terkait")
    assert other["session"].get(f"{API}/files/{fid}", timeout=30).status_code == 403
    # peminjam pemilik & pendana pemilik tetap boleh
    assert actors["borrower"]["session"].get(f"{API}/files/{fid}", timeout=30).status_code == 200
    assert actors["lender"]["session"].get(f"{API}/files/{fid}", timeout=30).status_code == 200


def test_existing_files_still_served(su):
    """ProofImage dipakai untuk file existing: sampel file lama harus tetap terbaca."""
    docs = list(MONGO.files.find({"is_deleted": {"$ne": True}}).limit(5))
    assert docs, "butuh minimal satu file existing"
    for d in docs:
        r = su.get(f"{API}/files/{d['_id']}", timeout=30)
        assert r.status_code == 200, f"{d['_id']} -> {r.status_code}"
        assert len(r.content) > 0
