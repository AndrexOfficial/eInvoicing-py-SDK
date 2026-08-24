"""Every profiled country, end to end.

The package claims coverage of the EU-27, the UK, Switzerland and the US. This
file is what makes that claim testable rather than aspirational: for each
country it builds a plausible domestic invoice and renders it through the
country's own default renderer, then re-renders through every other syntax.

It catches the failure mode that unit tests miss — a profile that is internally
consistent but blows up the moment a real document goes through it.
"""
from datetime import date
from decimal import Decimal

import pytest

from einvoice import (
    Address,
    Invoice,
    LineItem,
    Party,
    profile_for,
    renderer_for_country,
)
from einvoice.countries import COUNTRY_PROFILES
from einvoice.formats import get_renderer
from einvoice.taxid import CHECKSUM_COUNTRIES
from test_taxid import REAL_NUMBERS

#: A tax id per country: the real one where we have it, otherwise something
#: that satisfies that country's structural pattern.
STRUCTURAL_IDS = {
    "BG": "175074752", "CY": "10259033P", "CZ": "25123891", "ES": "A28015865",
    "LT": "119511515", "LV": "40003032949", "MT": "15121333",
    "NL": "004495445B01", "RO": "14388698", "US": "12-3456789",
}


def _tax_id(code: str) -> str:
    return REAL_NUMBERS.get(code) or STRUCTURAL_IDS[code]


def _domestic_invoice(code: str) -> Invoice:
    """A plausible domestic invoice for a seller in ``code``."""
    profile = profile_for(code)
    # The standard rate, so nothing trips the "unknown rate" advisory.
    rate = Decimal(profile.vat_rates[0]) if profile.vat_rates else Decimal("20")
    postcode = "20100" if code == "IT" else "10115"
    party = {"country_code": code}
    seller = Party(name="Seller SA", vat_number=_tax_id(code),
                   address=Address("Main 1", postcode, "City", country=code), **party)
    buyer = Party(name="Buyer SA", vat_number=_tax_id(code),
                  address=Address("Second 2", postcode, "Town", country=code),
                  sdi_code="ABCDEFG" if code == "IT" else None, **party)
    return Invoice(
        number="2026-0001", date=date(2026, 8, 24), seller=seller, buyer=buyer,
        lines=[LineItem("Service", Decimal("2"), Decimal("100"), rate)],
        currency=profile.currency_hint,
    )


ALL_COUNTRIES = sorted(COUNTRY_PROFILES)


@pytest.mark.parametrize("code", ALL_COUNTRIES)
def test_domestic_invoice_validates(code):
    _domestic_invoice(code).validate()


@pytest.mark.parametrize("code", ALL_COUNTRIES)
def test_domestic_invoice_renders_through_the_country_default(code):
    invoice = _domestic_invoice(code)
    doc = renderer_for_country(code).render(invoice)
    assert doc.content.startswith(b"<?xml")
    assert doc.filename.endswith(".xml")
    # The filename must never contain a stringified None — the bug that
    # produced "GBNone_00001-ubl.xml".
    assert "None" not in doc.filename


@pytest.mark.parametrize("code", ALL_COUNTRIES)
@pytest.mark.parametrize("standard", ["ubl", "cii"])
def test_every_country_renders_in_both_en16931_syntaxes(code, standard):
    """UBL and CII are interchangeable semantically; both must work everywhere."""
    invoice = _domestic_invoice(code)
    profile = profile_for(code)
    kwargs = {} if profile.tax_scheme == "VAT" else {"tax_scheme": profile.tax_scheme}
    doc = get_renderer(standard, **kwargs).render(invoice)
    assert doc.standard == standard
    assert b"<?xml" in doc.content


@pytest.mark.parametrize("code", ALL_COUNTRIES)
def test_the_two_syntaxes_agree_on_the_payable_total(code):
    """A divergence between UBL and CII on the money is always a bug."""
    from xml.etree import ElementTree as ET

    from einvoice.formats.cii import RAM

    invoice = _domestic_invoice(code)
    profile = profile_for(code)
    kwargs = {} if profile.tax_scheme == "VAT" else {"tax_scheme": profile.tax_scheme}

    cii = ET.fromstring(get_renderer("cii", **kwargs).render(invoice).content)
    ubl = ET.fromstring(get_renderer("ubl", **kwargs).render(invoice).content)
    cbc = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
    cac = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"

    cii_total = cii.find(f".//{{{RAM}}}GrandTotalAmount").text
    ubl_total = ubl.find(f"{cac}LegalMonetaryTotal/{cbc}PayableAmount").text
    assert cii_total == ubl_total == f"{invoice.total_document():.2f}"


@pytest.mark.parametrize("code", ALL_COUNTRIES)
def test_a_domestic_invoice_at_the_standard_rate_raises_no_advisories(code):
    """If the country data is right, the ordinary case is quiet."""
    assert _domestic_invoice(code).check() == []


@pytest.mark.parametrize("code", sorted(CHECKSUM_COUNTRIES))
def test_a_typo_in_the_seller_id_stops_the_document(code):
    """The point of the checksum work: a bad own-VAT number never renders."""
    from einvoice.errors import ValidationError

    invoice = _domestic_invoice(code)
    normalized = profile_for(code).normalize_tax_id(_tax_id(code))
    index = next(i for i, ch in enumerate(normalized) if ch.isdigit())
    invoice.seller.vat_number = (
        normalized[:index] + str((int(normalized[index]) + 1) % 10) + normalized[index + 1:]
    )
    with pytest.raises(ValidationError):
        invoice.validate()


@pytest.mark.parametrize("code", ALL_COUNTRIES)
def test_peppol_routing_is_derivable_wherever_a_scheme_exists(code):
    """A document nobody can route is a document nobody receives."""
    invoice = _domestic_invoice(code)
    scheme, endpoint = invoice.seller.peppol_endpoint()
    if code == "US":
        pytest.skip("US uses DBNAlliance, not a Peppol EAS")
    assert scheme and endpoint, f"{code}: no Peppol endpoint derivable"
    assert "None" not in endpoint
