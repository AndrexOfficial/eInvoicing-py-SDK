"""Le ricevute SdI.

Il pacchetto sapeva costruire la fattura, firmarla, trasmetterla e modellarne il
ciclo di vita — e non sapeva leggere l'unica cosa che torna indietro. Ogni
integrazione se le riparsava per conto suo.

Su una notifica di scarto il **codice d'errore** è il dato più utile dell'intero
flusso: dice perché la fattura è stata rifiutata, e senza si ricomincia a
tentativi.
"""
import pytest

from einvoice import InvoiceState, NotificationType
from einvoice.errors import ValidationError
from einvoice.notifications import (
    SDI_RECEIPT_TYPES,
    parse_sdi_receipt,
    receipt_kind_from_filename,
)

SCARTO = """<?xml version="1.0" encoding="UTF-8"?>
<ns3:NotificaScarto xmlns:ns3="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/messaggi/v1.0">
  <IdentificativoSdI>1234567</IdentificativoSdI>
  <NomeFile>IT12345678903_00001.xml</NomeFile>
  <DataOraRicezione>2026-08-27T10:15:00.000+02:00</DataOraRicezione>
  <ListaErrori>
    <Errore><Codice>00404</Codice><Descrizione>Fattura duplicata</Descrizione></Errore>
    <Errore><Codice>00311</Codice><Descrizione>CodiceDestinatario non valido</Descrizione></Errore>
  </ListaErrori>
  <MessageId>987</MessageId>
</ns3:NotificaScarto>"""

CONSEGNA = """<RicevutaConsegna>
  <IdentificativoSdI>77</IdentificativoSdI>
  <NomeFile>IT12345678903_00001.xml</NomeFile>
  <DataOraConsegna>2026-08-28T09:00:00</DataOraConsegna>
</RicevutaConsegna>"""


def test_a_rejection_carries_the_codes_that_make_the_work_restart():
    receipt = parse_sdi_receipt(SCARTO)

    assert receipt.kind == "NS"
    assert receipt.type is NotificationType.REJECTED
    assert [e.code for e in receipt.errors] == ["00404", "00311"]
    assert receipt.errors[0].description == "Fattura duplicata"


def test_the_receipt_becomes_a_lifecycle_notification():
    """È la forma che il resto del pacchetto sa già applicare: leggere la
    ricevuta e muovere lo stato devono essere lo stesso gesto."""
    notification = parse_sdi_receipt(SCARTO).to_notification()

    assert notification.target_state() is InvoiceState.REJECTED
    assert notification.sdi_id == "1234567"
    assert "00404" in (notification.message or "")


def test_a_delivery_receipt_moves_the_invoice_to_delivered():
    receipt = parse_sdi_receipt(CONSEGNA)

    assert receipt.kind == "RC"
    assert receipt.to_notification().target_state() is InvoiceState.DELIVERED
    assert receipt.at is not None and receipt.at.year == 2026


def test_the_namespace_is_not_trusted():
    """Alcuni intermediari lo riscrivono, altri lo tolgono del tutto. Un parser
    che lo pretendesse fallirebbe su file perfettamente validi."""
    senza = SCARTO.replace(' xmlns:ns3="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/messaggi/v1.0"', "")
    senza = senza.replace("ns3:", "")
    altro = SCARTO.replace("http://ivaservizi.agenziaentrate.gov.it/docs/xsd/messaggi/v1.0", "urn:qualcosa:altro")

    for variante in (senza, altro):
        assert parse_sdi_receipt(variante).kind == "NS"
        assert len(parse_sdi_receipt(variante).errors) == 2


def test_a_customer_rejection_is_negative():
    """EC02 = rifiutata dal committente. Trattarla come positiva chiuderebbe la
    fattura come accettata quando il cliente l'ha respinta."""
    esito = ('<NotificaEsito><IdentificativoSdI>9</IdentificativoSdI>'
             '<EsitoCommittente><Esito>EC02</Esito></EsitoCommittente></NotificaEsito>')

    receipt = parse_sdi_receipt(esito)
    assert receipt.positive is False
    assert receipt.to_notification().target_state() is InvoiceState.REJECTED


def test_a_customer_acceptance_is_positive():
    esito = ('<NotificaEsito><IdentificativoSdI>9</IdentificativoSdI>'
             '<EsitoCommittente><Esito>EC01</Esito></EsitoCommittente></NotificaEsito>')

    assert parse_sdi_receipt(esito).to_notification().target_state() is InvoiceState.ACCEPTED


@pytest.mark.parametrize("root,kind", sorted((k, v[0]) for k, v in SDI_RECEIPT_TYPES.items()))
def test_every_known_root_parses(root, kind):
    assert parse_sdi_receipt(f"<{root}><IdentificativoSdI>1</IdentificativoSdI></{root}>").kind == kind


def test_an_unrecognised_root_raises_instead_of_returning_none():
    """Chi passa un file qui si aspetta una ricevuta. Restituire ``None`` farebbe
    proseguire una riconciliazione su un documento che non è quello che crede."""
    with pytest.raises(ValidationError, match="non riconosciuta"):
        parse_sdi_receipt("<FatturaElettronica/>")


def test_broken_xml_is_a_validation_error_not_a_crash():
    with pytest.raises(ValidationError):
        parse_sdi_receipt("<non chiuso")


def test_an_unreadable_date_does_not_lose_the_receipt():
    """Una data che non si sa leggere non vale una ricevuta persa: gli errori
    servono comunque."""
    rotta = SCARTO.replace("2026-08-27T10:15:00.000+02:00", "27/08/2026 ore 10")

    receipt = parse_sdi_receipt(rotta)
    assert receipt.at is None
    assert len(receipt.errors) == 2


@pytest.mark.parametrize("name,kind", [
    ("IT12345678903_00001_NS_001.xml", "NS"),
    ("IT12345678903_00001_RC_001.xml", "RC"),
    ("IT12345678903_00001.xml", None),
    (None, None),
])
def test_the_filename_gives_the_kind_as_a_cross_check(name, kind):
    assert receipt_kind_from_filename(name) == kind
