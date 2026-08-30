"""Il documento commerciale, e il centesimo che non torna.

La cosa che questo modulo esiste per rendere esplicita è che **una cassa e una
fattura arrotondano in versi opposti**: il banco vende a prezzi lordi e scorpora
l'IVA dal corrispettivo, la fattura parte dai netti di riga e li somma. Sulla
stessa vendita i due totali possono differire di un centesimo, nessuno dei due
sbaglia, ed è quel centesimo che non torna alla chiusura.
"""
from datetime import date
from decimal import Decimal

import pytest

from einvoice import LineItem, VatNature
from einvoice.pos import PosPaymentMethod
from einvoice.receipt import (
    CommercialDocument,
    ReceiptPayment,
    check_receipt,
    print_receipt,
    receipt_lines,
)


def _trattoria(**kwargs) -> CommercialDocument:
    """Un conto vero: due aliquote, prezzi lordi come li batte una cassa."""
    defaults = {
        "number": "0002-0041", "date": date(2026, 8, 27),
        "lines": [
            LineItem.from_gross("Coperto", 2, Decimal("2.00"), Decimal("10")),
            LineItem.from_gross("Tagliatelle", 2, Decimal("12.00"), Decimal("10")),
            LineItem.from_gross("Vino", 1, Decimal("18.00"), Decimal("22")),
        ],
    }
    defaults.update(kwargs)
    return CommercialDocument(**defaults)


# ── i numeri ──────────────────────────────────────────────────────────


def test_the_total_is_the_money_that_changed_hands():
    """46,00 è quello che il cliente ha dato. Un totale di 46,01 su uno
    scontrino non è un arrotondamento: è una contestazione."""
    assert _trattoria().total() == Decimal("46.00")


def test_each_vat_bucket_reconciles_exactly():
    """Imponibile + imposta di ogni aliquota devono risommare al lordo di
    quella aliquota, o il riepilogo stampato non regge a una somma a mano."""
    doc = _trattoria()
    for summary in doc.vat_summary():
        gross = sum(doc.line_gross(line) for line in doc.lines
                    if line.vat_rate == summary.vat_rate)
        assert summary.taxable + summary.tax == gross, summary.vat_rate


def test_the_summary_adds_up_to_the_printed_total():
    doc = _trattoria()

    assert doc.taxable_total() + doc.tax_total() == doc.total()


def test_the_drift_against_the_invoice_is_reported_not_hidden():
    """Il difetto per cui il rilievo esiste: le stesse righe, in fattura,
    fanno 46,01. Sceglierne uno in silenzio è come si perde di vista il
    centesimo che alla chiusura non torna."""
    doc = _trattoria()

    assert doc.as_invoice_lines().total_document() == Decimal("46.01")
    assert "receipt_invoice_total_drift" in [a.code for a in check_receipt(doc)]


def test_a_sale_priced_net_has_no_drift_and_says_nothing():
    """Il rilievo non deve comparire su ogni scontrino, o smette di essere
    letto."""
    doc = CommercialDocument(
        number="1", date=date(2026, 8, 27),
        lines=[LineItem("Servizio", Decimal("1"), Decimal("100.00"), Decimal("22"))],
    )

    assert doc.total() == Decimal("122.00")
    assert "receipt_invoice_total_drift" not in [a.code for a in check_receipt(doc)]


def test_two_natures_at_the_same_rate_stay_separate():
    """Regimi diversi non si mischiano, come nel riepilogo della fattura."""
    doc = CommercialDocument(
        number="1", date=date(2026, 8, 27),
        lines=[
            LineItem("Esente", Decimal("1"), Decimal("10.00"), Decimal("0"),
                     nature=VatNature.EXEMPT),
            LineItem("Non soggetto", Decimal("1"), Decimal("10.00"), Decimal("0"),
                     nature=VatNature.NOT_SUBJECT),
        ],
    )

    assert len(doc.vat_summary()) == 2


def test_change_is_given_only_when_more_was_handed_over():
    doc = _trattoria(payments=[ReceiptPayment(PosPaymentMethod.CASH, Decimal("50.00"))])

    assert doc.change() == Decimal("4.00")
    assert _trattoria(payments=[ReceiptPayment(PosPaymentMethod.CARD, Decimal("46.00"))]).change() == 0


def test_an_underpaid_receipt_is_flagged():
    doc = _trattoria(payments=[ReceiptPayment(PosPaymentMethod.CASH, Decimal("20.00"))])

    assert "receipt_underpaid" in [a.code for a in check_receipt(doc)]


# ── la lotteria ───────────────────────────────────────────────────────


def test_the_lottery_code_needs_a_cashless_payment():
    """Stamparlo su un incasso in contanti promette al cliente una
    partecipazione che non ci sarà."""
    doc = _trattoria(lottery_code="ABCD1234",
                     payments=[ReceiptPayment(PosPaymentMethod.CASH, Decimal("46.00"))])

    assert "receipt_lottery_needs_electronic_payment" in [a.code for a in check_receipt(doc)]
    assert "Lotteria" not in "\n".join(receipt_lines(doc)), "e non va nemmeno stampato"


def test_the_lottery_code_prints_on_a_card_payment():
    doc = _trattoria(lottery_code="ABCD1234",
                     payments=[ReceiptPayment(PosPaymentMethod.CARD, Decimal("46.00"))])

    testo = "\n".join(receipt_lines(doc))
    assert "ABCD1234" in testo
    assert "Lotteria degli scontrini" in testo, "l'etichetta segue la lingua del paese"
    assert "receipt_lottery_needs_electronic_payment" not in [a.code for a in check_receipt(doc)]


def test_a_mixed_payment_is_not_fully_electronic():
    doc = _trattoria(payments=[
        ReceiptPayment(PosPaymentMethod.CARD, Decimal("40.00")),
        ReceiptPayment(PosPaymentMethod.CASH, Decimal("6.00")),
    ])

    assert doc.fully_electronic is False


# ── cosa è, e cosa non è ──────────────────────────────────────────────


def test_a_courtesy_copy_says_so_and_is_the_default():
    """Il valore predefinito non deve essere quello che espone a una sanzione."""
    doc = _trattoria()
    testo = "\n".join(receipt_lines(doc))

    assert doc.fiscal is False
    assert "COPIA DI CORTESIA" in testo
    assert "non valido ai fini fiscali" in testo


def test_a_fiscal_document_without_a_device_serial_is_flagged():
    doc = _trattoria(fiscal=True)

    assert "receipt_fiscal_without_device" in [a.code for a in check_receipt(doc)]


def test_the_reference_is_what_a_later_invoice_must_cite():
    from einvoice.pos import check_pos_alignment, link_receipt

    doc = _trattoria(fiscal=True, rt_serial="99MEY012345")
    invoice = doc.as_invoice_lines()

    assert "pos_receipt_not_referenced" in [a.code for a in check_pos_alignment(invoice, doc.reference())]
    link_receipt(invoice, doc.reference())
    assert "pos_receipt_not_referenced" not in [a.code for a in check_pos_alignment(invoice, doc.reference())]


# ── il layout ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("width", [32, 42, 48])
def test_no_line_overflows_the_paper(width):
    """Una riga più larga della carta va a capo dove decide la stampante, e il
    numero finisce su una riga sua."""
    doc = _trattoria(merchant="Trattoria da Bruno con un nome molto lungo",
                     merchant_details=["Via Roma 1, Milano", "P.IVA 12345678903"],
                     payments=[ReceiptPayment(PosPaymentMethod.CARD, Decimal("46.00"))],
                     footer=["Grazie e arrivederci"])

    for line in receipt_lines(doc, width=width):
        assert len(line) <= width, repr(line)


def test_the_amount_survives_a_long_description():
    """Si taglia l'etichetta, mai la cifra: uno scontrino con un totale mozzato
    non è un documento."""
    doc = CommercialDocument(
        number="1", date=date(2026, 8, 27),
        lines=[LineItem.from_gross("Descrizione lunghissima " * 5, 1,
                                   Decimal("1234.56"), Decimal("22"))],
    )

    riga = next(r for r in receipt_lines(doc, width=32) if r.endswith("1234.56"))
    assert riga.endswith("1234.56")


# ── la stampa ─────────────────────────────────────────────────────────


class _Recorder:
    """Una stampante finta con l'interfaccia di python-escpos."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.printed: list[str] = []

    def set(self, **kwargs):
        self.calls.append(("set", kwargs))

    def text(self, txt):
        self.calls.append(("text", txt))
        self.printed.append(txt)

    def cut(self):
        self.calls.append(("cut", None))

    def cashdraw(self, pin):
        self.calls.append(("cashdraw", pin))


def test_printing_sends_exactly_the_lines_that_were_composed():
    """Ciò che si vede in anteprima è ciò che esce: se le due strade divergono,
    l'anteprima smette di servire a qualcosa."""
    doc = _trattoria()
    printer = _Recorder()

    print_receipt(doc, printer)

    assert [t.rstrip("\n") for t in printer.printed] == receipt_lines(doc)
    assert ("cut", None) in printer.calls


def test_the_drawer_opens_after_the_cut_and_only_on_request():
    """Un cassetto che scatta a ogni preconto è un cassetto che resta aperto."""
    printer = _Recorder()
    print_receipt(_trattoria(), printer)
    assert not [c for c in printer.calls if c[0] == "cashdraw"]

    printer = _Recorder()
    print_receipt(_trattoria(), printer, open_drawer=True)
    kinds = [c[0] for c in printer.calls]
    assert kinds.index("cut") < kinds.index("cashdraw")
    assert [c[1] for c in printer.calls if c[0] == "cashdraw"] == [2, 5]


def test_a_printer_without_set_still_prints():
    """``set`` è opzionale nell'interfaccia. Un AttributeError a metà scontrino
    lascia mezza carta fuori e nessun documento."""

    class Minimal:
        def __init__(self):
            self.printed = []

        def text(self, txt):
            self.printed.append(txt)

        def cut(self):
            pass

    printer = Minimal()
    print_receipt(_trattoria(), printer)

    assert len(printer.printed) == len(receipt_lines(_trattoria()))


def test_a_drawer_pin_that_is_not_wired_is_not_an_error():
    class OnePin(_Recorder):
        def cashdraw(self, pin):
            if pin != 2:
                raise RuntimeError("pin non cablato")
            super().cashdraw(pin)

    printer = OnePin()
    print_receipt(_trattoria(), printer, open_drawer=True)

    assert [c[1] for c in printer.calls if c[0] == "cashdraw"] == [2]


def test_it_drives_the_real_python_escpos_dummy_printer():
    """La prova che l'interfaccia a cui parliamo è davvero la loro.

    ``Dummy()`` raccoglie i comandi in memoria: nessun hardware, nessuna rete.
    Saltato dove la libreria non è installata — non è una dipendenza.
    """
    escpos_printer = pytest.importorskip("escpos.printer")

    printer = escpos_printer.Dummy()
    print_receipt(_trattoria(fiscal=True, rt_serial="99MEY012345"), printer)

    assert b"DOCUMENTO COMMERCIALE" in printer.output
    assert b"99MEY012345" in printer.output


# ── la lingua ─────────────────────────────────────────────────────────


def test_the_receipt_speaks_the_language_of_the_billing_country():
    """Chi compra al banco legge la lingua del posto, non quella di chi ha
    scritto il software."""
    tedesco = "\n".join(receipt_lines(_trattoria(country="DE")))
    polacco = "\n".join(receipt_lines(_trattoria(country="PL")))

    assert "GESAMT" in tedesco and "Nettobetrag" in tedesco
    assert "RAZEM" in polacco and "Podstawa opodatkowania" in polacco


def test_an_explicit_locale_beats_the_country():
    """Un negozio di Bolzano vende in Italia e stampa in tedesco."""
    doc = _trattoria(country="IT", locale="de")

    assert "GESAMT" in "\n".join(receipt_lines(doc))
    assert doc.resolved_locale() == "de"


def test_an_unprofiled_country_falls_back_to_english_not_to_italian():
    assert "TOTAL" in "\n".join(receipt_lines(_trattoria(country="ZZ")))


def test_the_payment_method_is_a_word_not_an_identifier():
    """Arrivava sullo scontrino come ``card``: una chiave di programma finita
    in mano a un cliente."""
    doc = _trattoria(country="IT",
                     payments=[ReceiptPayment(PosPaymentMethod.MEAL_VOUCHER, Decimal("46.00"))])
    testo = "\n".join(receipt_lines(doc))

    assert "Buono pasto" in testo
    assert "meal_voucher" not in testo


@pytest.mark.parametrize("country", ["IT", "DE", "FR", "PL", "GR", "PT"])
def test_no_line_overflows_in_any_language(country):
    """Una traduzione più lunga dell'originale è il modo normale in cui un
    layout a colonne fisse si rompe."""
    doc = _trattoria(country=country,
                     payments=[ReceiptPayment(PosPaymentMethod.MEAL_VOUCHER, Decimal("50.00"))])

    for line in receipt_lines(doc, width=32):
        assert len(line) <= 32, repr(line)
