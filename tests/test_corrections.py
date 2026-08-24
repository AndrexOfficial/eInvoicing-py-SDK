"""Credit notes, debit notes and returns.

A correction is the document most likely to be built wrong, because its meaning
lives in two places at once: the document *type* says which direction the money
moves, and the *amounts* say how much. Applying the direction in both places
produces a credit note that asks the customer to pay.

The other half of this file covers returns, which have two legitimate shapes —
a credit note, or a negative line on the next invoice — and the package has to
handle both without treating either as an error.
"""
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from einvoice import (
    Address,
    DocumentReference,
    DocumentType,
    Invoice,
    LineItem,
    Party,
    Payment,
    PaymentMeans,
    parse_invoice,
)
from einvoice.formats import get_renderer

CBC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
CAC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"
CN_NS = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
INV_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"

STANDARDS = ["fatturapa", "ubl", "cii"]
CREDITED = [DocumentReference("invoice", "INV-9", date(2026, 7, 1))]


def _doc(**kw) -> Invoice:
    base = {
        "number": "CN-1", "date": date(2026, 8, 24),
        "seller": Party(name="S", vat_number="07643520567",
                        address=Address("Via Roma 1", "20100", "Milano", "MI")),
        "buyer": Party(name="B", vat_number="09876543217", sdi_code="ABCDEFG",
                       address=Address("Via Verdi 9", "00100", "Roma", "RM")),
        "lines": [LineItem("Reso merce", Decimal("2"), Decimal("50"), Decimal("22"))],
    }
    base.update(kw)
    return Invoice(**base)


def _credit_note(**kw) -> Invoice:
    return _doc(document_type=DocumentType.CREDIT_NOTE, references=CREDITED, **kw)


def _rendered(invoice: Invoice, standard: str) -> bytes:
    return get_renderer(standard).render(invoice).content


# ── the shape of a credit note ─────────────────────────────────────────────


def test_amounts_on_a_credit_note_are_positive():
    """The direction is carried by the document type, not by the sign.

    EN 16931 and FatturaPA agree on this: a credit note for 122.00 states
    122.00, and the reader knows from the type that it reduces what is owed.
    """
    note = _credit_note()
    assert note.taxable_total() == Decimal("100.00")
    assert note.tax_total() == Decimal("22.00")
    assert note.total_document() == Decimal("122.00")


def test_ubl_puts_a_credit_note_on_its_own_root():
    """Not cosmetic: UBL 2.1 has a separate CreditNote schema with different
    line and quantity tags. Emitting an Invoice root with type code 381 is a
    document no Peppol receiver accepts."""
    root = ET.fromstring(_rendered(_credit_note(), "ubl"))

    assert root.tag == f"{{{CN_NS}}}CreditNote"
    assert root.findtext(f"{CBC}CreditNoteTypeCode") == "381"
    assert root.find(f"{CAC}CreditNoteLine") is not None
    assert root.find(f"{CAC}CreditNoteLine/{CBC}CreditedQuantity") is not None


def test_a_ubl_credit_note_carries_no_document_due_date():
    """UBL 2.1's CreditNote has no cbc:DueDate; emitting one is invalid."""
    root = ET.fromstring(_rendered(_credit_note(
        payments=[Payment(means=PaymentMeans.BANK_TRANSFER,
                          due_date=date(2026, 9, 30))]), "ubl"))

    assert root.find(f"{CBC}DueDate") is None
    # ...while the payment means itself is still stated.
    assert root.find(f"{CAC}PaymentMeans") is not None


def test_cii_keeps_one_root_and_changes_only_the_type_code():
    """CII has no separate credit-note root — the type code is the whole
    difference, which is exactly why it is easy to get wrong."""
    from einvoice.formats.cii import RAM, RSM

    root = ET.fromstring(_rendered(_credit_note(), "cii"))
    assert root.tag == f"{{{RSM}}}CrossIndustryInvoice"
    assert root.findtext(f".//{{{RAM}}}TypeCode") == "381"


def test_fatturapa_uses_td04_and_links_the_original():
    xml = _rendered(_credit_note(), "fatturapa").decode()
    assert "<TipoDocumento>TD04</TipoDocumento>" in xml
    assert "<DatiFattureCollegate>" in xml
    assert "<IdDocumento>INV-9</IdDocumento>" in xml


def test_a_debit_note_is_not_a_credit_note():
    """Both correct an earlier invoice, in opposite directions. A debit note
    stays on the Invoice root with UNCL 383."""
    note = _doc(document_type=DocumentType.DEBIT_NOTE, references=CREDITED)
    root = ET.fromstring(_rendered(note, "ubl"))

    assert root.tag == f"{{{INV_NS}}}Invoice"
    assert root.findtext(f"{CBC}InvoiceTypeCode") == "383"


# ── the simplified family ──────────────────────────────────────────────────


def test_the_simplified_credit_note_is_a_credit_note():
    """TD08 was missing from the code list entirely, so a simplified credit
    note could not be expressed — and had it been, nothing would have known it
    belonged on the CreditNote root."""
    note = _doc(document_type=DocumentType.SIMPLIFIED_CREDIT_NOTE, references=CREDITED)
    root = ET.fromstring(_rendered(note, "ubl"))

    assert DocumentType.SIMPLIFIED_CREDIT_NOTE.is_credit_note
    assert root.tag == f"{{{CN_NS}}}CreditNote"
    assert root.findtext(f"{CBC}CreditNoteTypeCode") == "381"


def test_the_simplified_debit_note_stays_on_the_invoice_root():
    note = _doc(document_type=DocumentType.SIMPLIFIED_DEBIT_NOTE, references=CREDITED)
    root = ET.fromstring(_rendered(note, "ubl"))
    assert root.tag == f"{{{INV_NS}}}Invoice"
    assert root.findtext(f"{CBC}InvoiceTypeCode") == "383"


@pytest.mark.parametrize("doc_type", [
    DocumentType.SIMPLIFIED_INVOICE,
    DocumentType.SIMPLIFIED_CREDIT_NOTE,
    DocumentType.SIMPLIFIED_DEBIT_NOTE,
])
def test_fatturapa_preserves_the_simplified_code(doc_type):
    note = _doc(document_type=doc_type, references=CREDITED)
    restored = parse_invoice(_rendered(note, "fatturapa"))
    assert restored.document_type is doc_type


@pytest.mark.parametrize(("doc_type", "narrowed_to"), [
    (DocumentType.SIMPLIFIED_INVOICE, DocumentType.INVOICE),
    (DocumentType.SIMPLIFIED_CREDIT_NOTE, DocumentType.CREDIT_NOTE),
    (DocumentType.SIMPLIFIED_DEBIT_NOTE, DocumentType.DEBIT_NOTE),
])
@pytest.mark.parametrize("standard", ["ubl", "cii"])
def test_en16931_narrows_the_simplified_code_but_keeps_the_direction(
        doc_type, narrowed_to, standard):
    """UNCL 1001 has three codes where Italy has nine, so "simplified" cannot
    survive a trip through EN 16931. What must survive is the direction — a
    credit note has to come back a credit note."""
    note = _doc(document_type=doc_type, references=CREDITED)
    restored = parse_invoice(_rendered(note, standard))

    assert restored.document_type is narrowed_to
    assert restored.document_type.is_credit_note == doc_type.is_credit_note
    assert restored.document_type.is_debit_note == doc_type.is_debit_note


# ── round trip ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("standard", STANDARDS)
def test_a_credit_note_round_trips_with_its_reference_and_its_money(standard):
    original = _credit_note()
    restored = parse_invoice(_rendered(original, standard))

    assert restored.document_type.is_credit_note
    assert restored.total_document() == original.total_document()
    reference = next(r for r in restored.references if r.kind == "invoice")
    assert reference.doc_id == "INV-9"


# ── the mistakes worth catching ────────────────────────────────────────────


def test_a_credit_note_with_negative_amounts_is_flagged():
    """The expensive version of this mistake: the direction gets applied twice,
    and a document meant to refund the customer asks them to pay."""
    wrong = _credit_note(lines=[
        LineItem("Reso", Decimal("2"), Decimal("-50"), Decimal("22"))])

    assert wrong.total_document() < 0
    assert "correction_sign" in {a.code for a in wrong.check()}


def test_a_debit_note_with_negative_amounts_is_flagged_too():
    wrong = _doc(document_type=DocumentType.DEBIT_NOTE, references=CREDITED,
                 lines=[LineItem("X", Decimal("1"), Decimal("-50"), Decimal("22"))])
    assert "correction_sign" in {a.code for a in wrong.check()}


def test_a_correction_with_nothing_to_correct_is_flagged():
    """SdI accepts it, so this cannot be a hard error — but an unmatched credit
    note sits unapplied in the customer's ledger."""
    orphan = _doc(document_type=DocumentType.CREDIT_NOTE)

    orphan.validate()   # still a structurally valid document
    assert "correction_no_reference" in {a.code for a in orphan.check()}


@pytest.mark.parametrize("doc_type", [
    DocumentType.CREDIT_NOTE, DocumentType.DEBIT_NOTE,
    DocumentType.SIMPLIFIED_CREDIT_NOTE, DocumentType.SIMPLIFIED_DEBIT_NOTE,
])
def test_every_correcting_type_wants_a_reference(doc_type):
    assert "correction_no_reference" in {
        a.code for a in _doc(document_type=doc_type).check()}


def test_a_well_formed_credit_note_raises_nothing():
    assert _credit_note().check() == []


# ── returns ────────────────────────────────────────────────────────────────


def test_a_return_as_a_negative_line_on_an_ordinary_invoice_is_not_an_error():
    """The other legitimate shape: net the return off the next invoice rather
    than issuing a credit note. Nothing here may treat that as a mistake."""
    netted = _doc(lines=[
        LineItem("Vendita", Decimal("10"), Decimal("100"), Decimal("22")),
        LineItem("Reso", Decimal("-2"), Decimal("100"), Decimal("22")),
    ])

    netted.validate()
    assert netted.check() == []
    assert netted.taxable_total() == Decimal("800.00")
    assert netted.total_document() == Decimal("976.00")


@pytest.mark.parametrize("standard", STANDARDS)
def test_a_netted_return_round_trips(standard):
    netted = _doc(lines=[
        LineItem("Vendita", Decimal("10"), Decimal("100"), Decimal("22")),
        LineItem("Reso", Decimal("-2"), Decimal("100"), Decimal("22")),
    ])
    restored = parse_invoice(_rendered(netted, standard))

    assert restored.total_document() == netted.total_document()
    assert len(restored.lines) == 2
    assert restored.lines[1].quantity == Decimal("-2")


def test_a_full_return_nets_an_invoice_to_zero():
    """The edge worth knowing behaves: a return of everything sold."""
    nil = _doc(lines=[
        LineItem("Vendita", Decimal("2"), Decimal("100"), Decimal("22")),
        LineItem("Reso", Decimal("-2"), Decimal("100"), Decimal("22")),
    ])

    nil.validate()
    assert nil.total_document() == Decimal("0.00")
    assert _rendered(nil, "ubl").startswith(b"<?xml")


def test_a_partial_credit_note_credits_only_what_it_says():
    """Crediting 2 of the 10 units sold: the note stands alone at its own
    amount, not at the original invoice's."""
    partial = _credit_note(lines=[
        LineItem("Reso 2 di 10", Decimal("2"), Decimal("100"), Decimal("22"))])

    assert partial.total_document() == Decimal("244.00")
    assert partial.check() == []
