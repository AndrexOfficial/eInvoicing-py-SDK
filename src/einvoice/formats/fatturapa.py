"""FatturaPA 1.2 renderer (Italy / SdI).

Covers the mandatory backbone plus the common optional fiscal blocks:
ritenuta d'acconto, bollo virtuale, cassa previdenziale, sconto/maggiorazione
di documento e di linea, codice articolo, periodo di competenza, natura IVA
con riferimento normativo, esigibilità (immediata/differita/split payment),
arrotondamento, art. 73, riferimenti (ordine/contratto/DDT/fatture collegate)
e allegati. Element ORDER follows the XSD 1.2.2 sequence.

Foreign recipients follow the SdI conventions: CodiceDestinatario "XXXXXXX"
(via the model), CAP "00000" when the foreign postcode is not a 5-digit
number, no Provincia.

The output is NOT signed; SDI requires a CAdES ``.xml.p7m`` (the transport /
signer adds it).
"""
from __future__ import annotations

import base64
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from ..models import Invoice, Party
from ..money import fmt2, fmt6, fmt_rate
from ..naming import sdi_filename
from .base import InvoiceRenderer, RenderedDocument

FATTURAPA_NS = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
ET.register_namespace("p", FATTURAPA_NS)

_REF_TAG = {
    "order": "DatiOrdineAcquisto",
    "contract": "DatiContratto",
    "ddt": "DatiDDT",
    "invoice": "DatiFattureCollegate",
}


def _el(parent: ET.Element, tag: str, text=None) -> ET.Element:
    e = ET.SubElement(parent, tag)
    if text is not None:
        e.text = str(text)
    return e


def _anagrafica(parent: ET.Element, party: Party) -> None:
    ana = _el(parent, "Anagrafica")
    if party.name:
        _el(ana, "Denominazione", party.name)
    else:
        _el(ana, "Nome", party.first_name)
        _el(ana, "Cognome", party.last_name)


def _sede(parent: ET.Element, party: Party) -> None:
    a = party.address
    sede = _el(parent, "Sede")
    _el(sede, "Indirizzo", a.street)
    if a.country != "IT" and not (len(a.postcode) == 5 and a.postcode.isdigit()):
        _el(sede, "CAP", "00000")
    else:
        _el(sede, "CAP", a.postcode)
    _el(sede, "Comune", a.city)
    if a.province and a.country == "IT":
        _el(sede, "Provincia", a.province)
    _el(sede, "Nazione", a.country)


def build_fattura_xml(
    invoice: Invoice,
    *,
    progressivo_invio: str = "00001",
    transmitter: tuple[str, str] | None = None,
) -> bytes:
    """Render ``invoice`` to FatturaPA 1.2 XML bytes."""
    invoice.validate()
    code, pec = invoice.resolved_recipient()
    tx_country, tx_code = transmitter or (invoice.seller.country_code, invoice.seller.vat_number)
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
        _el(trasm, "PECDestinatario", pec)

    cedente = _el(header, "CedentePrestatore")
    cd = _el(cedente, "DatiAnagrafici")
    civa = _el(cd, "IdFiscaleIVA")
    _el(civa, "IdPaese", invoice.seller.country_code)
    _el(civa, "IdCodice", invoice.seller.vat_number)
    if invoice.seller.tax_code:
        _el(cd, "CodiceFiscale", invoice.seller.tax_code)
    _anagrafica(cd, invoice.seller)
    _el(cd, "RegimeFiscale", invoice.seller.tax_regime)
    _sede(cedente, invoice.seller)

    cess = _el(header, "CessionarioCommittente")
    bd = _el(cess, "DatiAnagrafici")
    if invoice.buyer.vat_number:
        biva = _el(bd, "IdFiscaleIVA")
        _el(biva, "IdPaese", invoice.buyer.country_code)
        _el(biva, "IdCodice", invoice.buyer.vat_number)
    if invoice.buyer.tax_code:
        _el(bd, "CodiceFiscale", invoice.buyer.tax_code)
    _anagrafica(bd, invoice.buyer)
    _sede(cess, invoice.buyer)

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
        _el(doc, "Causale", invoice.causale)
    if invoice.art73:
        _el(doc, "Art73", "SI")

    for ref in invoice.references:
        tag = _REF_TAG.get(ref.kind)
        if not tag:
            continue
        rb = _el(generali, tag)
        for ln in ref.line_numbers:
            _el(rb, "RiferimentoNumeroLinea", ln)
        _el(rb, "IdDocumento", ref.doc_id)
        if ref.date:
            _el(rb, "Data", ref.date.isoformat())

    beni = _el(body, "DatiBeniServizi")
    for i, ln in enumerate(invoice.lines, start=1):
        det = _el(beni, "DettaglioLinee")
        _el(det, "NumeroLinea", i)
        if ln.article_code:
            ca = _el(det, "CodiceArticolo")
            _el(ca, "CodiceTipo", ln.article_code_type)
            _el(ca, "CodiceValore", ln.article_code)
        _el(det, "Descrizione", ln.description)
        _el(det, "Quantita", fmt2(ln.quantity))
        if ln.unit_of_measure:
            _el(det, "UnitaMisura", ln.unit_of_measure)
        if ln.period_start:
            _el(det, "DataInizioPeriodo", ln.period_start.isoformat())
        if ln.period_end:
            _el(det, "DataFinePeriodo", ln.period_end.isoformat())
        _el(det, "PrezzoUnitario", fmt6(ln.unit_price))
        for d in ln.discounts:
            sm = _el(det, "ScontoMaggiorazione")
            _el(sm, "Tipo", "MG" if d.is_charge else "SC")
            _el(sm, "Importo", fmt2(d.amount))
        _el(det, "PrezzoTotale", fmt2(ln.total))
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
            _el(riep, "RiferimentoNormativo", vs.exemption_reason)

    if invoice.payments:
        pay = _el(body, "DatiPagamento")
        _el(pay, "CondizioniPagamento", invoice.payments[0].condition)
        for p in invoice.payments:
            det = _el(pay, "DettaglioPagamento")
            _el(det, "ModalitaPagamento", p.means.value)
            if p.due_date:
                _el(det, "DataScadenzaPagamento", p.due_date.isoformat())
            amount = p.amount if p.amount is not None else invoice.total_payable()
            _el(det, "ImportoPagamento", fmt2(amount))
            if p.account and p.account.iban:
                _el(det, "IBAN", p.account.iban)

    for att in invoice.attachments:
        a = _el(body, "Allegati")
        _el(a, "NomeAttachment", att.filename)
        ext = PurePosixPath(att.filename).suffix.lstrip(".").upper()
        if ext:
            _el(a, "FormatoAttachment", ext)
        if att.description:
            _el(a, "DescrizioneAttachment", att.description)
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
        filename = sdi_filename(
            invoice.seller.country_code, invoice.seller.vat_number, self.progressivo_invio
        )
        return RenderedDocument("fatturapa", xml, "application/xml", filename)
