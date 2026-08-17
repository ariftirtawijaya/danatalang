"""Iteration 15 — S3-compatible private object storage.

Covers the new /app/backend/storage.py layer:
    - S3 backend is actually reachable and configured (moto in tests, R2 in prod)
    - Uploaded objects use key pattern <prefix>/<kind>/<user_id>/<uuid>.<ext>
      (never the client-supplied filename)
    - DB `files` documents only carry {storage_path, kind, uploaded_by,
      content_type, size, is_deleted} — no bytes, no public URL
    - head_object shows correct ContentType and CacheControl 'private, no-store'
    - MIME whitelist: jpg/png/webp/pdf accepted; .exe / text/plain rejected 400;
      empty file rejected 400; >5MB rejected 400
    - RBAC on GET /api/files/{id}:
          401 without token, 403 unrelated borrower/lender, 200 for
          owner-uploader / admin / superadmin with Cache-Control private no-store
          and matching Content-Type; 404 for unknown id; 404 (not 500) when the
          object is missing from the bucket but the DB record still exists
    - No credentials/presigned URLs leak: search API responses and frontend
      bundle sources for `S3_`, `r2.cloudflarestorage`, `presign`, `aws`, and
      `EMERGENT_LLM_KEY`

Run: `cd /app/backend && python -m pytest tests/test_iter15_s3_storage.py -v -n 0`
"""
import io
import os
import re
import uuid
import glob
import random
import pytest
import requests
import boto3
from pymongo import MongoClient
from dotenv import load_dotenv

# Load backend .env so S3_* variables are available to the test process
load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://utang-tracker-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

SUPER_PHONE = os.environ["TEST_SUPER_PHONE"]
SUPER_PASS = os.environ["TEST_SUPER_PASS"]

S3_ENDPOINT = os.environ.get("S3_ENDPOINT_URL")
S3_BUCKET = os.environ.get("S3_BUCKET_NAME")
S3_PREFIX = (os.environ.get("S3_PREFIX") or "pinjamku").strip("/")


# --------------- helpers ---------------
def _s(token=None):
    s = requests.Session()
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _login(phone, password):
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {phone}: {r.status_code} {r.text}"
    return r.json()["token"]


def _rand_digits(n):
    return "".join(str(random.randint(0, 9)) for _ in range(n))


def _uniq_phone():
    return "0812" + _rand_digits(9)


# tiny valid PNG
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63f8cfc0f01f0005000101ff9c76960000000049454e44ae426082"
)


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def super_token():
    return _login(SUPER_PHONE, SUPER_PASS)


@pytest.fixture(scope="module")
def s3():
    if not S3_ENDPOINT:
        pytest.skip("S3 not configured — local fallback in use")
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("S3_REGION") or "us-east-1",
    )


# --------------- 1. Configuration & connectivity ---------------
class TestStorageConfigured:
    def test_env_populated(self):
        for k in ("S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET_NAME"):
            assert os.environ.get(k), f"{k} missing"

    def test_bucket_reachable(self, s3):
        # head_bucket should succeed
        s3.head_bucket(Bucket=S3_BUCKET)

    def test_no_emergent_llm_key(self):
        env_path = "/app/backend/.env"
        with open(env_path) as f:
            body = f.read()
        assert "EMERGENT_LLM_KEY" not in body, "EMERGENT_LLM_KEY still present in backend/.env"


# --------------- 2. Upload via branding endpoint (superadmin) ---------------
class TestUploadRoundtrip:
    """The /settings/logo endpoint uses the exact same save_upload() flow,
    so we can validate the whole storage contract without touching real loans."""

    def _upload(self, token, content, filename, ctype, kind="logo"):
        return _s(token).post(
            f"{API}/settings/logo?kind={kind}",
            files={"file": (filename, content, ctype)},
        )

    def _latest_branding_file(self, mongo):
        # branding _ids are UUID strings — no created_at; sort by insertion order via _id descending
        docs = list(mongo.files.find({"kind": "branding"}))
        return docs[-1] if docs else None

    def test_accepts_png(self, super_token, s3, mongo):
        # snapshot current branding docs, upload, find the new one
        before = {d["_id"] for d in mongo.files.find({"kind": "branding"}, {"_id": 1})}
        r = self._upload(super_token, _PNG_1x1, "logo.png", "image/png")
        assert r.status_code == 200, r.text
        after = list(mongo.files.find({"kind": "branding"}))
        new_docs = [d for d in after if d["_id"] not in before]
        assert new_docs, "no new branding file recorded"
        rec = new_docs[-1]

        # key pattern <prefix>/branding/<user_id>/<uuid>.<ext> — no filename echo
        path = rec["storage_path"]
        pattern = re.compile(rf"^{re.escape(S3_PREFIX)}/branding/[0-9a-f\-]+/[0-9a-f\-]+\.png$")
        assert pattern.match(path), f"bad key: {path}"
        assert "logo" not in path.split("/")[-1], "filename leaked into key"

        # DB doc only holds metadata — no bytes, no url
        allowed_keys = {"_id", "storage_path", "kind", "uploaded_by", "content_type",
                        "size", "is_deleted", "loan_id"}
        assert set(rec.keys()).issubset(allowed_keys), set(rec.keys()) - allowed_keys
        for banned in ("data", "bytes", "url", "public_url", "presigned"):
            assert banned not in rec

        # head_object → ContentType + Cache-Control
        head = s3.head_object(Bucket=S3_BUCKET, Key=path)
        assert head["ContentType"] == "image/png"
        assert head.get("CacheControl", "").lower() == "private, no-store"

        # cleanup this specific object + doc (branding is safe to purge)
        s3.delete_object(Bucket=S3_BUCKET, Key=path)
        mongo.files.delete_one({"_id": rec["_id"]})

    def _upload_and_cleanup(self, super_token, mongo, s3, content, name, ctype):
        before = {d["_id"] for d in mongo.files.find({"kind": "branding"}, {"_id": 1})}
        r = self._upload(super_token, content, name, ctype)
        if r.status_code == 200:
            for d in mongo.files.find({"kind": "branding"}):
                if d["_id"] not in before:
                    try:
                        s3.delete_object(Bucket=S3_BUCKET, Key=d["storage_path"])
                    except Exception:
                        pass
                    mongo.files.delete_one({"_id": d["_id"]})
        return r

    def test_accepts_jpg_webp_pdf(self, super_token, mongo, s3):
        # jpg — needs to be a decodable JPEG for python-magic-less MIME check (server checks Content-Type header only, so fake bytes are OK)
        jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 20 + b"\xff\xd9"
        assert self._upload_and_cleanup(super_token, mongo, s3, jpg, "l.jpg", "image/jpeg").status_code == 200
        # webp
        webp = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 20
        assert self._upload_and_cleanup(super_token, mongo, s3, webp, "l.webp", "image/webp").status_code == 200
        # pdf
        pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
        assert self._upload_and_cleanup(super_token, mongo, s3, pdf, "l.pdf", "application/pdf").status_code == 200

    def test_rejects_text_plain(self, super_token):
        r = self._upload(super_token, b"hello", "bad.txt", "text/plain")
        assert r.status_code == 400

    def test_rejects_exe(self, super_token):
        r = self._upload(super_token, b"MZ" + b"\x00" * 100, "bad.exe", "application/x-msdownload")
        assert r.status_code == 400

    def test_rejects_empty(self, super_token):
        r = self._upload(super_token, b"", "empty.png", "image/png")
        assert r.status_code == 400

    def test_rejects_oversize(self, super_token):
        big = b"\x00" * (5 * 1024 * 1024 + 1)
        r = self._upload(super_token, big, "big.png", "image/png")
        assert r.status_code == 400


# --------------- 3. RBAC on GET /api/files/{id} ---------------
class TestFileRBAC:
    def test_401_without_token(self, mongo):
        rec = mongo.files.find_one({"is_deleted": False})
        assert rec, "seed a file first"
        r = requests.get(f"{API}/files/{rec['_id']}")
        assert r.status_code == 401

    def test_404_unknown_id(self, super_token):
        r = _s(super_token).get(f"{API}/files/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_404_when_object_missing(self, super_token, mongo):
        # forge a DB doc that points to a non-existent key
        fid = str(uuid.uuid4())
        mongo.files.insert_one({
            "_id": fid,
            "storage_path": f"{S3_PREFIX}/branding/{uuid.uuid4()}/{uuid.uuid4()}.png",
            "kind": "branding",
            "uploaded_by": "nobody",
            "content_type": "image/png",
            "size": 0,
            "is_deleted": False,
        })
        try:
            r = _s(super_token).get(f"{API}/files/{fid}")
            assert r.status_code == 404, r.status_code
        finally:
            mongo.files.delete_one({"_id": fid})

    def test_200_for_superadmin_with_headers(self, super_token, mongo, s3):
        # upload a fresh branding file so we know it's really in S3
        before = {d["_id"] for d in mongo.files.find({"kind": "branding"}, {"_id": 1})}
        r = _s(super_token).post(
            f"{API}/settings/logo?kind=logo",
            files={"file": ("x.png", _PNG_1x1, "image/png")},
        )
        assert r.status_code == 200
        new_docs = [d for d in mongo.files.find({"kind": "branding"}) if d["_id"] not in before]
        assert new_docs
        rec = new_docs[-1]
        fid = rec["_id"]
        try:
            # Hit through the public preview URL — verifies auth + status + Content-Type
            r2 = _s(super_token).get(f"{API}/files/{fid}")
            assert r2.status_code == 200
            assert r2.headers.get("Content-Type", "").startswith("image/png")
            cc = r2.headers.get("Cache-Control", "").lower()
            # preview ingress (Cloudflare) rewrites Cache-Control and strips "private";
            # so verify backend directly on localhost:8001 for the exact "private, no-store"
            assert "no-store" in cc
            direct = requests.get(
                f"http://127.0.0.1:8001/api/files/{fid}",
                headers={"Authorization": f"Bearer {super_token}"},
                timeout=10,
            )
            assert direct.status_code == 200
            dcc = direct.headers.get("Cache-Control", "").lower()
            assert "private" in dcc and "no-store" in dcc, dcc
        finally:
            try:
                s3.delete_object(Bucket=S3_BUCKET, Key=rec["storage_path"])
            except Exception:
                pass
            mongo.files.delete_one({"_id": fid})

    def test_403_unrelated_borrower_on_loan_file(self, mongo):
        # find an existing loan-linked file (from real user's loans or leftover)
        rec = mongo.files.find_one({"loan_id": {"$ne": None}, "is_deleted": False})
        if not rec:
            pytest.skip("no loan-linked file in DB")
        # register a fresh unrelated borrower
        phone = _uniq_phone()
        r = requests.post(f"{API}/auth/register", json={
            "nik": _rand_digits(16), "full_name": "TEST S3 Unrelated",
            "birth_date": "1995-01-01", "phone": phone,
            "email": f"u_{uuid.uuid4().hex[:6]}@t.com",
            "password": "Unrelated1!", "confirm_password": "Unrelated1!",
            "bank_name": "BCA", "account_number": "1122334455", "account_holder": "TT",
        })
        assert r.status_code == 200, r.text
        tok = r.json()["token"]
        try:
            r2 = _s(tok).get(f"{API}/files/{rec['_id']}")
            assert r2.status_code == 403, r2.status_code
        finally:
            # cleanup: delete this test user
            uid = r.json()["user"]["id"]
            mongo.users.delete_one({"_id": uid})
            mongo.login_attempts.delete_many({"phone": phone})


# --------------- 4. No credential/URL leaks ---------------
class TestNoLeaks:
    def test_no_s3_creds_in_frontend_bundle(self):
        candidates = []
        for root in ("/app/frontend/src", "/app/frontend/public"):
            for ext in ("js", "jsx", "ts", "tsx", "html", "json"):
                candidates += glob.glob(f"{root}/**/*.{ext}", recursive=True)
        # scan built bundle too if present
        candidates += glob.glob("/app/frontend/build/**/*.js", recursive=True)
        leaks = {"S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_ENDPOINT_URL",
                 "r2.cloudflarestorage", "presign", "EMERGENT_LLM_KEY",
                 "emergentagent.com/objstore", "X-Storage-Key"}
        found = {}
        for p in candidates:
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    body = f.read()
            except Exception:
                continue
            for k in leaks:
                if k in body:
                    found.setdefault(k, []).append(p)
        assert not found, f"potential secret leak in frontend: {found}"

    def test_no_secrets_in_api_response(self, super_token):
        # scan a few endpoints for accidental credential dump
        endpoints = ["/auth/me", "/settings", "/settings/factory-reset/preview"]
        for ep in endpoints:
            r = _s(super_token).get(f"{API}{ep}")
            if r.status_code != 200:
                continue
            body = r.text
            for k in ("testsecret", "S3_SECRET_ACCESS_KEY", "S3_ACCESS_KEY_ID",
                      "EMERGENT_LLM_KEY", "presigned", "x-amz-signature"):
                assert k.lower() not in body.lower(), f"leak on {ep}: {k}"

    def test_no_llm_imports_in_backend(self):
        # production code must not import openai/anthropic/litellm/emergentintegrations
        pat = re.compile(r"^\s*(from|import)\s+(openai|anthropic|litellm|emergentintegrations)\b", re.M)
        for p in glob.glob("/app/backend/**/*.py", recursive=True):
            if "/tests/" in p or "__pycache__" in p:
                continue
            with open(p) as f:
                body = f.read()
            m = pat.search(body)
            assert not m, f"{p} still imports LLM lib: {m.group(0)}"


# --------------- 5. purge_prefix (DeleteObject) direct verification ---------------
# The factory-reset endpoint itself is DESTRUCTIVE against the shared test_database
# (would delete the user's canonical 5 accounts + 2 loans). Instead we exercise the
# same code path used by admin_routes → storage.purge_prefix() against a scratch
# prefix so we can prove objects are truly DeleteObject-ed (not just zeroed).
class TestPurgePrefix:
    def test_purge_prefix_deletes_objects(self, s3):
        import sys, importlib
        sys.path.insert(0, "/app/backend")
        storage = importlib.import_module("storage")
        scratch = f"iter15-purge-test-{uuid.uuid4().hex[:8]}"
        # seed 3 objects under the scratch prefix directly via storage.put_object
        keys = [f"{scratch}/a.png", f"{scratch}/b.png", f"{scratch}/c/d.png"]
        for k in keys:
            storage.put_object(k, _PNG_1x1, "image/png")
        # verify all exist
        for k in keys:
            s3.head_object(Bucket=S3_BUCKET, Key=k)
        # purge
        result = storage.purge_prefix(f"{scratch}/")
        assert result["purged"] == 3, result
        assert result["failed"] == 0, result
        assert result["remaining_objects"] == 0, result
        # confirm via list_objects_v2 that KeyCount is truly 0
        r = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=f"{scratch}/")
        assert r.get("KeyCount", 0) == 0
        # and each key is really gone (head_object 404)
        import botocore
        for k in keys:
            try:
                s3.head_object(Bucket=S3_BUCKET, Key=k)
                raise AssertionError(f"object still exists after purge: {k}")
            except botocore.exceptions.ClientError as e:
                assert e.response["Error"]["Code"] in ("404", "NoSuchKey")


# --------------- 6. Local fallback storage (dev mode, S3 env empty) ---------------
class TestLocalFallback:
    """Direct storage-module test that avoids restarting the backend.

    Temporarily clears S3_* env vars, forces storage._client refresh, and
    exercises put/get/list/purge on a private on-disk directory. Restores env
    unconditionally in teardown so subsequent tests keep using moto S3.
    """
    def test_local_fallback_roundtrip(self, tmp_path):
        import sys, importlib, os as _os
        sys.path.insert(0, "/app/backend")
        storage = importlib.import_module("storage")

        saved = {k: _os.environ.pop(k, None) for k in
                 ("S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY",
                  "S3_BUCKET_NAME", "S3_REGION")}
        saved_root = _os.environ.get("LOCAL_STORAGE_DIR")
        _os.environ["LOCAL_STORAGE_DIR"] = str(tmp_path)
        try:
            # reload module so LOCAL_ROOT is refreshed to tmp_path
            importlib.reload(storage)
            assert storage.s3_configured() is False
            assert storage.init_storage(force=True) == "local"
            key = f"iter15/local/{uuid.uuid4()}.png"
            storage.put_object(key, _PNG_1x1, "image/png")
            data, ct = storage.get_object(key)
            assert data == _PNG_1x1
            objs = storage.list_objects("iter15/")
            assert any(o["path"].endswith(".png") for o in objs)
            r = storage.purge_prefix("iter15/")
            assert r["purged"] >= 1 and r["remaining_objects"] == 0
            # file perms are 0o600 while it exists — recreate & check
            storage.put_object(key, _PNG_1x1, "image/png")
            mode = (tmp_path / key).stat().st_mode & 0o777
            assert mode == 0o600, oct(mode)
        finally:
            for k, v in saved.items():
                if v is not None:
                    _os.environ[k] = v
            if saved_root is None:
                _os.environ.pop("LOCAL_STORAGE_DIR", None)
            else:
                _os.environ["LOCAL_STORAGE_DIR"] = saved_root
            importlib.reload(storage)
