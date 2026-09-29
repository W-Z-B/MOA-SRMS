"""Generic request workflow shared by the GSA ecosystem: states, transitions, actor rules, side effects.

A transition may be performed by a holder of one of `roles`, or by anyone for whom `allow(instance, user)`
is true (for example the lecturer who owns the offering). Every transition is atomic and audited.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from django.db import transaction

from audit.services import record
from iam.services import has_role


class WorkflowError(Exception):
    code = "invalid_transition"

    def __init__(self, detail: str, code: str | None = None):
        super().__init__(detail)
        if code:
            self.code = code


@dataclass(frozen=True)
class Transition:
    action: str
    sources: tuple[str, ...]
    target: str
    roles: tuple[str, ...] = ()
    allow: Callable | None = None
    requires_comment: bool = False
    on_success: tuple[Callable, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WorkflowDefinition:
    key: str
    transitions: tuple[Transition, ...]

    @staticmethod
    def _can_act(instance, user, transition: Transition) -> bool:
        if transition.roles and has_role(user, *transition.roles):
            return True
        return bool(transition.allow and transition.allow(instance, user))

    def allowed_actions(self, instance, user) -> list[str]:
        seen: list[str] = []
        for t in self.transitions:
            if instance.state in t.sources and self._can_act(instance, user, t) and t.action not in seen:
                seen.append(t.action)
        return seen

    def apply(self, instance, action: str, *, request, comment: str = ""):
        user = request.user
        matches = [t for t in self.transitions if t.action == action and instance.state in t.sources]
        if not matches:
            raise WorkflowError(f"'{action}' is not allowed from state '{instance.state}'.")
        transition = matches[0]
        if not self._can_act(instance, user, transition):
            raise WorkflowError("You are not permitted to perform this action.", code="forbidden_actor")
        if transition.requires_comment and not comment.strip():
            raise WorkflowError("A comment is required for this action.", code="comment_required")
        with transaction.atomic():
            before = {"state": instance.state}
            instance.state = transition.target
            if comment and hasattr(instance, "decision_comment"):
                instance.decision_comment = comment
            instance.updated_by = user
            instance.save()
            for hook in transition.on_success:
                hook(instance, request)
            record(request, f"transition:{action}", instance, before=before, after={"state": instance.state})
        return instance
