"""Identity and access for the SRMS: roles, campus scopes, multi-factor devices, login attempts.

Campuses and units are referenced by the codes the HRMS owns (MRP, ESQ, unit codes), not by local keys.
"""

from django.conf import settings
from django.db import models

from core.fields import EncryptedTextField
from core.models import TimeStampedModel


class Role(TimeStampedModel):
    ADMINISTRATOR = "administrator"
    REGISTRAR = "registrar"
    ADMISSIONS_OFFICER = "admissions_officer"
    HOD = "hod"
    LECTURER = "lecturer"
    PRINCIPAL = "principal"
    FINANCE = "finance"
    STUDENT = "student"
    AUDITOR = "auditor"
    CODES = (
        (ADMINISTRATOR, "System Administrator"),
        (REGISTRAR, "Registrar"),
        (ADMISSIONS_OFFICER, "Admissions Officer"),
        (HOD, "Head of Department"),
        (LECTURER, "Lecturer or Instructor"),
        (PRINCIPAL, "Principal / Deputy Principal"),
        (FINANCE, "Finance Officer"),
        (STUDENT, "Student"),
        (AUDITOR, "Auditor"),
    )
    MFA_REQUIRED = frozenset({ADMINISTRATOR, REGISTRAR})

    code = models.CharField(max_length=40, unique=True, choices=CODES)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class RoleScope(TimeStampedModel):
    """Grants a role to a user, optionally limited to one campus or one department (HRMS unit code)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_scopes")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="scopes")
    campus_code = models.CharField(max_length=10, blank=True)
    unit_code = models.CharField(max_length=20, blank=True)

    class Meta:
        unique_together = [("user", "role", "campus_code", "unit_code")]

    def __str__(self) -> str:
        scope = self.unit_code or self.campus_code or "all campuses"
        return f"{self.user} as {self.role.code} ({scope})"


class TotpDevice(TimeStampedModel):
    """Time-based one-time password enrolment; required for privileged roles (Role.MFA_REQUIRED)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="totp_device"
    )
    secret = EncryptedTextField()
    confirmed_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_at is not None


class LoginAttempt(models.Model):
    """Every login attempt, used to lock an account after repeated failures."""

    username = models.CharField(max_length=150, db_index=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    success = models.BooleanField(default=False)

    class Meta:
        ordering = ["-at"]

    def __str__(self) -> str:
        return f"{self.username} {'ok' if self.success else 'failed'} at {self.at:%Y-%m-%d %H:%M}"
