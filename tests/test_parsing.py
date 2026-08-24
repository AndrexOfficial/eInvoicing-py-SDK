"""Reading an invoice back — the half of every integration that was missing.

The strongest property available here is the round trip: render an invoice,
parse it, and the two must agree. It exercises both directions at once and
catches an asymmetry the moment it appears.
"""
from datetime import date
from decimal import Decimal

import pytest

from einvoice import (
    Address,
    AllowanceCharge,
    Attachment,
    BankAccount,
    DocumentReference,
    DocumentType,
    Invoice,
    LineItem,
    Party,
    Payment,
    PaymentMeans,
    VatNature,
    compare_declared_totals,
    detect_standard,
    parse_invoice,
    profile_for,
    supported_countries,
)
from einvoice.errors import ValidationError
from einvoice.formats import get_renderer

STANDARDS = ["fatturapa", "ubl", "cii"]
#: FatturaPA is Italy's format; rendering a German seller through it is not a
#: thing anyone does, so the cross-country sweep uses the EN 16931 pair.
EN16931 = ["ubl", "cii"]


def _italian(**kw) -> Invoice:
    base = {
        "number": "RT-1", "date": date(2026, 8, 24),
        "seller": Party(name="Studio Rossi", vat_number="07643520567",
                        address=Address("Via Roma 1", "20100", "Milano", "MI")),
        "buyer": Party(name="ACME Srl", vat_number="09876543217", sdi_code="ABCDEFG",
                       address=Address("Via Verdi 9", "00100", "Roma", "RM")),
        "lines": [LineItem("Consulenza", Decimal("10"), Decimal("100"), Decimal("22"))],
    }
    base.update(kw)
    return Invoice(**base)


def _rendered(invoice: Invoice, standard: str) -> bytes:
    return get_renderer(standard).render(invoice).content


# ── detection ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("standard", STANDARDS)
def test_format_is_detected_from_the_root_element(standard):
    assert detect_standard(_rendered(_italian(), standard)) == standard


def test_a_credit_note_is_still_recognised_as_ubl():
    """Credit notes live on a different UBL root; detection must know both."""
    cn = _italian(document_type=DocumentType.CREDIT_NOTE,
                  references=[DocumentReference("invoice", "INV-1", date(2026, 1, 1))])
    assert detect_standard(_rendered(cn, "ubl")) == "ubl"


def test_an_unrecognised_document_says_what_it_expected():
    with pytest.raises(ValidationError, match="FatturaPA"):
        detect_standard(b"<?xml version='1.0'?><purchaseOrder/>")


def test_malformed_xml_is_a_validation_error_not_a_crash():
    with pytest.raises(ValidationError, match="XML non valido"):
        parse_invoice(b"<not-closed")


def test_parsing_accepts_str_as_well_as_bytes():
    xml = _rendered(_italian(), "ubl").decode()
    assert parse_invoice(xml).number == "RT-1"


# ── round trip: the core property ──────────────────────────────────────────


@pytest.mark.parametrize("standard", STANDARDS)
def test_round_trip_preserves_the_money(standard):
    original = _italian(
        lines=[LineItem("A", Decimal("10"), Decimal("100"), Decimal("22")),
               LineItem("B", Decimal("2"), Decimal("55.55"), Decimal("10"))])
    restored = parse_invoice(_rendered(original, standard))

    assert restored.lines_total() == original.lines_total()
    assert restored.taxable_total() == original.taxable_total()
    assert restored.tax_total() == original.tax_total()
    assert restored.total_document() == original.total_document()


@pytest.mark.parametrize("standard", STANDARDS)
def test_round_trip_preserves_identity_and_parties(standard):
    original = _italian()
    restored = parse_invoice(_rendered(original, standard))

    assert restored.number == original.number
    assert restored.date == original.date
    assert restored.currency == original.currency
    assert restored.seller.vat_number == original.seller.vat_number
    assert restored.buyer.vat_number == original.buyer.vat_number
    assert restored.seller.address.city == original.seller.address.city
    assert restored.buyer.address.postcode == original.buyer.address.postcode


@pytest.mark.parametrize("standard", STANDARDS)
def test_round_trip_preserves_line_detail(standard):
    original = _italian(lines=[LineItem(
        "Abbonamento", Decimal("3"), Decimal("120"), Decimal("22"),
        unit_of_measure="MON", article_code="SKU-9",
        period_start=date(2026, 1, 1), period_end=date(2026, 3, 31))])
    line = parse_invoice(_rendered(original, standard)).lines[0]

    assert line.description == "Abbonamento"
    assert line.quantity == Decimal("3")
    assert line.unit_price == Decimal("120")
    assert line.vat_rate == Decimal("22")
    assert line.unit_of_measure == "MON"
    assert line.article_code == "SKU-9"
    assert line.period_start == date(2026, 1, 1)
    assert line.period_end == date(2026, 3, 31)


@pytest.mark.parametrize("standard", STANDARDS)
def test_round_trip_preserves_payment_details(standard):
    original = _italian(payments=[Payment(
        means=PaymentMeans.BANK_TRANSFER, due_date=date(2026, 9, 30),
        account=BankAccount("IT60X0542811101000000123456"))])
    restored = parse_invoice(_rendered(original, standard))

    assert restored.payments
    assert restored.payments[0].means is PaymentMeans.BANK_TRANSFER
    assert restored.payments[0].due_date == date(2026, 9, 30)
    assert restored.payments[0].account.iban == "IT60X0542811101000000123456"


@pytest.mark.parametrize("standard", STANDARDS)
def test_round_trip_preserves_references(standard):
    original = _italian(references=[
        DocumentReference("order", "PO-1"),
        DocumentReference("contract", "C-7"),
        DocumentReference("ddt", "DDT-3"),
    ])
    restored = parse_invoice(_rendered(original, standard))
    kinds = {r.kind: r.doc_id for r in restored.references}

    assert kinds["order"] == "PO-1"
    assert kinds["contract"] == "C-7"
    assert kinds["ddt"] == "DDT-3"


@pytest.mark.parametrize("standard", EN16931)
def test_round_trip_preserves_attachments(standard):
    original = _italian(attachments=[Attachment(
        "spec.pdf", b"%PDF-1.4 payload", mime="application/pdf",
        description="Capitolato")])
    restored = parse_invoice(_rendered(original, standard))

    assert len(restored.attachments) == 1
    assert restored.attachments[0].content == b"%PDF-1.4 payload"
    assert restored.attachments[0].filename == "spec.pdf"


@pytest.mark.parametrize("standard", EN16931)
def test_round_trip_preserves_document_discounts(standard):
    original = _italian(allowances_charges=[
        AllowanceCharge(Decimal("25"), vat_rate=Decimal("22"), reason="Sconto")])
    restored = parse_invoice(_rendered(original, standard))

    assert restored.taxable_total() == original.taxable_total()
    assert any(a.amount == Decimal("25") and not a.is_charge
               for a in restored.allowances_charges)


@pytest.mark.parametrize("standard", STANDARDS)
def test_round_trip_preserves_line_discounts(standard):
    original = _italian(lines=[LineItem(
        "A", Decimal("2"), Decimal("100"), Decimal("22"),
        discounts=[AllowanceCharge(Decimal("15"), reason="promo")])])
    restored = parse_invoice(_rendered(original, standard))

    assert restored.lines[0].total == original.lines[0].total


@pytest.mark.parametrize("standard", STANDARDS)
def test_a_credit_note_stays_a_credit_note(standard):
    original = _italian(
        document_type=DocumentType.CREDIT_NOTE,
        references=[DocumentReference("invoice", "INV-1", date(2026, 1, 1))])
    restored = parse_invoice(_rendered(original, standard))

    assert restored.document_type.is_credit_note
    assert any(r.kind == "invoice" and r.doc_id == "INV-1" for r in restored.references)


# ── every country, both EN 16931 syntaxes ──────────────────────────────────


def _domestic(code: str) -> Invoice:
    from test_all_countries import _domestic_invoice

    return _domestic_invoice(code)


@pytest.mark.parametrize("code", sorted(supported_countries()))
@pytest.mark.parametrize("standard", EN16931)
def test_every_country_round_trips(code, standard):
    """A parser that works only for the country it was written against is a
    parser that will surprise someone."""
    profile = profile_for(code)
    kwargs = {} if profile.tax_scheme == "VAT" else {"tax_scheme": profile.tax_scheme}
    original = _domestic(code)
    xml = get_renderer(standard, **kwargs).render(original).content

    restored = parse_invoice(xml)

    assert restored.total_document() == original.total_document()
    assert restored.seller.vat_number == original.seller.normalized_vat()
    assert restored.currency == original.currency


# ── totals are recomputed, not believed ────────────────────────────────────


@pytest.mark.parametrize("standard", STANDARDS)
def test_declared_and_computed_totals_agree_on_our_own_output(standard):
    invoice = _italian()
    result = compare_declared_totals(_rendered(invoice, standard))

    assert result["declared"] == result["computed"] == invoice.total_document()
    assert result["difference"] == Decimal("0")


def test_a_supplier_whose_total_disagrees_with_their_lines_is_visible():
    """The reason totals are recomputed rather than read: a stated total that
    does not follow from the lines must not be imported as fact."""
    xml = _rendered(_italian(), "ubl").decode()
    tampered = xml.replace(
        "<cbc:PayableAmount currencyID=\"EUR\">1220.00</cbc:PayableAmount>",
        "<cbc:PayableAmount currencyID=\"EUR\">9999.00</cbc:PayableAmount>")
    assert tampered != xml, "fixture no longer matches the rendered total"

    result = compare_declared_totals(tampered)

    assert result["declared"] == Decimal("9999.00")
    assert result["computed"] == Decimal("1220.00")
    assert result["difference"] == Decimal("8779.00")


def test_a_header_only_profile_declares_a_total_but_carries_no_lines():
    """MINIMUM/BASIC WL are header-only by design, so the computed total is
    zero and the declared one is all there is — worth being explicit about."""
    from einvoice.formats.cii import FACTURX_PROFILES, build_cii_xml

    xml = build_cii_xml(_italian(), guideline=FACTURX_PROFILES["minimum"])
    parsed = parse_invoice(xml)
    assert parsed.lines == []

    result = compare_declared_totals(xml)
    assert result["declared"] == Decimal("1220.00")


# ── Italian specifics survive FatturaPA and only FatturaPA ─────────────────


def test_fatturapa_preserves_the_italian_blocks():
    original = _italian(stamp_duty=Decimal("2.00"), causale="Prestazione")
    restored = parse_invoice(_rendered(original, "fatturapa"))

    assert restored.stamp_duty == Decimal("2.00")
    assert restored.causale == "Prestazione"
    assert restored.recipient_code == "ABCDEFG"


def test_fatturapa_preserves_the_natura_subcode():
    """UBL narrows N6.3 to a single "AE" category; FatturaPA does not."""
    original = _italian(lines=[LineItem(
        "Subappalto", Decimal("1"), Decimal("100"), Decimal("0"),
        nature=VatNature.REVERSE_CHARGE_CONSTRUCTION_SUB)])
    restored = parse_invoice(_rendered(original, "fatturapa"))

    assert restored.lines[0].nature is VatNature.REVERSE_CHARGE_CONSTRUCTION_SUB


def test_ubl_narrows_the_natura_to_its_en16931_family():
    """Documented loss, not a silent one: EN 16931 has one reverse-charge
    category where Italy has nine, so the sub-code cannot survive."""
    original = _italian(lines=[LineItem(
        "Subappalto", Decimal("1"), Decimal("100"), Decimal("0"),
        nature=VatNature.REVERSE_CHARGE_CONSTRUCTION_SUB)])
    restored = parse_invoice(_rendered(original, "ubl"))

    assert restored.lines[0].nature is VatNature.REVERSE_CHARGE_OTHER
    assert restored.lines[0].nature.en16931_category == "AE"


# ── a parsed invoice is a usable invoice ───────────────────────────────────


@pytest.mark.parametrize("standard", STANDARDS)
def test_a_parsed_invoice_validates(standard):
    restored = parse_invoice(_rendered(_italian(), standard))
    restored.validate()


@pytest.mark.parametrize("standard", EN16931)
def test_a_parsed_invoice_can_be_re_rendered_to_the_same_totals(standard):
    """Receive, store, forward — the shape of any real AP workflow."""
    original = _italian(
        lines=[LineItem("A", Decimal("3"), Decimal("99.99"), Decimal("22"))])
    once = parse_invoice(_rendered(original, standard))
    twice = parse_invoice(_rendered(once, standard))

    assert twice.total_document() == once.total_document() == original.total_document()


def test_parse_invoice_can_be_told_the_format():
    xml = _rendered(_italian(), "ubl")
    assert parse_invoice(xml, standard="ubl").number == "RT-1"


def test_an_unknown_forced_format_lists_the_real_ones():
    with pytest.raises(ValidationError, match="fatturapa"):
        parse_invoice(_rendered(_italian(), "ubl"), standard="edifact")


# ── fidelity: what each format is contractually able to carry ─────────────


def _maximal() -> Invoice:
    """Every field the model has, so the round trip has something to lose."""
    from einvoice import SocialSecurityFund, WithholdingTax

    return Invoice(
        number="MAX-1", date=date(2026, 8, 24),
        seller=Party(name="Studio Rossi SRL", vat_number="07643520567",
                     tax_code="RSSMRA80A01H501U", country_code="IT",
                     tax_regime="RF19", email="info@studio.it",
                     registration_number="MI-123456",
                     address=Address("Via Roma 1", "20100", "Milano", "MI", "IT")),
        buyer=Party(name="ACME Srl", vat_number="09876543217",
                    tax_code="ACMTAX00X00X000X", country_code="IT",
                    sdi_code="ABCDEFG", email="ap@acme.it",
                    address=Address("Via Verdi 9", "00100", "Roma", "RM", "IT")),
        lines=[LineItem("Consulenza", Decimal("10"), Decimal("100.00"), Decimal("22"),
                        unit_of_measure="ORE", article_code="C-1",
                        period_start=date(2026, 1, 1), period_end=date(2026, 3, 31),
                        discounts=[AllowanceCharge(Decimal("50"), reason="Sconto")])],
        causale="Prestazione Q1", buyer_reference="PO-42",
        payments=[Payment(means=PaymentMeans.BANK_TRANSFER, due_date=date(2026, 9, 30),
                          account=BankAccount("IT60X0542811101000000123456",
                                              "Banca X", "Studio", "BCITITMM"))],
        withholdings=[WithholdingTax(Decimal("200"), Decimal("20"))],
        funds=[SocialSecurityFund("TC01", Decimal("4"), Decimal("40.00"),
                                  taxable=Decimal("1000"), vat_rate=Decimal("22"))],
        attachments=[Attachment("spec.pdf", b"%PDF-1.4", mime="application/pdf")],
        references=[DocumentReference("order", "PO-1", date(2026, 1, 5)),
                    DocumentReference("contract", "C-7"),
                    DocumentReference("ddt", "DDT-3"),
                    DocumentReference("invoice", "INV-9", date(2026, 3, 1))],
        stamp_duty=Decimal("2.00"), art73=True, rounding=Decimal("0.01"),
        recipient_code="ABCDEFG",
    )


#: Fields no EN 16931 syntax models. Losing them through UBL/CII is the
#: standard's limitation, not ours — but it must stay a *known* list, so a new
#: silent loss shows up here as a failure rather than as a support ticket.
EN16931_CANNOT_CARRY = {
    "stamp_duty",      # bollo virtuale — rendered as an untyped charge
    "recipient_code",  # CodiceDestinatario — SdI routing, not an EU concept
    "art73",           # art. 73 DPR 633/72
    "withholdings",    # ritenuta d'acconto
    "funds",           # cassa previdenziale
}


def test_fatturapa_is_lossless():
    """The format that is *meant* to be lossless has to actually be.

    Every one of these was silently dropped by the parser before: the ritenuta,
    the cassa, the attachments and the document discounts were rendered into
    the XML and then thrown away on the way back in.
    """
    original = _maximal()
    restored = parse_invoice(_rendered(original, "fatturapa"))

    for field in ("number", "date", "currency", "causale", "buyer_reference",
                  "stamp_duty", "rounding", "recipient_code", "art73"):
        assert getattr(restored, field) == getattr(original, field), field
    for role in ("seller", "buyer"):
        for field in ("name", "vat_number", "tax_code", "registration_number", "email"):
            assert getattr(getattr(restored, role), field) \
                == getattr(getattr(original, role), field), f"{role}.{field}"
    assert len(restored.withholdings) == 1
    assert restored.withholdings[0].amount == Decimal("200")
    assert len(restored.funds) == 1
    assert restored.funds[0].kind == "TC01"
    assert len(restored.attachments) == 1
    assert restored.attachments[0].content == b"%PDF-1.4"
    assert len(restored.references) == 4


def test_fatturapa_preserves_the_full_bank_details():
    original = _maximal()
    account = parse_invoice(_rendered(original, "fatturapa")).payments[0].account

    assert account.iban == "IT60X0542811101000000123456"
    assert account.holder == "Studio"
    assert account.bank_name == "Banca X"
    assert account.bic == "BCITITMM"


@pytest.mark.parametrize("standard", EN16931)
def test_en16931_carries_everything_except_the_known_list(standard):
    """A regression fence around the documented losses.

    If a field starts disappearing that is not on the list, this fails — which
    is the only way a silent loss gets noticed before a customer finds it.
    """
    original = _maximal()
    restored = parse_invoice(_rendered(original, standard))

    for field in ("number", "date", "currency", "causale", "buyer_reference", "rounding"):
        assert getattr(restored, field) == getattr(original, field), field
    for role in ("seller", "buyer"):
        for field in ("name", "vat_number", "tax_code", "registration_number", "email"):
            assert getattr(getattr(restored, role), field) \
                == getattr(getattr(original, role), field), f"{role}.{field}"
    assert len(restored.attachments) == 1
    assert len(restored.references) == 4
    assert restored.lines[0].article_code == "C-1"
    assert restored.lines[0].period_end == date(2026, 3, 31)


@pytest.mark.parametrize("standard", EN16931)
@pytest.mark.parametrize("field", sorted(EN16931_CANNOT_CARRY))
def test_the_documented_losses_really_are_losses(standard, field):
    """Pins the other direction: if one of these starts surviving, the docs and
    the PARSING.md table are wrong and should be updated."""
    original = _maximal()
    restored = parse_invoice(_rendered(original, standard))
    lost = getattr(restored, field)

    assert lost in (None, False, []), (
        f"{field} now survives {standard} — update docs/PARSING.md"
    )


@pytest.mark.parametrize("standard", EN16931)
def test_contact_email_survives_en16931(standard):
    """BG-6/BG-9 model it, so dropping it was our gap, not the standard's."""
    restored = parse_invoice(_rendered(_maximal(), standard))
    assert restored.seller.email == "info@studio.it"
    assert restored.buyer.email == "ap@acme.it"


def test_ubl_carries_the_payee_account_holder_and_bank():
    account = parse_invoice(_rendered(_maximal(), "ubl")).payments[0].account
    assert account.holder == "Studio"
    assert account.bic == "BCITITMM"


# ── documents nobody here rendered ─────────────────────────────────────────
# Round-tripping our own output proves the two halves agree with each other.
# It does not prove either agrees with the standard. These fixtures are shaped
# the way a third-party sender writes them.


def _third_party_ubl(*, base_quantity: str | None, price: str,
                     quantity: str, stated_total: str) -> str:
    base = (f'<cbc:BaseQuantity unitCode="C62">{base_quantity}</cbc:BaseQuantity>'
            if base_quantity else "")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
 <cbc:ID>  X-1  </cbc:ID><cbc:IssueDate>2026-08-24</cbc:IssueDate>
 <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
 <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
 <cac:AccountingSupplierParty><cac:Party>
   <cac:PostalAddress><cbc:StreetName>A</cbc:StreetName><cbc:CityName>Milano</cbc:CityName>
   <cbc:PostalZone>20100</cbc:PostalZone>
   <cac:Country><cbc:IdentificationCode>IT</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
   <cac:PartyTaxScheme><cbc:CompanyID>IT07643520567</cbc:CompanyID></cac:PartyTaxScheme>
   <cac:PartyLegalEntity><cbc:RegistrationName>Seller</cbc:RegistrationName></cac:PartyLegalEntity>
 </cac:Party></cac:AccountingSupplierParty>
 <cac:AccountingCustomerParty><cac:Party>
   <cac:PostalAddress><cbc:StreetName>B</cbc:StreetName><cbc:CityName>Roma</cbc:CityName>
   <cbc:PostalZone>00100</cbc:PostalZone>
   <cac:Country><cbc:IdentificationCode>IT</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
   <cac:PartyLegalEntity><cbc:RegistrationName>Buyer</cbc:RegistrationName></cac:PartyLegalEntity>
 </cac:Party></cac:AccountingCustomerParty>
 <cac:InvoiceLine><cbc:ID>1</cbc:ID>
   <cbc:InvoicedQuantity unitCode="C62">{quantity}</cbc:InvoicedQuantity>
   <cbc:LineExtensionAmount currencyID="EUR">{stated_total}</cbc:LineExtensionAmount>
   <cac:Item><cbc:Name>Widget</cbc:Name><cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID>
     <cbc:Percent>22</cbc:Percent></cac:ClassifiedTaxCategory></cac:Item>
   <cac:Price><cbc:PriceAmount currencyID="EUR">{price}</cbc:PriceAmount>{base}</cac:Price>
 </cac:InvoiceLine></Invoice>"""


@pytest.mark.parametrize(("base", "price", "quantity", "stated"), [
    ("10", "50.00", "10", "50.00"),        # price per 10
    ("100", "12.00", "250", "30.00"),      # price per 100
    ("1000", "2.50", "3000", "7.50"),      # per-mille pricing
    ("1", "7.50", "4", "30.00"),           # explicit base of 1
    (None, "50.00", "10", "500.00"),       # no base quantity at all
])
def test_a_price_quoted_per_n_units_is_normalised(base, price, quantity, stated):
    """Wholesale prices are routinely quoted per 100 or per 1000, and both
    syntaxes express that by pairing the amount with a base quantity.

    Reading the amount and ignoring the base multiplies the line by that base:
    "50.00 per 10" with a quantity of 10 came out as 500.00 instead of 50.00 —
    a tenfold error on a perfectly valid document from a real supplier.
    """
    invoice = parse_invoice(_third_party_ubl(
        base_quantity=base, price=price, quantity=quantity, stated_total=stated))

    assert invoice.lines[0].total == Decimal(stated)


def test_a_third_party_document_agrees_with_its_own_stated_total():
    """The strongest check available on foreign input: what we compute from the
    lines has to match what the sender put in the totals block."""
    xml = _third_party_ubl(base_quantity="10", price="50.00",
                           quantity="10", stated_total="50.00")
    invoice = parse_invoice(xml)
    assert invoice.lines_total() == Decimal("50.00")
    assert invoice.total_document() == Decimal("61.00")   # + 22% VAT


def test_whitespace_around_values_is_stripped():
    """Pretty-printed XML from another system puts newlines inside elements."""
    invoice = parse_invoice(_third_party_ubl(
        base_quantity=None, price="50.00", quantity="1", stated_total="50.00"))
    assert invoice.number == "X-1"


FATTURAPA_WITHOUT_NAMESPACE = """<?xml version="1.0"?>
<FatturaElettronica versione="FPR12">
<FatturaElettronicaHeader>
<DatiTrasmissione><CodiceDestinatario>ABCDEFG</CodiceDestinatario></DatiTrasmissione>
<CedentePrestatore><DatiAnagrafici>
<IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>07643520567</IdCodice></IdFiscaleIVA>
<Anagrafica><Denominazione>Seller</Denominazione></Anagrafica>
<RegimeFiscale>RF01</RegimeFiscale></DatiAnagrafici>
<Sede><Indirizzo>A</Indirizzo><CAP>20100</CAP><Comune>Milano</Comune>
<Nazione>IT</Nazione></Sede></CedentePrestatore>
<CessionarioCommittente><DatiAnagrafici>
<IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>09876543217</IdCodice></IdFiscaleIVA>
<Anagrafica><Denominazione>Buyer</Denominazione></Anagrafica></DatiAnagrafici>
<Sede><Indirizzo>B</Indirizzo><CAP>00100</CAP><Comune>Roma</Comune>
<Nazione>IT</Nazione></Sede></CessionarioCommittente>
</FatturaElettronicaHeader><FatturaElettronicaBody>
<DatiGenerali><DatiGeneraliDocumento><TipoDocumento>TD01</TipoDocumento>
<Divisa>EUR</Divisa><Data>2026-08-24</Data><Numero>F-1</Numero>
</DatiGeneraliDocumento></DatiGenerali>
<DatiBeniServizi><DettaglioLinee><NumeroLinea>1</NumeroLinea>
<Descrizione>A</Descrizione><Quantita>1.00</Quantita>
<PrezzoUnitario>100.00</PrezzoUnitario><PrezzoTotale>100.00</PrezzoTotale>
<AliquotaIVA>22.00</AliquotaIVA></DettaglioLinee></DatiBeniServizi>
</FatturaElettronicaBody></FatturaElettronica>"""


def test_fatturapa_stripped_of_its_namespace_is_still_read():
    """Intermediaries do strip it, and a document that only parses when it has
    been through our own renderer is not a parser."""
    assert detect_standard(FATTURAPA_WITHOUT_NAMESPACE) == "fatturapa"
    invoice = parse_invoice(FATTURAPA_WITHOUT_NAMESPACE)
    assert invoice.number == "F-1"
    assert invoice.seller.vat_number == "07643520567"
    assert invoice.total_document() == Decimal("122.00")


def test_fatturapa_cannot_carry_the_vat_rate_of_a_document_charge():
    """The one thing FatturaPA loses, and it is the format's limit, not ours.

    `ScontoMaggiorazione` carries Tipo, Percentuale and Importo — there is no
    field for the VAT rate the charge belongs to. The rendered document is
    still correct and internally consistent (the riepiloghi and
    ImportoTotaleDocumento account for it); it is only on the way back in that
    the rate has to be assumed, and the model assumes the first line's.

    Recovering it by comparing the riepiloghi against the lines would work, and
    is deliberately not done: it means reconstructing a value from totals this
    module makes a point of recomputing rather than trusting.
    """
    original = Invoice(
        number="SC-1", date=date(2026, 8, 24),
        seller=Party(name="S", vat_number="07643520567",
                     address=Address("Via Roma 1", "20100", "Milano", "MI")),
        buyer=Party(name="B", vat_number="09876543217", sdi_code="ABCDEFG",
                    address=Address("Via Verdi 9", "00100", "Roma", "RM")),
        lines=[LineItem("A", Decimal("1"), Decimal("100"), Decimal("22"))],
        allowances_charges=[AllowanceCharge(Decimal("50"), is_charge=True,
                                            vat_rate=Decimal("5"))],
    )
    xml = _rendered(original, "fatturapa").decode()
    # The document itself states the right total...
    assert "<ImportoTotaleDocumento>174.50</ImportoTotaleDocumento>" in xml
    assert "<AliquotaIVA>5.00</AliquotaIVA>" in xml

    # ...but the charge comes back without its rate, so it lands on the first
    # line's bucket instead of its own.
    restored = parse_invoice(xml)
    assert restored.allowances_charges[0].vat_rate is None
    assert restored.total_document() != original.total_document()


@pytest.mark.parametrize("standard", EN16931)
def test_en16931_does_carry_the_rate_of_a_document_charge(standard):
    """UBL and CII have cac:TaxCategory / ram:CategoryTradeTax, so here the
    round trip is exact — including the stamp duty rendered as a zero-rated
    charge, which used to come back attracting the first line's VAT."""
    original = Invoice(
        number="SC-2", date=date(2026, 8, 24),
        seller=Party(name="S", vat_number="07643520567",
                     address=Address("Via Roma 1", "20100", "Milano", "MI")),
        buyer=Party(name="B", vat_number="09876543217", sdi_code="ABCDEFG",
                    address=Address("Via Verdi 9", "00100", "Roma", "RM")),
        lines=[LineItem("A", Decimal("1"), Decimal("100"), Decimal("22"))],
        allowances_charges=[AllowanceCharge(Decimal("50"), is_charge=True,
                                            vat_rate=Decimal("5"))],
        stamp_duty=Decimal("2.00"),
    )
    restored = parse_invoice(_rendered(original, standard))
    assert restored.total_document() == original.total_document()
