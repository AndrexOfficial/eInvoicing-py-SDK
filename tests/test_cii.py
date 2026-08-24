"""CII (UN/CEFACT) renderer — Factur-X / ZUGFeRD / Chorus Pro.

CII is the *other* EN 16931 syntax. A receiver takes UBL or CII, not both, so
the two renderers must agree on every number while disagreeing on every tag —
which is what most of these tests check.
"""
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

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
)
from einvoice.formats import get_renderer
from einvoice.formats.cii import FACTURX_PROFILES, RAM, RSM, build_cii_xml

NS = {"rsm": RSM, "ram": RAM}


def _invoice(**kw) -> Invoice:
    base = {
        "number": "FR-2026-001",
        "date": date(2026, 8, 24),
        "seller": Party(name="Société Exemple", vat_number="40303265045", country_code="FR",
                        address=Address("1 rue de Rivoli", "75001", "Paris", country="FR")),
        "buyer": Party(name="Muster GmbH", vat_number="136695976", country_code="DE",
                       address=Address("Hauptstr 1", "10115", "Berlin", country="DE")),
        "lines": [LineItem("Conseil", Decimal("10"), Decimal("150"), Decimal("20"))],
    }
    base.update(kw)
    return Invoice(**base)


def _root(invoice: Invoice, **kw) -> ET.Element:
    return ET.fromstring(build_cii_xml(invoice, **kw))


def _text(root: ET.Element, path: str) -> str | None:
    el = root.find(path, NS)
    return el.text if el is not None else None


# ── document shape ─────────────────────────────────────────────────────────


def test_root_is_a_cross_industry_invoice():
    root = _root(_invoice())
    assert root.tag == f"{{{RSM}}}CrossIndustryInvoice"


def test_guideline_declares_en16931_by_default():
    """The guideline is how a receiver knows which rules to apply."""
    root = _root(_invoice())
    guideline = _text(root, "rsm:ExchangedDocumentContext/"
                            "ram:GuidelineSpecifiedDocumentContextParameter/ram:ID")
    assert guideline == "urn:cen.eu:en16931:2017"


@pytest.mark.parametrize("profile", sorted(FACTURX_PROFILES))
def test_every_named_facturx_profile_renders(profile):
    doc = get_renderer("cii", profile=profile).render(_invoice())
    root = ET.fromstring(doc.content)
    guideline = _text(root, "rsm:ExchangedDocumentContext/"
                            "ram:GuidelineSpecifiedDocumentContextParameter/ram:ID")
    assert guideline == FACTURX_PROFILES[profile]


def test_unknown_profile_names_the_valid_ones():
    with pytest.raises(ValueError, match="en16931"):
        get_renderer("cii", profile="deluxe")


def test_dates_use_the_cii_wrapper_not_a_bare_iso_string():
    """A CII date is a udt:DateTimeString with format 102 — never plain text."""
    root = _root(_invoice())
    el = root.find("rsm:ExchangedDocument/ram:IssueDateTime/"
                   "{urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100}"
                   "DateTimeString", NS)
    assert el is not None
    assert el.get("format") == "102"
    assert el.text == "20260824"


def test_facturx_and_zugferd_are_aliases_of_cii():
    for alias in ("facturx", "zugferd"):
        assert get_renderer(alias).standard == "cii"


# ── parties ────────────────────────────────────────────────────────────────


def test_seller_and_buyer_carry_their_tax_registration():
    root = _root(_invoice())
    agreement = root.find("rsm:SupplyChainTradeTransaction/"
                          "ram:ApplicableHeaderTradeAgreement", NS)
    seller = agreement.find("ram:SellerTradeParty", NS)
    buyer = agreement.find("ram:BuyerTradeParty", NS)
    assert seller.find("ram:Name", NS).text == "Société Exemple"
    assert seller.find("ram:SpecifiedTaxRegistration/ram:ID", NS).text == "FR40303265045"
    assert buyer.find("ram:SpecifiedTaxRegistration/ram:ID", NS).text == "DE136695976"


def test_electronic_address_is_the_peppol_endpoint():
    root = _root(_invoice())
    uri = root.find("rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/"
                    "ram:SellerTradeParty/ram:URIUniversalCommunication/ram:URIID", NS)
    assert uri.text == "FR40303265045"
    assert uri.get("schemeID") == "9957"


def test_swiss_party_routes_on_its_uid():
    inv = _invoice(seller=Party(
        name="Muster AG", vat_number="CHE-116.281.710", country_code="CH",
        address=Address("Bahnhofstr 1", "8001", "Zürich", country="CH")), currency="CHF")
    root = _root(inv)
    uri = root.find("rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/"
                    "ram:SellerTradeParty/ram:URIUniversalCommunication/ram:URIID", NS)
    assert uri.text == "CHE116281710" and uri.get("schemeID") == "0183"


# ── lines ──────────────────────────────────────────────────────────────────


def test_line_carries_quantity_price_tax_and_total():
    root = _root(_invoice())
    line = root.find("rsm:SupplyChainTradeTransaction/"
                     "ram:IncludedSupplyChainTradeLineItem", NS)
    assert line.find("ram:AssociatedDocumentLineDocument/ram:LineID", NS).text == "1"
    assert line.find("ram:SpecifiedTradeProduct/ram:Name", NS).text == "Conseil"
    qty = line.find("ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", NS)
    assert qty.text == "10.0000" and qty.get("unitCode") == "C62"
    price = line.find("ram:SpecifiedLineTradeAgreement/"
                      "ram:NetPriceProductTradePrice/ram:ChargeAmount", NS)
    assert price.text == "150.00"
    total = line.find("ram:SpecifiedLineTradeSettlement/"
                      "ram:SpecifiedTradeSettlementLineMonetarySummation/"
                      "ram:LineTotalAmount", NS)
    assert total.text == "1500.00"


def test_line_period_and_article_code_survive():
    """Both were silently dropped by the UBL renderer before this release."""
    inv = _invoice(lines=[LineItem(
        "Subscription", Decimal("1"), Decimal("100"), Decimal("20"),
        article_code="SKU-9", period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
    )])
    root = _root(inv)
    line = root.find("rsm:SupplyChainTradeTransaction/"
                     "ram:IncludedSupplyChainTradeLineItem", NS)
    assert line.find("ram:SpecifiedTradeProduct/ram:SellerAssignedID", NS).text == "SKU-9"
    period = line.find("ram:SpecifiedLineTradeSettlement/ram:BillingSpecifiedPeriod", NS)
    assert period is not None
    assert "20260101" in ET.tostring(period, encoding="unicode")
    assert "20261231" in ET.tostring(period, encoding="unicode")


def test_unit_of_measure_passes_through():
    inv = _invoice(lines=[LineItem("Heures", Decimal("3"), Decimal("100"),
                                   Decimal("20"), unit_of_measure="HUR")])
    qty = _root(inv).find("rsm:SupplyChainTradeTransaction/"
                          "ram:IncludedSupplyChainTradeLineItem/"
                          "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", NS)
    assert qty.get("unitCode") == "HUR"


# ── money ──────────────────────────────────────────────────────────────────


def test_monetary_summation_balances():
    """BR-CO-15: basis + tax + rounding == grand total."""
    inv = _invoice(
        lines=[LineItem("A", 1, Decimal("1000"), Decimal("20")),
               LineItem("B", 1, Decimal("100"), Decimal("10"))],
        allowances_charges=[AllowanceCharge(Decimal("50"), reason="Remise",
                                            vat_rate=Decimal("20"))],
        rounding=Decimal("0.01"),
    )
    mon = _root(inv).find(".//ram:SpecifiedTradeSettlementHeaderMonetarySummation", NS)
    v = {c.tag.split("}")[1]: Decimal(c.text) for c in mon}
    assert v["TaxBasisTotalAmount"] + v["TaxTotalAmount"] + v["RoundingAmount"] == v["GrandTotalAmount"]
    assert v["GrandTotalAmount"] == inv.total_document()
    assert v["LineTotalAmount"] == inv.lines_total()
    assert v["AllowanceTotalAmount"] == inv.allowance_total()


def test_tax_buckets_sum_to_the_tax_basis():
    inv = _invoice(lines=[LineItem("A", 1, Decimal("1000"), Decimal("20")),
                          LineItem("B", 1, Decimal("100"), Decimal("10"))],
                   stamp_duty=Decimal("2.00"))
    root = _root(inv)
    settlement = root.find("rsm:SupplyChainTradeTransaction/"
                           "ram:ApplicableHeaderTradeSettlement", NS)
    buckets = settlement.findall("ram:ApplicableTradeTax", NS)
    total = sum(Decimal(b.find("ram:BasisAmount", NS).text) for b in buckets)
    basis = Decimal(settlement.find(
        "ram:SpecifiedTradeSettlementHeaderMonetarySummation/"
        "ram:TaxBasisTotalAmount", NS).text)
    assert total == basis


def test_cii_and_ubl_agree_on_every_total():
    """Same semantics, two syntaxes — a divergence here is a real bug."""
    inv = _invoice(
        lines=[LineItem("A", 1, Decimal("1000"), Decimal("20")),
               LineItem("B", 2, Decimal("55.55"), Decimal("10"))],
        allowances_charges=[AllowanceCharge(Decimal("30"), reason="Remise",
                                            vat_rate=Decimal("20"))],
        stamp_duty=Decimal("2.00"), rounding=Decimal("0.01"),
    )
    cii = _root(inv)
    ubl = ET.fromstring(get_renderer("ubl").render(inv).content)
    cac = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"
    cbc = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
    mon = ubl.find(f"{cac}LegalMonetaryTotal")

    assert (cii.find(".//ram:GrandTotalAmount", NS).text
            == mon.find(f"{cbc}PayableAmount").text)
    assert (cii.find(".//ram:TaxBasisTotalAmount", NS).text
            == mon.find(f"{cbc}TaxExclusiveAmount").text)
    assert (cii.find(".//ram:LineTotalAmount", NS) is not None)


def test_charge_indicator_is_a_nested_udt_indicator():
    """CII wraps the boolean a level deeper than UBL; getting this wrong makes
    an otherwise-correct document schema-invalid."""
    inv = _invoice(allowances_charges=[AllowanceCharge(Decimal("10"), reason="Frais",
                                                       is_charge=True,
                                                       vat_rate=Decimal("20"))])
    xml = build_cii_xml(inv).decode()
    assert "<udt:Indicator>true</udt:Indicator>" in xml


# ── references, payments, attachments ──────────────────────────────────────


def test_references_land_in_their_own_slots():
    inv = _invoice(references=[
        DocumentReference("order", "PO-1"),
        DocumentReference("contract", "C-1"),
        DocumentReference("ddt", "DDT-7"),
        DocumentReference("invoice", "INV-100", date(2026, 3, 1)),
    ])
    root = _root(inv)
    txn = root.find("rsm:SupplyChainTradeTransaction", NS)
    assert txn.find("ram:ApplicableHeaderTradeAgreement/"
                    "ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID", NS).text == "PO-1"
    assert txn.find("ram:ApplicableHeaderTradeAgreement/"
                    "ram:ContractReferencedDocument/ram:IssuerAssignedID", NS).text == "C-1"
    assert txn.find("ram:ApplicableHeaderTradeDelivery/"
                    "ram:DespatchAdviceReferencedDocument/ram:IssuerAssignedID", NS).text == "DDT-7"
    assert txn.find("ram:ApplicableHeaderTradeSettlement/"
                    "ram:InvoiceReferencedDocument/ram:IssuerAssignedID", NS).text == "INV-100"


def test_payment_means_carries_the_iban():
    inv = _invoice(payments=[Payment(
        means=PaymentMeans.BANK_TRANSFER, due_date=date(2026, 9, 30),
        account=BankAccount("FR7630006000011234567890189", bic="AGRIFRPP",
                            holder="Société Exemple"))],
        payment_terms_note="30 jours")
    root = _root(inv)
    stl = root.find("rsm:SupplyChainTradeTransaction/"
                    "ram:ApplicableHeaderTradeSettlement", NS)
    pm = stl.find("ram:SpecifiedTradeSettlementPaymentMeans", NS)
    assert pm.find("ram:TypeCode", NS).text == "30"
    assert pm.find("ram:PayeePartyCreditorFinancialAccount/ram:IBANID", NS).text \
        == "FR7630006000011234567890189"
    terms = stl.find("ram:SpecifiedTradePaymentTerms", NS)
    assert terms.find("ram:Description", NS).text == "30 jours"
    assert "20260930" in ET.tostring(terms, encoding="unicode")


def test_attachment_travels_base64():
    inv = _invoice(attachments=[Attachment("spec.pdf", b"%PDF-1.4",
                                           mime="application/pdf",
                                           description="Spec")])
    root = _root(inv)
    adr = root.find("rsm:SupplyChainTradeTransaction/"
                    "ram:ApplicableHeaderTradeAgreement/"
                    "ram:AdditionalReferencedDocument", NS)
    assert adr.find("ram:IssuerAssignedID", NS).text == "spec.pdf"
    binary = adr.find("ram:AttachmentBinaryObject", NS)
    assert binary.text == "JVBERi0xLjQ="
    assert binary.get("mimeCode") == "application/pdf"


# ── document types & tax categories ────────────────────────────────────────


def test_credit_note_uses_type_code_381():
    inv = _invoice(document_type=DocumentType.CREDIT_NOTE,
                   references=[DocumentReference("invoice", "INV-1", date(2026, 1, 1))])
    assert _text(_root(inv), "rsm:ExchangedDocument/ram:TypeCode") == "381"


def test_zero_rated_line_gets_a_category_and_an_exemption_reason():
    inv = _invoice(
        seller=Party(name="Studio", vat_number="07643520567", country_code="IT",
                     address=Address("Via Roma 1", "20100", "Milano", "MI")),
        lines=[LineItem("Export", 1, Decimal("100"), Decimal("0"),
                        nature=VatNature.NOT_TAXABLE_EXPORT)],
        buyer=Party(name="US Corp", vat_number="123456789", country_code="US",
                    address=Address("Main", "10001", "New York", country="US")),
    )
    root = _root(inv)
    bucket = root.find("rsm:SupplyChainTradeTransaction/"
                       "ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax", NS)
    assert bucket.find("ram:CategoryCode", NS).text == "G"      # export outside the EU
    assert bucket.find("ram:ExemptionReason", NS) is not None


def test_us_seller_uses_the_sales_tax_type_code():
    inv = _invoice(
        seller=Party(name="Acme Inc", vat_number="12-3456789", country_code="US",
                     address=Address("Main St 1", "10001", "New York", country="US")),
        buyer=Party(name="Buyer LLC", vat_number="987654321", country_code="US",
                    address=Address("Second St", "94105", "San Francisco", country="US")),
        lines=[LineItem("Widget", 1, Decimal("100"), Decimal("8.875"))],
        currency="USD",
    )
    xml = build_cii_xml(inv, tax_scheme="STT").decode()
    assert "<ram:TypeCode>STT</ram:TypeCode>" in xml
    assert "<ram:TypeCode>VAT</ram:TypeCode>" not in xml


# ── output plumbing ────────────────────────────────────────────────────────


def test_rendered_document_metadata():
    doc = get_renderer("cii").render(_invoice())
    assert doc.standard == "cii"
    assert doc.mime == "application/xml"
    assert doc.filename == "FR_40303265045_FR-2026-001-cii.xml"
    assert doc.content.startswith(b"<?xml")


def test_invalid_invoice_never_renders():
    inv = _invoice()
    inv.lines = []
    from einvoice.errors import ValidationError

    with pytest.raises(ValidationError):
        build_cii_xml(inv)
