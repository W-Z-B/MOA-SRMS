"""Shared test fixtures. Database tests need PostgreSQL (run inside the Compose stack or CI)."""

from datetime import date

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

requires_postgres = pytest.mark.skipif(
    "postgresql" not in settings.DATABASES["default"]["ENGINE"],
    reason="database tests need PostgreSQL; run them in the Compose stack or CI",
)

PASSWORD = "Str0ng-Passw0rd-123"
TERM = "2026-27-S1"


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.get_closest_marker("django_db"):
            item.add_marker(requires_postgres)


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "files"


@pytest.fixture(autouse=True)
def _encryption_key(settings):
    settings.FIELD_ENCRYPTION_KEY = "test-only-key"
    from core import crypto

    crypto._fernet.cache_clear()


@pytest.fixture
def seeded(db):
    from django.core.management import call_command

    call_command("seed", "--country", "GY", "--year", "2026", verbosity=0)


@pytest.fixture
def make_user(seeded):
    def _make(username, *roles, campus_code="", unit_code="", email=""):
        from iam.models import Role, RoleScope

        user = get_user_model().objects.create_user(username=username, password=PASSWORD, email=email)
        for code in roles:
            RoleScope.objects.create(
                user=user, role=Role.objects.get(code=code), campus_code=campus_code, unit_code=unit_code
            )
        return user

    return _make


@pytest.fixture
def client_for():
    """API client signed in as a user, with the multi-factor step already satisfied."""

    def _client(user):
        client = APIClient()
        client.force_login(user)
        session = client.session
        session["mfa_verified"] = True
        session.save()
        return client

    return _client


@pytest.fixture
def registrar(make_user):
    return make_user("registrar", "registrar", email="registrar@gsa.edu.gy")


@pytest.fixture
def admissions(make_user):
    return make_user("admissions.mrp", "admissions_officer", campus_code="MRP")


@pytest.fixture
def lecturer(make_user):
    from integration.models import StaffRef

    user = make_user("lecturer.persaud", "lecturer", campus_code="MRP")
    StaffRef.objects.create(
        employee_no="E0001", full_name="Asha Persaud", campus_code="MRP", unit_code="AGR", user=user
    )
    return user


@pytest.fixture
def hod(make_user):
    return make_user("hod.agr", "hod", campus_code="MRP", unit_code="AGR")


@pytest.fixture
def programme(seeded):
    from programmes.models import Programme

    return Programme.objects.get(code="DIP-AGR")


@pytest.fixture
def student(programme, make_user):
    from students.models import Student

    user = make_user("26MRP0001", "student", campus_code="MRP", email="ravi@students.gsa.edu.gy")
    return Student.objects.create(
        student_no="26MRP0001",
        user=user,
        first_name="Ravi",
        last_name="Singh",
        date_of_birth=date(2006, 4, 2),
        gender="M",
        national_id="987654321",
        campus_code="MRP",
        programme=programme,
        intake_year=2026,
    )


@pytest.fixture
def offering(seeded):
    from academics.models import CourseOffering, Term
    from programmes.models import Course

    course = Course.objects.create(
        code="AGR101", title="Introduction to Crop Science", credits=3, department_code="AGR"
    )
    return CourseOffering.objects.create(
        code=f"AGR101-{TERM}-MRP",
        course=course,
        term=Term.objects.get(code=TERM),
        campus_code="MRP",
        lecturer_employee_no="E0001",
    )


@pytest.fixture
def result(student, offering):
    from academics.models import Enrolment, Result

    enrolment = Enrolment.objects.create(student=student, offering=offering)
    return Result.objects.create(enrolment=enrolment)
