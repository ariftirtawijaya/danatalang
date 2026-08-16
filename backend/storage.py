import os
import uuid
import requests
from fastapi import HTTPException, UploadFile

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_PREFIX = "pinjamku"

ALLOWED_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}
MAX_SIZE = 5 * 1024 * 1024

storage_key = None


def init_storage(force: bool = False):
    global storage_key
    if storage_key and not force:
        return storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    resp.raise_for_status()
    storage_key = resp.json()["storage_key"]
    return storage_key


def put_object(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data,
        timeout=120,
    )
    if resp.status_code == 404:
        key = init_storage(force=True)
        resp = requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": content_type},
            data=data,
            timeout=120,
        )
    resp.raise_for_status()
    return resp.json()


def get_object(path: str):
    key = init_storage()
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    if resp.status_code == 404:
        key = init_storage(force=True)
        resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


def list_objects(prefix: str) -> list:
    key = init_storage()
    resp = requests.get(f"{STORAGE_URL}/objects", headers={"X-Storage-Key": key}, params={"prefix": prefix}, timeout=60)
    if resp.status_code == 404:
        key = init_storage(force=True)
        resp = requests.get(f"{STORAGE_URL}/objects", headers={"X-Storage-Key": key}, params={"prefix": prefix}, timeout=60)
    resp.raise_for_status()
    return resp.json().get("objects", [])


def purge_object(path: str) -> bool:
    """The storage API exposes no DELETE verb, so the object's bytes are physically
    destroyed by overwriting it with an empty payload (verified size == 0)."""
    key = init_storage()
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": "application/octet-stream"},
        data=b"",
        timeout=60,
    )
    if resp.status_code == 404:
        key = init_storage(force=True)
        resp = requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": "application/octet-stream"},
            data=b"",
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json().get("size", -1) == 0


def purge_prefix(prefix: str = f"{APP_PREFIX}/") -> dict:
    """Purge every object under a prefix. Returns {purged, failed, remaining_bytes}."""
    purged, failed = 0, 0
    for obj in list_objects(prefix):
        try:
            if purge_object(obj["path"]):
                purged += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    remaining = sum(o.get("size", 0) for o in list_objects(prefix))
    return {"purged": purged, "failed": failed, "remaining_bytes": remaining}


async def save_upload(db, file: UploadFile, user_id: str, kind: str) -> dict:
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Tipe file tidak diizinkan. Gunakan JPG, PNG, WEBP atau PDF.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="File kosong")
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Ukuran file maksimal 5MB")
    ext = ALLOWED_MIME[content_type]
    path = f"{APP_PREFIX}/{kind}/{user_id}/{uuid.uuid4()}.{ext}"
    try:
        result = put_object(path, data, content_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gagal mengunggah file: {e}")
    file_id = str(uuid.uuid4())
    await db.files.insert_one(
        {
            "_id": file_id,
            "storage_path": result["path"],
            "kind": kind,
            "uploaded_by": user_id,
            "content_type": content_type,
            "size": result.get("size", len(data)),
            "is_deleted": False,
        }
    )
    return {"file_id": file_id, "content_type": content_type}
