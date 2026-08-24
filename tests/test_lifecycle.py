import pytest

from einvoice import InvoiceState, Lifecycle, Notification, NotificationType
from einvoice.errors import IllegalTransition


def test_initial_state_and_audit():
    lc = Lifecycle()
    assert lc.state == InvoiceState.DRAFT
    assert len(lc.events) == 1


def test_valid_path():
    lc = Lifecycle()
    lc.transition(InvoiceState.VALIDATED)
    lc.transition(InvoiceState.QUEUED)
    lc.transition(InvoiceState.SENT)
    assert lc.state == InvoiceState.SENT
    assert [e.state for e in lc.events][-1] == InvoiceState.SENT


def test_illegal_transition_raises():
    lc = Lifecycle()
    with pytest.raises(IllegalTransition):
        lc.transition(InvoiceState.SENT)  # DRAFT → SENT not allowed


def test_apply_notification_delivers():
    lc = Lifecycle()
    lc.transition(InvoiceState.VALIDATED)
    lc.transition(InvoiceState.QUEUED)
    lc.transition(InvoiceState.SENT)
    lc.apply(Notification(type=NotificationType.DELIVERED, sdi_id="SDI123"))
    assert lc.state == InvoiceState.DELIVERED
    trail = lc.audit_trail()
    assert trail[-1]["state"] == "delivered"


def test_outcome_negative_rejects():
    lc = Lifecycle()
    for s in (InvoiceState.VALIDATED, InvoiceState.QUEUED, InvoiceState.SENT, InvoiceState.DELIVERED):
        lc.transition(s)
    lc.apply(Notification(type=NotificationType.CUSTOMER_OUTCOME, positive=False))
    assert lc.state == InvoiceState.REJECTED
