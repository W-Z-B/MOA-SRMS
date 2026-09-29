import pyotp
import pytest
from rest_framework.test import APIClient

from conftest import PASSWORD
from iam.models import TotpDevice


@pytest.mark.django_db
def test_login_logout_and_me(admissions):
    client = APIClient()
    bad = client.post(
        "/api/v1/auth/login/", {"username": "admissions.mrp", "password": "wrong"}, format="json"
    )
    assert bad.status_code == 401
    ok = client.post(
        "/api/v1/auth/login/", {"username": "admissions.mrp", "password": PASSWORD}, format="json"
    )
    assert ok.status_code == 200
    assert ok.json()["roles"] == ["admissions_officer"] and ok.json()["mfa_required"] is False
    assert ok.json()["student_no"] is None
    assert client.post("/api/v1/auth/logout/").status_code == 204
    assert client.get("/api/v1/auth/me/").status_code == 403


@pytest.mark.django_db
def test_registrar_must_enrol_and_verify_totp(registrar):
    client = APIClient()
    login = client.post("/api/v1/auth/login/", {"username": "registrar", "password": PASSWORD}, format="json")
    assert login.json()["mfa_required"] is True and login.json()["mfa_verified"] is False
    assert client.get("/api/v1/programmes/").status_code == 403
    assert "otpauth://" in client.post("/api/v1/auth/mfa/enrol/").json()["provisioning_uri"]
    secret = TotpDevice.objects.get(user=registrar).secret
    assert client.post("/api/v1/auth/mfa/verify/", {"code": "000000"}, format="json").status_code == 400
    good = client.post("/api/v1/auth/mfa/verify/", {"code": pyotp.TOTP(secret).now()}, format="json")
    assert good.status_code == 200 and good.json()["mfa_verified"] is True
    assert client.get("/api/v1/programmes/").status_code == 200


@pytest.mark.django_db
def test_student_login_reports_student_number(student):
    client = APIClient()
    ok = client.post("/api/v1/auth/login/", {"username": "26MRP0001", "password": PASSWORD}, format="json")
    assert ok.status_code == 200 and ok.json()["student_no"] == "26MRP0001"
    # A student cannot read the student directory.
    assert client.get("/api/v1/students/").status_code == 403


@pytest.mark.django_db
def test_account_locks_after_repeated_failures(admissions, settings):
    settings.LOGIN_MAX_FAILURES = 3
    client = APIClient()
    for _ in range(3):
        assert (
            client.post(
                "/api/v1/auth/login/", {"username": "admissions.mrp", "password": "wrong"}, format="json"
            ).status_code
            == 401
        )
    locked = client.post(
        "/api/v1/auth/login/", {"username": "admissions.mrp", "password": PASSWORD}, format="json"
    )
    assert locked.status_code == 423 and locked.json()["code"] == "locked_out"
