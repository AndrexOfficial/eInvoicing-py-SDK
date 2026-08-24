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
    TransmissionFormat,
    VatNature,
)
from einvoice.errors import ValidationError


def _seller():
    return Party(name="Trattoria da Mario", vat_number="01234567897",
                 address=Address("Via Roma 1", "20100", "Milano", "MI"))


def _buyer():
    return Party(name="ACME Srl", vat_number="09876543217",
                 address=Address("Via Verdi 9", "00100", "Roma", "RM"), sdi_code="ABCDEF1")


def test_from_gross_scorporo():
    ln = LineItem.from_gross("Cena", 1, Decimal("122.00"), 22)
    assert ln.unit_price == Decimal("100.000000")
    assert ln.total == Decimal("100.00")


def test_vat_summary_groups_by_rate():
    inv = Invoice(
        number="1", date=date(2026, 6, 5), seller=_seller(), buyer=_buyer(),
        lines=[
            LineItem.from_gross("Cibo", 1, Decimal("110.00"), 10),
            LineItem.from_gross("Vino", 1, Decimal("122.00"), 22),
        ],
    )
    summ = {str(v.vat_rate): (v.taxable, v.tax) for v in inv.vat_summary()}
    assert summ["10.00"] == (Decimal("100.00"), Decimal("10.00"))
    assert summ["22.00"] == (Decimal("100.00"), Decimal("22.00"))
    assert inv.total_document() == Decimal("232.00")


def test_validate_requires_lines_and_ids():
    inv = Invoice(number="1", date=date(2026, 6, 5), seller=_seller(), buyer=_buyer(), lines=[])
    with pytest.raises(ValidationError):
        inv.validate()


def test_party_requires_fiscal_id():
    p = Party(name="X", address=Address("a", "00100", "Roma", "RM"))
    with pytest.raises(ValidationError):
        p.validate(role="Buyer")


def test_lines_total_vs_taxable_total_with_discounts():
    inv = Invoice(
        number="1", date=date(2026, 6, 5), seller=_seller(), buyer=_buyer(),
        lines=[LineItem("Servizio", Decimal("1"), Decimal("100"), Decimal("22"),
                        discounts=[AllowanceCharge(Decimal("10"))])],
        allowances_charges=[AllowanceCharge(Decimal("5"), vat_rate=Decimal("22"))],
    )
    assert inv.lines[0].total == Decimal("90.00")        # netto sconto riga
    assert inv.lines_total() == Decimal("90.00")
    assert inv.taxable_total() == Decimal("85.00")       # − sconto documento
    assert inv.allowance_total() == Decimal("5.00")
    assert inv.charge_total() == Decimal("0.00")


def test_vat_summary_includes_funds():
    inv = Invoice(
        number="1", date=date(2026, 6, 5), seller=_seller(), buyer=_buyer(),
        lines=[LineItem("Onorario", Decimal("1"), Decimal("100"), Decimal("22"))],
        funds=[SocialSecurityFund("TC04", Decimal("4"), Decimal("4.00"),
                                  vat_rate=Decimal("22"))],
    )
    summ = inv.vat_summary()
    assert len(summ) == 1
    assert summ[0].taxable == Decimal("104.00")          # cassa nell'imponibile
    assert summ[0].tax == Decimal("22.88")


def test_vat_summary_keeps_natures_separate_at_same_rate():
    inv = Invoice(
        number="1", date=date(2026, 6, 5), seller=_seller(), buyer=_buyer(),
        lines=[
            LineItem("Esente", Decimal("1"), Decimal("50"), Decimal("0"), nature=VatNature.EXEMPT),
            LineItem("Escluso", Decimal("1"), Decimal("30"), Decimal("0"), nature=VatNature.EXCLUDED),
        ],
    )
    summ = inv.vat_summary()
    assert [(v.nature, v.taxable) for v in summ] == [
        (VatNature.EXEMPT, Decimal("50.00")),
        (VatNature.EXCLUDED, Decimal("30.00")),
    ]
    assert summ[0].exemption_reason == VatNature.EXEMPT.default_exemption_reason


def test_validate_rejects_invalid_tax_regime():
    seller = _seller()
    seller.tax_regime = "RF99"
    inv = Invoice(number="1", date=date(2026, 6, 5), seller=seller, buyer=_buyer(),
                  lines=[LineItem.from_gross("Cena", 1, Decimal("22.00"), 22)])
    with pytest.raises(ValidationError, match="RegimeFiscale"):
        inv.validate()


def test_validate_rejects_invalid_italian_postcode():
    seller = _seller()
    seller.address.postcode = "201"
    inv = Invoice(number="1", date=date(2026, 6, 5), seller=seller, buyer=_buyer(),
                  lines=[LineItem.from_gross("Cena", 1, Decimal("22.00"), 22)])
    with pytest.raises(ValidationError, match="CAP"):
        inv.validate()


def test_validate_fpa12_requires_6_char_recipient():
    inv = Invoice(number="1", date=date(2026, 6, 5), seller=_seller(), buyer=_buyer(),
                  lines=[LineItem.from_gross("Cena", 1, Decimal("22.00"), 22)],
                  transmission_format=TransmissionFormat.PA)   # sdi_code è 7 char
    with pytest.raises(ValidationError, match="FPA12"):
        inv.validate()


def test_validate_rejects_nature_with_positive_rate():
    inv = Invoice(number="1", date=date(2026, 6, 5), seller=_seller(), buyer=_buyer(),
                  lines=[LineItem("X", Decimal("1"), Decimal("10"), Decimal("22"),
                                  nature=VatNature.EXEMPT)])
    with pytest.raises(ValidationError, match="mutuamente esclusive"):
        inv.validate()


def test_resolved_recipient_foreign_buyer_xxxxxxx():
    inv = Invoice(
        number="1", date=date(2026, 6, 5), seller=_seller(),
        buyer=Party(name="ACME GmbH", vat_number="123456789", country_code="DE",
                    address=Address("Hauptstr. 1", "10115", "Berlin", None, "DE")),
        lines=[LineItem.from_gross("Cena", 1, Decimal("22.00"), 22)],
    )
    code, pec = inv.resolved_recipient()
    assert code == "XXXXXXX"
    assert pec is None


def test_peppol_endpoint_derivation():
    it = Party(name="X", vat_number="01234567897",
               address=Address("a", "20100", "Milano", "MI"))
    assert it.peppol_endpoint() == ("0211", "IT01234567897")
    de = Party(name="Y", vat_number="123456789", country_code="DE",
               address=Address("b", "10115", "Berlin", None, "DE"))
    assert de.peppol_endpoint() == ("9930", "DE123456789")
    # Switzerland: EAS 0183, and the UID is used AS-IS — it carries its own
    # "CHE" prefix, so prefixing the country code again would be wrong.
    ch = Party(name="Z", vat_number="CHE-116.281.710", country_code="CH",
               address=Address("c", "8000", "Zurigo", None, "CH"))
    assert ch.peppol_endpoint() == ("0183", "CHE116281710")
    # A country with no EAS mapping still yields nothing to route on.
    zz = Party(name="Q", vat_number="123456789", country_code="ZZ",
               address=Address("e", "0000", "Nowhere", None, "ZZ"))
    assert zz.peppol_endpoint() == (None, None)
    explicit = Party(name="W", vat_number="01234567897",
                     endpoint_scheme="9906", endpoint_id="IT01234567897",
                     address=Address("d", "20100", "Milano", "MI"))
    assert explicit.peppol_endpoint() == ("9906", "IT01234567897")


def test_resolved_recipient_b2c_falls_back_to_zeroes():
    inv = Invoice(
        number="1", date=date(2026, 6, 5), seller=_seller(),
        buyer=Party(name="Privato", tax_code="RSSMRA80A01H501U",
                    address=Address("Via X", "00100", "Roma", "RM")),
        lines=[LineItem.from_gross("Cena", 1, Decimal("22.00"), 22)],
    )
    code, pec = inv.resolved_recipient()
    assert code == "0000000"
    assert pec is None
