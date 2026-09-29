"""Admissions workflow: received, screened, offered, accepted (admits the student), rejected, withdrawn."""

from core.workflow import Transition, WorkflowDefinition
from iam.models import Role

ADMISSIONS = (Role.ADMISSIONS_OFFICER, Role.REGISTRAR)


def _admit(instance, request):
    from students.services import admit

    admit(instance, actor=request.user)


APPLICATION = WorkflowDefinition(
    key="application",
    transitions=(
        Transition("screen", ("received",), "screened", ADMISSIONS),
        Transition("offer", ("screened",), "offered", (Role.REGISTRAR,)),
        Transition("accept", ("offered",), "accepted", ADMISSIONS, on_success=(_admit,)),
        Transition(
            "reject", ("received", "screened", "offered"), "rejected", ADMISSIONS, requires_comment=True
        ),
        Transition("withdraw", ("received", "screened", "offered"), "withdrawn", ADMISSIONS),
    ),
)
