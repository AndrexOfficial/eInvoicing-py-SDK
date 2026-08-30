"""Il punto cassa e la fattura, tenuti d'accordo.

Un registratore telematico e una fattura elettronica descrivono **la stessa
vendita** in due vocabolari che non si somigliano: l'RT ragiona per reparti IVA
e indici di pagamento, la FatturaPA per aliquote, `Natura` e codici
`ModalitaPagamento`. Nessuno dei due sa dell'altro, e il pacchetto finora
copriva solo il secondo.

Il costo di quel buco si vede in due posti precisi, entrambi trovati in un
prodotto reale:

**Il pagamento.** Emettere una fattura da un conto di ristorante richiede un
`ModalitaPagamento`, che è obbligatorio. Non avendo una tabella da consultare,
il codice metteva `MP05` — bonifico — su ogni fattura, anche quando il cliente
aveva pagato in contanti al banco. Il documento è valido, passa SdI e dice una
cosa falsa su come sono arrivati i soldi.

**Il documento commerciale.** Quando una vendita è già stata battuta sull'RT e
il cliente chiede la fattura dopo, la fattura deve **citare** quel documento:
è il riferimento che permette di scorporare il corrispettivo già trasmesso.
Senza, la stessa vendita risulta due volte.

Questo modulo non parla con nessuna stampante e non conosce nessun protocollo:
i driver Epson/Custom, l'ePOS-Print XML e la chiusura di cassa restano
correttamente nel prodotto, che è l'unico a sapere quale hardware ha in sala.
Qui c'è solo ciò che è **vero indipendentemente dal modello di stampante** —
la traduzione fra i due vocabolari, e le verifiche che dicono quando i due
documenti stanno raccontando storie diverse.

    from einvoice.pos import PosPaymentMethod, payment_means_for, ReceiptReference

    payment_means_for(PosPaymentMethod.CARD).code      # PaymentMeans.CARD (MP08)
    payment_means_for(PosPaymentMethod.MEAL_VOUCHER).exact   # False, e dice perché

    dc = ReceiptReference(number="0002-0041", date=date(2026, 8, 27), rt_serial="99MEY012345")
    link_receipt(invoice, dc)      # scrive la causale che cita il documento
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from .enums import PaymentMeans, VatNature
from .models import Advisory, DocumentReference, Invoice
from .money import D

__all__ = [
    "PosPaymentMethod",
    "PaymentMeansMapping",
    "PAYMENT_MEANS_BY_POS",
    "payment_means_for",
    "VatDepartment",
    "DepartmentTable",
    "ReceiptReference",
    "LOTTERY_CODE_PATTERN",
    "validate_lottery_code",
    "link_receipt",
    "check_pos_alignment",
]


class PosPaymentMethod(str, Enum):
    """Come un punto cassa distingue davvero un incasso.

    Volutamente più corto di :class:`~einvoice.enums.PaymentMeans`: un cassiere
    non sceglie fra RID veloce e domiciliazione postale. Le voci qui sono
    quelle che un RT stampa nella coda del documento commerciale e che un POS
    riporta a fine giornata.
    """

    CASH = "cash"
    CARD = "card"
    MEAL_VOUCHER = "meal_voucher"
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"
    BANKERS_DRAFT = "bankers_draft"
    DIRECT_DEBIT = "direct_debit"
    PAGOPA = "pagopa"
    #: Incassato in un secondo momento — «non riscosso» sull'RT.
    NOT_COLLECTED = "not_collected"
    OTHER = "other"


@dataclass(frozen=True)
class PaymentMeansMapping:
    """Il codice ``ModalitaPagamento`` per un incasso di cassa, e quanto è onesto.

    ``exact`` è il campo che conta. La lista MP01–MP23 è stata scritta per la
    fatturazione, non per la cassa, e per due modi di pagare molto comuni al
    banco — i buoni pasto e gli incassi da gateway — **non esiste un codice
    dedicato**. Restituire lo stesso oggetto in entrambi i casi renderebbe
    indistinguibile «questo è il codice giusto» da «questo è il meno sbagliato»,
    che è esattamente la differenza che un commercialista vorrebbe sapere.
    """

    code: PaymentMeans | None
    exact: bool = True
    note: str = ""


#: Incasso di cassa → ``ModalitaPagamento``.
#:
#: ``None`` non è un buco: significa **non emettere il blocco DatiPagamento**.
#: Una fattura non ancora incassata non ha una modalità di pagamento da
#: dichiarare, e inventarne una la farebbe risultare pagata.
PAYMENT_MEANS_BY_POS: dict[PosPaymentMethod, PaymentMeansMapping] = {
    PosPaymentMethod.CASH: PaymentMeansMapping(PaymentMeans.CASH),
    PosPaymentMethod.CARD: PaymentMeansMapping(PaymentMeans.CARD),
    PosPaymentMethod.BANK_TRANSFER: PaymentMeansMapping(PaymentMeans.BANK_TRANSFER),
    PosPaymentMethod.CHEQUE: PaymentMeansMapping(PaymentMeans.CHEQUE),
    PosPaymentMethod.BANKERS_DRAFT: PaymentMeansMapping(PaymentMeans.BANKERS_DRAFT),
    PosPaymentMethod.DIRECT_DEBIT: PaymentMeansMapping(PaymentMeans.SEPA_DD),
    PosPaymentMethod.PAGOPA: PaymentMeansMapping(PaymentMeans.PAGOPA),
    PosPaymentMethod.MEAL_VOUCHER: PaymentMeansMapping(
        PaymentMeans.CARD, exact=False,
        note="La lista MP non ha un codice per i buoni pasto. MP08 descrive il "
             "caso elettronico (card ticket); per i buoni cartacei c'è chi usa "
             "MP01. Scegli in accordo con il tuo commercialista e passa il "
             "codice esplicitamente.",
    ),
    PosPaymentMethod.OTHER: PaymentMeansMapping(
        None, exact=False,
        note="Nessun codice: «altro» non è una modalità di pagamento. Mappalo "
             "sul codice che descrive davvero l'incasso prima di emettere.",
    ),
    PosPaymentMethod.NOT_COLLECTED: PaymentMeansMapping(
        None,
        note="Non incassato: si omette il blocco DatiPagamento. Dichiarare una "
             "modalità farebbe risultare pagata una fattura che non lo è.",
    ),
}


def payment_means_for(method: PosPaymentMethod | str) -> PaymentMeansMapping:
    """Il codice ``ModalitaPagamento`` per un incasso di cassa.

    Un metodo sconosciuto non solleva: restituisce la mappatura di
    :attr:`PosPaymentMethod.OTHER`, che porta ``code=None`` e la nota che dice
    di scegliere davvero. Sollevare qui bloccherebbe l'emissione di una fattura
    per un valore che il prodotto potrebbe benissimo sapere gestire da solo.
    """
    try:
        key = PosPaymentMethod(method)
    except ValueError:
        return PAYMENT_MEANS_BY_POS[PosPaymentMethod.OTHER]
    return PAYMENT_MEANS_BY_POS[key]


@dataclass(frozen=True)
class VatDepartment:
    """Un reparto IVA della cassa.

    Il reparto è l'unica cosa che l'RT sa di un articolo: non conosce le
    aliquote per categoria merceologica, conosce «reparto 3». Se due reparti
    dichiarano la stessa aliquota, o se una riga di fattura usa un'aliquota che
    nessun reparto copre, lo scontrino e la fattura della stessa vendita
    smettono di quadrare — e se ne accorge il commercialista, mesi dopo.
    """

    index: int
    rate: Decimal
    nature: VatNature | None = None
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate", D(self.rate))


@dataclass
class DepartmentTable:
    """I reparti configurati su una cassa, con le domande che val la pena porgli."""

    departments: list[VatDepartment] = field(default_factory=list)

    def for_rate(self, rate: Decimal | str | int,
                 nature: VatNature | None = None) -> VatDepartment | None:
        """Il reparto per un'aliquota, o ``None``.

        ``None`` è una risposta, non un errore: dice al chiamante che quella
        vendita non è battibile su questa cassa così com'è configurata, il che
        è meglio che spedirla su un reparto qualunque.
        """
        wanted = D(rate)
        exact = [d for d in self.departments if d.rate == wanted and d.nature == nature]
        if exact:
            return exact[0]
        # Una Natura senza reparto dedicato cade sul reparto della stessa
        # aliquota, che è quasi sempre lo 0% generico: meglio del nulla, e il
        # rilievo sotto lo segnala comunque.
        same_rate = [d for d in self.departments if d.rate == wanted]
        return same_rate[0] if same_rate else None

    def check(self, invoice: Invoice | None = None) -> list[Advisory]:
        """Rilievi sulla configurazione, e su come regge questa fattura.

        Non solleva mai, come :meth:`einvoice.models.Invoice.check`: una cassa
        configurata male è un problema da mostrare, non un motivo per rifiutare
        di stampare.
        """
        out: list[Advisory] = []

        seen_index: dict[int, VatDepartment] = {}
        for dept in self.departments:
            if dept.index < 1:
                out.append(Advisory(
                    "pos_department_index",
                    f"Reparto {dept.index}: gli indici di reparto partono da 1.",
                ))
            if dept.index in seen_index:
                out.append(Advisory(
                    "pos_department_duplicate_index",
                    f"Reparto {dept.index} definito due volte "
                    f"({seen_index[dept.index].rate}% e {dept.rate}%): la cassa ne "
                    "userà uno solo e non è detto sia quello che ti aspetti.",
                ))
            seen_index[dept.index] = dept

        by_rate: dict[tuple[Decimal, VatNature | None], list[int]] = {}
        for dept in self.departments:
            by_rate.setdefault((dept.rate, dept.nature), []).append(dept.index)
        for (rate, _nature), indexes in sorted(by_rate.items(), key=lambda kv: kv[0][0]):
            if len(indexes) > 1:
                out.append(Advisory(
                    "pos_department_ambiguous_rate",
                    f"Aliquota {rate}% su più reparti ({', '.join(map(str, sorted(indexes)))}): "
                    "la stessa vendita finirà in reparti diversi a seconda di chi la batte, "
                    "e i totali per reparto non si riconcilieranno.",
                ))

        if invoice is not None:
            for summary in invoice.vat_summary():
                if self.for_rate(summary.vat_rate, summary.nature) is None:
                    out.append(Advisory(
                        "pos_rate_without_department",
                        f"Aliquota {summary.vat_rate}% presente in fattura ma su nessun "
                        "reparto della cassa: questa vendita non è battibile così com'è "
                        "configurata.",
                    ))
        return out


#: Il codice lotteria è alfanumerico maiuscolo di otto caratteri.
LOTTERY_CODE_PATTERN = re.compile(r"^[0-9A-Z]{8}$")


def validate_lottery_code(code: str | None) -> bool:
    """Forma del codice lotteria degli scontrini.

    Solo la forma. Che il codice esista davvero lo sa l'Agenzia, non noi, e
    fingere il contrario sarebbe la stessa bugia dei check digit inventati.
    """
    return bool(code and LOTTERY_CODE_PATTERN.match(code))


@dataclass(frozen=True)
class ReceiptReference:
    """Il documento commerciale che una fattura successiva deve citare.

    Quando la vendita è già stata battuta sull'RT, il corrispettivo è già stato
    trasmesso. La fattura emessa dopo descrive **la stessa** vendita: senza un
    riferimento che le colleghi, la contabilità conta due volte lo stesso
    incasso e lo scorporo del corrispettivo non ha su cosa appoggiarsi.
    """

    number: str
    date: date
    #: Matricola del registratore telematico che l'ha emesso.
    rt_serial: str | None = None
    lottery_code: str | None = None

    def to_causale(self) -> str:
        """La riga di causale che cita il documento.

        FatturaPA non ha un blocco dedicato al documento commerciale — i
        `DatiFattureCollegate` servono a collegare *fatture*. La prassi è
        citarlo in ``Causale`` (2.1.1.11), che è testo libero ripetibile e
        sopravvive intatto al giro di andata e ritorno. Il pacchetto produce la
        stringa e si ferma lì: dove metterla lo decide il prodotto, che è
        l'unico a sapere se quella causale è già occupata.
        """
        parts = [f"Documento commerciale n. {self.number} del {self.date:%d/%m/%Y}"]
        if self.rt_serial:
            parts.append(f"RT {self.rt_serial}")
        return " — ".join(parts)

    def as_document_reference(self) -> DocumentReference:
        """La forma neutra, per chi preferisce tenerla strutturata.

        ``kind="commercial_document"`` non è uno dei tipi che i renderer
        emettono: è deliberato. Un riferimento inventato dentro `DatiDDT` o
        `DatiFattureCollegate` sarebbe un documento che dichiara un
        collegamento che non esiste.
        """
        return DocumentReference(kind="commercial_document", doc_id=self.number, date=self.date)


def link_receipt(invoice: Invoice, receipt: ReceiptReference, *,
                 separator: str = " — ") -> Invoice:
    """Cita il documento commerciale nella causale della fattura.

    Modifica ``invoice`` sul posto e lo restituisce, così si incatena. Se una
    causale c'è già la nuova riga viene **accodata**, non sostituita: la
    descrizione della prestazione e il riferimento al corrispettivo servono
    entrambe, e sceglierne una sarebbe scegliere per il contribuente.

    Non tocca gli importi. Lo scorporo del corrispettivo già trasmesso si fa
    nella chiusura di cassa, non dentro la fattura.
    """
    line = receipt.to_causale()
    existing = (invoice.causale or "").strip()
    if line in existing:
        return invoice
    invoice.causale = f"{existing}{separator}{line}" if existing else line
    return invoice


def check_pos_alignment(invoice: Invoice, receipt: ReceiptReference | None = None, *,
                        departments: DepartmentTable | None = None) -> list[Advisory]:
    """Rilievi sul punto in cui cassa e fattura si toccano.

    Rilievi, non errori, per lo stesso motivo di :meth:`Invoice.check`: i regimi
    particolari esistono e un pacchetto che si rifiuta di emettere blocca
    fatture legittime. Non solleva mai.
    """
    out: list[Advisory] = []

    if receipt is not None:
        if receipt.to_causale() not in (invoice.causale or ""):
            out.append(Advisory(
                "pos_receipt_not_referenced",
                "La vendita è già stata battuta come documento commerciale "
                f"n. {receipt.number} ma la fattura non lo cita: il corrispettivo "
                "già trasmesso e questa fattura descrivono lo stesso incasso, e "
                "senza riferimento risulta due volte.",
            ))
        if receipt.lottery_code and not validate_lottery_code(receipt.lottery_code):
            out.append(Advisory(
                "pos_lottery_code_malformed",
                f"Codice lotteria {receipt.lottery_code!r}: attesi 8 caratteri "
                "alfanumerici maiuscoli.",
            ))
        if receipt.date > invoice.date:
            out.append(Advisory(
                "pos_receipt_after_invoice",
                f"Il documento commerciale è del {receipt.date:%d/%m/%Y}, dopo la "
                f"fattura del {invoice.date:%d/%m/%Y}: uno dei due ha la data sbagliata.",
            ))

    for payment in invoice.payments:
        if payment.means is None:
            out.append(Advisory(
                "pos_payment_means_missing",
                "Blocco di pagamento senza ModalitaPagamento: o si indica come è "
                "stato incassato, o si omette il blocco.",
            ))

    if departments is not None:
        out.extend(departments.check(invoice))
    return out
