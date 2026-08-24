"""Aruba Fatturazione Elettronica transport — uploads the rendered XML (base64).

Flow: signin (username/password → token) → upload → status.
See PROVIDERS/TRANSPORT docs: confirm exact paths against your account.
"""
from __future__ import annotations

import base64

from ..enums import NotificationType
from ..errors import ProviderConfigError, ProviderError
from ..formats.base import RenderedDocument
from ..lifecycle import Notification
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

_PROD, _DEMO = "https://ws.fatturazioneelettronica.aruba.it", "https://demows.fatturazioneelettronica.aruba.it"
_AUTH_PROD, _AUTH_DEMO = "https://auth.fatturazioneelettronica.aruba.it", "https://demoauth.fatturazioneelettronica.aruba.it"

_STATUS_MAP = {"INVI": STATUS_PENDING, "SCAR": STATUS_REJECTED, "CONS": STATUS_ACCEPTED,
               "MANC": STATUS_NOT_DELIVERED, "ACCE": STATUS_ACCEPTED, "RIFI": STATUS_REJECTED}
_NOTIF_MAP = {"CONS": NotificationType.DELIVERED, "SCAR": NotificationType.REJECTED,
              "MANC": NotificationType.NOT_DELIVERED, "ACCE": NotificationType.CUSTOMER_OUTCOME}


class ArubaTransport(Transport):
    name = "aruba"

    def __init__(self, config: TransportConfig):
        super().__init__(config)
        if not (config.username and config.password):
            raise ProviderConfigError("Aruba: 'username' e 'password' richiesti")
        self.base = (config.base_url or (_DEMO if config.sandbox else _PROD)).rstrip("/")
        self.auth_base = (config.extra.get("auth_url") or (_AUTH_DEMO if config.sandbox else _AUTH_PROD)).rstrip("/")
        self._token: str | None = None

    async def _signin(self) -> str:
        if self._token:
            return self._token
        data = await request_json("POST", f"{self.auth_base}/auth/signin",
                                  headers={"Content-Type": "application/json"},
                                  json={"username": self.config.username, "password": self.config.password},
                                  timeout=self.config.timeout)
        token = data.get("access_token") or data.get("value") or data.get("token")
        if not token:
            raise ProviderError("Aruba: signin senza token", raw=data)
        self._token = token
        return token

    def _auth(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def transmit(self, rendered: RenderedDocument, invoice: Invoice) -> SubmissionResult:
        invoice.validate()
        token = await self._signin()
        body = {"dataFile": base64.b64encode(rendered.content).decode("ascii"),
                "nomeFile": rendered.filename,
                "tipoFirma": self.config.extra.get("tipo_firma", "FEA")}
        resp = await request_json("POST", f"{self.base}/services/invoice/upload",
                                  headers=self._auth(token), json=body, timeout=self.config.timeout)
        upload_id = resp.get("uploadFileName") or resp.get("idDocumento") or resp.get("id")
        return SubmissionResult(transport=self.name, status=STATUS_SUBMITTED,
                                provider_id=str(upload_id) if upload_id is not None else None,
                                filename=rendered.filename, message="XML caricato su Aruba", raw=resp)

    async def fetch_status(self, provider_id: str) -> TransportStatus:
        token = await self._signin()
        resp = await request_json("GET", f"{self.base}/services/invoice/out/getInvoice?idDocument={provider_id}",
                                  headers=self._auth(token), timeout=self.config.timeout)
        code = (resp.get("status") or resp.get("statoDocumento") or "").upper()[:4]
        return TransportStatus(transport=self.name, provider_id=provider_id,
                               status=_STATUS_MAP.get(code, STATUS_UNKNOWN),
                               sdi_id=resp.get("identificativoSdi"), sdi_status=code or None, raw=resp)

    def parse_notification(self, payload: dict) -> Notification | None:
        code = (payload.get("tipoNotifica") or payload.get("status") or "").upper()[:4]
        ntype = _NOTIF_MAP.get(code)
        if not ntype:
            return None
        return Notification(type=ntype, positive=code != "RIFI",
                            sdi_id=payload.get("identificativoSdi"),
                            message=payload.get("descrizione"), raw=payload)
