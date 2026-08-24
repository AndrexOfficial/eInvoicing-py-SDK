"""Configurable REST-hub transport for intermediaries without a bespoke adapter.

Italy has a long tail of SdI intermediaries — InfoCert Legalinvoice HUB,
Notartel, Wolters Kluwer Fattura SMART, plus every regional software house —
and they all expose the same shape: authenticate with a token, POST the XML
base64-encoded under some field name, poll a document endpoint for the SdI
outcome. Only the *names* differ.

Hard-coding a module per vendor means shipping code against contracts we cannot
test and cannot keep in sync with each vendor's release cycle. Instead this
transport takes those names from ``config.extra``, so onboarding one is
configuration rather than a release:

    get_transport("infocert", TransportConfig(
        name="infocert",
        base_url="https://hub.legalinvoice.it/api/v1",
        api_key="…",
        extra={"upload_path": "/documents", "content_field": "fileContent"},
    ))

Every knob has a default that matches the most common convention, so a hub that
follows it needs only ``base_url`` and a credential.
"""
from __future__ import annotations

import base64

from ..enums import NotificationType
from ..errors import ProviderConfigError
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

#: Vendor wording → our normalized statuses. Deliberately generous: hubs report
#: the same SdI outcome in Italian, English, or the raw SdI notification code.
_STATUS_MAP = {
    "sent": STATUS_PENDING, "inviato": STATUS_PENDING, "submitted": STATUS_PENDING,
    "pending": STATUS_PENDING, "in_elaborazione": STATUS_PENDING, "processing": STATUS_PENDING,
    "delivered": STATUS_ACCEPTED, "consegnato": STATUS_ACCEPTED, "rc": STATUS_ACCEPTED,
    "accepted": STATUS_ACCEPTED, "accettato": STATUS_ACCEPTED, "ne": STATUS_ACCEPTED,
    "rejected": STATUS_REJECTED, "scartato": STATUS_REJECTED, "scarto": STATUS_REJECTED,
    "ns": STATUS_REJECTED, "discarded": STATUS_REJECTED, "error": STATUS_REJECTED,
    "not_delivered": STATUS_NOT_DELIVERED, "mancata_consegna": STATUS_NOT_DELIVERED,
    "mc": STATUS_NOT_DELIVERED,
}

_NOTIFICATION_MAP = {
    STATUS_ACCEPTED: NotificationType.DELIVERED,
    STATUS_REJECTED: NotificationType.REJECTED,
    STATUS_NOT_DELIVERED: NotificationType.NOT_DELIVERED,
}

#: First match wins when reading an id or a status out of a hub's response.
_ID_FIELDS = ("id", "documentId", "idDocumento", "uuid", "identificativo", "token")
_STATUS_FIELDS = ("status", "stato", "statoDocumento", "sdiStatus", "esito", "notificationType")
_SDI_ID_FIELDS = ("sdiId", "identificativoSdi", "idSdi", "sdi_identifier")


def _first(payload: dict, fields: tuple[str, ...]) -> str | None:
    """First non-empty value among ``fields``, searched one level deep.

    Hubs disagree on whether the document sits at the root or under ``data`` /
    ``result``, so both are checked before giving up.
    """
    for scope in (payload, payload.get("data"), payload.get("result")):
        if not isinstance(scope, dict):
            continue
        for field in fields:
            value = scope.get(field)
            if value not in (None, ""):
                return str(value)
    return None


class GenericHubTransport(Transport):
    """REST intermediary driven entirely by configuration.

    ``config.extra`` keys (all optional):

    ==================  ==========================  =====================================
    key                 default                     meaning
    ==================  ==========================  =====================================
    ``upload_path``     ``/invoices``               path appended to ``base_url`` to POST
    ``status_path``     ``/invoices/{id}``          status path; ``{id}`` is substituted
    ``content_field``   ``content``                 body field holding the base64 XML
    ``filename_field``  ``filename``                body field holding the file name
    ``auth_scheme``     ``bearer``                  ``bearer`` | ``apikey`` | ``basic``
    ``auth_header``     ``X-API-Key``               header name when scheme is ``apikey``
    ``extra_fields``    ``{}``                      merged into the upload body verbatim
    ==================  ==========================  =====================================
    """

    name = "hub"

    def __init__(self, config: TransportConfig):
        super().__init__(config)
        if not config.base_url:
            raise ProviderConfigError(
                f"{config.name or self.name}: 'base_url' del hub richiesto — "
                "questo transport è configurabile, non ha endpoint predefiniti"
            )
        if not (config.api_key or config.username):
            raise ProviderConfigError(
                f"{config.name or self.name}: serve 'api_key' oppure 'username' + 'password'"
            )
        self.name = config.name or self.name
        self.base = config.base_url.rstrip("/")

    def _headers(self) -> dict:
        extra = self.config.extra
        scheme = str(extra.get("auth_scheme", "bearer")).lower()
        if scheme == "apikey":
            auth = {str(extra.get("auth_header", "X-API-Key")): self.config.api_key or ""}
        elif scheme == "basic":
            raw = f"{self.config.username or ''}:{self.config.password or ''}".encode()
            auth = {"Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}"}
        else:
            auth = {"Authorization": f"Bearer {self.config.api_key or ''}"}
        return {**auth, "Content-Type": "application/json", "Accept": "application/json"}

    async def transmit(self, rendered: RenderedDocument, invoice: Invoice) -> SubmissionResult:
        invoice.validate()
        extra = self.config.extra
        body = {
            str(extra.get("content_field", "content")): base64.b64encode(rendered.content).decode("ascii"),
            str(extra.get("filename_field", "filename")): rendered.filename,
        }
        if self.config.company_id:
            body["companyId"] = self.config.company_id
        merged = extra.get("extra_fields")
        if isinstance(merged, dict):
            body.update(merged)

        url = f"{self.base}{extra.get('upload_path', '/invoices')}"
        resp = await request_json("POST", url, headers=self._headers(), json=body,
                                  timeout=self.config.timeout)
        return SubmissionResult(
            transport=self.name,
            status=STATUS_SUBMITTED,
            provider_id=_first(resp, _ID_FIELDS),
            sdi_id=_first(resp, _SDI_ID_FIELDS),
            filename=rendered.filename,
            message=f"XML caricato su {self.name}",
            raw=resp,
        )

    async def fetch_status(self, provider_id: str) -> TransportStatus:
        path = str(self.config.extra.get("status_path", "/invoices/{id}")).replace("{id}", provider_id)
        resp = await request_json("GET", f"{self.base}{path}", headers=self._headers(),
                                  timeout=self.config.timeout)
        raw_status = _first(resp, _STATUS_FIELDS) or ""
        return TransportStatus(
            transport=self.name,
            provider_id=provider_id,
            status=_STATUS_MAP.get(raw_status.strip().lower(), STATUS_UNKNOWN),
            sdi_id=_first(resp, _SDI_ID_FIELDS),
            sdi_status=raw_status or None,
            raw=resp,
        )

    def parse_notification(self, payload: dict) -> Notification | None:
        raw_status = (_first(payload, _STATUS_FIELDS) or "").strip().lower()
        normalized = _STATUS_MAP.get(raw_status)
        ntype = _NOTIFICATION_MAP.get(normalized) if normalized else None
        if ntype is None:
            return None
        return Notification(
            type=ntype,
            positive=normalized != STATUS_REJECTED,
            sdi_id=_first(payload, _SDI_ID_FIELDS),
            message=_first(payload, ("message", "descrizione", "descrizioneEsito")),
            raw=payload,
        )
