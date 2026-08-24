import asyncio
from datetime import date
from decimal import Decimal

from einvoice import (
    Address,
    EInvoiceEngine,
    FileArchive,
    Invoice,
    InvoiceState,
    LineItem,
    Party,
)
from einvoice.formats import get_renderer
from einvoice.transport import TransportConfig, get_transport


def _invoice():
    return Invoice(
        number="2026/0001", date=date(2026, 6, 5),
        seller=Party(name="Trattoria da Mario", vat_number="01234567897",
                     address=Address("Via Roma 1", "20100", "Milano", "MI")),
        buyer=Party(name="ACME Srl", vat_number="09876543217",
                    address=Address("Via Verdi 9", "00100", "Roma", "RM")),
        lines=[LineItem.from_gross("Cena", 1, Decimal("122.00"), 22)],
    )


def test_engine_fatturapa_file(tmp_path):
    engine = EInvoiceEngine(
        get_renderer("fatturapa"),
        get_transport("file", TransportConfig(name="file", extra={"output_dir": str(tmp_path)})),
    )
    result = asyncio.run(engine.process(_invoice()))
    assert result.rendered.standard == "fatturapa"
    assert result.submission.status == "exported"
    assert result.lifecycle.state == InvoiceState.SENT
    states = [e["state"] for e in result.lifecycle.audit_trail()]
    assert states == ["draft", "validated", "queued", "sent"]
    assert (tmp_path / result.rendered.filename).exists()


def test_engine_ubl_with_archive(tmp_path):
    archive_dir = tmp_path / "archive"
    engine = EInvoiceEngine(
        get_renderer("ubl"),
        get_transport("file", TransportConfig(name="file")),
        archive=FileArchive(str(archive_dir)),
    )
    result = asyncio.run(engine.process(_invoice()))
    assert result.rendered.standard == "ubl"
    assert result.archive_ref is not None
    assert (archive_dir / result.rendered.filename).exists()
