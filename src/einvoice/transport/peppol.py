"""PEPPOL Access Point transport (scaffold).

For EU B2G / cross-border you send the UBL (EN 16931) document through a
**certified PEPPOL Access Point**. Operating an AP yourself requires
certification; the common path is a provider that exposes a REST gateway. This
adapter encodes that gateway shape: POST the UBL with the participant
identifiers, then poll the message status.

Config: ``base_url`` (AP gateway) + ``api_key``; ``extra`` may carry
``sender_id`` / ``receiver_scheme`` (Peppol participant ids, e.g. ``9906:IT...``).

Pair it with the ``ubl`` renderer (NOT FatturaPA — PEPPOL carries UBL/CII).
"""
from __future__ import annotations

from ..enums import NotificationType
from ..errors import ProviderConfigError
from ..formats.base import RenderedDocument
from ..lifecycle import Notification
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

_STATUS_MAP = {"sent": STATUS_PENDING, "delivered": STATUS_ACCEPTED,
               "acknowledged": STATUS_ACCEPTED, "failed": STATUS_REJECTED, "rejected": STATUS_REJECTED}


class PeppolTransport(Transport):
    name = "peppol"

    def __init__(self, config: TransportConfig):
        super().__init__(config)
        if not config.base_url:
            raise ProviderConfigError("PEPPOL: 'base_url' dell'Access Point richiesto")
        if not config.api_key:
            raise ProviderConfigError("PEPPOL: 'api_key' richiesto")
        self.base = config.base_url.rstrip("/")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json", "Accept": "application/json"}

    async def transmit(self, rendered: RenderedDocument, invoice: Invoice) -> SubmissionResult:
        import base64
        invoice.validate()
        receiver = invoice.buyer.sdi_code or invoice.buyer.vat_number
        body = {
            "documentTypeId": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2::Invoice",
            "processId": "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0",
            "sender": self.config.extra.get("sender_id"),
            "receiver": f"{self.config.extra.get('receiver_scheme', '9906')}:{receiver}",
            "payload": base64.b64encode(rendered.content).decode("ascii"),
        }
        resp = await request_json("POST", f"{self.base}/messages/outbound",
                                  headers=self._headers(), json=body, timeout=self.config.timeout)
        msg_id = resp.get("messageId") or resp.get("id")
        return SubmissionResult(transport=self.name, status=STATUS_SUBMITTED,
                                provider_id=str(msg_id) if msg_id is not None else None,
                                filename=rendered.filename, message="UBL inviato via PEPPOL Access Point",
                                raw=resp)

    async def fetch_status(self, provider_id: str) -> TransportStatus:
        resp = await request_json("GET", f"{self.base}/messages/outbound/{provider_id}",
                                  headers=self._headers(), timeout=self.config.timeout)
        code = (resp.get("status") or "").lower()
        return TransportStatus(transport=self.name, provider_id=provider_id,
                               status=_STATUS_MAP.get(code, STATUS_UNKNOWN), sdi_status=code or None, raw=resp)

    def parse_notification(self, payload: dict) -> Notification | None:
        code = (payload.get("status") or payload.get("type") or "").lower()
        if code in ("delivered", "acknowledged"):
            return Notification(type=NotificationType.DELIVERED, raw=payload)
        if code in ("failed", "rejected"):
            return Notification(type=NotificationType.REJECTED, positive=False, raw=payload)
        return None
