"""Ogni FatturaPA che il pacchetto scrive deve passare lo schema ufficiale.

Il renderer era provato solo contro il proprio parser. Quando sbagliavano
entrambi nello stesso modo — ``DatiDDT`` scritto come un ordine d'acquisto,
con ``IdDocumento``/``Data`` invece di ``NumeroDDT``/``DataDDT`` — ogni test
passava, il round-trip era perfetto, e SdI avrebbe scartato il file con
``00200 — file non conforme al formato``. Lo schema è l'unico giudice che non
condivide i nostri errori.

Gli schemi stanno in ``tests/schemas/fatturapa`` (vedi il README lì): quello
FatturaPA importa la firma da un URL, e l'import viene riscritto in memoria
verso la copia locale — nessuna rete, file identici agli originali.

Niente ``importorskip``: lxml è fra le dipendenze di sviluppo, e una guardia
che salta quando manca è una guardia spenta che sembra accesa.
"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from einvoice import (
    Address,
    AllowanceCharge,
    BankAccount,
    Carrier,
    DeliveryLine,
    DeliveryNote,
    DocumentReference,
    DocumentType,
    Invoice,
    LineItem,
    Party,
    Payment,
    PaymentMeans,
    Quote,
    TransmissionFormat,
    TransportBy,
    TransportDetails,
    TransportReason,
    VatNature,
    build_fattura_xml,
    credit_note_for,
    deferred_invoice,
)
from test_fatturapa import _full

SCHEMAS = Path(__file__).parent / "schemas" / "fatturapa"


def _schema() -> etree.XMLSchema:
    source = (SCHEMAS / "Schema_VFPR12_v1.2.3.xsd").read_text(encoding="utf-8-sig")
    source = source.replace(
        "http://www.w3.org/TR/2002/REC-xmldsig-core-20020212/xmldsig-core-schema.xsd",
        (SCHEMAS / "xmldsig-core-schema.xsd").as_uri(),
    )
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
    return etree.XMLSchema(etree.fromstring(source.encode("utf-8"), parser,
                                            base_url=SCHEMAS.as_uri() + "/"))


SCHEMA = _schema()


def assert_valid(invoice: Invoice) -> bytes:
    xml = build_fattura_xml(invoice)
    if not SCHEMA.validate(etree.fromstring(xml)):
        errors = "\n".join(f"  riga {e.line}: {e.message}" for e in SCHEMA.error_log)
        pytest.fail(f"FatturaPA non conforme allo schema 1.2.3:\n{errors}")
    return xml


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


# ── the fixture the package has always used, and every block it knows ────


def test_the_full_invoice_is_valid():
    assert_valid(_full())


SIMPLIFIED = {"TD07", "TD08", "TD09"}


@pytest.mark.parametrize("doc_type", [t for t in DocumentType if t.value not in SIMPLIFIED])
def test_every_document_type_is_valid(doc_type):
    lines = [LineItem("Voce", Decimal("1"), Decimal("100"), Decimal("22"))]
    refs = [DocumentReference("invoice", "7/2026", date(2026, 9, 1))] \
        if doc_type.corrects_an_earlier_document else []
    assert_valid(_invoice(document_type=doc_type, lines=lines, references=refs))


@pytest.mark.parametrize("code", sorted(SIMPLIFIED))
def test_simplified_types_are_refused_rather_than_written_invalid(code):
    """TD07–TD09 belong to the simplified format (FSM10): the ordinary schema
    does not list them, and writing one produced a file SdI refuses."""
    from einvoice.errors import RenderError

    lines = [LineItem("Voce", Decimal("1"), Decimal("100"), Decimal("22"))]
    refs = [DocumentReference("invoice", "7/2026", date(2026, 9, 1))]
    with pytest.raises(RenderError, match="semplificata"):
        build_fattura_xml(_invoice(document_type=DocumentType(code), lines=lines,
                                   references=refs))


@pytest.mark.parametrize("nature", list(VatNature))
def test_every_vat_nature_is_valid(nature):
    assert_valid(_invoice(lines=[
        LineItem("Esente", Decimal("1"), Decimal("50"), Decimal("0"), nature=nature)]))


# ── the defects this test file was written to catch ──────────────────────


def test_ddt_references_have_the_ddt_shape():
    xml = assert_valid(_invoice(
        document_type=DocumentType.DEFERRED_INVOICE,
        lines=[LineItem("A", Decimal("1"), Decimal("10"), Decimal("22")),
               LineItem("B", Decimal("1"), Decimal("10"), Decimal("22"))],
        references=[DocumentReference("ddt", "DDT-1", date(2026, 9, 3), [1]),
                    DocumentReference("ddt", "DDT-2", date(2026, 9, 9), [2])]))
    assert b"<NumeroDDT>DDT-1</NumeroDDT>" in xml
    assert b"<DataDDT>2026-09-03</DataDDT>" in xml
    assert b"IdDocumento>DDT" not in xml


def test_references_follow_the_schema_order_whatever_the_callers_order():
    """A credit note listing the invoice before the purchase order was a file
    SdI refuses: ``DatiGenerali`` is an XSD sequence."""
    refs = [DocumentReference("ddt", "D-1", date(2026, 9, 2)),
            DocumentReference("invoice", "7/2026", date(2026, 9, 1)),
            DocumentReference("contract", "C-1"),
            DocumentReference("order", "PO-1", date(2026, 8, 1))]
    for ordering in (refs, list(reversed(refs)), refs[1:] + refs[:1]):
        assert_valid(_invoice(document_type=DocumentType.CREDIT_NOTE, references=ordering))


def test_a_long_causale_is_split_not_rejected():
    xml = assert_valid(_invoice(causale="Evento aziendale del 25 settembre " * 20))
    assert xml.count(b"<Causale>") >= 3


def test_typographic_text_is_rewritten_into_latin1():
    """«Pizza d’autore» — a curly apostrophe nobody types on purpose — used to
    make the whole file non-conforming."""
    xml = assert_valid(_invoice(
        causale="Menù “degustazione” – serata … 50 € 🍷",
        lines=[LineItem("Pizza d’autore — gluten free ½", Decimal("1"), Decimal("12"),
                        Decimal("10"))],
        buyer=dataclasses.replace(BUYER, name="Łódź Café Kft. ő"),
    ))
    assert "Pizza d'autore - gluten free ½".encode() in xml
    assert b"50 EUR" in xml
    # ó is Latin-1 and stays; Ł and ź and ő have no Latin-1 form and fold.
    assert "Lódz Café Kft. o".encode() in xml


def test_line_discounts_are_per_unit_and_pass_sdi_arithmetic():
    """SdI check 00423: PrezzoTotale = (PrezzoUnitario − sconti) × Quantita."""
    xml = assert_valid(_invoice(lines=[
        LineItem("Vino", Decimal("12"), Decimal("38"), Decimal("22"),
                 discounts=[AllowanceCharge(Decimal("24.00")), AllowanceCharge(Decimal("1.00"))]),
        LineItem("Coperto", Decimal("3"), Decimal("2.50"), Decimal("10"),
                 discounts=[AllowanceCharge(Decimal("1.00"), is_charge=True)]),
    ]))
    assert b"<Importo>2.00</Importo>" in xml           # 24.00 over 12 units
    assert b"<PrezzoTotale>431.00</PrezzoTotale>" in xml


def test_a_returned_item_is_a_positive_quantity_at_a_negative_price():
    xml = assert_valid(_invoice(lines=[
        LineItem("Vendita", Decimal("10"), Decimal("100"), Decimal("22")),
        LineItem("Reso", Decimal("-2"), Decimal("100"), Decimal("22")),
    ]))
    assert b"<Quantita>-" not in xml
    assert b"<PrezzoUnitario>-100.000000</PrezzoUnitario>" in xml


@pytest.mark.parametrize("quantity", ["1.125", "0.375", "12.12345678", "1000"])
def test_quantities_keep_their_decimals(quantity):
    xml = assert_valid(_invoice(lines=[
        LineItem("Formaggio", Decimal(quantity), Decimal("19.90"), Decimal("4"),
                 unit_of_measure="kg")]))
    assert f"<Quantita>{Decimal(quantity):f}".encode()[:18] in xml


def test_iban_bic_and_codice_fiscale_are_normalised():
    xml = assert_valid(_invoice(
        buyer=dataclasses.replace(BUYER, tax_code="rssmra80a01h501u "),
        payments=[Payment(PaymentMeans.BANK_TRANSFER, due_date=date(2026, 10, 30),
                          account=BankAccount("it60 x054 2811 1010 0000 0123 456",
                                              "Banca X", "Trattoria", "bcit it mm"))]))
    assert b"<IBAN>IT60X0542811101000000123456</IBAN>" in xml
    assert b"<CodiceFiscale>RSSMRA80A01H501U</CodiceFiscale>" in xml


def test_the_rea_office_is_the_province():
    xml = assert_valid(_invoice(seller=dataclasses.replace(
        SELLER, registration_number="mi 1234567", email="info@damario.it")))
    assert b"<Ufficio>MI</Ufficio>" in xml


def test_a_rea_that_cannot_be_read_is_an_error_not_an_invalid_file():
    from einvoice.errors import ValidationError

    with pytest.raises(ValidationError, match="REA"):
        build_fattura_xml(_invoice(seller=dataclasses.replace(SELLER, registration_number="1234567")))


def test_the_fattura_accompagnatoria_carries_its_transport_block():
    xml = assert_valid(_invoice(transport=TransportDetails(
        reason=TransportReason.SALE, reason_text="merce deperibile", by=TransportBy.CARRIER,
        carrier=Carrier("Trasporti Veloci S.n.c.", vat_number="01234567897",
                        tax_code="01234567897", license_number="MI1234567"),
        means="Furgone AB123CD", packages=6, goods_appearance="Casse termiche",
        gross_weight=Decimal("84.5"), net_weight=Decimal("70"),
        start=datetime(2026, 9, 30, 9, 30), incoterm="DAP",
        delivery_address=Address("Piazza del Duomo 1", "20121", "Milano", "MI"))))
    assert b"<CausaleTrasporto>Vendita: merce deperibile</CausaleTrasporto>" in xml
    assert b"<PesoLordo>84.50</PesoLordo>" in xml


def test_public_administration_and_foreign_buyers_are_valid():
    assert_valid(_invoice(transmission_format=TransmissionFormat.PA, recipient_code="UFABCD",
                          buyer=dataclasses.replace(BUYER, sdi_code=None)))
    foreign = Party(name="Müller GmbH", vat_number="DE136695976", country_code="DE",
                    address=Address("Hauptstraße 5", "10115", "Berlin", country="DE"))
    assert_valid(_invoice(buyer=foreign, lines=[
        LineItem("Servizio", Decimal("1"), Decimal("100"), Decimal("0"),
                 nature=VatNature.NOT_SUBJECT_ART7)]))


# ── everything the new document flows produce ────────────────────────────


def _quote() -> Quote:
    return Quote("PR-3/2026", date(2026, 9, 1), SELLER, BUYER, [
        LineItem("Menu evento", Decimal("40"), Decimal("45"), Decimal("10")),
        LineItem("Barolo DOCG", Decimal("12"), Decimal("38"), Decimal("22"),
                 discounts=[AllowanceCharge(Decimal("24"))]),
    ], valid_until=date(2026, 9, 30))


def test_an_accepted_quote_becomes_a_valid_invoice():
    assert_valid(_quote().to_invoice(number="13/2026", date=date(2026, 9, 10)))


def test_a_proforma_becomes_a_valid_invoice():
    proforma = _quote().to_proforma(number="PF-7/2026", date=date(2026, 9, 5))
    assert_valid(proforma.to_invoice(number="14/2026", date=date(2026, 9, 12)))


def test_a_deferred_invoice_over_several_ddts_is_valid():
    notes = [
        DeliveryNote(f"DDT-{n}/2026", date(2026, 9, day), SELLER, BUYER,
                     [DeliveryLine("Vassoi", Decimal(n), unit_price=Decimal("20"),
                                   vat_rate=Decimal("10"))],
                     references=[DocumentReference("order", "PO-9", date(2026, 8, 30))])
        for n, day in ((1, 3), (2, 10), (3, 17))
    ]
    xml = assert_valid(deferred_invoice(notes, number="15/2026", date=date(2026, 9, 30)))
    assert xml.count(b"<DatiDDT>") == 3
    assert xml.count(b"<DatiOrdineAcquisto>") == 1


def test_every_kind_of_credit_note_is_valid():
    invoice = _quote().to_invoice(number="13/2026", date=date(2026, 9, 10))
    assert_valid(credit_note_for(invoice, number="NC-1/2026", date=date(2026, 9, 20)))
    assert_valid(credit_note_for(invoice, number="NC-2/2026", date=date(2026, 9, 20),
                                 lines={1: Decimal("2")}))
    assert_valid(credit_note_for(invoice, number="NC-3/2026", date=date(2026, 9, 20),
                                 amount=Decimal("150.01")))
