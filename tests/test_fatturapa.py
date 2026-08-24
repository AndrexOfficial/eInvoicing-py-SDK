from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from einvoice import (
    Address,
    AllowanceCharge,
    Attachment,
    DocumentReference,
    DocumentType,
    Invoice,
    LineItem,
    Party,
    Payment,
    PaymentMeans,
    SocialSecurityFund,
    VatExigibility,
    VatNature,
    WithholdingTax,
    build_fattura_xml,
)
from einvoice.enums import WithholdingType


def _enriched() -> Invoice:
    return Invoice(
        number="2026/0001", date=date(2026, 6, 5),
        seller=Party(name="Studio Mario", vat_number="01234567890",
                     address=Address("Via Roma 1", "20100", "Milano", "MI")),
        buyer=Party(name="ACME Srl", vat_number="09876543210",
                    address=Address("Via Verdi 9", "00100", "Roma", "RM"), sdi_code="ABCDEF1"),
        lines=[
            LineItem.from_gross("Cibo", 1, Decimal("110.00"), 10),
            LineItem.from_gross("Servizio", 1, Decimal("122.00"), 22),
            LineItem("Esente", Decimal("1"), Decimal("50.00"), Decimal("0"), nature=VatNature.EXEMPT),
        ],
        allowances_charges=[AllowanceCharge(amount=Decimal("10.00"), vat_rate=Decimal("22"), reason="Sconto")],
        withholdings=[WithholdingTax(amount=Decimal("20.00"), rate=Decimal("20"),
                                     kind=WithholdingType.NATURAL_PERSON)],
        references=[DocumentReference("order", "ORD-1", line_numbers=[1])],
        stamp_duty=Decimal("2.00"),
        split_payment=True,
        payments=[Payment(means=PaymentMeans.BANK_TRANSFER)],
        causale="Prestazione professionale",
    )


def test_totals_and_payable_match_xml():
    inv = _enriched()
    root = ET.fromstring(build_fattura_xml(inv))
    doc = root.find("FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento")
    assert doc.findtext("ImportoTotaleDocumento") == f"{inv.total_document():.2f}"
    pay = root.find("FatturaElettronicaBody/DatiPagamento/DettaglioPagamento")
    assert pay.findtext("ImportoPagamento") == f"{inv.total_payable():.2f}"


def test_enriched_blocks_present():
    root = ET.fromstring(build_fattura_xml(_enriched()))
    doc = root.find("FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento")
    assert doc.find("DatiRitenuta/ImportoRitenuta").text == "20.00"
    assert doc.find("DatiRitenuta/TipoRitenuta").text == "RT01"
    assert doc.find("DatiBollo/ImportoBollo").text == "2.00"
    assert doc.find("ScontoMaggiorazione/Tipo").text == "SC"
    assert root.findtext("FatturaElettronicaBody/DatiGenerali/DatiOrdineAcquisto/IdDocumento") == "ORD-1"


def test_split_payment_and_nature():
    root = ET.fromstring(build_fattura_xml(_enriched()))
    riepiloghi = root.findall("FatturaElettronicaBody/DatiBeniServizi/DatiRiepilogo")
    for r in riepiloghi:
        assert r.findtext("EsigibilitaIVA") == "S"   # split payment
    zero = [r for r in riepiloghi if r.findtext("AliquotaIVA") == "0.00"][0]
    assert zero.findtext("Natura") == "N4"            # exempt


def _full() -> Invoice:
    """TD24 con cassa previdenziale, ritenuta, bollo, sconti documento e
    riga, esigibilità differita, arrotondamento, art. 73, allegato."""
    return Invoice(
        number="2026/0042", date=date(2026, 6, 5),
        document_type=DocumentType.DEFERRED_INVOICE,
        seller=Party(name="Studio Mario", vat_number="01234567890",
                     address=Address("Via Roma 1", "20100", "Milano", "MI")),
        buyer=Party(name="ACME Srl", vat_number="09876543210",
                    address=Address("Via Verdi 9", "00100", "Roma", "RM"), sdi_code="ABCDEF1"),
        lines=[
            LineItem("Onorario", Decimal("1"), Decimal("100"), Decimal("22"),
                     discounts=[AllowanceCharge(Decimal("10"))],
                     article_code="SRV-1",
                     period_start=date(2026, 5, 1), period_end=date(2026, 5, 31)),
            LineItem("Esente", Decimal("1"), Decimal("50.00"), Decimal("0"),
                     nature=VatNature.EXEMPT),
        ],
        funds=[SocialSecurityFund("TC04", Decimal("4"), Decimal("3.60"),
                                  taxable=Decimal("90.00"), vat_rate=Decimal("22"),
                                  withheld=True)],
        withholdings=[WithholdingTax(amount=Decimal("18.00"), rate=Decimal("20"))],
        allowances_charges=[AllowanceCharge(amount=Decimal("5.00"), vat_rate=Decimal("22"))],
        stamp_duty=Decimal("2.00"),
        rounding=Decimal("0.01"),
        art73=True,
        exigibility=VatExigibility.DEFERRED,
        causale="Prestazione maggio",
        attachments=[Attachment("dettaglio.pdf", b"%PDF", description="Dettaglio ore")],
    )


def test_full_dati_generali_documento_order_and_content():
    root = ET.fromstring(build_fattura_xml(_full()))
    doc = root.find("FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento")
    assert [el.tag for el in doc] == [
        "TipoDocumento", "Divisa", "Data", "Numero", "DatiRitenuta", "DatiBollo",
        "DatiCassaPrevidenziale", "ScontoMaggiorazione", "ImportoTotaleDocumento",
        "Arrotondamento", "Causale", "Art73",
    ]
    assert doc.findtext("TipoDocumento") == "TD24"
    cassa = doc.find("DatiCassaPrevidenziale")
    assert [el.tag for el in cassa] == [
        "TipoCassa", "AlCassa", "ImportoContributoCassa", "ImponibileCassa",
        "AliquotaIVA", "Ritenuta",
    ]
    assert cassa.findtext("ImportoContributoCassa") == "3.60"
    assert cassa.findtext("Ritenuta") == "SI"
    assert doc.findtext("Arrotondamento") == "0.01"
    assert doc.findtext("Art73") == "SI"


def test_full_dettaglio_linee_order_and_line_discount():
    root = ET.fromstring(build_fattura_xml(_full()))
    det = root.find("FatturaElettronicaBody/DatiBeniServizi/DettaglioLinee")
    assert [el.tag for el in det] == [
        "NumeroLinea", "CodiceArticolo", "Descrizione", "Quantita",
        "DataInizioPeriodo", "DataFinePeriodo", "PrezzoUnitario",
        "ScontoMaggiorazione", "PrezzoTotale", "AliquotaIVA",
    ]
    assert det.findtext("CodiceArticolo/CodiceTipo") == "INTERNO"
    assert det.findtext("CodiceArticolo/CodiceValore") == "SRV-1"
    assert det.findtext("ScontoMaggiorazione/Tipo") == "SC"
    assert det.findtext("ScontoMaggiorazione/Importo") == "10.00"
    assert det.findtext("PrezzoTotale") == "90.00"   # 100 − 10 sconto riga


def test_full_riepilogo_exigibility_and_riferimento_normativo():
    inv = _full()
    root = ET.fromstring(build_fattura_xml(inv))
    riepiloghi = root.findall("FatturaElettronicaBody/DatiBeniServizi/DatiRiepilogo")
    assert len(riepiloghi) == 2
    for r in riepiloghi:
        assert r.findtext("EsigibilitaIVA") == "D"
    # 22%: 90 (riga) + 3.60 (cassa) − 5 (sconto doc) = 88.60
    r22 = [r for r in riepiloghi if r.findtext("AliquotaIVA") == "22.00"][0]
    assert r22.findtext("ImponibileImporto") == "88.60"
    r0 = [r for r in riepiloghi if r.findtext("AliquotaIVA") == "0.00"][0]
    assert r0.findtext("Natura") == "N4"
    assert r0.findtext("RiferimentoNormativo") == VatNature.EXEMPT.default_exemption_reason
    doc = root.find("FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento")
    # 88.60 + 19.49 + 50 + 2.00 (bollo) + 0.01 (arrotondamento)
    assert doc.findtext("ImportoTotaleDocumento") == f"{inv.total_document():.2f}"


def test_attachment_format_and_description():
    root = ET.fromstring(build_fattura_xml(_full()))
    a = root.find("FatturaElettronicaBody/Allegati")
    assert [el.tag for el in a] == [
        "NomeAttachment", "FormatoAttachment", "DescrizioneAttachment", "Attachment",
    ]
    assert a.findtext("FormatoAttachment") == "PDF"
    assert a.findtext("DescrizioneAttachment") == "Dettaglio ore"


def test_foreign_buyer_conventions():
    inv = Invoice(
        number="2026/0099", date=date(2026, 6, 5),
        seller=Party(name="Studio Mario", vat_number="01234567890",
                     address=Address("Via Roma 1", "20100", "Milano", "MI")),
        buyer=Party(name="Maple Ltd", vat_number="GB123456789", country_code="GB",
                    address=Address("1 King St", "SW1A 1AA", "London", None, "GB")),
        lines=[LineItem("Export", Decimal("1"), Decimal("100"), Decimal("0"),
                        nature=VatNature.NOT_TAXABLE_EXPORT)],
    )
    root = ET.fromstring(build_fattura_xml(inv))
    assert root.findtext(
        "FatturaElettronicaHeader/DatiTrasmissione/CodiceDestinatario") == "XXXXXXX"
    sede = root.find("FatturaElettronicaHeader/CessionarioCommittente/Sede")
    assert sede.findtext("CAP") == "00000"
    assert sede.find("Provincia") is None
    assert sede.findtext("Nazione") == "GB"
