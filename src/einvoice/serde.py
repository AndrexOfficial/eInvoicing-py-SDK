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
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .enums import (
    DocumentType,
    PaymentMeans,
    TransmissionFormat,
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
from .rates import ProductCategory

__all__ = ["invoice_to_dict", "invoice_from_dict", "invoice_to_json", "invoice_from_json"]


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
        withholdings=[
            WithholdingTax(
                amount=_dec(_require(w, "amount", f"withholdings[{i}]"), f"withholdings[{i}].amount"),
                rate=_dec(_require(w, "rate", f"withholdings[{i}]"), f"withholdings[{i}].rate"),
                kind=_enum(WithholdingType, w.get("kind"), f"withholdings[{i}].kind")
                or WithholdingType.NATURAL_PERSON,
                reason=w.get("reason", "A"),
            )
            for i, w in enumerate(data.get("withholdings", []))
        ],
        references=[
            DocumentReference(
                kind=_require(r, "kind", f"references[{i}]"),
                doc_id=str(_require(r, "doc_id", f"references[{i}]")),
                date=_opt_date(r.get("date"), f"references[{i}].date"),
                line_numbers=list(r.get("line_numbers", [])),
            )
            for i, r in enumerate(data.get("references", []))
        ],
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
        funds=[
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
        ],
        art73=bool(data.get("art73", False)),
        rounding=_opt_dec(data.get("rounding"), "rounding"),
        payment_terms_note=data.get("payment_terms_note"),
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
        "payments": [
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
            for p in invoice.payments
        ],
        "recipient_code": invoice.recipient_code,
        "recipient_pec": invoice.recipient_pec,
        "allowances_charges": [_allowance_to_dict(a) for a in invoice.allowances_charges],
        "withholdings": [
            {"amount": _money(w.amount), "rate": _money(w.rate),
             "kind": w.kind.value, "reason": w.reason}
            for w in invoice.withholdings
        ],
        "references": [
            _prune({"kind": r.kind, "doc_id": r.doc_id,
                    "date": r.date.isoformat() if r.date else None,
                    "line_numbers": list(r.line_numbers)})
            for r in invoice.references
        ],
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
        "funds": [
            _prune({"kind": f.kind, "rate": _money(f.rate), "amount": _money(f.amount),
                    "taxable": _money(f.taxable), "vat_rate": _money(f.vat_rate),
                    "nature": f.nature.value if f.nature else None,
                    "withheld": f.withheld or None})
            for f in invoice.funds
        ],
        "art73": invoice.art73 or None,
        "rounding": _money(invoice.rounding),
        "payment_terms_note": invoice.payment_terms_note,
    })


def invoice_to_json(invoice: Invoice, *, indent: int | None = 2) -> str:
    return json.dumps(invoice_to_dict(invoice), indent=indent, ensure_ascii=False)
