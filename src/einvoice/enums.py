"""Shared enumerations and code lists.

Country-neutral where possible; IT-specific value lists carry helpers to map
onto the European code lists (UNCL) used by UBL / EN 16931.
"""
from __future__ import annotations

from enum import Enum


class TransmissionFormat(str, Enum):
    PRIVATE = "FPR12"          # FatturaPA B2B/B2C
    PA = "FPA12"               # FatturaPA Pubblica Amministrazione


class DocumentType(str, Enum):
    """Italian ``TipoDocumento`` (specifiche 1.2.2, lista completa TD01–TD06 +
    TD16–TD28); ``.uncl1001`` maps to the EN 16931 type code (UNCL 1001) used
    by UBL/CII.

    Mapping rationale: 380 (commercial invoice) for ordinary invoices,
    self-invoices and the TD16–TD19 "integrazioni" (which on the EU side are
    plain invoices issued by the buyer); 381 for credit notes (TD04);
    383 for debit notes (TD05); 386 for prepayment invoices (TD02/TD03).
    """

    INVOICE = "TD01"                       # fattura
    ADVANCE = "TD02"                       # acconto/anticipo su fattura
    ADVANCE_FEE = "TD03"                   # acconto/anticipo su parcella
    CREDIT_NOTE = "TD04"                   # nota di credito
    DEBIT_NOTE = "TD05"                    # nota di debito
    FEE = "TD06"                           # parcella
    REVERSE_CHARGE_INTERNAL = "TD16"       # integrazione fattura reverse charge interno
    SELF_INVOICE = "TD16"                  # alias storico di REVERSE_CHARGE_INTERNAL
    SELF_INVOICE_FOREIGN_SERVICES = "TD17"  # integrazione/autofattura servizi dall'estero
    INTRA_EU_GOODS = "TD18"                # integrazione beni intracomunitari
    SELF_INVOICE_ART17 = "TD19"            # integrazione/autofattura art. 17 c.2 DPR 633/72
    SELF_INVOICE_REGULARIZATION = "TD20"   # autofattura regolarizzazione (art. 6 c.8 D.lgs 471/97)
    SELF_INVOICE_PLAFOND = "TD21"          # autofattura splafonamento
    VAT_WAREHOUSE_EXTRACTION = "TD22"      # estrazione beni da deposito IVA
    VAT_WAREHOUSE_EXTRACTION_VAT = "TD23"  # estrazione beni da deposito IVA con versamento IVA
    DEFERRED_INVOICE = "TD24"              # fattura differita art. 21 c.4 lett. a
    DEFERRED_INVOICE_TRIANGULAR = "TD25"   # fattura differita art. 21 c.4 terzo periodo lett. b
    DEPRECIABLE_ASSETS = "TD26"            # cessione beni ammortizzabili / passaggi interni
    SELF_CONSUMPTION = "TD27"              # autoconsumo / cessioni gratuite senza rivalsa
    SAN_MARINO_PURCHASE = "TD28"           # acquisti da San Marino con IVA (fattura cartacea)

    @property
    def uncl1001(self) -> str:
        special = {
            "TD02": "386",   # prepayment invoice
            "TD03": "386",   # prepayment invoice
            "TD04": "381",   # credit note
            "TD05": "383",   # debit note
        }
        return special.get(self.value, "380")  # commercial invoice / self-billed

    @property
    def is_credit_note(self) -> bool:
        return self in (DocumentType.CREDIT_NOTE,)


class VatNature(str, Enum):
    """``Natura`` — required when the VAT rate is 0.

    Complete post-2021 list: the parent codes N2, N3 and N6 are no longer
    accepted by SdI, only the dotted sub-codes (plus N1, N4, N5, N7).

    ``.en16931_category`` maps onto the EN 16931 / UNCL 5305 VAT category:
    N3.1 exports → "G"; N3.2 intra-EU supplies → "K"; N6.* reverse charge →
    "AE"; N4 exempt → "E"; N1 (escluse art. 15), N2.* (non soggette) and N7 →
    "O" (outside scope of VAT). N3.3–N3.6 and N5 have no dedicated EN 16931
    category: they are zero-VAT regimes closest to an exemption on the EU side,
    so they map to "E" (with the legal reference carried in the exemption
    reason) — a pragmatic, documented choice.
    """

    EXCLUDED = "N1"                        # escluse ex art. 15
    NOT_SUBJECT_ART7 = "N2.1"              # non soggette ad IVA artt. 7–7-septies
    NOT_SUBJECT = "N2.2"                   # non soggette — altri casi
    NOT_TAXABLE_EXPORT = "N3.1"            # non imponibili — esportazioni
    NOT_TAXABLE = "N3.2"                   # non imponibili — cessioni intracomunitarie
    NOT_TAXABLE_SAN_MARINO = "N3.3"        # non imponibili — cessioni verso San Marino
    NOT_TAXABLE_EXPORT_ASSIMILATED = "N3.4"  # non imponibili — operazioni assimilate
    NOT_TAXABLE_DECLARATION_INTENT = "N3.5"  # non imponibili — dichiarazioni d'intento
    NOT_TAXABLE_OTHER = "N3.6"             # non imponibili — altre op. che non concorrono al plafond
    EXEMPT = "N4"                          # esenti
    MARGIN = "N5"                          # regime del margine / IVA non esposta
    REVERSE_CHARGE = "N6.1"                # inversione contabile — rottami
    REVERSE_CHARGE_GOLD = "N6.2"           # inversione contabile — oro e argento
    REVERSE_CHARGE_CONSTRUCTION_SUB = "N6.3"  # inversione contabile — subappalto edile
    REVERSE_CHARGE_BUILDINGS = "N6.4"      # inversione contabile — cessione fabbricati
    REVERSE_CHARGE_MOBILE_PHONES = "N6.5"  # inversione contabile — telefoni cellulari
    REVERSE_CHARGE_ELECTRONICS = "N6.6"    # inversione contabile — prodotti elettronici
    REVERSE_CHARGE_CONSTRUCTION = "N6.7"   # inversione contabile — comparto edile e connessi
    REVERSE_CHARGE_ENERGY = "N6.8"         # inversione contabile — settore energetico
    REVERSE_CHARGE_OTHER = "N6.9"          # inversione contabile — altri casi
    VAT_PAID_OTHER_EU = "N7"               # IVA assolta in altro Stato UE

    @property
    def en16931_category(self) -> str:
        code = self.value
        if code == "N3.1":
            return "G"    # export outside the EU
        if code == "N3.2":
            return "K"    # intra-community supply
        if code.startswith("N6"):
            return "AE"   # VAT reverse charge
        if code in ("N1", "N7") or code.startswith("N2"):
            return "O"    # outside the scope of VAT
        return "E"        # N4, N3.3–N3.6, N5 — exempt (or assimilated)

    @property
    def default_exemption_reason(self) -> str:
        """Short Italian legal reference, used as fallback for the UBL
        ``TaxExemptionReason`` and the FatturaPA ``RiferimentoNormativo``."""
        return {
            "N1": "Esclusa ex art. 15 DPR 633/72",
            "N2.1": "Non soggetta — artt. 7–7-septies DPR 633/72",
            "N2.2": "Non soggetta — altri casi",
            "N3.1": "Non imponibile — esportazione art. 8 DPR 633/72",
            "N3.2": "Non imponibile — cessione intracomunitaria art. 41 DL 331/93",
            "N3.3": "Non imponibile — cessione verso San Marino art. 71 DPR 633/72",
            "N3.4": "Non imponibile — operazione assimilata art. 8-bis DPR 633/72",
            "N3.5": "Non imponibile — dichiarazione d'intento art. 8 c.1 lett. c DPR 633/72",
            "N3.6": "Non imponibile — altra operazione che non concorre al plafond",
            "N4": "Esente art. 10 DPR 633/72",
            "N5": "Regime del margine / IVA non esposta art. 36 DL 41/95",
            "N6.1": "Inversione contabile — cessione di rottami art. 74 DPR 633/72",
            "N6.2": "Inversione contabile — cessione di oro e argento art. 17 c.5 DPR 633/72",
            "N6.3": "Inversione contabile — subappalto nel settore edile art. 17 c.6 lett. a",
            "N6.4": "Inversione contabile — cessione di fabbricati art. 17 c.6 lett. a-bis",
            "N6.5": "Inversione contabile — cessione di telefoni cellulari art. 17 c.6 lett. b",
            "N6.6": "Inversione contabile — cessione di prodotti elettronici art. 17 c.6 lett. c",
            "N6.7": "Inversione contabile — comparto edile e settori connessi art. 17 c.6 lett. a-ter",
            "N6.8": "Inversione contabile — operazioni settore energetico art. 17 c.6 lett. d-bis/ter/quater",
            "N6.9": "Inversione contabile — altri casi",
            "N7": "IVA assolta in altro Stato UE",
        }[self.value]


class PaymentMeans(str, Enum):
    """Italian ``ModalitaPagamento`` (lista completa MP01–MP23);
    ``.uncl4461`` maps to the EN 16931 payment means code.

    Where UNCL 4461 has no precise equivalent the generic fallback is
    97 ("clearing between partners" — usato come "altro"); MP06 maps to 60
    (promissory note, l'equivalente esatto del vaglia cambiario).
    """

    CASH = "MP01"                       # contanti
    CHEQUE = "MP02"                     # assegno
    BANKERS_DRAFT = "MP03"              # assegno circolare
    CASH_AT_TREASURY = "MP04"           # contanti presso tesoreria
    BANK_TRANSFER = "MP05"              # bonifico
    PROMISSORY_NOTE = "MP06"            # vaglia cambiario
    BANK_BULLETIN = "MP07"              # bollettino bancario
    CARD = "MP08"                       # carta di pagamento
    RID = "MP09"                        # RID
    RID_UTILITIES = "MP10"              # RID utenze
    RID_FAST = "MP11"                   # RID veloce
    RIBA = "MP12"                       # RIBA
    MAV = "MP13"                        # MAV
    TAX_OFFICE_RECEIPT = "MP14"         # quietanza erario
    SPECIAL_ACCOUNT_TRANSFER = "MP15"   # giroconto su conti di contabilità speciale
    BANK_DOMICILIATION = "MP16"         # domiciliazione bancaria
    POSTAL_DOMICILIATION = "MP17"       # domiciliazione postale
    POSTAL_BULLETIN = "MP18"            # bollettino di c/c postale
    SEPA_DD = "MP19"                    # SEPA Direct Debit
    SEPA_DD_CORE = "MP20"               # SEPA Direct Debit CORE
    SEPA_DD_B2B = "MP21"                # SEPA Direct Debit B2B
    WITHHELD_ON_SUMS = "MP22"           # trattenuta su somme già riscosse
    PAGOPA = "MP23"                     # PagoPA

    @property
    def uncl4461(self) -> str:
        return {
            "MP01": "10",   # in cash
            "MP02": "20",   # cheque
            "MP03": "20",   # cheque (banker's draft)
            "MP04": "10",   # in cash (treasury)
            "MP05": "30",   # credit transfer
            "MP06": "60",   # promissory note
            "MP07": "97",   # clearing between partners (fallback "altro")
            "MP08": "48",   # bank card
            "MP09": "49",   # direct debit
            "MP10": "49",   # direct debit
            "MP11": "49",   # direct debit
            "MP12": "49",   # direct debit (RIBA)
            "MP13": "97",   # fallback "altro" (MAV)
            "MP14": "97",   # fallback "altro" (quietanza erario)
            "MP15": "42",   # payment to bank account
            "MP16": "49",   # direct debit
            "MP17": "49",   # direct debit
            "MP18": "97",   # fallback "altro" (bollettino postale)
            "MP19": "59",   # SEPA direct debit
            "MP20": "59",   # SEPA direct debit
            "MP21": "59",   # SEPA direct debit
            "MP22": "97",   # fallback "altro" (trattenuta)
            "MP23": "68",   # online payment service (PagoPA)
        }[self.value]


class VatExigibility(str, Enum):
    """``EsigibilitaIVA`` — VAT chargeability."""

    IMMEDIATE = "I"
    DEFERRED = "D"
    SPLIT_PAYMENT = "S"


#: ``RegimeFiscale`` ammessi (specifiche 1.2.2+): RF03 è stato ritirato;
#: RF20 (regime transfrontaliero di franchigia IVA, dir. UE 2020/285) è stato
#: aggiunto dalle specifiche 1.9 in vigore dal 2025.
REGIMI_FISCALI = frozenset(
    {"RF01", "RF02"}
    | {f"RF{n:02d}" for n in range(4, 20)}
    | {"RF20"}
)


class WithholdingType(str, Enum):
    """``TipoRitenuta``."""

    NATURAL_PERSON = "RT01"
    LEGAL_PERSON = "RT02"
    INPS = "RT03"
    ENASARCO = "RT04"
    ENPAM = "RT05"
    OTHER = "RT06"


class InvoiceState(str, Enum):
    """Unified lifecycle, channel-agnostic."""

    DRAFT = "draft"
    VALIDATED = "validated"
    SIGNED = "signed"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"          # consegnata al destinatario
    ACCEPTED = "accepted"            # esito positivo committente / consegnata
    REJECTED = "rejected"            # scartata da SDI / esito negativo
    NOT_DELIVERED = "not_delivered"  # mancata consegna (messa a disposizione)
    ARCHIVED = "archived"            # in conservazione
    CANCELLED = "cancelled"
    FAILED = "failed"                # errore di trasporto/rendering


class NotificationType(str, Enum):
    """Normalized SDI / PEPPOL outcomes (esiti). The IT SDI code is in
    parentheses for reference."""

    DELIVERED = "delivered"              # RC ricevuta di consegna
    REJECTED = "rejected"                # NS notifica di scarto
    NOT_DELIVERED = "not_delivered"      # MC mancata consegna
    OUTCOME = "outcome"                  # NE notifica esito (PA)
    DEADLINE_PASSED = "deadline_passed"  # DT decorrenza termini
    CUSTOMER_OUTCOME = "customer_outcome"  # EC esito committente
    RECEIPT = "receipt"                  # generic acknowledgement
