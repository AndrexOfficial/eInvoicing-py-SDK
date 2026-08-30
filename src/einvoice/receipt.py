"""Il documento commerciale: il pezzo di carta che esce dalla cassa.

Il pacchetto sapeva descrivere una fattura e sapeva **citare** uno scontrino
(:class:`einvoice.pos.ReceiptReference`), ma non sapeva descriverne uno. Chi lo
incorpora finiva quindi a ricalcolare i riepiloghi IVA per conto proprio nel
codice di stampa — e due calcoli IVA sulla stessa vendita divergono, sempre, e
si scoprono al controllo.

**Una cassa e una fattura arrotondano in versi opposti**, ed è la cosa che
questo modulo esiste per rendere esplicita. Il banco vende a prezzi *lordi*: il
totale è quello che il cliente paga, e l'IVA si ricava per scorporo dal
corrispettivo di ogni aliquota. Una fattura si costruisce dal netto in su, riga
per riga, e ogni riga si arrotonda per conto suo. Sulla stessa vendita i due
totali possono differire di un centesimo — non perché uno sbagli, ma perché
sono due calcoli diversi entrambi corretti.

Quel centesimo è reale: è quello che non torna alla chiusura, quando lo stesso
incasso compare nei corrispettivi e in una fattura. Il documento qui usa lo
scorporo, che è ciò che fa una cassa e che fa quadrare il totale stampato con i
soldi ricevuti; :func:`check_receipt` segnala quando la fattura per le stesse
righe direbbe un numero diverso, invece di lasciare che la differenza si scopra
mesi dopo.

    from einvoice.receipt import CommercialDocument, receipt_lines

    doc = CommercialDocument(number="0002-0041", date=date.today(), lines=[...])
    print("\\n".join(receipt_lines(doc, width=42)))

**Sulla stampa.** Questo modulo non apre nessuna connessione. Compone le righe,
e sa *guidare* una stampante ESC/POS già aperta da chi lo chiama —
:func:`print_receipt` accetta qualunque oggetto con l'interfaccia di
`python-escpos <https://python-escpos.readthedocs.io>`_ (``set`` / ``text`` /
``ln`` / ``cut`` / ``cashdraw``) senza importarlo: nessuna dipendenza nuova, e
funziona anche col loro ``Dummy()``, che raccoglie i byte in memoria.

Reimplementare ESC/POS a byte qui dentro sarebbe stato l'errore facile. Il
punto duro di quel protocollo non sono i codici di controllo: sono le **code
page**. Uno scontrino italiano è pieno di `à è ì ò ù` e di `€`, e ogni modello
di stampante li vuole in una tabella diversa; python-escpos ha un meccanismo
apposta (``charcode`` / magic encode) che ci ha messo anni a diventare
affidabile. Rifarlo male significa mojibake su un documento fiscale.

**Non è un documento fiscale.** Un documento commerciale valido esce da un
dispositivo omologato — un RT — che lo numera e lo trasmette. Quello che si
stampa da qui è una copia di cortesia o un preconto, e :attr:`fiscal` di
default è ``False`` proprio per non lasciare quella distinzione all'intuito.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import date as _date
from decimal import Decimal

from .enums import VatNature
from .i18n import locale_for_country, normalize_locale, translate
from .models import Advisory, Invoice, LineItem, Party, VatSummary
from .money import D, q2
from .pos import PosPaymentMethod, ReceiptReference, validate_lottery_code

__all__ = [
    "ReceiptPayment",
    "CommercialDocument",
    "receipt_lines",
    "print_receipt",
    "check_receipt",
]

#: Larghezze tipiche in caratteri: 80 mm ≈ 42/48 colonne, 58 mm ≈ 32.
DEFAULT_WIDTH = 42

#: I metodi che, in Italia, rendono lo scontrino idoneo alla lotteria: la
#: lotteria degli scontrini vuole un pagamento **interamente elettronico**.
_ELECTRONIC = frozenset({
    PosPaymentMethod.CARD,
    PosPaymentMethod.DIRECT_DEBIT,
    PosPaymentMethod.PAGOPA,
    PosPaymentMethod.BANK_TRANSFER,
})


@dataclass
class ReceiptPayment:
    """Una tranche di incasso. Uno scontrino può averne più d'una."""

    method: PosPaymentMethod
    amount: Decimal

    def __post_init__(self) -> None:
        self.method = PosPaymentMethod(self.method)
        self.amount = D(self.amount)


@dataclass
class CommercialDocument:
    """Lo scontrino: prezzi lordi, IVA per scorporo, totale che quadra.

    I numeri **non** sono quelli della fattura, ed è deliberato: vedi il
    docstring del modulo e :func:`check_receipt`, che misura la distanza fra i
    due calcoli invece di far finta che non ci sia.
    """

    number: str
    date: _date
    lines: list[LineItem]
    payments: list[ReceiptPayment] = field(default_factory=list)
    #: Intestazione: ragione sociale e le righe sotto (indirizzo, P.IVA).
    merchant: str = ""
    merchant_details: list[str] = field(default_factory=list)
    #: Matricola del registratore telematico che l'ha emesso.
    rt_serial: str | None = None
    lottery_code: str | None = None
    #: È uscito da un dispositivo omologato. Default ``False``: una copia di
    #: cortesia da una termica non lo è, e il valore predefinito non deve
    #: essere quello che espone a una sanzione.
    fiscal: bool = False
    currency: str = "EUR"
    footer: list[str] = field(default_factory=list)
    #: Il paese di fatturazione. Da qui esce la lingua dello scontrino quando
    #: non se ne passa una esplicita: chi compra al banco legge la lingua del
    #: posto, non quella di chi ha scritto il software.
    country: str = "IT"
    #: Forza la lingua. Un negozio di Bolzano la vorrà diversa dal suo paese.
    locale: str | None = None

    def resolved_locale(self) -> str:
        """La lingua in cui stampare: quella richiesta, altrimenti quella del
        paese di fatturazione, altrimenti l'inglese."""
        if self.locale:
            return normalize_locale(self.locale)
        return locale_for_country(self.country)

    # ── i numeri ──────────────────────────────────────────────────────
    def line_gross(self, line: LineItem) -> Decimal:
        """Il lordo di una riga: quello che compare stampato accanto al nome.

        Arrotondato **per riga**, perché è per riga che il cliente lo legge, e
        un totale che non è la somma di ciò che sta scritto sopra è un totale
        che verrà contestato.
        """
        unit_gross = line.unit_price * (Decimal("1") + line.vat_rate / Decimal("100"))
        return q2(unit_gross * line.quantity)

    def total(self) -> Decimal:
        """Il totale lordo — i soldi che cambiano mano."""
        return q2(sum((self.line_gross(line) for line in self.lines), Decimal("0")))

    def vat_summary(self) -> list[VatSummary]:
        """Il riepilogo IVA per **scorporo dal corrispettivo**.

        È il calcolo di una cassa, ed è l'unico che fa quadrare: imponibile e
        imposta di ogni aliquota risommano esattamente al lordo di quella
        aliquota, e i lordi risommano al totale stampato.

        La fattura fa il contrario — parte dai netti di riga e li somma — e sulla
        stessa vendita può arrivare a un centesimo di distanza. Vedi
        :func:`check_receipt`, che quella distanza la misura invece di
        nasconderla.
        """
        buckets: dict[tuple[Decimal, VatNature | None], Decimal] = {}
        order: list[tuple[Decimal, VatNature | None]] = []
        for line in self.lines:
            key = (line.vat_rate, line.nature)
            if key not in buckets:
                buckets[key] = Decimal("0")
                order.append(key)
            buckets[key] += self.line_gross(line)

        summaries: list[VatSummary] = []
        for rate, nature in order:
            gross = q2(buckets[(rate, nature)])
            taxable = q2(gross / (Decimal("1") + rate / Decimal("100")))
            summaries.append(VatSummary(vat_rate=rate, taxable=taxable,
                                        tax=q2(gross - taxable), nature=nature))
        return summaries

    def taxable_total(self) -> Decimal:
        return q2(sum((s.taxable for s in self.vat_summary()), Decimal("0")))

    def tax_total(self) -> Decimal:
        return q2(sum((s.tax for s in self.vat_summary()), Decimal("0")))

    def as_invoice_lines(self) -> Invoice:
        """Le stesse righe viste come fattura, per confrontare i due calcoli.

        Le parti sono segnaposto: serve solo a chiedere a
        :meth:`Invoice.vat_summary` cosa direbbe, e non esce da qui se non
        attraverso :func:`check_receipt`.
        """
        placeholder = Party(name="—", country_code="IT")
        return Invoice(number=self.number, date=self.date, seller=placeholder,
                       buyer=placeholder, lines=self.lines, currency=self.currency)

    def paid(self) -> Decimal:
        return q2(sum((p.amount for p in self.payments), Decimal("0")))

    def change(self) -> Decimal:
        """Il resto. Zero quando non è stato dato più del dovuto."""
        difference = self.paid() - self.total()
        return difference if difference > 0 else Decimal("0.00")

    # ── l'aggancio alla fattura ───────────────────────────────────────
    def reference(self) -> ReceiptReference:
        """Il riferimento che una fattura successiva deve citare.

        Vedi :func:`einvoice.pos.link_receipt`: senza, la stessa vendita
        risulta due volte — una nei corrispettivi, una in fattura.
        """
        return ReceiptReference(number=self.number, date=self.date,
                                rt_serial=self.rt_serial,
                                lottery_code=self.lottery_code)

    @property
    def fully_electronic(self) -> bool:
        """Tutto l'incasso è elettronico — il requisito della lotteria."""
        return bool(self.payments) and all(p.method in _ELECTRONIC for p in self.payments)


def _money(amount: Decimal) -> str:
    return f"{amount:.2f}"


def _centre(text: str, width: int) -> str:
    """Centrato **e** tagliato alla carta.

    ``str.center`` non accorcia: una ragione sociale più lunga della carta
    passerebbe intatta e andrebbe a capo dove decide il firmware, di solito in
    mezzo a una parola e con l'intestazione su due righe storte.
    """
    return text[:width].center(width).rstrip()


def _row(left: str, right: str, width: int) -> str:
    """Etichetta a sinistra, importo a destra, con l'importo intero.

    Se non ci sta tutto si taglia l'etichetta, mai la cifra: uno scontrino con
    un totale mozzato non è un documento, è un reclamo.
    """
    space = width - len(right) - 1
    if space < 1:
        return right[:width]
    return f"{left[:space]:<{space}} {right}"


def receipt_lines(doc: CommercialDocument, width: int = DEFAULT_WIDTH,
                  locale: str | None = None) -> list[str]:
    """Il documento come righe di testo, larghe ``width`` caratteri.

    Nessun codice di controllo: solo testo. Va bene per l'anteprima a schermo,
    per un allegato, per un test — e sono le stesse righe che
    :func:`print_receipt` manda alla stampante, così ciò che si vede in
    anteprima è ciò che esce.

    ``locale`` vince su quella del documento; omessa, si stampa nella lingua
    del paese di fatturazione. Gli **identificatori non si traducono**: un
    metodo di pagamento arrivava sullo scontrino come ``card``, che è una
    chiave di programma finita in mano a un cliente.
    """
    lang = normalize_locale(locale) if locale else doc.resolved_locale()

    def t(key: str) -> str:
        return translate(key, lang)

    out: list[str] = []
    rule = "-" * width

    if doc.merchant:
        out.append(_centre(doc.merchant, width))
    out.extend(_centre(line, width) for line in doc.merchant_details)
    if out:
        out.append(rule)

    title = t("receipt.commercial_document" if doc.fiscal else "receipt.courtesy_copy")
    out.append(_centre(title, width))
    if not doc.fiscal:
        # Il documento fiscale lo emette il registratore. Dirlo qui, e non
        # lasciarlo dedurre dall'assenza di una matricola, è la differenza fra
        # una copia e una contestazione.
        out.append(_centre(t("receipt.not_fiscal"), width))
    out.append(rule)

    for line in doc.lines:
        gross_unit = line.unit_price * (Decimal("1") + line.vat_rate / Decimal("100"))
        out.append(_row(line.description, _money(doc.line_gross(line)), width))
        if line.quantity != 1:
            detail = f"  {line.quantity:g} x {_money(q2(gross_unit))}"
            out.append(detail[:width])

    out.append(rule)
    out.append(_row(t("doc.total"), f"{_money(doc.total())} {doc.currency}", width))

    summaries = doc.vat_summary()
    if summaries:
        out.append("")
        out.append(_row(t("doc.taxable"), _money(doc.taxable_total()), width))
        for summary in summaries:
            label = f'  {t("doc.vat")} {summary.vat_rate:g}%'
            out.append(_row(label, _money(summary.tax), width))

    if doc.payments:
        out.append("")
        for payment in doc.payments:
            out.append(_row(t(f"pos_method.{payment.method.value}"),
                            _money(payment.amount), width))
        if doc.change() > 0:
            out.append(_row(t("receipt.change"), _money(doc.change()), width))

    out.append(rule)
    out.append(_row(f'{t("doc.number")} {doc.number}',
                    doc.date.strftime("%d/%m/%Y"), width))
    if doc.rt_serial:
        out.append(f'{t("receipt.device")} {doc.rt_serial}'[:width])
    if doc.lottery_code and doc.fully_electronic:
        out.append(f'{t("receipt.lottery")}: {doc.lottery_code}'[:width])
    out.extend(_centre(line, width) for line in doc.footer)
    return out


def print_receipt(doc: CommercialDocument, printer, *, width: int = DEFAULT_WIDTH,
                  cut: bool = True, open_drawer: bool = False,
                  locale: str | None = None) -> None:
    """Manda il documento a una stampante ESC/POS già aperta.

    ``printer`` è qualunque oggetto con l'interfaccia di python-escpos —
    ``Network``, ``Usb``, ``Serial``, o il loro ``Dummy()`` che raccoglie i
    byte in memoria. **Non viene importato niente**: è duck typing, quindi il
    pacchetto resta senza dipendenze e chi non stampa non installa nulla.

    Le code page non sono affar nostro. Uno scontrino italiano è pieno di
    accenti e di `€`, ogni modello li vuole in una tabella diversa, e la
    libreria di stampa ha un meccanismo apposta: passarle testo e lasciarglielo
    codificare è la ragione per cui questa funzione la guida invece di generare
    byte.

    Il cassetto si apre **dopo** il taglio e solo se richiesto: un cassetto che
    scatta a ogni preconto è un cassetto che resta aperto.
    """
    intestazione = bool(doc.merchant or doc.merchant_details)
    lines = receipt_lines(doc, width, locale)

    for index, line in enumerate(lines):
        if intestazione and index == 0:
            _set(printer, align="center", bold=True)
        elif line.startswith(translate("doc.total", locale or doc.resolved_locale())):
            _set(printer, align="left", bold=True)
        else:
            _set(printer, align="left", bold=False)
        printer.text(line + "\n")

    _set(printer, align="left", bold=False)
    if cut:
        printer.cut()
    if open_drawer:
        # Pin 2 è lo standard di fatto; alcune stampanti cablano il 5.
        for pin in (2, 5):
            # Un pin non cablato non è un errore: la stampante lo ignora
            # o solleva, e in entrambi i casi l'altro pin fa il lavoro.
            with contextlib.suppress(Exception):
                printer.cashdraw(pin)


def _set(printer, **kwargs) -> None:
    """``set()`` è opzionale nell'interfaccia: un oggetto che non ce l'ha
    stampa comunque, senza grassetto. Meglio di un ``AttributeError`` in mezzo
    a uno scontrino già mezzo uscito."""
    setter = getattr(printer, "set", None)
    if setter is None:
        return
    try:
        setter(**kwargs)
    except TypeError:
        setter()


def check_receipt(doc: CommercialDocument) -> list[Advisory]:
    """Rilievi sul documento. Non solleva mai, come :meth:`Invoice.check`."""
    out: list[Advisory] = []

    if not doc.lines:
        out.append(Advisory("receipt_no_lines", "Documento senza righe: non c'è niente da vendere."))

    if doc.payments and doc.paid() < doc.total():
        out.append(Advisory(
            "receipt_underpaid",
            f"Incassato {_money(doc.paid())} a fronte di {_money(doc.total())}: "
            "manca una tranche di pagamento, oppure il totale è sbagliato.",
        ))

    if doc.lottery_code:
        if not validate_lottery_code(doc.lottery_code):
            out.append(Advisory(
                "receipt_lottery_code_malformed",
                f"Codice lotteria {doc.lottery_code!r}: attesi 8 caratteri "
                "alfanumerici maiuscoli.",
            ))
        elif not doc.fully_electronic:
            # Stamparlo su un incasso in contanti promette al cliente una
            # partecipazione che non ci sarà.
            out.append(Advisory(
                "receipt_lottery_needs_electronic_payment",
                "Codice lotteria su uno scontrino non interamente elettronico: "
                "la lotteria degli scontrini richiede il pagamento cashless, e "
                "stamparlo qui promette una partecipazione che non avverrà.",
            ))

    if doc.lines:
        # Il confronto è sul TOTALE, non sull'imposta: i due calcoli possono
        # concordare al centesimo sull'IVA e discordare sull'imponibile, e il
        # numero che qualcuno noterà è quello in fondo allo scontrino.
        invoice_total = q2(doc.as_invoice_lines().total_document())
        if invoice_total != doc.total():
            delta = invoice_total - doc.total()
            out.append(Advisory(
                "receipt_invoice_total_drift",
                f"La fattura per queste stesse righe totalizzerebbe "
                f"{_money(invoice_total)} invece di {_money(doc.total())} "
                f"({delta:+.2f}): la cassa scorpora dal lordo, la fattura somma i "
                "netti di riga arrotondati. Nessuno dei due sbaglia, ma è il "
                "centesimo che non torna alla chiusura quando la stessa vendita "
                "finisce sia nei corrispettivi sia in fattura.",
            ))

    if doc.fiscal and not doc.rt_serial:
        out.append(Advisory(
            "receipt_fiscal_without_device",
            "Documento dichiarato fiscale ma senza matricola del registratore: "
            "un documento commerciale valido esce da un dispositivo omologato, "
            "e la matricola è come si dimostra quale.",
        ))
    return out
