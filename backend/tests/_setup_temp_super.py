"""Standalone helper: create/delete temp superadmin used by regression tests.

Run:
  python _setup_temp_super.py create
  python _setup_temp_super.py delete
"""
import os
import sys
import uuid
from datetime import datetime, timezone
from pymongo import MongoClient
import bcrypt


def _load_env():
    env = {}
    with open("/app/backend/.env") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"')
    return env


ENV = _load_env()
MONGO_URL = os.environ.get("MONGO_URL", ENV.get("MONGO_URL", "mongodb://localhost:27017"))
DB_NAME = os.environ.get("DB_NAME", ENV.get("DB_NAME", "test_database"))

TEMP_PHONE = "081900000777"
TEMP_PASS = "TempSup3r!2026"


def create():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    # Remove any leftover temp super
    db.users.delete_many({"phone": TEMP_PHONE})
    uid = str(uuid.uuid4())
    hashed = bcrypt.hashpw(TEMP_PASS.encode(), bcrypt.gensalt()).decode()
    doc = {
        "_id": uid,
        "full_name": "TEST Temp Superadmin",
        "phone": TEMP_PHONE,
        "email": f"temp_super_{uid[:6]}@test.local",
        "password_hash": hashed,
        "role": "superadmin",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.users.insert_one(doc)
    db.login_attempts.delete_many({"phone": TEMP_PHONE})
    print(f"CREATED temp super: id={uid} phone={TEMP_PHONE}")
    client.close()
    return uid


def delete():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    # Handle case where phone was changed during test_iter6
    res1 = db.users.delete_many({"role": "superadmin", "full_name": "TEST Temp Superadmin"})
    res2 = db.users.delete_many({"phone": TEMP_PHONE})
    db.login_attempts.delete_many({})
    print(f"DELETED temp super rows: by_name={res1.deleted_count} by_phone={res2.deleted_count}; cleared login_attempts")
    client.close()


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "create"
    if action == "create":
        create()
    elif action == "delete":
        delete()
    else:
        print("usage: _setup_temp_super.py [create|delete]")
        sys.exit(1)
