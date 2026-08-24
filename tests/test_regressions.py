"""Bugs found and fixed, each pinned so it cannot come back.

One test per defect, named for the behaviour rather than the fix, and written
so that reverting the corresponding change turns it red.
"""
from datetime import date
from decimal import Decimal

import pytest

from einvoice import (
    Address,
    AllowanceCharge,
    Invoice,
    LineItem,
    Party,
    SocialSecurityFund,
    VatNature,
    WithholdingTax,
    profile_for,
)
from einvoice.formats import get_renderer
from einvoice.formats.cii import FACTURX_PROFILES, build_cii_xml
from einvoice.taxid import normalize_tax_id, validate_tax_id_full


def _invoice(**kw) -> Invoice:
    base = {
        "number": "FR-1",
        "date": date(2026, 8, 24),
        "seller": Party(name="S", vat_number="40303265045", country_code="FR",
                        address=Address("1 rue", "75001", "Paris", country="FR")),
        "buyer": Party(name="B", vat_number="136695976", country_code="DE",
                       address=Address("Haupt 1", "10115", "Berlin", country="DE")),
        "lines": [LineItem("Conseil", Decimal("2"), Decimal("150"), Decimal("20"))],
    }
    base.update(kw)
    return Invoice(**base)


# ── CII: a US tax id is not a VAT registration ─────────────────────────────


def _us_invoice() -> Invoice:
    return Invoice(
        number="US-1", date=date(2026, 8, 24),
        seller=Party(name="Acme Inc", vat_number="12-3456789", country_code="US",
                     address=Address("Main 1", "10001", "New York", country="US")),
        buyer=Party(name="Buyer LLC", vat_number="987654321", country_code="US",
                    address=Address("2nd", "94105", "San Francisco", country="US")),
        lines=[LineItem("Widget", Decimal("1"), Decimal("100"), Decimal("8.875"))],
        currency="USD",
    )


def test_sales_tax_seller_is_not_labelled_as_vat_registered():
    """UNCL 1153: "VA" means VAT registration, "FC" a fiscal number.

    Stamping a US EIN as "VA" asserts the seller is registered for a tax the
    United States does not levy.
    """
    xml = build_cii_xml(_us_invoice(), tax_scheme="STT").decode()
    assert '<ram:ID schemeID="FC">123456789</ram:ID>' in xml
    assert 'schemeID="VA"' not in xml


def test_vat_seller_is_still_labelled_va():
    xml = build_cii_xml(_invoice()).decode()
    assert '<ram:ID schemeID="VA">FR40303265045</ram:ID>' in xml


# ── CII: the header-only Factur-X profiles carry no lines ──────────────────


@pytest.mark.parametrize("profile", ["minimum", "basicwl"])
def test_header_only_profiles_emit_no_line_items(profile):
    """"BASIC WL" is literally "Basic Without Lines", and MINIMUM is smaller
    still. Emitting lines while declaring one of them produces a document that
    claims a profile it does not satisfy — a validating receiver rejects it."""
    xml = build_cii_xml(_invoice(), guideline=FACTURX_PROFILES[profile]).decode()
    assert "<ram:IncludedSupplyChainTradeLineItem>" not in xml


@pytest.mark.parametrize("profile", ["basic", "en16931", "extended", "xrechnung"])
def test_line_bearing_profiles_still_carry_lines(profile):
    xml = build_cii_xml(_invoice(), guideline=FACTURX_PROFILES[profile]).decode()
    assert xml.count("<ram:IncludedSupplyChainTradeLineItem>") == 1


@pytest.mark.parametrize("profile", sorted(FACTURX_PROFILES))
def test_totals_describe_the_whole_document_whatever_the_profile(profile):
    """Dropping the lines must not drop the money: the header totals still
    describe the entire invoice, which is the point of those profiles."""
    invoice = _invoice()
    xml = build_cii_xml(invoice, guideline=FACTURX_PROFILES[profile]).decode()
    assert f"<ram:GrandTotalAmount>{invoice.total_document():.2f}</ram:GrandTotalAmount>" in xml


# ── tax ids: France is the one country where the prefix is ambiguous ───────


def test_a_french_key_of_fr_is_not_mistaken_for_a_country_prefix():
    """The French VAT key is 2 characters from [0-9A-HJ-NP-Z] — which includes
    both F and R. So a bare "FR123456789" has the key "FR", and stripping those
    two characters as a country prefix leaves a 9-character stub that fails
    validation for a number that is perfectly well formed.
    """
    assert normalize_tax_id("FR", "FR123456789") == "FR123456789"
    # ...while a genuinely prefixed number still loses its prefix.
    assert normalize_tax_id("FR", "FRFR123456789") == "FR123456789"
    assert normalize_tax_id("FR", "FR40303265045") == "40303265045"


def test_the_real_french_number_validates_either_way():
    assert validate_tax_id_full("FR", "FR40303265045", pattern=None)
    assert validate_tax_id_full("FR", "40303265045", pattern=None)


def test_no_other_country_needs_the_guard():
    """If a second country ever gains an alphabetic-leading bare form, it needs
    its own minimum length — this is what would notice."""
    import re

    from einvoice.countries import _VAT_PATTERNS

    ambiguous = [
        code for code, pattern in _VAT_PATTERNS.items()
        if re.match(pattern, code + "0" * 11)
    ]
    assert ambiguous == ["FR"], f"new ambiguous country codes: {ambiguous}"


# ── country profiles: don't assert what you don't know ─────────────────────


def test_an_unprofiled_country_claims_no_usual_currency():
    """The generic fallback used to hint EUR, so a perfectly ordinary USD
    invoice from an unlisted country produced a spurious currency advisory."""
    generic = profile_for("ZZ")
    assert generic.currency_hint == ""

    invoice = Invoice(
        number="Z-1", date=date(2026, 8, 24),
        seller=Party(name="S", vat_number="X123", country_code="ZZ",
                     address=Address("a", "1", "c", country="ZZ")),
        buyer=Party(name="B", vat_number="Y456", country_code="ZZ",
                    address=Address("b", "2", "d", country="ZZ")),
        lines=[LineItem("X", Decimal("1"), Decimal("100"), Decimal("0"))],
        currency="USD",
    )
    assert invoice.check() == []


# ── money: the paths the unit tests do not reach ───────────────────────────


MONEY_CASES = {
    "zero-rated bucket plus stamp duty": {
        "lines": [LineItem("A", Decimal("1"), Decimal("1000"), Decimal("22")),
                  LineItem("Escluso", Decimal("1"), Decimal("50"), Decimal("0"),
                           nature=VatNature.EXCLUDED)],
        "stamp_duty": Decimal("2.00"),
    },
    "stamp duty with no zero-rated bucket to join": {"stamp_duty": Decimal("2.00")},
    "withholding, stamp and negative rounding": {
        "withholdings": [WithholdingTax(Decimal("200"), Decimal("20"))],
        "stamp_duty": Decimal("2.00"), "rounding": Decimal("-0.01"),
    },
    "social-security fund, stamp and a document discount": {
        "funds": [SocialSecurityFund(
            "TC01", Decimal("4"), Decimal("40.00"), vat_rate=Decimal("22"))],
        "allowances_charges": [AllowanceCharge(
            Decimal("30"), vat_rate=Decimal("22"), reason="Sconto")],
        "stamp_duty": Decimal("2.00"),
    },
    "line-level discounts": {
        "lines": [LineItem("A", Decimal("2"), Decimal("100"), Decimal("22"),
                           discounts=[AllowanceCharge(
                               Decimal("15"), reason="promo")])],
    },
}


def _italian(**kw) -> Invoice:
    base = {
        "number": "IT-1", "date": date(2026, 8, 24),
        "seller": Party(name="S", vat_number="07643520567",
                        address=Address("Via Roma 1", "20100", "Milano", "MI")),
        "buyer": Party(name="B", vat_number="09876543217", sdi_code="ABCDEFG",
                       address=Address("Via Verdi 9", "00100", "Roma", "RM")),
        "lines": [LineItem("A", Decimal("1"), Decimal("1000"), Decimal("22"))],
    }
    base.update(kw)
    return Invoice(**base)


@pytest.mark.parametrize("name", sorted(MONEY_CASES))
def test_both_syntaxes_agree_on_the_payable_total(name):
    from xml.etree import ElementTree as ET

    from einvoice.formats.cii import RAM

    invoice = _italian(**MONEY_CASES[name])
    cii = ET.fromstring(get_renderer("cii").render(invoice).content)
    ubl = ET.fromstring(get_renderer("ubl").render(invoice).content)
    cac = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"
    cbc = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"

    payable = ubl.find(f"{cac}LegalMonetaryTotal/{cbc}PayableAmount").text
    grand = cii.find(f".//{{{RAM}}}GrandTotalAmount").text
    assert payable == grand == f"{invoice.total_document():.2f}"


@pytest.mark.parametrize("name", sorted(MONEY_CASES))
def test_cii_tax_buckets_sum_to_the_declared_basis(name):
    from xml.etree import ElementTree as ET

    from einvoice.formats.cii import RAM

    invoice = _italian(**MONEY_CASES[name])
    root = ET.fromstring(get_renderer("cii").render(invoice).content)
    settlement = root.find("rsm:SupplyChainTradeTransaction/"
                           "ram:ApplicableHeaderTradeSettlement",
                           {"rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
                            "ram": RAM})
    buckets = sum(
        Decimal(b.find(f"{{{RAM}}}BasisAmount").text)
        for b in settlement.findall(f"{{{RAM}}}ApplicableTradeTax")
    )
    basis = Decimal(settlement.find(
        f"{{{RAM}}}SpecifiedTradeSettlementHeaderMonetarySummation/"
        f"{{{RAM}}}TaxBasisTotalAmount").text)
    assert buckets == basis


# ── unit prices with more than two decimals ────────────────────────────────

PRICE_CASES = [
    ("3", "0.123456"),   # six decimals — the case that exposed it
    ("2.5", "40"),
    ("7", "1.005"),
    ("12", "0.0833"),    # a monthly twelfth
    ("1", "19.99"),
]


def _priced(quantity: str, price: str) -> Invoice:
    return Invoice(
        number="P-1", date=date(2026, 8, 24),
        seller=Party(name="S", vat_number="07643520567",
                     address=Address("Via Roma 1", "20100", "Milano", "MI")),
        buyer=Party(name="B", vat_number="09876543217", sdi_code="ABCDEFG",
                    address=Address("Via Verdi 9", "00100", "Roma", "RM")),
        lines=[LineItem("A", Decimal(quantity), Decimal(price), Decimal("22"))],
    )


@pytest.mark.parametrize(("quantity", "price"), PRICE_CASES)
@pytest.mark.parametrize("standard", ["ubl", "cii", "fatturapa"])
def test_the_printed_price_explains_the_printed_line_total(quantity, price, standard):
    """EN 16931: line net amount = round(quantity x price, 2).

    Rendering the unit price with two decimals broke this silently. A price of
    0.123456 was written as "0.12" beside a line total computed from the full
    value, so a receiver recomputing the line got a different answer — an
    internally inconsistent document, not merely a lossy one.
    """
    import re
    from decimal import ROUND_HALF_UP

    xml = get_renderer(standard).render(_priced(quantity, price)).content.decode()
    printed_price = re.search(
        r"(?:PriceAmount[^>]*|ChargeAmount|PrezzoUnitario)>([\d.]+)", xml).group(1)
    printed_total = re.search(
        r"(?:LineExtensionAmount[^>]*|LineTotalAmount|PrezzoTotale)>([\d.]+)", xml).group(1)

    expected = (Decimal(quantity) * Decimal(printed_price)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert expected == Decimal(printed_total)


@pytest.mark.parametrize(("quantity", "price"), PRICE_CASES)
@pytest.mark.parametrize("standard", ["ubl", "cii", "fatturapa"])
def test_a_fine_grained_price_survives_the_round_trip(quantity, price, standard):
    from einvoice import parse_invoice

    original = _priced(quantity, price)
    restored = parse_invoice(get_renderer(standard).render(original).content)
    assert restored.total_document() == original.total_document()


def test_ordinary_prices_still_print_with_two_decimals():
    """The fix must not make every invoice look strange."""
    from einvoice.money import fmt_price

    assert fmt_price(Decimal("100")) == "100.00"
    assert fmt_price(Decimal("19.99")) == "19.99"
    assert fmt_price(Decimal("0.5")) == "0.50"
    assert fmt_price(Decimal("0")) == "0.00"


def test_precision_beyond_six_decimals_is_capped():
    """FatturaPA caps the unit price at six decimals; so do we, rather than
    emitting a precision no format accepts."""
    from einvoice.money import fmt_price

    assert fmt_price(Decimal("0.1234567")) == "0.123457"


# ── amounts must be real numbers ───────────────────────────────────────────


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_a_non_finite_amount_is_refused_where_it_enters(value):
    """NaN and the infinities are valid Decimals and arithmetically contagious.

    One of them in a line price used to pass `validate()` untouched and then
    surface either as a document total of NaN or as an `InvalidOperation` from
    inside XML generation — both far from the mistake that caused them.
    """
    from einvoice.errors import ValidationError

    with pytest.raises(ValidationError, match="non finito"):
        LineItem("A", Decimal("1"), Decimal(value), Decimal("22"))


def test_an_unparseable_amount_names_the_value():
    from einvoice.errors import ValidationError

    with pytest.raises(ValidationError, match="non valido"):
        LineItem("A", Decimal("1"), "centoventi", Decimal("22"))


def test_a_non_finite_amount_from_json_is_refused_too():
    """JSON is the realistic entry point for someone else's data."""
    from einvoice import invoice_from_dict
    from einvoice.errors import ValidationError

    payload = {
        "number": "1", "date": "2026-08-24",
        "seller": {"name": "S", "vat_number": "07643520567",
                   "address": {"street": "a", "postcode": "20100",
                               "city": "Milano", "province": "MI"}},
        "buyer": {"name": "B", "vat_number": "09876543217", "sdi_code": "ABCDEFG",
                  "address": {"street": "b", "postcode": "00100",
                              "city": "Roma", "province": "RM"}},
        "lines": [{"description": "A", "quantity": "1",
                   "unit_price": "NaN", "vat_rate": "22"}],
    }
    with pytest.raises(ValidationError):
        invoice_from_dict(payload)


def test_ordinary_amounts_are_unaffected():
    line = LineItem("A", Decimal("2"), Decimal("19.99"), Decimal("22"))
    assert line.total == Decimal("39.98")


# ── money must not silently disappear ──────────────────────────────────────


def _one_line_at_22() -> dict:
    return {
        "number": "AC-1", "date": date(2026, 8, 24),
        "seller": Party(name="S", vat_number="07643520567",
                        address=Address("Via Roma 1", "20100", "Milano", "MI")),
        "buyer": Party(name="B", vat_number="09876543217", sdi_code="ABCDEFG",
                       address=Address("Via Verdi 9", "00100", "Roma", "RM")),
        "lines": [LineItem("A", Decimal("1"), Decimal("100"), Decimal("22"))],
    }


@pytest.mark.parametrize(("rate", "expected_total"), [
    ("22", "183.00"),   # the bucket already exists
    ("5", "174.50"),    # no line uses 5% — the charge needs its own riepilogo
    ("0", "172.00"),    # nor 0%
])
def test_a_document_charge_is_counted_whatever_its_rate(rate, expected_total):
    """A charge at a rate no line uses used to vanish from the totals while
    still being rendered into the XML — an invoice that under-bills by the
    amount of the charge and does not add up.
    """
    invoice = Invoice(**_one_line_at_22(), allowances_charges=[
        AllowanceCharge(Decimal("50"), is_charge=True, vat_rate=Decimal(rate))])

    assert invoice.total_document() == Decimal(expected_total)
    assert invoice.taxable_total() == Decimal("150.00")


def test_a_document_discount_at_an_unused_rate_is_counted_too():
    invoice = Invoice(**_one_line_at_22(), allowances_charges=[
        AllowanceCharge(Decimal("10"), vat_rate=Decimal("5"))])
    assert invoice.taxable_total() == Decimal("90.00")


def test_every_charge_appears_in_exactly_one_vat_bucket():
    """The riepiloghi must account for the whole document."""
    invoice = Invoice(**_one_line_at_22(), allowances_charges=[
        AllowanceCharge(Decimal("50"), is_charge=True, vat_rate=Decimal("5")),
        AllowanceCharge(Decimal("30"), is_charge=True, vat_rate=Decimal("0")),
        AllowanceCharge(Decimal("10"), vat_rate=Decimal("22")),
    ])
    summary = invoice.vat_summary()
    assert sum(v.taxable for v in summary) == invoice.taxable_total()
    assert {str(v.vat_rate) for v in summary} == {"22.00", "5.00", "0.00"}


# ── stamp duty must survive as money, even where it loses its identity ─────


def test_stamp_duty_round_trips_as_an_amount_through_every_format():
    """UBL and CII have no bollo field, so it is rendered as an out-of-scope
    charge. Reading that charge back with no rate sent it to the first line's
    bucket, where it attracted 22% VAT and inflated the document — the value
    was not merely losing its name, it was changing.
    """
    from einvoice import parse_invoice

    original = Invoice(**_one_line_at_22(), stamp_duty=Decimal("2.00"))
    for standard in ("fatturapa", "ubl", "cii"):
        restored = parse_invoice(get_renderer(standard).render(original).content)
        assert restored.total_document() == original.total_document(), standard


def test_an_out_of_scope_charge_keeps_a_zero_rate_not_an_inherited_one():
    from einvoice import parse_invoice

    original = Invoice(**_one_line_at_22(), stamp_duty=Decimal("2.00"))
    restored = parse_invoice(get_renderer("ubl").render(original).content)
    stamp = next(a for a in restored.allowances_charges
                 if a.amount == Decimal("2.00"))
    assert stamp.vat_rate == Decimal("0"), "inherited the line's 22% instead"
