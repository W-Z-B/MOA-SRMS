"""Role look-ups used by permissions, scoping and workflows."""

from iam.models import Role, RoleScope

BROAD_READ_ROLES = frozenset({Role.ADMINISTRATOR, Role.REGISTRAR, Role.PRINCIPAL, Role.AUDITOR})


def role_codes(user) -> set[str]:
    if not getattr(user, "is_authenticated", False) or getattr(user, "is_service", False):
        return set()
    cached = getattr(user, "_role_codes", None)
    if cached is None:
        cached = set(RoleScope.objects.filter(user=user).values_list("role__code", flat=True))
        user._role_codes = cached
    return cached


def has_role(user, *codes: str) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return bool(role_codes(user) & set(codes))


def campus_codes(user) -> set[str]:
    """Campuses the user is explicitly scoped to."""
    return set(
        RoleScope.objects.filter(user=user).exclude(campus_code="").values_list("campus_code", flat=True)
    )


def unit_codes(user, role: str) -> set[str]:
    """Departments (HRMS unit codes) a role grant is limited to, e.g. the departments a HOD heads."""
    return set(
        RoleScope.objects.filter(user=user, role__code=role)
        .exclude(unit_code="")
        .values_list("unit_code", flat=True)
    )


def requires_mfa(user) -> bool:
    return bool(role_codes(user) & Role.MFA_REQUIRED) or getattr(user, "is_superuser", False)


def scope_queryset(user, queryset, campus_field: str = "campus_code"):
    """Restrict a queryset to the user's campuses unless the user holds a broad role."""
    if getattr(user, "is_superuser", False) or role_codes(user) & BROAD_READ_ROLES:
        return queryset
    codes = campus_codes(user)
    if not codes:
        return queryset.none()
    return queryset.filter(**{f"{campus_field}__in": codes})


def person_payload(user) -> dict:
    """Links from the signed-in user to this system's person records."""
    staff = getattr(user, "staff_ref", None)
    student = getattr(user, "student", None)
    return {
        "employee_no": staff.employee_no if staff else None,
        "student_id": student.id if student else None,
        "student_no": student.student_no if student else None,
    }
