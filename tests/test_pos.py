"""Il punto in cui la cassa e la fattura si toccano.

Due difetti reali di un prodotto che usa questo pacchetto hanno motivato il
modulo, e sono il metro di questi test: una fattura che dichiarava «bonifico»
su ogni vendita perché non c'era una tabella da consultare, e una fattura
emessa dopo un documento commerciale che non lo citava — quindi la stessa
vendita contata due volte.
"""
from datetime import date
from decimal import Decimal

import pytest

from einvoice import Invoice, LineItem, Party, PaymentMeans, VatNature
from einvoice.pos import (
    PAYMENT_MEANS_BY_POS,
    DepartmentTable,
    PosPaymentMethod,
    ReceiptReference,
    VatDepartment,
    check_pos_alignment,
    link_receipt,
    payment_means_for,
    validate_lottery_code,
)


def _invoice(rate="10", causale=None):
    return Invoice(
        number="1/2026", date=date(2026, 8, 27),
        seller=Party(name="Trattoria", vat_number="IT12345678903", country_code="IT",
                     tax_regime="RF01"),
        buyer=Party(name="Cliente", vat_number="IT0278620153", country_code="IT"),
        lines=[LineItem.from_gross("Coperto", 1, Decimal("11.00"), Decimal(rate))],
        causale=causale,
    )


# ── il pagamento ──────────────────────────────────────────────────────


@pytest.mark.parametrize("method", list(PosPaymentMethod))
def test_every_till_payment_has_an_answer(method):
    """Un metodo senza voce farebbe ricadere il chiamante sul default che ha
    causato il bug: MP05 su tutto."""
    assert method in PAYMENT_MEANS_BY_POS


def test_cash_is_cash_and_card_is_card():
    assert payment_means_for(PosPaymentMethod.CASH).code is PaymentMeans.CASH
    assert payment_means_for(PosPaymentMethod.CARD).code is PaymentMeans.CARD


def test_a_compromise_is_labelled_as_one():
    """La lista MP è stata scritta per la fatturazione: per i buoni pasto un
    codice dedicato non esiste, e nascondere la differenza fra «giusto» e «meno
    sbagliato» toglie proprio l'informazione che serve al commercialista."""
    voucher = payment_means_for(PosPaymentMethod.MEAL_VOUCHER)

    assert voucher.code is PaymentMeans.CARD
    assert voucher.exact is False
    assert voucher.note


def test_not_collected_means_omit_the_block_not_invent_a_method():
    """Dichiarare una modalità su una fattura non incassata la fa risultare
    pagata."""
    mapping = payment_means_for(PosPaymentMethod.NOT_COLLECTED)

    assert mapping.code is None
    assert mapping.exact is True


def test_an_unknown_method_degrades_instead_of_blocking_the_invoice():
    mapping = payment_means_for("qualcosa-che-non-esiste")

    assert mapping.code is None
    assert mapping.exact is False


@pytest.mark.parametrize("method,mapping", sorted(PAYMENT_MEANS_BY_POS.items(), key=lambda kv: kv[0].value))
def test_an_inexact_mapping_always_explains_itself(method, mapping):
    if not mapping.exact:
        assert mapping.note, f"{method.value}: compromesso senza spiegazione"


# ── il documento commerciale ──────────────────────────────────────────


def test_the_reference_names_the_document_and_the_device():
    receipt = ReceiptReference(number="0002-0041", date=date(2026, 8, 27),
                               rt_serial="99MEY012345")
    causale = receipt.to_causale()

    assert "0002-0041" in causale and "27/08/2026" in causale
    assert "99MEY012345" in causale


def test_linking_keeps_the_causale_that_was_already_there():
    """La descrizione della prestazione e il riferimento al corrispettivo
    servono entrambe; sceglierne una sarebbe scegliere per il contribuente."""
    invoice = _invoice(causale="Servizio di ristorazione")
    link_receipt(invoice, ReceiptReference("0002-0041", date(2026, 8, 27)))

    assert "Servizio di ristorazione" in invoice.causale
    assert "0002-0041" in invoice.causale


def test_linking_twice_does_not_repeat_itself():
    invoice = _invoice()
    receipt = ReceiptReference("0002-0041", date(2026, 8, 27))
    link_receipt(invoice, receipt)
    link_receipt(invoice, receipt)

    assert invoice.causale.count("0002-0041") == 1


def test_an_unlinked_invoice_is_flagged():
    """Il difetto per cui il modulo esiste: senza riferimento, il corrispettivo
    già trasmesso e la fattura descrivono lo stesso incasso due volte."""
    findings = check_pos_alignment(_invoice(), ReceiptReference("0002-0041", date(2026, 8, 27)))

    assert "pos_receipt_not_referenced" in [f.code for f in findings]


def test_a_linked_invoice_is_not_flagged():
    invoice = _invoice()
    receipt = ReceiptReference("0002-0041", date(2026, 8, 27))
    link_receipt(invoice, receipt)

    codes = [f.code for f in check_pos_alignment(invoice, receipt)]
    assert "pos_receipt_not_referenced" not in codes


def test_a_receipt_dated_after_its_invoice_is_flagged():
    receipt = ReceiptReference("0002-0041", date(2026, 9, 30))

    codes = [f.code for f in check_pos_alignment(_invoice(), receipt)]
    assert "pos_receipt_after_invoice" in codes


@pytest.mark.parametrize("code,valid", [
    ("ABCD1234", True), ("12345678", True), ("abcd1234", False),
    ("ABC123", False), ("ABCD12345", False), ("", False), (None, False),
])
def test_lottery_code_shape(code, valid):
    assert validate_lottery_code(code) is valid


def test_a_malformed_lottery_code_is_flagged():
    receipt = ReceiptReference("1", date(2026, 8, 27), lottery_code="nope")

    codes = [f.code for f in check_pos_alignment(_invoice(), receipt)]
    assert "pos_lottery_code_malformed" in codes


# ── i reparti IVA ─────────────────────────────────────────────────────


def test_a_rate_resolves_to_its_department():
    table = DepartmentTable([
        VatDepartment(1, Decimal("10")), VatDepartment(2, Decimal("22")),
    ])

    assert table.for_rate(Decimal("22")).index == 2
    assert table.for_rate("10").index == 1


def test_a_rate_with_no_department_answers_none_rather_than_guessing():
    """Battere una vendita su un reparto qualunque è peggio che dire che non è
    battibile: il totale per reparto smette di riconciliarsi e nessuno se ne
    accorge fino alla chiusura."""
    table = DepartmentTable([VatDepartment(1, Decimal("10"))])

    assert table.for_rate(Decimal("22")) is None


def test_two_departments_on_the_same_rate_are_flagged():
    table = DepartmentTable([
        VatDepartment(1, Decimal("10")), VatDepartment(3, Decimal("10")),
    ])

    assert "pos_department_ambiguous_rate" in [f.code for f in table.check()]


def test_a_duplicate_index_is_flagged():
    table = DepartmentTable([
        VatDepartment(1, Decimal("10")), VatDepartment(1, Decimal("22")),
    ])

    assert "pos_department_duplicate_index" in [f.code for f in table.check()]


def test_an_invoice_rate_the_till_cannot_ring_is_flagged():
    table = DepartmentTable([VatDepartment(1, Decimal("22"))])

    codes = [f.code for f in table.check(_invoice(rate="10"))]
    assert "pos_rate_without_department" in codes


def test_a_nature_falls_back_to_the_plain_rate_department():
    """Meglio del nulla, e il rilievo resta a segnalarlo."""
    table = DepartmentTable([VatDepartment(4, Decimal("0"))])

    assert table.for_rate(Decimal("0"), VatNature.EXEMPT).index == 4


def test_check_never_raises_on_an_empty_table():
    assert DepartmentTable().check(_invoice()) is not None


# ── la superficie pubblica ────────────────────────────────────────────


def test_every_public_module_is_reachable_from_the_package_root():
    """Un modulo aggiunto e non esportato è codice che esiste e che nessuno
    trova. Il controllo va fatto nei due versi: che ogni nome in ``__all__``
    esista *e* che ogni nome pubblico dei moduli ci sia — verificare solo il
    primo passa anche quando non si è esportato niente, che è esattamente
    com'è successo aggiungendo `pdf` e `receipt`.
    """
    import importlib

    import einvoice

    mancanti: list[str] = []
    for nome in ("pos", "receipt", "pdf", "devices", "i18n", "onboarding", "reference"):
        modulo = importlib.import_module(f"einvoice.{nome}")
        for pubblico in getattr(modulo, "__all__", []):
            if pubblico.startswith("_"):
                continue
            if pubblico not in einvoice.__all__:
                mancanti.append(f"{nome}.{pubblico}")

    assert not mancanti, f"pubblici ma non esportati dal pacchetto: {mancanti}"


def test_every_exported_name_actually_exists():
    import einvoice

    assert [n for n in einvoice.__all__ if not hasattr(einvoice, n)] == []
