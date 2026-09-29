import pytest
from django.core.exceptions import ImproperlyConfigured

from core import crypto


def test_encrypt_decrypt_round_trip():
    token = crypto.encrypt("987654321")
    assert token != b"987654321"
    assert crypto.decrypt(token) == "987654321"


def test_mask_shows_only_last_characters():
    assert crypto.mask("987654321").endswith("321") and "987" not in crypto.mask("987654321")
    assert crypto.mask(None) is None


def test_missing_key_is_a_configuration_error(settings):
    settings.FIELD_ENCRYPTION_KEY = ""
    crypto._fernet.cache_clear()
    with pytest.raises(ImproperlyConfigured):
        crypto.encrypt("x")
    crypto._fernet.cache_clear()


@pytest.mark.django_db
def test_seed_is_idempotent(seeded):
    from django.core.management import call_command

    from academics.models import GradeBand, Term
    from programmes.models import Programme

    before = (Programme.objects.count(), GradeBand.objects.count(), Term.objects.count())
    call_command("seed", "--country", "GY", "--year", "2026", verbosity=0)
    assert (Programme.objects.count(), GradeBand.objects.count(), Term.objects.count()) == before
    assert Term.objects.filter(is_current=True).count() == 1


@pytest.mark.django_db
def test_demonstration_data_is_fictional_idempotent_and_consistent(seeded):
    from decimal import Decimal

    from django.core.management import CommandError, call_command

    from academics.models import CourseOffering, Enrolment, Result
    from academics.services import gpa
    from students.models import Application, Student

    with pytest.raises(CommandError):
        call_command("seed_demo", verbosity=0)
    assert Student.objects.count() == 0

    def counts():
        return (
            Student.objects.count(),
            Application.objects.count(),
            CourseOffering.objects.count(),
            Enrolment.objects.count(),
            Result.objects.count(),
        )

    call_command("seed_demo", fictional=True, verbosity=0)
    first = counts()
    call_command("seed_demo", fictional=True, verbosity=0)
    assert counts() == first
    assert first[:3] == (13, 17, 7)

    assert not Student.objects.exclude(address__icontains="fictional").exists()
    ravi = Student.objects.get(student_no="26MRP0001")
    assert (ravi.first_name, ravi.last_name, ravi.application.reference) == ("Ravi", "Singh", "DEMO-001")
    assert ravi.national_id.startswith("DEMO-")
    assert Student.objects.filter(campus_code="ESQ").count() == 3
    assert Student.objects.filter(student_no__startswith="25MRP").count() == 3

    # the current term starts as empty drafts that the LMS can fill; a dropped course has no result
    current = Result.objects.filter(enrolment__offering__term__is_current=True)
    assert current.count() == 22 and not current.exclude(state="draft").exists()
    assert not current.filter(coursework_mark__isnull=False).exists()
    assert Enrolment.objects.filter(status="dropped").count() == 1

    # the term before is published and graded under the seeded scale
    published = Result.objects.filter(state="published")
    assert published.count() == 6 and not published.filter(letter="").exists()
    omar = Student.objects.get(application__reference="DEMO-013")
    failed = published.get(enrolment__student=omar, enrolment__offering__course__code="AGR101")
    assert (failed.final_mark, failed.letter, failed.is_pass) == (Decimal("45.40"), "F", False)
    assert gpa(Student.objects.get(application__reference="DEMO-012")) == Decimal("3.50")
