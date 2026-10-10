"""Raise this term's fee charges for every active student in a programme (or every programme).

Run once a term starts, by a Finance Officer or Registrar with shell access; idempotent, so running
it again (or for a programme already charged) adds nothing. Bulk charging stays a management
command rather than an API action, matching how `seed` and `sync_hrms` already run in this repo.
"""

from django.core.management.base import BaseCommand, CommandError

from academics.models import Term
from fees.services import charge_student_for_term
from programmes.models import Programme
from students.models import Student


class Command(BaseCommand):
    help = "Charge this term's fees to every active student, e.g. --term 2026-27-S1"

    def add_arguments(self, parser):
        parser.add_argument("--term", required=True, help="Term code, e.g. 2026-27-S1")
        parser.add_argument("--programme", help="Limit to one programme code; default is every programme")

    def handle(self, *args, **options):
        try:
            term = Term.objects.get(code=options["term"])
        except Term.DoesNotExist as exc:
            raise CommandError(f"No term with code {options['term']!r}.") from exc

        students = Student.objects.filter(status=Student.Status.ENROLLED)
        if options["programme"]:
            try:
                programme = Programme.objects.get(code=options["programme"])
            except Programme.DoesNotExist as exc:
                raise CommandError(f"No programme with code {options['programme']!r}.") from exc
            students = students.filter(programme=programme)

        charged, total = 0, 0
        for student in students:
            new_charges = charge_student_for_term(student, term)
            total += len(new_charges)
            charged += int(bool(new_charges))

        self.stdout.write(
            self.style.SUCCESS(f"Raised {total} charge(s) for {charged} student(s) in term {term.code}.")
        )
