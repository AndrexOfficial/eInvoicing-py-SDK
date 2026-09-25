"""Preventivi, pro forma e DDT: i documenti intorno alla fattura.

Five documents follow a sale, and only two of them are fiscal::

    Quote ──► ProForma ──► Invoice ──► credit_note_for(invoice)
      │                      ▲
      └──► DeliveryNote ─────┘  deferred_invoice([ddt, ddt, …])   (TD24)

* :class:`Quote` (*preventivo*) — an offer with a validity date.
* :class:`ProForma` (*fattura pro forma*) — a request for payment that is **not**
  an invoice: no tax point, no number in the invoice sequence, never sent to
  SdI or Peppol.
* :class:`DeliveryNote` (*documento di trasporto*, DPR 472/1996) — the paper
  that travels with the goods and lets them be invoiced later, together, with
  a deferred invoice.
* :class:`~einvoice.models.Invoice` and its credit note are the fiscal pair,
  unchanged.

The commercial documents are separate types on purpose, not an ``Invoice`` with
a flag. Every renderer refuses them (:func:`~einvoice.formats.base.require_invoice`):
a pro forma transmitted by mistake *is* an invoice, and undoing it takes a
credit note. The conversions are explicit, carry the lines and the fiscal
blocks across unchanged, and — because :class:`Quote` and :class:`ProForma`
total with the very same code as :class:`~einvoice.models.Invoice` — the invoice
a quote becomes adds up to exactly what the quote said.

What is *not* here: numbering (a sequence is the host's database, with its
locks) and persistence. :func:`initial_status` / :func:`can_transition` state
which status changes make sense, so two products embedding this package refuse
the same things.
"""
from __future__ import annotations

import copy
import datetime as _dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from typing import Any, ClassVar

from .enums import DocumentKind, DocumentStatus, DocumentType, TransportBy, VatNature
from .errors import IllegalTransition, ValidationError
from .models import (
    Advisory,
    AllowanceCharge,
    DocumentReference,
    Invoice,
    LineItem,
    Party,
    Payment,
    SocialSecurityFund,
    TransportDetails,
    WithholdingTax,
    _TotalsMixin,
)
from .money import CENTS, D, q2

__all__ = [
    "Quote", "ProForma", "DeliveryNote", "DeliveryLine",
    "deferred_invoice", "credit_note_for",
    "initial_status", "can_transition", "next_statuses", "transition",
    "document_kind",
]


# ── shared checks ────────────────────────────────────────────────────────


def _require_number(number: str, what: str) -> None:
    if not (number or "").strip():
        raise ValidationError(f"{what}: numero documento mancante")


def _require_name(party: Party, role: str) -> None:
    if not (party.name or (party.first_name and party.last_name)):
        raise ValidationError(f"{role}: serve Denominazione oppure Nome + Cognome")


def _require_lines(lines: Sequence[Any], what: str) -> None:
    if not lines:
        raise ValidationError(f"{what}: serve almeno una riga")


def _source_note(kind: DocumentKind, number: str, issued: date, seller_country: str) -> str:
    """«Preventivo N. 12 — 03/09/2026», in the seller's language."""
    from .i18n import locale_for_country, translate

    locale = locale_for_country(seller_country)
    title = translate(f"doc.kind.{kind.value}", locale)
    title = title[:1].upper() + title[1:].lower() if title.isupper() else title
    return f"{title} {translate('doc.number', locale)} {number} — {issued:%d/%m/%Y}"


def _join(*parts: str | None) -> str | None:
    text = " — ".join(p.strip() for p in parts if p and p.strip())
    return text or None


def _preview_advisories(doc: _PricedDocument) -> list[Advisory]:
    """The invoice checks that already make sense on a quote or a pro forma.

    The rate a quote proposes is the rate the invoice will charge: telling the
    operator it looks wrong *before* the customer signs is the cheap moment.
    Checks about things only an invoice has (due dates, corrections, deferred
    deadlines) are left out.
    """
    relevant = {"country", "intra_eu_vat", "intra_eu_no_vat_id", "export_vat",
                "currency", "rate_category"}
    preview = Invoice(number=doc.number or "0", date=doc.date, seller=doc.seller,
                      buyer=doc.buyer, lines=doc.lines, currency=doc.currency,
                      allowances_charges=doc.allowances_charges, funds=doc.funds,
                      withholdings=doc.withholdings)
    return [a for a in preview.check() if a.code in relevant]


# ── quote and pro forma ──────────────────────────────────────────────────


@dataclass
class _PricedDocument(_TotalsMixin):
    """Fields and conversions shared by the two priced commercial documents."""

    number: str
    date: date
    seller: Party
    buyer: Party
    lines: list[LineItem]
    currency: str = "EUR"
    #: Printed text: terms, conditions, what is and is not included.
    notes: str | None = None
    payments: list[Payment] = field(default_factory=list)
    payment_terms_note: str | None = None
    allowances_charges: list[AllowanceCharge] = field(default_factory=list)
    withholdings: list[WithholdingTax] = field(default_factory=list)
    funds: list[SocialSecurityFund] = field(default_factory=list)
    stamp_duty: Decimal | None = None
    rounding: Decimal | None = None
    references: list[DocumentReference] = field(default_factory=list)

    kind: ClassVar[DocumentKind]

    def _validate_common(self, what: str) -> None:
        _require_number(self.number, what)
        self.seller.validate(role=f"{what}: fornitore")
        _require_name(self.buyer, f"{what}: cliente")
        _require_lines(self.lines, what)

    def check(self) -> list[Advisory]:
        """Non-fatal findings, like :meth:`Invoice.check`. Never raises."""
        try:
            return _preview_advisories(self)
        except Exception:
            return []

    def to_invoice(self, *, number: str, date: _dt.date,
                   document_type: DocumentType | None = None,
                   mention_source: bool = True, **overrides: Any) -> Invoice:
        """The invoice this document becomes — same lines, same fiscal blocks.

        ``number`` and ``date`` are the invoice's own: an invoice is numbered in
        the invoice sequence and dated when it is issued, never inherited from
        the quote or the pro forma. With ``mention_source`` the causale names the
        document it came from («Preventivo N. 12 — 03/09/2026»), so the customer
        can match the two. Anything else can be overridden by keyword, e.g.
        ``payments=[…]`` or ``recipient_code="ABCDEFG"``.

        The result is **not** validated here: an offer made to a prospect may
        lack the fiscal data an invoice requires, and the place to say so is
        :meth:`Invoice.validate`, at issue time.
        """
        own: DocumentType = getattr(self, "document_type", DocumentType.INVOICE)
        doc_type = document_type if document_type is not None else own
        if doc_type.is_credit_note:
            raise ValidationError("Un preventivo o una pro forma non diventano una nota di credito")
        causale = overrides.pop("causale", getattr(self, "causale", None))
        if mention_source:
            causale = _join(causale, _source_note(self.kind, self.number, self.date,
                                                  self.seller.country_code))
        fields: dict[str, Any] = {
            "number": number, "date": date,
            "seller": copy.deepcopy(self.seller), "buyer": copy.deepcopy(self.buyer),
            "lines": copy.deepcopy(self.lines), "document_type": doc_type,
            "currency": self.currency, "causale": causale,
            "payments": copy.deepcopy(self.payments),
            "allowances_charges": copy.deepcopy(self.allowances_charges),
            "withholdings": copy.deepcopy(self.withholdings),
            "funds": copy.deepcopy(self.funds),
            "stamp_duty": self.stamp_duty, "rounding": self.rounding,
            "references": copy.deepcopy(self.references),
            "payment_terms_note": self.payment_terms_note,
        }
        fields.update(overrides)
        return Invoice(**fields)


@dataclass
class Quote(_PricedDocument):
    """Un preventivo: un'offerta, con una scadenza.

    It totals exactly like the invoice it may become (same code), and it can
    carry the same fiscal blocks — a professional's estimate shows the cassa
    previdenziale and the ritenuta so the client sees the net amount.
    """

    valid_until: date | None = None

    kind: ClassVar[DocumentKind] = DocumentKind.QUOTE

    def validate(self) -> None:
        self._validate_common("Preventivo")
        if self.valid_until is not None and self.valid_until < self.date:
            raise ValidationError(
                f"Preventivo: validità ({self.valid_until:%d/%m/%Y}) anteriore alla "
                f"data del documento ({self.date:%d/%m/%Y})")

    def is_expired(self, on: _dt.date) -> bool:
        """Whether the offer has lapsed on ``on``. The last valid day is valid."""
        return self.valid_until is not None and on > self.valid_until

    def to_proforma(self, *, number: str, date: _dt.date, mention_source: bool = True,
                    **overrides: Any) -> ProForma:
        """The accepted quote as a pro forma — typically to collect a deposit."""
        notes = overrides.pop("notes", self.notes)
        fields: dict[str, Any] = {
            "number": number, "date": date,
            "seller": copy.deepcopy(self.seller), "buyer": copy.deepcopy(self.buyer),
            "lines": copy.deepcopy(self.lines), "currency": self.currency, "notes": notes,
            "payments": copy.deepcopy(self.payments),
            "payment_terms_note": self.payment_terms_note,
            "allowances_charges": copy.deepcopy(self.allowances_charges),
            "withholdings": copy.deepcopy(self.withholdings),
            "funds": copy.deepcopy(self.funds),
            "stamp_duty": self.stamp_duty, "rounding": self.rounding,
            "references": copy.deepcopy(self.references),
            "causale": _source_note(self.kind, self.number, self.date,
                                    self.seller.country_code) if mention_source else None,
        }
        fields.update(overrides)
        return ProForma(**fields)

    def to_delivery_note(self, *, number: str, date: _dt.date,
                         transport: TransportDetails | None = None,
                         include_prices: bool = True, **overrides: Any) -> DeliveryNote:
        """The goods of the quote, on their way.

        With ``include_prices`` the DDT is *valorizzato*: it carries price and
        rate per line, so it can later be invoiced without asking again. A line
        discount travels with its line — dropping it here would re-appear as an
        overcharge on the deferred invoice.
        """
        lines = [DeliveryLine(
            description=ln.description, quantity=ln.quantity,
            unit_of_measure=ln.unit_of_measure, article_code=ln.article_code,
            unit_price=ln.unit_price if include_prices else None,
            vat_rate=ln.vat_rate if include_prices else None,
            nature=ln.nature if include_prices else None,
            discounts=copy.deepcopy(ln.discounts) if include_prices else [],
        ) for ln in self.lines]
        fields: dict[str, Any] = {
            "number": number, "date": date,
            "seller": copy.deepcopy(self.seller), "buyer": copy.deepcopy(self.buyer),
            "lines": lines, "transport": copy.deepcopy(transport) or TransportDetails(),
            "currency": self.currency,
            "references": copy.deepcopy(self.references),
        }
        fields.update(overrides)
        return DeliveryNote(**fields)


@dataclass
class ProForma(_PricedDocument):
    """Una fattura pro forma: una richiesta di pagamento che non è una fattura.

    ``document_type`` is what the real invoice will be (TD01, or TD06 for a
    professional's *parcella*). ``causale`` goes onto that invoice.
    """

    document_type: DocumentType = DocumentType.INVOICE
    causale: str | None = None

    kind: ClassVar[DocumentKind] = DocumentKind.PROFORMA

    def validate(self) -> None:
        self._validate_common("Pro forma")
        if self.document_type.corrects_an_earlier_document:
            raise ValidationError(
                "Pro forma: una nota di credito o di debito non ha una pro forma")


# ── delivery note ────────────────────────────────────────────────────────


@dataclass
class DeliveryLine:
    """A line of a DDT. The price is optional: a DDT describes goods, and one
    that also carries prices (*DDT valorizzato*) can be invoiced as it is."""

    description: str
    quantity: Decimal
    unit_of_measure: str | None = None
    article_code: str | None = None
    unit_price: Decimal | None = None        # NET, like LineItem.unit_price
    vat_rate: Decimal | None = None
    nature: VatNature | None = None
    discounts: list[AllowanceCharge] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.quantity = D(self.quantity)
        if self.unit_price is not None:
            self.unit_price = D(self.unit_price)
        if self.vat_rate is not None:
            self.vat_rate = D(self.vat_rate)

    @property
    def priced(self) -> bool:
        return self.unit_price is not None and self.vat_rate is not None

    @property
    def total(self) -> Decimal | None:
        """Line total net of discounts, when the line is priced."""
        if self.unit_price is None:
            return None
        adj = sum((d.signed for d in self.discounts), Decimal("0"))
        return q2(self.unit_price * self.quantity + adj)


@dataclass
class DeliveryNote:
    """Il documento di trasporto (DDT), DPR 472/1996.

    What the law asks it to carry — and what :meth:`validate` insists on — is a
    number and a date, who sells and who receives, what the goods are and how
    many; who carries them when it is a third party. The rest of
    :class:`~einvoice.models.TransportDetails` is what every printed DDT has
    anyway: reason, packages, weight, appearance, freight terms.

    On an Italian seller the number is also checked against FatturaPA, because
    the deferred invoice will write it into ``DatiDDT/NumeroDDT`` — a DDT
    numbered in a way the invoice cannot cite is found out a month too late.
    """

    number: str
    date: date
    seller: Party                     # cedente (mittente)
    buyer: Party                      # cessionario (destinatario)
    lines: list[DeliveryLine]
    transport: TransportDetails = field(default_factory=TransportDetails)
    currency: str = "EUR"
    notes: str | None = None
    #: The customer's order, a contract — carried onto the deferred invoice.
    references: list[DocumentReference] = field(default_factory=list)

    kind: ClassVar[DocumentKind] = DocumentKind.DELIVERY_NOTE

    def validate(self) -> None:
        _require_number(self.number, "DDT")
        if self.seller.country_code == "IT" and (
                len(self.number) > 20 or not all(" " <= ch <= "~" for ch in self.number)):
            raise ValidationError(
                f"DDT '{self.number}': al massimo 20 caratteri ASCII — è il valore "
                "che la fattura differita scriverà in DatiDDT/NumeroDDT")
        self.seller.validate(role="DDT: cedente")
        _require_name(self.buyer, "DDT: cessionario")
        if self.buyer.address is None and self.transport.delivery_address is None:
            raise ValidationError("DDT: manca l'indirizzo del cessionario o del luogo di destinazione")
        _require_lines(self.lines, "DDT")
        for i, ln in enumerate(self.lines, start=1):
            if not (ln.description or "").strip():
                raise ValidationError(f"DDT, riga {i}: descrizione dei beni mancante")
            if ln.quantity <= 0:
                raise ValidationError(
                    f"DDT, riga {i}: quantità {ln.quantity} non valida — un reso è un "
                    "DDT con causale «reso», non una quantità negativa")
            if (ln.unit_price is None) != (ln.vat_rate is None):
                raise ValidationError(
                    f"DDT, riga {i}: prezzo e aliquota si indicano insieme (o nessuno dei due)")
        self.transport.validate()

    def check(self) -> list[Advisory]:
        """Non-fatal findings. Never raises."""
        out: list[Advisory] = []
        start = self.transport.start
        if start is not None and start.date() < self.date:
            out.append(Advisory(
                "delivery_note_after_start",
                f"Trasporto iniziato il {start:%d/%m/%Y}, prima della data del DDT "
                f"({self.date:%d/%m/%Y}): il DDT va emesso prima dell'inizio del "
                "trasporto o della consegna (DPR 472/1996).",
            ))
        if not (self.buyer.vat_number or self.buyer.tax_code):
            out.append(Advisory(
                "delivery_note_buyer_id",
                "Cessionario senza partita IVA né codice fiscale: le generalità "
                "del cessionario sul DDT ne comprendono di norma uno.",
            ))
        carrier = self.transport.carrier
        if self.transport.by is TransportBy.CARRIER and carrier is not None \
                and not carrier.vat_number:
            out.append(Advisory(
                "carrier_no_vat",
                f"Vettore '{carrier.name}' senza partita IVA: un'impresa di "
                "trasporto la indica sempre.",
            ))
        return out

    @property
    def priced(self) -> bool:
        return all(ln.priced for ln in self.lines)

    def to_invoice(self, *, number: str, date: _dt.date, **kwargs: Any) -> Invoice:
        """This DDT alone as a deferred invoice. See :func:`deferred_invoice`."""
        return deferred_invoice([self], number=number, date=date, **kwargs)


Pricing = Callable[[DeliveryLine], tuple]


def _party_key(party: Party) -> tuple[str, str]:
    ident = party.normalized_vat() or (party.tax_code or "").upper() or party.display_name()
    return party.country_code, ident


def deferred_invoice(notes: Sequence[DeliveryNote], *, number: str, date: date,
                     pricing: Pricing | None = None,
                     document_type: DocumentType = DocumentType.DEFERRED_INVOICE,
                     **overrides: Any) -> Invoice:
    """One invoice for the deliveries documented by ``notes`` (TD24).

    Art. 21 c.4 lett. a) DPR 633/72 lets the deliveries of a calendar month to
    one customer, each with its DDT, be billed by a single invoice issued by the
    15th of the following month. The invoice:

    * lists every DDT line, in DDT date order, and cites each DDT in
      ``DatiDDT`` with its number, date and — when there is more than one — the
      invoice lines it covers (``RiferimentoNumeroLinea``);
    * carries the DDTs' own references (the customer's order) along;
    * is refused when the DDTs belong to different sellers or buyers, or when
      one appears twice. Mixing months or missing the deadline is left to
      :meth:`Invoice.check` (``deferred_mixed_months``, ``deferred_late``):
      they are mistakes, but the law has exceptions and the invoice may still
      have to be issued.

    A line without a price needs ``pricing``: a callable that receives the
    :class:`DeliveryLine` and returns ``(unit_price, vat_rate)`` or
    ``(unit_price, vat_rate, nature)``. Without it, the unpriced lines are named
    in the error.
    """
    if not notes:
        raise ValidationError("Fattura differita: serve almeno un DDT")
    first = notes[0]
    if len({_party_key(n.seller) for n in notes}) > 1:
        raise ValidationError("Fattura differita: i DDT hanno cedenti diversi")
    if len({_party_key(n.buyer) for n in notes}) > 1:
        raise ValidationError(
            "Fattura differita: i DDT sono intestati a cessionari diversi — la "
            "fattura differita riguarda le consegne a UN cliente")
    if len({n.currency for n in notes}) > 1:
        raise ValidationError("Fattura differita: i DDT sono in valute diverse")
    keys = [(n.number, n.date) for n in notes]
    if len(set(keys)) != len(keys):
        raise ValidationError("Fattura differita: lo stesso DDT compare due volte")

    ordered = sorted(notes, key=lambda n: (n.date, n.number))
    lines: list[LineItem] = []
    references: list[DocumentReference] = []
    unpriced: list[str] = []
    for note in ordered:
        start = len(lines) + 1
        for dl in note.lines:
            if dl.priced:
                price, rate, nature = dl.unit_price, dl.vat_rate, dl.nature
            elif pricing is not None:
                resolved = tuple(pricing(dl))
                price, rate = resolved[0], resolved[1]
                nature = resolved[2] if len(resolved) > 2 else None
            else:
                unpriced.append(f"DDT {note.number}: {dl.description}")
                continue
            lines.append(LineItem(
                description=dl.description, quantity=dl.quantity,
                unit_price=D(price), vat_rate=D(rate),
                unit_of_measure=dl.unit_of_measure, nature=nature,
                discounts=copy.deepcopy(dl.discounts), article_code=dl.article_code,
            ))
        covered = list(range(start, len(lines) + 1)) if len(ordered) > 1 else []
        references.append(DocumentReference("ddt", note.number, note.date, covered))
    if unpriced:
        raise ValidationError(
            "Fattura differita: righe senza prezzo — " + "; ".join(unpriced[:10])
            + (" …" if len(unpriced) > 10 else "")
            + ". Indicare prezzo e aliquota sul DDT oppure passare pricing=")
    seen = {("ddt", r.doc_id) for r in references}
    for note in ordered:
        for ref in note.references:
            if (ref.kind, ref.doc_id) not in seen and ref.kind != "ddt":
                seen.add((ref.kind, ref.doc_id))
                references.append(DocumentReference(ref.kind, ref.doc_id, ref.date))

    fields: dict[str, Any] = {
        "number": number, "date": date,
        "seller": copy.deepcopy(first.seller), "buyer": copy.deepcopy(first.buyer),
        "lines": lines, "document_type": document_type, "currency": first.currency,
        "references": references,
    }
    fields.update(overrides)
    return Invoice(**fields)


# ── credit note ──────────────────────────────────────────────────────────


def _allocate_cents(amount: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split ``amount`` in proportion to ``weights``, to the cent, exactly.

    Largest remainder: floor every share, then hand out the leftover cents to
    the largest fractions. The shares always add up to ``amount`` — rounding
    each share on its own does not, and the missing cent is how a credit note
    stops matching the refund it documents.
    """
    total = sum(weights, Decimal("0"))
    raw = [amount * w / total for w in weights]
    floors = [r.quantize(CENTS, rounding=ROUND_FLOOR) for r in raw]
    leftover = int(((amount - sum(floors, Decimal("0"))) / CENTS).to_integral_value())
    order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
    for i in order[:leftover]:
        floors[i] += CENTS
    return floors


def _net_for_gross(gross: Decimal, rate: Decimal) -> Decimal:
    """The net amount whose VAT, computed the way ``vat_summary`` does, adds
    back up to ``gross`` — or the closest one when no net amount does (at 22%
    some gross amounts are unreachable to the cent)."""
    start = q2(gross / (Decimal("1") + rate / Decimal("100")))
    best, best_gap = start, None
    for step in (0, 1, -1, 2, -2):
        net = start + CENTS * step
        gap = abs(net + q2(net * rate / Decimal("100")) - gross)
        if best_gap is None or gap < best_gap:
            best, best_gap = net, gap
        if gap == 0:
            break
    return best


def credit_note_for(invoice: Invoice, *, number: str, date: date,
                    amount: Decimal | None = None,
                    lines: Mapping[int, Decimal] | None = None,
                    reason: str | None = None,
                    document_type: DocumentType = DocumentType.CREDIT_NOTE) -> Invoice:
    """A credit note (TD04) for ``invoice`` — whole, by lines, or by amount.

    * **Whole** (no ``amount``, no ``lines``): the invoice's lines, document
      discounts, cassa and ritenuta, mirrored. The VAT summary of the note is
      the invoice's own.
    * **By lines** — ``lines={index: quantity}`` with 0-based indexes: the goods
      that came back. Line discounts are scaled to the credited quantity.
    * **By amount** — ``amount`` is the gross sum to give back. It is split
      across the invoice's VAT rates in proportion to what each rate weighs in
      the invoice, one line per rate. Crediting everything at a single
      rate is the mistake this exists to prevent: on a bill of food at 10% and
      wine at 22%, it moves VAT from one rate to the other on the return.

    Amounts on the note are positive — the type makes it a credit — and the note
    cites the invoice (``DatiFattureCollegate``), dated not before it. Its
    :meth:`~Invoice.total_document` is the figure to store: at some rates a
    gross amount has no exact net-plus-VAT decomposition, and the note says
    what it can say to the cent. The bollo is not copied: it was due on the
    invoice and is not refunded by the note.
    """
    if invoice.document_type.corrects_an_earlier_document:
        raise ValidationError(
            "Si storna una fattura, non una nota di credito o di debito: per "
            "annullare una nota di credito si emette una nuova fattura")
    if not document_type.is_credit_note:
        raise ValidationError(f"{document_type.value} non è un tipo di nota di credito")
    if amount is not None and lines is not None:
        raise ValidationError("Nota di credito: indicare l'importo OPPURE le righe, non entrambi")

    from .i18n import locale_for_country, translate

    locale = locale_for_country(invoice.seller.country_code)
    causale = (reason or "").strip() or translate(
        "doc.credit_note_causale", locale, number=invoice.number,
        date=f"{invoice.date:%d/%m/%Y}")
    base: dict[str, Any] = {
        "number": number, "date": date,
        "seller": copy.deepcopy(invoice.seller), "buyer": copy.deepcopy(invoice.buyer),
        "document_type": document_type, "currency": invoice.currency,
        "transmission_format": invoice.transmission_format,
        "recipient_code": invoice.recipient_code, "recipient_pec": invoice.recipient_pec,
        "split_payment": invoice.split_payment, "exigibility": invoice.exigibility,
        "buyer_reference": invoice.buyer_reference, "causale": causale,
        "references": [DocumentReference("invoice", invoice.number, invoice.date)],
    }

    if lines is not None:
        if not lines:
            raise ValidationError("Nota di credito: nessuna riga indicata")
        credited: list[LineItem] = []
        for index, qty in sorted(lines.items()):
            if not 0 <= index < len(invoice.lines):
                raise ValidationError(f"Nota di credito: la riga {index + 1} non esiste")
            original = invoice.lines[index]
            quantity = D(qty)
            if original.quantity <= 0:
                raise ValidationError(
                    f"Nota di credito: la riga {index + 1} ('{original.description}') "
                    "è già una riga di reso")
            if not Decimal("0") < quantity <= original.quantity:
                raise ValidationError(
                    f"Nota di credito: quantità {quantity} per la riga {index + 1} "
                    f"fuori da (0, {original.quantity}]")
            line = copy.deepcopy(original)
            line.quantity = quantity
            ratio = quantity / original.quantity
            for d in line.discounts:
                d.amount = q2(d.amount * ratio)
            credited.append(line)
        return Invoice(lines=credited, **base)

    if amount is None:
        return Invoice(
            lines=copy.deepcopy(invoice.lines),
            allowances_charges=copy.deepcopy(invoice.allowances_charges),
            funds=copy.deepcopy(invoice.funds),
            withholdings=copy.deepcopy(invoice.withholdings),
            **base,
        )

    gross = D(amount)
    if invoice.withholdings or invoice.funds:
        raise ValidationError(
            "Storno parziale per importo di una fattura con ritenuta o cassa "
            "previdenziale: l'importo da solo non dice come ripartirle — indicare "
            "le righe da stornare (lines=)")
    summary = [s for s in invoice.vat_summary() if s.taxable + s.tax != 0]
    weights = [s.taxable + s.tax for s in summary]
    if any(w < 0 for w in weights):
        raise ValidationError(
            "Nota di credito: la fattura ha un riepilogo IVA negativo — indicare "
            "le righe da stornare (lines=)")
    ceiling = sum(weights, Decimal("0"))
    if gross <= 0:
        raise ValidationError("Nota di credito: l'importo deve essere positivo")
    if gross > ceiling:
        raise ValidationError(
            f"Nota di credito: {gross} supera il totale IVA inclusa della fattura ({ceiling})")
    shares = _allocate_cents(gross, weights)
    note_lines = []
    for bucket, share in zip(summary, shares, strict=True):
        if share <= 0:
            continue
        rate = f"{bucket.vat_rate.normalize():f}"
        label = causale if len(summary) == 1 else f"{causale} — {rate}%"
        note_lines.append(LineItem(
            description=label, quantity=Decimal("1"),
            unit_price=_net_for_gross(share, bucket.vat_rate), vat_rate=bucket.vat_rate,
            nature=bucket.nature, exemption_reason=bucket.exemption_reason if bucket.nature else None,
        ))
    return Invoice(lines=note_lines, **base)


# ── status ───────────────────────────────────────────────────────────────

S = DocumentStatus
_TRANSITIONS: dict[DocumentKind, dict[DocumentStatus, frozenset[DocumentStatus]]] = {
    DocumentKind.QUOTE: {
        S.DRAFT: frozenset({S.SENT, S.ACCEPTED, S.REJECTED, S.CONVERTED, S.CANCELLED}),
        S.SENT: frozenset({S.DRAFT, S.ACCEPTED, S.REJECTED, S.EXPIRED, S.CONVERTED, S.CANCELLED}),
        S.ACCEPTED: frozenset({S.CONVERTED, S.CANCELLED}),
        S.EXPIRED: frozenset({S.SENT, S.CANCELLED}),
        S.REJECTED: frozenset(),
        S.CONVERTED: frozenset(),
        S.CANCELLED: frozenset(),
    },
    DocumentKind.PROFORMA: {
        S.ISSUED: frozenset({S.CONVERTED, S.CANCELLED}),
        S.CONVERTED: frozenset(),
        S.CANCELLED: frozenset(),
    },
    DocumentKind.DELIVERY_NOTE: {
        S.ISSUED: frozenset({S.INVOICED, S.CANCELLED}),
        S.INVOICED: frozenset(),
        S.CANCELLED: frozenset(),
    },
}
del S


def _kind(kind: DocumentKind | str) -> DocumentKind:
    return kind if isinstance(kind, DocumentKind) else DocumentKind(kind)


def _status(status: DocumentStatus | str) -> DocumentStatus:
    return status if isinstance(status, DocumentStatus) else DocumentStatus(status)


def initial_status(kind: DocumentKind | str) -> DocumentStatus:
    """The status a new commercial document starts in.

    A quote starts as a draft (it can still change); a pro forma and a DDT are
    issued the moment they exist — a DDT that travelled with goods cannot go
    back to being a draft.
    """
    kind = _kind(kind)
    if kind.is_fiscal:
        raise ValueError(f"{kind.value}: lo stato di un documento fiscale lo dà SdI")
    return DocumentStatus.DRAFT if kind is DocumentKind.QUOTE else DocumentStatus.ISSUED


def next_statuses(kind: DocumentKind | str, current: DocumentStatus | str) -> frozenset[DocumentStatus]:
    """Where a document of ``kind`` can go from ``current``. Empty = final."""
    table = _TRANSITIONS.get(_kind(kind), {})
    return table.get(_status(current), frozenset())


def can_transition(kind: DocumentKind | str, current: DocumentStatus | str,
                   target: DocumentStatus | str) -> bool:
    return _status(target) in next_statuses(kind, current)


def transition(kind: DocumentKind | str, current: DocumentStatus | str,
               target: DocumentStatus | str) -> DocumentStatus:
    """``target``, or :class:`~einvoice.errors.IllegalTransition` saying why not."""
    if not can_transition(kind, current, target):
        allowed = ", ".join(sorted(s.value for s in next_statuses(kind, current))) or "nessuno"
        raise IllegalTransition(
            f"{_kind(kind).value}: da '{_status(current).value}' non si passa a "
            f"'{_status(target).value}' (ammessi: {allowed})")
    return _status(target)


def document_kind(document: object) -> DocumentKind:
    """The :class:`DocumentKind` of any document this package models."""
    if isinstance(document, Invoice):
        return (DocumentKind.CREDIT_NOTE if document.document_type.is_credit_note
                else DocumentKind.INVOICE)
    kind = getattr(document, "kind", None)
    if isinstance(kind, DocumentKind):
        return kind
    raise TypeError(f"{type(document).__name__} non è un documento di einvoice")
