from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from einvoice import Address, Invoice, LineItem, Party, build_ubl_xml
from einvoice.formats.ubl import CAC, CBC, INV_NS

NS = {"i": INV_NS, "cbc": CBC, "cac": CAC}


def _invoice() -> Invoice:
    return Invoice(
        number="2026/0001", date=date(2026, 6, 5),
        seller=Party(name="Trattoria da Mario", vat_number="01234567897",
                     address=Address("Via Roma 1", "20100", "Milano", "MI")),
        buyer=Party(name="ACME Srl", vat_number="09876543217",
                    address=Address("Via Verdi 9", "00100", "Roma", "RM")),
        lines=[
            LineItem.from_gross("Cibo", 1, Decimal("110.00"), 10),
            LineItem.from_gross("Vino", 1, Decimal("122.00"), 22),
        ],
    )


def test_ubl_root_and_customization():
    root = ET.fromstring(build_ubl_xml(_invoice()))
    assert root.tag == f"{{{INV_NS}}}Invoice"
    assert root.findtext("cbc:CustomizationID", namespaces=NS).startswith("urn:cen.eu:en16931")
    assert root.findtext("cbc:InvoiceTypeCode", namespaces=NS) == "380"
    assert root.findtext("cbc:DocumentCurrencyCode", namespaces=NS) == "EUR"


def test_ubl_parties_and_vat():
    root = ET.fromstring(build_ubl_xml(_invoice()))
    supplier = root.find("cac:AccountingSupplierParty/cac:Party", NS)
    assert supplier.findtext("cac:PartyLegalEntity/cbc:RegistrationName", namespaces=NS) == "Trattoria da Mario"
    assert supplier.findtext("cac:PartyTaxScheme/cbc:CompanyID", namespaces=NS) == "IT01234567897"


def test_ubl_tax_and_totals():
    root = ET.fromstring(build_ubl_xml(_invoice()))
    subtotals = root.findall("cac:TaxTotal/cac:TaxSubtotal", NS)
    by_rate = {s.findtext("cac:TaxCategory/cbc:Percent", namespaces=NS):
               (s.findtext("cbc:TaxableAmount", namespaces=NS), s.findtext("cbc:TaxAmount", namespaces=NS))
               for s in subtotals}
    assert by_rate["10.00"] == ("100.00", "10.00")
    assert by_rate["22.00"] == ("100.00", "22.00")
    mon = root.find("cac:LegalMonetaryTotal", NS)
    assert mon.findtext("cbc:PayableAmount", namespaces=NS) == "232.00"
    assert len(root.findall("cac:InvoiceLine", NS)) == 2


from einvoice import (
    AllowanceCharge,
    DocumentReference,
    DocumentType,
    VatNature,
)
from einvoice import (
    Party as _Party,
)
from einvoice.formats.ubl import CN_NS


def test_buyer_reference_always_present():
    inv = _invoice()
    root = ET.fromstring(build_ubl_xml(inv))
    assert root.findtext("cbc:BuyerReference", namespaces=NS) == inv.number  # fallback
    inv.buyer_reference = "PO-77"
    root = ET.fromstring(build_ubl_xml(inv))
    assert root.findtext("cbc:BuyerReference", namespaces=NS) == "PO-77"
    inv.buyer_reference = None
    inv.references = [DocumentReference("order", "ORD-9")]
    root = ET.fromstring(build_ubl_xml(inv))
    assert root.find("cbc:BuyerReference", NS) is None
    assert root.findtext("cac:OrderReference/cbc:ID", namespaces=NS) == "ORD-9"


def test_credit_note_root_and_lines():
    inv = _invoice()
    inv.document_type = DocumentType.CREDIT_NOTE
    root = ET.fromstring(build_ubl_xml(inv))
    assert root.tag == f"{{{CN_NS}}}CreditNote"
    assert root.findtext("cbc:CreditNoteTypeCode", namespaces=NS) == "381"
    assert root.find("cbc:InvoiceTypeCode", NS) is None
    lines = root.findall("cac:CreditNoteLine", NS)
    assert len(lines) == 2
    assert lines[0].find("cbc:CreditedQuantity", NS) is not None
    assert root.findtext("cbc:BuyerReference", namespaces=NS) == inv.number


def test_endpoint_id_derivation_and_omission():
    inv = _invoice()
    inv.buyer = _Party(name="ACME GmbH", vat_number="123456789", country_code="DE",
                       address=Address("Hauptstr. 1", "10115", "Berlin", None, "DE"))
    root = ET.fromstring(build_ubl_xml(inv))
    sup = root.find("cac:AccountingSupplierParty/cac:Party/cbc:EndpointID", NS)
    assert sup.text == "IT01234567897" and sup.get("schemeID") == "0211"
    cus = root.find("cac:AccountingCustomerParty/cac:Party/cbc:EndpointID", NS)
    assert cus.text == "DE123456789" and cus.get("schemeID") == "9930"
    # Switzerland routes on EAS 0183 with the bare UID.
    inv.buyer = _Party(name="Swiss AG", vat_number="CHE-116.281.710", country_code="CH",
                       address=Address("Bahnhofstr. 1", "8000", "Zurigo", None, "CH"))
    root = ET.fromstring(build_ubl_xml(inv))
    ch = root.find("cac:AccountingCustomerParty/cac:Party/cbc:EndpointID", NS)
    assert ch.text == "CHE116281710" and ch.get("schemeID") == "0183"
    # A country with no EAS mapping omits the element entirely.
    inv.buyer = _Party(name="Nowhere Ltd", vat_number="123456789", country_code="ZZ",
                       address=Address("Road 1", "0000", "Nowhere", None, "ZZ"))
    root = ET.fromstring(build_ubl_xml(inv))
    assert root.find("cac:AccountingCustomerParty/cac:Party/cbc:EndpointID", NS) is None


def test_tax_categories_with_exemption_reasons():
    inv = _invoice()
    inv.lines = [
        LineItem("Std", Decimal("1"), Decimal("100"), Decimal("22")),
        LineItem("Export", Decimal("1"), Decimal("10"), Decimal("0"),
                 nature=VatNature.NOT_TAXABLE_EXPORT),
        LineItem("IntraUE", Decimal("1"), Decimal("10"), Decimal("0"),
                 nature=VatNature.NOT_TAXABLE),
        LineItem("Esente", Decimal("1"), Decimal("10"), Decimal("0"),
                 nature=VatNature.EXEMPT, exemption_reason="Esente art. 10 n. 18"),
        LineItem("RC", Decimal("1"), Decimal("10"), Decimal("0"),
                 nature=VatNature.REVERSE_CHARGE),
        LineItem("Escluso", Decimal("1"), Decimal("10"), Decimal("0"),
                 nature=VatNature.EXCLUDED),
    ]
    root = ET.fromstring(build_ubl_xml(inv))
    cats = {}
    for sub in root.findall("cac:TaxTotal/cac:TaxSubtotal", NS):
        cat = sub.find("cac:TaxCategory", NS)
        cats[cat.findtext("cbc:ID", namespaces=NS)] = cat
    assert set(cats) == {"S", "G", "K", "E", "AE", "O"}
    assert cats["S"].find("cbc:TaxExemptionReason", NS) is None
    for c in ("G", "K", "E", "AE", "O"):
        assert cats[c].findtext("cbc:TaxExemptionReason", namespaces=NS)
    assert cats["E"].findtext("cbc:TaxExemptionReason", namespaces=NS) == "Esente art. 10 n. 18"
    assert cats["O"].find("cbc:Percent", NS) is None          # O: niente Percent
    assert cats["G"].findtext("cbc:Percent", namespaces=NS) == "0.00"


def test_monetary_totals_balance_with_discounts_stamp_and_rounding():
    inv = _invoice()
    inv.lines = [
        LineItem("A", Decimal("1"), Decimal("100"), Decimal("22")),
        LineItem("B", Decimal("1"), Decimal("50"), Decimal("10")),
    ]
    inv.allowances_charges = [AllowanceCharge(Decimal("10"), vat_rate=Decimal("22"),
                                              reason="Sconto")]
    inv.stamp_duty = Decimal("2.00")
    inv.rounding = Decimal("0.02")
    root = ET.fromstring(build_ubl_xml(inv))
    mon = root.find("cac:LegalMonetaryTotal", NS)
    t = lambda tag: mon.findtext(tag, namespaces=NS)
    # BR-CO-10: somma dei LineExtensionAmount di riga
    line_sum = sum(Decimal(l.findtext("cbc:LineExtensionAmount", namespaces=NS))
                   for l in root.findall("cac:InvoiceLine", NS))
    assert t("cbc:LineExtensionAmount") == "150.00" == f"{line_sum:.2f}"
    assert t("cbc:AllowanceTotalAmount") == "10.00"
    assert t("cbc:ChargeTotalAmount") == "2.00"               # bollo come charge
    # BR-CO-13: 150 − 10 + 2
    assert t("cbc:TaxExclusiveAmount") == "142.00"
    # BR-CO-15: TaxExclusive + IVA (19.80 + 5.00)
    assert root.findtext("cac:TaxTotal/cbc:TaxAmount", namespaces=NS) == "24.80"
    assert t("cbc:TaxInclusiveAmount") == "166.80"
    assert t("cbc:PayableRoundingAmount") == "0.02"
    assert t("cbc:PayableAmount") == "166.82"
    # Il bollo ha il suo riepilogo O a imposta zero
    o_sub = [s for s in root.findall("cac:TaxTotal/cac:TaxSubtotal", NS)
             if s.findtext("cac:TaxCategory/cbc:ID", namespaces=NS) == "O"][0]
    assert o_sub.findtext("cbc:TaxableAmount", namespaces=NS) == "2.00"
    assert o_sub.findtext("cbc:TaxAmount", namespaces=NS) == "0.00"


def test_line_discount_and_payment_terms():
    inv = _invoice()
    inv.lines = [LineItem("Servizio", Decimal("1"), Decimal("100"), Decimal("22"),
                          discounts=[AllowanceCharge(Decimal("10"), reason="Promo")])]
    inv.payment_terms_note = "30 gg data fattura"
    root = ET.fromstring(build_ubl_xml(inv))
    line = root.find("cac:InvoiceLine", NS)
    assert line.findtext("cbc:LineExtensionAmount", namespaces=NS) == "90.00"
    lac = line.find("cac:AllowanceCharge", NS)
    assert lac.findtext("cbc:ChargeIndicator", namespaces=NS) == "false"
    assert lac.findtext("cbc:Amount", namespaces=NS) == "10.00"
    assert root.findtext("cac:PaymentTerms/cbc:Note", namespaces=NS) == "30 gg data fattura"
