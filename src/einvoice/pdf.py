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
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .errors import EInvoiceError
from .i18n import locale_for_country, normalize_locale, translate
from .money import q2

if TYPE_CHECKING:  # pragma: no cover
    from .models import Invoice
    from .receipt import CommercialDocument

__all__ = ["PdfUnavailable", "PdfBranding", "invoice_pdf", "receipt_pdf"]


class PdfUnavailable(EInvoiceError, RuntimeError):
    """L'extra ``[pdf]`` non è installato su questo deploy.

    Distinta da un errore sui dati: qui il documento va benissimo, manca una
    libreria. Chi cattura questa può rispondere «PDF non disponibile su questo
    server» e continuare a emettere l'XML, che è la parte fiscale.
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

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(210 * mm, 297 * mm))
    left, right = 18 * mm, 192 * mm
    y = 275 * mm

    logo_height = _draw_logo(pdf, _logo_reader(branding), branding, left, y, mm)
    if logo_height:
        y -= logo_height + 6 * mm

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(left, y, t("doc.invoice"))
    pdf.setFont("Helvetica", 10)
    pdf.drawRightString(right, y, f'{t("doc.number")} {invoice.number}')
    y -= 5 * mm
    pdf.drawRightString(right, y, f'{t("doc.date")}: {invoice.date:%d/%m/%Y}')
    y -= 10 * mm

    for label, party in ((t("doc.seller"), invoice.seller), (t("doc.buyer"), invoice.buyer)):
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(left, y, label)
        y -= 4.5 * mm
        pdf.setFont("Helvetica", 9)
        for row in _party_rows(party):
            pdf.drawString(left, y, row[:90])
            y -= 4.2 * mm
        y -= 3 * mm

    y -= 2 * mm
    columns = (left, left + 92 * mm, left + 112 * mm, left + 140 * mm, right)
    pdf.setFont("Helvetica-Bold", 8)
    for x, key, align in ((columns[0], "doc.description", "l"), (columns[1], "doc.quantity", "r"),
                          (columns[2], "doc.unit_price", "r"), (columns[3], "doc.vat", "r"),
                          (columns[4], "doc.line_total", "r")):
        (pdf.drawString if align == "l" else pdf.drawRightString)(x, y, t(key))
    y -= 2 * mm
    pdf.line(left, y, right, y)
    y -= 5 * mm

    pdf.setFont("Helvetica", 8)
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
            pdf.setFont("Helvetica", 8)

    y -= 2 * mm
    pdf.line(columns[2], y, right, y)
    y -= 6 * mm
    pdf.setFont("Helvetica", 9)
    for label, amount in ((t("doc.taxable"), invoice.taxable_total()),
                          (t("doc.vat"), _tax_total(invoice))):
        pdf.drawRightString(columns[3], y, label)
        pdf.drawRightString(right, y, _money(amount))
        y -= 5 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(columns[3], y, t("doc.total"))
    pdf.drawRightString(right, y, f"{_money(q2(invoice.total_document()))} {invoice.currency}")
    y -= 10 * mm

    pdf.setFont("Helvetica", 8)
    if invoice.payments and invoice.payments[0].means is not None:
        method = invoice.payments[0].means
        pdf.drawString(left, y, f'{t("doc.payment")}: {method.value}')
        y -= 4.5 * mm
    if invoice.causale:
        pdf.drawString(left, y, f'{t("doc.notes")}: {invoice.causale[:110]}')
        y -= 4.5 * mm

    _draw_footer(pdf, branding, left, mm)
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

    font, size = "Courier", 8.5
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


def _draw_footer(pdf, branding: PdfBranding, left: float, mm: float) -> None:
    if not branding.footer_lines:
        return
    y = 14 * mm
    pdf.setFont("Helvetica", 7)
    for row in branding.footer_lines:
        pdf.drawString(left, y, row[:130])
        y -= 3.5 * mm
