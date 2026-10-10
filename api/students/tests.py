import pytest

from audit.models import AuditLog
from students.models import Application, Student, WaitlistEntry

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

# A minimal, valid one-pixel PNG, used to exercise document upload without a binary test fixture.
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
    b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _apply(client, programme, **overrides):
    body = {**APPLICANT, "programme": programme.id, **overrides}
    return client.post("/api/v1/applications/", body, format="json").json()


@pytest.mark.django_db
def test_admissions_flow_admits_a_student(admissions, registrar, client_for, programme):
    officer, registry = client_for(admissions), client_for(registrar)
    created = officer.post("/api/v1/applications/", {**APPLICANT, "programme": programme.id}, format="json")
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["reference"] == "APP-2026-0001" and body["state"] == "submitted"
    assert body["allowed_actions"] == ["review", "reject", "withdraw"]
    url = f"/api/v1/applications/{body['id']}/transition/"
    record_url = f"/api/v1/applications/{body['id']}/"

    assert officer.post(url, {"action": "review"}).json()["state"] == "under_review"
    assert officer.post(url, {"action": "schedule_interview"}).json()["state"] == "interview"

    # The score is entered before the interview can be marked as assessed.
    assert officer.post(url, {"action": "score"}).json()["code"] == "score_missing"
    scored = officer.patch(record_url, {"assessment_score": "78.50"}, format="json")
    assert scored.status_code == 200 and scored.json()["assessment_score"] == "78.50"
    assert officer.post(url, {"action": "score"}).json()["state"] == "assessed"

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
    body = _apply(officer, programme)
    url = f"/api/v1/applications/{body['id']}/transition/"
    assert officer.post(url, {"action": "reject"}).json()["code"] == "comment_required"
    rejected = officer.post(url, {"action": "reject", "comment": "Entry requirements not met"}).json()
    assert rejected["state"] == "rejected" and Application.objects.get(pk=body["id"]).student is None


@pytest.mark.django_db
def test_full_programme_waitlists_and_promotion_opens_an_offer(admissions, registrar, client_for, programme):
    officer, registry = client_for(admissions), client_for(registrar)
    programme.intake_capacity = 1
    programme.save(update_fields=["intake_capacity"])

    def to_assessed(email_suffix):
        body = _apply(officer, programme, email=f"a{email_suffix}@example.com")
        url = f"/api/v1/applications/{body['id']}/transition/"
        record_url = f"/api/v1/applications/{body['id']}/"
        officer.post(url, {"action": "review"})
        officer.post(url, {"action": "schedule_interview"})
        officer.patch(record_url, {"assessment_score": "80"}, format="json")
        officer.post(url, {"action": "score"})
        return body["id"], url

    first_id, first_url = to_assessed(1)
    second_id, second_url = to_assessed(2)

    assert registry.post(first_url, {"action": "offer"}).json()["state"] == "offered"
    # The programme's single place is now held; the second applicant cannot also be offered.
    full = registry.post(second_url, {"action": "offer"})
    assert full.json()["code"] == "capacity_full"
    waitlisted = registry.post(second_url, {"action": "waitlist"}).json()
    assert waitlisted["state"] == "waitlisted" and waitlisted["waitlist_rank"] == 1
    assert WaitlistEntry.objects.filter(application_id=second_id).exists()

    # The first applicant declines, the Registrar promotes the waitlisted applicant into the open place.
    registry.post(first_url, {"action": "decline"})
    promoted = registry.post(second_url, {"action": "promote"}).json()
    assert promoted["state"] == "offered" and promoted["waitlist_rank"] is None
    assert not WaitlistEntry.objects.filter(application_id=second_id).exists()


@pytest.mark.django_db
def test_application_documents_are_uploaded_and_downloaded(admissions, client_for, programme):
    officer = client_for(admissions)
    body = _apply(officer, programme)
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("transcript.png", PNG_BYTES, content_type="image/png")
    created = officer.post(
        "/api/v1/application-documents/",
        {"application": body["id"], "doc_type": "transcript", "file": upload},
    )
    assert created.status_code == 201, created.content
    doc_id = created.json()["id"]

    listed = officer.get(f"/api/v1/application-documents/?application={body['id']}").json()
    assert listed["count"] == 1

    downloaded = officer.get(f"/api/v1/application-documents/{doc_id}/download/")
    assert downloaded.status_code == 200
    assert b"".join(downloaded.streaming_content) == PNG_BYTES
    assert AuditLog.objects.filter(entity="students.applicationdocument", action="download").exists()


@pytest.mark.django_db
def test_a_renamed_executable_is_rejected_as_an_upload(admissions, client_for, programme):
    from django.core.files.uploadedfile import SimpleUploadedFile

    officer = client_for(admissions)
    body = _apply(officer, programme)
    fake = SimpleUploadedFile("transcript.png", b"MZ\x90\x00not-really-a-png", content_type="image/png")
    response = officer.post(
        "/api/v1/application-documents/",
        {"application": body["id"], "doc_type": "transcript", "file": fake},
    )
    assert response.status_code == 400


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
