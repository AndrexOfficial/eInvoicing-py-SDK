"""Multichannel e-invoicing engine.

Ties the three layers together for one document:

    validate → render (country format) → [sign] → transmit (channel) →
    [archive] → advance the unified state machine + audit trail.

Pick the format and channel independently:

    engine = EInvoiceEngine(
        renderer=get_renderer("fatturapa"),     # or "ubl" for PEPPOL
        transport=get_transport("aruba", cfg),  # or "peppol", "file", …
        archive=FileArchive("/var/einvoice"),   # optional conservazione/audit
    )
    result = await engine.process(invoice)
    result.lifecycle.state        # → sent / delivered / accepted / rejected …
    result.lifecycle.audit_trail()
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .enums import InvoiceState
from .formats.base import InvoiceRenderer, RenderedDocument
from .lifecycle import Lifecycle, Notification
from .models import Invoice
from .transport.base import (
    STATUS_ACCEPTED,
    STATUS_DELIVERED,
    STATUS_ERROR,
    STATUS_NOT_DELIVERED,
    STATUS_REJECTED,
    ArchiveStore,
    Signer,
    SubmissionResult,
    Transport,
)

# transport status → lifecycle target after SENT.
_STATUS_STATE = {
    STATUS_DELIVERED: InvoiceState.DELIVERED,
    STATUS_ACCEPTED: InvoiceState.ACCEPTED,
    STATUS_REJECTED: InvoiceState.REJECTED,
    STATUS_NOT_DELIVERED: InvoiceState.NOT_DELIVERED,
}


@dataclass
class EngineResult:
    rendered: RenderedDocument
    submission: SubmissionResult
    lifecycle: Lifecycle
    archive_ref: str | None = None


class EInvoiceEngine:
    def __init__(
        self,
        renderer: InvoiceRenderer,
        transport: Transport,
        *,
        signer: Signer | None = None,
        archive: ArchiveStore | None = None,
    ):
        self.renderer = renderer
        self.transport = transport
        self.signer = signer
        self.archive = archive

    async def process(self, invoice: Invoice, *, lifecycle: Lifecycle | None = None) -> EngineResult:
        lc = lifecycle or Lifecycle()

        invoice.validate()
        lc.transition(InvoiceState.VALIDATED, f"validato ({self.renderer.standard})")

        rendered = self.renderer.render(invoice)

        if self.signer is not None:
            content, fname = self.signer.sign(rendered.content, filename=rendered.filename)
            rendered = replace(rendered, content=content, filename=fname)
            lc.transition(InvoiceState.SIGNED, "firmato")

        lc.transition(InvoiceState.QUEUED, f"in coda ({self.transport.name})")

        try:
            submission = await self.transport.transmit(rendered, invoice)
        except Exception as exc:
            lc.transition(InvoiceState.FAILED, str(exc))
            raise

        if submission.status == STATUS_ERROR:
            lc.transition(InvoiceState.FAILED, submission.message)
            return EngineResult(rendered, submission, lc)

        lc.transition(InvoiceState.SENT, submission.message or submission.status)
        target = _STATUS_STATE.get(submission.status)
        if target:
            lc.transition(target, submission.message)

        archive_ref = None
        if self.archive is not None:
            archive_ref = await self.archive.store(rendered, invoice, result=submission)
            if lc.can(InvoiceState.ARCHIVED):
                lc.transition(InvoiceState.ARCHIVED, f"conservato: {archive_ref}")

        return EngineResult(rendered, submission, lc, archive_ref)

    def apply_notification(self, lifecycle: Lifecycle, notification: Notification) -> Lifecycle:
        """Advance the lifecycle from an incoming async notification (esito)."""
        return lifecycle.apply(notification)
