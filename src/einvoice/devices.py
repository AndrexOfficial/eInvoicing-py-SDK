"""Registratori di cassa e software certificato, paese per paese.

Il pacchetto sapeva rispondere a «come si trasmette una fattura in Portogallo»
e non a «mi serve un registratore di cassa per vendere al banco a Lisbona»,
che per un prodotto di punto vendita è metà della domanda. Le due cose sono
regimi distinti: la Germania non ha fatturazione elettronica B2C obbligatoria
ma pretende una TSE su ogni cassa; il Regno Unito non pretende né l'una né
l'altra.

    from einvoice.devices import device_regime

    device_regime("IT").device_name      # 'Registratore Telematico (RT)'
    device_regime("IT").pos_link_required  # True — dal 1° gennaio 2026
    device_regime("CZ").requirement      # 'none' — EET abolita nel 2023

**Sui dati.** Valgono le stesse regole del resto del pacchetto: sono
**orientamento operativo, non consulenza fiscale**, sono datati da
:data:`FISCAL_DEVICES_VERIFIED_AS_OF`, e un paese di cui non sappiamo
abbastanza dichiara ``"unknown"`` invece di una risposta plausibile. Le soglie
di fatturato, le esenzioni di settore e le proroghe cambiano in continuazione:
questa tabella dice *che tipo di regime* esiste, non se il tuo caso specifico
ci rientra.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

__all__ = [
    "FiscalDeviceRegime",
    "FISCAL_DEVICE_REGIMES",
    "FISCAL_DEVICES_VERIFIED_AS_OF",
    "REQUIREMENT_KINDS",
    "REPORTING_KINDS",
    "device_regime",
    "countries_requiring_a_device",
    "CONNECTIONS",
    "DEVICE_CAPABILITIES",
    "FiscalDeviceModel",
    "PosTerminal",
    "FISCAL_DEVICE_MODELS",
    "POS_TERMINALS",
    "fiscal_device_model",
    "pos_terminal",
    "devices_for_country",
    "terminals_for_country",
]

#: Quando questa tabella è stata confrontata con le fonti nazionali.
FISCAL_DEVICES_VERIFIED_AS_OF = date(2026, 8, 27)

#: Cosa impone il paese a chi vende al banco.
REQUIREMENT_KINDS = {
    "device": "Dispositivo fiscale omologato obbligatorio",
    "sector": "Obbligo limitato ad alcuni settori o sopra soglia",
    "software": "Nessun dispositivo, ma software di cassa certificato/attestato",
    "none": "Nessun obbligo di dispositivo né di certificazione del software",
    "unknown": "Non coperto da questa tabella",
}

#: Come i corrispettivi arrivano al fisco.
REPORTING_KINDS = {
    "realtime": "Ogni scontrino, al momento",
    "daily": "Chiusura giornaliera",
    "periodic": "Invio periodico (dichiarativo o su richiesta)",
    "none": "Nessuna trasmissione dedicata",
    "unknown": "Non coperto da questa tabella",
}


@dataclass(frozen=True)
class FiscalDeviceRegime:
    """Il regime di cassa di un paese."""

    country: str
    requirement: str
    reporting: str
    #: Come lo chiama il paese. Vuoto dove non esiste un dispositivo.
    device_name: str = ""
    #: Il software di cassa deve essere certificato/attestato da qualcuno.
    certified_software: bool | None = None
    #: Lotteria degli scontrini attiva.
    receipt_lottery: bool = False
    #: Il terminale di pagamento va collegato al dispositivo fiscale.
    pos_link_required: bool = False
    pos_link_since: date | None = None
    notes: str = ""

    @property
    def needs_a_device(self) -> bool:
        return self.requirement in ("device", "sector")


def _unknown(code: str) -> FiscalDeviceRegime:
    return FiscalDeviceRegime(
        country=code, requirement="unknown", reporting="unknown",
        notes="Regime di cassa non verificato per questo paese: chiedi "
              "all'amministrazione finanziaria nazionale prima di installare.",
    )


FISCAL_DEVICE_REGIMES: dict[str, FiscalDeviceRegime] = {
    "IT": FiscalDeviceRegime(
        "IT", "device", "daily", device_name="Registratore Telematico (RT)",
        certified_software=True, receipt_lottery=True,
        pos_link_required=True, pos_link_since=date(2026, 1, 1),
        notes="L'RT emette il documento commerciale e trasmette i corrispettivi "
              "alla chiusura giornaliera. Dal 1° gennaio 2026 il terminale di "
              "pagamento va collegato al registratore telematico. La fattura "
              "emessa dopo un documento commerciale deve citarlo, altrimenti la "
              "stessa vendita risulta due volte — vedi einvoice.pos.",
    ),
    "DE": FiscalDeviceRegime(
        "DE", "device", "none", device_name="Technische Sicherheitseinrichtung (TSE)",
        certified_software=True,
        notes="KassenSichV: ogni cassa elettronica ha una TSE certificata BSI che "
              "firma le transazioni. Nessuna trasmissione in tempo reale, ma "
              "obbligo di scontrino (Belegausgabepflicht) e di comunicazione "
              "delle casse all'amministrazione.",
    ),
    "AT": FiscalDeviceRegime(
        "AT", "device", "none", device_name="Registrierkasse (RKSV)",
        certified_software=True,
        notes="RKSV: cassa con unità di firma, catena di scontrini e QR code. "
              "Obbligo sopra soglie di fatturato; controllo periodico via "
              "FinanzOnline.",
    ),
    "HR": FiscalDeviceRegime(
        "HR", "device", "realtime", device_name="Fiskalizacija",
        certified_software=True,
        notes="Ogni scontrino è fiscalizzato in tempo reale e torna con JIR; il "
              "codice ZKI si stampa sul documento.",
    ),
    "SI": FiscalDeviceRegime(
        "SI", "device", "realtime", device_name="Davčno potrjevanje računov",
        certified_software=True,
        notes="Conferma fiscale in tempo reale di ogni ricevuta, con EOR e ZOI "
              "stampati sul documento.",
    ),
    "SK": FiscalDeviceRegime(
        "SK", "device", "realtime", device_name="eKasa",
        certified_software=True,
        notes="Ogni ricevuta passa dal sistema eKasa dell'amministrazione "
              "finanziaria e torna con un codice di ricevuta.",
    ),
    "HU": FiscalDeviceRegime(
        "HU", "device", "realtime", device_name="Online pénztárgép",
        certified_software=True,
        notes="Registratori collegati in permanenza al NAV. Da tenere distinto "
              "dal reporting fatture, che è un obbligo separato.",
    ),
    "PL": FiscalDeviceRegime(
        "PL", "device", "realtime", device_name="Kasa fiskalna online",
        certified_software=True, receipt_lottery=True,
        notes="Casse online che trasmettono al Centralne Repozytorium Kas; "
              "l'obbligo è entrato per settori successivi.",
    ),
    "RO": FiscalDeviceRegime(
        "RO", "device", "periodic", device_name="Aparat de marcat electronic fiscal (AMEF)",
        certified_software=True, receipt_lottery=True,
        notes="Casse con giornale elettronico e invio periodico dei dati "
              "all'ANAF; distinto da e-Factura, che riguarda le fatture.",
    ),
    "BG": FiscalDeviceRegime(
        "BG", "device", "realtime", device_name="Фискално устройство",
        certified_software=True,
        notes="Dispositivi fiscali collegati all'Agenzia nazionale delle entrate; "
              "requisiti aggiuntivi (SUPTO) per il software gestionale.",
    ),
    "GR": FiscalDeviceRegime(
        "GR", "device", "realtime", device_name="ΦΗΜ / ταμειακή μηχανή",
        certified_software=True, pos_link_required=True,
        notes="Meccanismi fiscali con trasmissione dei corrispettivi; il "
              "collegamento fra terminale di pagamento e cassa è obbligatorio. "
              "myDATA è un obbligo separato sui documenti.",
    ),
    "LT": FiscalDeviceRegime(
        "LT", "device", "periodic", device_name="Kasos aparatas",
        certified_software=True,
        notes="Registratori di cassa omologati; l'infrastruttura di raccolta "
              "(i.EKA) sta sostituendo l'invio periodico — verifica lo stato "
              "corrente prima di installare.",
    ),
    "LV": FiscalDeviceRegime(
        "LV", "device", "periodic", device_name="Kases aparāts",
        certified_software=True,
        notes="Casse registrate presso il VID con requisiti tecnici omologati.",
    ),
    "SE": FiscalDeviceRegime(
        "SE", "device", "none", device_name="Kassaregister med kontrollenhet",
        certified_software=True,
        notes="Cassa con unità di controllo certificata; nessuna trasmissione, "
              "il controllo è in loco.",
    ),
    "BE": FiscalDeviceRegime(
        "BE", "sector", "none", device_name="Geregistreerd kassasysteem (SCE / «black box»)",
        certified_software=True,
        notes="Obbligo nel settore horeca sopra soglia di fatturato da "
              "ristorazione; fuori da quel perimetro non serve.",
    ),
    "DK": FiscalDeviceRegime(
        "DK", "sector", "none", device_name="Digitalt salgsregistreringssystem",
        certified_software=True,
        notes="Sistema di registrazione digitale delle vendite richiesto nei "
              "settori a rischio (ristorazione, chioschi); non generalizzato.",
    ),
    "PT": FiscalDeviceRegime(
        "PT", "software", "periodic", certified_software=True,
        notes="Nessun dispositivo: il software di fatturazione dev'essere "
              "certificato dall'AT. Ogni documento porta ATCUD e QR code, e i "
              "dati vanno nel SAF-T PT.",
    ),
    "FR": FiscalDeviceRegime(
        "FR", "software", "none", certified_software=True,
        notes="Nessun dispositivo fiscale: il software di cassa dev'essere "
              "certificato o attestato (loi anti-fraude TVA). La riforma della "
              "fatturazione B2B è un obbligo distinto.",
    ),
    "ES": FiscalDeviceRegime(
        "ES", "software", "realtime", certified_software=True,
        notes="Nessun dispositivo: obbligo sul software di fatturazione. "
              "TicketBAI nei territori forali (Paesi Baschi, Navarra) e "
              "VeriFactu nel regime comune, con calendari propri — verifica "
              "quale si applica alla tua sede.",
    ),
    "CZ": FiscalDeviceRegime(
        "CZ", "none", "none",
        notes="EET (elektronická evidence tržeb) abolita il 1° gennaio 2023: "
              "oggi non c'è obbligo di registratore né di trasmissione.",
    ),
    "NL": FiscalDeviceRegime("NL", "none", "none", notes="Nessun regime di cassa fiscale."),
    "IE": FiscalDeviceRegime("IE", "none", "none", notes="Nessun regime di cassa fiscale."),
    "FI": FiscalDeviceRegime("FI", "none", "none", notes="Nessun regime di cassa fiscale."),
    "EE": FiscalDeviceRegime("EE", "none", "none", notes="Nessun regime di cassa fiscale."),
    "LU": FiscalDeviceRegime("LU", "none", "none", notes="Nessun regime di cassa fiscale."),
    "GB": FiscalDeviceRegime(
        "GB", "none", "none",
        notes="Nessun dispositivo fiscale. Making Tax Digital riguarda i "
              "registri IVA, non la cassa.",
    ),
    "CH": FiscalDeviceRegime(
        "CH", "none", "none",
        notes="Nessun obbligo di registratore fiscale; valgono le regole "
              "generali di tenuta della contabilità.",
    ),
    "US": FiscalDeviceRegime(
        "US", "none", "none",
        notes="Nessun regime federale di cassa fiscale. Alcuni stati impongono "
              "requisiti propri sul record delle vendite: verifica lo stato.",
    ),
    # Non verificati: dichiararlo è l'unica risposta onesta.
    "CY": _unknown("CY"),
    "MT": _unknown("MT"),
}


def device_regime(code: str) -> FiscalDeviceRegime:
    """Il regime di cassa di un paese.

    A differenza di :func:`einvoice.reference.country_reference`, che solleva su
    un paese non supportato, qui un codice ignoto torna come ``"unknown"``:
    la domanda «mi serve un registratore?» ha una risposta utile anche quando è
    «non lo sappiamo, chiedi» — mentre un `KeyError` in mezzo a una schermata di
    configurazione non ne ha nessuna.
    """
    return FISCAL_DEVICE_REGIMES.get((code or "").upper(), _unknown((code or "").upper()))


def countries_requiring_a_device() -> list[str]:
    """I paesi dove serve un dispositivo omologato, anche solo per settore."""
    return sorted(c for c, r in FISCAL_DEVICE_REGIMES.items() if r.needs_a_device)


# ─────────────────────────────────────────────────  il ferro, per nome ──
#
# La domanda dopo «mi serve un registratore?» è «quale posso comprare». È una
# domanda di catalogo, e senza una risposta ognuno se la ricostruisce leggendo
# i listini dei fornitori — con l'esito prevedibile che due prodotti della
# stessa casa finiscono per credere cose diverse sullo stesso modello.
#
# **Questo pacchetto non parla con nessuna stampante e con nessun terminale.**
# Non c'è nessun driver qui dentro e non ce ne saranno: il trasporto verso il
# ferro è locale, dipende dalla rete della sala e va tenuto nel prodotto. Qui
# c'è l'anagrafica — chi produce cosa, che protocollo parla, come si collega e
# dove sta la documentazione — perché quella è la parte che non cambia da un
# prodotto all'altro.
#
# Vale la stessa regola dei preset di trasmissione: nessun endpoint inventato.
# `protocol` nomina il protocollo **come lo chiama il fornitore**; dove non
# esiste una specifica pubblica lo si dice, invece di far sembrare che basti
# aprire un socket.

#: Come il dispositivo si attacca a qualcosa.
CONNECTIONS = ("lan", "usb", "serial", "bluetooth", "cloud")

#: Cosa un dispositivo fiscale sa fare, oltre a stampare.
DEVICE_CAPABILITIES = (
    "receipt",     # documento commerciale
    "refund",      # reso
    "void",        # annullo
    "z_report",    # chiusura giornaliera
    "drawer",      # cassetto
    "lottery",     # codice lotteria sullo scontrino
    "invoice",     # fattura stampata dal dispositivo
)


@dataclass(frozen=True)
class FiscalDeviceModel:
    """Una famiglia di registratori/stampanti fiscali."""

    key: str
    vendor: str
    models: tuple[str, ...]
    countries: tuple[str, ...]
    protocol: str
    connection: tuple[str, ...]
    capabilities: tuple[str, ...] = ()
    #: La chiave con cui un host chiama convenzionalmente il proprio driver.
    #: È un suggerimento di nomenclatura, non una promessa che esista.
    driver_hint: str | None = None
    #: Il protocollo è documentato pubblicamente o serve l'SDK del fornitore.
    public_protocol: bool = False
    #: Emette documenti fiscali. Falso per le termiche da scontrino di cortesia.
    fiscal: bool = True
    docs_url: str = ""
    notes: str = ""


@dataclass(frozen=True)
class PosTerminal:
    """Una famiglia di terminali di pagamento."""

    key: str
    vendor: str
    models: tuple[str, ...]
    countries: tuple[str, ...]
    #: ``cloud_api`` (il server chiede, il terminale esegue), ``terminal_api``
    #: (protocollo diretto sul terminale, spesso in LAN), ``device_sdk`` (la
    #: app gira **sul** terminale Android), ``softpos`` (il telefono È il
    #: terminale), ``wallet`` (QR/app, nessun terminale fisico).
    integration: str
    connection: tuple[str, ...]
    countries_note: str = ""
    docs_url: str = ""
    notes: str = ""


FISCAL_DEVICE_MODELS: dict[str, FiscalDeviceModel] = {
    "epson_rt": FiscalDeviceModel(
        "epson_rt", "Epson", ("FP-81II", "FP-90III"), ("IT",),
        protocol="ePOS-Print Fiscal XML (HTTP su /cgi-bin/fpmate.cgi)",
        connection=("lan", "usb", "serial"),
        capabilities=("receipt", "refund", "void", "z_report", "drawer", "lottery"),
        driver_hint="fiscal_epson", public_protocol=True,
        docs_url="https://www.epson.it/",
        notes="Il modello più diffuso in Italia e l'unico con una specifica "
              "pubblicata per intero. Va messo in modalità di rete con "
              "l'estensione ePOS-Print Fiscal attiva, e il certificato RT lo "
              "installa un tecnico abilitato: non è una configurazione che si "
              "fa da soli.",
    ),
    "custom_rt": FiscalDeviceModel(
        "custom_rt", "Custom S.p.A.", ("Q3X", "KUBE II"), ("IT",),
        protocol="XML fiscale Custom (SDK Custom4Innovation), TCP 9100",
        connection=("lan", "usb"),
        capabilities=("receipt", "z_report", "drawer"),
        driver_hint="fiscal_custom",
        docs_url="https://www.custom.biz/",
        notes="Il firmware va portato in emulazione «XML»: fuori da quella "
              "modalità la stessa porta risponde con un protocollo diverso. "
              "I tag sono vicini a quelli Epson ma non identici.",
    ),
    "rch_rt": FiscalDeviceModel(
        "rch_rt", "RCH", ("Print!F", "ONDA", "ABC"), ("IT",),
        protocol="Protocollo RCH (SDK del produttore)",
        connection=("lan", "serial", "usb"),
        capabilities=("receipt", "z_report"),
        docs_url="https://www.rch.it/",
        notes="Diffuso nella panificazione e nella ristorazione veloce. La "
              "specifica si ottiene dal produttore: senza, non si parte.",
    ),
    "ditron_rt": FiscalDeviceModel(
        "ditron_rt", "Ditron", ("Quadra", "Labo"), ("IT",),
        protocol="Protocollo Ditron (SDK del produttore)",
        connection=("lan", "serial"),
        capabilities=("receipt", "z_report"),
        docs_url="https://www.ditron.it/",
    ),
    "olivetti_rt": FiscalDeviceModel(
        "olivetti_rt", "Olivetti", ("Nettuna", "Form 100"), ("IT",),
        protocol="Protocollo Olivetti (SDK del produttore)",
        connection=("lan", "serial", "usb"),
        capabilities=("receipt", "z_report"),
        docs_url="https://www.olivetti.com/",
    ),
    "swissbit_tse": FiscalDeviceModel(
        "swissbit_tse", "Swissbit", ("TSE microSD", "TSE USB"), ("DE",),
        protocol="TSE hardware (interfaccia a file/blocchi)",
        connection=("usb",),
        capabilities=(),
        docs_url="https://www.swissbit.com/",
        notes="Non è una stampante: è il modulo di sicurezza che firma le "
              "transazioni della cassa. Lo scontrino lo stampa una termica "
              "qualunque.",
    ),
    "fiskaly_tse": FiscalDeviceModel(
        "fiskaly_tse", "fiskaly", ("TSE cloud",), ("DE", "AT"),
        protocol="REST (TSE come servizio)",
        connection=("cloud",), capabilities=(),
        public_protocol=True,
        docs_url="https://developer.fiskaly.com/",
        notes="TSE senza hardware: la firma la fa un servizio. Utile dove la "
              "cassa è un tablet e non c'è dove infilare una microSD.",
    ),
    "escpos_generic": FiscalDeviceModel(
        "escpos_generic", "Epson / Star Micronics / Citizen / Bixolon",
        ("Epson TM-T20III", "Epson TM-T88VII", "Epson TM-m30III",
         "Star TSP143III", "Citizen CT-S310II", "Bixolon SRP-330II"),
        ("EU",),
        protocol="ESC/POS (TCP 9100)",
        connection=("lan", "usb", "bluetooth"),
        capabilities=("drawer",),
        driver_hint="escpos_network", public_protocol=True, fiscal=False,
        docs_url="https://reference.epson-biz.com/modules/ref_escpos/",
        notes="NON è un dispositivo fiscale. Stampa comande, preconti e copie "
              "di cortesia; un documento commerciale valido non può uscire da "
              "qui. Elencata perché è il ferro che in sala c'è comunque, e "
              "perché confonderla con un RT è l'errore che costa una sanzione.",
    ),
}


POS_TERMINALS: dict[str, PosTerminal] = {
    "stripe_terminal": PosTerminal(
        "stripe_terminal", "Stripe", ("BBPOS WisePOS E", "Reader S700", "Reader M2"),
        ("EU", "GB", "US"), integration="cloud_api", connection=("lan", "cloud"),
        docs_url="https://docs.stripe.com/terminal",
        notes="Il server crea l'intento e il lettore lo esegue: nessun SDK da "
              "installare in sala. La via più corta per partire.",
    ),
    "sumup": PosTerminal(
        "sumup", "SumUp", ("Air", "Solo", "Solo Lite"), ("EU", "GB"),
        integration="cloud_api", connection=("bluetooth", "cloud"),
        docs_url="https://developer.sumup.com/",
        notes="Diffuso fra ambulanti e piccoli esercizi; Air richiede un "
              "telefono a fare da ponte, Solo è autonomo.",
    ),
    "nexi": PosTerminal(
        "nexi", "Nexi", ("SmartPOS (PAX A920)", "SoftPOS"), ("IT",),
        integration="device_sdk", connection=("cloud", "lan"),
        docs_url="https://developer.nexi.it/",
        notes="Lo SmartPOS è un Android: l'integrazione più solida è una app "
              "che gira **sul** terminale, non un server che lo comanda.",
    ),
    "adyen": PosTerminal(
        "adyen", "Adyen", ("P400", "V400m", "S1E2L"), ("EU", "GB", "US"),
        integration="terminal_api", connection=("lan", "cloud"),
        docs_url="https://docs.adyen.com/point-of-sale/",
        notes="Terminal API funziona sia in locale sia via cloud; la locale "
              "sopravvive a una linea che cade, ed è il motivo per preferirla "
              "in sala.",
    ),
    "worldline": PosTerminal(
        "worldline", "Worldline (ex Ingenico, ex SIX)",
        ("YOMANI", "YOXIMO", "Move/5000", "Desk/5000", "VALINA"),
        ("EU", "CH"), integration="terminal_api", connection=("lan", "cloud"),
        docs_url="https://docs.direct.worldline-solutions.com/",
        countries_note="VALINA passa da Saferpay ed è la via svizzera.",
        notes="Più famiglie di terminali con vie di integrazione diverse: "
              "prima di scrivere codice, stabilisci quale hai in mano.",
    ),
    "pax": PosTerminal(
        "pax", "PAX Technology", ("A920", "A80", "IM30"), ("EU", "global"),
        integration="device_sdk", connection=("cloud", "lan"),
        docs_url="https://www.paxtechnology.com/",
        notes="Il ferro sotto molti SmartPOS di marca (Nexi fra gli altri): "
              "l'acquirer cambia, l'hardware no.",
    ),
    "verifone": PosTerminal(
        "verifone", "Verifone", ("V240m", "P400", "T650"), ("EU", "global"),
        integration="device_sdk", connection=("lan", "cloud"),
        docs_url="https://developer.verifone.com/",
    ),
    "zettle": PosTerminal(
        "zettle", "Zettle (PayPal)", ("Reader 2", "Terminal"), ("EU", "GB"),
        integration="device_sdk", connection=("bluetooth",),
        docs_url="https://developer.zettle.com/",
    ),
    "satispay": PosTerminal(
        "satispay", "Satispay", ("QR / app",), ("IT", "EU"),
        integration="wallet", connection=("cloud",),
        docs_url="https://developers.satispay.com/",
        notes="Non è un terminale: è un portafoglio. Nessun ferro da "
              "acquistare, e nessun collegamento all'RT da cablare — il che "
              "non lo esonera dall'obbligo di tracciamento dell'incasso.",
    ),
}


def fiscal_device_model(key: str) -> FiscalDeviceModel | None:
    """Una famiglia di dispositivi, o ``None`` se non è a catalogo."""
    return FISCAL_DEVICE_MODELS.get((key or "").lower())


def pos_terminal(key: str) -> PosTerminal | None:
    """Una famiglia di terminali, o ``None`` se non è a catalogo."""
    return POS_TERMINALS.get((key or "").lower())


def devices_for_country(code: str) -> list[FiscalDeviceModel]:
    """I dispositivi utilizzabili in un paese, quelli che lo nominano prima.

    Un dispositivo omologato in Italia non lo è in Germania: l'omologazione è
    nazionale, e un catalogo che mescolasse i due manderebbe qualcuno a
    comprare un RT per un negozio di Monaco.
    """
    country = (code or "").upper()
    named = [d for d in FISCAL_DEVICE_MODELS.values() if country in d.countries]
    generic = [d for d in FISCAL_DEVICE_MODELS.values()
               if country not in d.countries and "EU" in d.countries]
    return named + generic


def terminals_for_country(code: str) -> list[PosTerminal]:
    """I terminali utilizzabili in un paese, quelli che lo nominano prima."""
    country = (code or "").upper()
    named = [t for t in POS_TERMINALS.values() if country in t.countries]
    wide = [t for t in POS_TERMINALS.values()
            if country not in t.countries and {"EU", "global"} & set(t.countries)]
    return named + wide
