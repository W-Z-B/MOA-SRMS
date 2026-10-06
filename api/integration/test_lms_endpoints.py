"""Attendance totals, course outcomes, competency results and terms for the LMS (LMS ADRs 0008 and 0017)."""

from datetime import date

import pytest
from rest_framework.test import APIClient

from academics.models import AttendanceTotal, CompetencyResult, Result
from audit.models import AuditLog
from integration.models import ServiceClient
from programmes.models import CourseOutcome, ProgrammeCourse

OFFERING = "AGR101-2026-27-S1-MRP"
ATTENDANCE = "/api/v1/integration/attendance-totals/"
OUTCOMES = "/api/v1/integration/course-outcomes/"
COMPETENCIES = "/api/v1/integration/competency-results/"
TERMS = "/api/v1/integration/terms/"
SENSITIVE = ("national_id", "date_of_birth", "address", "nis", "tin")


def _service(*scopes: str, name: str = "lms") -> APIClient:
    _, key = ServiceClient.issue(name, list(scopes))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    return client


def _row(student_no="26MRP0001", **counts):
    values = {"sessions": 10, "present": 7, "late": 1, "excused": 1, "absent": 1, "not_recorded": 0}
    values.update(counts)
    return {"student_no": student_no, **values, "percent": counts.get("percent", "88.89")}


def _no_sensitive_keys(payload) -> None:
    text = str(payload).lower()
    for key in SENSITIVE:
        assert f"'{key}'" not in text


@pytest.fixture
def requires_attendance(result, programme, offering):
    programme.attendance_required = True
    programme.save()
    ProgrammeCourse.objects.create(programme=programme, course=offering.course)
    return result


@pytest.mark.django_db
def test_attendance_totals_are_stored_once_and_shown_to_the_registrar(
    requires_attendance, registrar, client_for
):
    lms = _service("academics:read", "marks:write", "attendance:write")
    payload = {"offering_code": OFFERING, "totals": [_row(), _row("NOPE")]}
    response = lms.post(ATTENDANCE, payload, format="json")
    assert response.status_code == 200
    assert response.json() == {
        "offering_code": OFFERING,
        "accepted": ["26MRP0001"],
        "locked": [],
        "unknown": ["NOPE"],
    }
    total = AttendanceTotal.objects.get(enrolment__offering__code=OFFERING)
    assert (total.sessions, total.present, total.absent, str(total.percent)) == (10, 7, 1, "88.89")

    # Idempotent: sending again replaces the totals, never adds a second row.
    again = {"offering_code": OFFERING, "totals": [_row(sessions=12, present=9, percent="90.91")]}
    assert lms.post(ATTENDANCE, again, format="json").json()["accepted"] == ["26MRP0001"]
    assert AttendanceTotal.objects.count() == 1
    assert AttendanceTotal.objects.get().sessions == 12
    assert AuditLog.objects.filter(action="integration:attendance.write").count() == 2

    # The Registrar sees it beside the marks on the results screen.
    rows = client_for(registrar).get("/api/v1/academics/results/").json()["results"]
    assert rows[0]["attendance"]["percent"] == "90.91" and rows[0]["attendance"]["sessions"] == 12

    # A result past draft keeps the totals it had.
    Result.objects.filter(pk=requires_attendance.pk).update(state="submitted")
    locked = lms.post(ATTENDANCE, {"offering_code": OFFERING, "totals": [_row(sessions=10)]}, format="json")
    assert locked.json()["locked"] == ["26MRP0001"] and AttendanceTotal.objects.get().sessions == 12


@pytest.mark.django_db
def test_attendance_totals_refusals(requires_attendance, programme):
    lms = _service("academics:read", "marks:write", "attendance:write")
    marks_only = _service("academics:read", "marks:write", name="marks-only")
    body = {"offering_code": OFFERING, "totals": [_row()]}

    assert APIClient().post(ATTENDANCE, body, format="json").status_code in (401, 403)
    assert marks_only.post(ATTENDANCE, body, format="json").status_code == 403
    unknown = lms.post(ATTENDANCE, {**body, "offering_code": "MISSING"}, format="json")
    assert unknown.status_code == 404 and unknown.json()["code"] == "unknown_offering"
    wrong_sum = lms.post(ATTENDANCE, {**body, "totals": [_row(sessions=11)]}, format="json")
    assert wrong_sum.status_code == 400
    assert lms.post(ATTENDANCE, {**body, "totals": []}, format="json").status_code == 400

    programme.attendance_required = False
    programme.save()
    refused = lms.post(ATTENDANCE, body, format="json")
    assert refused.status_code == 409 and refused.json()["code"] == "attendance_not_required"
    assert not AttendanceTotal.objects.exists()


@pytest.mark.django_db
def test_course_outcomes_are_kept_by_the_registrar_and_read_by_the_lms(
    offering, registrar, lecturer, client_for
):
    registry = client_for(registrar)
    for position, (code, text) in enumerate([("LO2", "Plan a crop rotation"), ("LO1", "Name soil types")]):
        created = registry.post(
            "/api/v1/course-outcomes/",
            {"course": offering.course.id, "code": code, "text": text, "position": 2 - position},
            format="json",
        )
        assert created.status_code == 201, created.content
    assert AuditLog.objects.filter(entity="programmes.courseoutcome", action="create").count() == 2
    outcome = {"course": offering.course.id, "code": "LO3", "text": "x"}
    assert client_for(lecturer).post("/api/v1/course-outcomes/", outcome, format="json").status_code == 403
    course = registry.get(f"/api/v1/courses/{offering.course.id}/").json()
    assert [o["code"] for o in course["outcomes"]] == ["LO1", "LO2"]

    lms = _service("academics:read")
    page = lms.get(OUTCOMES, {"course": "AGR101"}).json()
    assert page["results"] == [
        {
            "course_code": "AGR101",
            "outcomes": [
                {"code": "LO1", "text": "Name soil types"},
                {"code": "LO2", "text": "Plan a crop rotation"},
            ],
        }
    ]
    assert AuditLog.objects.filter(action="integration:course_outcomes.read").exists()
    assert _service("attendance:write", name="other").get(OUTCOMES).status_code == 403
    assert CourseOutcome.objects.count() == 2


@pytest.mark.django_db
def test_competency_results_are_stored_per_unit_and_appear_on_the_transcript(
    result, student, registrar, client_for
):
    lms = _service("academics:read", "marks:write")
    rows = [
        {
            "offering_code": OFFERING,
            "student_no": "26MRP0001",
            "unit_code": "CROP-01",
            "result": "not_yet_competent",
            "assessed_on": "2026-10-01",
        },
        {
            "offering_code": OFFERING,
            "student_no": "26MRP0001",
            "unit_code": "CROP-02",
            "result": "competent",
            "assessed_on": "2026-10-02",
        },
        {
            "offering_code": OFFERING,
            "student_no": "NOPE",
            "unit_code": "CROP-01",
            "result": "competent",
            "assessed_on": "2026-10-02",
        },
        {
            "offering_code": "MISSING",
            "student_no": "26MRP0001",
            "unit_code": "CROP-01",
            "result": "competent",
            "assessed_on": "2026-10-02",
        },
    ]
    response = lms.post(COMPETENCIES, rows, format="json")
    assert response.status_code == 200, response.content
    body = response.json()
    assert [a["unit_code"] for a in body["accepted"]] == ["CROP-01", "CROP-02"]
    assert body["locked"] == []
    assert [(u["student_no"], u["code"]) for u in body["unknown"]] == [
        ("NOPE", "unknown_student"),
        ("26MRP0001", "unknown_offering"),
    ]

    # Idempotent: the unit assessed again replaces the earlier result.
    retake = {**rows[0], "result": "competent", "assessed_on": "2026-10-05"}
    assert len(lms.post(COMPETENCIES, [retake], format="json").json()["accepted"]) == 1
    assert CompetencyResult.objects.count() == 2
    unit = CompetencyResult.objects.get(unit_code="CROP-01")
    assert unit.result == "competent" and unit.assessed_on == date(2026, 10, 5)
    assert AuditLog.objects.filter(action="integration:competencies.write").count() == 2

    # The Registrar's transcript lists them; the student's own, published only, not until the result is.
    transcript = client_for(registrar).get(f"/api/v1/students/{student.id}/transcript/").json()
    assert [(c["unit_code"], c["result"]) for c in transcript["competencies"]] == [
        ("CROP-01", "competent"),
        ("CROP-02", "competent"),
    ]
    _no_sensitive_keys(transcript["competencies"])
    assert client_for(student.user).get("/api/v1/academics/my-results/").json()["competencies"] == []
    Result.objects.filter(pk=result.pk).update(state="published")
    mine = client_for(student.user).get("/api/v1/academics/my-results/").json()
    assert len(mine["competencies"]) == 2

    locked = lms.post(COMPETENCIES, [rows[1]], format="json").json()
    assert locked["accepted"] == [] and locked["locked"][0]["unit_code"] == "CROP-02"


@pytest.mark.django_db
def test_competency_results_refusals(result):
    row = {
        "offering_code": OFFERING,
        "student_no": "26MRP0001",
        "unit_code": "CROP-01",
        "result": "competent",
        "assessed_on": "2026-10-01",
    }
    assert APIClient().post(COMPETENCIES, [row], format="json").status_code in (401, 403)
    assert (
        _service("academics:read", "attendance:write").post(COMPETENCIES, [row], format="json").status_code
        == 403
    )
    lms = _service("marks:write", name="writer")
    assert lms.post(COMPETENCIES, [{**row, "result": "pass"}], format="json").status_code == 400
    assert lms.post(COMPETENCIES, [], format="json").status_code == 400
    assert lms.post(COMPETENCIES, {"rows": [row]}, format="json").status_code == 400
    assert not CompetencyResult.objects.exists()


@pytest.mark.django_db
def test_terms_with_their_dates(seeded):
    from academics.models import Term

    lms = _service("academics:read")
    rows = lms.get(TERMS).json()["results"]
    first = Term.objects.order_by("starts").first()
    assert rows[0] == {
        "code": first.code,
        "name": first.name,
        "year_code": first.year.code,
        "starts": first.starts.isoformat(),
        "ends": first.ends.isoformat(),
        "is_current": first.is_current,
    }
    current = lms.get(TERMS, {"current": "1"}).json()["results"]
    assert [t["code"] for t in current] == list(
        Term.objects.filter(is_current=True).values_list("code", flat=True)
    )
    assert AuditLog.objects.filter(action="integration:terms.read").exists()
    assert _service("marks:write", name="writer").get(TERMS).status_code == 403


def test_attendance_write_is_a_known_scope():
    from integration.management.commands.create_service_client import KNOWN_SCOPES

    assert "attendance:write" in KNOWN_SCOPES
