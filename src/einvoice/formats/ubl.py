"""UBL 2.1 renderer — Peppol BIS Billing 3.0 (EN 16931).

The European semantic model (EN 16931) in OASIS UBL syntax, the format used on
the PEPPOL network and by most EU B2G/cross-border flows. This covers the
mandatory core; national CIUS (XRechnung, etc.) layer extra rules on top and
can be added as thin subclasses that tweak ``CustomizationID`` + a few
constraints.

Credit notes (``DocumentType.is_credit_note``) are emitted on the dedicated
UBL ``CreditNote-2`` root with ``cbc:CreditNoteTypeCode`` and
``cac:CreditNoteLine``/``cbc:CreditedQuantity``, as required by Peppol.

Semantic mapping of the Italian-only blocks (documented contracts):

* ``BuyerReference`` (BT-10) is never absent (PEPPOL-EN16931-R003): explicit
  ``invoice.buyer_reference``, else an ``OrderReference`` from a
  ``kind=="order"`` reference, else the invoice number as fallback.
* ``stamp_duty`` (bollo) is rendered as a document-level *charge* with VAT
  category "O" so the monetary totals balance (BR-CO-13/15).
* ``funds`` (cassa previdenziale) are rendered as document-level *charges* in
  their VAT category — they already join the VAT breakdown via
  ``vat_summary()``, so BR-CO-13 holds.
* ``PayableAmount`` is the document total (EN 16931 does not model the Italian
  ritenuta; withholdings do not reduce the payable amount here).
* ``InvoicedQuantity/@unitCode`` passes ``unit_of_measure`` through verbatim
  (default ``C62``); for valid Peppol output it must be a UNECE Rec. 20 code.
"""
from __future__ import annotations

import base64
from decimal import Decimal
from xml.etree import ElementTree as ET

from ..models import Invoice, Party, VatNature
from ..money import D, fmt2, fmt_price, q2
from ..naming import safe_filename
from .base import InvoiceRenderer, RenderedDocument

INV_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CN_NS = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"

ET.register_namespace("", INV_NS)
ET.register_namespace("cbc", CBC)
ET.register_namespace("cac", CAC)

_CUSTOMIZATION = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
_PROFILE = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
_NS = {"cbc": CBC, "cac": CAC}


def _e(parent: ET.Element, qname: str, text=None, **attrib) -> ET.Element:
    prefix, _, local = qname.partition(":")
    tag = f"{{{_NS[prefix]}}}{local}" if local else f"{{{INV_NS}}}{prefix}"
    el = ET.SubElement(parent, tag, {k: str(v) for k, v in attrib.items()})
    if text is not None:
        el.text = str(text)
    return el


def _tax_category(rate: Decimal, nature: VatNature | None) -> str:
    """EN 16931 (UNCL 5305) VAT category: S for positive rates, Z for plain
    zero-rated, otherwise mapped from the Italian Natura."""
    if rate > 0:
        return "S"
    if nature is None:
        return "Z"
    return nature.en16931_category


def _tax_cat_el(parent: ET.Element, container: str, category: str,
                rate: Decimal | None, reason: str | None = None,
                tax_scheme: str = "VAT") -> None:
    """``cac:TaxCategory``/``cac:ClassifiedTaxCategory``. Category "O"
    (outside scope of VAT) carries no ``cbc:Percent``."""
    cat = _e(parent, container)
    _e(cat, "cbc:ID", category)
    if category != "O" and rate is not None:
        _e(cat, "cbc:Percent", fmt2(rate))
    if reason:
        _e(cat, "cbc:TaxExemptionReason", reason)
    _e(_e(cat, "cac:TaxScheme"), "cbc:ID", tax_scheme)


def _party(parent: ET.Element, party: Party, tax_scheme: str = "VAT") -> None:
    p = _e(parent, "cac:Party")
    scheme, endpoint = party.peppol_endpoint()
    if scheme and endpoint:
        _e(p, "cbc:EndpointID", endpoint, schemeID=scheme)
    # BT-29: the party's own identifier. Emitted whenever there is a tax code,
    # not only when the VAT number is absent — an Italian party routinely has
    # both, and dropping the codice fiscale loses the one that identifies a
    # natural person.
    if party.tax_code:
        _e(_e(p, "cac:PartyIdentification"), "cbc:ID", party.tax_code)
    addr_ = party.postal_address
    addr = _e(p, "cac:PostalAddress")
    _e(addr, "cbc:StreetName", addr_.street)
    _e(addr, "cbc:CityName", addr_.city)
    _e(addr, "cbc:PostalZone", addr_.postcode)
    if addr_.province:
        _e(addr, "cbc:CountrySubentity", addr_.province)
    country = _e(addr, "cac:Country")
    _e(country, "cbc:IdentificationCode", addr_.country)
    if party.vat_number:
        pts = _e(p, "cac:PartyTaxScheme")
        _e(pts, "cbc:CompanyID", party.tax_company_id())
        _e(_e(pts, "cac:TaxScheme"), "cbc:ID", tax_scheme)
    ple = _e(p, "cac:PartyLegalEntity")
    _e(ple, "cbc:RegistrationName", party.display_name())
    if party.registration_number:
        _e(ple, "cbc:CompanyID", party.registration_number)
    # BG-6 / BG-9 contact. The email is how a human chases a query about the
    # invoice, and dropping it silently made the document less useful than the
    # data it was built from. Sequence: Contact follows PartyLegalEntity.
    if party.email or party.pec:
        _e(_e(p, "cac:Contact"), "cbc:ElectronicMail", party.email or party.pec)


def _allowance_charge(parent: ET.Element, *, is_charge: bool, amount, currency: str,
                      reason: str | None, category: str, rate,
                      tax_scheme: str = "VAT") -> None:
    ac = _e(parent, "cac:AllowanceCharge")
    _e(ac, "cbc:ChargeIndicator", "true" if is_charge else "false")
    if reason:
        _e(ac, "cbc:AllowanceChargeReason", reason)
    _e(ac, "cbc:Amount", fmt2(amount), currencyID=currency)
    _tax_cat_el(ac, "cac:TaxCategory", category, rate, tax_scheme=tax_scheme)


def build_ubl_xml(invoice: Invoice, *, customization: str = _CUSTOMIZATION,
                  tax_scheme: str = "VAT") -> bytes:
    invoice.validate()
    cur = invoice.currency
    is_cn = invoice.document_type.is_credit_note
    doc_ns = CN_NS if is_cn else INV_NS
    ET.register_namespace("", doc_ns)
    root = ET.Element(f"{{{doc_ns}}}{'CreditNote' if is_cn else 'Invoice'}")

    summary = invoice.vat_summary()

    def category_for_rate(rate) -> tuple[str, Decimal]:
        """Category + rate of the VAT bucket a document allowance/charge
        belongs to (first bucket with that rate, mirroring vat_summary)."""
        rate = D(rate)
        vs = next((v for v in summary if v.vat_rate == rate), None)
        nature = vs.nature if vs else None
        return _tax_category(rate, nature), rate

    _e(root, "cbc:CustomizationID", customization)
    _e(root, "cbc:ProfileID", _PROFILE)
    _e(root, "cbc:ID", invoice.number)
    _e(root, "cbc:IssueDate", invoice.date.isoformat())
    due = next((p.due_date for p in invoice.payments if p.due_date), None)
    if due and not is_cn:
        # UBL 2.1 CreditNote has no document-level DueDate.
        _e(root, "cbc:DueDate", due.isoformat())
    type_tag = "cbc:CreditNoteTypeCode" if is_cn else "cbc:InvoiceTypeCode"
    _e(root, type_tag, invoice.document_type.uncl1001)
    if invoice.causale:
        _e(root, "cbc:Note", invoice.causale)
    _e(root, "cbc:DocumentCurrencyCode", cur)

    order_ref = next((r for r in invoice.references if r.kind == "order"), None)
    if invoice.buyer_reference:
        _e(root, "cbc:BuyerReference", invoice.buyer_reference)
    elif order_ref is None:
        _e(root, "cbc:BuyerReference", invoice.number)
    if order_ref is not None:
        _e(_e(root, "cac:OrderReference"), "cbc:ID", order_ref.doc_id)

    # Preceding invoice(s) — BG-3. EN 16931 BR-55 requires one on a credit
    # note: without it the receiver cannot tell which invoice is being undone.
    for ref in (r for r in invoice.references if r.kind == "invoice"):
        br = _e(root, "cac:BillingReference")
        idoc = _e(br, "cac:InvoiceDocumentReference")
        _e(idoc, "cbc:ID", ref.doc_id)
        if ref.date:
            _e(idoc, "cbc:IssueDate", ref.date.isoformat())
    for ref in (r for r in invoice.references if r.kind == "ddt"):
        _e(_e(root, "cac:DespatchDocumentReference"), "cbc:ID", ref.doc_id)
    for ref in (r for r in invoice.references if r.kind == "contract"):
        _e(_e(root, "cac:ContractDocumentReference"), "cbc:ID", ref.doc_id)

    # Attachments — BG-24. The bytes travel base64 inside the document.
    for att in invoice.attachments:
        adr = _e(root, "cac:AdditionalDocumentReference")
        _e(adr, "cbc:ID", att.filename)
        if att.description:
            _e(adr, "cbc:DocumentDescription", att.description)
        _e(_e(adr, "cac:Attachment"), "cbc:EmbeddedDocumentBinaryObject",
           base64.b64encode(att.content).decode("ascii"),
           mimeCode=att.mime, filename=att.filename)

    _party(_e(root, "cac:AccountingSupplierParty"), invoice.seller, tax_scheme)
    _party(_e(root, "cac:AccountingCustomerParty"), invoice.buyer, tax_scheme)

    if invoice.payments:
        pm = _e(root, "cac:PaymentMeans")
        _e(pm, "cbc:PaymentMeansCode", invoice.payments[0].means.uncl4461)
        _e(pm, "cbc:PaymentID", invoice.number)
        acc = invoice.payments[0].account
        if acc and acc.iban:
            # BT-84/85/86: account, holder, servicing bank.
            fa = _e(pm, "cac:PayeeFinancialAccount")
            _e(fa, "cbc:ID", acc.iban)
            if acc.holder:
                _e(fa, "cbc:Name", acc.holder)
            if acc.bic:
                _e(_e(fa, "cac:FinancialInstitutionBranch"), "cbc:ID", acc.bic)
    if invoice.payment_terms_note:
        _e(_e(root, "cac:PaymentTerms"), "cbc:Note", invoice.payment_terms_note)

    for ac in invoice.allowances_charges:
        category, rate = category_for_rate(
            ac.vat_rate if ac.vat_rate is not None else invoice.lines[0].vat_rate
        )
        _allowance_charge(root, is_charge=ac.is_charge, amount=ac.amount,
                          currency=cur, reason=ac.reason, category=category, rate=rate,
                          tax_scheme=tax_scheme)
    for fund in invoice.funds:
        category, rate = _tax_category(fund.vat_rate, fund.nature), fund.vat_rate
        _allowance_charge(root, is_charge=True, amount=fund.amount, currency=cur,
                          reason=f"Cassa previdenziale {fund.kind}",
                          category=category, rate=rate, tax_scheme=tax_scheme)
    stamp = D(invoice.stamp_duty) if invoice.stamp_duty else None
    if stamp:
        _allowance_charge(root, is_charge=True, amount=stamp, currency=cur,
                          reason="Imposta di bollo", category="O", rate=None,
                          tax_scheme=tax_scheme)

    # VAT breakdown. The stamp duty joins the (single) "O" subtotal so the
    # category totals stay consistent (BR-O-01 / BR-CO-13).
    subtotals: list[dict] = []
    for vs in summary:
        category = _tax_category(vs.vat_rate, vs.nature)
        reason = None
        if category not in ("S", "Z"):
            reason = vs.exemption_reason or (
                "Operazione fuori campo IVA" if category == "O" else None
            )
        subtotals.append({"taxable": vs.taxable, "tax": vs.tax, "rate": vs.vat_rate,
                          "category": category, "reason": reason})
    if stamp:
        o_bucket = next((s for s in subtotals if s["category"] == "O"), None)
        if o_bucket is not None:
            o_bucket["taxable"] = q2(o_bucket["taxable"] + stamp)
        else:
            subtotals.append({"taxable": stamp, "tax": Decimal("0"), "rate": None,
                              "category": "O", "reason": "Imposta di bollo"})

    tax_total = _e(root, "cac:TaxTotal")
    _e(tax_total, "cbc:TaxAmount", fmt2(invoice.tax_total()), currencyID=cur)
    for s in subtotals:
        sub = _e(tax_total, "cac:TaxSubtotal")
        _e(sub, "cbc:TaxableAmount", fmt2(s["taxable"]), currencyID=cur)
        _e(sub, "cbc:TaxAmount", fmt2(s["tax"]), currencyID=cur)
        _tax_cat_el(sub, "cac:TaxCategory", s["category"], s["rate"], s["reason"],
                    tax_scheme=tax_scheme)

    # Monetary totals (BR-CO-10/13/15): the funds and the stamp duty are
    # document charges, so TaxExclusive = lines − allowances + charges equals
    # taxable_total + stamp and everything balances with total_document().
    lines_total = invoice.lines_total()
    allowance_total = invoice.allowance_total()
    charge_total = q2(
        invoice.charge_total()
        + sum((f.amount for f in invoice.funds), Decimal("0"))
        + (stamp or Decimal("0"))
    )
    rounding = D(invoice.rounding) if invoice.rounding else None
    tax_inclusive = q2(invoice.total_document() - (rounding or Decimal("0")))

    mon = _e(root, "cac:LegalMonetaryTotal")
    _e(mon, "cbc:LineExtensionAmount", fmt2(lines_total), currencyID=cur)
    _e(mon, "cbc:TaxExclusiveAmount",
       fmt2(lines_total - allowance_total + charge_total), currencyID=cur)
    _e(mon, "cbc:TaxInclusiveAmount", fmt2(tax_inclusive), currencyID=cur)
    if allowance_total:
        _e(mon, "cbc:AllowanceTotalAmount", fmt2(allowance_total), currencyID=cur)
    if charge_total:
        _e(mon, "cbc:ChargeTotalAmount", fmt2(charge_total), currencyID=cur)
    if rounding is not None:
        _e(mon, "cbc:PayableRoundingAmount", fmt2(rounding), currencyID=cur)
    _e(mon, "cbc:PayableAmount", fmt2(invoice.total_document()), currencyID=cur)

    line_tag = "cac:CreditNoteLine" if is_cn else "cac:InvoiceLine"
    qty_tag = "cbc:CreditedQuantity" if is_cn else "cbc:InvoicedQuantity"
    for i, ln in enumerate(invoice.lines, start=1):
        line = _e(root, line_tag)
        _e(line, "cbc:ID", i)
        _e(line, qty_tag, f"{ln.quantity:.2f}", unitCode=(ln.unit_of_measure or "C62"))
        _e(line, "cbc:LineExtensionAmount", fmt2(ln.total), currencyID=cur)
        for d in ln.discounts:
            lac = _e(line, "cac:AllowanceCharge")
            _e(lac, "cbc:ChargeIndicator", "true" if d.is_charge else "false")
            if d.reason:
                _e(lac, "cbc:AllowanceChargeReason", d.reason)
            _e(lac, "cbc:Amount", fmt2(d.amount), currencyID=cur)
        # Accounting period the line covers — BG-26. Dropping it loses the
        # only thing that distinguishes twelve identical subscription lines.
        if ln.period_start or ln.period_end:
            per = _e(line, "cac:InvoicePeriod")
            if ln.period_start:
                _e(per, "cbc:StartDate", ln.period_start.isoformat())
            if ln.period_end:
                _e(per, "cbc:EndDate", ln.period_end.isoformat())
        item = _e(line, "cac:Item")
        _e(item, "cbc:Name", ln.description)
        if ln.article_code:
            _e(_e(item, "cac:SellersItemIdentification"), "cbc:ID", ln.article_code)
        _tax_cat_el(item, "cac:ClassifiedTaxCategory",
                    _tax_category(ln.vat_rate, ln.nature), ln.vat_rate,
                    reason=ln.exemption_reason if ln.vat_rate == 0 else None,
                    tax_scheme=tax_scheme)
        price = _e(line, "cac:Price")
        _e(price, "cbc:PriceAmount", fmt_price(ln.unit_price), currencyID=cur)

    ET.indent(root)
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


class UblRenderer(InvoiceRenderer):
    standard = "ubl"

    def __init__(self, *, customization: str = _CUSTOMIZATION, tax_scheme: str = "VAT"):
        self.customization = customization
        self.tax_scheme = tax_scheme

    def render(self, invoice: Invoice) -> RenderedDocument:
        xml = build_ubl_xml(invoice, customization=self.customization,
                            tax_scheme=self.tax_scheme)
        # Peppol carries the payload, not a file, so this name is for humans
        # and archives — it must simply always be valid.
        filename = safe_filename(
            invoice.seller.country_code,
            invoice.seller.normalized_vat() or invoice.seller.tax_code,
            invoice.number,
            suffix="-ubl.xml",
        )
        return RenderedDocument("ubl", xml, "application/xml", filename)
