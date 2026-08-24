"""Country-neutral invoice domain (EN 16931-aligned).

This is the single internal model. Country/format renderers (FatturaPA, UBL …)
and transport adapters (SdI, PEPPOL …) consume it; the hosting platform only
maps its data onto :class:`Invoice`. Italian specifics (ritenuta, bollo, natura,
split payment, regime fiscale, cassa previdenziale) live here as OPTIONAL
fields so the same model serves other countries — you simply don't set them.

Money is always :class:`decimal.Decimal`. FatturaPA/UBL work on NET amounts and
add VAT, so :class:`LineItem` carries a net ``unit_price``; use
:meth:`LineItem.from_gross` for VAT-included (POS) prices.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .enums import (
    DocumentType,
    PaymentMeans,
    TransmissionFormat,
    VatExigibility,
    VatNature,
    WithholdingType,
)
from .errors import ValidationError
from .money import D, q2, q6
from .rates import ProductCategory, rate_for

__all__ = [
    "Address", "Party", "LineItem", "VatSummary", "AllowanceCharge", "Advisory",
    "WithholdingTax", "SocialSecurityFund", "DocumentReference", "Attachment",
    "BankAccount", "Payment", "Invoice", "DocumentType", "TransmissionFormat",
    "VatNature", "VatExigibility", "PaymentMeans", "WithholdingType",
]

#: Peppol EAS (Electronic Address Scheme) per paese, usato per derivare
#: l'``EndpointID`` UBL dalla P.IVA quando non è impostato un endpoint
#: esplicito. Per l'Italia si preferisce 0211 (Partita IVA, ICD ufficiale)
#: al legacy 9906 (IT:VAT). Per gli schemi VAT (0211 e 99xx) il valore
#: include il prefisso paese (es. ``IT01234567890``); per gli schemi basati
#: su registri nazionali (0007/0192/0184/0216) viene usato l'identificativo
#: così com'è — per quei paesi è preferibile impostare ``endpoint_id``
#: esplicitamente.
PEPPOL_EAS_BY_COUNTRY = {
    "IT": "0211",
    # EU — legacy "<country>:VAT" EAS schemes (Peppol codelist), still valid
    # for endpoint derivation from the VAT number.
    "DE": "9930",
    "FR": "9957",
    "NL": "9944",
    "BE": "9925",
    "ES": "9920",
    "AT": "9914",
    "BG": "9926",
    "CY": "9928",
    "CZ": "9929",
    "EE": "9931",
    "GR": "9933",
    "HR": "9934",
    "HU": "9910",
    "IE": "9935",
    "LT": "9937",
    "LU": "9938",
    "LV": "9939",
    "MT": "9943",
    "PL": "9945",
    "PT": "9946",
    "RO": "9947",
    "SI": "9949",
    "SK": "9950",
    # National-registry schemes (identifier used as-is).
    "SE": "0007",
    "NO": "0192",
    "DK": "0184",
    "FI": "0216",
    # United Kingdom (GB:VAT).
    "GB": "9932",
    # Switzerland — CH UID (the CHE number), used as-is, NOT VAT-prefixed:
    # the identifier already carries its own "CHE" prefix.
    "CH": "0183",
}

_VAT_PREFIXED_SCHEMES = frozenset(
    {"0211", "9906", "9910", "9914", "9920", "9925", "9926", "9928", "9929",
     "9930", "9931", "9932", "9933", "9934", "9935", "9937", "9938", "9939",
     "9943", "9944", "9945", "9946", "9947", "9949", "9950", "9957"}
)


#: Countries whose tax identifier already carries its own alphabetic prefix —
#: adding the ISO country code would produce "CHCHE123456789".
_SELF_PREFIXED_TAX_IDS = frozenset({"CH"})


def _vies_prefix(country_code: str) -> str:
    """The VAT-number prefix for VIES/UBL ``CompanyID`` — Greece uses "EL"."""
    return "EL" if country_code == "GR" else country_code


@dataclass
class Address:
    street: str
    postcode: str
    city: str
    province: str | None = None
    country: str = "IT"


@dataclass
class Party:
    name: str | None = None
    address: Address | None = None
    vat_number: str | None = None
    country_code: str = "IT"
    tax_code: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    tax_regime: str = "RF01"          # seller only (RegimeFiscale)
    pec: str | None = None
    sdi_code: str | None = None       # buyer's CodiceDestinatario
    email: str | None = None
    endpoint_id: str | None = None    # Peppol participant id (explicit)
    endpoint_scheme: str | None = None  # Peppol EAS, e.g. "0211" / "9930"
    registration_number: str | None = None  # REA / registro imprese

    def display_name(self) -> str:
        if self.name:
            return self.name
        return " ".join(p for p in (self.first_name, self.last_name) if p) or "—"

    def normalized_vat(self) -> str:
        """The bare VAT/UID number: no country prefix, no dots, dashes or
        spaces. Printed forms (``"CHE-116.281.710 MWST"``, ``"IT 0123 456 7891"``)
        must never reach the XML — a receiver matches on the exact string."""
        from .taxid import normalize_tax_id

        return normalize_tax_id(self.country_code, self.vat_number)

    def peppol_endpoint(self) -> tuple[str | None, str | None]:
        """``(scheme, id)`` for the UBL ``EndpointID``.

        Explicit ``endpoint_scheme``/``endpoint_id`` win; otherwise the pair is
        derived from the VAT number via :data:`PEPPOL_EAS_BY_COUNTRY`. Returns
        ``(None, None)`` for unmapped countries (the renderer omits the
        element).
        """
        if self.endpoint_id:
            return self.endpoint_scheme, self.endpoint_id
        scheme = PEPPOL_EAS_BY_COUNTRY.get(self.country_code)
        if scheme is None or not self.vat_number:
            return None, None
        bare = self.normalized_vat()
        if scheme in _VAT_PREFIXED_SCHEMES:
            return scheme, f"{_vies_prefix(self.country_code)}{bare}"
        return scheme, bare

    def tax_company_id(self) -> str | None:
        """The ``PartyTaxScheme/CompanyID``: VIES-prefixed VAT number for
        VAT countries (Greece → "EL"), the bare id elsewhere (e.g. US EIN).

        The number is normalized first, so a party stored as ``"IT01234567891"``
        does not come out as ``"ITIT01234567891"``, and Switzerland is not
        prefixed at all — a Swiss UID already begins with its own ``CHE``.
        """
        if not self.vat_number:
            return None
        from .countries import profile_for

        bare = self.normalized_vat()
        if self.country_code in _SELF_PREFIXED_TAX_IDS:
            return bare
        if profile_for(self.country_code).tax_scheme == "VAT":
            return f"{_vies_prefix(self.country_code)}{bare}"
        return bare

    @property
    def postal_address(self) -> Address:
        """The address, guaranteed present.

        :meth:`validate` already enforces this and every renderer runs after
        ``Invoice.validate()``, but renderers reach into the address a dozen
        times each. Going through here means a broken invariant raises with a
        name attached instead of emitting a document with an empty address
        block — or an ``AttributeError`` from deep inside XML generation.
        """
        if self.address is None:
            raise ValidationError(f"{self.display_name()}: indirizzo mancante")
        return self.address

    def validate(self, *, role: str) -> None:
        if not (self.name or (self.first_name and self.last_name)):
            raise ValidationError(f"{role}: serve Denominazione oppure Nome + Cognome")
        if not (self.vat_number or self.tax_code):
            raise ValidationError(f"{role}: serve P.IVA oppure Codice Fiscale")
        if self.address is None:
            raise ValidationError(f"{role}: indirizzo mancante")


@dataclass
class AllowanceCharge:
    """Document- or line-level discount (allowance) or surcharge (charge)."""

    amount: Decimal
    is_charge: bool = False           # False = sconto, True = maggiorazione
    vat_rate: Decimal | None = None   # rate bucket it applies to
    reason: str | None = None

    def __post_init__(self) -> None:
        self.amount = D(self.amount)
        if self.vat_rate is not None:
            self.vat_rate = D(self.vat_rate)

    @property
    def signed(self) -> Decimal:
        return self.amount if self.is_charge else -self.amount


@dataclass
class LineItem:
    description: str
    quantity: Decimal
    unit_price: Decimal               # NET (imponibile)
    vat_rate: Decimal                 # percentage
    unit_of_measure: str | None = None
    nature: VatNature | None = None   # required by IT when vat_rate == 0
    discounts: list[AllowanceCharge] = field(default_factory=list)  # ScontoMaggiorazione di linea
    article_code: str | None = None   # CodiceArticolo/CodiceValore
    article_code_type: str = "INTERNO"  # CodiceArticolo/CodiceTipo
    period_start: date | None = None
    period_end: date | None = None
    exemption_reason: str | None = None  # testo UBL/RiferimentoNormativo (fallback: nature)
    #: What is being sold, in the vocabulary reduced rates are written in.
    #: Optional and purely advisory: setting it lets :meth:`Invoice.check`
    #: compare the rate you used against the one the country applies to that
    #: kind of supply. It is not rendered into any format — no e-invoicing
    #: standard carries it — and nothing validates against it.
    category: ProductCategory | None = None

    def __post_init__(self) -> None:
        self.quantity = D(self.quantity)
        self.unit_price = D(self.unit_price)
        self.vat_rate = D(self.vat_rate)

    @property
    def total(self) -> Decimal:
        """Line total NET of line-level discounts/charges (``PrezzoTotale``)."""
        gross = self.unit_price * self.quantity
        adj = sum((d.signed for d in self.discounts), Decimal("0"))
        return q2(gross + adj)

    @classmethod
    def from_gross(cls, description, quantity, gross_unit_price, vat_rate,
                   unit_of_measure=None, nature=None) -> LineItem:
        rate = D(vat_rate)
        net = q6(D(gross_unit_price) / (Decimal("1") + rate / Decimal("100")))
        return cls(description, D(quantity), net, rate, unit_of_measure, nature)


@dataclass
class WithholdingTax:
    """Ritenuta d'acconto."""

    amount: Decimal
    rate: Decimal
    kind: WithholdingType = WithholdingType.NATURAL_PERSON
    reason: str = "A"                 # CausalePagamento (Modello 770)

    def __post_init__(self) -> None:
        self.amount = D(self.amount)
        self.rate = D(self.rate)


@dataclass
class SocialSecurityFund:
    """Cassa previdenziale (``DatiCassaPrevidenziale``).

    The contribution joins the VAT base of its ``vat_rate`` bucket, as
    required by FatturaPA.
    """

    kind: str                          # TipoCassa TC01–TC22
    rate: Decimal                      # AlCassa (percentuale)
    amount: Decimal                    # ImportoContributoCassa
    taxable: Decimal | None = None     # ImponibileCassa
    vat_rate: Decimal = Decimal("0")   # AliquotaIVA applicata al contributo
    nature: VatNature | None = None    # Natura, se il contributo non è imponibile
    withheld: bool = False             # Ritenuta = "SI"

    def __post_init__(self) -> None:
        self.rate = D(self.rate)
        self.amount = D(self.amount)
        if self.taxable is not None:
            self.taxable = D(self.taxable)
        self.vat_rate = D(self.vat_rate)


@dataclass
class DocumentReference:
    """Riferimento a ordine / contratto / DDT / fattura collegata."""

    kind: str                          # "order" | "contract" | "ddt" | "invoice"
    doc_id: str
    date: date | None = None
    line_numbers: list[int] = field(default_factory=list)


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime: str = "application/octet-stream"
    description: str | None = None


@dataclass
class BankAccount:
    iban: str
    bank_name: str | None = None
    holder: str | None = None
    bic: str | None = None


@dataclass
class Payment:
    means: PaymentMeans = PaymentMeans.BANK_TRANSFER
    amount: Decimal | None = None
    due_date: date | None = None
    account: BankAccount | None = None
    condition: str = "TP02"           # CondizioniPagamento


@dataclass(frozen=True)
class Advisory:
    """A non-fatal finding from :meth:`Invoice.check`.

    ``code`` is stable and machine-readable so a caller can suppress a class of
    finding it has already reasoned about; ``message`` is for a human.
    """

    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


@dataclass
class VatSummary:
    vat_rate: Decimal
    taxable: Decimal
    tax: Decimal
    nature: VatNature | None = None
    exemption_reason: str | None = None  # per RiferimentoNormativo / TaxExemptionReason


@dataclass
class Invoice:
    number: str
    date: date
    seller: Party
    buyer: Party
    lines: list[LineItem]
    document_type: DocumentType = DocumentType.INVOICE
    currency: str = "EUR"
    transmission_format: TransmissionFormat = TransmissionFormat.PRIVATE
    causale: str | None = None
    payments: list[Payment] = field(default_factory=list)
    # Routing
    recipient_code: str | None = None
    recipient_pec: str | None = None
    # Optional fiscal blocks (mostly IT; leave empty for other countries)
    allowances_charges: list[AllowanceCharge] = field(default_factory=list)
    withholdings: list[WithholdingTax] = field(default_factory=list)
    references: list[DocumentReference] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    stamp_duty: Decimal | None = None   # bollo virtuale (es. 2,00 €)
    split_payment: bool = False         # scissione dei pagamenti (PA)
    buyer_reference: str | None = None  # BT-10 (Peppol BuyerReference)
    exigibility: VatExigibility | None = None  # override EsigibilitaIVA
    funds: list[SocialSecurityFund] = field(default_factory=list)
    art73: bool = False                 # documento emesso ex art. 73 DPR 633/72
    rounding: Decimal | None = None     # Arrotondamento di documento
    payment_terms_note: str | None = None

    # ── routing / totals ──────────────────────────────────────────────

    def resolved_recipient(self) -> tuple[str, str | None]:
        """``(CodiceDestinatario, PECDestinatario?)``.

        Fallbacks: "0000000" for IT recipients without an explicit code
        (B2C / PEC routing), "XXXXXXX" for foreign recipients (SdI
        convention). PA (FPA12) codes are 6 chars and never padded.
        """
        code = self.recipient_code or self.buyer.sdi_code
        if not code:
            code = "XXXXXXX" if self.buyer.country_code != "IT" else "0000000"
        pec = self.recipient_pec or self.buyer.pec
        return code, (pec if code == "0000000" else None)

    def resolved_exigibility(self) -> str:
        """``EsigibilitaIVA``: explicit override, else split payment → "S",
        else immediate."""
        if self.exigibility is not None:
            return self.exigibility.value
        return "S" if self.split_payment else "I"

    def vat_summary(self) -> list[VatSummary]:
        # Bucket per (aliquota, natura): a pari aliquota 0 nature diverse
        # restano riepiloghi distinti (regimi diversi non vanno mischiati).
        buckets: dict[str, list] = {}
        order: list[str] = []

        def key_for(rate: Decimal, nature: VatNature | None) -> str:
            return f"{rate:.2f}|{nature.value if nature else ''}"

        def bucket(rate: Decimal, nature: VatNature | None) -> list:
            key = key_for(rate, nature)
            if key not in buckets:
                buckets[key] = [Decimal("0"), nature, None]
                order.append(key)
            return buckets[key]

        for ln in self.lines:
            b = bucket(ln.vat_rate, ln.nature)
            b[0] += ln.total
            if b[2] is None and ln.exemption_reason:
                b[2] = ln.exemption_reason
        # La cassa previdenziale concorre all'imponibile della sua aliquota.
        for fund in self.funds:
            bucket(fund.vat_rate, fund.nature)[0] += fund.amount
        # Apply document-level allowances/charges to their rate bucket
        # (default to the first/most-common rate when unspecified).
        for ac in self.allowances_charges:
            rate = ac.vat_rate if ac.vat_rate is not None else self.lines[0].vat_rate
            prefix = f"{rate:.2f}|"
            key = next((k for k in order if k.startswith(prefix)), None)
            if key is None:
                # A document charge at a rate no line uses still has to be
                # taxed and totalled. Skipping it — which is what this did —
                # made the amount vanish from the totals while still being
                # rendered into the XML: an invoice that under-bills and does
                # not add up. Give it its own riepilogo instead.
                key = key_for(rate, None)
                buckets[key] = [Decimal("0"), None, None]
                order.append(key)
            buckets[key][0] += ac.signed
        out: list[VatSummary] = []
        for key in order:
            rate = D(key.split("|", 1)[0])
            taxable = q2(buckets[key][0])
            tax = q2(taxable * rate / Decimal("100"))
            nature = buckets[key][1]
            reason = buckets[key][2] or (
                nature.default_exemption_reason if nature else None
            )
            out.append(VatSummary(rate, taxable, tax, nature, reason))
        return out

    def lines_total(self) -> Decimal:
        """Somma dei totali riga (UBL ``LineExtensionAmount``, BR-CO-10)."""
        return q2(sum((ln.total for ln in self.lines), Decimal("0")))

    def allowance_total(self) -> Decimal:
        """Somma (positiva) degli sconti di documento."""
        return q2(sum((ac.amount for ac in self.allowances_charges
                       if not ac.is_charge), Decimal("0")))

    def charge_total(self) -> Decimal:
        """Somma (positiva) delle maggiorazioni di documento."""
        return q2(sum((ac.amount for ac in self.allowances_charges
                       if ac.is_charge), Decimal("0")))

    def taxable_total(self) -> Decimal:
        return q2(sum((v.taxable for v in self.vat_summary()), Decimal("0")))

    def tax_total(self) -> Decimal:
        return q2(sum((v.tax for v in self.vat_summary()), Decimal("0")))

    def withholding_total(self) -> Decimal:
        return q2(sum((w.amount for w in self.withholdings), Decimal("0")))

    def total_document(self) -> Decimal:
        total = self.taxable_total() + self.tax_total()
        if self.stamp_duty:
            total += D(self.stamp_duty)
        if self.rounding:
            total += D(self.rounding)
        return q2(total)

    def total_payable(self) -> Decimal:
        """Net amount due = document total minus withholdings."""
        return q2(self.total_document() - self.withholding_total())

    def validate(self) -> None:
        """Core checks + the seller-country profile rules.

        The Italian-only constraints (RegimeFiscale, CodiceDestinatario, CAP,
        Natura) live in the IT :class:`~einvoice.countries.CountryProfile`, so
        the same neutral invoice validates for EU/UK/CH/US sellers too.

        Raises on anything that makes the document *wrong*. For things that are
        merely *suspicious* — an implausible VAT rate, a cross-border supply
        that looks like it should be reverse-charged — see :meth:`check`.
        """
        from .countries import profile_for

        self.seller.validate(role="Cedente/Prestatore")
        self.buyer.validate(role="Cessionario/Committente")
        if not self.lines:
            raise ValidationError("La fattura deve avere almeno una riga")
        if not self.number:
            raise ValidationError("Numero documento mancante")
        profile_for(self.seller.country_code).validate_invoice(self)

    def check(self) -> list[Advisory]:
        """Non-fatal findings: things worth a human look before sending.

        Separate from :meth:`validate` on purpose. A hard failure must mean
        "this document is invalid"; an unusual VAT rate or a missing buyer VAT
        number on a cross-border supply is often legitimate, and refusing to
        emit those would block real invoices. Returning them instead lets a UI
        surface a warning and a batch job log one.

        Never raises — a malformed invoice simply yields whatever findings are
        computable.
        """
        from .countries import EU_COUNTRIES, profile_for

        out: list[Advisory] = []
        seller_country = self.seller.country_code
        buyer_country = self.buyer.country_code
        profile = profile_for(seller_country)

        out.extend(Advisory("country", m) for m in profile.advisories(self))

        # Cross-border EU B2B: the supply is normally reverse-charged, so a
        # domestic VAT rate on it is a common and expensive mistake.
        cross_border_eu = (
            seller_country in EU_COUNTRIES
            and buyer_country in EU_COUNTRIES
            and seller_country != buyer_country
        )
        if cross_border_eu and self.buyer.vat_number:
            taxed = [ln for ln in self.lines if ln.vat_rate > 0]
            if taxed:
                out.append(Advisory(
                    "intra_eu_vat",
                    f"Cessione intracomunitaria {seller_country}→{buyer_country} con "
                    f"IVA esposta su {len(taxed)} riga/e: di norma è non imponibile "
                    "(inversione contabile). Verificare il regime.",
                ))
        if cross_border_eu and not self.buyer.vat_number:
            out.append(Advisory(
                "intra_eu_no_vat_id",
                f"Cessionario in {buyer_country} senza partita IVA: senza un "
                "identificativo valido l'operazione non può essere trattata come "
                "cessione intracomunitaria.",
            ))

        # A supply out of the EU that still carries VAT.
        if (seller_country in EU_COUNTRIES and buyer_country
                and buyer_country not in EU_COUNTRIES
                and any(ln.vat_rate > 0 for ln in self.lines)):
            out.append(Advisory(
                "export_vat",
                f"Operazione verso {buyer_country} (fuori UE) con IVA esposta: "
                "un'esportazione è di norma non imponibile.",
            ))

        if self.currency != profile.currency_hint and profile.currency_hint:
            out.append(Advisory(
                "currency",
                f"Valuta {self.currency} diversa da quella abituale di "
                f"{seller_country} ({profile.currency_hint}): assicurarsi che il "
                "destinatario la accetti.",
            ))

        if self.payments and any(
            p.due_date and p.due_date < self.date for p in self.payments
        ):
            out.append(Advisory(
                "due_date",
                "Data di scadenza anteriore alla data del documento.",
            ))

        out.extend(self._correction_advisories())
        out.extend(self._category_advisories(seller_country))
        return out

    def _category_advisories(self, seller_country: str) -> list[Advisory]:
        """Lines whose rate disagrees with what the country charges for that
        kind of supply.

        Only fires for lines that declared a :attr:`LineItem.category`, and only
        where this package can state the country's rate for it — an unmapped
        category is silence, not a complaint. Reduced-rate law turns on
        distinctions an invoice does not carry, so a mismatch is a question
        worth asking, never a verdict.
        """
        out: list[Advisory] = []
        for line in self.lines:
            if line.category is None:
                continue
            expected = rate_for(seller_country, line.category)
            if expected is None or D(expected) == line.vat_rate:
                continue
            out.append(Advisory(
                "rate_category",
                f"Riga '{line.description}': aliquota {line.vat_rate}% per "
                f"'{line.category.value}', ma {seller_country} applica di norma "
                f"{expected}% a questa categoria. Verificare — le eccezioni "
                "nazionali esistono, ma di solito è un errore di aliquota.",
            ))
        return out

    def _correction_advisories(self) -> list[Advisory]:
        """Findings specific to credit and debit notes.

        Both are corrections to an earlier invoice, and both go wrong in the
        same two ways: the sign gets applied twice, or the document says nothing
        about what it is correcting.
        """
        out: list[Advisory] = []
        if not self.document_type.corrects_an_earlier_document:
            return out

        # A credit note already means "we owe you"; the direction is carried by
        # the document type, not by the sign of the amounts. Entering the
        # amounts as negatives applies it twice and produces a document that
        # asks the customer to pay — the expensive version of this mistake.
        total = self.total_document()
        kind = "nota di credito" if self.document_type.is_credit_note else "nota di debito"
        if total < 0:
            out.append(Advisory(
                "correction_sign",
                f"{kind.capitalize()} con totale negativo ({total}). Il verso è già "
                "dato dal tipo documento: gli importi vanno indicati POSITIVI, "
                "altrimenti il segno si applica due volte e il documento dice "
                "l'opposto di quello che intende.",
            ))

        # Without a reference the receiver cannot match the correction to
        # anything. SdI and most CIUS accept it, so this is a warning — but an
        # unmatched credit note sits in the customer's ledger unapplied.
        if not any(ref.kind == "invoice" for ref in self.references):
            out.append(Advisory(
                "correction_no_reference",
                f"{kind.capitalize()} senza riferimento alla fattura che "
                "rettifica: il destinatario non può abbinarla. Aggiungere un "
                "DocumentReference(kind='invoice', doc_id=…).",
            ))
        return out
