"""Results workflow: the lecturer submits, the Head of Department approves, the Registrar publishes."""

from core.workflow import Transition, WorkflowDefinition
from iam.models import Role
from iam.services import has_role, unit_codes


def owns_offering(result, user) -> bool:
    staff = getattr(user, "staff_ref", None)
    return bool(staff and result.enrolment.offering.lecturer_employee_no == staff.employee_no)


def heads_department(result, user) -> bool:
    if getattr(user, "is_superuser", False) or not has_role(user, Role.HOD):
        return False
    units = unit_codes(user, Role.HOD)
    return not units or result.enrolment.offering.course.department_code in units


def _compute(result, request):
    from academics.services import compute

    compute(result)


def _complete_and_notify(result, request):
    from academics.models import Enrolment
    from notifications.services import notify

    enrolment = result.enrolment
    enrolment.status = Enrolment.Status.COMPLETED
    enrolment.save(update_fields=["status", "updated_at"])
    notify(
        [enrolment.student.user],
        title=f"Result published: {enrolment.offering.course.code}",
        body=f"{enrolment.offering.course.title}: {result.letter} ({result.final_mark}).",
        link="/my-results",
        dedupe_key=f"result:{result.id}:published",
    )


RESULT = WorkflowDefinition(
    key="result",
    transitions=(
        Transition(
            "submit", ("draft",), "submitted", (Role.REGISTRAR,), allow=owns_offering, on_success=(_compute,)
        ),
        Transition("approve", ("submitted",), "approved", (Role.REGISTRAR,), allow=heads_department),
        Transition(
            "publish", ("approved",), "published", (Role.REGISTRAR,), on_success=(_complete_and_notify,)
        ),
        Transition(
            "return",
            ("submitted", "approved"),
            "draft",
            (Role.REGISTRAR,),
            allow=heads_department,
            requires_comment=True,
        ),
    ),
)
