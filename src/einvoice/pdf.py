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
from .money import q2

if TYPE_CHECKING:  # pragma: no cover
    from .models import Invoice
    from .receipt import CommercialDocument

__all__ = ["PdfUnavailable", "PdfFontUnavailable", "PdfBranding",
           "invoice_pdf", "receipt_pdf", "needs_unicode_font",
           "locales_without_font", "system_unicode_font", "font_for_text"]

#: Le etichette che i due renderer disegnano davvero. Il catalogo ne ha molte di
#: più — passi di setup, note — che in un PDF non entrano mai, e includerle
#: farebbe risultare «serve un font» anche dove non serve.
_PDF_LABEL_KEYS = (
    "doc.invoice", "doc.number", "doc.date", "doc.seller", "doc.buyer",
    "doc.description", "doc.quantity", "doc.unit_price", "doc.vat",
    "doc.line_total", "doc.taxable", "doc.total", "doc.payment", "doc.notes",
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


def invoice_pdf(invoice: Invoice, *, branding: PdfBranding | None = None,
                logo: str | bytes | os.PathLike | None = None,
                locale: str | None = None) -> bytes:
    """La fattura come PDF A4.

    Non è il documento fiscale — quello è l'XML — ed è la copia leggibile che
    gli sta accanto. I numeri vengono da :meth:`~einvoice.Invoice.vat_summary`,
    gli stessi che finiscono nell'XML: ricalcolarli qui avrebbe prodotto un PDF
    che dice una cifra e un XML che ne dice un'altra sulla stessa vendita.
    """
    canvas, mm = _reportlab()
    if branding is None:
        branding = PdfBranding(logo=logo)
    elif logo is not None:
        branding = PdfBranding(logo=logo, logo_width_mm=branding.logo_width_mm,
                               footer_lines=branding.footer_lines)

    lang = _resolve_locale(locale, invoice.seller.country_code)

    def t(key: str) -> str:
        return translate(key, lang)

    # Tutto il testo che finirà sulla pagina, prima di aprire il canvas: le
    # etichette seguono la lingua, ma i nomi delle parti e le descrizioni delle
    # righe sono dati del chiamante e possono essere in qualunque alfabeto
    # indipendentemente dalla lingua scelta.
    custom_font = _resolve_font(
        [
            *(t(k) for k in ("doc.invoice", "doc.number", "doc.date", "doc.seller",
                             "doc.buyer", "doc.description", "doc.quantity",
                             "doc.unit_price", "doc.vat", "doc.line_total",
                             "doc.taxable", "doc.total", "doc.payment", "doc.notes")),
            *(row for party in (invoice.seller, invoice.buyer) for row in _party_rows(party)),
            *(line.description for line in invoice.lines),
            invoice.number, invoice.causale or "", invoice.currency,
            *branding.footer_lines,
        ],
        branding,
    )
    body_font = custom_font or "Helvetica"
    bold_font = custom_font or "Helvetica-Bold"

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(210 * mm, 297 * mm))
    left, right = 18 * mm, 192 * mm
    y = 275 * mm

    logo_height = _draw_logo(pdf, _logo_reader(branding), branding, left, y, mm)
    if logo_height:
        y -= logo_height + 6 * mm

    pdf.setFont(bold_font, 16)
    pdf.drawString(left, y, t("doc.invoice"))
    pdf.setFont(body_font, 10)
    pdf.drawRightString(right, y, f'{t("doc.number")} {invoice.number}')
    y -= 5 * mm
    pdf.drawRightString(right, y, f'{t("doc.date")}: {invoice.date:%d/%m/%Y}')
    y -= 10 * mm

    for label, party in ((t("doc.seller"), invoice.seller), (t("doc.buyer"), invoice.buyer)):
        pdf.setFont(bold_font, 9)
        pdf.drawString(left, y, label)
        y -= 4.5 * mm
        pdf.setFont(body_font, 9)
        for row in _party_rows(party):
            pdf.drawString(left, y, row[:90])
            y -= 4.2 * mm
        y -= 3 * mm

    y -= 2 * mm
    columns = (left, left + 92 * mm, left + 112 * mm, left + 140 * mm, right)
    pdf.setFont(bold_font, 8)
    for x, key, align in ((columns[0], "doc.description", "l"), (columns[1], "doc.quantity", "r"),
                          (columns[2], "doc.unit_price", "r"), (columns[3], "doc.vat", "r"),
                          (columns[4], "doc.line_total", "r")):
        (pdf.drawString if align == "l" else pdf.drawRightString)(x, y, t(key))
    y -= 2 * mm
    pdf.line(left, y, right, y)
    y -= 5 * mm

    pdf.setFont(body_font, 8)
    for line in invoice.lines:
        pdf.drawString(columns[0], y, line.description[:60])
        pdf.drawRightString(columns[1], y, f"{line.quantity:g}")
        pdf.drawRightString(columns[2], y, _money(q2(line.unit_price)))
        pdf.drawRightString(columns[3], y, f"{line.vat_rate:g}%")
        pdf.drawRightString(columns[4], y, _money(line.total))
        y -= 4.6 * mm
        if y < 45 * mm:                      # una riga tagliata a metà pagina
            pdf.showPage()                   # è una riga che nessuno conta
            y = 275 * mm
            pdf.setFont(body_font, 8)

    y -= 2 * mm
    pdf.line(columns[2], y, right, y)
    y -= 6 * mm
    pdf.setFont(body_font, 9)
    for label, amount in ((t("doc.taxable"), invoice.taxable_total()),
                          (t("doc.vat"), _tax_total(invoice))):
        pdf.drawRightString(columns[3], y, label)
        pdf.drawRightString(right, y, _money(amount))
        y -= 5 * mm
    pdf.setFont(bold_font, 11)
    pdf.drawRightString(columns[3], y, t("doc.total"))
    pdf.drawRightString(right, y, f"{_money(q2(invoice.total_document()))} {invoice.currency}")
    y -= 10 * mm

    pdf.setFont(body_font, 8)
    if invoice.payments and invoice.payments[0].means is not None:
        method = invoice.payments[0].means
        pdf.drawString(left, y, f'{t("doc.payment")}: {method.value}')
        y -= 4.5 * mm
    if invoice.causale:
        pdf.drawString(left, y, f'{t("doc.notes")}: {invoice.causale[:110]}')
        y -= 4.5 * mm

    _draw_footer(pdf, branding, left, mm, body_font)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _tax_total(invoice: Invoice) -> Decimal:
    return q2(sum((s.tax for s in invoice.vat_summary()), Decimal("0")))


def _party_rows(party) -> list[str]:
    rows = [party.name]
    address = getattr(party, "address", None)
    if address is not None:
        street = getattr(address, "street", None)
        if street:
            rows.append(street)
        town = " ".join(str(x) for x in (getattr(address, "postcode", None),
                                         getattr(address, "city", None)) if x)
        if town:
            rows.append(town)
    if party.vat_number:
        rows.append(party.vat_number)
    elif getattr(party, "tax_code", None):
        rows.append(party.tax_code)
    return rows


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
