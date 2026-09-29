from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from academics.models import CourseOffering, Enrolment, Result
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
def test_enrolment_respects_capacity_and_campus(student, offering, registrar, client_for):
    registry = client_for(registrar)
    CourseOffering.objects.filter(pk=offering.pk).update(capacity=0)
    full = registry.post("/api/v1/academics/enrolments/", {"student": student.id, "offering": offering.id})
    assert full.status_code == 400 and "full" in str(full.json())
    CourseOffering.objects.filter(pk=offering.pk).update(capacity=40, campus_code="ESQ")
    wrong = registry.post("/api/v1/academics/enrolments/", {"student": student.id, "offering": offering.id})
    assert wrong.status_code == 400 and "campus" in str(wrong.json())
