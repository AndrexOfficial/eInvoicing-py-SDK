"""Zucchetti Digital Hub transport — uploads the rendered XML (base64).

Config: ``api_key`` + ``base_url`` (Digital Hub). ``extra['auth_scheme']`` =
``bearer`` (default) | ``apikey``. Confirm paths against your DH API contract.
"""
from __future__ import annotations

import base64

from ..errors import ProviderConfigError
from ..formats.base import RenderedDocument
from ..models import Invoice
from ._http import request_json
from .base import (
    STATUS_ACCEPTED,
    STATUS_NOT_DELIVERED,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
    STATUS_UNKNOWN,
    SubmissionResult,
    Transport,
    TransportConfig,
    TransportStatus,
)

_STATUS_MAP = {"SENT": STATUS_PENDING, "DELIVERED": STATUS_ACCEPTED, "ACCEPTED": STATUS_ACCEPTED,
               "REJECTED": STATUS_REJECTED, "DISCARDED": STATUS_REJECTED, "NOT_DELIVERED": STATUS_NOT_DELIVERED}


class ZucchettiTransport(Transport):
    name = "zucchetti"

    def __init__(self, config: TransportConfig):
        super().__init__(config)
        if not config.api_key:
            raise ProviderConfigError("Zucchetti: 'api_key' richiesto")
        if not config.base_url:
            raise ProviderConfigError("Zucchetti: 'base_url' del Digital Hub richiesto")
        self.base = config.base_url.rstrip("/")

    def _headers(self) -> dict:
        scheme = self.config.extra.get("auth_scheme", "bearer")
        auth = ({"Authorization": f"Bearer {self.config.api_key}"} if scheme == "bearer"
                else {"X-API-Key": self.config.api_key})
        return {**auth, "Content-Type": "application/json", "Accept": "application/json"}

    async def transmit(self, rendered: RenderedDocument, invoice: Invoice) -> SubmissionResult:
        invoice.validate()
        body = {"company": self.config.company_id, "fileName": rendered.filename,
                "fileContent": base64.b64encode(rendered.content).decode("ascii"),
                "documentType": "INVOICE"}
        resp = await request_json("POST", f"{self.base}/invoices/outbound",
                                  headers=self._headers(), json=body, timeout=self.config.timeout)
        doc_id = resp.get("id") or resp.get("documentId") or resp.get("uuid")
        return SubmissionResult(transport=self.name, status=STATUS_SUBMITTED,
                                provider_id=str(doc_id) if doc_id is not None else None,
                                filename=rendered.filename, message="XML caricato sul Digital Hub Zucchetti",
                                raw=resp)

    async def fetch_status(self, provider_id: str) -> TransportStatus:
        resp = await request_json("GET", f"{self.base}/invoices/outbound/{provider_id}",
                                  headers=self._headers(), timeout=self.config.timeout)
        code = (resp.get("status") or resp.get("sdiStatus") or "").upper()
        return TransportStatus(transport=self.name, provider_id=provider_id,
                               status=_STATUS_MAP.get(code, STATUS_UNKNOWN),
                               sdi_id=resp.get("sdiId") or resp.get("identificativoSdi"),
                               sdi_status=code or None, raw=resp)
