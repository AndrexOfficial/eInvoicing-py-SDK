"""Country coverage: Switzerland, e-invoicing regimes, CIUS selection, advisories."""
from datetime import date
from decimal import Decimal

import pytest

from einvoice import (
    Address,
    Invoice,
    LineItem,
    Party,
    VatNature,
    profile_for,
    renderer_for_country,
)
from einvoice.countries import (
    CIUS_RO_CUSTOMIZATION,
    COUNTRY_PROFILES,
    EU_COUNTRIES,
    MANDATES_VERIFIED_AS_OF,
    NLCIUS_CUSTOMIZATION,
    XRECHNUNG_CUSTOMIZATION,
    supported_countries,
)
from einvoice.errors import ValidationError


def _invoice(country: str, vat: str, *, buyer_country="DE", buyer_vat="136695976",
             rate="20", currency="EUR", **kw) -> Invoice:
    return Invoice(
        number="2026-001", date=date(2026, 8, 24),
        seller=Party(name="Seller", vat_number=vat, country_code=country,
                     address=Address("Main 1", "10115", "City", country=country)),
        buyer=Party(name="Buyer", vat_number=buyer_vat, country_code=buyer_country,
                    address=Address("Second 2", "60311", "Town", country=buyer_country)),
        lines=[LineItem("Consulting", Decimal("1"), Decimal("100"), Decimal(rate))],
        currency=currency, **kw,
    )


# ── coverage ───────────────────────────────────────────────────────────────


def test_all_promised_countries_are_profiled():
    """EU-27 + UK + Switzerland + US — the scope this package claims."""
    codes = set(supported_countries())
    assert codes >= EU_COUNTRIES
    assert {"GB", "CH", "US"} <= codes
    assert len(EU_COUNTRIES) == 27


@pytest.mark.parametrize("code", sorted(COUNTRY_PROFILES))
def test_every_profile_is_internally_consistent(code):
    profile = COUNTRY_PROFILES[code]
    assert profile.code == code
    assert profile.default_standard in ("ubl", "fatturapa")
    assert profile.regime.b2g in ("mandatory", "voluntary", "none")
    assert profile.regime.b2b in ("mandatory", "phased", "voluntary", "none")
    assert profile.eu_member == (code in EU_COUNTRIES)


def test_regulatory_data_is_dated():
    """Mandates go stale; a reader must be able to see how old this is."""
    assert MANDATES_VERIFIED_AS_OF.year >= 2026


# ── Switzerland ────────────────────────────────────────────────────────────


def test_switzerland_is_profiled_not_generic():
    ch = profile_for("CH")
    assert ch.code == "CH"
    assert ch.currency_hint == "CHF"
    assert not ch.eu_member
    assert ch.tax_id_label == "MWST/UID"


def test_swiss_vat_rates_are_the_swiss_ones():
    ch = profile_for("CH")
    assert ch.is_known_vat_rate(Decimal("8.1"))     # standard
    assert ch.is_known_vat_rate(Decimal("2.6"))     # reduced
    assert ch.is_known_vat_rate(Decimal("3.8"))     # accommodation
    assert not ch.is_known_vat_rate(Decimal("22"))  # that is Italy's


def test_swiss_invoice_validates_and_renders():
    inv = _invoice("CH", "CHE-116.281.710", buyer_country="CH",
                   buyer_vat="CHE-105.805.129", rate="8.1", currency="CHF")
    inv.validate()
    xml = renderer_for_country("CH").render(inv).text()
    assert 'schemeID="0183"' in xml
    assert "<cbc:CompanyID>CHE116281710</cbc:CompanyID>" in xml
    assert 'currencyID="CHF"' in xml


def test_swiss_seller_rejects_italian_vat_natures():
    """Switzerland has zero-rated supplies but no Italian Natura code list —
    emitting one would assert a VAT regime that does not exist there."""
    inv = _invoice("CH", "CHE-116.281.710", buyer_country="CH",
                   buyer_vat="CHE-105.805.129", rate="0", currency="CHF")
    inv.lines[0].nature = VatNature.EXEMPT
    with pytest.raises(ValidationError, match="Nature IVA"):
        inv.validate()


def test_swiss_zero_rate_needs_no_nature():
    inv = _invoice("CH", "CHE-116.281.710", buyer_country="CH",
                   buyer_vat="CHE-105.805.129", rate="0", currency="CHF")
    inv.validate()


def test_switzerland_is_not_treated_as_an_intra_eu_supply():
    """It is outside the EU VAT area — an EU seller shipping there is exporting."""
    inv = _invoice("DE", "136695976", buyer_country="CH",
                   buyer_vat="CHE-116.281.710", rate="19")
    codes = {a.code for a in inv.check()}
    assert "export_vat" in codes
    assert "intra_eu_vat" not in codes


# ── CIUS selection ─────────────────────────────────────────────────────────


def test_b2g_selects_the_national_cius():
    """Sending plain Peppol BIS where a CIUS is expected is a rejection."""
    assert renderer_for_country("DE", b2g=True).customization == XRECHNUNG_CUSTOMIZATION
    assert renderer_for_country("NL", b2g=True).customization == NLCIUS_CUSTOMIZATION
    assert renderer_for_country("RO", b2g=True).customization == CIUS_RO_CUSTOMIZATION


def test_without_b2g_the_default_stays_peppol_bis():
    plain = renderer_for_country("DE")
    assert "peppol" in plain.customization


def test_countries_without_a_cius_are_unaffected_by_b2g():
    assert renderer_for_country("FR", b2g=True).customization == \
        renderer_for_country("FR").customization


def test_explicit_xrechnung_flag_still_works():
    assert renderer_for_country("DE", xrechnung=True).customization == XRECHNUNG_CUSTOMIZATION


def test_standard_override_selects_cii_for_france():
    assert renderer_for_country("FR", standard="cii").standard == "cii"


def test_italy_still_defaults_to_fatturapa():
    assert renderer_for_country("IT").standard == "fatturapa"


def test_us_still_gets_the_sales_tax_scheme():
    assert renderer_for_country("US").tax_scheme == "STT"


# ── regimes ────────────────────────────────────────────────────────────────


def test_countries_needing_a_national_syntax_are_flagged_not_hidden():
    """Poland and Spain need a format this package does not emit. Saying so is
    the difference between a limitation and a silent failure."""
    for code in ("PL", "ES"):
        regime = profile_for(code).regime
        assert regime.national_format is not None
        assert not regime.covered_by_this_package


def test_countries_we_do_cover_say_so():
    for code in ("DE", "FR", "NL", "RO", "IT", "CH", "GB"):
        assert profile_for(code).regime.covered_by_this_package, code


def test_italy_regime_points_at_sdi():
    assert profile_for("IT").regime.network == "sdi"
    assert profile_for("IT").regime.b2b == "mandatory"


def test_uk_has_no_mandate():
    gb = profile_for("GB").regime
    assert gb.b2b == "voluntary" and gb.b2g == "voluntary"


# ── advisories ─────────────────────────────────────────────────────────────


def test_check_never_raises_and_returns_findings():
    inv = _invoice("DE", "136695976", buyer_country="FR", buyer_vat="40303265045",
                   rate="19")
    findings = inv.check()
    assert all(hasattr(f, "code") and hasattr(f, "message") for f in findings)
    assert "intra_eu_vat" in {f.code for f in findings}


def test_a_clean_domestic_invoice_has_nothing_to_report():
    inv = _invoice("DE", "136695976", buyer_country="DE", rate="19")
    assert inv.check() == []


def test_implausible_vat_rate_is_flagged_but_not_fatal():
    """2.2 instead of 22 is the classic slip, and it is not a validation error
    anywhere — only a rate nobody uses gives it away."""
    inv = _invoice("IT", "07643520567", buyer_country="IT",
                   buyer_vat="09876543217", rate="2.2")
    inv.validate()                       # still a structurally valid invoice
    assert "country" in {f.code for f in inv.check()}


def test_known_rates_do_not_trigger_the_advisory():
    for rate in ("22", "10", "5", "4"):
        inv = _invoice("IT", "07643520567", buyer_country="IT",
                       buyer_vat="09876543217", rate=rate)
        assert "country" not in {f.code for f in inv.check()}, rate


def test_cross_border_eu_without_a_buyer_vat_is_flagged():
    inv = _invoice("DE", "136695976", buyer_country="FR", buyer_vat=None, rate="0")
    inv.buyer.tax_code = "FR-INDIVIDUAL"
    assert "intra_eu_no_vat_id" in {f.code for f in inv.check()}


def test_a_due_date_before_the_invoice_date_is_flagged():
    from einvoice import Payment

    inv = _invoice("DE", "136695976", buyer_country="DE", rate="19",
                   payments=[Payment(due_date=date(2026, 1, 1))])
    assert "due_date" in {f.code for f in inv.check()}


def test_unusual_currency_is_mentioned():
    inv = _invoice("DE", "136695976", buyer_country="DE", rate="19", currency="JPY")
    assert "currency" in {f.code for f in inv.check()}


def test_advisory_renders_readably():
    inv = _invoice("DE", "136695976", buyer_country="FR", buyer_vat="40303265045",
                   rate="19")
    assert str(inv.check()[0]).startswith("[")
