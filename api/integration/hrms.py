"""Pull staff and organisation reference data from the HRMS, which is their system of record."""

from django.conf import settings
from django.utils import timezone

from integration.client import call, pages
from integration.models import CampusRef, StaffRef


def sync_org() -> dict:
    payload = call(settings.HRMS_API_URL, settings.HRMS_API_KEY, "/api/v1/integration/org/")
    for campus in payload.get("campuses", []):
        CampusRef.objects.update_or_create(
            code=campus["code"], defaults={"name": campus["name"], "region": campus.get("region", "")}
        )
    return {"campuses": len(payload.get("campuses", [])), "units": len(payload.get("units", []))}


def sync_staff() -> dict:
    """Upsert staff by employee number. Staff missing from the HRMS answer are marked inactive."""
    seen: set[str] = set()
    created = updated = 0
    now = timezone.now()
    for row in pages(settings.HRMS_API_URL, settings.HRMS_API_KEY, "/api/v1/integration/staff/"):
        _, was_created = StaffRef.objects.update_or_create(
            employee_no=row["employee_no"],
            defaults={
                "full_name": row["full_name"],
                "email": row.get("email") or "",
                "campus_code": row.get("campus_code") or "",
                "unit_code": row.get("unit_code") or "",
                "unit_name": row.get("unit_name") or "",
                "position_title": row.get("position_title") or "",
                "is_active": row.get("status") == "active",
                "synced_at": now,
            },
        )
        seen.add(row["employee_no"])
        created += was_created
        updated += not was_created
    deactivated = (
        StaffRef.objects.exclude(employee_no__in=seen).filter(is_active=True).update(is_active=False)
    )
    return {"created": created, "updated": updated, "deactivated": deactivated}
