"""Iteration 22: regression bug filter role pada GET /api/users.

Bug: backend menimpa filter role dari client ketika pemanggilnya Admin, sehingga
`/users?role=lender` ikut mengembalikan Peminjam.
"""
import sys
import pytest
import requests

sys.path.insert(0, "/app/backend")

from test_iter16_profit_sharing import API, actors, su, loan_rates, sess, login  # noqa: E402,F401


def _roles(resp):
    assert resp.status_code == 200, resp.text
    return {i["role"] for i in resp.json()["items"]}


# ---------- Admin ----------
def test_admin_role_lender_returns_only_lender(actors):
    r = actors["admin"]["session"].get(f"{API}/users?role=lender&page_size=100", timeout=30)
    assert _roles(r) <= {"lender"}
    assert "borrower" not in _roles(r)
    assert r.json()["total"] > 0


def test_admin_role_borrower_returns_only_borrower(actors):
    r = actors["admin"]["session"].get(f"{API}/users?role=borrower&page_size=100", timeout=30)
    assert _roles(r) <= {"borrower"}


def test_admin_without_role_returns_lender_and_borrower_only(actors):
    r = actors["admin"]["session"].get(f"{API}/users?page_size=100", timeout=30)
    assert _roles(r) <= {"lender", "borrower"}


@pytest.mark.parametrize("role", ["admin", "superadmin", "lender,admin", "borrower,superadmin"])
def test_admin_forbidden_roles(actors, role):
    r = actors["admin"]["session"].get(f"{API}/users?role={role}", timeout=30)
    assert r.status_code == 403, f"{role} -> {r.status_code} {r.text[:120]}"


def test_admin_multi_allowed_roles(actors):
    r = actors["admin"]["session"].get(f"{API}/users?role=lender,borrower&page_size=100", timeout=30)
    assert _roles(r) <= {"lender", "borrower"}


# ---------- Superadmin ----------
@pytest.mark.parametrize("role", ["lender", "borrower", "admin", "superadmin"])
def test_superadmin_role_filter_respected(su, role):
    r = su.get(f"{API}/users?role={role}&page_size=100", timeout=30)
    assert _roles(r) <= {role}


def test_superadmin_multi_and_no_filter(su):
    r = su.get(f"{API}/users?role=admin,superadmin&page_size=100", timeout=30)
    assert _roles(r) <= {"admin", "superadmin"}
    r2 = su.get(f"{API}/users?page_size=100", timeout=30)
    assert _roles(r2) <= {"admin", "superadmin", "lender", "borrower"}
    assert r2.json()["total"] >= r.json()["total"]


def test_search_still_works_for_admin(actors):
    lender = actors["lender"]
    r = actors["admin"]["session"].get(f"{API}/users?role=lender&q={lender['phone']}", timeout=30)
    assert r.status_code == 200
    assert [i["role"] for i in r.json()["items"]] in ([], ["lender"])


# ---------- Auth ----------
def test_users_requires_auth(actors):
    assert requests.get(f"{API}/users?role=lender", timeout=30).status_code == 401
    assert actors["borrower"]["session"].get(f"{API}/users?role=lender", timeout=30).status_code == 403
