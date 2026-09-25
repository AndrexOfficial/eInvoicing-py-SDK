"""FatturaPA 1.2 renderer (Italy / SdI).

Covers the mandatory backbone plus the common optional fiscal blocks:
ritenuta d'acconto, bollo virtuale, cassa previdenziale, sconto/maggiorazione
di documento e di linea, codice articolo, periodo di competenza, natura IVA
con riferimento normativo, esigibilità (immediata/differita/split payment),
arrotondamento, art. 73, riferimenti (ordine/contratto/fatture collegate/DDT),
dati di trasporto (fattura accompagnatoria) e allegati. Element ORDER follows
the XSD sequence (schema 1.2.3, specifiche tecniche 1.9).

What the schema and SdI demand beyond the element order, and this renderer
enforces instead of leaving to a *scarto* days later:

* **Text** goes through :func:`~einvoice.formats.latin.to_latin` — Latin-1 only,
  per-field maximum lengths; typography rewritten, non-Latin letters refused.
* **The line-level discount is per unit.** SdI recomputes
  ``PrezzoTotale = (PrezzoUnitario − ΣSconti + ΣMaggiorazioni) × Quantita``
  (check 00423, tolerance 1 cent). The model's line discount is a line-total
  amount, as in EN 16931, so it is divided by the quantity here — and the
  result is re-checked with SdI's own formula before the file is returned.
* **Quantities are never negative** (``QuantitaType`` has no sign): a returned
  item is written as a positive quantity at a negative price, which is the
  same amount in the only shape the schema accepts.
* **Causale** longer than 200 characters becomes several ``Causale``
  elements, which is what the schema's 0..N is for.

Foreign recipients follow the SdI conventions: CodiceDestinatario "XXXXXXX"
(via the model), CAP "00000" when the foreign postcode is not a 5-digit
number, no Provincia.

The output is NOT signed; SDI requires a CAdES ``.xml.p7m`` (the transport /
signer adds it).
"""
from __future__ import annotations

import base64
import re
from decimal import Decimal
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from ..errors import RenderError, ValidationError
from ..models import Address, Carrier, Invoice, LineItem, Party, TransportDetails
from ..money import D, fmt2, fmt6, fmt_rate
from ..naming import sdi_filename
from .base import InvoiceRenderer, RenderedDocument, require_invoice
from .latin import to_latin

FATTURAPA_NS = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
ET.register_namespace("p", FATTURAPA_NS)

#: ``DatiGenerali`` children in schema order. The renderer used to follow the
#: caller's order, so a credit note listing the invoice before the purchase
#: order produced a file SdI refuses — the XSD is a ``sequence``.
_REF_ORDER = ("order", "contract", "invoice", "ddt")
_REF_TAG = {
    "order": "DatiOrdineAcquisto",
    "contract": "DatiContratto",
    "invoice": "DatiFattureCollegate",
    "ddt": "DatiDDT",
}

_CAUSALE_MAX = 200
#: TipoDocumento valid only in the simplified format (schema VFSM10).
_SIMPLIFIED_ONLY = frozenset({"TD07", "TD08", "TD09"})
_EMAIL = re.compile(r".+@.+[.]+.+")
_REA = re.compile(r"^([A-Za-z]{2})\s*[-/ ]\s*(.{1,20})$")


def _el(parent: ET.Element, tag: str, text=None) -> ET.Element:
    e = ET.SubElement(parent, tag)
    if text is not None:
        e.text = str(text)
    return e


def _txt(parent: ET.Element, tag: str, value: str | None, *, field: str,
         max_len: int, ascii_only: bool = False, required: bool = True) -> None:
    """A text element in the alphabet and length its XSD type allows."""
    if value is None and not required:
        return
    text = to_latin(value or "", field=field, max_len=max_len,
                    ascii_only=ascii_only, required=required)
    if text:
        _el(parent, tag, text)


def _fmt_decimals(value: Decimal, *, minimum: int, maximum: int) -> str:
    """``value`` with as many decimals as it carries, within the type's range."""
    quantized = D(value).quantize(Decimal(1).scaleb(-maximum)).normalize()
    decimals = max(minimum, min(-int(quantized.as_tuple().exponent), maximum))
    return f"{quantized:.{decimals}f}"


def _fmt_qty(value: Decimal) -> str:
    """``QuantitaType``: ``[0-9]{1,12}\\.[0-9]{2,8}``."""
    return _fmt_decimals(value, minimum=2, maximum=8)


def _fmt_amount8(value: Decimal) -> str:
    """``Amount8DecimalType``: ``[\\-]?[0-9]{1,11}\\.[0-9]{2,8}``."""
    return _fmt_decimals(value, minimum=2, maximum=8)


def _anagrafica(parent: ET.Element, party: Party | Carrier, role: str) -> None:
    ana = _el(parent, "Anagrafica")
    name = getattr(party, "name", None)
    if name:
        _txt(ana, "Denominazione", name, field=f"{role}: denominazione", max_len=80)
    else:
        _txt(ana, "Nome", getattr(party, "first_name", None), field=f"{role}: nome", max_len=60)
        _txt(ana, "Cognome", getattr(party, "last_name", None),
             field=f"{role}: cognome", max_len=60)


def _indirizzo(parent: ET.Element, tag: str, a: Address, role: str) -> None:
    sede = _el(parent, tag)
    _txt(sede, "Indirizzo", a.street, field=f"{role}: indirizzo", max_len=60)
    if a.country != "IT" and not (len(a.postcode) == 5 and a.postcode.isdigit()):
        _el(sede, "CAP", "00000")
    else:
        _el(sede, "CAP", a.postcode)
    _txt(sede, "Comune", a.city, field=f"{role}: comune", max_len=60)
    if a.province and a.country == "IT":
        province = a.province.strip().upper()
        if not (len(province) == 2 and province.isascii() and province.isalpha()):
            raise ValidationError(
                f"{role}: provincia '{a.province}' non valida (sigla di due lettere)")
        _el(sede, "Provincia", province)
    _el(sede, "Nazione", a.country)


def _codice_fiscale(parent: ET.Element, value: str | None, role: str) -> None:
    if not value:
        return
    cf = "".join(value.split()).upper()
    if not (11 <= len(cf) <= 16 and cf.isascii() and cf.isalnum()):
        raise ValidationError(f"{role}: codice fiscale '{value}' non valido")
    _el(parent, "CodiceFiscale", cf)


def _email(parent: ET.Element, value: str, role: str) -> None:
    email = value.strip()
    if len(email) > 256 or not _EMAIL.fullmatch(email):
        raise ValidationError(f"{role}: indirizzo email '{value}' non valido")
    _el(parent, "Email", email)


def _causali(parent: ET.Element, causale: str) -> None:
    """``Causale`` is 0..N elements of at most 200 characters each: a long one
    is split on word boundaries instead of being refused or cut."""
    text = to_latin(causale, field="Causale", required=False)
    while text:
        if len(text) <= _CAUSALE_MAX:
            _el(parent, "Causale", text)
            return
        cut = text.rfind(" ", 0, _CAUSALE_MAX + 1)
        if cut <= 0:
            cut = _CAUSALE_MAX
        _el(parent, "Causale", text[:cut].rstrip())
        text = text[cut:].lstrip()


def _dati_trasporto(parent: ET.Element, t: TransportDetails, seller_country: str) -> None:
    from ..i18n import locale_for_country, translate

    block = _el(parent, "DatiTrasporto")
    carrier = t.carrier
    # DatiAnagraficiVettore requires IdFiscaleIVA: a carrier without a VAT
    # number cannot be described in this block, so it is left out rather than
    # written with an invented identifier.
    if carrier is not None and carrier.vat_number:
        dav = _el(block, "DatiAnagraficiVettore")
        idf = _el(dav, "IdFiscaleIVA")
        _el(idf, "IdPaese", carrier.country_code)
        _txt(idf, "IdCodice", "".join(carrier.vat_number.split()),
             field="Vettore: partita IVA", max_len=28, ascii_only=True)
        _codice_fiscale(dav, carrier.tax_code, "Vettore")
        _anagrafica(dav, carrier, "Vettore")
        _txt(dav, "NumeroLicenzaGuida", carrier.license_number,
             field="Vettore: numero licenza di guida", max_len=20,
             ascii_only=True, required=False)
    _txt(block, "MezzoTrasporto", t.means, field="Mezzo di trasporto",
         max_len=80, required=False)
    # The reason is written in the seller's language: an Italian DDT says
    # «Vendita», and that is also what the parser matches on the way back.
    label = translate(f"transport_reason.{t.reason.value}", locale_for_country(seller_country))
    extra = (t.reason_text or "").strip()
    qualified = f"{label}: {extra}" if extra else label
    reason = extra if t.reason.value == "other" else qualified
    _txt(block, "CausaleTrasporto", reason, field="Causale del trasporto",
         max_len=100, required=False)
    if t.packages is not None:
        _el(block, "NumeroColli", t.packages)
    _txt(block, "Descrizione", t.goods_appearance, field="Aspetto esteriore dei beni",
         max_len=100, required=False)
    if t.gross_weight is not None or t.net_weight is not None:
        _txt(block, "UnitaMisuraPeso", t.weight_unit, field="Unità di misura del peso",
             max_len=10, ascii_only=True, required=False)
    if t.gross_weight is not None:
        _el(block, "PesoLordo", fmt2(t.gross_weight))
    if t.net_weight is not None:
        _el(block, "PesoNetto", fmt2(t.net_weight))
    if t.start is not None:
        _el(block, "DataOraRitiro", t.start.replace(microsecond=0).isoformat())
        _el(block, "DataInizioTrasporto", t.start.date().isoformat())
    if t.incoterm:
        _el(block, "TipoResa", t.incoterm)
    if t.delivery_address is not None:
        _indirizzo(block, "IndirizzoResa", t.delivery_address, "Luogo di consegna")


def _line_discounts(ln: LineItem) -> list[tuple[str, Decimal]]:
    """The line's discounts as FatturaPA wants them: ``(Tipo, Importo per unità)``."""
    if not ln.discounts:
        return []
    if ln.quantity == 0:
        raise ValidationError(
            f"Riga '{ln.description}': sconto su una riga a quantità zero — in "
            "FatturaPA lo sconto di riga è per unità, e non c'è unità a cui applicarlo")
    per = abs(ln.quantity)
    return [("MG" if d.is_charge else "SC", D(d.amount) / per) for d in ln.discounts]


def _check_line_total(number: int, ln: LineItem, price: str, qty: str,
                      discounts: list[tuple[str, str]], total: str) -> None:
    """SdI check 00423, recomputed on the strings actually written.

    Rounding is where a correct model becomes a rejected file: six decimals of
    unit price, eight of quantity, eight of per-unit discount. Recomputing from
    the written values — not from the model — is the only way to know what SdI
    will compute.
    """
    unit = D(price)
    for kind, amount in discounts:
        unit += D(amount) if kind == "MG" else -D(amount)
    expected = unit * D(qty)
    if abs(expected - D(total)) >= Decimal("0.01"):
        raise RenderError(
            f"Riga {number} '{ln.description}': PrezzoTotale {total} diverso da "
            f"(PrezzoUnitario ± sconti) × Quantità = {expected:.8f}. SdI la "
            "scarterebbe con codice 00423."
        )


def build_fattura_xml(
    invoice: Invoice,
    *,
    progressivo_invio: str = "00001",
    transmitter: tuple[str, str] | None = None,
) -> bytes:
    """Render ``invoice`` to FatturaPA 1.2 XML bytes."""
    require_invoice(invoice, "FatturaPA")
    if invoice.document_type.value in _SIMPLIFIED_ONLY:
        # TD07–TD09 exist only in the SIMPLIFIED invoice format (FSM10, a
        # different schema). The ordinary FPR12/FPA12 schema does not list
        # them, so this used to produce a file SdI refuses on format.
        raise RenderError(
            f"{invoice.document_type.value} è un tipo della fattura semplificata "
            "(formato FSM10), che questo renderer non produce: emettere una "
            "fattura ordinaria (TD01, o TD04/TD05 per le rettifiche).")
    invoice.validate()
    code, pec = invoice.resolved_recipient()
    tx_country, tx_code = transmitter or (invoice.seller.country_code,
                                          invoice.seller.normalized_vat())
    esigibilita = invoice.resolved_exigibility()

    root = ET.Element(
        f"{{{FATTURAPA_NS}}}FatturaElettronica",
        {"versione": invoice.transmission_format.value},
    )

    # ── Header ────────────────────────────────────────────────────────
    header = _el(root, "FatturaElettronicaHeader")
    trasm = _el(header, "DatiTrasmissione")
    idt = _el(trasm, "IdTrasmittente")
    _el(idt, "IdPaese", tx_country)
    _el(idt, "IdCodice", tx_code)
    _el(trasm, "ProgressivoInvio", progressivo_invio)
    _el(trasm, "FormatoTrasmissione", invoice.transmission_format.value)
    _el(trasm, "CodiceDestinatario", code)
    if pec:
        _el(trasm, "PECDestinatario", pec.strip())

    cedente = _el(header, "CedentePrestatore")
    cd = _el(cedente, "DatiAnagrafici")
    civa = _el(cd, "IdFiscaleIVA")
    _el(civa, "IdPaese", invoice.seller.country_code)
    # The bare number: a P.IVA stored as "IT 01234567890" must not come out as
    # IdPaese IT + IdCodice "IT 01234567890".
    _el(civa, "IdCodice", invoice.seller.normalized_vat())
    _codice_fiscale(cd, invoice.seller.tax_code, "Cedente/Prestatore")
    _anagrafica(cd, invoice.seller, "Cedente/Prestatore")
    _el(cd, "RegimeFiscale", invoice.seller.tax_regime)
    _indirizzo(cedente, "Sede", invoice.seller.postal_address, "Cedente/Prestatore")
    # IscrizioneREA and Contatti come after Sede in the schema sequence.
    if invoice.seller.registration_number:
        # The REA is printed as "MI-123456": the office is the two-letter
        # province. Anything else used to be split blindly and written as an
        # Ufficio SdI refuses (the XSD wants exactly [A-Z]{2}).
        match = _REA.match(invoice.seller.registration_number.strip())
        if match is None:
            raise ValidationError(
                f"Cedente/Prestatore: iscrizione REA "
                f"'{invoice.seller.registration_number}' non leggibile — atteso "
                "'PR-NUMERO', es. MI-1234567")
        rea = _el(cedente, "IscrizioneREA")
        _el(rea, "Ufficio", match.group(1).upper())
        _txt(rea, "NumeroREA", match.group(2), field="Cedente/Prestatore: numero REA",
             max_len=20, ascii_only=True)
        _el(rea, "StatoLiquidazione", "LN")
    if invoice.seller.email or invoice.seller.pec:
        contatti = _el(cedente, "Contatti")
        _email(contatti, invoice.seller.email or invoice.seller.pec or "", "Cedente/Prestatore")

    cess = _el(header, "CessionarioCommittente")
    bd = _el(cess, "DatiAnagrafici")
    if invoice.buyer.vat_number:
        biva = _el(bd, "IdFiscaleIVA")
        _el(biva, "IdPaese", invoice.buyer.country_code)
        _txt(biva, "IdCodice", invoice.buyer.normalized_vat(),
             field="Cessionario/Committente: partita IVA", max_len=28, ascii_only=True)
    _codice_fiscale(bd, invoice.buyer.tax_code, "Cessionario/Committente")
    _anagrafica(bd, invoice.buyer, "Cessionario/Committente")
    _indirizzo(cess, "Sede", invoice.buyer.postal_address, "Cessionario/Committente")
    if invoice.buyer.email:
        _email(_el(cess, "Contatti"), invoice.buyer.email, "Cessionario/Committente")
    # BT-10 (BuyerReference) has no home in DatiGeneraliDocumento; the Italian
    # CIUS puts it here, and it is what the buyer's AP system matches on.
    if invoice.buyer_reference:
        _txt(cess, "RiferimentoAmministrazione", invoice.buyer_reference,
             field="Riferimento amministrazione", max_len=20, ascii_only=True)

    # ── Body ──────────────────────────────────────────────────────────
    body = _el(root, "FatturaElettronicaBody")
    generali = _el(body, "DatiGenerali")
    doc = _el(generali, "DatiGeneraliDocumento")
    _el(doc, "TipoDocumento", invoice.document_type.value)
    _el(doc, "Divisa", invoice.currency)
    _el(doc, "Data", invoice.date.isoformat())
    _el(doc, "Numero", invoice.number)
    for w in invoice.withholdings:
        dr = _el(doc, "DatiRitenuta")
        _el(dr, "TipoRitenuta", w.kind.value)
        _el(dr, "ImportoRitenuta", fmt2(w.amount))
        _el(dr, "AliquotaRitenuta", fmt_rate(w.rate))
        _el(dr, "CausalePagamento", w.reason)
    if invoice.stamp_duty:
        db = _el(doc, "DatiBollo")
        _el(db, "BolloVirtuale", "SI")
        _el(db, "ImportoBollo", fmt2(invoice.stamp_duty))
    for fund in invoice.funds:
        dc = _el(doc, "DatiCassaPrevidenziale")
        _el(dc, "TipoCassa", fund.kind)
        _el(dc, "AlCassa", fmt_rate(fund.rate))
        _el(dc, "ImportoContributoCassa", fmt2(fund.amount))
        if fund.taxable is not None:
            _el(dc, "ImponibileCassa", fmt2(fund.taxable))
        _el(dc, "AliquotaIVA", fmt_rate(fund.vat_rate))
        if fund.withheld:
            _el(dc, "Ritenuta", "SI")
        if fund.nature:
            _el(dc, "Natura", fund.nature.value)
    for ac in invoice.allowances_charges:
        sm = _el(doc, "ScontoMaggiorazione")
        _el(sm, "Tipo", "MG" if ac.is_charge else "SC")
        _el(sm, "Importo", fmt2(ac.amount))
    _el(doc, "ImportoTotaleDocumento", fmt2(invoice.total_document()))
    if invoice.rounding:
        _el(doc, "Arrotondamento", fmt2(invoice.rounding))
    if invoice.causale:
        _causali(doc, invoice.causale)
    if invoice.art73:
        _el(doc, "Art73", "SI")

    for ref in sorted((r for r in invoice.references if r.kind in _REF_TAG),
                      key=lambda r: _REF_ORDER.index(r.kind)):
        rb = _el(generali, _REF_TAG[ref.kind])
        if ref.kind == "ddt":
            # DatiDDTType is NOT DatiDocumentiCorrelatiType: number and date
            # first (both mandatory), then the invoice lines it covers. It used
            # to be written like a purchase order — IdDocumento/Data — which
            # is a file SdI refuses.
            if ref.date is None:
                raise ValidationError(
                    f"DDT '{ref.doc_id}': manca la data (DataDDT è obbligatoria)")
            _el(rb, "NumeroDDT", ref.doc_id)
            _el(rb, "DataDDT", ref.date.isoformat())
            for line_no in ref.line_numbers:
                _el(rb, "RiferimentoNumeroLinea", line_no)
            continue
        for line_no in ref.line_numbers:
            _el(rb, "RiferimentoNumeroLinea", line_no)
        _el(rb, "IdDocumento", ref.doc_id)
        if ref.date:
            _el(rb, "Data", ref.date.isoformat())

    if invoice.transport is not None:
        _dati_trasporto(generali, invoice.transport, invoice.seller.country_code)

    beni = _el(body, "DatiBeniServizi")
    for i, ln in enumerate(invoice.lines, start=1):
        det = _el(beni, "DettaglioLinee")
        _el(det, "NumeroLinea", i)
        if ln.article_code:
            ca = _el(det, "CodiceArticolo")
            _txt(ca, "CodiceTipo", ln.article_code_type, field=f"Riga {i}: tipo codice articolo",
                 max_len=35, ascii_only=True)
            _txt(ca, "CodiceValore", ln.article_code, field=f"Riga {i}: codice articolo",
                 max_len=35)
        _txt(det, "Descrizione", ln.description, field=f"Riga {i}: descrizione", max_len=1000)
        # A negative quantity is a returned item; QuantitaType has no sign, so
        # the sign moves to the price — same amount, the only shape allowed.
        sign = Decimal("-1") if ln.quantity < 0 else Decimal("1")
        qty = _fmt_qty(abs(ln.quantity))
        _el(det, "Quantita", qty)
        if ln.unit_of_measure:
            _txt(det, "UnitaMisura", ln.unit_of_measure, field=f"Riga {i}: unità di misura",
                 max_len=10, ascii_only=True, required=False)
        if ln.period_start:
            _el(det, "DataInizioPeriodo", ln.period_start.isoformat())
        if ln.period_end:
            _el(det, "DataFinePeriodo", ln.period_end.isoformat())
        price = fmt6(ln.unit_price * sign)
        _el(det, "PrezzoUnitario", price)
        written: list[tuple[str, str]] = []
        for kind, per_unit in _line_discounts(ln):
            sm = _el(det, "ScontoMaggiorazione")
            _el(sm, "Tipo", kind)
            importo = _fmt_amount8(per_unit)
            _el(sm, "Importo", importo)
            written.append((kind, importo))
        total = fmt2(ln.total)
        _el(det, "PrezzoTotale", total)
        _check_line_total(i, ln, price, qty, written, total)
        _el(det, "AliquotaIVA", fmt_rate(ln.vat_rate))
        if ln.vat_rate == 0 and ln.nature:
            _el(det, "Natura", ln.nature.value)

    for vs in invoice.vat_summary():
        riep = _el(beni, "DatiRiepilogo")
        _el(riep, "AliquotaIVA", fmt_rate(vs.vat_rate))
        if vs.vat_rate == 0 and vs.nature:
            _el(riep, "Natura", vs.nature.value)
        _el(riep, "ImponibileImporto", fmt2(vs.taxable))
        _el(riep, "Imposta", fmt2(vs.tax))
        _el(riep, "EsigibilitaIVA", esigibilita)
        if vs.nature and vs.exemption_reason:
            _txt(riep, "RiferimentoNormativo", vs.exemption_reason,
                 field="Riferimento normativo", max_len=100)

    if invoice.payments:
        pay = _el(body, "DatiPagamento")
        _el(pay, "CondizioniPagamento", invoice.payments[0].condition)
        for p in invoice.payments:
            det = _el(pay, "DettaglioPagamento")
            has_account = bool(p.account and p.account.iban)
            # Beneficiario is the FIRST child of DettaglioPagamento. It used to
            # be written after ImportoPagamento, beside the bank — where a
            # comment said the schema wanted it, and where the schema refuses it.
            if has_account and p.account is not None:
                _txt(det, "Beneficiario", p.account.holder, field="Beneficiario",
                     max_len=200, required=False)
            _el(det, "ModalitaPagamento", p.means.value)
            if p.due_date:
                _el(det, "DataScadenzaPagamento", p.due_date.isoformat())
            amount = p.amount if p.amount is not None else invoice.total_payable()
            _el(det, "ImportoPagamento", fmt2(amount))
            if has_account and p.account is not None:
                _txt(det, "IstitutoFinanziario", p.account.bank_name,
                     field="Istituto finanziario", max_len=80, required=False)
                # IBANs are printed in groups of four; the schema wants none of
                # the spaces a person copies along with the number.
                _el(det, "IBAN", "".join(p.account.iban.split()).upper())
                if p.account.bic:
                    _el(det, "BIC", "".join(p.account.bic.split()).upper())

    for n, att in enumerate(invoice.attachments, start=1):
        a = _el(body, "Allegati")
        _txt(a, "NomeAttachment", att.filename, field=f"Allegato {n}: nome", max_len=60)
        ext = PurePosixPath(att.filename).suffix.lstrip(".").upper()
        if ext:
            _txt(a, "FormatoAttachment", ext, field=f"Allegato {n}: formato",
                 max_len=10, ascii_only=True)
        if att.description:
            _txt(a, "DescrizioneAttachment", att.description,
                 field=f"Allegato {n}: descrizione", max_len=100)
        _el(a, "Attachment", base64.b64encode(att.content).decode("ascii"))

    ET.indent(root)
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


class FatturaPARenderer(InvoiceRenderer):
    standard = "fatturapa"

    def __init__(self, *, progressivo_invio: str = "00001",
                 transmitter: tuple[str, str] | None = None):
        self.progressivo_invio = progressivo_invio
        self.transmitter = transmitter

    def render(self, invoice: Invoice) -> RenderedDocument:
        xml = build_fattura_xml(
            invoice, progressivo_invio=self.progressivo_invio, transmitter=self.transmitter
        )
        # An IT seller always has a P.IVA (the profile enforces it), but this
        # renderer can be selected explicitly for a foreign seller — and a
        # missing number used to be stringified straight into the name as
        # "ITNone_00001.xml".
        seller_id = invoice.seller.normalized_vat() or invoice.seller.tax_code
        if not seller_id:
            raise ValidationError(
                "FatturaPA: il cedente deve avere P.IVA o codice fiscale per "
                "comporre il nome file di trasmissione SdI"
            )
        filename = sdi_filename(
            invoice.seller.country_code, seller_id, self.progressivo_invio
        )
        return RenderedDocument("fatturapa", xml, "application/xml", filename)
