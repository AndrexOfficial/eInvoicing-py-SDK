"""UN/CEFACT CII renderer — EN 16931, Factur-X / ZUGFeRD / Chorus Pro.

EN 16931 has **two** permitted syntaxes: OASIS UBL (see :mod:`~einvoice.formats.ubl`)
and UN/CEFACT Cross Industry Invoice. They carry the same semantics and are not
interchangeable on the wire — a receiver accepts one or the other — so a package
that only speaks UBL cannot serve:

* **France** — the B2B reform admits Factur-X, UBL and CII; Factur-X (a PDF/A-3
  carrying this XML) is the format most French software actually exchanges, and
  Chorus Pro has taken CII since the B2G mandate.
* **Germany** — ZUGFeRD is Factur-X under a different name, and is accepted
  alongside XRechnung for the B2B rollout.
* Anyone integrating with SAP, DATEV or the many ERPs whose native e-invoice
  export is CII.

Profiles (the ``GuidelineSpecifiedDocumentContextParameter/ID``) declare which
rule set the document follows; :data:`FACTURX_PROFILES` holds the ones worth
naming. The default is plain EN 16931 ("COMFORT"), which is what both Chorus Pro
and ZUGFeRD's EN 16931 profile expect.

**Element order is load-bearing.** Unlike a dictionary, the CII schema is a
sequence: emitting ``ram:Name`` before ``ram:ID`` produces a document that is
semantically right and schema-invalid. The order below follows D16B and is the
reason this module is written as a straight line rather than as helpers that
"add a field wherever".

Not implemented here: embedding the XML into a PDF/A-3 container (that is what
turns CII into *Factur-X* proper). This renders the XML payload; wrapping it in
a PDF needs a PDF toolkit and is a deliberate boundary — see the README.
"""
from __future__ import annotations

from decimal import Decimal
from xml.etree import ElementTree as ET

from ..models import Invoice, Party, VatNature
from ..money import D, fmt2, fmt_price, q2
from ..naming import safe_filename
from .base import InvoiceRenderer, RenderedDocument

RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"

_NS = {"rsm": RSM, "ram": RAM, "udt": UDT}
for _prefix, _uri in _NS.items():
    ET.register_namespace(_prefix, _uri)

#: Named Factur-X / ZUGFeRD profiles. ``en16931`` is the interoperable default:
#: the lighter profiles drop line detail and the extended one adds fields no
#: generic receiver is obliged to understand.
FACTURX_PROFILES = {
    "minimum": "urn:factur-x.eu:1p0:minimum",
    "basicwl": "urn:factur-x.eu:1p0:basicwl",
    "basic": "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic",
    "en16931": "urn:cen.eu:en16931:2017",
    "extended": "urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended",
    "xrechnung": "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0",
}

_DEFAULT_GUIDELINE = FACTURX_PROFILES["en16931"]

#: Profiles that carry **no line items at all**. "BASIC WL" is literally
#: "Basic Without Lines", and MINIMUM is smaller still — both describe the
#: document only at header level. Emitting lines while declaring one of these
#: produces a document that claims a profile it does not satisfy, which a
#: validating receiver rejects.
_HEADER_ONLY_GUIDELINES = frozenset({
    FACTURX_PROFILES["minimum"],
    FACTURX_PROFILES["basicwl"],
})

#: ``udt:DateTimeString/@format`` 102 = CCYYMMDD, the only form EN 16931 uses.
_DATE_FORMAT = "102"


def _e(parent: ET.Element, qname: str, text=None, **attrib) -> ET.Element:
    prefix, _, local = qname.partition(":")
    el = ET.SubElement(parent, f"{{{_NS[prefix]}}}{local}",
                       {k: str(v) for k, v in attrib.items()})
    if text is not None:
        el.text = str(text)
    return el


def _date(parent: ET.Element, qname: str, value) -> None:
    """A CII date is always wrapped in a formatted ``udt:DateTimeString``."""
    _e(_e(parent, qname), "udt:DateTimeString", value.strftime("%Y%m%d"),
       format=_DATE_FORMAT)


def _tax_category(rate: Decimal, nature: VatNature | None) -> str:
    if rate > 0:
        return "S"
    if nature is None:
        return "Z"
    return nature.en16931_category


def _trade_party(parent: ET.Element, tag: str, party: Party, tax_scheme: str) -> None:
    """``ram:SellerTradeParty`` / ``ram:BuyerTradeParty``.

    Schema order: ID, Name, SpecifiedLegalOrganization, PostalTradeAddress,
    URIUniversalCommunication, SpecifiedTaxRegistration.
    """
    p = _e(parent, tag)
    _e(p, "ram:Name", party.display_name())
    if party.registration_number:
        org = _e(p, "ram:SpecifiedLegalOrganization")
        _e(org, "ram:ID", party.registration_number)
    if party.email or party.pec:
        # BT-43/BT-58. Schema order: DefinedTradeContact precedes the address.
        contact = _e(p, "ram:DefinedTradeContact")
        _e(_e(contact, "ram:EmailURIUniversalCommunication"), "ram:URIID",
           party.email or party.pec)
    addr_ = party.postal_address
    addr = _e(p, "ram:PostalTradeAddress")
    _e(addr, "ram:PostcodeCode", addr_.postcode)
    _e(addr, "ram:LineOne", addr_.street)
    _e(addr, "ram:CityName", addr_.city)
    _e(addr, "ram:CountryID", addr_.country)
    if addr_.province:
        _e(addr, "ram:CountrySubDivisionName", addr_.province)
    scheme, endpoint = party.peppol_endpoint()
    if scheme and endpoint:
        # BT-34/BT-49: the electronic address the document routes to.
        _e(_e(p, "ram:URIUniversalCommunication"), "ram:URIID", endpoint,
           schemeID=scheme)
    elif party.email:
        _e(_e(p, "ram:URIUniversalCommunication"), "ram:URIID", party.email,
           schemeID="EM")
    if party.vat_number:
        # UNCL 1153: "VA" = VAT registration, "FC" = fiscal number. A US EIN is
        # not a VAT registration — stamping it "VA" asserts the seller is
        # registered for a tax the United States does not levy.
        _e(_e(p, "ram:SpecifiedTaxRegistration"), "ram:ID",
           party.tax_company_id(), schemeID="VA" if tax_scheme == "VAT" else "FC")
    if party.tax_code:
        _e(_e(p, "ram:SpecifiedTaxRegistration"), "ram:ID",
           party.tax_code, schemeID="FC")


def _trade_tax(parent: ET.Element, *, taxable, tax, category: str,
               rate, reason: str | None, tax_scheme: str) -> None:
    """A ``ram:ApplicableTradeTax`` bucket, in schema order."""
    t = _e(parent, "ram:ApplicableTradeTax")
    _e(t, "ram:CalculatedAmount", fmt2(tax))
    _e(t, "ram:TypeCode", tax_scheme)
    if reason:
        _e(t, "ram:ExemptionReason", reason)
    _e(t, "ram:BasisAmount", fmt2(taxable))
    _e(t, "ram:CategoryCode", category)
    if category != "O" and rate is not None:
        _e(t, "ram:RateApplicablePercent", fmt2(rate))


def _allowance_charge(parent: ET.Element, *, is_charge: bool, amount,
                      reason: str | None, category: str, rate,
                      tax_scheme: str) -> None:
    ac = _e(parent, "ram:SpecifiedTradeAllowanceCharge")
    # CII wraps the boolean one level deeper than UBL does: the flag is a
    # udt:Indicator child, not the element's own text.
    _e(_e(ac, "ram:ChargeIndicator"), "udt:Indicator",
       "true" if is_charge else "false")
    _e(ac, "ram:ActualAmount", fmt2(amount))
    if reason:
        _e(ac, "ram:Reason", reason)
    cat = _e(ac, "ram:CategoryTradeTax")
    _e(cat, "ram:TypeCode", tax_scheme)
    _e(cat, "ram:CategoryCode", category)
    if category != "O" and rate is not None:
        _e(cat, "ram:RateApplicablePercent", fmt2(rate))


def build_cii_xml(invoice: Invoice, *, guideline: str = _DEFAULT_GUIDELINE,
                  tax_scheme: str = "VAT") -> bytes:
    """Render an :class:`~einvoice.models.Invoice` as EN 16931 CII (D16B)."""
    invoice.validate()
    cur = invoice.currency
    summary = invoice.vat_summary()

    root = ET.Element(f"{{{RSM}}}CrossIndustryInvoice")

    # ── context: which rule set this document claims to follow ──────────
    ctx = _e(root, "rsm:ExchangedDocumentContext")
    _e(_e(ctx, "ram:GuidelineSpecifiedDocumentContextParameter"), "ram:ID", guideline)

    # ── the document header ─────────────────────────────────────────────
    doc = _e(root, "rsm:ExchangedDocument")
    _e(doc, "ram:ID", invoice.number)
    _e(doc, "ram:TypeCode", invoice.document_type.uncl1001)
    _date(doc, "ram:IssueDateTime", invoice.date)
    if invoice.causale:
        _e(_e(doc, "ram:IncludedNote"), "ram:Content", invoice.causale)

    txn = _e(root, "rsm:SupplyChainTradeTransaction")

    # ── lines ───────────────────────────────────────────────────────────
    # Suppressed entirely for the header-only profiles; the totals below still
    # describe the whole document, which is exactly what those profiles are for.
    lines = [] if guideline in _HEADER_ONLY_GUIDELINES else invoice.lines
    for i, ln in enumerate(lines, start=1):
        item = _e(txn, "ram:IncludedSupplyChainTradeLineItem")
        _e(_e(item, "ram:AssociatedDocumentLineDocument"), "ram:LineID", i)

        product = _e(item, "ram:SpecifiedTradeProduct")
        if ln.article_code:
            _e(product, "ram:SellerAssignedID", ln.article_code)
        _e(product, "ram:Name", ln.description)

        agreement = _e(item, "ram:SpecifiedLineTradeAgreement")
        _e(_e(agreement, "ram:NetPriceProductTradePrice"), "ram:ChargeAmount",
           fmt_price(ln.unit_price))

        delivery = _e(item, "ram:SpecifiedLineTradeDelivery")
        _e(delivery, "ram:BilledQuantity", f"{ln.quantity:.4f}",
           unitCode=(ln.unit_of_measure or "C62"))

        settlement = _e(item, "ram:SpecifiedLineTradeSettlement")
        tax = _e(settlement, "ram:ApplicableTradeTax")
        _e(tax, "ram:TypeCode", tax_scheme)
        _e(tax, "ram:CategoryCode", _tax_category(ln.vat_rate, ln.nature))
        if ln.vat_rate is not None:
            _e(tax, "ram:RateApplicablePercent", fmt2(ln.vat_rate))
        if ln.period_start or ln.period_end:
            period = _e(settlement, "ram:BillingSpecifiedPeriod")
            if ln.period_start:
                _date(period, "ram:StartDateTime", ln.period_start)
            if ln.period_end:
                _date(period, "ram:EndDateTime", ln.period_end)
        for d in ln.discounts:
            _allowance_charge(settlement, is_charge=d.is_charge, amount=d.amount,
                              reason=d.reason,
                              category=_tax_category(ln.vat_rate, ln.nature),
                              rate=ln.vat_rate, tax_scheme=tax_scheme)
        _e(_e(settlement, "ram:SpecifiedTradeSettlementLineMonetarySummation"),
           "ram:LineTotalAmount", fmt2(ln.total))

    # ── agreement: who, and against which order/contract ────────────────
    agreement = _e(txn, "ram:ApplicableHeaderTradeAgreement")
    order_ref = next((r for r in invoice.references if r.kind == "order"), None)
    buyer_ref = invoice.buyer_reference or (None if order_ref else invoice.number)
    if buyer_ref:
        _e(agreement, "ram:BuyerReference", buyer_ref)
    _trade_party(agreement, "ram:SellerTradeParty", invoice.seller, tax_scheme)
    _trade_party(agreement, "ram:BuyerTradeParty", invoice.buyer, tax_scheme)
    if order_ref is not None:
        _e(_e(agreement, "ram:BuyerOrderReferencedDocument"),
           "ram:IssuerAssignedID", order_ref.doc_id)
    for ref in (r for r in invoice.references if r.kind == "contract"):
        _e(_e(agreement, "ram:ContractReferencedDocument"),
           "ram:IssuerAssignedID", ref.doc_id)
    for att in invoice.attachments:
        adr = _e(agreement, "ram:AdditionalReferencedDocument")
        _e(adr, "ram:IssuerAssignedID", att.filename)
        _e(adr, "ram:TypeCode", "916")          # related document
        if att.description:
            _e(adr, "ram:Name", att.description)
        import base64

        _e(adr, "ram:AttachmentBinaryObject",
           base64.b64encode(att.content).decode("ascii"),
           mimeCode=att.mime, filename=att.filename)

    # ── delivery ────────────────────────────────────────────────────────
    delivery = _e(txn, "ram:ApplicableHeaderTradeDelivery")
    for ref in (r for r in invoice.references if r.kind == "ddt"):
        dd = _e(delivery, "ram:DespatchAdviceReferencedDocument")
        _e(dd, "ram:IssuerAssignedID", ref.doc_id)

    # ── settlement: money ───────────────────────────────────────────────
    stl = _e(txn, "ram:ApplicableHeaderTradeSettlement")
    _e(stl, "ram:PaymentReference", invoice.number)
    _e(stl, "ram:InvoiceCurrencyCode", cur)
    for pay in invoice.payments:
        pm = _e(stl, "ram:SpecifiedTradeSettlementPaymentMeans")
        _e(pm, "ram:TypeCode", pay.means.uncl4461)
        if pay.account and pay.account.iban:
            acct = _e(pm, "ram:PayeePartyCreditorFinancialAccount")
            _e(acct, "ram:IBANID", pay.account.iban)
            if pay.account.holder:
                _e(acct, "ram:AccountName", pay.account.holder)
            if pay.account.bic or pay.account.bank_name:
                bank = _e(pm, "ram:PayeeSpecifiedCreditorFinancialInstitution")
                if pay.account.bic:
                    _e(bank, "ram:BICID", pay.account.bic)
                if pay.account.bank_name:
                    _e(bank, "ram:Name", pay.account.bank_name)

    stamp = D(invoice.stamp_duty) if invoice.stamp_duty else None
    for vs in summary:
        category = _tax_category(vs.vat_rate, vs.nature)
        reason = None
        if category not in ("S", "Z"):
            reason = vs.exemption_reason or (
                "Operazione fuori campo IVA" if category == "O" else None
            )
        taxable = vs.taxable
        if stamp and category == "O":
            taxable = q2(taxable + stamp)
            stamp = None                      # folded into the existing bucket
        _trade_tax(stl, taxable=taxable, tax=vs.tax, category=category,
                   rate=vs.vat_rate, reason=reason, tax_scheme=tax_scheme)
    if stamp:                                  # no "O" bucket existed
        _trade_tax(stl, taxable=stamp, tax=Decimal("0"), category="O",
                   rate=None, reason="Imposta di bollo", tax_scheme=tax_scheme)

    for ac in invoice.allowances_charges:
        rate = ac.vat_rate if ac.vat_rate is not None else invoice.lines[0].vat_rate
        bucket = next((v for v in summary if v.vat_rate == D(rate)), None)
        _allowance_charge(stl, is_charge=ac.is_charge, amount=ac.amount,
                          reason=ac.reason,
                          category=_tax_category(D(rate), bucket.nature if bucket else None),
                          rate=rate, tax_scheme=tax_scheme)
    for fund in invoice.funds:
        _allowance_charge(stl, is_charge=True, amount=fund.amount,
                          reason=f"Cassa previdenziale {fund.kind}",
                          category=_tax_category(fund.vat_rate, fund.nature),
                          rate=fund.vat_rate, tax_scheme=tax_scheme)
    if invoice.stamp_duty:
        _allowance_charge(stl, is_charge=True, amount=D(invoice.stamp_duty),
                          reason="Imposta di bollo", category="O", rate=None,
                          tax_scheme=tax_scheme)

    if invoice.payment_terms_note or any(p.due_date for p in invoice.payments):
        terms = _e(stl, "ram:SpecifiedTradePaymentTerms")
        if invoice.payment_terms_note:
            _e(terms, "ram:Description", invoice.payment_terms_note)
        due = next((p.due_date for p in invoice.payments if p.due_date), None)
        if due:
            _date(terms, "ram:DueDateDateTime", due)

    # BT-106/109/110/112: the totals a receiver reconciles against.
    lines_total = invoice.lines_total()
    allowance_total = invoice.allowance_total()
    charge_total = q2(
        invoice.charge_total()
        + sum((f.amount for f in invoice.funds), Decimal("0"))
        + (D(invoice.stamp_duty) if invoice.stamp_duty else Decimal("0"))
    )
    rounding = D(invoice.rounding) if invoice.rounding else None

    mon = _e(stl, "ram:SpecifiedTradeSettlementHeaderMonetarySummation")
    _e(mon, "ram:LineTotalAmount", fmt2(lines_total))
    if charge_total:
        _e(mon, "ram:ChargeTotalAmount", fmt2(charge_total))
    if allowance_total:
        _e(mon, "ram:AllowanceTotalAmount", fmt2(allowance_total))
    _e(mon, "ram:TaxBasisTotalAmount",
       fmt2(lines_total - allowance_total + charge_total))
    _e(mon, "ram:TaxTotalAmount", fmt2(invoice.tax_total()), currencyID=cur)
    if rounding is not None:
        _e(mon, "ram:RoundingAmount", fmt2(rounding))
    _e(mon, "ram:GrandTotalAmount", fmt2(invoice.total_document()))
    _e(mon, "ram:DuePayableAmount", fmt2(invoice.total_document()))

    for ref in (r for r in invoice.references if r.kind == "invoice"):
        ird = _e(stl, "ram:InvoiceReferencedDocument")
        _e(ird, "ram:IssuerAssignedID", ref.doc_id)
        if ref.date:
            _date(ird, "ram:FormattedIssueDateTime", ref.date)

    ET.indent(root)
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


class CiiRenderer(InvoiceRenderer):
    """EN 16931 in UN/CEFACT CII syntax — Factur-X, ZUGFeRD, Chorus Pro.

    ``profile`` names a Factur-X level from :data:`FACTURX_PROFILES`;
    ``guideline`` sets the identifier outright when you need one not listed.
    """

    standard = "cii"

    def __init__(self, *, guideline: str | None = None, profile: str = "en16931",
                 tax_scheme: str = "VAT", customization: str | None = None):
        if customization and not guideline:
            # `renderer_for_country` speaks "customization" for both syntaxes;
            # in CII that value is the guideline id, so accept it under either
            # name rather than silently ignoring a caller's CIUS choice.
            guideline = customization
        if guideline is None:
            try:
                guideline = FACTURX_PROFILES[profile]
            except KeyError:
                raise ValueError(
                    f"profilo Factur-X sconosciuto: {profile!r}. "
                    f"Disponibili: {', '.join(FACTURX_PROFILES)}"
                ) from None
        self.guideline = guideline
        self.tax_scheme = tax_scheme

    def render(self, invoice: Invoice) -> RenderedDocument:
        xml = build_cii_xml(invoice, guideline=self.guideline,
                            tax_scheme=self.tax_scheme)
        filename = safe_filename(
            invoice.seller.country_code,
            invoice.seller.normalized_vat() or invoice.seller.tax_code,
            invoice.number,
            suffix="-cii.xml",
        )
        return RenderedDocument("cii", xml, "application/xml", filename)
