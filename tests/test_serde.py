"""JSON ⇄ Invoice round-tripping."""
import json
from datetime import date
from decimal import Decimal

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
    SocialSecurityFund,
    VatNature,
    WithholdingTax,
    invoice_from_dict,
    invoice_from_json,
    invoice_to_dict,
    invoice_to_json,
)
from einvoice.errors import ValidationError

MINIMAL = {
    "number": "2026/0001",
    "date": "2026-06-05",
    "seller": {
        "name": "Trattoria da Mario", "vat_number": "01234567897",
        "address": {"street": "Via Roma 1", "postcode": "20100", "city": "Milano", "province": "MI"},
    },
    "buyer": {
        "name": "ACME Srl", "vat_number": "09876543217",
        "address": {"street": "Via Verdi 9", "postcode": "00100", "city": "Roma", "province": "RM"},
    },
    "lines": [{"description": "Cena", "quantity": "1", "unit_price": "100.00", "vat_rate": "22"}],
}


def _rich_invoice() -> Invoice:
    """Exercises every optional block, so the round-trip test means something."""
    return Invoice(
        number="2026/0099",
        date=date(2026, 6, 5),
        seller=Party(name="Studio Rossi", vat_number="01234567897", tax_regime="RF19",
                     address=Address("Via Roma 1", "20100", "Milano", "MI")),
        buyer=Party(first_name="Anna", last_name="Bianchi", tax_code="BNCNNA80A41H501Z",
                    pec="anna@pec.it",
                    address=Address("Via Verdi 9", "00100", "Roma", "RM")),
        lines=[
            LineItem("Consulenza", Decimal("10"), Decimal("100.00"), Decimal("22"),
                     unit_of_measure="ORE", article_code="CONS-1",
                     period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
                     discounts=[AllowanceCharge(Decimal("50.00"), reason="Sconto cliente")]),
            LineItem("Rimborso spese", Decimal("1"), Decimal("80.00"), Decimal("0"),
                     nature=VatNature.EXCLUDED, exemption_reason="Art. 15 DPR 633/72"),
        ],
        document_type=DocumentType.CREDIT_NOTE,
        causale="Nota di credito",
        payments=[Payment(means=PaymentMeans.BANK_TRANSFER, amount=Decimal("500.00"),
                          due_date=date(2026, 7, 31),
                          account=BankAccount("IT60X0542811101000000123456", bank_name="Banca X"))],
        allowances_charges=[AllowanceCharge(Decimal("20.00"), is_charge=True,
                                            vat_rate=Decimal("22"), reason="Trasferta")],
        withholdings=[WithholdingTax(Decimal("200.00"), Decimal("20"), reason="A")],
        references=[DocumentReference("invoice", "2026/0001", date(2026, 1, 15), [1])],
        attachments=[Attachment("nota.pdf", b"%PDF-1.4 fake", mime="application/pdf")],
        funds=[SocialSecurityFund("TC01", Decimal("4"), Decimal("40.00"), vat_rate=Decimal("22"))],
        stamp_duty=Decimal("2.00"),
        buyer_reference="PO-77",
        art73=True,
        rounding=Decimal("0.01"),
        payment_terms_note="30 gg data fattura",
        recipient_code="0000000",
    )


# ─────────────────────────────────────────────────────────── round-trip ──


def test_rich_invoice_round_trips_losslessly():
    original = _rich_invoice()

    restored = invoice_from_dict(invoice_to_dict(original))

    assert invoice_to_dict(restored) == invoice_to_dict(original)


def test_round_trip_preserves_the_computed_totals():
    """The point of the model: the numbers must survive the trip unchanged."""
    original = _rich_invoice()

    restored = invoice_from_json(invoice_to_json(original))

    assert restored.taxable_total() == original.taxable_total()
    assert restored.tax_total() == original.tax_total()
    assert restored.total_document() == original.total_document()
    assert restored.total_payable() == original.total_payable()


def test_attachment_bytes_survive_base64():
    original = _rich_invoice()

    restored = invoice_from_dict(invoice_to_dict(original))

    assert restored.attachments[0].content == b"%PDF-1.4 fake"


def test_output_is_json_serializable():
    """Decimals must already be strings — json.dumps cannot encode Decimal."""
    json.dumps(invoice_to_dict(_rich_invoice()))


# ─────────────────────────────────────────────────────────────── decode ──


def test_minimal_invoice_needs_no_optional_fields():
    invoice = invoice_from_dict(MINIMAL)
    invoice.validate()
    assert invoice.total_document() == Decimal("122.00")


def test_money_is_exact_not_floating_point():
    """0.1 + 0.2 is exactly the error a fiscal document must not contain."""
    data = {**MINIMAL, "lines": [
        {"description": "a", "quantity": "1", "unit_price": "0.10", "vat_rate": "0"},
        {"description": "b", "quantity": "1", "unit_price": "0.20", "vat_rate": "0"},
    ]}

    invoice = invoice_from_dict(data)

    assert invoice.taxable_total() == Decimal("0.30")


def test_json_numbers_are_accepted_and_still_exact():
    """Hand-written fixtures use bare numbers; they must not become floats."""
    data = {**MINIMAL, "lines": [
        {"description": "a", "quantity": 3, "unit_price": 19.99, "vat_rate": 22},
    ]}

    invoice = invoice_from_dict(data)

    assert invoice.lines[0].unit_price == Decimal("19.99")
    assert invoice.lines[0].total == Decimal("59.97")


def test_gross_prices_are_de_grossed_like_the_model_does():
    data = {**MINIMAL, "lines": [
        {"description": "Menu", "quantity": "1", "gross_unit_price": "122.00", "vat_rate": "22"},
    ]}

    invoice = invoice_from_dict(data)

    assert invoice.total_document() == Decimal("122.00")


def test_net_and_gross_price_together_is_rejected():
    """Silently preferring one would hide a real pricing mistake."""
    data = {**MINIMAL, "lines": [
        {"description": "x", "quantity": "1", "unit_price": "100", "gross_unit_price": "122", "vat_rate": "22"},
    ]}

    with pytest.raises(ValidationError, match="OPPURE"):
        invoice_from_dict(data)


def test_enums_travel_as_their_standard_code():
    data = {**MINIMAL, "document_type": "TD04", "exigibility": "S",
            "payments": [{"means": "MP05"}]}

    invoice = invoice_from_dict(data)

    assert invoice.document_type is DocumentType.CREDIT_NOTE
    assert invoice.payments[0].means is PaymentMeans.BANK_TRANSFER
    assert invoice_to_dict(invoice)["document_type"] == "TD04"


# ───────────────────────────────────────────────────── error reporting ──


def test_missing_required_field_names_the_path():
    with pytest.raises(ValidationError, match="lines"):
        invoice_from_dict({k: v for k, v in MINIMAL.items() if k != "lines"})


def test_bad_line_error_points_at_the_offending_line():
    data = {**MINIMAL, "lines": [
        MINIMAL["lines"][0],
        {"description": "x", "quantity": "1", "vat_rate": "22"},  # no price
    ]}

    with pytest.raises(ValidationError, match=r"lines\[1\]"):
        invoice_from_dict(data)


def test_bad_date_says_what_it_expected():
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        invoice_from_dict({**MINIMAL, "date": "05/06/2026"})


def test_unknown_enum_lists_the_allowed_codes():
    with pytest.raises(ValidationError, match="TD01"):
        invoice_from_dict({**MINIMAL, "document_type": "TD99"})


def test_unparsable_amount_is_reported_with_its_field():
    data = {**MINIMAL, "lines": [
        {"description": "x", "quantity": "1", "unit_price": "cento", "vat_rate": "22"},
    ]}

    with pytest.raises(ValidationError, match="unit_price"):
        invoice_from_dict(data)


def test_invalid_json_is_a_validation_error_not_a_crash():
    with pytest.raises(ValidationError, match="JSON"):
        invoice_from_json("{ not json")
