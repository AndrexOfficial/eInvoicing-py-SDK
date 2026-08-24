"""Unified invoice lifecycle — a single channel-agnostic state machine plus an
append-only audit trail and normalized notifications (esiti).

The platform owns one :class:`Lifecycle` per document. Transitions are
validated, every change is recorded as a :class:`LifecycleEvent`, and incoming
provider/SDI/PEPPOL notifications are normalized to :class:`Notification` and
applied uniformly — so audit, reconciliation and reporting don't care which
channel the document went through.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from .enums import InvoiceState, NotificationType
from .errors import IllegalTransition

# Allowed transitions. Kept deliberately permissive on the "outcome" edges
# (SENT can go to any SDI outcome) and strict on the build-up edges.
_ALLOWED: dict[InvoiceState, set[InvoiceState]] = {
    InvoiceState.DRAFT: {InvoiceState.VALIDATED, InvoiceState.CANCELLED, InvoiceState.FAILED},
    InvoiceState.VALIDATED: {InvoiceState.SIGNED, InvoiceState.QUEUED, InvoiceState.FAILED, InvoiceState.CANCELLED},
    InvoiceState.SIGNED: {InvoiceState.QUEUED, InvoiceState.FAILED},
    InvoiceState.QUEUED: {InvoiceState.SENT, InvoiceState.FAILED},
    InvoiceState.SENT: {
        InvoiceState.DELIVERED, InvoiceState.ACCEPTED, InvoiceState.REJECTED,
        InvoiceState.NOT_DELIVERED, InvoiceState.FAILED,
    },
    InvoiceState.DELIVERED: {InvoiceState.ACCEPTED, InvoiceState.REJECTED, InvoiceState.ARCHIVED},
    InvoiceState.NOT_DELIVERED: {InvoiceState.DELIVERED, InvoiceState.ACCEPTED, InvoiceState.ARCHIVED},
    InvoiceState.ACCEPTED: {InvoiceState.ARCHIVED},
    InvoiceState.REJECTED: {InvoiceState.DRAFT, InvoiceState.ARCHIVED},
    InvoiceState.FAILED: {InvoiceState.QUEUED, InvoiceState.DRAFT, InvoiceState.CANCELLED},
    InvoiceState.ARCHIVED: set(),
    InvoiceState.CANCELLED: set(),
}

# Which state a normalized notification drives the document to.
_NOTIF_STATE: dict[NotificationType, InvoiceState] = {
    NotificationType.DELIVERED: InvoiceState.DELIVERED,
    NotificationType.REJECTED: InvoiceState.REJECTED,
    NotificationType.NOT_DELIVERED: InvoiceState.NOT_DELIVERED,
    NotificationType.DEADLINE_PASSED: InvoiceState.ACCEPTED,
    NotificationType.RECEIPT: InvoiceState.SENT,
}


@dataclass
class Notification:
    """A normalized delivery outcome from any channel."""

    type: NotificationType
    positive: bool = True             # for OUTCOME / CUSTOMER_OUTCOME (esito)
    sdi_id: str | None = None
    message: str | None = None
    at: datetime | None = None
    raw: dict = field(default_factory=dict)

    def target_state(self) -> InvoiceState:
        if self.type in (NotificationType.OUTCOME, NotificationType.CUSTOMER_OUTCOME):
            return InvoiceState.ACCEPTED if self.positive else InvoiceState.REJECTED
        return _NOTIF_STATE.get(self.type, InvoiceState.SENT)


@dataclass
class LifecycleEvent:
    state: InvoiceState
    at: datetime
    detail: str | None = None
    actor: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        d["at"] = self.at.isoformat()
        return d


class Lifecycle:
    """State machine + append-only audit trail for one document."""

    def __init__(self, state: InvoiceState = InvoiceState.DRAFT):
        self.state = state
        self.events: list[LifecycleEvent] = [
            LifecycleEvent(state, datetime.now(UTC), "created")
        ]

    def can(self, to: InvoiceState) -> bool:
        return to in _ALLOWED.get(self.state, set())

    def transition(
        self, to: InvoiceState, detail: str | None = None, *,
        actor: str | None = None, at: datetime | None = None,
    ) -> Lifecycle:
        if to == self.state:
            return self
        if not self.can(to):
            raise IllegalTransition(
                f"Transizione non consentita: {self.state.value} → {to.value}"
            )
        self.state = to
        self.events.append(LifecycleEvent(to, at or datetime.now(UTC), detail, actor))
        return self

    def apply(self, notification: Notification, *, actor: str | None = None) -> Lifecycle:
        return self.transition(
            notification.target_state(),
            detail=notification.message or notification.type.value,
            actor=actor,
            at=notification.at,
        )

    @property
    def is_terminal(self) -> bool:
        return not _ALLOWED.get(self.state, set())

    def audit_trail(self) -> list[dict]:
        return [e.to_dict() for e in self.events]
