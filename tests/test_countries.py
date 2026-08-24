"""Country profiles: EU-27 + UK + US — tax-id validation, per-country rules,
renderer selection and the non-IT rendering paths."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest

from einvoice import (
    COUNTRY_PROFILES,
    EU_COUNTRIES,
    XRECHNUNG_CUSTOMIZATION,
    Address,
    Invoice,
    LineItem,
    Party,
    ValidationError,
    VatNature,
    profile_for,
    renderer_for_country,
    validate_tax_id,
)


def _invoice(seller_country: str, vat: str, *, buyer_country: str = "DE",
             **inv_kwargs) -> Invoice:
    seller = Party(
        name="Seller Corp", vat_number=vat, country_code=seller_country,
        address=Address("Main St 1", "10115" if seller_country != "IT" else "20100",
                        "City", country=seller_country),
    )
    # A buyer number that is valid in the country it is placed in — the buyer's
    # id is advisory, not fatal, but a fixture should not model a broken one.
    buyer_vat = {"DE": "136695976", "GB": "980780684", "US": "123456789",
                 "IT": "07643520567", "GR": "094014249"}.get(buyer_country, "136695976")
    buyer = Party(
        name="Buyer GmbH", vat_number=buyer_vat, country_code=buyer_country,
        address=Address("Kaiserstr. 2", "60311", "Frankfurt", country=buyer_country),
    )
    line = LineItem("Consulting", Decimal("1"), Decimal("100"), Decimal("19"))
    return Invoice(number="2026-001", date=date(2026, 7, 16), seller=seller,
                   buyer=buyer, lines=[line], **inv_kwargs)


# ── registry ────────────────────────────────────────────────────────────────

def test_registry_covers_eu27_uk_us():
    assert set(COUNTRY_PROFILES) >= EU_COUNTRIES
    assert len(EU_COUNTRIES) == 27
    assert {"GB", "US"} <= set(COUNTRY_PROFILES)
    for code in EU_COUNTRIES:
        assert COUNTRY_PROFILES[code].eu_member
        assert COUNTRY_PROFILES[code].tax_scheme == "VAT"
    assert not COUNTRY_PROFILES["US"].eu_member
    assert COUNTRY_PROFILES["US"].tax_scheme == "STT"
    assert COUNTRY_PROFILES["IT"].default_standard == "fatturapa"
    assert COUNTRY_PROFILES["DE"].default_standard == "ubl"


# ── tax-id validation ───────────────────────────────────────────────────────

# Real, published identifiers. Made-up numbers used to pass here because the
# check was a regex; now that the check digit is verified they no longer do,
# which is the point — see tests/test_taxid.py for the full matrix.
@pytest.mark.parametrize("country,good", [
    ("IT", "07643520567"), ("DE", "136695976"), ("FR", "40303265045"),
    ("NL", "004495445B01"), ("IE", "6388047V"), ("ES", "A28015865"),
    ("GR", "EL094014249"), ("SE", "556012579001"), ("BE", "0428759497"),
    ("AT", "U13585627"), ("PL", "5260001246"), ("GB", "980780684"),
    ("GB", "GD123"), ("CH", "CHE-116.281.710"), ("US", "12-3456789"),
    ("US", "123456789"),
])
def test_tax_id_valid(country, good):
    assert validate_tax_id(country, good), f"{country}:{good}"


@pytest.mark.parametrize("country,bad", [
    ("IT", "123"), ("DE", "12345678"), ("NL", "123456789"),
    ("GB", "12345"), ("US", "1234"), ("AT", "12345678"),
    # Right shape, impossible arithmetic — a regex cannot tell these apart.
    ("IT", "01234567890"), ("DE", "136695977"), ("CH", "CHE-116.281.711"),
])
def test_tax_id_invalid(country, bad):
    assert not validate_tax_id(country, bad), f"{country}:{bad}"


def test_tax_id_accepts_printed_forms():
    """Numbers arrive from humans: prefixed, spaced, dotted, suffixed."""
    assert validate_tax_id("DE", "DE 136 695 976")
    assert validate_tax_id("IT", "IT07643520567")
    assert validate_tax_id("GR", "EL094014249")
    assert validate_tax_id("CH", "CHE-116.281.710 MWST")
    assert validate_tax_id("FR", "FR 40 303 265 045")


def test_switzerland_is_a_real_profile_now():
    """It used to fall through to the permissive generic profile, which meant
    any string passed as a Swiss VAT number."""
    ch = profile_for("CH")
    assert ch.code == "CH"
    assert ch.currency_hint == "CHF"
    assert ch.tax_id_validation == "checksum"
    assert not ch.eu_member
    assert not validate_tax_id("CH", "not-a-uid")


def test_unknown_country_is_still_permissive():
    generic = profile_for("ZZ")
    assert generic.tax_id_pattern is None
    assert validate_tax_id("ZZ", "whatever-they-use")


# ── per-country invoice validation ─────────────────────────────────────────

def test_german_seller_validates_without_italian_blocks():
    inv = _invoice("DE", "811193231")
    inv.validate()  # no RegimeFiscale / CodiceDestinatario / Natura required


def test_german_seller_zero_rate_needs_no_natura():
    inv = _invoice("DE", "811193231")
    inv.lines[0].vat_rate = Decimal("0")
    inv.validate()  # UBL will emit category Z


def test_italian_seller_keeps_strict_rules():
    inv = _invoice("IT", "01234567897", buyer_country="IT")
    inv.buyer.address.postcode = "603"  # invalid CAP for IT buyer
    inv.buyer.address.country = "IT"
    with pytest.raises(ValidationError):
        inv.validate()


def test_italian_zero_rate_still_requires_natura():
    inv = _invoice("IT", "01234567897")
    inv.seller.address.postcode = "20100"
    inv.lines[0].vat_rate = Decimal("0")
    with pytest.raises(ValidationError, match="Natura"):
        inv.validate()


def test_seller_tax_id_structure_enforced():
    inv = _invoice("DE", "12345")  # malformed USt-IdNr.
    # The message names the identifier the way the country does, so the
    # operator recognises the field being complained about.
    with pytest.raises(ValidationError, match=re.escape("USt-IdNr.")):
        inv.validate()


def test_us_seller_rejects_italian_natures():
    inv = _invoice("US", "12-3456789", buyer_country="US")
    inv.lines[0].vat_rate = Decimal("0")
    inv.lines[0].nature = VatNature.NOT_SUBJECT
    with pytest.raises(ValidationError, match="Nature IVA"):
        inv.validate()


def test_us_seller_plain_sales_tax_invoice_validates():
    inv = _invoice("US", "12-3456789", buyer_country="US", currency="USD")
    inv.lines[0].vat_rate = Decimal("8.875")  # NYC combined rate
    inv.validate()


# ── renderer selection + output ─────────────────────────────────────────────

def test_renderer_for_country_routes():
    assert renderer_for_country("IT").standard == "fatturapa"
    assert renderer_for_country("DE").standard == "ubl"
    assert renderer_for_country("US").standard == "ubl"


def test_xrechnung_customization():
    r = renderer_for_country("DE", xrechnung=True)
    assert r.customization == XRECHNUNG_CUSTOMIZATION
    xml = r.render(_invoice("DE", "811193231")).text()
    assert "xrechnung_3.0" in xml


def test_us_invoice_renders_with_sales_tax_scheme():
    r = renderer_for_country("US")
    assert r.tax_scheme == "STT"
    inv = _invoice("US", "12-3456789", buyer_country="US", currency="USD")
    inv.lines[0].vat_rate = Decimal("8.875")
    xml = r.render(inv).text()
    assert "<cbc:ID>STT</cbc:ID>" in xml
    assert "<cbc:ID>VAT</cbc:ID>" not in xml
    assert 'currencyID="USD"' in xml
    # The EIN goes through unprefixed AND normalized: the printed dash is
    # decoration, and a receiver matches on the exact string.
    assert "<cbc:CompanyID>123456789</cbc:CompanyID>" in xml


def test_uk_invoice_renders_with_gb_vat():
    inv = _invoice("GB", "980780684", buyer_country="GB", currency="GBP")
    inv.buyer.vat_number = "553557881"
    xml = renderer_for_country("GB").render(inv).text()
    assert "<cbc:CompanyID>GB980780684</cbc:CompanyID>" in xml
    assert 'currencyID="GBP"' in xml


def test_greek_vat_uses_el_prefix():
    inv = _invoice("GR", "094014249")
    xml = renderer_for_country("GR").render(inv).text()
    assert "<cbc:CompanyID>EL094014249</cbc:CompanyID>" in xml
    # Peppol endpoint derived with the EL prefix too (EAS 9933)
    assert 'schemeID="9933"' in xml and ">EL094014249<" in xml


def test_peppol_endpoint_all_eu_vat_schemes():
    for code in sorted(EU_COUNTRIES - {"IT"}):
        p = Party(name="X", vat_number="123456789", country_code=code,
                  address=Address("s", "11111", "c", country=code))
        scheme, endpoint = p.peppol_endpoint()
        if scheme is None:
            continue  # registry-based countries need an explicit endpoint
        assert endpoint.startswith("EL" if code == "GR" else code) or scheme in ("0007", "0184", "0216")
