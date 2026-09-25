"""Preventivo, pro forma, DDT — e le due strade verso la fattura e ritorno.

Le proprietà che contano, più che le singole funzioni:

* un documento commerciale non raggiunge mai un renderer fiscale;
* una conversione non cambia i soldi (stesso codice di calcolo, stessi totali);
* una conversione non lascia i due documenti legati per riferimento;
* la fattura differita cita ogni DDT come lo schema vuole, e rifiuta di mescolare
  clienti;
* la nota di credito rispetta le aliquote della fattura che storna.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from einvoice import (
    Address,
    AllowanceCharge,
    Carrier,
    DeliveryLine,
    DeliveryNote,
    DocumentKind,
    DocumentReference,
    DocumentStatus,
    DocumentType,
    Freight,
    Invoice,
    LineItem,
    Party,
    ProForma,
    Quote,
    SocialSecurityFund,
    TransportBy,
    TransportDetails,
    TransportReason,
    VatNature,
    WithholdingTax,
    can_transition,
    credit_note_for,
    deferred_invoice,
    document_from_dict,
    document_from_json,
    document_kind,
    document_to_dict,
    document_to_json,
    initial_status,
    next_statuses,
    parse_invoice,
    transition,
)
from einvoice.errors import IllegalTransition, RenderError, ValidationError
from einvoice.formats import build_cii_xml, build_fattura_xml, build_ubl_xml, get_renderer

SELLER = Party(name="Trattoria da Mario S.r.l.", vat_number="07643520567",
               address=Address("Via Roma 1", "20100", "Milano", "MI"))
BUYER = Party(name="ACME Eventi S.p.A.", vat_number="09876543217", sdi_code="ABCDEFG",
              address=Address("Via Verdi 9", "00100", "Roma", "RM"))
OTHER_BUYER = Party(name="Beta Srl", vat_number="12345678903", sdi_code="ABCDEFG",
                    address=Address("Via Po 2", "10100", "Torino", "TO"))


def _lines() -> list[LineItem]:
    return [
        LineItem("Menu evento", Decimal("40"), Decimal("45"), Decimal("10")),
        LineItem("Barolo DOCG", Decimal("12"), Decimal("38"), Decimal("22"),
                 discounts=[AllowanceCharge(Decimal("24"))]),
        LineItem("Servizio camerieri", Decimal("8"), Decimal("30"), Decimal("22"),
                 unit_of_measure="h"),
    ]


def _quote(**kw) -> Quote:
    base: dict = {"number": "PR-3/2026", "date": date(2026, 9, 1), "seller": SELLER,
                  "buyer": BUYER, "lines": _lines(), "valid_until": date(2026, 9, 30)}
    base.update(kw)
    return Quote(**base)


def _ddt(number: str, day: date, qty: str = "2", buyer: Party = BUYER, priced: bool = True,
         **kw) -> DeliveryNote:
    line = DeliveryLine("Vassoi finger food", Decimal(qty), unit_of_measure="pz",
                        unit_price=Decimal("20") if priced else None,
                        vat_rate=Decimal("10") if priced else None)
    return DeliveryNote(number, day, SELLER, buyer, [line], **kw)


# ── the kinds and the renderers ──────────────────────────────────────────


@pytest.mark.parametrize("build", [build_fattura_xml, build_ubl_xml, build_cii_xml])
def test_no_commercial_document_reaches_a_fiscal_renderer(build):
    """A pro forma transmitted by mistake IS an invoice. The type decides."""
    quote = _quote()
    proforma = quote.to_proforma(number="PF-1/2026", date=date(2026, 9, 2))
    note = quote.to_delivery_note(number="DDT-1/2026", date=date(2026, 9, 3))
    for doc in (quote, proforma, note):
        with pytest.raises(RenderError, match=doc.kind.value):
            build(doc)


def test_the_registered_renderers_refuse_them_too():
    proforma = _quote().to_proforma(number="PF-1/2026", date=date(2026, 9, 2))
    for standard in ("fatturapa", "ubl", "cii", "peppol", "facturx"):
        with pytest.raises(RenderError):
            get_renderer(standard).render(proforma)


def test_document_kind_names_every_document():
    invoice = _quote().to_invoice(number="1/2026", date=date(2026, 9, 5))
    assert document_kind(invoice) is DocumentKind.INVOICE
    assert document_kind(credit_note_for(invoice, number="NC-1/2026",
                                         date=date(2026, 9, 6))) is DocumentKind.CREDIT_NOTE
    assert document_kind(_quote()) is DocumentKind.QUOTE
    assert document_kind(_ddt("DDT-1", date(2026, 9, 1))) is DocumentKind.DELIVERY_NOTE
    assert DocumentKind.INVOICE.is_fiscal and not DocumentKind.PROFORMA.is_fiscal


# ── conversions keep the money and cut the ties ──────────────────────────


def test_a_quote_totals_exactly_like_the_invoice_it_becomes():
    quote = _quote(funds=[SocialSecurityFund("TC22", Decimal("4"), Decimal("10.00"),
                                             vat_rate=Decimal("22"))],
                   withholdings=[WithholdingTax(Decimal("20.00"), Decimal("20"))],
                   allowances_charges=[AllowanceCharge(Decimal("5"), vat_rate=Decimal("10"))])
    invoice = quote.to_invoice(number="13/2026", date=date(2026, 9, 10))
    proforma = quote.to_proforma(number="PF-7/2026", date=date(2026, 9, 5))

    for doc in (quote, proforma):
        assert doc.vat_summary() == invoice.vat_summary()
        assert doc.total_document() == invoice.total_document()
        assert doc.total_payable() == invoice.total_payable()


def test_a_conversion_is_a_copy_not_a_second_name():
    quote = _quote()
    invoice = quote.to_invoice(number="13/2026", date=date(2026, 9, 10))
    invoice.lines[0].quantity = Decimal("1")
    invoice.buyer.name = "Altro"
    assert quote.lines[0].quantity == Decimal("40")
    assert quote.buyer.name == "ACME Eventi S.p.A."


def test_the_invoice_names_the_document_it_came_from():
    invoice = _quote().to_invoice(number="13/2026", date=date(2026, 9, 10))
    assert invoice.number == "13/2026" and invoice.date == date(2026, 9, 10)
    assert "PR-3/2026" in invoice.causale and "01/09/2026" in invoice.causale

    quiet = _quote().to_invoice(number="13/2026", date=date(2026, 9, 10), mention_source=False)
    assert quiet.causale is None


def test_a_proforma_passes_its_causale_and_type_to_the_invoice():
    proforma = ProForma("PF-2/2026", date(2026, 9, 5), SELLER, BUYER, _lines(),
                        causale="Parcella settembre", document_type=DocumentType.FEE)
    invoice = proforma.to_invoice(number="20/2026", date=date(2026, 9, 20))
    assert invoice.document_type is DocumentType.FEE
    assert invoice.causale.startswith("Parcella settembre — ")
    invoice.validate()


def test_overrides_reach_the_invoice():
    invoice = _quote().to_invoice(number="13/2026", date=date(2026, 9, 10),
                                  recipient_code="XYZ1234", causale="Evento")
    assert invoice.recipient_code == "XYZ1234"
    assert invoice.causale.startswith("Evento — ")


def test_a_quote_to_a_prospect_is_valid_but_its_invoice_is_not():
    """An offer may go to someone whose tax data nobody has yet; the invoice
    may not. The place to say so is the invoice."""
    prospect = Party(name="Mario Rossi")
    quote = _quote(buyer=prospect)
    quote.validate()
    with pytest.raises(ValidationError):
        quote.to_invoice(number="13/2026", date=date(2026, 9, 10)).validate()


def test_quote_validation():
    with pytest.raises(ValidationError, match="validità"):
        _quote(valid_until=date(2026, 8, 1)).validate()
    with pytest.raises(ValidationError, match="riga"):
        _quote(lines=[]).validate()
    with pytest.raises(ValidationError, match="numero"):
        _quote(number=" ").validate()
    with pytest.raises(ValidationError):
        _quote(seller=Party(name="Senza dati")).validate()


def test_the_last_day_of_validity_is_valid():
    quote = _quote()
    assert not quote.is_expired(date(2026, 9, 30))
    assert quote.is_expired(date(2026, 10, 1))
    assert not _quote(valid_until=None).is_expired(date(2030, 1, 1))


def test_a_quote_checks_its_rates_like_an_invoice():
    from einvoice import ProductCategory

    quote = _quote(lines=[LineItem("Libro", Decimal("1"), Decimal("10"), Decimal("22"),
                                   category=ProductCategory.BOOKS)])
    assert "rate_category" in {a.code for a in quote.check()}


def test_a_proforma_cannot_be_a_credit_note():
    with pytest.raises(ValidationError):
        ProForma("PF-1", date(2026, 9, 1), SELLER, BUYER, _lines(),
                 document_type=DocumentType.CREDIT_NOTE).validate()


# ── delivery notes ────────────────────────────────────────────────────────


def test_a_quote_ships_with_its_prices_and_discounts():
    note = _quote().to_delivery_note(number="DDT-12/2026", date=date(2026, 9, 20))
    assert note.priced
    assert note.lines[1].discounts[0].amount == Decimal("24")
    note.validate()

    bare = _quote().to_delivery_note(number="DDT-13/2026", date=date(2026, 9, 20),
                                     include_prices=False)
    assert not bare.priced and not bare.lines[1].discounts


def test_delivery_note_validation():
    with pytest.raises(ValidationError, match="20 caratteri"):
        _ddt("D" * 21, date(2026, 9, 1)).validate()
    with pytest.raises(ValidationError, match="reso"):
        _ddt("DDT-1", date(2026, 9, 1), qty="-1").validate()
    with pytest.raises(ValidationError, match="insieme"):
        DeliveryNote("DDT-1", date(2026, 9, 1), SELLER, BUYER,
                     [DeliveryLine("X", Decimal("1"), unit_price=Decimal("2"))]).validate()
    with pytest.raises(ValidationError, match="indirizzo"):
        DeliveryNote("DDT-1", date(2026, 9, 1), SELLER, Party(name="Mario Rossi"),
                     [DeliveryLine("X", Decimal("1"))]).validate()
    # A private recipient needs a name and a place, not a VAT number.
    DeliveryNote("DDT-1", date(2026, 9, 1), SELLER, Party(name="Mario Rossi"),
                 [DeliveryLine("X", Decimal("1"))],
                 transport=TransportDetails(delivery_address=Address(
                     "Via Po 1", "10100", "Torino", "TO"))).validate()


@pytest.mark.parametrize("transport, message", [
    (TransportDetails(packages=0), "colli"),
    (TransportDetails(packages=10000), "colli"),
    (TransportDetails(gross_weight=Decimal("10000")), "peso"),
    (TransportDetails(gross_weight=Decimal("5"), net_weight=Decimal("6")), "netto"),
    (TransportDetails(incoterm="dap"), "Incoterms"),
    (TransportDetails(by=TransportBy.CARRIER), "vettore"),
    (TransportDetails(reason=TransportReason.OTHER), "altro"),
])
def test_transport_validation(transport, message):
    with pytest.raises(ValidationError, match=message):
        _ddt("DDT-1", date(2026, 9, 1), transport=transport).validate()


def test_delivery_note_advisories():
    late = _ddt("DDT-1", date(2026, 9, 10), transport=TransportDetails(
        start=datetime(2026, 9, 9, 8, 0), by=TransportBy.CARRIER,
        carrier=Carrier("Padroncino")))
    codes = {a.code for a in late.check()}
    assert {"delivery_note_after_start", "carrier_no_vat"} <= codes
    private = DeliveryNote("DDT-2", date(2026, 9, 1), SELLER,
                           Party(name="Mario Rossi", address=BUYER.address),
                           [DeliveryLine("X", Decimal("1"))])
    assert "delivery_note_buyer_id" in {a.code for a in private.check()}
    assert _ddt("DDT-3", date(2026, 9, 1)).check() == []


# ── the deferred invoice ─────────────────────────────────────────────────


def test_one_ddt_is_cited_whole():
    invoice = _ddt("DDT-1/2026", date(2026, 9, 3)).to_invoice(
        number="15/2026", date=date(2026, 9, 30))
    assert invoice.document_type is DocumentType.DEFERRED_INVOICE
    (ref,) = invoice.references
    assert (ref.kind, ref.doc_id, ref.date, ref.line_numbers) == \
        ("ddt", "DDT-1/2026", date(2026, 9, 3), [])
    invoice.validate()
    assert invoice.check() == []


def test_several_ddts_are_cited_line_by_line_in_date_order():
    notes = [_ddt("DDT-3", date(2026, 9, 17), "1"),
             _ddt("DDT-1", date(2026, 9, 3), "2", references=[
                 DocumentReference("order", "PO-9", date(2026, 8, 30))]),
             DeliveryNote("DDT-2", date(2026, 9, 10), SELLER, BUYER, [
                 DeliveryLine("Vassoi", Decimal("1"), unit_price=Decimal("20"), vat_rate=Decimal("10")),
                 DeliveryLine("Bibite", Decimal("6"), unit_price=Decimal("2"), vat_rate=Decimal("22")),
             ])]
    invoice = deferred_invoice(notes, number="15/2026", date=date(2026, 9, 30))

    ddts = [(r.doc_id, r.line_numbers) for r in invoice.references if r.kind == "ddt"]
    assert ddts == [("DDT-1", [1]), ("DDT-2", [2, 3]), ("DDT-3", [4])]
    assert [r.doc_id for r in invoice.references if r.kind == "order"] == ["PO-9"]
    assert len(invoice.lines) == 4
    invoice.validate()


def test_the_deferred_invoice_round_trips_its_ddt_citations():
    notes = [_ddt("DDT-1", date(2026, 9, 3)), _ddt("DDT-2", date(2026, 9, 10))]
    invoice = deferred_invoice(notes, number="15/2026", date=date(2026, 9, 30))
    reread = parse_invoice(build_fattura_xml(invoice))
    assert [(r.doc_id, r.date, r.line_numbers) for r in reread.references] == [
        ("DDT-1", date(2026, 9, 3), [1]), ("DDT-2", date(2026, 9, 10), [2])]


def test_different_customers_are_not_one_deferred_invoice():
    with pytest.raises(ValidationError, match="cessionari diversi"):
        deferred_invoice([_ddt("DDT-1", date(2026, 9, 3)),
                          _ddt("DDT-2", date(2026, 9, 4), buyer=OTHER_BUYER)],
                         number="15/2026", date=date(2026, 9, 30))


def test_the_same_ddt_twice_is_refused():
    with pytest.raises(ValidationError, match="due volte"):
        deferred_invoice([_ddt("DDT-1", date(2026, 9, 3)), _ddt("DDT-1", date(2026, 9, 3))],
                         number="15/2026", date=date(2026, 9, 30))


def test_unpriced_lines_are_named_or_priced_by_the_caller():
    bare = _ddt("DDT-1", date(2026, 9, 3), priced=False)
    with pytest.raises(ValidationError, match="Vassoi finger food"):
        deferred_invoice([bare], number="15/2026", date=date(2026, 9, 30))

    invoice = deferred_invoice([bare], number="15/2026", date=date(2026, 9, 30),
                               pricing=lambda line: (Decimal("18"), Decimal("10")))
    assert invoice.lines[0].unit_price == Decimal("18")
    exempt = deferred_invoice(
        [bare], number="16/2026", date=date(2026, 9, 30),
        pricing=lambda line: (Decimal("18"), Decimal("0"), VatNature.EXEMPT))
    assert exempt.lines[0].nature is VatNature.EXEMPT


def test_the_deferred_invoice_deadline_is_checked():
    """Art. 21 c.4 lett. a: one invoice per month of deliveries, by the 15th of
    the next month. SdI checks neither half."""
    on_time = deferred_invoice([_ddt("DDT-1", date(2026, 9, 3))], number="15/2026",
                               date=date(2026, 10, 15))
    assert on_time.check() == []

    late = deferred_invoice([_ddt("DDT-1", date(2026, 9, 3))], number="15/2026",
                            date=date(2026, 10, 16))
    assert "deferred_late" in {a.code for a in late.check()}

    december = deferred_invoice([_ddt("DDT-1", date(2026, 12, 20))], number="1/2027",
                                date=date(2027, 1, 15))
    assert december.check() == []

    mixed = deferred_invoice([_ddt("DDT-1", date(2026, 8, 28)), _ddt("DDT-2", date(2026, 9, 2))],
                             number="15/2026", date=date(2026, 9, 10))
    assert "deferred_mixed_months" in {a.code for a in mixed.check()}

    early = deferred_invoice([_ddt("DDT-1", date(2026, 9, 20))], number="15/2026",
                             date=date(2026, 9, 10))
    assert "deferred_before_delivery" in {a.code for a in early.check()}


# ── credit notes ──────────────────────────────────────────────────────────


def _invoice() -> Invoice:
    return _quote().to_invoice(number="13/2026", date=date(2026, 9, 10))


def test_a_full_credit_note_mirrors_the_invoice():
    invoice = _invoice()
    note = credit_note_for(invoice, number="NC-1/2026", date=date(2026, 9, 20))
    assert note.document_type is DocumentType.CREDIT_NOTE
    assert note.vat_summary() == invoice.vat_summary()
    assert note.total_document() == invoice.total_document()
    assert note.payments == []
    assert note.references == [DocumentReference("invoice", "13/2026", date(2026, 9, 10))]
    assert "13/2026" in note.causale
    note.validate()
    assert note.check() == []


def test_a_credit_note_by_amount_keeps_the_rates_of_the_invoice():
    """150 back on food at 10% and wine at 22%: crediting it all at one rate
    moves VAT from one rate to the other."""
    invoice = _invoice()
    note = credit_note_for(invoice, number="NC-2/2026", date=date(2026, 9, 20),
                           amount=Decimal("150.00"))
    assert note.total_document() == Decimal("150.00")
    assert sorted(line.vat_rate for line in note.lines) == [Decimal("10.00"), Decimal("22.00")]
    gross = {s.vat_rate: s.taxable + s.tax for s in invoice.vat_summary()}
    share = {s.vat_rate: s.taxable + s.tax for s in note.vat_summary()}
    ratio_invoice = gross[Decimal("10.00")] / gross[Decimal("22.00")]
    ratio_note = share[Decimal("10.00")] / share[Decimal("22.00")]
    assert abs(ratio_invoice - ratio_note) < Decimal("0.01")


@pytest.mark.parametrize("amount", ["0.01", "0.07", "10.01", "99.99", "1234.56"])
def test_a_credit_note_by_amount_lands_on_the_cent_or_says_so(amount):
    note = credit_note_for(_invoice(), number="NC-2/2026", date=date(2026, 9, 20),
                           amount=Decimal(amount))
    assert abs(note.total_document() - Decimal(amount)) <= Decimal("0.01") * len(note.lines)
    note.validate()


def test_a_credit_note_by_lines_credits_what_came_back():
    note = credit_note_for(_invoice(), number="NC-3/2026", date=date(2026, 9, 20),
                           lines={1: Decimal("3")})
    (line,) = note.lines
    assert line.description == "Barolo DOCG" and line.quantity == Decimal("3")
    assert line.discounts[0].amount == Decimal("6.00")        # 24 × 3/12
    assert note.total_document() == Decimal("131.76")          # (114 − 6) × 1.22


def test_credit_note_limits():
    invoice = _invoice()
    with pytest.raises(ValidationError, match="supera"):
        credit_note_for(invoice, number="NC", date=date(2026, 9, 20), amount=Decimal("9999"))
    with pytest.raises(ValidationError, match="positivo"):
        credit_note_for(invoice, number="NC", date=date(2026, 9, 20), amount=Decimal("0"))
    with pytest.raises(ValidationError, match="fuori"):
        credit_note_for(invoice, number="NC", date=date(2026, 9, 20), lines={1: Decimal("13")})
    with pytest.raises(ValidationError, match="non esiste"):
        credit_note_for(invoice, number="NC", date=date(2026, 9, 20), lines={9: Decimal("1")})
    with pytest.raises(ValidationError, match="OPPURE"):
        credit_note_for(invoice, number="NC", date=date(2026, 9, 20), amount=Decimal("1"),
                        lines={0: Decimal("1")})
    note = credit_note_for(invoice, number="NC", date=date(2026, 9, 20))
    with pytest.raises(ValidationError, match="non una nota di credito"):
        credit_note_for(note, number="NC-2", date=date(2026, 9, 21))


def test_a_partial_amount_on_an_invoice_with_withholding_asks_for_lines():
    invoice = _quote(withholdings=[WithholdingTax(Decimal("20"), Decimal("20"))]).to_invoice(
        number="13/2026", date=date(2026, 9, 10))
    with pytest.raises(ValidationError, match="lines="):
        credit_note_for(invoice, number="NC", date=date(2026, 9, 20), amount=Decimal("10"))
    full = credit_note_for(invoice, number="NC", date=date(2026, 9, 20))
    assert full.withholding_total() == invoice.withholding_total()


def test_a_credit_note_dated_before_its_invoice_is_refused():
    """SdI 00418: the note may not precede the invoice it corrects."""
    note = credit_note_for(_invoice(), number="NC-1/2026", date=date(2026, 9, 9))
    with pytest.raises(ValidationError, match="00418"):
        note.validate()


# ── status ────────────────────────────────────────────────────────────────


def test_initial_statuses():
    assert initial_status("quote") is DocumentStatus.DRAFT
    assert initial_status(DocumentKind.PROFORMA) is DocumentStatus.ISSUED
    assert initial_status("delivery_note") is DocumentStatus.ISSUED
    with pytest.raises(ValueError):
        initial_status("invoice")


def test_the_status_table():
    assert can_transition("quote", "draft", "sent")
    assert can_transition("quote", "sent", "accepted")
    assert can_transition("quote", "accepted", "converted")
    assert not can_transition("quote", "rejected", "converted")
    assert not can_transition("quote", "converted", "draft")
    assert can_transition("proforma", "issued", "converted")
    assert not can_transition("proforma", "converted", "cancelled")
    assert can_transition("delivery_note", "issued", "invoiced")
    assert not can_transition("delivery_note", "invoiced", "cancelled")
    assert next_statuses("delivery_note", "cancelled") == frozenset()
    assert transition("quote", "draft", "sent") is DocumentStatus.SENT
    with pytest.raises(IllegalTransition, match="ammessi"):
        transition("delivery_note", "invoiced", "issued")


# ── JSON ──────────────────────────────────────────────────────────────────


def _everything() -> list:
    quote = _quote(notes="Allestimento incluso",
                   funds=[SocialSecurityFund("TC22", Decimal("4"), Decimal("10.00"),
                                             vat_rate=Decimal("22"))])
    transport = TransportDetails(
        reason=TransportReason.APPROVAL, reason_text="ritiro entro 10 giorni",
        by=TransportBy.CARRIER, carrier=Carrier("Trasporti Veloci", vat_number="01234567897",
                                                address=Address("Via A 1", "20100", "Milano", "MI"),
                                                license_number="MI1"),
        means="Furgone", packages=3, goods_appearance="Casse", gross_weight=Decimal("12.5"),
        net_weight=Decimal("10"), start=datetime(2026, 9, 20, 9, 30), freight=Freight.COLLECT,
        incoterm="DAP", delivery_address=Address("Piazza Duomo 1", "20121", "Milano", "MI"))
    invoice = quote.to_invoice(number="13/2026", date=date(2026, 9, 10), transport=transport)
    return [
        quote,
        quote.to_proforma(number="PF-1/2026", date=date(2026, 9, 2)),
        quote.to_delivery_note(number="DDT-1/2026", date=date(2026, 9, 20), transport=transport),
        invoice,
        credit_note_for(invoice, number="NC-1/2026", date=date(2026, 9, 20)),
    ]


@pytest.mark.parametrize("index", range(5))
def test_every_document_survives_json(index):
    doc = _everything()[index]
    assert document_from_json(document_to_json(doc)) == doc
    assert document_to_dict(doc)["kind"] == document_kind(doc).value


def test_json_without_a_kind_is_an_invoice():
    from einvoice import invoice_to_dict

    invoice = _everything()[3]
    assert document_from_dict(invoice_to_dict(invoice)) == invoice


def test_a_wrong_kind_is_named():
    with pytest.raises(ValidationError, match="kind"):
        document_from_dict({"kind": "receipt"})


# ── PDF ───────────────────────────────────────────────────────────────────


def _pdf_text(pdf: bytes) -> bytes:
    """The page content streams, decoded: ReportLab writes them ASCII85 over
    Flate, so the drawn strings are not in the raw bytes."""
    import base64
    import re
    import zlib

    out = []
    for stream in re.findall(rb"stream\r?\n(.*?)\r?\n?endstream", pdf, re.S):
        data = stream.strip()
        try:
            if data.endswith(b"~>"):
                data = base64.a85decode(data[:-2])
            out.append(zlib.decompress(data))
        except (ValueError, zlib.error):
            out.append(stream)
    return b"\n".join(out)


@pytest.mark.parametrize("index", range(5))
def test_every_document_prints(index):
    pytest.importorskip("reportlab", reason="il PDF è l'extra [pdf]")
    from einvoice import document_pdf

    assert document_pdf(_everything()[index]).startswith(b"%PDF-")


def test_each_pdf_carries_its_own_title():
    """A credit note used to be printed under the title «FATTURA»."""
    pytest.importorskip("reportlab", reason="il PDF è l'extra [pdf]")
    from einvoice import document_pdf, translate

    quote, proforma, note, invoice, credit = _everything()
    expected = {
        "doc.kind.quote": quote, "doc.kind.proforma": proforma,
        "doc.kind.delivery_note": note, "doc.invoice": invoice,
        "doc.kind.credit_note": credit,
    }
    for key, doc in expected.items():
        assert f"({translate(key, 'it')})".encode("latin-1") in _pdf_text(document_pdf(doc)), key
    assert f"({translate('doc.invoice', 'it')})".encode() not in _pdf_text(document_pdf(credit))


def test_the_proforma_says_it_is_not_an_invoice():
    pytest.importorskip("reportlab", reason="il PDF è l'extra [pdf]")
    from einvoice import document_pdf, translate

    proforma = _everything()[1]
    disclaimer = translate("doc.proforma_disclaimer", "it")
    assert disclaimer.split(":")[0].encode("latin-1") in _pdf_text(document_pdf(proforma))


def test_the_cli_prints_any_document(tmp_path):
    pytest.importorskip("reportlab", reason="il PDF è l'extra [pdf]")
    from einvoice.cli import main

    for doc in _everything():
        source = tmp_path / f"{document_kind(doc).value}.json"
        source.write_text(document_to_json(doc), encoding="utf-8")
        out = tmp_path / f"{document_kind(doc).value}.pdf"
        assert main(["pdf", str(source), "-o", str(out)]) == 0
        assert out.read_bytes().startswith(b"%PDF-")
