"""Load a fictional demonstration dataset: courses, applicants, students, enrolments and results.

For staging and development databases only, never for a database that holds real records. Every
person is invented, says so in the address line, and carries an identifier that is plainly not real.
Lecturers are named by the employee numbers of the HRMS demonstration data. Idempotent: running it
again adds nothing. Run `seed` first.
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academics.models import AcademicYear, CourseOffering, Enrolment, Result, Term
from academics.services import compute
from programmes.models import Course, Programme, ProgrammeCourse
from students.models import Application, Student
from students.services import admit

FICTIONAL = "Demonstration record (fictional person)"
EMAIL_DOMAIN = "students.gsa.example"

COURSES = [
    # code, title, credits, department (HRMS unit code)
    ("AGR101", "Introduction to Crop Science", 3, "AGR"),
    ("AGR102", "Principles of Soil Science", 3, "AGR"),
    ("AGR110", "Farm Records and Mathematics", 2, "AGR"),
    ("LIV101", "Introduction to Animal Husbandry", 3, "LIV"),
]

CURRICULUM = [
    # programme, course, year, semester
    ("DIP-AGR", "AGR101", 1, 1),
    ("DIP-AGR", "AGR102", 1, 1),
    ("DIP-AGR", "LIV101", 2, 1),
    ("CERT-AGR", "AGR101", 1, 1),
    ("CERT-AGR", "AGR110", 1, 1),
    ("DIP-LPM", "LIV101", 1, 1),
    ("DIP-LPM", "AGR101", 1, 1),
]

# course, campus, lecturer (HRMS employee number); "now" is the current term, "before" the one before it
OFFERINGS = {
    "now": [
        ("AGR101", "MRP", "E0001"),
        ("AGR102", "MRP", "E0003"),
        ("LIV101", "MRP", "E0004"),
        ("AGR101", "ESQ", "E0008"),
        ("AGR110", "ESQ", "E0009"),
    ],
    "before": [("AGR101", "MRP", "E0001"), ("AGR102", "MRP", "E0003")],
}

# Admitted applicants become students, in this order, so the first Mon Repos number goes to Ravi Singh.
# reference, first name, last name, born, gender, programme, campus, intake (0 this year, -1 last year)
ADMITTED = [
    ("DEMO-001", "Ravi", "Singh", date(2006, 4, 2), "M", "DIP-AGR", "MRP", 0),
    ("DEMO-002", "Devi", "Ramnarine", date(2007, 1, 19), "F", "DIP-AGR", "MRP", 0),
    ("DEMO-003", "Joshua", "Henry", date(2006, 10, 7), "M", "DIP-AGR", "MRP", 0),
    ("DEMO-004", "Alicia", "Gomes", date(2005, 12, 28), "F", "DIP-AGR", "MRP", 0),
    ("DEMO-005", "Marcus", "Joseph", date(2006, 6, 15), "M", "DIP-AGR", "MRP", 0),
    ("DEMO-006", "Priya", "Mohamed", date(2006, 8, 3), "F", "DIP-LPM", "MRP", 0),
    ("DEMO-007", "Kevin", "Fraser", date(2005, 5, 21), "M", "DIP-LPM", "MRP", 0),
    ("DEMO-008", "Anita", "Bacchus", date(2007, 3, 11), "F", "CERT-AGR", "ESQ", 0),
    ("DEMO-009", "Shawn", "Rodrigues", date(2006, 11, 30), "M", "CERT-AGR", "ESQ", 0),
    ("DEMO-010", "Latoya", "Hinds", date(2006, 2, 9), "F", "CERT-AGR", "ESQ", 0),
    ("DEMO-011", "Vishal", "Deonarine", date(2005, 7, 14), "M", "DIP-AGR", "MRP", -1),
    ("DEMO-012", "Candace", "Peters", date(2005, 9, 26), "F", "DIP-AGR", "MRP", -1),
    ("DEMO-013", "Omar", "Ali", date(2004, 12, 5), "M", "DIP-AGR", "MRP", -1),
]

# Applications still in the admissions process, for the next intake.
# reference, first name, last name, born, gender, programme, campus, state, comment
PENDING = [
    ("DEMO-101", "Tiffany", "Edwards", date(2008, 2, 17), "F", "CERT-FOR", "MRP", "submitted", ""),
    ("DEMO-102", "Rohan", "Sukhdeo", date(2007, 9, 1), "M", "DIP-AHV", "MRP", "under_review", ""),
    ("DEMO-103", "Melissa", "Grant", date(2007, 5, 23), "F", "CERT-AGP", "MRP", "offered", ""),
    (
        "DEMO-104",
        "Andre",
        "Lewis",
        date(2008, 8, 12),
        "M",
        "DIP-AGR",
        "MRP",
        "rejected",
        "Entry requirements not met; advised to apply for the certificate",
    ),
]

# Who takes what in the current term, by application reference. Results start as empty drafts.
ENROLMENTS = {
    ("AGR101", "MRP"): [f"DEMO-{n:03d}" for n in (1, 2, 3, 4, 5, 6, 7)],
    ("AGR102", "MRP"): [f"DEMO-{n:03d}" for n in (1, 2, 3, 4, 5)],
    ("LIV101", "MRP"): [f"DEMO-{n:03d}" for n in (6, 7, 11, 12, 13)],
    ("AGR101", "ESQ"): [f"DEMO-{n:03d}" for n in (8, 9, 10)],
    ("AGR110", "ESQ"): [f"DEMO-{n:03d}" for n in (8, 9, 10)],
}
DROPPED = {("AGR102", "MRP"): ["DEMO-005"]}

# Published results of the term before, for the second-year students: coursework and examination marks.
PUBLISHED = {
    ("AGR101", "MRP"): {"DEMO-011": (78, 71), "DEMO-012": (88, 84), "DEMO-013": (52, 41)},
    ("AGR102", "MRP"): {"DEMO-011": (65, 58), "DEMO-012": (74, 69), "DEMO-013": (61, 55)},
}


class Command(BaseCommand):
    help = "Load fictional demonstration data (staging and development only). Requires --fictional."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fictional",
            action="store_true",
            help="Required: confirms this database is for demonstration, never for real records",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["fictional"]:
            raise CommandError(
                "This loads invented people. Pass --fictional to confirm the database holds no real records."
            )
        current = Term.objects.filter(is_current=True).select_related("year").order_by("-starts").first()
        programmes = {p.code: p for p in Programme.objects.all()}
        if current is None or "DIP-AGR" not in programmes:
            raise CommandError("Reference data is missing. Run `manage.py seed` first.")
        intake = current.year.starts.year
        terms = {"now": current, "before": self._term_before(intake)}

        courses = {
            code: Course.objects.update_or_create(
                code=code, defaults={"title": title, "credits": credits, "department_code": unit}
            )[0]
            for code, title, credits, unit in COURSES
        }
        for programme, course, year, semester in CURRICULUM:
            ProgrammeCourse.objects.update_or_create(
                programme=programmes[programme],
                course=courses[course],
                defaults={"year": year, "semester": semester},
            )
        offerings = {
            (when, course, campus): CourseOffering.objects.update_or_create(
                code=f"{course}-{terms[when].code}-{campus}",
                defaults={
                    "course": courses[course],
                    "term": terms[when],
                    "campus_code": campus,
                    "lecturer_employee_no": lecturer,
                },
            )[0]
            for when, rows in OFFERINGS.items()
            for course, campus, lecturer in rows
        }

        students = {}
        for index, row in enumerate(ADMITTED, start=1):
            reference, first, last, born, gender, programme, campus, offset = row
            application = self._application(
                reference, first, last, born, gender, programmes[programme], campus, intake + offset
            )
            students[reference] = self._admit(application, index)
        for reference, first, last, born, gender, programme, campus, state, comment in PENDING:
            self._application(
                reference,
                first,
                last,
                born,
                gender,
                programmes[programme],
                campus,
                intake + 1,
                state,
                comment,
            )

        for (course, campus), references in ENROLMENTS.items():
            for reference in references:
                dropped = reference in DROPPED.get((course, campus), [])
                enrolment, _ = Enrolment.objects.get_or_create(
                    student=students[reference],
                    offering=offerings["now", course, campus],
                    defaults={"status": Enrolment.Status.DROPPED if dropped else Enrolment.Status.ENROLLED},
                )
                if not dropped:
                    Result.objects.get_or_create(enrolment=enrolment)
        for (course, campus), marks in PUBLISHED.items():
            for reference, (coursework, exam) in marks.items():
                enrolment, _ = Enrolment.objects.get_or_create(
                    student=students[reference],
                    offering=offerings["before", course, campus],
                    defaults={"status": Enrolment.Status.COMPLETED},
                )
                result, created = Result.objects.get_or_create(
                    enrolment=enrolment,
                    defaults={
                        "coursework_mark": Decimal(coursework),
                        "exam_mark": Decimal(exam),
                        "state": Result.State.PUBLISHED,
                    },
                )
                if created:
                    compute(result)

        self.stdout.write(
            self.style.SUCCESS(
                f"Demonstration data applied: {len(courses)} courses, {len(offerings)} offerings, "
                f"{len(students)} students, {len(PENDING)} applications in progress, "
                f"{Result.objects.filter(state=Result.State.PUBLISHED).count()} published results."
            )
        )

    def _term_before(self, intake: int) -> Term:
        year, _ = AcademicYear.objects.get_or_create(
            code=f"{intake - 1}-{intake}",
            defaults={"starts": date(intake - 1, 9, 1), "ends": date(intake, 7, 31)},
        )
        term, _ = Term.objects.get_or_create(
            code=f"{intake - 1}-{intake % 100:02d}-S2",
            defaults={
                "year": year,
                "number": 2,
                "name": "Semester 2",
                "starts": date(intake, 1, 12),
                "ends": date(intake, 5, 29),
                "is_current": False,
            },
        )
        return term

    def _application(
        self,
        reference,
        first,
        last,
        born,
        gender,
        programme,
        campus,
        intake_year,
        state="accepted",
        comment="",
    ) -> Application:
        application, _ = Application.objects.get_or_create(
            reference=reference,
            defaults={
                "first_name": first,
                "last_name": last,
                "date_of_birth": born,
                "gender": gender,
                "email": f"{first}.{last}@{EMAIL_DOMAIN}".lower(),
                "address": FICTIONAL,
                "region": "Region 2" if campus == "ESQ" else "Region 4",
                "qualifications": "Five CSEC subjects including English A, Mathematics and a science",
                "programme": programme,
                "campus_code": campus,
                "intake_year": intake_year,
                "state": state,
                "decision_comment": comment,
            },
        )
        return application

    def _admit(self, application: Application, index: int) -> Student:
        """Admit through the admissions service; reuse a student who is already on record."""
        if application.student_id is None:
            existing = Student.objects.filter(
                first_name=application.first_name,
                last_name=application.last_name,
                date_of_birth=application.date_of_birth,
                application__isnull=True,
            ).first()
            if existing is not None:
                application.student = existing
                application.save(update_fields=["student", "updated_at"])
        student = admit(application)
        if not student.national_id:
            student.national_id = f"DEMO-ID-{index:04d}"
            student.sponsor = Student.Sponsor.GOVERNMENT if index % 3 == 0 else Student.Sponsor.SELF
            student.is_residential = index % 2 == 0
            student.save()
        return student
