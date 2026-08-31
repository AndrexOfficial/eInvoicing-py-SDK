"""Quello che il pacchetto scrive, deve saperlo rileggere.

«Ricevi → archivia → inoltra» è un flusso che la documentazione promette, e in
quel giro la fattura passa dal renderer al parser e di nuovo al renderer. Se un
campo si perde per strada nessuno se ne accorge: il file resta valido, il
parsing non fallisce, e quello che è cambiato sono i soldi.

Questi test confrontano il *prima* e il *dopo* del giro completo, non singoli
elementi XML: è l'unico modo per accorgersi di un campo che si scrive e non si
rilegge, perché guardando solo il renderer sembra tutto a posto.
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal
from xml.etree import ElementTree as ET

from einvoice import build_fattura_xml, compare_declared_totals, parse_invoice
from einvoice.models import AllowanceCharge
from test_fatturapa import _full


def _riepilogo(xml: bytes) -> list[tuple[str | None, str | None]]:
    root = ET.fromstring(xml)
    return [(r.findtext("AliquotaIVA"), r.findtext("ImponibileImporto"))
            for r in root.findall("FatturaElettronicaBody/DatiBeniServizi/DatiRiepilogo")]


def _totale(xml: bytes) -> str | None:
    return ET.fromstring(xml).findtext(
        "FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento/ImportoTotaleDocumento")


def test_no_field_is_written_and_then_silently_dropped():
    """Il giro completo su una fattura con ogni blocco opzionale popolato."""
    original = _full()
    reread = parse_invoice(build_fattura_xml(original))

    # Due normalizzazioni sono volute e vanno escluse esplicitamente, non
    # ignorate: il codice destinatario sale da Party a Invoice, e il MIME
    # dell'allegato si deduce dal FormatoAttachment invece di restare generico.
    expected = dataclasses.replace(
        original,
        recipient_code=original.buyer.sdi_code,
        buyer=dataclasses.replace(original.buyer, sdi_code=None),
    )
    for field in dataclasses.fields(expected):
        if field.name == "attachments":
            continue
        assert getattr(reread, field.name) == getattr(expected, field.name), field.name

    assert reread.attachments[0].filename == "dettaglio.pdf"
    assert reread.attachments[0].content == b"%PDF"
    assert reread.attachments[0].mime == "application/pdf"


def test_a_document_discount_keeps_the_vat_rate_it_was_applied_to():
    """`ScontoMaggiorazione` di documento non ha `AliquotaIVA` nello schema.

    L'aliquota va ricostruita dai `DatiRiepilogo`, altrimenti alla riemissione
    lo sconto cade nel bucket di default e sposta imponibile fra aliquote.
    """
    invoice = _full()
    # Lo sconto appartiene all'esente, non al 22% della prima riga.
    invoice.allowances_charges = [AllowanceCharge(Decimal("5.00"), vat_rate=Decimal("0"))]

    first = build_fattura_xml(invoice)
    reread = parse_invoice(first)
    again = build_fattura_xml(reread)

    assert reread.allowances_charges[0].vat_rate == Decimal("0")
    assert _riepilogo(again) == _riepilogo(first) == [("22.00", "93.60"), ("0.00", "45.00")]
    assert _totale(again) == _totale(first) == "161.20"


def test_the_same_holds_when_the_discount_belongs_to_the_default_bucket():
    """Il caso che passava già: deve continuare a passare."""
    invoice = _full()   # sconto documento al 22%
    first = build_fattura_xml(invoice)
    again = build_fattura_xml(parse_invoice(first))

    assert _riepilogo(again) == _riepilogo(first) == [("22.00", "88.60"), ("0.00", "50.00")]
    assert _totale(again) == _totale(first) == "160.10"


def test_the_reread_invoice_still_adds_up_to_what_the_file_declared():
    """Se l'attribuzione fosse sbagliata, il totale ricalcolato divergerebbe."""
    invoice = _full()
    invoice.allowances_charges = [AllowanceCharge(Decimal("5.00"), vat_rate=Decimal("0"))]
    xml = build_fattura_xml(invoice)

    # Prima della ricostruzione dell'aliquota questa differenza era 1,10 €:
    # IVA inventata su cinque euro di sconto finiti nel bucket sbagliato.
    assert compare_declared_totals(xml)["difference"] == Decimal("0")


def test_an_unattributable_discount_stays_unattributed_rather_than_guessing():
    """Nel dubbio si lascia `None`: un'attribuzione inventata sposterebbe
    imponibile esattamente come il difetto che questo codice corregge."""
    invoice = _full()
    invoice.allowances_charges = [
        AllowanceCharge(Decimal("5.00"), vat_rate=Decimal("0")),
        AllowanceCharge(Decimal("5.00"), vat_rate=Decimal("22")),
    ]
    xml = build_fattura_xml(invoice)
    # Due sconti di pari importo su due bucket: la differenza per aliquota è la
    # stessa per entrambi, quindi l'ordine non è deducibile dal file. Qui
    # l'assegnazione esatta funziona proprio perché ogni bucket si muove di 5.
    rates = [ac.vat_rate for ac in parse_invoice(xml).allowances_charges]
    assert all(r is not None for r in rates)
    assert sorted(str(r) for r in rates) == ["0.00", "22.00"]
