from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from academics.models import CourseOffering, Enrolment, RegistrationHold, Result
from academics.services import compute, gpa
from notifications.models import Notification


@pytest.mark.django_db
def test_results_workflow_end_to_end(student, offering, lecturer, hod, registrar, make_user, client_for):
    registry, teacher, head = client_for(registrar), client_for(lecturer), client_for(hod)
    enrolled = registry.post(
        "/api/v1/academics/enrolments/", {"student": student.id, "offering": offering.id}, format="json"
    )
    assert enrolled.status_code == 201, enrolled.content
    result = Result.objects.get(enrolment_id=enrolled.json()["id"])
    url = f"/api/v1/academics/results/{result.id}/"

    # The lecturer sees the result, enters coursework, and cannot submit without the examination mark.
    assert teacher.get("/api/v1/academics/results/", {"offering": offering.id}).json()["count"] == 1
    assert teacher.patch(url, {"coursework_mark": "70"}, format="json").status_code == 200
    assert teacher.post(f"{url}transition/", {"action": "submit"}).json()["code"] == "marks_missing"
    graded = teacher.patch(url, {"exam_mark": "60"}, format="json").json()
    assert (graded["final_mark"], graded["letter"], graded["points"]) == ("64.00", "C", "2.00")

    # Another lecturer can neither see nor change it.
    stranger = client_for(make_user("lecturer.other", "lecturer", campus_code="MRP"))
    assert stranger.patch(url, {"exam_mark": "99"}, format="json").status_code == 404

    assert teacher.post(f"{url}transition/", {"action": "submit"}).json()["state"] == "submitted"
    assert teacher.patch(url, {"exam_mark": "99"}, format="json").status_code == 403  # locked
    assert teacher.post(f"{url}transition/", {"action": "approve"}).status_code == 403
    assert head.post(f"{url}transition/", {"action": "approve"}).json()["state"] == "approved"
    assert head.post(f"{url}transition/", {"action": "publish"}).status_code == 403
    assert registry.post(f"{url}transition/", {"action": "publish"}).json()["state"] == "published"

    assert Enrolment.objects.get(pk=enrolled.json()["id"]).status == "completed"
    assert Notification.objects.filter(recipient=student.user, title="Result published: AGR101").exists()


@pytest.mark.django_db
def test_head_of_department_can_return_a_result_with_a_comment(result, hod, client_for):
    result.coursework_mark, result.exam_mark, result.state = 50, 50, "submitted"
    result.save()
    head = client_for(hod)
    url = f"/api/v1/academics/results/{result.id}/transition/"
    assert head.post(url, {"action": "return"}).json()["code"] == "comment_required"
    assert head.post(url, {"action": "return", "comment": "Check script 14"}).json()["state"] == "draft"


@pytest.mark.django_db
def test_student_sees_only_own_published_results(result, student, client_for):
    result.coursework_mark, result.exam_mark = Decimal("80"), Decimal("90")
    compute(result)
    me = client_for(student.user)
    assert me.get("/api/v1/academics/my-results/").json()["terms"] == []
    assert me.get("/api/v1/academics/results/").status_code == 403
    Result.objects.filter(pk=result.pk).update(state="published")
    transcript = me.get("/api/v1/academics/my-results/").json()
    course = transcript["terms"][0]["courses"][0]
    assert (course["course_code"], course["letter"]) == ("AGR101", "A")
    assert transcript["cumulative_gpa"] == "4.00" and transcript["student_no"] == "26MRP0001"


@pytest.mark.django_db
def test_gpa_is_credit_weighted(result, student):
    from programmes.models import Course

    result.coursework_mark, result.exam_mark, result.state = 80, 80, "published"  # A, 4.0, 3 credits
    compute(result)
    course = Course.objects.create(
        code="LIV110", title="Poultry Production", credits=1, department_code="LIV"
    )
    second = CourseOffering.objects.create(
        code="LIV110-2026-27-S1-MRP", course=course, term=result.enrolment.offering.term, campus_code="MRP"
    )
    other = Result.objects.create(
        enrolment=Enrolment.objects.create(student=student, offering=second),
        coursework_mark=60,
        exam_mark=60,
        state="published",
    )
    compute(other)  # C, 2.0, 1 credit
    assert gpa(student) == Decimal("3.50")  # (4.0*3 + 2.0*1) / 4


@pytest.mark.django_db
def test_offering_weights_must_total_100(offering):
    with pytest.raises(IntegrityError), transaction.atomic():
        CourseOffering.objects.filter(pk=offering.pk).update(coursework_weight=50, exam_weight=60)


@pytest.mark.django_db
def test_enrolment_rejects_the_wrong_campus(student, offering, registrar, client_for):
    registry = client_for(registrar)
    CourseOffering.objects.filter(pk=offering.pk).update(campus_code="ESQ")
    wrong = registry.post("/api/v1/academics/enrolments/", {"student": student.id, "offering": offering.id})
    assert wrong.status_code == 400 and "campus" in str(wrong.json())


@pytest.mark.django_db
def test_a_full_offering_waitlists_and_dropping_a_seat_promotes_the_waitlist(
    programme, offering, registrar, make_user, client_for
):
    from students.models import Student

    registry = client_for(registrar)
    CourseOffering.objects.filter(pk=offering.pk).update(capacity=1)

    def new_student(no):
        user = make_user(no, "student", campus_code="MRP")
        return Student.objects.create(
            student_no=no,
            user=user,
            first_name="Test",
            last_name=no,
            date_of_birth="2006-01-01",
            campus_code="MRP",
            programme=programme,
            intake_year=2026,
        )

    first, second = new_student("26MRP0101"), new_student("26MRP0102")
    url = "/api/v1/academics/enrolments/"

    first_enrolment = registry.post(url, {"student": first.id, "offering": offering.id}).json()
    assert first_enrolment["status"] == "enrolled" and first_enrolment["waitlist_rank"] is None

    second_enrolment = registry.post(url, {"student": second.id, "offering": offering.id}).json()
    assert second_enrolment["status"] == "waitlisted" and second_enrolment["waitlist_rank"] == 1
    assert Result.objects.filter(enrolment_id=second_enrolment["id"]).exists() is False

    dropped = registry.post(f"{url}{first_enrolment['id']}/drop/").json()
    assert dropped["status"] == "dropped"

    promoted = Enrolment.objects.get(pk=second_enrolment["id"])
    assert promoted.status == Enrolment.Status.ENROLLED and promoted.waitlist_rank is None
    assert Result.objects.filter(enrolment=promoted).exists()
    assert Notification.objects.filter(recipient=second.user, title__startswith="You are enrolled").exists()


@pytest.mark.django_db
def test_prerequisite_must_be_passed_before_enrolling(student, offering, registrar, client_for):
    from programmes.models import Course, CoursePrerequisite

    advanced_course = Course.objects.create(code="AGR201", title="Advanced Crop Science", credits=3)
    advanced = CourseOffering.objects.create(
        code="AGR201-2026-27-S1-MRP", course=advanced_course, term=offering.term, campus_code="MRP"
    )
    CoursePrerequisite.objects.create(course=advanced_course, prerequisite=offering.course)
    registry = client_for(registrar)
    url = "/api/v1/academics/enrolments/"

    blocked = registry.post(url, {"student": student.id, "offering": advanced.id})
    assert blocked.status_code == 400 and "AGR101" in str(blocked.json())

    passed = Result.objects.create(
        enrolment=Enrolment.objects.create(student=student, offering=offering),
        coursework_mark=70,
        exam_mark=70,
        state="published",
    )
    compute(passed)
    allowed = registry.post(url, {"student": student.id, "offering": advanced.id})
    assert allowed.status_code == 201, allowed.content


@pytest.mark.django_db
def test_a_registration_hold_blocks_new_enrolment_but_not_an_existing_drop(
    student, offering, registrar, client_for
):
    registry = client_for(registrar)
    hold = RegistrationHold.objects.create(
        student=student, reason=RegistrationHold.Reason.MISSING_DOCUMENT, source="admissions"
    )
    url = "/api/v1/academics/enrolments/"
    blocked = registry.post(url, {"student": student.id, "offering": offering.id})
    assert blocked.status_code == 400 and "hold" in str(blocked.json())

    resolved = registry.post(f"/api/v1/academics/registration-holds/{hold.id}/resolve/")
    assert resolved.json()["is_active"] is False
    allowed = registry.post(url, {"student": student.id, "offering": offering.id})
    assert allowed.status_code == 201, allowed.content

    # Dropping an existing enrolment is never blocked by a hold.
    RegistrationHold.objects.create(
        student=student, reason=RegistrationHold.Reason.FINANCIAL, source="fees"
    )
    enrolment_id = allowed.json()["id"]
    dropped = registry.post(f"{url}{enrolment_id}/drop/")
    assert dropped.json()["status"] == "dropped"
