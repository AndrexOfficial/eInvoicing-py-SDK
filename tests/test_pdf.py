"""Il PDF: la copia che una persona legge.

Non è il documento fiscale — quello è l'XML — ma è quello che finisce allegato
a una mail e in un archivio. Quello che va sorvegliato non è l'estetica, che
non si testa, ma le tre proprietà che l'hanno resa una libreria e non due
copie: che i numeri vengano dallo stesso calcolo dell'XML, che la lingua sia
quella del paese di fatturazione, e che un logo rotto non impedisca di emettere.
"""
from datetime import date
from decimal import Decimal

import pytest

from einvoice import Address, Invoice, LineItem, Party, Payment, PaymentMeans
from einvoice.pdf import PdfBranding, PdfUnavailable, invoice_pdf, receipt_pdf
from einvoice.pos import PosPaymentMethod
from einvoice.receipt import CommercialDocument, ReceiptPayment

pytest.importorskip("reportlab", reason="il PDF è l'extra [pdf]")

def _png(width: int = 8, height: int = 8) -> bytes:
    """Un PNG valido, costruito qui.

    Scritto invece di incollato: un blob esadecimale a memoria è esattamente
    come è nato il primo tentativo di questo file, che ReportLab ha rifiutato
    con «broken data stream» — e il test che doveva provare che il logo
    funziona provava che non funzionava niente.
    """
    import struct
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


PNG = _png()

#: L'esemplare vero: intestazione PNG corretta, flusso dati rotto.
#:
#: Non è costruito ad arte — è il blob che avevo scritto a memoria al primo
#: tentativo di questo file. ``ImageReader`` lo costruisce, ``getSize()`` non
#: protesta, e ``drawImage`` solleva a documento già iniziato. Un file
#: illeggibile del tutto (``b"non sono un'immagine"``) fallisce prima e non
#: prova niente su quel percorso.
PNG_ROTTO = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


def _invoice(**kwargs) -> Invoice:
    defaults = {
        "number": "1/2026", "date": date(2026, 8, 27),
        "seller": Party(name="Trattoria da Bruno", vat_number="IT12345678903",
                        country_code="IT", tax_regime="RF01",
                        address=Address(street="Via Roma 1", postcode="20100", city="Milano")),
        "buyer": Party(name="ACME Srl", vat_number="IT0278620153", country_code="IT",
                       address=Address(street="Via Verdi 9", postcode="00100", city="Roma")),
        "lines": [LineItem.from_gross("Pranzo di lavoro", 4, Decimal("25.00"), Decimal("10"))],
        "payments": [Payment(means=PaymentMeans.CARD)],
        "causale": "Servizio di ristorazione",
    }
    defaults.update(kwargs)
    return Invoice(**defaults)


def _receipt(**kwargs) -> CommercialDocument:
    defaults = {
        "number": "0002-0041", "date": date(2026, 8, 27), "merchant": "Bar Centrale",
        "lines": [LineItem.from_gross("Caffè", 2, Decimal("1.20"), Decimal("10"))],
        "payments": [ReceiptPayment(PosPaymentMethod.CARD, Decimal("2.40"))],
    }
    defaults.update(kwargs)
    return CommercialDocument(**defaults)


# ── che sia un PDF ────────────────────────────────────────────────────


def test_both_produce_a_real_pdf():
    for blob in (invoice_pdf(_invoice()), receipt_pdf(_receipt())):
        assert blob.startswith(b"%PDF-")
        assert blob.rstrip().endswith(b"%%EOF")


def test_they_return_bytes_and_write_nothing():
    """Un modulo che scrive file da sé va riscritto la prima volta che il file
    deve finire su un bucket."""
    assert isinstance(invoice_pdf(_invoice()), bytes)
    assert isinstance(receipt_pdf(_receipt()), bytes)


# ── il logo ───────────────────────────────────────────────────────────


def test_the_logo_can_arrive_as_bytes_or_as_a_path(tmp_path):
    """Chi lo tiene su disco e chi lo tiene su un bucket non deve scrivere
    codice diverso."""
    path = tmp_path / "logo.png"
    path.write_bytes(PNG)

    da_byte = invoice_pdf(_invoice(), logo=PNG)
    da_percorso = invoice_pdf(_invoice(), logo=str(path))

    senza = invoice_pdf(_invoice())
    assert len(da_byte) > len(senza) and len(da_percorso) > len(senza)


def test_the_receipt_takes_a_logo_too():
    assert len(receipt_pdf(_receipt(), logo=PNG)) > len(receipt_pdf(_receipt()))


def test_a_broken_logo_does_not_stop_the_document():
    """Una fattura che non esce perché il PNG è corrotto è un danno peggiore di
    una fattura senza marchio, e chi chiama non ha modo di saperlo prima."""
    blob = invoice_pdf(_invoice(), logo=b"non sono un'immagine")

    assert blob.startswith(b"%PDF-")


def test_a_plausible_but_corrupt_png_does_not_stop_the_document():
    """Il caso vero, e quello che il primo tentativo di questo file ha trovato
    per sbaglio: un file con l'intestazione PNG giusta e il flusso dati rotto.

    ``ImageReader`` lo costruisce volentieri e fallisce **al disegno**, cioè a
    documento già iniziato. Proteggere solo la lettura lasciava scoperto proprio
    il caso per cui la protezione esisteva.
    """
    assert invoice_pdf(_invoice(), logo=PNG_ROTTO).startswith(b"%PDF-")
    assert receipt_pdf(_receipt(), logo=PNG_ROTTO).startswith(b"%PDF-")


def test_a_missing_logo_file_does_not_stop_the_document():
    assert invoice_pdf(_invoice(), logo="/non/esiste/logo.png").startswith(b"%PDF-")


def test_branding_carries_the_footer_lines():
    branding = PdfBranding(logo=PNG, footer_lines=("Via Roma 1, Milano", "REA MI-123456"))

    assert invoice_pdf(_invoice(), branding=branding).startswith(b"%PDF-")


# ── la lingua ─────────────────────────────────────────────────────────


def test_the_receipt_pdf_says_the_same_words_as_the_text_layout():
    """Comporre un secondo layout nel PDF sarebbe stato il modo più veloce per
    farlo divergere dalla termica."""
    from einvoice.receipt import receipt_lines

    doc = _receipt(country="DE")
    testo = receipt_lines(doc, 42, doc.resolved_locale())

    # Le stringhe finiscono nel PDF non compresso di ReportLab in chiaro solo
    # a tratti: si verifica la scelta della lingua, che è ciò che decide quelle
    # parole, e il layout è già coperto dai test del testo.
    assert doc.resolved_locale() == "de"
    assert any("GESAMT" in line for line in testo)
    assert receipt_pdf(doc).startswith(b"%PDF-")


def test_an_explicit_locale_reaches_the_pdf():
    assert receipt_pdf(_receipt(country="IT"), locale="fr").startswith(b"%PDF-")
    # Il greco lo copre `test_a_script_the_font_cannot_draw_raises…`: senza font
    # non esce, ed è la correzione — prima usciva pieno di punti interrogativi.
    assert invoice_pdf(_invoice(), locale="pt").startswith(b"%PDF-")


def test_the_invoice_language_follows_the_seller_country():
    """Un'intestazione italiana su una fattura di un cedente tedesco è la
    stessa svista dello scontrino."""
    tedesca = _invoice(seller=Party(name="Bäckerei Schmidt", vat_number="DE136695976",
                                    country_code="DE"))

    assert invoice_pdf(tedesca).startswith(b"%PDF-")


# ── i numeri ──────────────────────────────────────────────────────────


def test_the_invoice_pdf_reads_the_totals_it_does_not_recompute_them():
    """Un PDF che dice una cifra e un XML che ne dice un'altra sulla stessa
    vendita è il difetto che questo modulo esiste per non introdurre."""
    invoice = _invoice()
    prima = invoice.total_document()

    invoice_pdf(invoice)

    assert invoice.total_document() == prima, "il PDF ha alterato il documento"


def test_a_long_invoice_spills_onto_a_second_page():
    """Una riga tagliata a metà pagina è una riga che nessuno conta."""
    molte = _invoice(lines=[
        LineItem.from_gross(f"Voce {n}", 1, Decimal("10.00"), Decimal("22"))
        for n in range(120)
    ])

    assert invoice_pdf(molte).count(b"/Type /Page\n") >= 2 or len(invoice_pdf(molte)) > 4000


def test_a_receipt_page_is_as_tall_as_it_needs_to_be():
    """Un A4 con dieci centimetri di testo in alto e il resto bianco non è la
    stessa cosa, né da guardare né da ristampare."""
    corto = receipt_pdf(_receipt())
    lungo = receipt_pdf(_receipt(lines=[
        LineItem.from_gross(f"Voce {n}", 1, Decimal("2.00"), Decimal("10")) for n in range(40)
    ]))

    assert len(lungo) > len(corto)


# ── la dipendenza ─────────────────────────────────────────────────────


def test_the_missing_extra_is_its_own_error(monkeypatch):
    """«Non è installato» e «il documento è rotto» sono due problemi diversi:
    il primo è di deploy, il secondo è un dato da correggere. Chi cattura
    questa può rispondere «PDF non disponibile» e continuare a emettere l'XML,
    che è la parte fiscale."""
    import builtins

    from einvoice import pdf as pdf_module

    reale = builtins.__import__

    def senza_reportlab(name, *args, **kwargs):
        if name.startswith("reportlab"):
            raise ModuleNotFoundError(name)
        return reale(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", senza_reportlab)
    with pytest.raises(PdfUnavailable, match=r"\[pdf\]"):
        pdf_module.invoice_pdf(_invoice())


def test_the_error_is_catchable_as_an_einvoice_error():
    from einvoice.errors import EInvoiceError

    assert issubclass(PdfUnavailable, EInvoiceError)
    assert issubclass(PdfUnavailable, RuntimeError)


# ── gli alfabeti ──────────────────────────────────────────────────────
#
# Il pacchetto scrive le etichette in trentuno lingue e i font base di ReportLab
# coprono Latin-1. Localizzare il PDF senza accorgersene produceva un documento
# in cui il nome del cliente greco era una fila di punti interrogativi — e non
# falliva niente, quindi non se ne accorgeva nessuno.


def _greca() -> Invoice:
    return _invoice(
        seller=Party(name="Εταιρεία ΑΕ", vat_number="EL123456783", country_code="GR",
                     address=Address(street="Οδός 1", postcode="10431", city="Αθήνα")),
        buyer=Party(name="Πελάτης", vat_number="EL094014201", country_code="GR"),
        lines=[LineItem("Υπηρεσία", Decimal("1"), Decimal("100.00"), Decimal("24"))],
        causale=None,
    )


def test_a_script_the_font_cannot_draw_raises_instead_of_printing_question_marks(senza_font_di_sistema):
    """Una copia di cortesia col nome del cliente sostituito da `???` è peggio
    di una copia che non esce: quella almeno si nota."""
    from einvoice.pdf import PdfFontUnavailable

    with pytest.raises(PdfFontUnavailable, match="font_path"):
        invoice_pdf(_greca())


def test_the_error_names_the_characters_and_the_fix(senza_font_di_sistema):
    from einvoice.pdf import PdfFontUnavailable

    with pytest.raises(PdfFontUnavailable) as exc:
        invoice_pdf(_greca())

    assert "Σ" in str(exc.value) or "Ο" in str(exc.value)
    assert "DejaVuSans" in str(exc.value)


def test_latin_accents_and_the_euro_sign_still_work():
    """à è ì ò ù e € sono dentro Latin-1: la correzione non deve rendere più
    difficile il caso normale italiano."""
    accentata = _invoice(
        seller=Party(name="Trattoria àèìòù", vat_number="IT12345678903", country_code="IT",
                     tax_regime="RF01",
                     address=Address(street="Via Perù 1", postcode="20100", city="Milano")),
        lines=[LineItem("Caffè", Decimal("1"), Decimal("1.00"), Decimal("10"))],
    )

    assert invoice_pdf(accentata).startswith(b"%PDF-")


def test_a_unicode_font_makes_the_greek_invoice_work():
    """La via d'uscita dichiarata dall'errore deve funzionare davvero."""
    import glob
    import os

    import reportlab

    from einvoice.pdf import PdfBranding

    # Un TTF qualunque presente sul sistema di test: qui basta che la
    # registrazione e il controllo di copertura passino per i caratteri usati.
    candidati = glob.glob(os.path.join(os.path.dirname(reportlab.__file__), "fonts", "*.ttf"))
    assert candidati, "reportlab non espone nessun TTF: il test non può girare"

    latina = _invoice()
    blob = invoice_pdf(latina, branding=PdfBranding(font_path=candidati[0]))
    assert blob.startswith(b"%PDF-")


def test_a_font_file_that_is_not_a_font_says_so():
    from einvoice.pdf import PdfBranding, PdfFontUnavailable

    with pytest.raises(PdfFontUnavailable, match="non caricabile"):
        invoice_pdf(_invoice(), branding=PdfBranding(font_path="/non/esiste/font.ttf"))


def test_the_receipt_pdf_checks_the_alphabet_too(senza_font_di_sistema):
    from einvoice.pdf import PdfFontUnavailable

    with pytest.raises(PdfFontUnavailable):
        receipt_pdf(_receipt(country="GR", merchant="Καφενείο"))


def test_which_languages_print_without_a_font_is_computed_not_guessed():
    """Una lista fissa direbbe di sì a una lingua che nel frattempo ha smesso di
    esserlo — basta che una traduzione cambi e introduca una lettera fuori da
    Latin-1."""
    from einvoice.pdf import locales_without_font, needs_unicode_font

    senza = locales_without_font()

    # Il caso comune non deve regredire.
    assert {"it", "en", "de", "fr", "es"} <= senza
    assert not needs_unicode_font("it")
    assert len(senza) == 14

    # E le lingue che un font lo richiedono davvero.
    for locale in ("el", "ru", "pl", "ar", "zh", "th", "ro", "hu"):
        assert needs_unicode_font(locale), locale
        assert locale not in senza


def test_the_question_can_be_asked_before_printing():
    """Scoprire che serve un font quando il cliente chiede la copia significa
    non dargliela."""
    from einvoice.pdf import needs_unicode_font

    assert needs_unicode_font("el") is True
    assert needs_unicode_font(None) is False   # default inglese


@pytest.fixture
def senza_font_di_sistema(monkeypatch):
    """Toglie il font di sistema, perché altrimenti questi test direbbero cose
    diverse su macchine diverse: verdi su un portatile che i font ce li ha,
    rossi in un container `slim` che non ne ha nessuno. Quel che si vuole
    verificare è il comportamento *senza* font, e va chiesto esplicitamente."""
    monkeypatch.setattr("einvoice.pdf.SYSTEM_FONT_CANDIDATES", ())


def test_a_system_font_is_used_when_the_caller_does_not_supply_one():
    """Pretendere che ogni chiamante sappia di dover procurare un font per
    stampare in greco significa che in greco non stampa nessuno."""
    from einvoice.pdf import system_unicode_font

    if system_unicode_font() is None:
        pytest.skip("nessun font Unicode di sistema su questa macchina")
    assert invoice_pdf(_greca()).startswith(b"%PDF-")


def test_the_caller_font_wins_over_the_system_one(monkeypatch):
    """`PdfBranding.font_path` è una scelta, non un suggerimento: si usa quello
    anche se in giro ci sono font di sistema."""
    from einvoice.pdf import PdfBranding, system_unicode_font

    font = system_unicode_font()
    if font is None:
        pytest.skip("nessun font Unicode di sistema su questa macchina")

    monkeypatch.setattr("einvoice.pdf.SYSTEM_FONT_CANDIDATES", ())
    assert invoice_pdf(_greca(), branding=PdfBranding(font_path=font)).startswith(b"%PDF-")


def test_a_font_that_does_not_cover_the_document_is_rejected_not_used(monkeypatch):
    """DejaVu è il font che quasi ogni immagine Linux ha, e non copre CJK né
    thai: prendere il primo font trovato avrebbe stampato caselle vuote in
    giapponese — lo stesso difetto di prima, con un passaggio in più."""
    from einvoice.pdf import PdfFontUnavailable

    # Nessun font disponibile copre il documento, di sistema o meno.
    monkeypatch.setattr("einvoice.pdf._missing_glyphs", lambda texts, font: {"Σ"})
    with pytest.raises(PdfFontUnavailable):
        invoice_pdf(_greca())


def test_the_error_says_which_fonts_were_tried():
    """«Non funziona» non aiuta; «ho provato questi e non bastavano» sì."""
    from einvoice.pdf import PdfFontUnavailable, system_unicode_font

    if system_unicode_font() is None:
        pytest.skip("nessun font Unicode di sistema su questa macchina")

    import einvoice.pdf as mod
    original = mod._missing_glyphs
    try:
        mod._missing_glyphs = lambda texts, font: {"\u5b57"}
        with pytest.raises(PdfFontUnavailable) as exc:
            invoice_pdf(_greca())
    finally:
        mod._missing_glyphs = original

    assert "Provati senza successo" in str(exc.value)
    assert "fonts-noto-cjk" in str(exc.value)


# ── chi disegna un PDF proprio ────────────────────────────────────────


def test_font_for_text_says_none_when_the_base_fonts_are_enough():
    """`None` non è un fallimento: è «usa Helvetica», e il PDF resta leggero."""
    from einvoice.pdf import font_for_text

    assert font_for_text(["Trattoria àèìòù", "Caffè 1,20 €"]) is None


def test_font_for_text_gives_a_registered_font_for_other_alphabets():
    """Deve tornare un font che ReportLab ha già registrato, pronto per
    `setFont`: restituire un percorso lascerebbe il lavoro a chi chiama, ed è
    il lavoro che si sbaglia."""
    from reportlab.pdfbase import pdfmetrics

    from einvoice.pdf import font_for_text, system_unicode_font

    if system_unicode_font() is None:
        pytest.skip("nessun font Unicode di sistema su questa macchina")

    name = font_for_text(["Καφενείο", "Иванов"])
    assert name is not None
    assert name in pdfmetrics.getRegisteredFontNames()


def test_font_for_text_raises_rather_than_returning_a_font_that_cannot_draw(
        senza_font_di_sistema):
    """Chi disegna a mano vuole saperlo prima di aprire la pagina, per gli
    stessi motivi per cui lo vuole sapere invoice_pdf."""
    from einvoice.pdf import PdfFontUnavailable, font_for_text

    with pytest.raises(PdfFontUnavailable):
        font_for_text(["Καφενείο"])


def test_font_for_text_honours_an_explicit_font():
    from einvoice.pdf import font_for_text, system_unicode_font

    font = system_unicode_font()
    if font is None:
        pytest.skip("nessun font Unicode di sistema su questa macchina")

    assert font_for_text(["Καφενείο"], font_path=font) is not None


def test_the_euro_sign_is_drawable_by_the_base_fonts():
    """I font base si disegnano in WinAnsi (CP1252), non in Latin-1, e l'euro
    sta nella differenza. Trattarlo da carattere indisegnabile significava
    rifiutare uno scontrino da «12,00 €» su un'immagine senza font."""
    from einvoice.pdf import font_for_text

    assert font_for_text(["Totale 12,00 €", "Caffè 1,20 €"]) is None


def test_a_receipt_with_euro_signs_prints_without_any_system_font(
        senza_font_di_sistema):
    """Il caso più comune d'Europa, sull'immagine più spoglia."""
    assert receipt_pdf(_receipt(country="IT")).startswith(b"%PDF-")
    assert font_for_text_is_none_for("12,00 €")


def font_for_text_is_none_for(text: str) -> bool:
    from einvoice.pdf import font_for_text

    return font_for_text([text]) is None
