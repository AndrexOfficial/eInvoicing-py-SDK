"""JSON ⇄ :class:`~einvoice.models.Invoice`.

The model is the integration boundary: a host platform maps its own tables onto
it. That mapping is much easier to build, review and regression-test when an
invoice can be written down — as a fixture, a queue payload, an audit record, or
the input to the CLI — so this module defines one portable JSON shape for it.

Design rules:

* **Field names match the dataclasses.** Nothing to look up; ``Invoice.number``
  is ``"number"``.
* **Money is a JSON string**, never a float. ``0.1 + 0.2`` is exactly the class
  of error a fiscal document must not contain, and floats round-trip lossily.
  Numbers are still accepted on input (via ``Decimal(str(...))``) so
  hand-written fixtures stay convenient.
* **Enums travel as their code** — ``"TD01"``, ``"MP05"``, ``"N2.2"`` — which is
  what the standards themselves use.
* **Omitted optional fields keep their dataclass default**, so the smallest
  valid invoice is genuinely small.

``to_dict`` → ``from_dict`` is lossless for everything the renderers read;
``Attachment.content`` is base64-encoded on the way out.
"""
from __future__ import annotations

import base64
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .documents import DeliveryLine, DeliveryNote, ProForma, Quote, document_kind
from .enums import (
    DocumentKind,
    DocumentType,
    Freight,
    PaymentMeans,
    TransmissionFormat,
    TransportBy,
    TransportReason,
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
    Carrier,
    DocumentReference,
    Invoice,
    LineItem,
    Party,
    Payment,
    SocialSecurityFund,
    TransportDetails,
    WithholdingTax,
)
from .rates import ProductCategory

__all__ = [
    "invoice_to_dict", "invoice_from_dict", "invoice_to_json", "invoice_from_json",
    "document_to_dict", "document_from_dict", "document_to_json", "document_from_json",
]

#: Any document :func:`document_to_dict` knows how to write.
Document = Invoice | Quote | ProForma | DeliveryNote


# ────────────────────────────────────────────────────────────── decode ──


def _dec(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field}: importo non valido ({value!r})") from exc


def _opt_dec(value: Any, field: str) -> Decimal | None:
    return None if value is None else _dec(value, field)


def _date(value: Any, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field}: data non valida ({value!r}), attesa YYYY-MM-DD") from exc


def _opt_date(value: Any, field: str) -> date | None:
    return None if value in (None, "") else _date(value, field)


def _enum(enum_cls, value: Any, field: str):
    if value in (None, ""):
        return None
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except ValueError as exc:
        allowed = ", ".join(m.value for m in enum_cls)
        raise ValidationError(f"{field}: {value!r} non valido. Ammessi: {allowed}") from exc


def _require(data: dict, key: str, context: str) -> Any:
    if key not in data:
        raise ValidationError(f"{context}: campo obbligatorio '{key}' mancante")
    return data[key]


def _address(data: Any, context: str) -> Address | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValidationError(f"{context}.address: atteso un oggetto")
    return Address(
        street=_require(data, "street", f"{context}.address"),
        postcode=str(_require(data, "postcode", f"{context}.address")),
        city=_require(data, "city", f"{context}.address"),
        province=data.get("province"),
        country=data.get("country", "IT"),
    )


def _party(data: Any, role: str) -> Party:
    if not isinstance(data, dict):
        raise ValidationError(f"{role}: atteso un oggetto")
    known = {f for f in Party.__dataclass_fields__ if f != "address"}
    return Party(
        address=_address(data.get("address"), role),
        **{k: v for k, v in data.items() if k in known},
    )


def _allowance(data: dict, context: str) -> AllowanceCharge:
    return AllowanceCharge(
        amount=_dec(_require(data, "amount", context), f"{context}.amount"),
        is_charge=bool(data.get("is_charge", False)),
        vat_rate=_opt_dec(data.get("vat_rate"), f"{context}.vat_rate"),
        reason=data.get("reason"),
    )


def _line(data: dict, index: int) -> LineItem:
    context = f"lines[{index}]"
    gross = data.get("gross_unit_price")
    if gross is not None and "unit_price" in data:
        raise ValidationError(f"{context}: indicare 'unit_price' (netto) OPPURE 'gross_unit_price', non entrambi")
    if gross is not None:
        # POS/consumer pricing: VAT-included, de-grossed exactly as the model does.
        line = LineItem.from_gross(
            description=_require(data, "description", context),
            quantity=_dec(_require(data, "quantity", context), f"{context}.quantity"),
            gross_unit_price=_dec(gross, f"{context}.gross_unit_price"),
            vat_rate=_dec(_require(data, "vat_rate", context), f"{context}.vat_rate"),
            unit_of_measure=data.get("unit_of_measure"),
            nature=_enum(VatNature, data.get("nature"), f"{context}.nature"),
        )
    else:
        line = LineItem(
            description=_require(data, "description", context),
            quantity=_dec(_require(data, "quantity", context), f"{context}.quantity"),
            unit_price=_dec(_require(data, "unit_price", context), f"{context}.unit_price"),
            vat_rate=_dec(_require(data, "vat_rate", context), f"{context}.vat_rate"),
            unit_of_measure=data.get("unit_of_measure"),
            nature=_enum(VatNature, data.get("nature"), f"{context}.nature"),
        )
    line.discounts = [_allowance(d, f"{context}.discounts[{i}]")
                      for i, d in enumerate(data.get("discounts", []))]
    line.article_code = data.get("article_code")
    line.article_code_type = data.get("article_code_type", "INTERNO")
    line.period_start = _opt_date(data.get("period_start"), f"{context}.period_start")
    line.period_end = _opt_date(data.get("period_end"), f"{context}.period_end")
    line.exemption_reason = data.get("exemption_reason")
    line.category = _enum(ProductCategory, data.get("category"), f"{context}.category")
    return line


def _payment(data: dict, index: int) -> Payment:
    context = f"payments[{index}]"
    account = data.get("account")
    return Payment(
        means=_enum(PaymentMeans, data.get("means"), f"{context}.means") or PaymentMeans.BANK_TRANSFER,
        amount=_opt_dec(data.get("amount"), f"{context}.amount"),
        due_date=_opt_date(data.get("due_date"), f"{context}.due_date"),
        account=BankAccount(
            iban=_require(account, "iban", f"{context}.account"),
            bank_name=account.get("bank_name"),
            holder=account.get("holder"),
            bic=account.get("bic"),
        ) if isinstance(account, dict) else None,
        condition=data.get("condition", "TP02"),
    )


def _opt_datetime(value: Any, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field}: data e ora non valide ({value!r}), attese in ISO 8601") from exc


def _carrier(data: Any, context: str) -> Carrier | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValidationError(f"{context}: atteso un oggetto")
    return Carrier(
        name=_require(data, "name", context),
        vat_number=data.get("vat_number"),
        country_code=data.get("country_code", "IT"),
        tax_code=data.get("tax_code"),
        address=_address(data.get("address"), context),
        license_number=data.get("license_number"),
    )


def _transport(data: Any, context: str = "transport") -> TransportDetails | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValidationError(f"{context}: atteso un oggetto")
    packages = data.get("packages")
    return TransportDetails(
        reason=_enum(TransportReason, data.get("reason"), f"{context}.reason") or TransportReason.SALE,
        reason_text=data.get("reason_text"),
        by=_enum(TransportBy, data.get("by"), f"{context}.by") or TransportBy.SENDER,
        carrier=_carrier(data.get("carrier"), f"{context}.carrier"),
        means=data.get("means"),
        packages=int(packages) if packages not in (None, "") else None,
        goods_appearance=data.get("goods_appearance"),
        gross_weight=_opt_dec(data.get("gross_weight"), f"{context}.gross_weight"),
        net_weight=_opt_dec(data.get("net_weight"), f"{context}.net_weight"),
        weight_unit=data.get("weight_unit", "kg"),
        start=_opt_datetime(data.get("start"), f"{context}.start"),
        freight=_enum(Freight, data.get("freight"), f"{context}.freight"),
        incoterm=data.get("incoterm"),
        delivery_address=_address(data.get("delivery_address"), f"{context}.delivery_address"),
    )


def _references(data: dict) -> list[DocumentReference]:
    return [
        DocumentReference(
            kind=_require(r, "kind", f"references[{i}]"),
            doc_id=str(_require(r, "doc_id", f"references[{i}]")),
            date=_opt_date(r.get("date"), f"references[{i}].date"),
            line_numbers=list(r.get("line_numbers", [])),
        )
        for i, r in enumerate(data.get("references", []))
    ]


def _withholdings(data: dict) -> list[WithholdingTax]:
    return [
        WithholdingTax(
            amount=_dec(_require(w, "amount", f"withholdings[{i}]"), f"withholdings[{i}].amount"),
            rate=_dec(_require(w, "rate", f"withholdings[{i}]"), f"withholdings[{i}].rate"),
            kind=_enum(WithholdingType, w.get("kind"), f"withholdings[{i}].kind")
            or WithholdingType.NATURAL_PERSON,
            reason=w.get("reason", "A"),
        )
        for i, w in enumerate(data.get("withholdings", []))
    ]


def _funds(data: dict) -> list[SocialSecurityFund]:
    return [
        SocialSecurityFund(
            kind=_require(f, "kind", f"funds[{i}]"),
            rate=_dec(_require(f, "rate", f"funds[{i}]"), f"funds[{i}].rate"),
            amount=_dec(_require(f, "amount", f"funds[{i}]"), f"funds[{i}].amount"),
            taxable=_opt_dec(f.get("taxable"), f"funds[{i}].taxable"),
            vat_rate=_dec(f.get("vat_rate", 0), f"funds[{i}].vat_rate"),
            nature=_enum(VatNature, f.get("nature"), f"funds[{i}].nature"),
            withheld=bool(f.get("withheld", False)),
        )
        for i, f in enumerate(data.get("funds", []))
    ]


def invoice_from_dict(data: dict) -> Invoice:
    """Build an :class:`Invoice` from the JSON shape. Raises
    :class:`~einvoice.errors.ValidationError` with the offending path."""
    if not isinstance(data, dict):
        raise ValidationError("Atteso un oggetto JSON alla radice")

    invoice = Invoice(
        number=str(_require(data, "number", "invoice")),
        date=_date(_require(data, "date", "invoice"), "invoice.date"),
        seller=_party(_require(data, "seller", "invoice"), "seller"),
        buyer=_party(_require(data, "buyer", "invoice"), "buyer"),
        lines=[_line(ln, i) for i, ln in enumerate(_require(data, "lines", "invoice"))],
        document_type=_enum(DocumentType, data.get("document_type"), "document_type") or DocumentType.INVOICE,
        currency=data.get("currency", "EUR"),
        transmission_format=(
            _enum(TransmissionFormat, data.get("transmission_format"), "transmission_format")
            or TransmissionFormat.PRIVATE
        ),
        causale=data.get("causale"),
        payments=[_payment(p, i) for i, p in enumerate(data.get("payments", []))],
        recipient_code=data.get("recipient_code"),
        recipient_pec=data.get("recipient_pec"),
        allowances_charges=[_allowance(a, f"allowances_charges[{i}]")
                            for i, a in enumerate(data.get("allowances_charges", []))],
        withholdings=_withholdings(data),
        references=_references(data),
        attachments=[
            Attachment(
                filename=_require(a, "filename", f"attachments[{i}]"),
                content=base64.b64decode(_require(a, "content_base64", f"attachments[{i}]")),
                mime=a.get("mime", "application/octet-stream"),
                description=a.get("description"),
            )
            for i, a in enumerate(data.get("attachments", []))
        ],
        stamp_duty=_opt_dec(data.get("stamp_duty"), "stamp_duty"),
        split_payment=bool(data.get("split_payment", False)),
        buyer_reference=data.get("buyer_reference"),
        exigibility=_enum(VatExigibility, data.get("exigibility"), "exigibility"),
        funds=_funds(data),
        art73=bool(data.get("art73", False)),
        rounding=_opt_dec(data.get("rounding"), "rounding"),
        payment_terms_note=data.get("payment_terms_note"),
        transport=_transport(data.get("transport")),
    )
    return invoice


def invoice_from_json(raw: str | bytes) -> Invoice:
    try:
        return invoice_from_dict(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"JSON non valido: {exc}") from exc


# ────────────────────────────────────────────────────────────── encode ──


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _prune(data: dict) -> dict:
    """Drop empty optionals so the output stays as small as the input was."""
    return {k: v for k, v in data.items() if v not in (None, [], {})}


def _address_to_dict(address: Address | None) -> dict | None:
    if address is None:
        return None
    return _prune({
        "street": address.street, "postcode": address.postcode, "city": address.city,
        "province": address.province, "country": address.country,
    })


def _party_to_dict(party: Party) -> dict:
    out = {f: getattr(party, f) for f in Party.__dataclass_fields__ if f != "address"}
    out["address"] = _address_to_dict(party.address)
    # tax_regime defaults to RF01 for every party but only means anything on the
    # seller; keeping it on the buyer would imply a claim the model never makes.
    return _prune(out)


def _allowance_to_dict(ac: AllowanceCharge) -> dict:
    return _prune({
        "amount": _money(ac.amount), "is_charge": ac.is_charge or None,
        "vat_rate": _money(ac.vat_rate), "reason": ac.reason,
    })


def _line_to_dict(line: LineItem) -> dict:
    return _prune({
        "description": line.description,
        "quantity": _money(line.quantity),
        "unit_price": _money(line.unit_price),
        "vat_rate": _money(line.vat_rate),
        "unit_of_measure": line.unit_of_measure,
        "nature": line.nature.value if line.nature else None,
        "discounts": [_allowance_to_dict(d) for d in line.discounts],
        "article_code": line.article_code,
        "article_code_type": line.article_code_type if line.article_code else None,
        "period_start": line.period_start.isoformat() if line.period_start else None,
        "period_end": line.period_end.isoformat() if line.period_end else None,
        "exemption_reason": line.exemption_reason,
        "category": line.category.value if line.category else None,
    })


def _carrier_to_dict(carrier: Carrier | None) -> dict | None:
    if carrier is None:
        return None
    return _prune({
        "name": carrier.name, "vat_number": carrier.vat_number,
        "country_code": carrier.country_code, "tax_code": carrier.tax_code,
        "address": _address_to_dict(carrier.address),
        "license_number": carrier.license_number,
    })


def _transport_to_dict(t: TransportDetails | None) -> dict | None:
    if t is None:
        return None
    return _prune({
        "reason": t.reason.value, "reason_text": t.reason_text, "by": t.by.value,
        "carrier": _carrier_to_dict(t.carrier), "means": t.means, "packages": t.packages,
        "goods_appearance": t.goods_appearance,
        "gross_weight": _money(t.gross_weight), "net_weight": _money(t.net_weight),
        "weight_unit": t.weight_unit,
        "start": t.start.isoformat() if t.start else None,
        "freight": t.freight.value if t.freight else None, "incoterm": t.incoterm,
        "delivery_address": _address_to_dict(t.delivery_address),
    })


def _references_to_list(refs: list[DocumentReference]) -> list[dict]:
    return [
        _prune({"kind": r.kind, "doc_id": r.doc_id,
                "date": r.date.isoformat() if r.date else None,
                "line_numbers": list(r.line_numbers)})
        for r in refs
    ]


def _payments_to_list(payments: list[Payment]) -> list[dict]:
    return [
        _prune({
            "means": p.means.value,
            "amount": _money(p.amount),
            "due_date": p.due_date.isoformat() if p.due_date else None,
            "condition": p.condition,
            "account": _prune({
                "iban": p.account.iban, "bank_name": p.account.bank_name,
                "holder": p.account.holder, "bic": p.account.bic,
            }) if p.account else None,
        })
        for p in payments
    ]


def _withholdings_to_list(items: list[WithholdingTax]) -> list[dict]:
    return [{"amount": _money(w.amount), "rate": _money(w.rate),
             "kind": w.kind.value, "reason": w.reason} for w in items]


def _funds_to_list(items: list[SocialSecurityFund]) -> list[dict]:
    return [
        _prune({"kind": f.kind, "rate": _money(f.rate), "amount": _money(f.amount),
                "taxable": _money(f.taxable), "vat_rate": _money(f.vat_rate),
                "nature": f.nature.value if f.nature else None,
                "withheld": f.withheld or None})
        for f in items
    ]


def invoice_to_dict(invoice: Invoice) -> dict:
    """Serialize to the JSON shape :func:`invoice_from_dict` reads back."""
    return _prune({
        "number": invoice.number,
        "date": invoice.date.isoformat(),
        "document_type": invoice.document_type.value,
        "currency": invoice.currency,
        "transmission_format": invoice.transmission_format.value,
        "causale": invoice.causale,
        "seller": _party_to_dict(invoice.seller),
        "buyer": _party_to_dict(invoice.buyer),
        "lines": [_line_to_dict(ln) for ln in invoice.lines],
        "payments": _payments_to_list(invoice.payments),
        "recipient_code": invoice.recipient_code,
        "recipient_pec": invoice.recipient_pec,
        "allowances_charges": [_allowance_to_dict(a) for a in invoice.allowances_charges],
        "withholdings": _withholdings_to_list(invoice.withholdings),
        "references": _references_to_list(invoice.references),
        "attachments": [
            _prune({"filename": a.filename,
                    "content_base64": base64.b64encode(a.content).decode("ascii"),
                    "mime": a.mime, "description": a.description})
            for a in invoice.attachments
        ],
        "stamp_duty": _money(invoice.stamp_duty),
        "split_payment": invoice.split_payment or None,
        "buyer_reference": invoice.buyer_reference,
        "exigibility": invoice.exigibility.value if invoice.exigibility else None,
        "funds": _funds_to_list(invoice.funds),
        "art73": invoice.art73 or None,
        "rounding": _money(invoice.rounding),
        "payment_terms_note": invoice.payment_terms_note,
        "transport": _transport_to_dict(invoice.transport),
    })


def invoice_to_json(invoice: Invoice, *, indent: int | None = 2) -> str:
    return json.dumps(invoice_to_dict(invoice), indent=indent, ensure_ascii=False)


# ─────────────────────────────────────────────── commercial documents ──
#
# The same rules as the invoice shape, plus a ``"kind"`` discriminator: a host
# that stores documents of five kinds in one table reads them back with one
# call. Invoices keep their own shape — ``document_to_dict(invoice)`` is
# ``invoice_to_dict`` with the kind added.


def _priced_from_dict(data: dict, context: str) -> dict[str, Any]:
    return {
        "number": str(_require(data, "number", context)),
        "date": _date(_require(data, "date", context), f"{context}.date"),
        "seller": _party(_require(data, "seller", context), "seller"),
        "buyer": _party(_require(data, "buyer", context), "buyer"),
        "lines": [_line(ln, i) for i, ln in enumerate(_require(data, "lines", context))],
        "currency": data.get("currency", "EUR"),
        "notes": data.get("notes"),
        "payments": [_payment(p, i) for i, p in enumerate(data.get("payments", []))],
        "payment_terms_note": data.get("payment_terms_note"),
        "allowances_charges": [_allowance(a, f"allowances_charges[{i}]")
                               for i, a in enumerate(data.get("allowances_charges", []))],
        "withholdings": _withholdings(data),
        "funds": _funds(data),
        "stamp_duty": _opt_dec(data.get("stamp_duty"), "stamp_duty"),
        "rounding": _opt_dec(data.get("rounding"), "rounding"),
        "references": _references(data),
    }


def _priced_to_dict(doc: Quote | ProForma) -> dict[str, Any]:
    return {
        "number": doc.number, "date": doc.date.isoformat(), "currency": doc.currency,
        "seller": _party_to_dict(doc.seller), "buyer": _party_to_dict(doc.buyer),
        "lines": [_line_to_dict(ln) for ln in doc.lines],
        "notes": doc.notes, "payments": _payments_to_list(doc.payments),
        "payment_terms_note": doc.payment_terms_note,
        "allowances_charges": [_allowance_to_dict(a) for a in doc.allowances_charges],
        "withholdings": _withholdings_to_list(doc.withholdings),
        "funds": _funds_to_list(doc.funds),
        "stamp_duty": _money(doc.stamp_duty), "rounding": _money(doc.rounding),
        "references": _references_to_list(doc.references),
    }


def _delivery_line(data: dict, index: int) -> DeliveryLine:
    context = f"lines[{index}]"
    return DeliveryLine(
        description=_require(data, "description", context),
        quantity=_dec(_require(data, "quantity", context), f"{context}.quantity"),
        unit_of_measure=data.get("unit_of_measure"),
        article_code=data.get("article_code"),
        unit_price=_opt_dec(data.get("unit_price"), f"{context}.unit_price"),
        vat_rate=_opt_dec(data.get("vat_rate"), f"{context}.vat_rate"),
        nature=_enum(VatNature, data.get("nature"), f"{context}.nature"),
        discounts=[_allowance(d, f"{context}.discounts[{i}]")
                   for i, d in enumerate(data.get("discounts", []))],
    )


def _delivery_line_to_dict(line: DeliveryLine) -> dict:
    return _prune({
        "description": line.description, "quantity": _money(line.quantity),
        "unit_of_measure": line.unit_of_measure, "article_code": line.article_code,
        "unit_price": _money(line.unit_price), "vat_rate": _money(line.vat_rate),
        "nature": line.nature.value if line.nature else None,
        "discounts": [_allowance_to_dict(d) for d in line.discounts],
    })


def document_from_dict(data: dict) -> Document:
    """Any document from its JSON shape, chosen by ``"kind"``.

    Without a ``kind`` the object is read as an invoice, which is what every
    JSON this package wrote before 0.10.0 is.
    """
    if not isinstance(data, dict):
        raise ValidationError("Atteso un oggetto JSON alla radice")
    kind = _enum(DocumentKind, data.get("kind"), "kind")
    body = {k: v for k, v in data.items() if k != "kind"}
    if kind in (None, DocumentKind.INVOICE, DocumentKind.CREDIT_NOTE):
        invoice = invoice_from_dict(body)
        if kind is DocumentKind.CREDIT_NOTE and not invoice.document_type.is_credit_note:
            raise ValidationError(
                f"kind 'credit_note' con document_type {invoice.document_type.value}")
        return invoice
    if kind is DocumentKind.QUOTE:
        return Quote(**_priced_from_dict(body, "quote"),
                     valid_until=_opt_date(body.get("valid_until"), "valid_until"))
    if kind is DocumentKind.PROFORMA:
        return ProForma(
            **_priced_from_dict(body, "proforma"),
            document_type=_enum(DocumentType, body.get("document_type"), "document_type")
            or DocumentType.INVOICE,
            causale=body.get("causale"),
        )
    return DeliveryNote(
        number=str(_require(body, "number", "delivery_note")),
        date=_date(_require(body, "date", "delivery_note"), "delivery_note.date"),
        seller=_party(_require(body, "seller", "delivery_note"), "seller"),
        buyer=_party(_require(body, "buyer", "delivery_note"), "buyer"),
        lines=[_delivery_line(ln, i)
               for i, ln in enumerate(_require(body, "lines", "delivery_note"))],
        transport=_transport(body.get("transport")) or TransportDetails(),
        currency=body.get("currency", "EUR"),
        notes=body.get("notes"),
        references=_references(body),
    )


def document_to_dict(document: Document) -> dict:
    """Serialize any document to the shape :func:`document_from_dict` reads."""
    kind = document_kind(document)
    if isinstance(document, Invoice):
        return {"kind": kind.value, **invoice_to_dict(document)}
    if isinstance(document, Quote):
        body = {**_priced_to_dict(document),
                "valid_until": document.valid_until.isoformat() if document.valid_until else None}
    elif isinstance(document, ProForma):
        body = {**_priced_to_dict(document), "document_type": document.document_type.value,
                "causale": document.causale}
    else:
        body = {
            "number": document.number, "date": document.date.isoformat(),
            "currency": document.currency,
            "seller": _party_to_dict(document.seller), "buyer": _party_to_dict(document.buyer),
            "lines": [_delivery_line_to_dict(ln) for ln in document.lines],
            "transport": _transport_to_dict(document.transport),
            "notes": document.notes,
            "references": _references_to_list(document.references),
        }
    return {"kind": kind.value, **_prune(body)}


def document_to_json(document: Document, *, indent: int | None = 2) -> str:
    return json.dumps(document_to_dict(document), indent=indent, ensure_ascii=False)


def document_from_json(raw: str | bytes) -> Document:
    try:
        return document_from_dict(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"JSON non valido: {exc}") from exc
