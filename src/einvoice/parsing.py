"""Read an invoice back: XML → :class:`~einvoice.models.Invoice`.

The package could write FatturaPA, UBL and CII but not read any of them, which
left out half of every real integration — and increasingly the mandatory half.
Germany has required businesses to *accept* structured e-invoices since
2025-01-01, France requires it of everyone from 2026, and Italy has for years:
you cannot be compliant by sending alone.

    from einvoice import parse_invoice

    invoice = parse_invoice(open("incoming.xml", "rb").read())
    invoice.seller.vat_number      # → the supplier's VAT id
    invoice.total_document()       # → recomputed from the lines, not trusted

**The totals are recomputed, never read.** A received document states its own
totals; this parser extracts the *lines* and lets :class:`Invoice` derive the
money from them exactly as it does for an outgoing invoice. That way a
discrepancy between what a supplier claims and what their own lines add up to
becomes visible instead of being imported as fact — use
:func:`compare_declared_totals` to see it.

**What survives the trip.** Everything EN 16931 models: parties, addresses, tax
identifiers, lines with quantities and rates, discounts, payment means and
terms, references, periods. Italian-only blocks (ritenuta, cassa previdenziale,
bollo) round-trip through **FatturaPA**, which has dedicated elements for them;
through UBL and CII they arrive as ordinary charges, because that is all those
syntaxes preserve. The docstrings on each parser say which.
"""
from __future__ import annotations

import base64
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from .enums import (
    DocumentType,
    PaymentMeans,
    VatExigibility,
    VatNature,
    WithholdingType,
)
from .errors import ValidationError
from .models import (
    Address,
    AllowanceCharge,
    Attachment,
    BankAccount,
    DocumentReference,
    Invoice,
    LineItem,
    Party,
    Payment,
    SocialSecurityFund,
    WithholdingTax,
)
from .money import q6
from .taxid import normalize_tax_id

__all__ = [
    "detect_standard",
    "parse_invoice",
    "parse_ubl_xml",
    "parse_cii_xml",
    "parse_fattura_xml",
    "compare_declared_totals",
]

# ── namespaces ─────────────────────────────────────────────────────────────

CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
INV_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CN_NS = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"
FPA = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"

_UBL = {"cbc": CBC, "cac": CAC}
_CII = {"rsm": RSM, "ram": RAM, "udt": UDT}


# ── small helpers ──────────────────────────────────────────────────────────


def _root(xml: bytes | str) -> ET.Element:
    try:
        return ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except ET.ParseError as exc:
        raise ValidationError(f"XML non valido: {exc}") from exc


def _text(el: ET.Element | None, path: str, ns: dict) -> str | None:
    if el is None:
        return None
    found = el.find(path, ns)
    return found.text.strip() if found is not None and found.text else None


def _dec(value: str | None, default: str = "0") -> Decimal:
    try:
        return Decimal((value or default).strip())
    except (InvalidOperation, AttributeError):
        return Decimal(default)


def _opt_dec(value: str | None) -> Decimal | None:
    return None if value in (None, "") else _dec(value)


def _iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _cii_date(el: ET.Element | None) -> date | None:
    """CII wraps dates in ``udt:DateTimeString`` with a format code."""
    if el is None:
        return None
    stamp = el.find(f"{{{UDT}}}DateTimeString")
    raw = (stamp.text if stamp is not None and stamp.text else el.text or "").strip()
    if not raw:
        return None
    # Format 102 (CCYYMMDD) is what EN 16931 mandates, but 610/616 and a plain
    # ISO date all turn up in the wild, so try the two shapes that occur.
    for fmt, width in (("%Y%m%d", 8), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(raw[:width], fmt).date()
        except ValueError:
            continue
    return None


def _document_type(code: str | None, *, credit_note: bool = False) -> DocumentType:
    """UNCL 1001 → our (Italian-rooted) document type.

    The mapping is lossy in one direction by construction: 380 covers a dozen
    Italian TD codes, so an inbound 380 becomes TD01. What matters downstream —
    is this a credit note? a prepayment? — is preserved.
    """
    if credit_note or code == "381":
        return DocumentType.CREDIT_NOTE
    return {
        "383": DocumentType.DEBIT_NOTE,
        "386": DocumentType.ADVANCE,
    }.get((code or "").strip(), DocumentType.INVOICE)


def _nature(category: str | None, reason: str | None) -> VatNature | None:
    """EN 16931 VAT category → the closest Italian ``Natura``.

    Only meaningful for zero-rated lines. The EU categories are coarser than
    the Italian list (one "AE" covers all nine N6.x reverse-charge cases), so
    this picks the general member of each family and keeps the free-text reason
    on the line. Round-tripping an Italian document through UBL therefore
    narrows N6.3 to N6.9 — documented rather than silently pretended away.
    """
    mapping = {
        "G": VatNature.NOT_TAXABLE_EXPORT,
        "K": VatNature.NOT_TAXABLE,
        "AE": VatNature.REVERSE_CHARGE_OTHER,
        "E": VatNature.EXEMPT,
        "O": VatNature.NOT_SUBJECT,
    }
    del reason  # kept in LineItem.exemption_reason by the callers
    return mapping.get((category or "").strip().upper())


# ── format detection ───────────────────────────────────────────────────────


def detect_standard(xml: bytes | str) -> str:
    """``"fatturapa"`` | ``"ubl"`` | ``"cii"``, from the document's root element.

    Detection is by namespace, not by guessing at content: the root element is
    the one thing every one of these standards agrees to be explicit about.
    """
    root = _root(xml)
    tag = root.tag
    if tag.startswith(f"{{{RSM}}}"):
        return "cii"
    if tag.startswith(f"{{{INV_NS}}}") or tag.startswith(f"{{{CN_NS}}}"):
        return "ubl"
    if tag.startswith(f"{{{FPA}}}") or tag.endswith("FatturaElettronica"):
        return "fatturapa"
    raise ValidationError(
        f"Formato non riconosciuto: elemento radice {tag!r}. "
        "Attesi FatturaPA, UBL Invoice/CreditNote o CII CrossIndustryInvoice."
    )


def parse_invoice(xml: bytes | str, *, standard: str | None = None) -> Invoice:
    """Parse any supported e-invoice into the neutral model.

    ``standard`` forces a parser; by default the format is detected from the
    root element.
    """
    chosen = standard or detect_standard(xml)
    parsers = {
        "ubl": parse_ubl_xml,
        "peppol": parse_ubl_xml,
        "cii": parse_cii_xml,
        "facturx": parse_cii_xml,
        "zugferd": parse_cii_xml,
        "fatturapa": parse_fattura_xml,
    }
    parser = parsers.get(chosen.lower())
    if parser is None:
        raise ValidationError(
            f"Nessun parser per {chosen!r}. Disponibili: {', '.join(sorted(parsers))}"
        )
    return parser(xml)


# ── UBL ────────────────────────────────────────────────────────────────────


def _ubl_party(el: ET.Element | None) -> Party:
    if el is None:
        raise ValidationError("UBL: blocco Party mancante")
    party = el.find("cac:Party", _UBL)
    if party is None:
        raise ValidationError("UBL: cac:Party mancante")
    addr = party.find("cac:PostalAddress", _UBL)
    country = _text(addr, "cac:Country/cbc:IdentificationCode", _UBL) or "IT"
    endpoint = party.find("cbc:EndpointID", _UBL)
    # CompanyID carries the VIES prefix; the model stores the bare number and
    # re-adds it on render, so stripping here keeps a round-trip stable.
    # Delegated to the canonical normalizer rather than re-implemented: a
    # naive "drop two leading letters" turns the Swiss UID CHE116281710 into
    # E116281710, and mangles a French number whose key is "FR".
    vat = normalize_tax_id(country, _text(party, "cac:PartyTaxScheme/cbc:CompanyID", _UBL)) or None
    return Party(
        name=_text(party, "cac:PartyLegalEntity/cbc:RegistrationName", _UBL)
        or _text(party, "cac:PartyName/cbc:Name", _UBL),
        vat_number=vat,
        tax_code=_text(party, "cac:PartyIdentification/cbc:ID", _UBL),
        country_code=country,
        registration_number=_text(party, "cac:PartyLegalEntity/cbc:CompanyID", _UBL),
        endpoint_id=endpoint.text if endpoint is not None else None,
        endpoint_scheme=endpoint.get("schemeID") if endpoint is not None else None,
        email=_text(party, "cac:Contact/cbc:ElectronicMail", _UBL),
        address=Address(
            street=_text(addr, "cbc:StreetName", _UBL) or "—",
            postcode=_text(addr, "cbc:PostalZone", _UBL) or "00000",
            city=_text(addr, "cbc:CityName", _UBL) or "—",
            province=_text(addr, "cbc:CountrySubentity", _UBL),
            country=country,
        ),
    )


def parse_ubl_xml(xml: bytes | str) -> Invoice:
    """Parse UBL 2.1 (Peppol BIS 3.0 / EN 16931), Invoice or CreditNote.

    Italian extras arrive as what UBL made of them: the bollo and cassa
    previdenziale were rendered as document charges, so they come back as
    :class:`AllowanceCharge` entries rather than ``stamp_duty`` / ``funds``.
    """
    root = _root(xml)
    is_cn = root.tag.startswith(f"{{{CN_NS}}}")
    line_tag = "cac:CreditNoteLine" if is_cn else "cac:InvoiceLine"
    qty_tag = "cbc:CreditedQuantity" if is_cn else "cbc:InvoicedQuantity"
    type_tag = "cbc:CreditNoteTypeCode" if is_cn else "cbc:InvoiceTypeCode"

    currency = _text(root, "cbc:DocumentCurrencyCode", _UBL) or "EUR"
    issue = _iso_date(_text(root, "cbc:IssueDate", _UBL))
    if issue is None:
        raise ValidationError("UBL: cbc:IssueDate mancante o non valida")

    lines: list[LineItem] = []
    for el in root.findall(line_tag, _UBL):
        qty_el = el.find(qty_tag, _UBL)
        item = el.find("cac:Item", _UBL)
        category = _text(item, "cac:ClassifiedTaxCategory/cbc:ID", _UBL)
        rate = _dec(_text(item, "cac:ClassifiedTaxCategory/cbc:Percent", _UBL))
        reason = _text(item, "cac:ClassifiedTaxCategory/cbc:TaxExemptionReason", _UBL)
        period = el.find("cac:InvoicePeriod", _UBL)
        line = LineItem(
            description=_text(item, "cbc:Name", _UBL) or "—",
            quantity=_dec(qty_el.text if qty_el is not None else None, "1"),
            unit_price=_unit_price(_text(el, "cac:Price/cbc:PriceAmount", _UBL),
                                   _text(el, "cac:Price/cbc:BaseQuantity", _UBL)),
            vat_rate=rate,
            unit_of_measure=qty_el.get("unitCode") if qty_el is not None else None,
            nature=_nature(category, reason) if rate == 0 else None,
            exemption_reason=reason,
            article_code=_text(item, "cac:SellersItemIdentification/cbc:ID", _UBL),
            period_start=_iso_date(_text(period, "cbc:StartDate", _UBL)),
            period_end=_iso_date(_text(period, "cbc:EndDate", _UBL)),
        )
        for ac in el.findall("cac:AllowanceCharge", _UBL):
            line.discounts.append(AllowanceCharge(
                amount=_dec(_text(ac, "cbc:Amount", _UBL)),
                is_charge=(_text(ac, "cbc:ChargeIndicator", _UBL) or "").lower() == "true",
                reason=_text(ac, "cbc:AllowanceChargeReason", _UBL),
            ))
        lines.append(line)

    allowances = [
        AllowanceCharge(
            amount=_dec(_text(ac, "cbc:Amount", _UBL)),
            is_charge=(_text(ac, "cbc:ChargeIndicator", _UBL) or "").lower() == "true",
            vat_rate=_charge_rate(_text(ac, "cac:TaxCategory/cbc:Percent", _UBL),
                                  _text(ac, "cac:TaxCategory/cbc:ID", _UBL)),
            reason=_text(ac, "cbc:AllowanceChargeReason", _UBL),
        )
        for ac in root.findall("cac:AllowanceCharge", _UBL)
    ]

    payments: list[Payment] = []
    for pm in root.findall("cac:PaymentMeans", _UBL):
        iban = _text(pm, "cac:PayeeFinancialAccount/cbc:ID", _UBL)
        payments.append(Payment(
            means=_payment_means(_text(pm, "cbc:PaymentMeansCode", _UBL)),
            due_date=_iso_date(_text(root, "cbc:DueDate", _UBL)),
            account=BankAccount(
                iban=iban,
                holder=_text(pm, "cac:PayeeFinancialAccount/cbc:Name", _UBL),
                bic=_text(pm, "cac:PayeeFinancialAccount/"
                              "cac:FinancialInstitutionBranch/cbc:ID", _UBL),
            ) if iban else None,
        ))

    references: list[DocumentReference] = []
    order = _text(root, "cac:OrderReference/cbc:ID", _UBL)
    if order:
        references.append(DocumentReference("order", order))
    for br in root.findall("cac:BillingReference/cac:InvoiceDocumentReference", _UBL):
        references.append(DocumentReference(
            "invoice", _text(br, "cbc:ID", _UBL) or "—",
            _iso_date(_text(br, "cbc:IssueDate", _UBL))))
    for dr in root.findall("cac:DespatchDocumentReference", _UBL):
        references.append(DocumentReference("ddt", _text(dr, "cbc:ID", _UBL) or "—"))
    for cr in root.findall("cac:ContractDocumentReference", _UBL):
        references.append(DocumentReference("contract", _text(cr, "cbc:ID", _UBL) or "—"))

    attachments = []
    for adr in root.findall("cac:AdditionalDocumentReference", _UBL):
        blob = adr.find("cac:Attachment/cbc:EmbeddedDocumentBinaryObject", _UBL)
        if blob is None or not blob.text:
            continue
        attachments.append(Attachment(
            filename=blob.get("filename") or _text(adr, "cbc:ID", _UBL) or "allegato",
            content=base64.b64decode(blob.text),
            mime=blob.get("mimeCode") or "application/octet-stream",
            description=_text(adr, "cbc:DocumentDescription", _UBL),
        ))

    return Invoice(
        number=_text(root, "cbc:ID", _UBL) or "—",
        date=issue,
        seller=_ubl_party(root.find("cac:AccountingSupplierParty", _UBL)),
        buyer=_ubl_party(root.find("cac:AccountingCustomerParty", _UBL)),
        lines=lines,
        document_type=_document_type(_text(root, type_tag, _UBL), credit_note=is_cn),
        currency=currency,
        causale=_text(root, "cbc:Note", _UBL),
        payments=payments,
        buyer_reference=_text(root, "cbc:BuyerReference", _UBL),
        allowances_charges=allowances,
        references=references,
        attachments=attachments,
        payment_terms_note=_text(root, "cac:PaymentTerms/cbc:Note", _UBL),
        rounding=_opt_dec(_text(root, "cac:LegalMonetaryTotal/cbc:PayableRoundingAmount", _UBL)),
    )


def _unit_price(price: str | None, base_quantity: str | None) -> Decimal:
    """Normalize a price quoted per N units down to a price per one unit.

    Prices per 100, per 1000 or per dozen are ordinary in wholesale, and both
    syntaxes express them by pairing the amount with a base quantity. Reading
    the amount and ignoring the base multiplies the line by that base: "50.00
    per 10" with a quantity of 10 becomes 500.00 instead of 50.00.

    The model has no base-quantity concept — a ``LineItem.unit_price`` is per
    one unit — so the division happens here. The line total then matches what
    the sender stated. Re-rendering emits the per-one price, which is the same
    money written differently.
    """
    amount = _dec(price)
    base = _dec(base_quantity, "1")
    if base in (Decimal("0"), Decimal("1")):
        return amount
    return q6(amount / base)


def _payment_means(code: str | None) -> PaymentMeans:
    """UNCL 4461 → the Italian ``ModalitaPagamento`` that renders back to it."""
    return {
        "10": PaymentMeans.CASH, "20": PaymentMeans.CHEQUE,
        "30": PaymentMeans.BANK_TRANSFER, "42": PaymentMeans.SPECIAL_ACCOUNT_TRANSFER,
        "48": PaymentMeans.CARD, "49": PaymentMeans.RID,
        "59": PaymentMeans.SEPA_DD, "60": PaymentMeans.PROMISSORY_NOTE,
        "68": PaymentMeans.PAGOPA,
    }.get((code or "").strip(), PaymentMeans.BANK_TRANSFER)


# ── CII ────────────────────────────────────────────────────────────────────


def _cii_party(el: ET.Element | None) -> Party:
    if el is None:
        raise ValidationError("CII: TradeParty mancante")
    addr = el.find("ram:PostalTradeAddress", _CII)
    country = _text(addr, "ram:CountryID", _CII) or "IT"
    # UNCL 1153: "VA" is a VAT registration, "FC" a fiscal number. In a country
    # that levies no VAT the fiscal number IS the tax identifier — a US EIN
    # arrives as "FC" and belongs in ``vat_number``, or it would vanish.
    from .countries import profile_for

    levies_vat = profile_for(country).tax_scheme == "VAT"
    vat, tax_code = None, None
    for reg in el.findall("ram:SpecifiedTaxRegistration/ram:ID", _CII):
        value = (reg.text or "").strip()
        if (reg.get("schemeID") or "").upper() == "VA" or not levies_vat:
            vat = value
        else:
            tax_code = value
    vat = normalize_tax_id(country, vat) or None
    uri = el.find("ram:URIUniversalCommunication/ram:URIID", _CII)
    scheme = uri.get("schemeID") if uri is not None else None
    return Party(
        name=_text(el, "ram:Name", _CII),
        vat_number=vat,
        tax_code=tax_code,
        country_code=country,
        registration_number=_text(el, "ram:SpecifiedLegalOrganization/ram:ID", _CII),
        # "EM" is an email address, not a routing endpoint.
        endpoint_id=uri.text if uri is not None and scheme != "EM" else None,
        endpoint_scheme=scheme if scheme != "EM" else None,
        email=_text(el, "ram:DefinedTradeContact/"
                        "ram:EmailURIUniversalCommunication/ram:URIID", _CII)
        or (uri.text if uri is not None and scheme == "EM" else None),
        address=Address(
            street=_text(addr, "ram:LineOne", _CII) or "—",
            postcode=_text(addr, "ram:PostcodeCode", _CII) or "00000",
            city=_text(addr, "ram:CityName", _CII) or "—",
            province=_text(addr, "ram:CountrySubDivisionName", _CII),
            country=country,
        ),
    )


def parse_cii_xml(xml: bytes | str) -> Invoice:
    """Parse UN/CEFACT CII (EN 16931, Factur-X / ZUGFeRD).

    The header-only Factur-X profiles (MINIMUM, BASIC WL) carry no lines by
    design, so an invoice parsed from one has none either — its declared totals
    are still readable via :func:`compare_declared_totals`.
    """
    root = _root(xml)
    doc = root.find("rsm:ExchangedDocument", _CII)
    txn = root.find("rsm:SupplyChainTradeTransaction", _CII)
    if doc is None or txn is None:
        raise ValidationError("CII: ExchangedDocument o SupplyChainTradeTransaction mancante")

    issue = _cii_date(doc.find("ram:IssueDateTime", _CII))
    if issue is None:
        raise ValidationError("CII: ram:IssueDateTime mancante o non valida")

    agreement = txn.find("ram:ApplicableHeaderTradeAgreement", _CII)
    delivery = txn.find("ram:ApplicableHeaderTradeDelivery", _CII)
    settlement = txn.find("ram:ApplicableHeaderTradeSettlement", _CII)

    lines: list[LineItem] = []
    for el in txn.findall("ram:IncludedSupplyChainTradeLineItem", _CII):
        line_settle = el.find("ram:SpecifiedLineTradeSettlement", _CII)
        tax = line_settle.find("ram:ApplicableTradeTax", _CII) if line_settle is not None else None
        qty = el.find("ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", _CII)
        period = line_settle.find("ram:BillingSpecifiedPeriod", _CII) if line_settle is not None else None
        rate = _dec(_text(tax, "ram:RateApplicablePercent", _CII))
        line = LineItem(
            description=_text(el, "ram:SpecifiedTradeProduct/ram:Name", _CII) or "—",
            quantity=_dec(qty.text if qty is not None else None, "1"),
            unit_price=_unit_price(
                _text(el, "ram:SpecifiedLineTradeAgreement/"
                          "ram:NetPriceProductTradePrice/ram:ChargeAmount", _CII),
                _text(el, "ram:SpecifiedLineTradeAgreement/"
                          "ram:NetPriceProductTradePrice/ram:BasisQuantity", _CII)),
            vat_rate=rate,
            unit_of_measure=qty.get("unitCode") if qty is not None else None,
            nature=_nature(_text(tax, "ram:CategoryCode", _CII), None) if rate == 0 else None,
            article_code=_text(el, "ram:SpecifiedTradeProduct/ram:SellerAssignedID", _CII),
            period_start=_cii_date(period.find("ram:StartDateTime", _CII)) if period is not None else None,
            period_end=_cii_date(period.find("ram:EndDateTime", _CII)) if period is not None else None,
        )
        if line_settle is not None:
            for ac in line_settle.findall("ram:SpecifiedTradeAllowanceCharge", _CII):
                line.discounts.append(_cii_allowance(ac))
        lines.append(line)

    allowances = [_cii_allowance(ac) for ac in
                  (settlement.findall("ram:SpecifiedTradeAllowanceCharge", _CII)
                   if settlement is not None else [])]

    payments: list[Payment] = []
    terms = settlement.find("ram:SpecifiedTradePaymentTerms", _CII) if settlement is not None else None
    due = _cii_date(terms.find("ram:DueDateDateTime", _CII)) if terms is not None else None
    for pm in (settlement.findall("ram:SpecifiedTradeSettlementPaymentMeans", _CII)
               if settlement is not None else []):
        iban = _text(pm, "ram:PayeePartyCreditorFinancialAccount/ram:IBANID", _CII)
        bic = _text(pm, "ram:PayeeSpecifiedCreditorFinancialInstitution/ram:BICID", _CII)
        payments.append(Payment(
            means=_payment_means(_text(pm, "ram:TypeCode", _CII)),
            due_date=due,
            account=BankAccount(
                iban=iban,
                holder=_text(pm, "ram:PayeePartyCreditorFinancialAccount/ram:AccountName", _CII),
                bank_name=_text(pm, "ram:PayeeSpecifiedCreditorFinancialInstitution/"
                                    "ram:Name", _CII),
                bic=bic,
            ) if iban else None,
        ))

    references: list[DocumentReference] = []
    order = _text(agreement, "ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID", _CII)
    if order:
        references.append(DocumentReference("order", order))
    for cr in (agreement.findall("ram:ContractReferencedDocument", _CII)
               if agreement is not None else []):
        references.append(DocumentReference("contract", _text(cr, "ram:IssuerAssignedID", _CII) or "—"))
    for dd in (delivery.findall("ram:DespatchAdviceReferencedDocument", _CII)
               if delivery is not None else []):
        references.append(DocumentReference("ddt", _text(dd, "ram:IssuerAssignedID", _CII) or "—"))
    for ird in (settlement.findall("ram:InvoiceReferencedDocument", _CII)
                if settlement is not None else []):
        references.append(DocumentReference(
            "invoice", _text(ird, "ram:IssuerAssignedID", _CII) or "—",
            _cii_date(ird.find("ram:FormattedIssueDateTime", _CII))))

    attachments = []
    for adr in (agreement.findall("ram:AdditionalReferencedDocument", _CII)
                if agreement is not None else []):
        blob = adr.find("ram:AttachmentBinaryObject", _CII)
        if blob is None or not blob.text:
            continue
        attachments.append(Attachment(
            filename=blob.get("filename") or _text(adr, "ram:IssuerAssignedID", _CII) or "allegato",
            content=base64.b64decode(blob.text),
            mime=blob.get("mimeCode") or "application/octet-stream",
            description=_text(adr, "ram:Name", _CII),
        ))

    return Invoice(
        number=_text(doc, "ram:ID", _CII) or "—",
        date=issue,
        seller=_cii_party(agreement.find("ram:SellerTradeParty", _CII) if agreement is not None else None),
        buyer=_cii_party(agreement.find("ram:BuyerTradeParty", _CII) if agreement is not None else None),
        lines=lines,
        document_type=_document_type(_text(doc, "ram:TypeCode", _CII)),
        currency=_text(settlement, "ram:InvoiceCurrencyCode", _CII) or "EUR",
        causale=_text(doc, "ram:IncludedNote/ram:Content", _CII),
        payments=payments,
        buyer_reference=_text(agreement, "ram:BuyerReference", _CII),
        allowances_charges=allowances,
        references=references,
        attachments=attachments,
        payment_terms_note=_text(terms, "ram:Description", _CII) if terms is not None else None,
        rounding=_opt_dec(_text(settlement, "ram:SpecifiedTradeSettlementHeaderMonetarySummation/"
                                            "ram:RoundingAmount", _CII)),
    )


def _charge_rate(percent: str | None, category: str | None) -> Decimal | None:
    """The VAT rate a document charge belongs to.

    A category carrying no percent — "O", outside the scope of VAT, which is how
    both syntaxes render an Italian bollo — means a rate of **zero**, not
    "unspecified". Returning ``None`` sent it to the first line's bucket, so a
    2.00 stamp duty came back attracting 22% VAT and inflated the document.
    ``None`` stays reserved for a charge that genuinely names no category.
    """
    if percent not in (None, ""):
        return _dec(percent)
    return Decimal("0") if category else None


def _cii_allowance(el: ET.Element) -> AllowanceCharge:
    flag = el.find("ram:ChargeIndicator/udt:Indicator", _CII)
    return AllowanceCharge(
        amount=_dec(_text(el, "ram:ActualAmount", _CII)),
        is_charge=(flag.text or "").strip().lower() == "true" if flag is not None else False,
        vat_rate=_charge_rate(_text(el, "ram:CategoryTradeTax/ram:RateApplicablePercent", _CII),
                              _text(el, "ram:CategoryTradeTax/ram:CategoryCode", _CII)),
        reason=_text(el, "ram:Reason", _CII),
    )


# ── FatturaPA ──────────────────────────────────────────────────────────────


def _fpa_party(el: ET.Element | None, *, seller: bool) -> Party:
    if el is None:
        raise ValidationError("FatturaPA: blocco anagrafico mancante")
    anag = el.find("DatiAnagrafici")
    sede = el.find("Sede")
    country = (_text(sede, "Nazione", {}) or "IT") if sede is not None else "IT"
    office = _text(el, "IscrizioneREA/Ufficio", {})
    number = _text(el, "IscrizioneREA/NumeroREA", {})
    rea = f"{office}-{number}" if office and number else (office or number)
    return Party(
        name=_text(anag, "Anagrafica/Denominazione", {}),
        first_name=_text(anag, "Anagrafica/Nome", {}),
        last_name=_text(anag, "Anagrafica/Cognome", {}),
        vat_number=_text(anag, "IdFiscaleIVA/IdCodice", {}),
        tax_code=_text(anag, "CodiceFiscale", {}),
        country_code=_text(anag, "IdFiscaleIVA/IdPaese", {}) or country,
        tax_regime=(_text(anag, "RegimeFiscale", {}) or "RF01") if seller else "RF01",
        registration_number=rea,
        email=_text(el, "Contatti/Email", {}),
        address=Address(
            street=_text(sede, "Indirizzo", {}) or "—",
            postcode=_text(sede, "CAP", {}) or "00000",
            city=_text(sede, "Comune", {}) or "—",
            province=_text(sede, "Provincia", {}),
            country=country,
        ),
    )


def parse_fattura_xml(xml: bytes | str) -> Invoice:
    """Parse FatturaPA 1.2 (SdI).

    The one format that preserves the Italian blocks: ritenuta, cassa
    previdenziale, bollo and the ``Natura`` sub-codes all have dedicated
    elements here, so a FatturaPA round-trip is lossless where a UBL one is not.
    """
    root = _root(xml)
    # FatturaPA is often transmitted with the p: prefix and sometimes without a
    # namespace at all (some intermediaries strip it), so search both ways.
    body = root.find(f"{{{FPA}}}FatturaElettronicaBody") or root.find("FatturaElettronicaBody")
    header = root.find(f"{{{FPA}}}FatturaElettronicaHeader") or root.find("FatturaElettronicaHeader")
    if body is None or header is None:
        raise ValidationError("FatturaPA: header o body mancante")

    general = body.find("DatiGenerali/DatiGeneraliDocumento")
    if general is None:
        raise ValidationError("FatturaPA: DatiGeneraliDocumento mancante")
    # Previously this block was only reached because a missing DatiGenerali made
    # the date lookup return None too. That is a real invariant resting on an
    # accident: checking the block itself keeps the later `.findall` calls safe
    # even if the date check ever moves.
    issue = _iso_date(_text(general, "Data", {}))
    if issue is None:
        raise ValidationError("FatturaPA: DatiGeneraliDocumento/Data mancante")

    lines: list[LineItem] = []
    for el in body.findall("DatiBeniServizi/DettaglioLinee"):
        nature_code = _text(el, "Natura", {})
        line = LineItem(
            description=_text(el, "Descrizione", {}) or "—",
            quantity=_dec(_text(el, "Quantita", {}), "1"),
            unit_price=_dec(_text(el, "PrezzoUnitario", {})),
            vat_rate=_dec(_text(el, "AliquotaIVA", {})),
            unit_of_measure=_text(el, "UnitaMisura", {}),
            nature=VatNature(nature_code) if nature_code else None,
            article_code=_text(el, "CodiceArticolo/CodiceValore", {}),
            article_code_type=_text(el, "CodiceArticolo/CodiceTipo", {}) or "INTERNO",
            period_start=_iso_date(_text(el, "DataInizioPeriodo", {})),
            period_end=_iso_date(_text(el, "DataFinePeriodo", {})),
        )
        for sm in el.findall("ScontoMaggiorazione"):
            line.discounts.append(AllowanceCharge(
                amount=_dec(_text(sm, "Importo", {})),
                is_charge=_text(sm, "Tipo", {}) == "MG",
            ))
        lines.append(line)

    payments: list[Payment] = []
    for dp in body.findall("DatiPagamento/DettaglioPagamento"):
        iban = _text(dp, "IBAN", {})
        means_code = _text(dp, "ModalitaPagamento", {})
        payments.append(Payment(
            means=PaymentMeans(means_code) if means_code else PaymentMeans.BANK_TRANSFER,
            amount=_opt_dec(_text(dp, "ImportoPagamento", {})),
            due_date=_iso_date(_text(dp, "DataScadenzaPagamento", {})),
            condition=_text(body, "DatiPagamento/CondizioniPagamento", {}) or "TP02",
            account=BankAccount(
                iban=iban,
                bank_name=_text(dp, "IstitutoFinanziario", {}),
                holder=_text(dp, "Beneficiario", {}),
                bic=_text(dp, "BIC", {}),
            ) if iban else None,
        ))

    references: list[DocumentReference] = []
    for kind, tag in (("order", "DatiOrdineAcquisto"), ("contract", "DatiContratto"),
                      ("ddt", "DatiDDT"), ("invoice", "DatiFattureCollegate")):
        for ref in body.findall(f"DatiGenerali/{tag}"):
            doc_id = _text(ref, "IdDocumento", {}) or _text(ref, "NumeroDDT", {})
            if doc_id:
                references.append(DocumentReference(
                    kind, doc_id,
                    _iso_date(_text(ref, "Data", {}) or _text(ref, "DataDDT", {}))))

    # ── the Italian blocks the other two syntaxes cannot carry ──────────
    withholdings = [
        WithholdingTax(
            amount=_dec(_text(w, "ImportoRitenuta", {})),
            rate=_dec(_text(w, "AliquotaRitenuta", {})),
            kind=WithholdingType(_text(w, "TipoRitenuta", {}) or "RT01"),
            reason=_text(w, "CausalePagamento", {}) or "A",
        )
        for w in general.findall("DatiRitenuta")
    ]
    funds = [
        SocialSecurityFund(
            kind=_text(f, "TipoCassa", {}) or "TC01",
            rate=_dec(_text(f, "AlCassa", {})),
            amount=_dec(_text(f, "ImportoContributoCassa", {})),
            taxable=_opt_dec(_text(f, "ImponibileCassa", {})),
            vat_rate=_dec(_text(f, "AliquotaIVA", {})),
            nature=_fpa_nature(_text(f, "Natura", {})),
            withheld=_text(f, "Ritenuta", {}) == "SI",
        )
        for f in general.findall("DatiCassaPrevidenziale")
    ]
    allowances = [
        AllowanceCharge(
            amount=_dec(_text(sm, "Importo", {})),
            is_charge=_text(sm, "Tipo", {}) == "MG",
        )
        for sm in general.findall("ScontoMaggiorazione")
    ]
    attachments = []
    for att in body.findall("Allegati"):
        payload = _text(att, "Attachment", {})
        if not payload:
            continue
        fmt = (_text(att, "FormatoAttachment", {}) or "").lower()
        attachments.append(Attachment(
            filename=_text(att, "NomeAttachment", {}) or "allegato",
            content=base64.b64decode(payload),
            mime=f"application/{fmt}" if fmt else "application/octet-stream",
            description=_text(att, "DescrizioneAttachment", {}),
        ))

    doc_type = _text(general, "TipoDocumento", {})
    return Invoice(
        number=_text(general, "Numero", {}) or "—",
        date=issue,
        seller=_fpa_party(header.find("CedentePrestatore"), seller=True),
        buyer=_fpa_party(header.find("CessionarioCommittente"), seller=False),
        lines=lines,
        document_type=DocumentType(doc_type) if doc_type else DocumentType.INVOICE,
        currency=_text(general, "Divisa", {}) or "EUR",
        causale=_text(general, "Causale", {}),
        payments=payments,
        references=references,
        buyer_reference=_text(header, "CessionarioCommittente/"
                                     "RiferimentoAmministrazione", {}),
        recipient_code=_text(header, "DatiTrasmissione/CodiceDestinatario", {}),
        recipient_pec=_text(header, "DatiTrasmissione/PECDestinatario", {}),
        stamp_duty=_opt_dec(_text(general, "DatiBollo/ImportoBollo", {})),
        rounding=_opt_dec(_text(general, "Arrotondamento", {})),
        withholdings=withholdings,
        funds=funds,
        allowances_charges=allowances,
        attachments=attachments,
        art73=_text(general, "Art73", {}) == "SI",
        exigibility=_fpa_exigibility(body),
    )


def _fpa_nature(code: str | None) -> VatNature | None:
    """A FatturaPA ``Natura`` is the exact code — no narrowing needed here."""
    try:
        return VatNature(code) if code else None
    except ValueError:
        return None


def _fpa_exigibility(body: ET.Element) -> VatExigibility | None:
    """``EsigibilitaIVA`` lives on each riepilogo; they agree in practice, so
    the first one that states it speaks for the document."""
    for riep in body.findall("DatiBeniServizi/DatiRiepilogo"):
        value = _text(riep, "EsigibilitaIVA", {})
        if value:
            try:
                return VatExigibility(value)
            except ValueError:
                return None
    return None


# ── declared vs computed ───────────────────────────────────────────────────


def compare_declared_totals(xml: bytes | str) -> dict[str, Decimal | None]:
    """The totals a document *claims*, beside the ones its lines *produce*.

    A supplier's arithmetic is their own; importing their stated total as fact
    hides the case where it disagrees with their own lines. This returns both so
    the difference is visible:

        result = compare_declared_totals(received_xml)
        if result["difference"]:
            ...  # query it before paying

    ``declared`` is ``None`` when the document states no total (a header-only
    Factur-X profile, or a stripped-down FatturaPA).
    """
    standard = detect_standard(xml)
    root = _root(xml)
    if standard == "ubl":
        declared = _opt_dec(_text(root, "cac:LegalMonetaryTotal/cbc:PayableAmount", _UBL))
    elif standard == "cii":
        declared = _opt_dec(_text(
            root, "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"
                  "ram:SpecifiedTradeSettlementHeaderMonetarySummation/"
                  "ram:GrandTotalAmount", _CII))
    else:
        body = root.find(f"{{{FPA}}}FatturaElettronicaBody") or root.find("FatturaElettronicaBody")
        declared = _opt_dec(_text(
            body, "DatiGenerali/DatiGeneraliDocumento/ImportoTotaleDocumento", {}))

    computed = parse_invoice(xml, standard=standard).total_document()
    return {
        "declared": declared,
        "computed": computed,
        "difference": None if declared is None else declared - computed,
    }
