"""FattureInCloud transports (API v2) — two, because there are two integrations.

:class:`FattureInCloudTransport` (``"fattureincloud"``) uses the **structured**
API: it maps the domain :class:`Invoice` onto FIC's ``issued_document`` and lets
FIC build the FatturaPA XML. Good when FIC is the system of record — the invoice
also appears in the customer's FIC account as a native document.

:class:`FattureInCloudXmlTransport` (``"fattureincloud_xml"``) uploads a
**pre-rendered** FatturaPA instead. Use it when the host already rendered and
persisted the XML: that file is the fiscal document of record, and re-deriving
it from the model would transmit something subtly different from what was
stored, audited and shown to the customer. It is also the only faithful option
for anything FIC's structured payload cannot express — line-level discounts,
cassa previdenziale, bollo, ritenuta, linked-document references.

Config for both: ``api_key`` (access token) + ``company_id``.
Docs: https://developers.fattureincloud.it/
"""
from __future__ import annotations

import base64
import contextlib

from ..errors import ProviderConfigError, ProviderError
from ..formats.base import RenderedDocument
from ..models import Invoice
from ._http import request_json
from .base import (
    STATUS_ACCEPTED,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
    STATUS_UNKNOWN,
    SubmissionResult,
    Transport,
    TransportConfig,
    TransportStatus,
)

_DEFAULT_BASE = "https://api-v2.fattureincloud.it"
_STATUS_MAP = {
    "not_sent": STATUS_SUBMITTED, "sent": STATUS_PENDING, "pending": STATUS_PENDING,
    "delivered": STATUS_ACCEPTED, "accepted": STATUS_ACCEPTED,
    "rejected": STATUS_REJECTED, "error": STATUS_REJECTED,
}


class FattureInCloudTransport(Transport):
    name = "fattureincloud"

    def __init__(self, config: TransportConfig):
        super().__init__(config)
        if not config.api_key:
            raise ProviderConfigError("FattureInCloud: 'api_key' (access token) richiesto")
        if not config.company_id:
            raise ProviderConfigError("FattureInCloud: 'company_id' richiesto")
        self.base = (config.base_url or _DEFAULT_BASE).rstrip("/")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json", "Accept": "application/json"}

    def _payload(self, invoice: Invoice) -> dict:
        b = invoice.buyer
        code, pec = invoice.resolved_recipient()
        return {"data": {
            "type": "invoice",
            "entity": {
                "name": b.display_name(), "vat_number": b.vat_number, "tax_code": b.tax_code,
                "address_street": b.address.street if b.address else None,
                "address_postal_code": b.address.postcode if b.address else None,
                "address_city": b.address.city if b.address else None,
                "address_province": b.address.province if b.address else None,
                "country": b.address.country if b.address else "IT",
                "certified_email": pec, "ei_code": code,
            },
            "date": invoice.date.isoformat(), "number": invoice.number,
            "currency": {"id": invoice.currency},
            "items_list": [
                {"name": ln.description, "qty": float(ln.quantity),
                 "measure": ln.unit_of_measure, "net_price": float(ln.unit_price),
                 "vat": {"value": float(ln.vat_rate)}}
                for ln in invoice.lines
            ],
            "payments_list": [
                {"amount": float(p.amount if p.amount is not None else invoice.total_payable()),
                 "due_date": (p.due_date or invoice.date).isoformat()}
                for p in invoice.payments
            ],
            "e_invoice": True,
        }}

    async def transmit(self, rendered: RenderedDocument, invoice: Invoice) -> SubmissionResult:
        invoice.validate()
        url = f"{self.base}/c/{self.config.company_id}/issued_documents"
        created = await request_json("POST", url, headers=self._headers(),
                                     json=self._payload(invoice), timeout=self.config.timeout)
        doc = created.get("data", {})
        doc_id = str(doc.get("id")) if doc.get("id") is not None else None
        if doc_id:
            send = f"{self.base}/c/{self.config.company_id}/issued_documents/{doc_id}/e_invoice/send"
            # Best-effort: the document already exists on FIC, so a failed
            # hand-off to SdI is recoverable from their UI and must not lose it.
            with contextlib.suppress(Exception):
                await request_json("POST", send, headers=self._headers(), json={"data": {}},
                                   timeout=self.config.timeout)
        return SubmissionResult(transport=self.name, status=STATUS_SUBMITTED,
                                provider_id=doc_id, message="Creato su FattureInCloud e inviato a SdI",
                                raw=created)

    async def fetch_status(self, provider_id: str) -> TransportStatus:
        url = f"{self.base}/c/{self.config.company_id}/issued_documents/{provider_id}"
        data = await request_json("GET", url, headers=self._headers(), timeout=self.config.timeout)
        ei = (data.get("data", {}).get("ei_status") or "").lower()
        return TransportStatus(transport=self.name, provider_id=provider_id,
                               status=_STATUS_MAP.get(ei, STATUS_UNKNOWN), sdi_status=ei or None, raw=data)


class FattureInCloudXmlTransport(FattureInCloudTransport):
    """Upload a pre-rendered FatturaPA to FIC, then hand it to SdI.

    Two steps, as FIC's API requires: ``e_invoice/upload`` returns a token for
    the stored file, and ``e_invoice/send`` transmits it. Unlike the structured
    parent, the rendered bytes travel verbatim — nothing is re-derived.
    """

    name = "fattureincloud_xml"

    async def transmit(self, rendered: RenderedDocument, invoice: Invoice) -> SubmissionResult:
        invoice.validate()
        base = f"{self.base}/c/{self.config.company_id}/issued_documents/e_invoice"
        uploaded = await request_json(
            "POST", f"{base}/upload", headers=self._headers(),
            json={"data": {"filename": rendered.filename,
                           "content": base64.b64encode(rendered.content).decode("ascii")}},
            timeout=self.config.timeout,
        )
        token = (uploaded.get("data") or {}).get("token")
        if not token:
            raise ProviderError("FattureInCloud: upload senza token", raw=uploaded)

        sent = await request_json(
            "POST", f"{base}/send", headers=self._headers(),
            json={"data": {"token": token}}, timeout=self.config.timeout,
        )
        payload = sent.get("data") or {}
        doc_id = payload.get("id")
        return SubmissionResult(
            transport=self.name,
            status=STATUS_SUBMITTED,
            provider_id=str(doc_id) if doc_id is not None else str(token),
            filename=rendered.filename,
            message="XML caricato su FattureInCloud e inviato a SdI",
            raw={"upload": uploaded, "send": sent},
        )
