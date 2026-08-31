"""Le ricevute SdI: leggere la risposta, non solo mandare la domanda.

Il pacchetto sapeva costruire la fattura, firmarla, trasmetterla e modellarne il
ciclo di vita — e non sapeva leggere l'unica cosa che torna indietro. Le
ricevute arrivano come file XML (dal provider, dalla PEC, o scaricate dal
portale) e ogni integrazione se le riparsava per conto suo, che è la
duplicazione che questo pacchetto esiste per togliere.

    from einvoice.notifications import parse_sdi_receipt

    notifica = parse_sdi_receipt(open("IT01234567890_00001_NS_001.xml").read())
    notifica.type          # NotificationType.REJECTED
    notifica.errors        # [SdiError(code="00404", description="Fattura duplicata")]
    lifecycle.apply(notifica)

**Perché conta più di quanto sembri.** Su una notifica di scarto (NS) il codice
d'errore è il dato più utile dell'intero flusso: dice *perché* la fattura è
stata rifiutata, e senza si ricomincia a tentativi. Il resto — identificativo
SdI, nome file, data — serve a riconciliare, ma è il codice che fa ripartire il
lavoro.

**Sul formato.** I nomi degli elementi sono quelli delle specifiche SdI; il
*namespace* no, perché non è affidabile: alcuni intermediari lo riscrivono,
altri lo tolgono del tutto, e un parser che lo pretendesse fallirebbe su file
perfettamente validi. Qui si guarda il nome locale della radice, come già fa il
lettore FatturaPA per lo stesso motivo.

I campi opzionali restano opzionali. Una ricevuta a cui manca un elemento non è
un errore: è una ricevuta di un tipo che quell'elemento non lo porta, oppure di
un intermediario che lo omette. Sollevare qui bloccherebbe la riconciliazione
per un dato che spesso non serve.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from xml.etree import ElementTree as ET

from .enums import NotificationType
from .errors import ValidationError
from .lifecycle import Notification

__all__ = [
    "SdiError",
    "SdiReceipt",
    "SDI_RECEIPT_TYPES",
    "parse_sdi_receipt",
    "receipt_kind_from_filename",
]

#: Nome locale della radice → tipo normalizzato.
#:
#: Le sigle sono quelle che SdI usa anche nel nome file (``..._NS_001.xml``).
SDI_RECEIPT_TYPES: dict[str, tuple[str, NotificationType]] = {
    "RicevutaConsegna": ("RC", NotificationType.DELIVERED),
    "NotificaScarto": ("NS", NotificationType.REJECTED),
    "NotificaMancataConsegna": ("MC", NotificationType.NOT_DELIVERED),
    "NotificaEsito": ("NE", NotificationType.OUTCOME),
    "NotificaDecorrenzaTermini": ("DT", NotificationType.DEADLINE_PASSED),
    "AttestazioneTrasmissioneFattura": ("AT", NotificationType.RECEIPT),
    "EsitoCommittente": ("EC", NotificationType.CUSTOMER_OUTCOME),
    "NotificaEsitoCommittente": ("EC", NotificationType.CUSTOMER_OUTCOME),
    "RicevutaScarto": ("NS", NotificationType.REJECTED),
}

#: ``IT01234567890_00001_NS_001.xml`` → ``NS``.
_FILENAME_KIND = re.compile(
    r"_(RC|NS|MC|NE|DT|AT|EC)_", re.IGNORECASE
)


@dataclass(frozen=True)
class SdiError:
    """Un errore dentro una notifica di scarto.

    ``code`` è il dato che fa ripartire il lavoro: i codici SdI sono stabili e
    documentati, e su quelli si costruisce una risposta automatica (rinumerare,
    correggere il codice destinatario, non ritrasmettere un duplicato).
    ``description`` è per una persona e cambia formulazione fra versioni.
    """

    code: str
    description: str = ""
    suggestion: str = ""

    def __str__(self) -> str:
        return f"[{self.code}] {self.description}" if self.description else f"[{self.code}]"


@dataclass
class SdiReceipt:
    """Una ricevuta SdI, letta."""

    kind: str                       # RC | NS | MC | NE | DT | AT | EC
    type: NotificationType
    sdi_id: str | None = None       # IdentificativoSdI
    filename: str | None = None     # NomeFile della fattura a cui si riferisce
    message_id: str | None = None
    at: datetime | None = None
    #: Esito positivo. Ha senso solo su NE / EC; altrove segue il tipo.
    positive: bool = True
    errors: list[SdiError] = field(default_factory=list)
    note: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_notification(self) -> Notification:
        """La forma che il ciclo di vita sa applicare."""
        return Notification(
            type=self.type,
            positive=self.positive,
            sdi_id=self.sdi_id,
            message=self.note or (str(self.errors[0]) if self.errors else None),
            at=self.at,
            raw=self.raw,
        )


def receipt_kind_from_filename(name: str | None) -> str | None:
    """La sigla dal nome file, quando la radice non basta.

    Serve come conferma, non come fonte: il nome file si rinomina, la radice no.
    """
    if not name:
        return None
    found = _FILENAME_KIND.search(name)
    return found.group(1).upper() if found else None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_text(root: ET.Element, *names: str) -> str | None:
    """Il primo elemento con uno di questi nomi locali, a qualunque profondità.

    Namespace-agnostica di proposito: vedi il docstring del modulo.
    """
    wanted = {n.lower() for n in names}
    for el in root.iter():
        if _local(el.tag).lower() not in wanted:
            continue
        text = (el.text or "").strip()
        if text:
            return text
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        # Alcuni intermediari mandano ``YYYY-MM-DDTHH:MM:SS.mmm`` troncato o con
        # il fuso attaccato senza due punti. Una data illeggibile non vale una
        # ricevuta persa: si tiene il resto.
        return None


def parse_sdi_receipt(xml: bytes | str) -> SdiReceipt:
    """Legge una ricevuta SdI e la normalizza.

    :raises ValidationError: la radice non è una ricevuta riconosciuta. È
        deliberatamente un errore e non un ``None``: chi passa qui un file si
        aspetta una ricevuta, e restituire ``None`` farebbe proseguire un flusso
        di riconciliazione su un documento che non è quello che crede.
    """
    try:
        root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except ET.ParseError as exc:
        raise ValidationError(f"Ricevuta SdI: XML non valido ({exc})") from exc

    name = _local(root.tag)
    entry = SDI_RECEIPT_TYPES.get(name)
    if entry is None:
        raise ValidationError(
            f"Ricevuta SdI: radice {name!r} non riconosciuta. "
            f"Attese: {', '.join(sorted(SDI_RECEIPT_TYPES))}"
        )
    kind, notification_type = entry

    errors: list[SdiError] = []
    for el in root.iter():
        if _local(el.tag) != "Errore":
            continue
        code = _find_text(el, "Codice") or ""
        if code:
            errors.append(SdiError(
                code=code,
                description=_find_text(el, "Descrizione") or "",
                suggestion=_find_text(el, "Suggerimento") or "",
            ))

    esito = (_find_text(root, "Esito") or "").upper()
    # EC/NE portano l'esito del committente: EC01 accettato, EC02 rifiutato.
    positive = notification_type not in (NotificationType.OUTCOME,
                                         NotificationType.CUSTOMER_OUTCOME) or \
        esito in ("", "EC01", "ACCETTATO")

    filename = _find_text(root, "NomeFile")
    receipt = SdiReceipt(
        kind=kind,
        type=notification_type,
        sdi_id=_find_text(root, "IdentificativoSdI"),
        filename=filename,
        message_id=_find_text(root, "MessageId", "MessageIdCommittente"),
        at=_parse_datetime(_find_text(root, "DataOraRicezione", "DataOraConsegna",
                                      "DataMessaMessaADisposizione", "DataOraTrasmissione")),
        positive=positive,
        errors=errors,
        note=_find_text(root, "Note", "Descrizione") if not errors else None,
        raw={"root": name, "esito": esito or None},
    )

    declared = receipt_kind_from_filename(filename)
    if declared and declared != kind:
        # Non è un errore — il NomeFile è quello della FATTURA, non della
        # ricevuta — ma quando coincide vale la pena tenerlo, e quando diverge
        # vale la pena poterlo vedere invece di scoprirlo dopo.
        receipt.raw["filename_kind"] = declared
    return receipt
