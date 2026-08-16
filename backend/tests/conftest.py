"""Shared conftest — creates a session-scoped TEMP superadmin so regression
tests never depend on the user's real superadmin credentials.

The temp super is created with a str(uuid.uuid4()) `_id` and password hashed
via bcrypt, then removed at end of session together with any login_attempts.

Tests should read TEST_SUPER_PHONE / TEST_SUPER_PASS from environment.
"""
import os
import sys
import pytest

# Ensure this dir is on sys.path
sys.path.insert(0, os.path.dirname(__file__))

from _setup_temp_super import create as _create_temp, delete as _delete_temp, TEMP_PHONE, TEMP_PASS

# Expose creds via env vars BEFORE test modules import
os.environ.setdefault("TEST_SUPER_PHONE", TEMP_PHONE)
os.environ.setdefault("TEST_SUPER_PASS", TEMP_PASS)


@pytest.fixture(scope="session", autouse=True)
def _temp_superadmin_lifecycle():
    """Create temp superadmin at session start, delete at session end."""
    try:
        _create_temp()
    except Exception as e:
        # If already exists (created externally), that's fine
        print(f"[conftest] create temp super warning: {e}")
    yield
    try:
        _delete_temp()
    except Exception as e:
        print(f"[conftest] delete temp super warning: {e}")
