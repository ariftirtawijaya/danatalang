"""Private object storage for payment/disbursement proofs.

S3-compatible (Cloudflare R2, AWS S3, MinIO, Backblaze B2, ...) — provider is switched purely
through environment variables. Objects are always private: no ACL is set, no public URL is ever
generated, and every byte is uploaded/downloaded by the backend after RBAC checks.

Env:
    S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_BUCKET_NAME, S3_REGION
    S3_PREFIX (optional, default "pinjamku")

When S3 is not configured (local development/CI) the same interface falls back to a private
on-disk directory that is likewise only reachable through the authenticated file endpoint.
"""

import os
import uuid
import shutil
import logging
import mimetypes
from pathlib import Path
from fastapi import HTTPException, UploadFile

logger = logging.getLogger("app")

APP_PREFIX = (os.environ.get("S3_PREFIX") or "pinjamku").strip("/")
LOCAL_ROOT = Path(os.environ.get("LOCAL_STORAGE_DIR") or (Path(__file__).parent / ".storage"))

ALLOWED_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}
MAX_SIZE = 5 * 1024 * 1024

_client = None


def s3_configured() -> bool:
    return all(
        os.environ.get(k)
        for k in ("S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET_NAME")
    )


def bucket() -> str:
    return os.environ["S3_BUCKET_NAME"]


def get_client():
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        _client = boto3.client(
            "s3",
            endpoint_url=os.environ["S3_ENDPOINT_URL"],
            aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
            region_name=os.environ.get("S3_REGION") or "auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
        )
    return _client


def init_storage(force: bool = False):
    """Validate connectivity at boot. Never raises for the local fallback."""
    global _client
    if force:
        _client = None
    if not s3_configured():
        LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
        os.chmod(LOCAL_ROOT, 0o700)
        logger.warning("S3 not configured; using private local storage at %s", LOCAL_ROOT)
        return "local"
    get_client().head_bucket(Bucket=bucket())
    logger.info("object storage ready: s3 bucket %s", bucket())
    return "s3"


# ---------------- local fallback helpers ----------------
def _local_path(key: str) -> Path:
    path = (LOCAL_ROOT / key).resolve()
    if not str(path).startswith(str(LOCAL_ROOT.resolve())):
        raise HTTPException(status_code=400, detail="Path objek tidak valid")
    return path


# ---------------- public API ----------------
def put_object(key: str, data: bytes, content_type: str) -> dict:
    if s3_configured():
        get_client().put_object(
            Bucket=bucket(),
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl="private, no-store",
        )
    else:
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.chmod(path, 0o600)
    return {"path": key, "size": len(data)}


def get_object(key: str):
    if s3_configured():
        try:
            obj = get_client().get_object(Bucket=bucket(), Key=key)
        except Exception as e:
            raise FileNotFoundError(str(e))
        return obj["Body"].read(), obj.get("ContentType") or "application/octet-stream"
    path = _local_path(key)
    if not path.exists():
        raise FileNotFoundError(key)
    return path.read_bytes(), mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def list_objects(prefix: str = None) -> list:
    prefix = prefix if prefix is not None else f"{APP_PREFIX}/"
    if s3_configured():
        out, token = [], None
        while True:
            kwargs = {"Bucket": bucket(), "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = get_client().list_objects_v2(**kwargs)
            out += [{"path": o["Key"], "size": o["Size"]} for o in resp.get("Contents", [])]
            if not resp.get("IsTruncated"):
                return out
            token = resp.get("NextContinuationToken")
    root = _local_path(prefix.rstrip("/"))
    if not root.exists():
        return []
    return [
        {"path": str(p.relative_to(LOCAL_ROOT)), "size": p.stat().st_size}
        for p in root.rglob("*")
        if p.is_file()
    ]


def purge_object(key: str) -> bool:
    """Permanently delete a single object."""
    if s3_configured():
        get_client().delete_object(Bucket=bucket(), Key=key)
        try:
            get_client().head_object(Bucket=bucket(), Key=key)
            return False
        except Exception:
            return True
    path = _local_path(key)
    if path.exists():
        path.unlink()
    return not path.exists()


def purge_prefix(prefix: str = None) -> dict:
    """Permanently delete every object under a prefix (used by Factory Reset)."""
    prefix = prefix if prefix is not None else f"{APP_PREFIX}/"
    purged, failed = 0, 0
    if s3_configured():
        client = get_client()
        keys = [o["path"] for o in list_objects(prefix)]
        for i in range(0, len(keys), 1000):
            batch = keys[i : i + 1000]
            resp = client.delete_objects(
                Bucket=bucket(), Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True}
            )
            failed += len(resp.get("Errors") or [])
            purged += len(batch) - len(resp.get("Errors") or [])
    else:
        for obj in list_objects(prefix):
            try:
                purged += 1 if purge_object(obj["path"]) else 0
            except Exception:
                failed += 1
        root = _local_path(prefix.rstrip("/"))
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
    remaining = list_objects(prefix)
    return {
        "purged": purged,
        "failed": failed,
        "remaining_objects": len(remaining),
        "remaining_bytes": sum(o.get("size", 0) for o in remaining),
    }


async def save_upload(db, file: UploadFile, user_id: str, kind: str) -> dict:
    content_type = (file.content_type or "").lower().split(";")[0].strip()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Tipe file tidak diizinkan. Gunakan JPG, PNG, WEBP atau PDF.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="File kosong")
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Ukuran file maksimal 5MB")
    ext = ALLOWED_MIME[content_type]
    key = f"{APP_PREFIX}/{kind}/{user_id}/{uuid.uuid4()}.{ext}"
    try:
        result = put_object(key, data, content_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("upload failed")
        raise HTTPException(status_code=502, detail=f"Gagal mengunggah file: {e}")
    file_id = str(uuid.uuid4())
    await db.files.insert_one(
        {
            "_id": file_id,
            "storage_path": result["path"],
            "kind": kind,
            "uploaded_by": user_id,
            "content_type": content_type,
            "size": result["size"],
            "is_deleted": False,
        }
    )
    return {"file_id": file_id, "content_type": content_type}
