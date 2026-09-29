"""Seed reference data for the SRMS: roles, campuses, grading scale, programmes, academic calendar.

Idempotent. Programme names come from GSA's published offer; durations, the grading scale and term
dates are placeholders for the Registrar to confirm and are editable in the application.
"""

from datetime import date

from django.core.management.base import BaseCommand

from academics.models import AcademicYear, GradeBand, Term
from core.models import PublicHoliday
from iam.models import Role
from integration.models import CampusRef
from programmes.models import Programme

CAMPUSES = [("MRP", "Mon Repos Campus", "Region 4"), ("ESQ", "Essequibo Campus", "Region 2")]

PROGRAMMES = [
    # code, name, award, years, campuses
    ("DIP-AGR", "Diploma in Agriculture", "diploma", 2, ["MRP"]),
    ("CERT-AGR", "Certificate in Agriculture", "certificate", 2, ["MRP", "ESQ"]),
    ("DIP-LPM", "Diploma in Livestock Production and Management", "diploma", 2, ["MRP"]),
    ("DIP-AHV", "Diploma in Animal Health and Veterinary Public Health", "diploma", 2, ["MRP"]),
    ("CERT-FOR", "Certificate in Forestry", "certificate", 2, ["MRP"]),
    ("CERT-FIS", "Certificate in Fisheries Studies", "certificate", 1, ["MRP"]),
    ("CERT-AGP", "Certificate in Agro-Processing", "certificate", 1, ["MRP"]),
]

GRADE_BANDS = [
    ("A", 80, 4.0, True),
    ("B", 70, 3.0, True),
    ("C", 60, 2.0, True),
    ("D", 50, 1.0, True),
    ("F", 0, 0.0, False),
]

FIXED_HOLIDAYS = [
    ((1, 1), "New Year's Day"),
    ((2, 23), "Republic Day (Mashramani)"),
    ((5, 5), "Arrival Day"),
    ((5, 26), "Independence Day"),
    ((8, 1), "Emancipation Day"),
    ((12, 25), "Christmas Day"),
    ((12, 26), "Boxing Day"),
]


class Command(BaseCommand):
    help = "Seed SRMS reference data for the Guyana School of Agriculture (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--country", default="GY")
        parser.add_argument(
            "--year", type=int, default=date.today().year, help="Start year of the academic year"
        )

    def handle(self, *args, **options):
        start = options["year"]
        for code, name in Role.CODES:
            Role.objects.update_or_create(code=code, defaults={"name": name})
        for code, name, region in CAMPUSES:
            CampusRef.objects.update_or_create(code=code, defaults={"name": name, "region": region})
        for letter, minimum, points, is_pass in GRADE_BANDS:
            GradeBand.objects.update_or_create(
                letter=letter,
                effective_from=date(2020, 1, 1),
                defaults={"min_mark": minimum, "points": points, "is_pass": is_pass},
            )
        for code, name, award, years, campuses in PROGRAMMES:
            Programme.objects.update_or_create(
                code=code,
                defaults={"name": name, "award": award, "duration_years": years, "campus_codes": campuses},
            )
        year, _ = AcademicYear.objects.update_or_create(
            code=f"{start}-{start + 1}",
            defaults={"starts": date(start, 9, 1), "ends": date(start + 1, 7, 31)},
        )
        short = f"{start}-{(start + 1) % 100:02d}"
        Term.objects.update_or_create(
            code=f"{short}-S1",
            defaults={
                "year": year,
                "number": 1,
                "name": "Semester 1",
                "starts": date(start, 9, 1),
                "ends": date(start, 12, 18),
                "is_current": True,
            },
        )
        Term.objects.update_or_create(
            code=f"{short}-S2",
            defaults={
                "year": year,
                "number": 2,
                "name": "Semester 2",
                "starts": date(start + 1, 1, 11),
                "ends": date(start + 1, 5, 28),
                "is_current": False,
            },
        )
        for calendar_year in (start, start + 1):
            for (month, day), name in FIXED_HOLIDAYS:
                PublicHoliday.objects.update_or_create(
                    date=date(calendar_year, month, day), defaults={"name": name}
                )
        self.stdout.write(
            self.style.SUCCESS(
                "Seed data applied: roles, campuses, grading scale, programmes, academic calendar."
            )
        )
