"""Pull campuses and staff from the HRMS. Safe to run repeatedly; also scheduled nightly."""

from django.core.management.base import BaseCommand, CommandError

from integration.client import IntegrationError
from integration.hrms import sync_org, sync_staff


class Command(BaseCommand):
    help = "Synchronise campus and staff reference data from the GSA HRMS."

    def handle(self, *args, **options):
        try:
            org = sync_org()
            staff = sync_staff()
        except IntegrationError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"HRMS sync complete: org={org} staff={staff}"))
