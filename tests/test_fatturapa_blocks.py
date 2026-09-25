"""I blocchi FatturaPA toccati dalla 0.10.0, nei due versi: scrivere e rileggere.

Each test here pins a defect that produced either a file SdI refuses or a
document that changes meaning on the way back in — and none of them made any
existing test fail, because renderer and parser agreed with each other.
"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime
from decimal import Decimal

import pytest

from einvoice import (
    Address,
    AllowanceCharge,
    Carrier,
    DocumentReference,
    DocumentType,
    Freight,
    Invoice,
    LineItem,
    Party,
    TransportBy,
    TransportDetails,
    TransportReason,
    build_cii_xml,
    build_fattura_xml,
    build_ubl_xml,
    parse_invoice,
)
from einvoice.errors import RenderError, ValidationError

SELLER = Party(name="Trattoria da Mario S.r.l.", vat_number="07643520567",
               address=Address("Via Roma 1", "20100", "Milano", "MI"))
BUYER = Party(name="ACME Eventi S.p.A.", vat_number="09876543217", sdi_code="ABCDEFG",
              address=Address("Via Verdi 9", "00100", "Roma", "RM"))


def _invoice(**kw) -> Invoice:
    base: dict = {
        "number": "12/2026", "date": date(2026, 9, 30), "seller": SELLER, "buyer": BUYER,
        "lines": [LineItem("Menu degustazione", Decimal("2"), Decimal("45"), Decimal("10"))],
    }
    base.update(kw)
    return Invoice(**base)


TRANSPORT = TransportDetails(
    reason=TransportReason.REPAIR, reason_text="rientro entro 30 giorni",
    by=TransportBy.CARRIER,
    carrier=Carrier("Trasporti Veloci S.n.c.", vat_number="01234567897",
                    tax_code="01234567897", license_number="MI1234567"),
    means="Furgone AB123CD", packages=6, goods_appearance="Casse termiche",
    gross_weight=Decimal("84.50"), net_weight=Decimal("70.00"), weight_unit="kg",
    start=datetime(2026, 9, 30, 9, 30), incoterm="DAP",
    delivery_address=Address("Piazza del Duomo 1", "20121", "Milano", "MI"))


# ── DatiTrasporto ─────────────────────────────────────────────────────────


def test_the_transport_block_round_trips():
    restored = parse_invoice(build_fattura_xml(_invoice(transport=TRANSPORT))).transport
    assert restored == TRANSPORT


def test_the_declared_transport_losses():
    """FatturaPA has no field for who transports when no carrier is named, nor
    for the freight terms: both come back as defaults, and are documented."""
    sent = dataclasses.replace(TRANSPORT, by=TransportBy.RECIPIENT, carrier=None,
                               freight=Freight.COLLECT)
    restored = parse_invoice(build_fattura_xml(_invoice(transport=sent))).transport
    assert restored == dataclasses.replace(sent, by=TransportBy.SENDER, freight=None)


def test_a_free_text_reason_round_trips_as_other():
    sent = TransportDetails(reason=TransportReason.OTHER, reason_text="Campionatura")
    restored = parse_invoice(build_fattura_xml(_invoice(transport=sent))).transport
    assert (restored.reason, restored.reason_text) == (TransportReason.OTHER, "Campionatura")


@pytest.mark.parametrize("build", [build_ubl_xml, build_cii_xml])
def test_en16931_does_not_carry_the_transport_block(build):
    """A documented loss, pinned so that it stays documented."""
    assert parse_invoice(build(_invoice(transport=TRANSPORT))).transport is None


# ── Causale ───────────────────────────────────────────────────────────────


def test_a_long_causale_is_split_and_rejoined():
    causale = " ".join(f"parola{n}" for n in range(80))
    xml = build_fattura_xml(_invoice(causale=causale))
    assert xml.count(b"<Causale>") > 1
    assert parse_invoice(xml).causale == causale


# ── what arrives from other senders ──────────────────────────────────────


def test_a_percentage_line_discount_is_read_in_cascade():
    """SdI applies percentages in cascade on the unit price. Reading only
    <Importo> made every percentage discount of an incoming invoice zero."""
    xml = build_fattura_xml(_invoice(lines=[
        LineItem("Vino", Decimal("10"), Decimal("20"), Decimal("22"),
                 discounts=[AllowanceCharge(Decimal("20")), AllowanceCharge(Decimal("18"))])]))
    # 20 × 10% = 2.00, then 18.00 × 10% = 1.80: the same amounts as percentages.
    xml = xml.replace(b"<Importo>2.00</Importo>", b"<Percentuale>10.00</Percentuale>")
    xml = xml.replace(b"<Importo>1.80</Importo>", b"<Percentuale>10.00</Percentuale>")
    assert b"<Percentuale>" in xml
    line = parse_invoice(xml).lines[0]
    assert [d.amount for d in line.discounts] == [Decimal("20.00"), Decimal("18.00")]
    assert line.total == Decimal("162.00")


def test_a_percentage_document_discount_is_not_read_as_zero():
    xml = build_fattura_xml(_invoice(allowances_charges=[AllowanceCharge(Decimal("9.00"))]))
    xml = xml.replace(b"<Importo>9.00</Importo>", b"<Percentuale>10.00</Percentuale>")
    reread = parse_invoice(xml)
    assert reread.allowances_charges[0].amount == Decimal("9.00")
    assert reread.total_document() == _invoice(
        allowances_charges=[AllowanceCharge(Decimal("9.00"))]).total_document()


def test_ddt_references_written_by_older_versions_are_still_read():
    """Before 0.10.0 this package wrote DatiDDT like a purchase order; files of
    that shape sit in archives and must still open."""
    legacy = build_fattura_xml(_invoice(references=[
        DocumentReference("ddt", "DDT-9", date(2026, 9, 3))]))
    legacy = legacy.replace(b"<NumeroDDT>DDT-9</NumeroDDT>", b"<IdDocumento>DDT-9</IdDocumento>")
    legacy = legacy.replace(b"<DataDDT>2026-09-03</DataDDT>", b"<Data>2026-09-03</Data>")
    (ref,) = parse_invoice(legacy).references
    assert (ref.kind, ref.doc_id, ref.date) == ("ddt", "DDT-9", date(2026, 9, 3))


def test_reference_line_numbers_come_back():
    invoice = _invoice(lines=[LineItem("A", Decimal("1"), Decimal("1"), Decimal("22")),
                              LineItem("B", Decimal("1"), Decimal("1"), Decimal("22"))],
                       references=[DocumentReference("order", "PO-1", date(2026, 9, 1), [2])])
    assert parse_invoice(build_fattura_xml(invoice)).references[0].line_numbers == [2]


# ── EN 16931 cardinality ─────────────────────────────────────────────────


@pytest.mark.parametrize("build, despatch, contract", [
    (build_ubl_xml, b"<cac:DespatchDocumentReference>", b"<cac:ContractDocumentReference>"),
    (build_cii_xml, b"<ram:DespatchAdviceReferencedDocument>", b"<ram:ContractReferencedDocument>"),
])
def test_one_despatch_and_one_contract_reference_in_en16931(build, despatch, contract):
    """BT-16 and BT-12 are 0..1 (UBL-SR-03, UBL-SR-01): a deferred invoice over
    three DDTs used to write three, which EN 16931 validation refuses."""
    xml = build(_invoice(references=[
        DocumentReference("ddt", f"DDT-{n}", date(2026, 9, n)) for n in (1, 2, 3)
    ] + [DocumentReference("contract", "C-1"), DocumentReference("contract", "C-2")]))
    assert xml.count(despatch) == 1
    assert xml.count(contract) == 1


# ── SdI content checks reproduced before sending ─────────────────────────


@pytest.mark.parametrize("number, message", [
    ("FT-A", "00425"),
    ("A" * 19 + "1" * 2, "20 caratteri"),
    ("Fattura № 3", "ASCII"),
])
def test_the_invoice_number(number, message):
    with pytest.raises(ValidationError, match=message):
        _invoice(number=number).validate()


def test_seller_and_buyer_cannot_be_the_same_taxpayer():
    with pytest.raises(ValidationError, match="00471"):
        _invoice(buyer=dataclasses.replace(BUYER, vat_number=SELLER.vat_number)).validate()
    # A credit note is not on SdI's list, and stays allowed.
    _invoice(document_type=DocumentType.CREDIT_NOTE,
             buyer=dataclasses.replace(BUYER, vat_number=SELLER.vat_number),
             references=[DocumentReference("invoice", "1/2026", date(2026, 9, 1))]).validate()


def test_a_ddt_reference_needs_its_date():
    with pytest.raises(ValidationError, match="DataDDT"):
        _invoice(references=[DocumentReference("ddt", "DDT-1")]).validate()


def test_a_reference_to_a_line_that_does_not_exist_is_refused():
    with pytest.raises(ValidationError, match="la riga 3 non esiste"):
        _invoice(references=[DocumentReference("order", "PO", date(2026, 9, 1), [3])]).validate()


def test_the_renderer_refuses_a_line_sdi_would_recompute_differently():
    """The last line of defence for 00423: recompute on the strings written.
    Seven decimals of unit price over a large quantity drift past a cent."""
    with pytest.raises(RenderError, match="00423"):
        build_fattura_xml(_invoice(lines=[
            LineItem("Viti", Decimal("100000"), Decimal("0.1234567"), Decimal("22"))]))
