import pytest

from advising.models import AdvisingNote, AdvisorAssignment
from advising.services import (
    AdvisingError,
    assign,
    bulk_assign,
    current_assignment,
    unassign,
)
from notifications.models import Notification
from students.models import Student


@pytest.mark.django_db
def test_assign_requires_an_employee_number(student):
    with pytest.raises(AdvisingError) as exc:
        assign(student, "  ")
    assert exc.value.code == "advisor_required"


@pytest.mark.django_db
def test_assign_is_idempotent_for_the_same_advisor(student, registrar):
    first = assign(student, "E0001", actor=registrar)
    second = assign(student, "E0001", actor=registrar)
    assert first.id == second.id
    assert AdvisorAssignment.objects.filter(student=student).count() == 1


@pytest.mark.django_db
def test_reassigning_ends_the_previous_assignment_and_keeps_history(student, registrar):
    """Decision: one advisor at a time, history kept (not overwritten)."""
    first = assign(student, "E0001", actor=registrar)
    second = assign(student, "E0002", actor=registrar, reason="Workload rebalance")

    first.refresh_from_db()
    assert first.ended_at is not None
    assert first.ended_reason == "Workload rebalance"
    assert second.ended_at is None
    assert current_assignment(student).id == second.id
    assert AdvisorAssignment.objects.filter(student=student).count() == 2


@pytest.mark.django_db
def test_unassign_ends_the_current_assignment_without_a_replacement(student, registrar):
    assign(student, "E0001", actor=registrar)
    ended = unassign(student, actor=registrar, reason="Left the programme")
    assert ended.ended_at is not None
    assert current_assignment(student) is None


@pytest.mark.django_db
def test_unassign_without_a_current_advisor_is_a_noop(student):
    assert unassign(student) is None


@pytest.mark.django_db
def test_bulk_assign_skips_students_already_with_that_advisor(programme, make_user, registrar):
    from datetime import date

    s1 = Student.objects.create(
        student_no="26MRP0101",
        first_name="A",
        last_name="One",
        date_of_birth=date(2005, 1, 1),
        campus_code="MRP",
        programme=programme,
        intake_year=2026,
    )
    s2 = Student.objects.create(
        student_no="26MRP0102",
        first_name="B",
        last_name="Two",
        date_of_birth=date(2005, 1, 1),
        campus_code="MRP",
        programme=programme,
        intake_year=2026,
    )
    assign(s1, "E0001", actor=registrar)  # already has this advisor

    changed = bulk_assign(Student.objects.filter(id__in=[s1.id, s2.id]), "E0001", actor=registrar)
    assert changed == 1
    assert current_assignment(s1).advisor_employee_no == "E0001"
    assert current_assignment(s2).advisor_employee_no == "E0001"


@pytest.mark.django_db
def test_assign_and_bulk_assign_api(student, programme, registrar, lecturer, client_for):
    registry = client_for(registrar)

    resp = registry.post(
        "/api/v1/advising/assignments/assign/",
        {"student": student.id, "advisor_employee_no": "E0001"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json()["advisor_name"] == "Asha Persaud"

    bulk = registry.post(
        "/api/v1/advising/assignments/bulk_assign/",
        {"advisor_employee_no": "E0001", "programme": programme.id, "intake_year": student.intake_year},
        format="json",
    )
    assert bulk.status_code == 200
    body = bulk.json()
    assert body["matched"] == 1 and body["assigned"] == 0  # already assigned above, idempotent


@pytest.mark.django_db
def test_bulk_assign_requires_a_filter(registrar, client_for):
    registry = client_for(registrar)
    resp = registry.post(
        "/api/v1/advising/assignments/bulk_assign/", {"advisor_employee_no": "E0001"}, format="json"
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_lecturer_cannot_assign_an_advisor(student, lecturer, client_for):
    teacher = client_for(lecturer)
    resp = teacher.post(
        "/api/v1/advising/assignments/assign/",
        {"student": student.id, "advisor_employee_no": "E0001"},
        format="json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_my_advisees_scoped_to_the_signed_in_advisor(student, lecturer, registrar, client_for):
    assign(student, "E0001", actor=registrar)  # E0001 is the `lecturer` fixture's employee number
    mine = client_for(lecturer).get("/api/v1/advising/my-advisees/").json()
    assert len(mine) == 1
    advisee = mine[0]
    assert advisee["student_no"] == student.student_no
    # No AcademicStanding row exists until the nightly job or an override creates one (S-W04);
    # until then the advisor correctly sees "not yet computed", not a misleading default.
    assert advisee["standing_tier"] is None
    assert advisee["active_holds"] == []
    assert advisee["current_offerings"] == []


@pytest.mark.django_db
def test_my_advisees_for_a_user_with_no_staff_record(registrar, client_for):
    resp = client_for(registrar).get("/api/v1/advising/my-advisees/")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_staff"


@pytest.mark.django_db
def test_my_advisor_shows_the_students_own_history(student, registrar, client_for):
    assign(student, "E0001", actor=registrar)
    mine = client_for(student.user).get("/api/v1/advising/my-advisor/").json()
    assert len(mine) == 1 and mine[0]["advisor_employee_no"] == "E0001"


@pytest.mark.django_db
def test_advisor_can_log_a_note_only_for_their_own_advisee(
    student, lecturer, registrar, make_user, client_for
):
    assign(student, "E0001", actor=registrar)
    teacher = client_for(lecturer)

    ok = teacher.post(
        "/api/v1/advising/notes/",
        {"student": student.id, "met_on": "2026-10-05", "summary": "First check-in, going well."},
        format="json",
    )
    assert ok.status_code == 201
    assert ok.json()["advisor_employee_no"] == "E0001"  # forced to the advisor's own employee number

    other_student = make_user("26MRP0999", "student", campus_code="MRP")
    from datetime import date

    stranger = Student.objects.create(
        student_no="26MRP0999",
        user=other_student,
        first_name="Not",
        last_name="Mine",
        date_of_birth=date(2005, 1, 1),
        campus_code="MRP",
        programme=student.programme,
        intake_year=2026,
    )
    forbidden = teacher.post(
        "/api/v1/advising/notes/",
        {"student": stranger.id, "met_on": "2026-10-05", "summary": "Not my advisee."},
        format="json",
    )
    assert forbidden.status_code == 403


@pytest.mark.django_db
def test_flagged_note_notifies_the_registrar(student, lecturer, registrar, client_for):
    assign(student, "E0001", actor=registrar)
    teacher = client_for(lecturer)
    resp = teacher.post(
        "/api/v1/advising/notes/",
        {
            "student": student.id,
            "met_on": "2026-10-05",
            "summary": "Missed three classes in a row.",
            "concern": "attendance",
            "flagged_for_registrar": True,
        },
        format="json",
    )
    assert resp.status_code == 201
    assert Notification.objects.filter(recipient=registrar, title__icontains="flagged").exists()


@pytest.mark.django_db
def test_advising_notes_cannot_be_edited_or_deleted(student, lecturer, registrar, client_for):
    assign(student, "E0001", actor=registrar)
    teacher = client_for(lecturer)
    note = AdvisingNote.objects.create(
        student=student, advisor_employee_no="E0001", met_on="2026-10-01", summary="Initial note"
    )
    edit = teacher.patch(f"/api/v1/advising/notes/{note.id}/", {"summary": "Edited"}, format="json")
    assert edit.status_code == 405
    assert teacher.delete(f"/api/v1/advising/notes/{note.id}/").status_code == 405
