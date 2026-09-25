"""Il PDF: la copia che una persona legge.

L'XML è il documento fiscale; il PDF è quello che si allega a una mail, si
consegna al banco e si ritrova in un archivio tre anni dopo. I due prodotti che
incorporano il pacchetto se lo erano costruito ognuno per conto proprio, con il
risultato prevedibile: due impaginazioni, due traduzioni delle stesse voci, e
due modi di sbagliare i totali.

    from einvoice.pdf import invoice_pdf, receipt_pdf

    open("fattura.pdf", "wb").write(invoice_pdf(invoice, logo="logo.png"))
    open("scontrino.pdf", "wb").write(receipt_pdf(documento))

Restituiscono **byte**, come :func:`~einvoice.build_fattura_xml`: dove finiscano
lo decide chi chiama. Un modulo che scrive file da sé è un modulo che va
riscritto la prima volta che il file deve andare su un bucket.

**La lingua.** Di default quella del paese di fatturazione, con la stessa regola
del resto del pacchetto: chi legge lo scontrino al banco legge la lingua del
posto, non quella di chi ha scritto il software. Si può forzare.

**La dipendenza.** ReportLab è un extra (``pip install einvoice[pdf]``), come
``cryptography`` per la firma: il core resta senza dipendenze, e chi non stampa
PDF non se lo porta dietro. Se manca, :class:`PdfUnavailable` lo dice —
distinguere «non è installato» da «il documento è rotto» è la stessa
distinzione che il modulo di firma fa da sempre, e per lo stesso motivo: la
prima è una questione di deploy, la seconda è un dato da correggere.
"""
from __future__ import annotations

import io
import os
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from .errors import EInvoiceError
from .i18n import locale_for_country, normalize_locale, translate
from .money import D, q2

if TYPE_CHECKING:  # pragma: no cover
    from .models import Invoice
    from .receipt import CommercialDocument

__all__ = ["PdfUnavailable", "PdfFontUnavailable", "PdfBranding",
           "invoice_pdf", "receipt_pdf", "quote_pdf", "proforma_pdf",
           "delivery_note_pdf", "document_pdf", "needs_unicode_font",
           "locales_without_font", "system_unicode_font", "font_for_text"]

#: Le etichette che i due renderer disegnano davvero. Il catalogo ne ha molte di
#: più — passi di setup, note — che in un PDF non entrano mai, e includerle
#: farebbe risultare «serve un font» anche dove non serve.
_PDF_LABEL_KEYS = (
    "doc.invoice", "doc.number", "doc.date", "doc.seller", "doc.buyer",
    "doc.description", "doc.quantity", "doc.unit_price", "doc.vat",
    "doc.line_total", "doc.taxable", "doc.total", "doc.payment", "doc.notes",
    "doc.kind.quote", "doc.kind.proforma", "doc.kind.delivery_note",
    "doc.kind.credit_note", "doc.kind.debit_note", "doc.valid_until",
    "doc.acceptance", "doc.proforma_disclaimer", "doc.due_date",
    "doc.withholding", "doc.stamp_duty", "doc.amount_due", "doc.references",
    "doc.ref.invoice", "doc.ref.delivery_note", "doc.ref.order", "doc.ref.contract",
    "doc.destination", "doc.transport_reason", "doc.transport_by", "doc.carrier",
    "doc.packages", "doc.goods_appearance", "doc.gross_weight", "doc.net_weight",
    "doc.transport_start", "doc.freight", "doc.code", "doc.unit",
    "doc.signature_driver", "doc.signature_carrier", "doc.signature_recipient",
    "doc.discount", "doc.surcharge", "transport_by.sender", "transport_by.recipient", "transport_by.carrier",
    "freight.paid", "freight.collect",
    *(f"transport_reason.{r}" for r in (
        "sale", "return", "approval", "processing", "consignment",
        "free_of_charge", "loan", "repair", "transfer", "other")),
    "receipt.commercial_document", "receipt.courtesy_copy", "receipt.not_fiscal",
    "receipt.change", "receipt.lottery", "receipt.device",
    *(f"pos_method.{m}" for m in (
        "cash", "card", "meal_voucher", "bank_transfer", "cheque",
        "bankers_draft", "direct_debit", "pagopa", "not_collected", "other")),
)


class PdfUnavailable(EInvoiceError, RuntimeError):
    """L'extra ``[pdf]`` non è installato su questo deploy.

    Distinta da un errore sui dati: qui il documento va benissimo, manca una
    libreria. Chi cattura questa può rispondere «PDF non disponibile su questo
    server» e continuare a emettere l'XML, che è la parte fiscale.
    """


class PdfFontUnavailable(EInvoiceError, RuntimeError):
    """Il documento contiene caratteri che il font in uso non sa disegnare.

    Distinta da :class:`PdfUnavailable`, che riguarda la libreria: qui ReportLab
    c'è, il documento è valido, e manca un font.

    È un errore e non un ripiego silenzioso perché il ripiego silenzioso c'era e
    faceva danni: i font base di ReportLab sono Latin-1, e un nome greco, russo
    o arabo usciva stampato come una fila di punti interrogativi. Una copia di
    cortesia con al posto del nome del cliente è peggio di una copia che non
    esce — quella almeno si nota.

    Si risolve passando un font Unicode:
    ``PdfBranding(font_path="DejaVuSans.ttf")``.
    """


@dataclass
class PdfBranding:
    """Il vestito dell'azienda sul documento.

    ``logo`` accetta un percorso o i byte dell'immagine: chi lo tiene su disco
    e chi lo tiene su un bucket non devono scrivere codice diverso.
    """

    logo: str | bytes | os.PathLike | None = None
    #: Larghezza massima del logo in millimetri. L'altezza segue le proporzioni.
    logo_width_mm: float = 35.0
    #: Righe sotto l'intestazione: indirizzo, contatti, iscrizione REA.
    footer_lines: tuple[str, ...] = ()
    #: Un TrueType Unicode da usare al posto dei font base.
    #:
    #: Serve per tutto ciò che esce da Latin-1 — greco, cirillico, arabo, CJK,
    #: thai — cioè per buona parte delle trentuno lingue in cui il pacchetto sa
    #: già scrivere le etichette. ReportLab non ne spedisce uno adatto (nemmeno
    #: Vera, che si ferma al latino), quindi il file lo mette chi stampa:
    #: ``DejaVuSans.ttf`` è la scelta abituale.
    font_path: str | os.PathLike | None = None


def _reportlab():
    """Importa ReportLab, o spiega che manca."""
    try:
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except ModuleNotFoundError as exc:  # pragma: no cover - dipende dal deploy
        raise PdfUnavailable(
            "La generazione PDF richiede l'extra [pdf]: pip install einvoice[pdf]"
        ) from exc
    return canvas, mm


def _logo_reader(branding: PdfBranding | None):
    """Il logo come oggetto disegnabile, o ``None``.

    Un logo illeggibile **non** ferma il documento: si stampa senza. Una fattura
    che non esce perché il PNG è corrotto è un danno peggiore di una fattura
    senza marchio, e il chiamante non ha modo di accorgersene prima.
    """
    if branding is None or branding.logo is None:
        return None
    try:
        from reportlab.lib.utils import ImageReader

        source: Any = branding.logo
        if isinstance(source, bytes):
            # ImageReader vuole un percorso o un file-like: i byte nudi li
            # accetta solo così, ed è il caso di chi tiene il logo su un bucket.
            source = io.BytesIO(source)
        return ImageReader(source)
    except Exception:
        return None


def _draw_logo(pdf, reader, branding: PdfBranding, x: float, top: float, mm: float) -> float:
    """Disegna il logo e restituisce quanto spazio verticale ha occupato.

    Anche qui l'immagine rotta non ferma il documento, e non è una ripetizione
    del controllo in :func:`_logo_reader`: ``ImageReader`` si costruisce
    volentieri su byte che poi non sa decodificare, e l'errore arriva al
    momento del disegno — cioè a documento già iniziato. Proteggere solo la
    costruzione lasciava scoperto proprio il caso per cui la protezione
    esisteva.
    """
    if reader is None:
        return 0.0
    try:
        width_px, height_px = reader.getSize()
        width = branding.logo_width_mm * mm
        height = width * (height_px / width_px) if width_px else 0
        pdf.drawImage(reader, x, top - height, width=width, height=height,
                      mask="auto", preserveAspectRatio=True, anchor="nw")
    except Exception:
        return 0.0
    return height


@lru_cache(maxsize=1)
def locales_without_font() -> frozenset[str]:
    """Le lingue in cui un PDF esce leggibile **senza** passare un font.

    Calcolata, non scritta a mano: se una traduzione cambia e introduce una
    lettera fuori da Latin-1, l'insieme si aggiorna da sé. Una lista fissa
    direbbe di sì a una lingua che nel frattempo ha smesso di esserlo.

    Oggi sono quattordici su trentuno — le altre diciassette (greco, cirillico,
    arabo, CJK, thai e tutto il latino esteso: polacco, ceco, ungherese,
    rumeno, baltico, maltese…) hanno bisogno di
    :attr:`PdfBranding.font_path`.
    """
    from .i18n import LOCALES, translate

    safe = set()
    for locale in LOCALES:
        text = "".join(translate(key, locale) for key in _PDF_LABEL_KEYS)
        if not _missing_glyphs([text], None):
            safe.add(locale)
    return frozenset(safe)


def needs_unicode_font(locale: str | None) -> bool:
    """Se stampare in questa lingua richiede un font Unicode.

    Da chiamare in configurazione, non al momento di stampare: sapere in
    anticipo che per il greco serve un file permette di procurarlo, mentre
    scoprirlo quando il cliente chiede la copia significa non dargliela.
    """
    from .i18n import normalize_locale

    return normalize_locale(locale) not in locales_without_font()


#: Dove cercare un font Unicode quando il chiamante non ne indica uno.
#:
#: Sono i percorsi dei pacchetti di sistema, non font impacchettati qui: un TTF
#: nel wheel sarebbero 700 KB per un caso che la maggior parte delle
#: installazioni non incontra, e una licenza in più da portarsi dietro. Su
#: un'immagine Debian basta ``fonts-dejavu-core``.
SYSTEM_FONT_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/local/share/fonts/DejaVuSans.ttf",
    # Noto copre quello che DejaVu non copre: CJK e thai.
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:\\Windows\\Fonts\\arialuni.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
)


@lru_cache(maxsize=1)
def system_unicode_font() -> str | None:
    """Il primo font Unicode di sistema, se ce n'è uno.

    Serve perché il pacchetto scrive le etichette in trentuno lingue: pretendere
    che ogni chiamante sappia di dover procurare un font per stampare in greco
    significa che in greco non stampa nessuno. Dove il font c'è — ed è il caso
    di quasi ogni immagine Linux con ``fonts-dejavu-core`` — funziona senza che
    nessuno debba saperlo.

    Resta un ripiego, non una garanzia: `PdfBranding.font_path` ha la
    precedenza, e dove non c'è nulla si solleva invece di stampare punti
    interrogativi.
    """
    return next((path for path in SYSTEM_FONT_CANDIDATES if os.path.isfile(path)), None)


def _load_font(path: str | os.PathLike, *, required: bool) -> str | None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    name = f"einvoice-{os.path.basename(str(path))}"
    if name not in pdfmetrics.getRegisteredFontNames():
        try:
            pdfmetrics.registerFont(TTFont(name, str(path)))
        except Exception as exc:
            if required:
                raise PdfFontUnavailable(f"Font non caricabile: {path} ({exc})") from exc
            # Un font di sistema illeggibile non è un errore del chiamante: si
            # torna ai font base, e se il documento ne aveva bisogno lo dirà il
            # controllo di copertura.
            return None
    return name


def font_for_text(texts: Iterable[str], *,
                  font_path: str | os.PathLike | None = None) -> str | None:
    """Il nome del font ReportLab con cui disegnare questi testi, o ``None``.

    ``None`` significa «i font base bastano»: usa ``Helvetica`` e derivati.
    Altrimenti torna un font già **registrato** in ReportLab, pronto per
    ``canvas.setFont``.

    Serve a chi disegna un PDF proprio invece di usare :func:`invoice_pdf` — un
    layout di ripiego, una ricevuta su misura. Senza, ogni prodotto ricasca nel
    difetto che questo modulo ha appena chiuso: `Helvetica` cablata e il nome
    del cliente stampato come `???` appena esce da Latin-1, senza che niente
    fallisca.

        font = font_for_text([restaurant.name, customer.name])
        c.setFont(font or "Helvetica", 10)

    Solleva :class:`PdfFontUnavailable` se nessun font disponibile copre i
    testi: chi disegna a mano vuole saperlo prima di aprire la pagina, per gli
    stessi motivi per cui lo vuole sapere :func:`invoice_pdf`.
    """
    return _resolve_font(texts, PdfBranding(font_path=font_path) if font_path else None)


def _missing_glyphs(texts: Iterable[str], font: str | None) -> set[str]:
    """I caratteri che questo font non sa disegnare. Non solleva: risponde."""
    missing: set[str] = set()
    if font is None:
        # I font base di ReportLab si disegnano in **WinAnsi (CP1252)**, non in
        # Latin-1: la differenza non è accademica, perché è lì che sta l'euro.
        # `ord(ch) > 0xFF` avrebbe dichiarato indisegnabile il simbolo `€`
        # (U+20AC) — cioè avrebbe rifiutato di stampare un normalissimo
        # scontrino italiano su un'immagine senza font di sistema. Si chiede
        # alla codifica invece di indovinare dal punto di codice.
        for text in texts:
            for ch in text:
                try:
                    ch.encode("cp1252")
                except UnicodeEncodeError:
                    missing.add(ch)
        return missing

    from reportlab.pdfbase import pdfmetrics

    face = getattr(pdfmetrics.getFont(font), "face", None)
    cmap = getattr(face, "charToGlyph", None)
    if cmap is None:
        return missing
    for text in texts:
        missing.update(ch for ch in text if ord(ch) not in cmap and not ch.isspace())
    return missing


def _resolve_font(texts: Iterable[str], branding: PdfBranding | None) -> str | None:
    """Il font con cui disegnare questo documento — scelto, non trovato.

    Prendere il primo font di sistema disponibile non basta: DejaVu, che è
    quello che quasi ogni immagine Linux ha, copre latino, greco, cirillico e
    arabo ma **non** CJK e **non** thai. Un prodotto con l'interfaccia in
    giapponese avrebbe trovato un font, l'avrebbe usato, e avrebbe stampato
    caselle vuote: esattamente il difetto di prima con un passaggio in più.
    Quindi si prova la copertura e si passa al candidato successivo.

    La verifica si fa **prima** di aprire la pagina: un errore a documento
    iniziato lascia un PDF troncato, che è il modo peggiore di fallire.
    """
    texts = list(texts)

    if branding is not None and branding.font_path is not None:
        # Una scelta esplicita non si scavalca: se non basta, lo si dice.
        name = _load_font(branding.font_path, required=True)
        missing = _missing_glyphs(texts, name)
        if missing:
            raise PdfFontUnavailable(
                f"Il font indicato ({branding.font_path}) non sa disegnare "
                f"{_sample(missing)}. Serve un font che copra questo alfabeto."
            )
        return name

    if not _missing_glyphs(texts, None):
        # Tutto dentro Latin-1: i font base bastano e il PDF resta più leggero.
        return None

    tried: list[str] = []
    for path in SYSTEM_FONT_CANDIDATES:
        if not os.path.isfile(path):
            continue
        name = _load_font(path, required=False)
        if name is None:
            continue
        tried.append(os.path.basename(path))
        if not _missing_glyphs(texts, name):
            return name

    missing = _missing_glyphs(texts, None)
    trovati = f" Provati senza successo: {', '.join(tried)}." if tried else \
        " Nessun font Unicode di sistema trovato."
    raise PdfFontUnavailable(
        f"Il documento contiene caratteri che nessun font disponibile sa "
        f"disegnare: {_sample(missing)}.{trovati} "
        "Passa un TrueType che copra questo alfabeto con "
        "PdfBranding(font_path='DejaVuSans.ttf'), oppure installalo nel sistema "
        "(su Debian: fonts-dejavu-core per latino/greco/cirillico/arabo, "
        "fonts-noto-cjk per giapponese e cinese, fonts-noto-core per il thai). "
        "Senza, al posto del testo uscirebbero punti interrogativi."
    )


def _sample(missing: set[str]) -> str:
    return repr("".join(sorted(missing)[:12]))


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}".replace(",", " ")


def _resolve_locale(explicit: str | None, country: str | None) -> str:
    return normalize_locale(explicit) if explicit else locale_for_country(country or "IT")


#: ModalitaPagamento → the words a customer reads. The code stays beside the
#: word — an accountant matches on "MP05", a person on «Bonifico».
_PAYMENT_LABEL_KEY = {
    "MP01": "cash", "MP04": "cash", "MP02": "cheque", "MP03": "bankers_draft",
    "MP05": "bank_transfer", "MP15": "bank_transfer", "MP08": "card",
    "MP09": "direct_debit", "MP10": "direct_debit", "MP11": "direct_debit",
    "MP16": "direct_debit", "MP17": "direct_debit", "MP19": "direct_debit",
    "MP20": "direct_debit", "MP21": "direct_debit", "MP23": "pagopa",
}

_REF_KEY = {"invoice": "doc.ref.invoice", "ddt": "doc.ref.delivery_note",
            "order": "doc.ref.order", "contract": "doc.ref.contract"}

_TOP = 275.0          # mm: first baseline of a page
_BOTTOM = 32.0        # mm: below this a new page starts (room for the footer)


def _date(value) -> str:
    return f"{value:%d/%m/%Y}" if value else ""


def _payment_text(payment, t) -> str:
    """«Bonifico (MP05) · Scadenza 30/09/2026 · IBAN IT60X…»."""
    code = payment.means.value
    word = t(f"pos_method.{_PAYMENT_LABEL_KEY.get(code, 'other')}")
    parts = [f"{word} ({code})"]
    if payment.due_date:
        parts.append(f"{t('doc.due_date')} {_date(payment.due_date)}")
    account = getattr(payment, "account", None)
    if account is not None and account.iban:
        parts.append(f"IBAN {''.join(account.iban.split()).upper()}")
        if account.bic:
            parts.append(f"BIC {account.bic}")
    return " · ".join(parts)


def _reference_text(refs, t) -> str:
    """«Fattura N. 12 — 01/09/2026; DDT N. 3 — 28/08/2026»."""
    out = []
    for ref in refs:
        label = t(_REF_KEY[ref.kind]) if ref.kind in _REF_KEY else ref.kind
        out.append(" ".join(p for p in (label, t("doc.number"), ref.doc_id,
                                        f"— {_date(ref.date)}" if ref.date else "") if p))
    return "; ".join(out)


def _party_rows(party, home: str | None = None) -> list[str]:
    """What identifies a party on paper: name, address, tax identifiers.

    The country is printed when the address is abroad from ``home`` (the
    seller's country): a cross-border buyer without it is an address the
    courier cannot use.
    """
    rows = [party.display_name() if hasattr(party, "display_name") else party.name]
    address = getattr(party, "address", None)
    if address is not None:
        if getattr(address, "street", None):
            rows.append(address.street)
        town = " ".join(str(x) for x in (address.postcode, address.city) if x)
        if getattr(address, "province", None):
            town = f"{town} ({address.province})"
        if home and address.country and address.country != home:
            town = f"{town} — {address.country}"
        if town.strip():
            rows.append(town.strip())
    ids = []
    if party.vat_number:
        bare = party.normalized_vat() if hasattr(party, "normalized_vat") else party.vat_number
        ids.append(f"{party.country_code} {bare}")
    if getattr(party, "tax_code", None) and party.tax_code != party.vat_number:
        ids.append(party.tax_code)
    if ids:
        rows.append(" · ".join(ids))
    return [r for r in rows if r]


class _Sheet:
    """A4 pages with a cursor: text that does not fit starts a new page.

    The table header is redrawn on every page it continues onto — a second page
    of numbers without column names is a page nobody can read.
    """

    def __init__(self, pdf, mm, fonts, branding):
        self.pdf, self.mm = pdf, mm
        self.body, self.bold = fonts
        self.branding = branding
        self.left, self.right = 18 * mm, 192 * mm
        self.y = _TOP * mm
        self.on_new_page = None

    def ensure(self, height_mm: float) -> None:
        if self.y - height_mm * self.mm < _BOTTOM * self.mm:
            _draw_footer(self.pdf, self.branding, self.left, self.mm, self.body)
            self.pdf.showPage()
            self.y = _TOP * self.mm
            if self.on_new_page is not None:
                self.on_new_page()

    def down(self, step_mm: float) -> None:
        self.y -= step_mm * self.mm

    def text(self, value: str, *, size: float = 9, bold: bool = False,
             x: float | None = None, width_mm: float | None = None,
             leading_mm: float = 4.2) -> None:
        """Wrapped text at the cursor; the cursor moves below it."""
        from reportlab.lib.utils import simpleSplit

        font = self.bold if bold else self.body
        x = self.left if x is None else x
        width = (width_mm * self.mm) if width_mm else (self.right - x)
        for row in simpleSplit(value, font, size, width) or [""]:
            self.ensure(leading_mm)
            self.pdf.setFont(font, size)
            self.pdf.drawString(x, self.y, row)
            self.down(leading_mm)

    def labelled(self, label: str, value: str, *, size: float = 8.5) -> None:
        self.text(f"{label}: {value}", size=size)

    def finish(self) -> None:
        _draw_footer(self.pdf, self.branding, self.left, self.mm, self.body)
        self.pdf.showPage()


def _open(branding: PdfBranding | None, logo, texts: list[str]):
    canvas, mm = _reportlab()
    if branding is None:
        branding = PdfBranding(logo=logo)
    elif logo is not None:
        branding = PdfBranding(logo=logo, logo_width_mm=branding.logo_width_mm,
                               footer_lines=branding.footer_lines,
                               font_path=branding.font_path)
    custom_font = _resolve_font([*texts, *branding.footer_lines], branding)
    fonts = (custom_font or "Helvetica", custom_font or "Helvetica-Bold")
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(210 * mm, 297 * mm))
    return buffer, _Sheet(pdf, mm, fonts, branding)


def _heading(sheet: _Sheet, title: str, meta: list[str], subtitle: str | None = None) -> None:
    """Logo, title on the left, number/date/validity on the right."""
    mm = sheet.mm
    logo_height = _draw_logo(sheet.pdf, _logo_reader(sheet.branding), sheet.branding,
                             sheet.left, sheet.y, mm)
    if logo_height:
        sheet.down(logo_height / mm + 6)
    sheet.pdf.setFont(sheet.bold, 16)
    sheet.pdf.drawString(sheet.left, sheet.y, title)
    top = sheet.y
    sheet.pdf.setFont(sheet.body, 10)
    for row in meta:
        sheet.pdf.drawRightString(sheet.right, sheet.y, row)
        sheet.down(5)
    if subtitle:
        sheet.pdf.setFont(sheet.body, 8)
        sheet.pdf.drawString(sheet.left, top - 5 * mm, subtitle)
    sheet.y = min(sheet.y, top - 5 * mm) - 6 * mm


def _parties(sheet: _Sheet, blocks: list[tuple[str, list[str]]]) -> None:
    for label, rows in blocks:
        sheet.ensure(4.5 + 4.2 * len(rows))
        sheet.text(label, size=9, bold=True, leading_mm=4.5)
        for row in rows:
            sheet.text(row, size=9)
        sheet.down(3)


_COLUMNS_PRICED = (("doc.description", 0, "l"), ("doc.quantity", 104, "r"),
                   ("doc.unit_price", 128, "r"), ("doc.vat", 144, "r"),
                   ("doc.line_total", 174, "r"))


def _table(sheet: _Sheet, t, columns, rows: list[tuple[str, list[str]]],
           description_width_mm: float) -> None:
    """``rows`` = (description, [the other cells, right-aligned])."""
    mm = sheet.mm

    def header() -> None:
        sheet.pdf.setFont(sheet.bold, 8)
        for key, offset, align in columns:
            x = sheet.left + offset * mm
            (sheet.pdf.drawString if align == "l" else sheet.pdf.drawRightString)(x, sheet.y, t(key))
        sheet.down(2)
        sheet.pdf.line(sheet.left, sheet.y, sheet.right, sheet.y)
        sheet.down(5)

    sheet.ensure(12)
    header()
    sheet.on_new_page = header
    from reportlab.lib.utils import simpleSplit

    for description, cells in rows:
        wrapped = simpleSplit(description, sheet.body, 8, description_width_mm * mm) or [""]
        sheet.ensure(4.6 * len(wrapped))
        sheet.pdf.setFont(sheet.body, 8)
        for (_, offset, _align), cell in zip(columns[1:], cells, strict=True):
            sheet.pdf.drawRightString(sheet.left + offset * mm, sheet.y, cell)
        desc_x = sheet.left + columns[0][1] * mm
        for i, row in enumerate(wrapped):
            if i:
                sheet.ensure(4.2)
            sheet.pdf.drawString(desc_x, sheet.y, row)
            sheet.down(4.2 if i < len(wrapped) - 1 else 4.6)
    sheet.on_new_page = None


def _totals(sheet: _Sheet, t, doc, currency: str) -> None:
    mm = sheet.mm
    label_x = sheet.left + 144 * mm
    stamp = D(doc.stamp_duty) if doc.stamp_duty else None
    withheld = doc.withholding_total() if doc.withholdings else None
    rows = [(t("doc.surcharge" if ac.is_charge else "doc.discount")
             + (f" — {ac.reason}" if ac.reason else ""), q2(ac.signed), False)
            for ac in doc.allowances_charges]
    rows += [(t("doc.taxable"), doc.taxable_total(), False),
             (t("doc.vat"), doc.tax_total(), False)]
    if stamp:
        rows.append((t("doc.stamp_duty"), q2(stamp), False))
    rows.append((t("doc.total"), q2(doc.total_document()), True))
    if withheld:
        rows.append((t("doc.withholding"), -withheld, False))
        rows.append((t("doc.amount_due"), q2(doc.total_payable()), True))
    sheet.ensure(8 + 5.5 * len(rows))
    sheet.down(1)
    sheet.pdf.line(sheet.left + 110 * mm, sheet.y, sheet.right, sheet.y)
    sheet.down(6)
    for label, amount, strong in rows:
        sheet.pdf.setFont(sheet.bold if strong else sheet.body, 11 if strong else 9)
        sheet.pdf.drawRightString(label_x, sheet.y, label)
        suffix = f" {currency}" if strong else ""
        sheet.pdf.drawRightString(sheet.right, sheet.y, f"{_money(amount)}{suffix}")
        sheet.down(6 if strong else 5)
    sheet.down(4)


def _rate(value: Decimal) -> str:
    """``10`` for 10, 10.0 and 10.00 alike; ``5.5`` stays ``5.5``."""
    text = f"{D(value).normalize():f}"
    return f"{text}%"


def _priced_rows(lines, t) -> list[tuple[str, list[str]]]:
    """One row per line, and one under it per discount or surcharge.

    Without the discount row a reader sees 12 × 38.00 next to 432.00 and has
    no way to tell a discount from an arithmetic error.
    """
    rows: list[tuple[str, list[str]]] = []
    for ln in lines:
        # With a discount the line shows quantity × price and the discount row
        # below it, so the column adds up to the taxable amount; showing the
        # net total above a "−24.00" read as a second deduction.
        amount = q2(ln.unit_price * ln.quantity) if ln.discounts else ln.total
        rows.append((ln.description, [f"{ln.quantity:g}", _money(q2(ln.unit_price)),
                                      _rate(ln.vat_rate), _money(amount)]))
        rows.extend(_discount_rows(ln, t, 4))
    return rows


def _discount_rows(line, t, blank_cells: int) -> list[tuple[str, list[str]]]:
    out = []
    for d in line.discounts:
        label = t("doc.surcharge" if d.is_charge else "doc.discount")
        text = f"— {label}" + (f" {d.reason}" if d.reason else "")
        out.append((text, [""] * (blank_cells - 1) + [_money(q2(d.signed))]))
    return out


def _priced_texts(t, doc, extra: list[str]) -> list[str]:
    """Every string a priced document will draw — asked of the font first."""
    return [
        *(t(k) for k in _PDF_LABEL_KEYS),
        *(row for party in (doc.seller, doc.buyer)
          for row in _party_rows(party, doc.seller.country_code)),
        *(ln.description for ln in doc.lines),
        doc.number, getattr(doc, "causale", None) or "", getattr(doc, "notes", None) or "",
        doc.currency, *extra,
    ]


def _priced_pdf(doc, *, title: str, meta: list[str], closing: list[str],
                acceptance: bool, branding, logo, locale) -> bytes:
    lang = _resolve_locale(locale, doc.seller.country_code)

    def t(key: str) -> str:
        return translate(key, lang)

    references = _reference_text(getattr(doc, "references", []), t)
    payments = [_payment_text(p, t) for p in doc.payments]
    buffer, sheet = _open(branding, logo, _priced_texts(t, doc, [
        title, *meta, *closing, references, *payments]))
    _heading(sheet, title, meta)
    home = doc.seller.country_code
    _parties(sheet, [(t("doc.seller"), _party_rows(doc.seller, home)),
                     (t("doc.buyer"), _party_rows(doc.buyer, home))])
    if references:
        sheet.labelled(t("doc.references"), references)
        sheet.down(2)
    _table(sheet, t, _COLUMNS_PRICED, _priced_rows(doc.lines, t), description_width_mm=84)
    _totals(sheet, t, doc, doc.currency)
    for payment in payments:
        sheet.labelled(t("doc.payment"), payment)
    causale = getattr(doc, "causale", None)
    if causale:
        sheet.labelled(t("doc.notes"), causale)
    notes = getattr(doc, "notes", None)
    if notes:
        # Terms and conditions of an offer: a paragraph, not a «Causale».
        sheet.down(2)
        sheet.text(notes, size=8.5)
    if acceptance:
        sheet.ensure(22)
        sheet.down(10)
        sheet.text(t("doc.acceptance"), size=9)
        sheet.down(6)
        sheet.pdf.line(sheet.left, sheet.y, sheet.left + 80 * sheet.mm, sheet.y)
        sheet.down(4)
    for row in closing:
        sheet.down(2)
        sheet.text(row, size=8.5, bold=True)
    sheet.finish()
    sheet.pdf.save()
    return buffer.getvalue()


def invoice_pdf(invoice: Invoice, *, branding: PdfBranding | None = None,
                logo: str | bytes | os.PathLike | None = None,
                locale: str | None = None) -> bytes:
    """La fattura — o la nota di credito, o di debito — come PDF A4.

    Non è il documento fiscale — quello è l'XML — ed è la copia leggibile che
    gli sta accanto. I numeri vengono da :meth:`~einvoice.Invoice.vat_summary`,
    gli stessi che finiscono nell'XML: ricalcolarli qui avrebbe prodotto un PDF
    che dice una cifra e un XML che ne dice un'altra sulla stessa vendita.

    The title follows the document type: a credit note used to come out
    headed «FATTURA», which is the one word it must not carry.
    """
    lang = _resolve_locale(locale, invoice.seller.country_code)
    if invoice.document_type.is_credit_note:
        key = "doc.kind.credit_note"
    elif invoice.document_type.is_debit_note:
        key = "doc.kind.debit_note"
    else:
        key = "doc.invoice"
    meta = [f'{translate("doc.number", lang)} {invoice.number}',
            f'{translate("doc.date", lang)}: {_date(invoice.date)}']
    return _priced_pdf(invoice, title=translate(key, lang), meta=meta, closing=[],
                       acceptance=False, branding=branding, logo=logo, locale=lang)


def quote_pdf(quote, *, branding: PdfBranding | None = None,
              logo: str | bytes | os.PathLike | None = None,
              locale: str | None = None) -> bytes:
    """Il preventivo: le stesse righe e gli stessi totali della fattura che
    diventerà, la validità, e lo spazio per l'accettazione."""
    lang = _resolve_locale(locale, quote.seller.country_code)
    meta = [f'{translate("doc.number", lang)} {quote.number}',
            f'{translate("doc.date", lang)}: {_date(quote.date)}']
    if quote.valid_until:
        meta.append(f'{translate("doc.valid_until", lang)}: {_date(quote.valid_until)}')
    return _priced_pdf(quote, title=translate("doc.kind.quote", lang), meta=meta,
                       closing=[], acceptance=True, branding=branding, logo=logo, locale=lang)


def proforma_pdf(proforma, *, branding: PdfBranding | None = None,
                 logo: str | bytes | os.PathLike | None = None,
                 locale: str | None = None) -> bytes:
    """La pro forma, con la dichiarazione che non è una fattura — scritta sul
    documento, non affidata a chi lo consegna."""
    lang = _resolve_locale(locale, proforma.seller.country_code)
    meta = [f'{translate("doc.number", lang)} {proforma.number}',
            f'{translate("doc.date", lang)}: {_date(proforma.date)}']
    return _priced_pdf(proforma, title=translate("doc.kind.proforma", lang), meta=meta,
                       closing=[translate("doc.proforma_disclaimer", lang)],
                       acceptance=False, branding=branding, logo=logo, locale=lang)


_Column = tuple[str, int, str]
_COLUMNS_DDT: tuple[_Column, ...] = (("doc.code", 0, "l"), ("doc.description", 26, "l"),
                                     ("doc.unit", 140, "r"), ("doc.quantity", 174, "r"))
_COLUMNS_DDT_PRICED: tuple[_Column, ...] = (("doc.code", 0, "l"), ("doc.description", 22, "l"),
                       ("doc.unit", 96, "r"), ("doc.quantity", 110, "r"),
                       ("doc.unit_price", 132, "r"), ("doc.vat", 146, "r"),
                       ("doc.line_total", 174, "r"))


def delivery_note_pdf(note, *, branding: PdfBranding | None = None,
                      logo: str | bytes | os.PathLike | None = None,
                      locale: str | None = None) -> bytes:
    """Il DDT: chi, cosa, quanto, come viaggia — e le firme.

    The layout every Italian delivery note has, because it answers the
    questions a driver stopped at a check and a warehouse receiving the goods
    both ask: sender and recipient, destination, reason, who carries it,
    packages, weight, appearance, when the transport started. Prices appear
    only on a *DDT valorizzato*, where every line has one.
    """
    lang = _resolve_locale(locale, note.seller.country_code)

    def t(key: str) -> str:
        return translate(key, lang)

    transport = note.transport
    carrier = transport.carrier
    reason = t(f"transport_reason.{transport.reason.value}")
    if transport.reason_text:
        reason = (transport.reason_text if transport.reason.value == "other"
                  else f"{reason} — {transport.reason_text}")
    info = [(t("doc.transport_reason"), reason),
            (t("doc.transport_by"), t(f"transport_by.{transport.by.value}"))]
    if transport.freight is not None:
        info.append((t("doc.freight"), t(f"freight.{transport.freight.value}")))
    if transport.start is not None:
        info.append((t("doc.transport_start"), f"{transport.start:%d/%m/%Y %H:%M}"))
    if transport.packages is not None:
        info.append((t("doc.packages"), str(transport.packages)))
    if transport.goods_appearance:
        info.append((t("doc.goods_appearance"), transport.goods_appearance))
    unit = transport.weight_unit or ""
    if transport.gross_weight is not None:
        info.append((t("doc.gross_weight"), f"{transport.gross_weight:f} {unit}".strip()))
    if transport.net_weight is not None:
        info.append((t("doc.net_weight"), f"{transport.net_weight:f} {unit}".strip()))
    if transport.means:
        info.append(("", transport.means))
    if transport.incoterm:
        info.append(("Incoterms", transport.incoterm))

    home = note.seller.country_code
    blocks = [(t("doc.seller"), _party_rows(note.seller, home)),
              (t("doc.buyer"), _party_rows(note.buyer, home))]
    if transport.delivery_address is not None:
        a = transport.delivery_address
        rows = [a.street, " ".join(x for x in (a.postcode, a.city) if x)
                + (f" ({a.province})" if a.province else "")]
        blocks.append((t("doc.destination"), [r for r in rows if r]))
    if carrier is not None:
        blocks.append((t("doc.carrier"), _party_rows(carrier, home) + (
            [carrier.license_number] if carrier.license_number else [])))

    priced = bool(note.lines) and all(ln.priced for ln in note.lines)
    code_of: list[str] = []
    if priced:
        columns = _COLUMNS_DDT_PRICED
        table_rows = []
        for ln in note.lines:
            amount = q2(ln.unit_price * ln.quantity) if ln.discounts else ln.total
            table_rows.append((ln.description, [ln.unit_of_measure or "", f"{ln.quantity:g}",
                                                _money(q2(ln.unit_price)), _rate(ln.vat_rate),
                                                _money(amount)]))
            code_of.append(ln.article_code or "")
            for row in _discount_rows(ln, t, 5):
                table_rows.append(row)
                code_of.append("")
        width = 72.0
    else:
        columns = _COLUMNS_DDT
        table_rows = [(ln.description, [ln.unit_of_measure or "", f"{ln.quantity:g}"])
                      for ln in note.lines]
        code_of = [ln.article_code or "" for ln in note.lines]
        width = 110.0
    references = _reference_text(note.references, t)
    signatures = [t("doc.signature_driver"), t("doc.signature_carrier"),
                  t("doc.signature_recipient")]
    title = t("doc.kind.delivery_note")
    meta = [f'{t("doc.number")} {note.number}', f'{t("doc.date")}: {_date(note.date)}']
    legal = "D.P.R. 472/1996" if note.seller.country_code == "IT" else None

    texts = [title, *meta, *(t(k) for k in _PDF_LABEL_KEYS), references, *signatures,
             *(f"{a}: {b}" for a, b in info), *(r for _, rows in blocks for r in rows),
             *(ln.description for ln in note.lines), *(ln.article_code or "" for ln in note.lines),
             *(ln.unit_of_measure or "" for ln in note.lines), note.notes or ""]
    buffer, sheet = _open(branding, logo, texts)
    _heading(sheet, title, meta, subtitle=legal)
    _parties(sheet, blocks)
    for label, value in info:
        sheet.text(f"{label}: {value}" if label else value, size=8.5)
    sheet.down(2)
    if references:
        sheet.labelled(t("doc.references"), references)
        sheet.down(2)

    mm = sheet.mm
    rows_with_code = [(description, cells, code)
                      for (description, cells), code in zip(table_rows, code_of, strict=True)]

    def header() -> None:
        sheet.pdf.setFont(sheet.bold, 8)
        for key, offset, align in columns:
            x = sheet.left + offset * mm
            (sheet.pdf.drawString if align == "l" else sheet.pdf.drawRightString)(x, sheet.y, t(key))
        sheet.down(2)
        sheet.pdf.line(sheet.left, sheet.y, sheet.right, sheet.y)
        sheet.down(5)

    from reportlab.lib.utils import simpleSplit

    sheet.ensure(12)
    header()
    sheet.on_new_page = header
    for description, cells, code in rows_with_code:
        wrapped = simpleSplit(description, sheet.body, 8, width * mm) or [""]
        sheet.ensure(4.6 * len(wrapped))
        sheet.pdf.setFont(sheet.body, 8)
        sheet.pdf.drawString(sheet.left, sheet.y, code[:14])
        for (_, offset, _align), cell in zip(columns[2:], cells, strict=True):
            sheet.pdf.drawRightString(sheet.left + offset * mm, sheet.y, cell)
        for i, row in enumerate(wrapped):
            sheet.pdf.drawString(sheet.left + columns[1][1] * mm, sheet.y, row)
            sheet.down(4.2 if i < len(wrapped) - 1 else 4.6)
    sheet.on_new_page = None
    sheet.down(4)
    if note.notes:
        sheet.labelled(t("doc.notes"), note.notes)

    sheet.ensure(24)
    sheet.down(12)
    third = (sheet.right - sheet.left) / 3
    for i, label in enumerate(signatures):
        x = sheet.left + i * third
        sheet.pdf.line(x, sheet.y, x + third - 8 * mm, sheet.y)
        sheet.pdf.setFont(sheet.body, 7.5)
        sheet.pdf.drawString(x, sheet.y - 4 * mm, label)
    sheet.down(8)
    sheet.finish()
    sheet.pdf.save()
    return buffer.getvalue()


def document_pdf(document, *, branding: PdfBranding | None = None,
                 logo: str | bytes | os.PathLike | None = None,
                 locale: str | None = None) -> bytes:
    """Any of the five documents as a PDF: one call for a host that stores them
    side by side and prints whichever the operator opens."""
    from .documents import DeliveryNote, ProForma, Quote
    from .models import Invoice as _Invoice

    if isinstance(document, _Invoice):
        return invoice_pdf(document, branding=branding, logo=logo, locale=locale)
    if isinstance(document, Quote):
        return quote_pdf(document, branding=branding, logo=logo, locale=locale)
    if isinstance(document, ProForma):
        return proforma_pdf(document, branding=branding, logo=logo, locale=locale)
    if isinstance(document, DeliveryNote):
        return delivery_note_pdf(document, branding=branding, logo=logo, locale=locale)
    raise TypeError(f"{type(document).__name__} non è un documento stampabile")


def receipt_pdf(doc: CommercialDocument, *, branding: PdfBranding | None = None,
                logo: str | bytes | os.PathLike | None = None,
                locale: str | None = None, width_mm: float = 80.0,
                columns: int = 42) -> bytes:
    """Lo scontrino come PDF, sulla stessa carta della termica.

    La pagina è **alta quanto serve** e larga come il rotolo: un A4 con dieci
    centimetri di testo in alto e il resto bianco non è la stessa cosa, né da
    guardare né da ristampare.

    Il testo è quello di :func:`~einvoice.receipt.receipt_lines`, riga per riga:
    così l'anteprima a schermo, la stampa sulla termica e questo PDF dicono le
    stesse identiche parole. Comporre un secondo layout qui sarebbe stato il
    modo più veloce per farli divergere.
    """
    from .receipt import receipt_lines

    canvas, mm = _reportlab()
    if branding is None:
        branding = PdfBranding(logo=logo)
    elif logo is not None:
        branding = PdfBranding(logo=logo, logo_width_mm=branding.logo_width_mm,
                               footer_lines=branding.footer_lines)

    lang = normalize_locale(locale) if locale else doc.resolved_locale()
    lines = receipt_lines(doc, columns, lang)

    custom_font = _resolve_font(lines, branding)
    font, size = custom_font or "Courier", 8.5
    leading = size * 1.25
    margin = 4 * mm
    reader = _logo_reader(branding)
    logo_space = 0.0
    if reader is not None:
        try:
            width_px, height_px = reader.getSize()
        except Exception:
            reader, width_px, height_px = None, 0, 0
        if reader is not None:
            logo_width = min(branding.logo_width_mm, width_mm - 8) * mm
            logo_space = (logo_width * (height_px / width_px) if width_px else 0) + 3 * mm

    height = margin * 2 + logo_space + leading * (len(lines) + 1)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width_mm * mm, height))

    y = height - margin
    if reader is not None:
        drawn = _draw_logo(pdf, reader, PdfBranding(logo=branding.logo,
                                                    logo_width_mm=min(branding.logo_width_mm,
                                                                      width_mm - 8)),
                           (width_mm * mm - min(branding.logo_width_mm, width_mm - 8) * mm) / 2,
                           y, mm)
        y -= drawn + 3 * mm

    pdf.setFont(font, size)
    for line in lines:
        y -= leading
        pdf.drawString(margin, y, line)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _draw_footer(pdf, branding: PdfBranding, left: float, mm: float,
                 font: str = "Helvetica") -> None:
    if not branding.footer_lines:
        return
    y = 14 * mm
    pdf.setFont(font, 7)
    for row in branding.footer_lines:
        pdf.drawString(left, y, row[:130])
        y -= 3.5 * mm
