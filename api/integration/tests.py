import pytest
from rest_framework.test import APIClient

from academics.models import Result
from audit.models import AuditLog
from integration.models import CampusRef, ServiceClient, StaffRef


def _service(key: str | None) -> APIClient:
    client = APIClient()
    if key:
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    return client


@pytest.mark.django_db
def test_lms_reads_offerings_and_enrolments(result):
    _, key = ServiceClient.issue("lms", ["academics:read", "marks:write"])
    _, weak = ServiceClient.issue("other", ["students:read"])
    assert _service(None).get("/api/v1/integration/offerings/").status_code in (401, 403)
    assert _service(weak).get("/api/v1/integration/offerings/").status_code == 403

    offerings = _service(key).get("/api/v1/integration/offerings/", {"current": "1"}).json()["results"]
    assert offerings[0]["code"] == "AGR101-2026-27-S1-MRP" and offerings[0]["lecturer_employee_no"] == "E0001"
    roster = _service(key).get("/api/v1/integration/enrolments/", {"offering": offerings[0]["code"]}).json()
    assert roster["results"][0]["student_no"] == "26MRP0001"
    assert "national_id" not in roster["results"][0] and "date_of_birth" not in roster["results"][0]
    assert AuditLog.objects.filter(action="integration:enrolments.read").exists()


@pytest.mark.django_db
def test_coursework_marks_from_the_lms(result):
    _, key = ServiceClient.issue("lms", ["academics:read", "marks:write"])
    payload = {
        "offering_code": "AGR101-2026-27-S1-MRP",
        "marks": [{"student_no": "26MRP0001", "mark": "72.50"}, {"student_no": "NOPE", "mark": "10"}],
    }
    response = _service(key).post("/api/v1/integration/coursework-marks/", payload, format="json")
    assert response.status_code == 200
    assert response.json() == {
        "offering_code": "AGR101-2026-27-S1-MRP",
        "accepted": ["26MRP0001"],
        "locked": [],
        "unknown": ["NOPE"],
    }
    result.refresh_from_db()
    assert str(result.coursework_mark) == "72.50" and result.coursework_source == "lms"

    # Once submitted, the SRMS refuses further marks from the LMS and says so.
    Result.objects.filter(pk=result.pk).update(state="submitted")
    again = _service(key).post("/api/v1/integration/coursework-marks/", payload, format="json").json()
    assert again["locked"] == ["26MRP0001"] and again["accepted"] == []
    bad = _service(key).post(
        "/api/v1/integration/coursework-marks/", {**payload, "offering_code": "MISSING"}, format="json"
    )
    assert bad.status_code == 404


@pytest.mark.django_db
def test_staff_and_campuses_sync_from_the_hrms(seeded, monkeypatch, settings):
    from integration import hrms

    settings.HRMS_API_URL, settings.HRMS_API_KEY = "http://hrms-api:8000", "test-key"
    StaffRef.objects.create(employee_no="E0099", full_name="Left Already", is_active=True)
    staff = [
        {
            "employee_no": "E0001",
            "full_name": "Asha Persaud",
            "email": "asha@gsa.edu.gy",
            "campus_code": "MRP",
            "unit_code": "AGR",
            "unit_name": "Agriculture Department",
            "position_title": "Lecturer",
            "status": "active",
        },
        {
            "employee_no": "E0002",
            "full_name": "Ravi Singh",
            "email": None,
            "campus_code": "ESQ",
            "unit_code": None,
            "unit_name": None,
            "position_title": None,
            "status": "separated",
        },
    ]
    monkeypatch.setattr(hrms, "pages", lambda *a, **k: iter(staff))
    monkeypatch.setattr(
        hrms,
        "call",
        lambda *a, **k: {"campuses": [{"code": "BER", "name": "Berbice", "region": "Region 6"}], "units": []},
    )
    assert hrms.sync_org() == {"campuses": 1, "units": 0}
    assert hrms.sync_staff() == {"created": 2, "updated": 0, "deactivated": 1}
    assert CampusRef.objects.filter(code="BER").exists()
    assert StaffRef.objects.get(employee_no="E0001").unit_code == "AGR"
    assert StaffRef.objects.get(employee_no="E0002").is_active is False
    assert StaffRef.objects.get(employee_no="E0099").is_active is False
    assert hrms.sync_staff() == {"created": 0, "updated": 2, "deactivated": 0}


def test_unconfigured_sibling_raises_a_clear_error(settings):
    from integration.client import IntegrationError, call

    with pytest.raises(IntegrationError, match="not configured"):
        call("", "", "/api/v1/integration/staff/")


@pytest.mark.django_db
def test_reference_and_reports_for_staff(student, registrar, client_for):
    registry = client_for(registrar)
    assert {c["code"] for c in registry.get("/api/v1/reference/campuses/").json()} == {"MRP", "ESQ"}
    report = registry.get("/api/v1/reports/enrolment-by-programme/").json()
    assert report["rows"] == [
        {
            "programme": "DIP-AGR",
            "name": "Diploma in Agriculture",
            "campus": "MRP",
            "enrolled": 1,
            "graduated": 0,
            "total": 1,
        }
    ]
    assert client_for(student.user).get("/api/v1/reports/enrolment-by-programme/").status_code == 403


@pytest.mark.django_db
def test_a_key_held_by_the_platform_is_registered_without_being_printed(monkeypatch, capsys):
    from django.core.management import CommandError, call_command

    key = "k" * 43
    monkeypatch.setenv("SERVICE_KEY_TEST", key)
    call_command(
        "create_service_client", name="sibling", scopes=["academics:read"], key_env="SERVICE_KEY_TEST"
    )
    assert key not in capsys.readouterr().out
    client = ServiceClient.authenticate(key)
    assert client is not None and client.name == "sibling" and client.scopes == ["academics:read"]

    monkeypatch.setenv("SERVICE_KEY_TEST", "too-short")
    with pytest.raises(CommandError):
        call_command(
            "create_service_client", name="sibling", scopes=["academics:read"], key_env="SERVICE_KEY_TEST"
        )
    assert ServiceClient.authenticate(key) is not None
