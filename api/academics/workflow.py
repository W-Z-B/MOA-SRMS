"""Results workflow (S-W03): the lecturer enters marks and submits; the Head of Department of the
offering's course reviews it; the exam board approves it; the Registrar publishes it, which locks
it against further change except through a ResultCorrection (see `academics.services`).

Decision: the ecosystem has no dedicated "exam board member" role (Phase A's `iam.Role` list has
nothing closer), so the exam-board-approval step is granted to Role.PRINCIPAL (Principal / Deputy
Principal) as the senior academic authority who would chair or stand in for the board, alongside
the Registrar as an administrative override — the same pattern Phase A already used for Registrar
overriding the Head of Department on the department-review step.
"""

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


def department_or_board(result, user) -> bool:
    """Who may send a result back to draft: the department (at either review stage) or the
    exam board (once it has reached board approval)."""
    return heads_department(result, user) or has_role(user, Role.PRINCIPAL)


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
        Transition(
            "dept_review", ("submitted",), "dept_reviewed", (Role.REGISTRAR,), allow=heads_department
        ),
        Transition("board_approve", ("dept_reviewed",), "board_approved", (Role.REGISTRAR, Role.PRINCIPAL)),
        Transition(
            "publish", ("board_approved",), "published", (Role.REGISTRAR,), on_success=(_complete_and_notify,)
        ),
        Transition(
            "return",
            ("submitted", "dept_reviewed", "board_approved"),
            "draft",
            (Role.REGISTRAR,),
            allow=department_or_board,
            requires_comment=True,
        ),
    ),
)
