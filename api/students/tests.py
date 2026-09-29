import pytest

from audit.models import AuditLog
from students.models import Application, Student

APPLICANT = {
    "first_name": "Devi",
    "last_name": "Ramnarine",
    "date_of_birth": "2007-02-11",
    "gender": "F",
    "email": "devi@example.com",
    "qualifications": "CSEC: 6 subjects including Mathematics, English A and Agricultural Science",
    "campus_code": "MRP",
    "intake_year": 2026,
}


@pytest.mark.django_db
def test_admissions_flow_admits_a_student(admissions, registrar, client_for, programme):
    officer, registry = client_for(admissions), client_for(registrar)
    created = officer.post("/api/v1/applications/", {**APPLICANT, "programme": programme.id}, format="json")
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["reference"] == "APP-2026-0001" and body["state"] == "received"
    assert body["allowed_actions"] == ["screen", "reject", "withdraw"]
    url = f"/api/v1/applications/{body['id']}/transition/"

    assert officer.post(url, {"action": "screen"}).json()["state"] == "screened"
    # Only the Registrar makes the offer.
    assert officer.post(url, {"action": "offer"}).status_code == 403
    assert registry.post(url, {"action": "offer"}).json()["state"] == "offered"
    accepted = officer.post(url, {"action": "accept"}).json()
    assert accepted["state"] == "accepted" and accepted["student_no"] == "26MRP0001"

    student = Student.objects.get(student_no="26MRP0001")
    assert student.programme == programme and student.first_name == "Devi" and student.status == "enrolled"
    assert AuditLog.objects.filter(entity="students.application", action="transition:accept").exists()
    assert officer.post(url, {"action": "accept"}).status_code == 409


@pytest.mark.django_db
def test_rejection_requires_a_comment(admissions, client_for, programme):
    officer = client_for(admissions)
    body = officer.post(
        "/api/v1/applications/", {**APPLICANT, "programme": programme.id}, format="json"
    ).json()
    url = f"/api/v1/applications/{body['id']}/transition/"
    assert officer.post(url, {"action": "reject"}).json()["code"] == "comment_required"
    rejected = officer.post(url, {"action": "reject", "comment": "Entry requirements not met"}).json()
    assert rejected["state"] == "rejected" and Application.objects.get(pk=body["id"]).student is None


@pytest.mark.django_db
def test_students_are_campus_scoped_masked_and_reveal_is_audited(student, admissions, make_user, client_for):
    own = client_for(admissions)
    row = own.get(f"/api/v1/students/{student.id}/").json()
    assert "national_id" not in row and row["national_id_masked"].endswith("321")
    assert own.post(f"/api/v1/students/{student.id}/reveal/").json()["national_id"] == "987654321"
    assert AuditLog.objects.filter(entity="students.student", entity_id=student.id, action="reveal").exists()

    other = client_for(make_user("admissions.esq", "admissions_officer", campus_code="ESQ"))
    assert other.get(f"/api/v1/students/{student.id}/").status_code == 404
    assert other.get("/api/v1/students/").json()["count"] == 0


@pytest.mark.django_db
def test_identifier_is_encrypted_at_rest(student):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT national_id FROM students_student WHERE id = %s", [student.id])
        raw = cursor.fetchone()[0]
    assert b"987654321" not in bytes(raw)
