"""The configurable hub transport used by intermediaries without an adapter."""
import asyncio
from datetime import date
from decimal import Decimal

import pytest

from einvoice import Address, Invoice, LineItem, Party
from einvoice.enums import NotificationType
from einvoice.errors import ProviderConfigError, ValidationError
from einvoice.formats import get_renderer
from einvoice.transport import TransportConfig, get_transport
from einvoice.transport.generic_hub import GenericHubTransport


def _invoice():
    return Invoice(
        number="2026/0007", date=date(2026, 6, 5),
        seller=Party(name="Trattoria da Mario", vat_number="01234567897",
                     address=Address("Via Roma 1", "20100", "Milano", "MI")),
        buyer=Party(name="ACME Srl", vat_number="09876543217",
                    address=Address("Via Verdi 9", "00100", "Roma", "RM")),
        lines=[LineItem.from_gross("Cena", 1, Decimal("122.00"), 22)],
    )


def _hub(**extra):
    return GenericHubTransport(TransportConfig(
        name="infocert", base_url="https://hub.example.it/api/v1", api_key="secret", extra=extra,
    ))


class _Recorder:
    """Stands in for ``request_json`` so the transport is exercised without I/O."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __call__(self, method, url, *, headers=None, json=None, data=None, timeout=30.0):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return self.response


def _patch(monkeypatch, response):
    recorder = _Recorder(response)
    monkeypatch.setattr("einvoice.transport.generic_hub.request_json", recorder)
    return recorder


# ───────────────────────────────────────────────────────────── config ──


def test_registered_aliases_resolve_to_the_hub():
    for name in ("infocert", "notartel", "wolters_kluwer", "hub"):
        transport = get_transport(name, TransportConfig(name=name, base_url="https://x", api_key="k"))
        assert isinstance(transport, GenericHubTransport)
        # The alias keeps its identity, so results and errors name the vendor.
        assert transport.name == name


def test_hub_requires_a_base_url_and_a_credential():
    with pytest.raises(ProviderConfigError):
        get_transport("infocert", TransportConfig(name="infocert", api_key="k"))  # no base_url
    with pytest.raises(ProviderConfigError):
        get_transport("infocert", TransportConfig(name="infocert", base_url="https://x"))  # no credential


# ─────────────────────────────────────────────────────────── transmit ──


def test_transmit_posts_base64_xml_under_the_configured_field(monkeypatch):
    recorder = _patch(monkeypatch, {"id": "DOC-1"})
    inv = _invoice()
    rendered = get_renderer("fatturapa").render(inv)
    hub = _hub(upload_path="/documents", content_field="fileContent", filename_field="fileName")

    result = asyncio.run(hub.transmit(rendered, inv))

    import base64
    body = recorder.calls[0]["json"]
    assert recorder.calls[0]["url"] == "https://hub.example.it/api/v1/documents"
    assert base64.b64decode(body["fileContent"]) == rendered.content
    assert body["fileName"] == rendered.filename
    assert result.status == "submitted"
    assert result.provider_id == "DOC-1"


def test_defaults_cover_a_hub_that_follows_the_common_convention(monkeypatch):
    recorder = _patch(monkeypatch, {"data": {"documentId": "42"}})
    inv = _invoice()
    rendered = get_renderer("fatturapa").render(inv)

    result = asyncio.run(_hub().transmit(rendered, inv))

    assert recorder.calls[0]["url"].endswith("/invoices")
    assert "content" in recorder.calls[0]["json"]
    assert result.provider_id == "42", "the id is found under `data` as well as at the root"


def test_extra_fields_are_merged_into_the_upload_body(monkeypatch):
    recorder = _patch(monkeypatch, {"id": "1"})
    inv = _invoice()
    rendered = get_renderer("fatturapa").render(inv)

    asyncio.run(_hub(extra_fields={"documentType": "FATTURA", "channel": "SDI"}).transmit(rendered, inv))

    assert recorder.calls[0]["json"]["documentType"] == "FATTURA"


@pytest.mark.parametrize(
    ("scheme", "extra", "header", "expected"),
    [
        ("bearer", {}, "Authorization", "Bearer secret"),
        ("apikey", {}, "X-API-Key", "secret"),
        ("apikey", {"auth_header": "X-Auth-Token"}, "X-Auth-Token", "secret"),
    ],
)
def test_auth_schemes(monkeypatch, scheme, extra, header, expected):
    recorder = _patch(monkeypatch, {"id": "1"})
    inv = _invoice()
    rendered = get_renderer("fatturapa").render(inv)

    asyncio.run(_hub(auth_scheme=scheme, **extra).transmit(rendered, inv))

    assert recorder.calls[0]["headers"][header] == expected


def test_basic_auth_uses_username_and_password(monkeypatch):
    recorder = _patch(monkeypatch, {"id": "1"})
    inv = _invoice()
    rendered = get_renderer("fatturapa").render(inv)
    hub = GenericHubTransport(TransportConfig(
        name="notartel", base_url="https://x", username="mario", password="pw",
        extra={"auth_scheme": "basic"},
    ))

    asyncio.run(hub.transmit(rendered, inv))

    import base64
    header = recorder.calls[0]["headers"]["Authorization"]
    assert base64.b64decode(header.removeprefix("Basic ")).decode() == "mario:pw"


def test_transmit_validates_before_sending(monkeypatch):
    """An invalid invoice must never reach the wire."""
    recorder = _patch(monkeypatch, {"id": "1"})
    inv = _invoice()
    rendered = get_renderer("fatturapa").render(inv)
    inv.lines = []  # now invalid

    with pytest.raises(ValidationError):
        asyncio.run(_hub().transmit(rendered, inv))
    assert recorder.calls == []


# ───────────────────────────────────────────────────────────── status ──


@pytest.mark.parametrize(
    ("reported", "normalized"),
    [
        ("consegnato", "accepted"), ("DELIVERED", "accepted"), ("RC", "accepted"),
        ("scartato", "rejected"), ("NS", "rejected"), ("error", "rejected"),
        ("inviato", "pending"), ("processing", "pending"),
        ("mancata_consegna", "not_delivered"), ("MC", "not_delivered"),
        ("qualcosa di ignoto", "unknown"),
    ],
)
def test_status_vocabularies_normalize(monkeypatch, reported, normalized):
    """Hubs report the same SdI outcome in Italian, English, or raw SdI codes."""
    _patch(monkeypatch, {"stato": reported, "identificativoSdi": "SDI-9"})

    status = asyncio.run(_hub().fetch_status("DOC-1"))

    assert status.status == normalized
    assert status.sdi_status == reported, "the vendor's own wording is preserved for support"


def test_status_path_substitutes_the_document_id(monkeypatch):
    recorder = _patch(monkeypatch, {"status": "sent"})

    asyncio.run(_hub(status_path="/documents/{id}/status").fetch_status("ABC"))

    assert recorder.calls[0]["url"] == "https://hub.example.it/api/v1/documents/ABC/status"


def test_notifications_map_to_lifecycle_events():
    hub = _hub()
    delivered = hub.parse_notification({"esito": "RC", "identificativoSdi": "5"})
    rejected = hub.parse_notification({"esito": "scarto", "descrizione": "P.IVA errata"})

    assert delivered is not None and delivered.type == NotificationType.DELIVERED
    assert delivered.positive and delivered.sdi_id == "5"
    assert rejected is not None and rejected.type == NotificationType.REJECTED
    assert not rejected.positive and rejected.message == "P.IVA errata"


def test_unrecognized_notification_is_ignored_not_guessed():
    assert _hub().parse_notification({"esito": "boh"}) is None
    assert _hub().parse_notification({}) is None
