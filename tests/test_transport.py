import asyncio
from datetime import date
from decimal import Decimal

import pytest

from einvoice import Address, Invoice, LineItem, Party
from einvoice.enums import NotificationType
from einvoice.errors import ProviderConfigError
from einvoice.formats import get_renderer
from einvoice.transport import TransportConfig, available_transports, get_transport
from einvoice.transport.aruba import ArubaTransport


def _invoice():
    return Invoice(
        number="2026/0001", date=date(2026, 6, 5),
        seller=Party(name="Trattoria da Mario", vat_number="01234567897",
                     address=Address("Via Roma 1", "20100", "Milano", "MI")),
        buyer=Party(name="ACME Srl", vat_number="09876543217",
                    address=Address("Via Verdi 9", "00100", "Roma", "RM")),
        lines=[LineItem.from_gross("Cena", 1, Decimal("122.00"), 22)],
    )


def test_registry_lists_channels():
    names = available_transports()
    for n in ("file", "fattureincloud", "aruba", "zucchetti", "peppol", "sdi"):
        assert n in names


def test_unknown_transport_raises():
    with pytest.raises(ProviderConfigError):
        get_transport("nope")


def test_file_export_writes(tmp_path):
    inv = _invoice()
    rendered = get_renderer("fatturapa").render(inv)
    transport = get_transport("file", TransportConfig(name="file", extra={"output_dir": str(tmp_path)}))
    res = asyncio.run(transport.transmit(rendered, inv))
    assert res.status == "exported"
    assert (tmp_path / rendered.filename).read_bytes() == rendered.content


def test_network_transports_require_credentials():
    with pytest.raises(ProviderConfigError):
        get_transport("fattureincloud", TransportConfig(name="fattureincloud"))
    with pytest.raises(ProviderConfigError):
        get_transport("aruba", TransportConfig(name="aruba"))
    with pytest.raises(ProviderConfigError):
        get_transport("zucchetti", TransportConfig(name="zucchetti", api_key="x"))  # missing base_url
    with pytest.raises(ProviderConfigError):
        get_transport("peppol", TransportConfig(name="peppol", base_url="https://ap"))  # missing api_key


def test_aruba_parse_notification():
    t = ArubaTransport(TransportConfig(name="aruba", username="u", password="p"))
    n = t.parse_notification({"tipoNotifica": "CONS", "identificativoSdi": "123"})
    assert n is not None
    assert n.type == NotificationType.DELIVERED
    assert n.sdi_id == "123"
