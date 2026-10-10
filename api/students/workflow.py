"""Admissions workflow.

submitted -> under_review -> interview -> assessed -> offered | waitlisted -> accepted (admits the
student) | declined | rejected | withdrawn. Rejection and withdrawal are allowed from any state before a
decision is final. A waitlisted application can later be promoted to an offer when a place opens.
"""

from core.workflow import Transition, WorkflowDefinition
from iam.models import Role

ADMISSIONS = (Role.ADMISSIONS_OFFICER, Role.REGISTRAR)
BEFORE_DECISION = ("submitted", "under_review", "interview", "assessed")


def _admit(instance, request):
    from students.services import admit

    admit(instance, actor=request.user)


def _waitlist(instance, request):
    from students.services import waitlist

    waitlist(instance, actor=request.user)


def _unwaitlist(instance, request):
    from students.services import unwaitlist

    unwaitlist(instance)


APPLICATION = WorkflowDefinition(
    key="application",
    transitions=(
        Transition("review", ("submitted",), "under_review", ADMISSIONS),
        Transition("schedule_interview", ("under_review",), "interview", ADMISSIONS),
        Transition("score", ("interview",), "assessed", ADMISSIONS),
        Transition("offer", ("assessed",), "offered", (Role.REGISTRAR,)),
        Transition("waitlist", ("assessed",), "waitlisted", (Role.REGISTRAR,), on_success=(_waitlist,)),
        Transition("promote", ("waitlisted",), "offered", (Role.REGISTRAR,), on_success=(_unwaitlist,)),
        Transition("accept", ("offered",), "accepted", ADMISSIONS, on_success=(_admit,)),
        Transition("decline", ("offered",), "declined", ADMISSIONS),
        Transition("reject", BEFORE_DECISION, "rejected", ADMISSIONS, requires_comment=True),
        Transition("withdraw", (*BEFORE_DECISION, "offered", "waitlisted"), "withdrawn", ADMISSIONS),
    ),
)
