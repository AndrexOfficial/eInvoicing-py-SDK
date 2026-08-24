"""Named presets for e-invoicing platforms — Fiscozen, Storecove, Chorus Pro, …

A :class:`~einvoice.transport.base.Transport` needs a base URL, an auth scheme
and a set of field names. Working those out for each vendor is the tedious part
of an integration, and getting one wrong fails at the worst moment. A preset
records that knowledge once:

    from einvoice.transport import transport_for_provider

    t = transport_for_provider("fiscozen", api_key="…",
                               base_url="https://…")   # per-account host
    await t.transmit(rendered, invoice)

Each preset states which **renderer** to pair with it, which **credentials** it
needs, and — the field that matters most — whether its endpoints are
:attr:`~ProviderPreset.endpoints_verified`.

**Why that flag exists.** Most of these vendors publish their API contract only
to account holders, and several change paths between plan tiers. Shipping a
confident-looking URL for an endpoint nobody here has called would produce a
library that looks integrated and fails on first use, which is worse than one
that says "supply your base_url and check these two field names". So:

``endpoints_verified=True``
    The flow is implemented against a published contract and exercised by the
    package's own tests.
``endpoints_verified=False``
    The *shape* is right — this is the transport and these are the credentials
    — but confirm the paths against your account's documentation before going
    live. ``base_url`` is usually required from you for exactly this reason.

Adding a platform is a dict entry, not a module, whenever it follows the common
"POST base64 XML, poll a document endpoint" REST shape. Write a dedicated
:class:`Transport` only when the flow genuinely differs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import ProviderConfigError
from .base import Transport, TransportConfig
from .registry import get_transport

__all__ = [
    "ProviderPreset",
    "PROVIDER_PRESETS",
    "PROVIDER_KINDS",
    "available_providers",
    "preset_for",
    "transport_for_provider",
    "providers_for_country",
    "providers_of_kind",
]


#: What kind of thing a platform *is*. With sixty-odd entries a flat list stops
#: being navigable, and the kinds differ in ways that change the integration:
#: an access point routes a document you rendered, a national portal imposes its
#: own syntax, an accounting platform owns the invoice's whole life.
PROVIDER_KINDS = {
    "access_point": "Peppol Access Point / rete di interscambio",
    "sdi_intermediary": "Intermediario SdI (Italia)",
    "national_portal": "Portale nazionale obbligatorio",
    "accounting_platform": "Gestionale / piattaforma di contabilità",
    "compliance_suite": "Suite di compliance fiscale multi-paese",
}


@dataclass(frozen=True)
class ProviderPreset:
    """How to talk to one e-invoicing platform."""

    key: str
    name: str
    #: Markets served, most relevant first. ``"EU"`` / ``"global"`` for
    #: aggregators that are not tied to one country.
    countries: tuple[str, ...]
    #: Key in the transport registry (``hub``, ``aruba``, ``peppol``, …).
    transport: str
    #: One of :data:`PROVIDER_KINDS`.
    kind: str = "access_point"
    #: Renderer to pair with it — sending FatturaPA to a Peppol AP is a
    #: rejection, and vice versa.
    renderer: str = "ubl"
    #: Credential keys the caller must supply.
    credentials: tuple[str, ...] = ("api_key",)
    #: What the integration can do here. ``receive`` means the platform can
    #: hand you inbound documents — increasingly the half that is mandatory.
    supports: tuple[str, ...] = ("send", "status")
    base_url: str | None = None
    sandbox_url: str | None = None
    docs_url: str = ""
    extra: dict = field(default_factory=dict)
    #: See the module docstring — this is the honest bit.
    endpoints_verified: bool = False
    notes: str = ""

    @property
    def country(self) -> str:
        """Primary market. Kept because it reads better at a call site than
        ``countries[0]`` and most presets serve exactly one."""
        return self.countries[0]

    @property
    def needs_base_url(self) -> bool:
        """True when the account's host is not knowable in advance."""
        return self.base_url is None

    def serves(self, country_code: str) -> bool:
        """Whether this platform covers a country, directly or as an aggregator."""
        code = (country_code or "").upper()
        return code in self.countries or bool({"EU", "global"} & set(self.countries))

    def config(self, *, sandbox: bool = True, **credentials) -> TransportConfig:
        """Build a :class:`TransportConfig`, checking the caller supplied what
        this platform actually needs.

        Failing here — with the missing key named — beats failing inside an
        HTTP call with a 401 that could mean anything.
        """
        missing = [c for c in self.credentials if not credentials.get(c)]
        base_url = credentials.pop("base_url", None) or (
            self.sandbox_url if sandbox and self.sandbox_url else self.base_url
        )
        if self.needs_base_url and not base_url:
            missing.append("base_url")
        if missing:
            raise ProviderConfigError(
                f"{self.name}: credenziali mancanti: {', '.join(sorted(set(missing)))}. "
                f"Richieste: {', '.join(self.credentials)}"
                + ("" if not self.needs_base_url else " + base_url del tuo account")
                + (f". Documentazione: {self.docs_url}" if self.docs_url else "")
            )
        merged_extra = {**self.extra, **(credentials.pop("extra", None) or {})}
        return TransportConfig(
            name=self.key,
            base_url=base_url,
            api_key=credentials.get("api_key"),
            username=credentials.get("username"),
            password=credentials.get("password"),
            company_id=credentials.get("company_id"),
            sandbox=sandbox,
            timeout=float(credentials.get("timeout", 30.0)),
            extra=merged_extra,
        )


def _hub(key, name, countries, *, kind="access_point", creds=("api_key",), docs="",
         extra=None, renderer="ubl", base_url=None, supports=("send", "status"),
         notes="") -> ProviderPreset:
    """A preset running on the configurable REST hub — the honest default for a
    platform whose exact paths we have not called ourselves."""
    return ProviderPreset(
        key=key, name=name,
        countries=(countries,) if isinstance(countries, str) else tuple(countries),
        transport="hub", kind=kind, renderer=renderer, credentials=creds,
        supports=tuple(supports), base_url=base_url, docs_url=docs,
        extra=extra or {}, endpoints_verified=False, notes=notes,
    )


PROVIDER_PRESETS: dict[str, ProviderPreset] = {

    # ══ Italy — SdI intermediaries ═════════════════════════════════════
    "fiscozen": _hub(
        "fiscozen", "Fiscozen", "IT", kind="sdi_intermediary", renderer="fatturapa",
        docs="https://www.fiscozen.it/",
        extra={"upload_path": "/invoices", "content_field": "xml",
               "auth_scheme": "bearer"},
        notes="Piattaforma fiscale per partite IVA individuali: emette verso SdI "
              "per conto del cliente. Il contratto API è riservato ai titolari di "
              "account — chiedere a Fiscozen base_url e nomi dei campi, poi "
              "sovrascriverli in `extra`. Renderizzare FatturaPA, non UBL.",
    ),
    "aruba": ProviderPreset(
        key="aruba", name="Aruba Fatturazione Elettronica", countries=("IT",),
        transport="aruba", kind="sdi_intermediary", renderer="fatturapa",
        credentials=("username", "password"), supports=("send", "status", "notify"),
        base_url="https://ws.fatturazioneelettronica.aruba.it",
        sandbox_url="https://demows.fatturazioneelettronica.aruba.it",
        docs_url="https://fatturazioneelettronica.aruba.it/apidoc/docs.html",
        endpoints_verified=True,
        notes="Adapter dedicato: login → upload → stato. Host di autenticazione "
              "separato, override con extra['auth_url'].",
    ),
    "fattureincloud": ProviderPreset(
        key="fattureincloud", name="Fatture in Cloud (TeamSystem)", countries=("IT",),
        transport="fattureincloud_xml", kind="accounting_platform", renderer="fatturapa",
        credentials=("api_key", "company_id"), supports=("send", "status"),
        base_url="https://api-v2.fattureincloud.it",
        docs_url="https://developers.fattureincloud.it/",
        endpoints_verified=True,
        notes="Due integrazioni: 'fattureincloud' costruisce il documento dal "
              "modello, 'fattureincloud_xml' carica la FatturaPA già "
              "renderizzata — preferire la seconda se l'XML è il documento di "
              "riferimento.",
    ),
    "zucchetti": ProviderPreset(
        key="zucchetti", name="Zucchetti Digital Hub", countries=("IT",),
        transport="zucchetti", kind="sdi_intermediary", renderer="fatturapa",
        credentials=("api_key",), docs_url="https://www.zucchetti.it/",
        notes="base_url del Digital Hub specifico dell'installazione.",
    ),
    "infocert": _hub(
        "infocert", "InfoCert Legalinvoice HUB", "IT", kind="sdi_intermediary",
        renderer="fatturapa", docs="https://www.infocert.it/",
        extra={"upload_path": "/documents"},
        notes="Hub REST configurabile; confermare i path sul contratto."),
    "notartel": _hub(
        "notartel", "Notartel", "IT", kind="sdi_intermediary", renderer="fatturapa",
        creds=("username", "password"), extra={"auth_scheme": "basic"},
        docs="https://www.notartel.it/",
        notes="Richiede un contratto di intermediazione notarile."),
    "wolters_kluwer": _hub(
        "wolters_kluwer", "Wolters Kluwer Fattura SMART", "IT",
        kind="sdi_intermediary", renderer="fatturapa",
        docs="https://www.wolterskluwer.com/it-it",
        notes="Diffuso presso gli studi commercialisti."),
    "agyo": _hub(
        "agyo", "Agyo (TeamSystem)", "IT", kind="sdi_intermediary",
        renderer="fatturapa", docs="https://agyo.io/",
        supports=("send", "status", "receive"),
        notes="Piattaforma TeamSystem; API a contratto."),
    "namirial": _hub(
        "namirial", "Namirial", "IT", kind="sdi_intermediary", renderer="fatturapa",
        docs="https://www.namirial.it/",
        notes="Conservazione a norma inclusa nell'offerta."),
    "openapi_it": _hub(
        "openapi_it", "OpenAPI.it Fatturazione", "IT", kind="sdi_intermediary",
        renderer="fatturapa", base_url="https://ws.fatturazione.openapi.it",
        docs="https://fatturazione.openapi.it/",
        notes="API pubblica a consumo; confermare i path sulla doc corrente."),
    "credemtel": _hub(
        "credemtel", "Credemtel", "IT", kind="sdi_intermediary", renderer="fatturapa",
        docs="https://www.credemtel.it/",
        notes="Intermediario del gruppo Credem; diffuso nel manifatturiero."),
    "passepartout": _hub(
        "passepartout", "Passepartout", "IT", kind="accounting_platform",
        renderer="fatturapa", docs="https://www.passepartout.net/",
        supports=("send", "status", "receive"),
        notes="Gestionale con SdI integrato; API disponibile a contratto."),
    "danea": _hub(
        "danea", "Danea Easyfatt", "IT", kind="accounting_platform",
        renderer="fatturapa", docs="https://www.danea.it/",
        notes="Molto diffuso fra PMI e artigiani italiani."),
    "register_it": _hub(
        "register_it", "Register.it Fatturazione", "IT", kind="sdi_intermediary",
        renderer="fatturapa", docs="https://www.register.it/",
        notes="Offerta entry-level, spesso abbinata a PEC e domini."),

    # ══ Peppol access points / reti di interscambio ═════════════════════
    "storecove": _hub(
        "storecove", "Storecove", "EU", base_url="https://api.storecove.com/api/v2",
        docs="https://www.storecove.com/docs",
        supports=("send", "status", "receive"),
        extra={"upload_path": "/document_submissions", "auth_scheme": "bearer"},
        notes="Access Point Peppol con copertura EU/global e API REST "
              "documentata pubblicamente. Renderizzare UBL."),
    "pagero": _hub(
        "pagero", "Pagero", "global", docs="https://www.pagero.com/",
        supports=("send", "status", "receive"),
        notes="Rete globale; onboarding e credenziali a contratto."),
    "basware": _hub(
        "basware", "Basware", "global", docs="https://www.basware.com/",
        supports=("send", "status", "receive"),
        notes="Prevalentemente enterprise AP/AR."),
    "tradeshift": _hub(
        "tradeshift", "Tradeshift", "global", docs="https://developers.tradeshift.com/",
        supports=("send", "status", "receive"),
        notes="Access Point Peppol + rete propria."),
    "unifiedpost": _hub(
        "unifiedpost", "Unifiedpost / Banqup", ("BE", "NL", "EU"),
        docs="https://www.unifiedpost.com/",
        supports=("send", "status", "receive"),
        notes="Forte in BE/NL; utile per il mandato belga 2026."),
    "ecosio": _hub(
        "ecosio", "ecosio", ("AT", "DE", "EU"), docs="https://ecosio.com/",
        supports=("send", "status", "receive"),
        notes="EDI + Peppol Access Point, radici austriache."),
    "b2brouter": _hub(
        "b2brouter", "B2Brouter", ("ES", "IT", "EU"),
        base_url="https://app.b2brouter.net/api",
        docs="https://www.b2brouter.net/",
        supports=("send", "status", "receive"),
        notes="Peppol AP con buona copertura ES/IT; produce anche Facturae e "
              "FatturaPA, quindi è una via pratica dove il formato nazionale "
              "non è UBL."),
    "tickstar": _hub(
        "tickstar", "Tickstar (Basware)", ("SE", "EU"),
        docs="https://www.tickstar.com/",
        supports=("send", "status", "receive"),
        notes="Infrastruttura Peppol usata da altri provider come base."),
    "galaxygw": _hub(
        "galaxygw", "Galaxy Gateway", "EU", docs="https://galaxygw.com/",
        supports=("send", "status", "receive"),
        notes="Access Point Peppol per volumi medio-piccoli."),
    "qvalia": _hub(
        "qvalia", "Qvalia", ("SE", "EU"), docs="https://qvalia.com/",
        supports=("send", "status", "receive"),
        notes="Peppol AP nordico con servizi di riconciliazione."),
    "opuscapita": _hub(
        "opuscapita", "OpusCapita", ("FI", "SE", "NO", "EU"),
        docs="https://www.opuscapita.com/",
        supports=("send", "status", "receive"),
        notes="Rete di e-invoicing nordica, forte nel B2B enterprise."),
    "billit": _hub(
        "billit", "Billit", ("BE", "NL"), base_url="https://api.billit.be/v1",
        docs="https://api.billit.be/",
        supports=("send", "status", "receive"),
        notes="Molto usato in Belgio; rilevante per il mandato B2B 2026."),
    "logiq": _hub(
        "logiq", "Logiq", ("NO", "EU"), docs="https://www.logiq.no/",
        supports=("send", "status", "receive"),
        notes="Access Point norvegese (EHF/Peppol)."),
    "inexchange": _hub(
        "inexchange", "InExchange", ("SE",), docs="https://inexchange.se/",
        supports=("send", "status", "receive"),
        notes="Rete svedese di fatturazione elettronica."),
    "maventa": _hub(
        "maventa", "Maventa (Visma)", ("FI", "SE"),
        docs="https://maventa.com/", supports=("send", "status", "receive"),
        notes="Operatore finlandese del gruppo Visma; API REST documentata."),
    "apix": _hub(
        "apix", "Apix Messaging", ("FI",), docs="https://www.apix.fi/",
        supports=("send", "status", "receive"),
        notes="Operatore finlandese; usa Finvoice oltre a Peppol."),

    # ══ Piattaforme di contabilità / ERP ═══════════════════════════════
    "datev": _hub(
        "datev", "DATEV", ("DE",), kind="accounting_platform",
        docs="https://developer.datev.de/",
        supports=("send", "receive"),
        notes="Standard di fatto fra i commercialisti tedeschi: qualunque "
              "integrazione B2B in Germania prima o poi ci passa. API a "
              "contratto, OAuth2."),
    "sap_business_network": _hub(
        "sap_business_network", "SAP Business Network (Ariba)", "global",
        kind="accounting_platform", docs="https://help.sap.com/",
        supports=("send", "status", "receive"),
        notes="Rete di fornitura enterprise; l'e-invoicing è un modulo."),
    "seeburger": _hub(
        "seeburger", "SEEBURGER BIS", ("DE", "EU"), kind="compliance_suite",
        docs="https://www.seeburger.com/", supports=("send", "status", "receive"),
        notes="Piattaforma EDI/integrazione tedesca con modulo e-invoicing."),
    "comarch": _hub(
        "comarch", "Comarch e-Invoicing", ("PL", "DE", "EU"),
        kind="compliance_suite", docs="https://www.comarch.com/",
        supports=("send", "status", "receive"),
        notes="Copre KSeF in Polonia oltre a Peppol — utile proprio dove il "
              "formato nazionale non è UBL."),
    "visma": _hub(
        "visma", "Visma", ("NO", "SE", "FI", "DK", "NL"),
        kind="accounting_platform", docs="https://developer.visma.com/",
        supports=("send", "status", "receive"),
        notes="Gruppo nordico di gestionali; l'invio passa spesso da Maventa."),
    "exact": _hub(
        "exact", "Exact Online", ("NL", "BE"), kind="accounting_platform",
        docs="https://support.exactonline.com/",
        supports=("send", "receive"),
        notes="Gestionale olandese diffuso fra PMI."),
    "sage": _hub(
        "sage", "Sage", ("GB", "FR", "ES", "DE"), kind="accounting_platform",
        docs="https://developer.sage.com/",
        supports=("send", "receive"),
        notes="Presente in più mercati con prodotti diversi: verificare quale "
              "API copre il paese che ti serve."),
    "cegid": _hub(
        "cegid", "Cegid", ("FR", "ES"), kind="accounting_platform",
        docs="https://www.cegid.com/", supports=("send", "status", "receive"),
        notes="Editore francese, candidato PDP per la riforma B2B."),
    "pennylane": _hub(
        "pennylane", "Pennylane", ("FR",), kind="accounting_platform",
        docs="https://pennylane.com/", supports=("send", "receive"),
        notes="Piattaforma contabile francese in forte crescita fra le PMI."),
    "bexio": _hub(
        "bexio", "Bexio", ("CH",), kind="accounting_platform",
        base_url="https://api.bexio.com/2.0", docs="https://docs.bexio.com/",
        supports=("send",),
        notes="Gestionale svizzero per PMI; API REST pubblica."),
    "abacus": _hub(
        "abacus", "Abacus", ("CH",), kind="accounting_platform",
        docs="https://www.abacus.ch/",
        supports=("send", "receive"),
        notes="ERP svizzero diffuso nelle medie imprese."),

    # ══ Suite di compliance multi-paese ════════════════════════════════
    "edicom": _hub(
        "edicom", "EDICOM", "global", kind="compliance_suite",
        docs="https://edicomgroup.com/", supports=("send", "status", "receive"),
        notes="Forte in ES/IT/LATAM; gestisce anche i formati nazionali."),
    "sovos": _hub(
        "sovos", "Sovos", "global", kind="compliance_suite",
        docs="https://sovos.com/", supports=("send", "status", "receive"),
        notes="Compliance fiscale globale, inclusi i CTC extra-UE."),
    "avalara": _hub(
        "avalara", "Avalara E-Invoicing", "global", kind="compliance_suite",
        docs="https://www.avalara.com/", supports=("send", "status"),
        notes="Integrato con il calcolo delle imposte Avalara."),
    "vertex": _hub(
        "vertex", "Vertex", "global", kind="compliance_suite",
        docs="https://www.vertexinc.com/", supports=("send", "status"),
        notes="Calcolo imposte + e-invoicing; forte sul mercato US."),
    "fonoa": _hub(
        "fonoa", "Fonoa", "global", kind="compliance_suite",
        docs="https://www.fonoa.com/", supports=("send", "status"),
        notes="Tax compliance API-first, copertura CTC globale."),
    "sni": _hub(
        "sni", "SNI", "global", kind="compliance_suite",
        docs="https://sni.global/", supports=("send", "status", "receive"),
        notes="Specializzata nei mandati CTC (TR, IT, PL, RO, …), integrazione SAP."),
    "tungsten": _hub(
        "tungsten", "Tungsten Automation (ex Kofax)", "global",
        kind="compliance_suite", docs="https://www.tungstenautomation.com/",
        supports=("send", "status", "receive"),
        notes="Rete AP/AR globale con lunga storia nel Regno Unito."),
    "coupa": _hub(
        "coupa", "Coupa", "global", kind="compliance_suite",
        docs="https://compass.coupa.com/", supports=("send", "status", "receive"),
        notes="Business spend management; l'e-invoicing è parte del modulo AP."),
    "esker": _hub(
        "esker", "Esker", ("FR", "EU"), kind="compliance_suite",
        docs="https://www.esker.com/", supports=("send", "status", "receive"),
        notes="Automazione documentale francese, candidato PDP."),
    "generix": _hub(
        "generix", "Generix Group", ("FR", "EU"), kind="compliance_suite",
        docs="https://www.generixgroup.com/", supports=("send", "status", "receive"),
        notes="EDI/supply chain francese, candidato PDP."),
    "docaposte": _hub(
        "docaposte", "Docaposte", ("FR",), kind="compliance_suite",
        docs="https://www.docaposte.com/", supports=("send", "status", "receive"),
        notes="Filiale digitale de La Poste, candidato PDP."),
    "iopole": _hub(
        "iopole", "Iopole", ("FR",), kind="access_point",
        docs="https://iopole.com/", supports=("send", "status", "receive"),
        notes="Access Point Peppol francese, candidato PDP."),
    "voxel": _hub(
        "voxel", "Voxel (Amadeus)", ("ES",), kind="compliance_suite",
        docs="https://www.voxelgroup.net/", supports=("send", "status", "receive"),
        notes="Forte nell'hospitality spagnola; produce Facturae."),
    "seres": _hub(
        "seres", "SERES", ("ES", "FR"), kind="compliance_suite",
        docs="https://www.groupseres.com/", supports=("send", "status", "receive"),
        notes="Operatore ES/FR; copre Facturae e Chorus Pro."),
    "saphety": _hub(
        "saphety", "Saphety", ("PT", "ES"), kind="compliance_suite",
        docs="https://www.saphety.com/", supports=("send", "status", "receive"),
        notes="Operatore iberico; copre gli adempimenti portoghesi (ATCUD/SAF-T)."),
    "smartbill": _hub(
        "smartbill", "SmartBill", ("RO",), kind="accounting_platform",
        docs="https://www.smartbill.ro/", supports=("send", "status"),
        notes="Gestionale rumeno con integrazione e-Factura ANAF."),

    # ══ Portali nazionali obbligatori ══════════════════════════════════
    "chorus_pro": _hub(
        "chorus_pro", "Chorus Pro", ("FR",), kind="national_portal", renderer="cii",
        base_url="https://chorus-pro.gouv.fr/cpro/api",
        docs="https://developer.aife.economie.gouv.fr/",
        supports=("send", "status", "receive"),
        notes="Portale B2G francese. Accetta CII/Factur-X e UBL — qui si "
              "renderizza CII di default. Autenticazione OAuth2 + certificato: "
              "usare un connettore dedicato se serve mTLS."),
    "ksef": _hub(
        "ksef", "KSeF", ("PL",), kind="national_portal", renderer="ubl",
        base_url="https://ksef.mf.gov.pl/api",
        docs="https://www.podatki.gov.pl/ksef/",
        supports=("send", "status", "receive"),
        notes="ATTENZIONE: KSeF accetta SOLO il formato nazionale FA(2), che "
              "NON è UBL. Questo pacchetto genera EN 16931 valido ma serve un "
              "convertitore verso FA(2) prima dell'invio."),
    "efactura_anaf": _hub(
        "efactura_anaf", "e-Factura (ANAF)", ("RO",), kind="national_portal",
        renderer="ubl", base_url="https://api.anaf.ro/prod/FCTEL/rest",
        docs="https://mfinante.gov.ro/ro/web/efactura",
        supports=("send", "status", "receive"),
        notes="CIUS-RO su UBL. OAuth2 con certificato qualificato."),
    "face": _hub(
        "face", "FACe", ("ES",), kind="national_portal", renderer="ubl",
        docs="https://face.gob.es/", supports=("send", "status"),
        notes="ATTENZIONE: FACe richiede Facturae 3.2.x, un XML nazionale che "
              "NON è UBL. Serve un convertitore o un provider che lo produca "
              "(es. B2Brouter, EDICOM, Voxel)."),
    "digipoort": _hub(
        "digipoort", "Digipoort", ("NL",), kind="national_portal", renderer="ubl",
        docs="https://www.logius.nl/diensten/digipoort",
        supports=("send", "status"),
        notes="Canale B2G olandese (Logius). Richiede NLCIUS: renderizzare con "
              "renderer_for_country('NL', b2g=True). Autenticazione con "
              "certificato PKIoverheid."),
    "nemhandel": _hub(
        "nemhandel", "Nemhandel", ("DK",), kind="national_portal", renderer="ubl",
        docs="https://nemhandel.dk/", supports=("send", "status", "receive"),
        notes="Infrastruttura danese, oggi allineata a Peppol/OIOUBL."),
    "ebill_ch": _hub(
        "ebill_ch", "eBill (SIX)", ("CH",), kind="national_portal", renderer="ubl",
        docs="https://www.ebill.ch/", supports=("send",),
        notes="Circuito di fatturazione domestico svizzero (SIX). Per il B2G "
              "federale e il cross-border si usa Peppol."),
    "swisscom_conextrade": _hub(
        "swisscom_conextrade", "Conextrade (Swisscom)", ("CH",),
        kind="access_point", docs="https://www.conextrade.com/",
        supports=("send", "status", "receive"),
        notes="Hub B2B svizzero e Access Point Peppol; via comune per il B2G "
              "federale sopra CHF 5'000."),
}


def available_providers() -> list[str]:
    return sorted(PROVIDER_PRESETS)


def providers_for_country(country_code: str, *, kind: str | None = None) -> list[ProviderPreset]:
    """Presets serving a country, the ones that name it first.

    A platform that lists the country explicitly is almost always the better
    starting point than a global aggregator, so ordering carries information
    here rather than being cosmetic.
    """
    code = (country_code or "").upper()
    chosen = [p for p in PROVIDER_PRESETS.values()
              if p.serves(code) and (kind is None or p.kind == kind)]
    national = sorted((p for p in chosen if code in p.countries), key=lambda p: p.key)
    wide = sorted((p for p in chosen if code not in p.countries), key=lambda p: p.key)
    return national + wide


def providers_of_kind(kind: str) -> list[ProviderPreset]:
    """Presets of one :data:`PROVIDER_KINDS` category."""
    if kind not in PROVIDER_KINDS:
        raise ProviderConfigError(
            f"Categoria sconosciuta: {kind!r}. Disponibili: {', '.join(sorted(PROVIDER_KINDS))}"
        )
    return sorted((p for p in PROVIDER_PRESETS.values() if p.kind == kind),
                  key=lambda p: p.key)


def preset_for(key: str) -> ProviderPreset:
    preset = PROVIDER_PRESETS.get((key or "").lower())
    if preset is None:
        raise ProviderConfigError(
            f"Piattaforma sconosciuta: {key!r}. "
            f"Disponibili: {', '.join(available_providers())}"
        )
    return preset


def transport_for_provider(key: str, *, sandbox: bool = True, **credentials) -> Transport:
    """Ready-to-use transport for a named platform.

    ``credentials`` takes the preset's required keys plus an optional
    ``base_url`` (your account's host) and ``extra`` (overrides for the field
    names, merged over the preset's own).
    """
    preset = preset_for(key)
    return get_transport(preset.transport, preset.config(sandbox=sandbox, **credentials))
