"""Country profiles — rules, tax ids, VAT rates and e-invoicing regimes.

One :class:`CountryProfile` per supported country ties together everything that
varies by jurisdiction:

* the **default rendering standard** for a domestic seller (``fatturapa`` for
  Italy, ``ubl`` — Peppol BIS Billing 3.0 — everywhere else);
* the **tax scheme** the renderer stamps (``VAT`` in the EU/UK/CH, ``STT`` —
  UN/ECE 5153 state sales tax — in the US);
* **tax-id validation**, with a real check digit wherever one exists (see
  :mod:`einvoice.taxid`);
* the **known VAT rates**, so an implausible rate can be flagged before the
  document leaves;
* the **e-invoicing regime** (:class:`EInvoicingRegime`): which network, which
  CIUS, whether B2G/B2B is mandatory, and whether a *national* syntax exists
  that UBL does not satisfy;
* the **country-specific invoice rules** — the Italian ones (RegimeFiscale,
  Natura, CodiceDestinatario, CAP) apply only to Italian sellers, so the same
  neutral :class:`~einvoice.models.Invoice` validates cleanly for a German,
  British, Swiss or American seller.

Coverage: the 27 EU member states, the United Kingdom, Switzerland and the
United States. ``profile_for()`` falls back to a permissive generic profile for
anything else, so the engine never hard-fails on an unlisted country.

    from einvoice import profile_for, renderer_for_country

    profile_for("DE").validate_tax_id("DE136695976")   # True (check digit)
    profile_for("CH").regime.network                   # "peppol"
    renderer_for_country("US")                         # UblRenderer(tax_scheme="STT")
    renderer_for_country("DE", b2g=True)               # XRechnung CIUS

**On the regulatory data.** Mandates and deadlines move — they are policy, not
arithmetic. Everything in :class:`EInvoicingRegime` is dated by
:data:`MANDATES_VERIFIED_AS_OF` and is *operational guidance, not legal advice*:
check the national tax authority before relying on a date. The mechanical parts
of this module (tax ids, rates, CIUS identifiers, rendering rules) do not go
stale the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from .errors import ValidationError
from .rates import COUNTRY_RATES, ProductCategory, categories_for, rate_for, rates_for
from .taxid import normalize_tax_id, validate_tax_id_full, validation_level

if TYPE_CHECKING:  # pragma: no cover
    from .formats.base import InvoiceRenderer
    from .models import Invoice

__all__ = [
    "CountryProfile", "EInvoicingRegime", "FiscalRules", "EU_OSS_THRESHOLD",
    "COUNTRY_PROFILES", "EU_COUNTRIES",
    "profile_for", "renderer_for_country", "validate_tax_id",
    "XRECHNUNG_CUSTOMIZATION", "PEPPOL_CUSTOMIZATION", "NLCIUS_CUSTOMIZATION",
    "CIUS_RO_CUSTOMIZATION", "MANDATES_VERIFIED_AS_OF", "supported_countries",
]

#: When the regulatory fields in this module were last reviewed. Surfaced by
#: the CLI (``einvoice countries``) so nobody mistakes stale policy for fact.
MANDATES_VERIFIED_AS_OF = date(2026, 8, 24)

# ── CIUS / customization identifiers ────────────────────────────────────────
# The CustomizationID is what tells a receiver which rule set the document
# claims to follow. Sending Peppol BIS to a receiver expecting XRechnung is a
# rejection, not a warning, so these strings are load-bearing.

#: Peppol BIS Billing 3.0 — the EU default.
PEPPOL_CUSTOMIZATION = (
    "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
)
#: XRechnung 3.0 CIUS — German public sector.
XRECHNUNG_CUSTOMIZATION = (
    "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
)
#: NLCIUS — Dutch public sector.
NLCIUS_CUSTOMIZATION = (
    "urn:cen.eu:en16931:2017#compliant#urn:fdc:nen.nl:nlcius:v1.0"
)
#: CIUS-RO — Romanian e-Factura.
CIUS_RO_CUSTOMIZATION = (
    "urn:cen.eu:en16931:2017#compliant#urn:efactura.mfinante.ro:CIUS-RO:1.0.1"
)

#: ISO 3166-1 alpha-2 codes of the 27 EU member states.
EU_COUNTRIES = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
})

# Structural VAT-number patterns (VIES formats), WITHOUT the country prefix.
# Used only where no check-digit algorithm is registered — see einvoice.taxid.
_VAT_PATTERNS: dict[str, str] = {
    "AT": r"U\d{8}", "BE": r"[01]\d{9}", "BG": r"\d{9,10}", "HR": r"\d{11}",
    "CY": r"\d{8}[A-Z]", "CZ": r"\d{8,10}", "DK": r"\d{8}", "EE": r"\d{9}",
    "FI": r"\d{8}", "FR": r"[A-HJ-NP-Z0-9]{2}\d{9}", "DE": r"\d{9}",
    "GR": r"\d{9}", "HU": r"\d{8}", "IE": r"\d{7}[A-W][A-I]?|\d[A-Z+*]\d{5}[A-W]",
    "IT": r"\d{11}", "LV": r"\d{11}", "LT": r"\d{9}(\d{3})?", "LU": r"\d{8}",
    "MT": r"\d{8}", "NL": r"\d{9}B\d{2}", "PL": r"\d{10}", "PT": r"\d{9}",
    "RO": r"\d{2,10}", "SK": r"\d{10}", "SI": r"\d{8}",
    "ES": r"[A-Z0-9]\d{7}[A-Z0-9]", "SE": r"\d{12}",
    "GB": r"\d{9}(\d{3})?|GD\d{3}|HA\d{3}",
    "CH": r"CHE\d{9}",
    "US": r"\d{2}-?\d{7}",
}

_COUNTRY_NAMES = {
    "AT": "Österreich", "BE": "Belgique/België", "BG": "България",
    "HR": "Hrvatska", "CY": "Κύπρος", "CZ": "Česko", "DK": "Danmark",
    "EE": "Eesti", "FI": "Suomi", "FR": "France", "DE": "Deutschland",
    "GR": "Ελλάδα", "HU": "Magyarország", "IE": "Ireland", "IT": "Italia",
    "LV": "Latvija", "LT": "Lietuva", "LU": "Luxembourg", "MT": "Malta",
    "NL": "Nederland", "PL": "Polska", "PT": "Portugal", "RO": "România",
    "SK": "Slovensko", "SI": "Slovenija", "ES": "España", "SE": "Sverige",
    "GB": "United Kingdom", "CH": "Schweiz/Suisse/Svizzera",
    "US": "United States",
}

#: Rates in force per country, derived from the one table that also knows what
#: each rate applies to (:mod:`einvoice.rates`). Kept as a derived view rather
#: than a second hand-maintained list — two tables of tax rates drift, and the
#: one that drifts is always the one nobody is looking at.
_VAT_RATES: dict[str, tuple[str, ...]] = {
    code: tuple(str(entry.rate) for entry in entries)
    for code, entries in COUNTRY_RATES.items()
    if entries
}


@dataclass(frozen=True)
class FiscalRules:
    """The non-rate obligations that shape how an invoice is issued and kept.

    These are the questions that come up once the XML is correct: how long must
    it be kept, by when must it be issued, when may a simplified invoice be used.
    Like :class:`EInvoicingRegime` this is **operational guidance, not legal
    advice**, dated by :data:`MANDATES_VERIFIED_AS_OF` — and like it, a value
    this module cannot state is ``None`` rather than a plausible number.
    """

    #: Years the issuer must retain the invoice (conservazione / Aufbewahrung).
    retention_years: int | None = None
    #: Ceiling below which a simplified invoice may be issued, in the country's
    #: currency. ``None`` where the country has no such regime.
    simplified_invoice_threshold: Decimal | None = None
    #: Days from the taxable event within which the invoice must be issued.
    issue_deadline_days: int | None = None
    #: Whether domestic reverse charge applies in specific sectors.
    domestic_reverse_charge: bool = False
    #: Free-text notes on anything a caller should know before issuing here.
    notes: str = ""


#: EU-wide, not per country: the distance-selling threshold above which a seller
#: must charge the customer's rate (or register for OSS). It is a *combined*
#: turnover across all member states, which is the part people get wrong.
EU_OSS_THRESHOLD = Decimal("10000")

#: The rules per country. Absent entries fall back to a permissive default.
_FISCAL_RULES: dict[str, FiscalRules] = {
    "IT": FiscalRules(
        retention_years=10, simplified_invoice_threshold=Decimal("400"),
        issue_deadline_days=12, domestic_reverse_charge=True,
        notes="Fattura immediata entro 12 giorni; differita entro il 15 del mese "
              "successivo (TD24). Conservazione a norma decennale. Reverse charge "
              "interno per edilizia, rottami, elettronica (Natura N6.x)."),
    "DE": FiscalRules(
        retention_years=10, simplified_invoice_threshold=Decimal("250"),
        issue_deadline_days=180, domestic_reverse_charge=True,
        notes="Kleinbetragsrechnung fino a 250 €. Rechnung entro 6 mesi. "
              "§13b UStG per costruzioni e alcuni beni."),
    "FR": FiscalRules(
        retention_years=10, simplified_invoice_threshold=Decimal("150"),
        domestic_reverse_charge=True,
        notes="Autoliquidation nel settore edile. Conservazione 10 anni "
              "(6 anni ai fini fiscali, 10 ai fini commerciali)."),
    "ES": FiscalRules(
        retention_years=4, simplified_invoice_threshold=Decimal("400"),
        domestic_reverse_charge=True,
        notes="Factura simplificada fino a 400 € (3.000 € in alcuni settori). "
              "Prescrizione fiscale quadriennale."),
    "NL": FiscalRules(retention_years=7, simplified_invoice_threshold=Decimal("100"),
                      notes="Bewaarplicht 7 anni (10 per gli immobili)."),
    "BE": FiscalRules(retention_years=10, notes="Conservazione decennale."),
    "AT": FiscalRules(retention_years=7, simplified_invoice_threshold=Decimal("400"),
                      notes="Kleinbetragsrechnung fino a 400 €."),
    "PT": FiscalRules(retention_years=10, issue_deadline_days=5,
                      notes="Fattura entro 5 giorni lavorativi. Servono ATCUD e "
                           "codice QR; SAF-T (PT) mensile."),
    "IE": FiscalRules(retention_years=6, domestic_reverse_charge=True,
                      notes="Reverse charge in edilizia (RCT)."),
    "GB": FiscalRules(retention_years=6, simplified_invoice_threshold=Decimal("250"),
                      domestic_reverse_charge=True,
                      notes="Simplified invoice fino a 250 £. Domestic reverse "
                           "charge per l'edilizia dal 2021. MTD per i registri IVA."),
    "CH": FiscalRules(retention_years=10,
                      notes="Aufbewahrungspflicht decennale (OR 958f). Nessuna "
                           "cessione intracomunitaria: le vendite verso l'UE sono "
                           "esportazioni e gli acquisti importazioni."),
    "SE": FiscalRules(retention_years=7, simplified_invoice_threshold=Decimal("4000"),
                      notes="Soglia in SEK."),
    "DK": FiscalRules(retention_years=5, notes="Bogføringsloven: 5 anni."),
    "FI": FiscalRules(retention_years=6, simplified_invoice_threshold=Decimal("400")),
    "PL": FiscalRules(retention_years=5, domestic_reverse_charge=True,
                      notes="Conservazione 5 anni dalla fine dell'anno fiscale."),
    "CZ": FiscalRules(retention_years=10, simplified_invoice_threshold=Decimal("10000"),
                      notes="Soglia in CZK."),
    "HU": FiscalRules(retention_years=8,
                      notes="Reporting NAV RTIR in tempo reale, separato dalla fattura."),
    "RO": FiscalRules(retention_years=10,
                      notes="e-Factura obbligatoria; trasmissione entro 5 giorni."),
    "GR": FiscalRules(retention_years=5, notes="Reporting myDATA obbligatorio."),
    "SI": FiscalRules(retention_years=10),
    "SK": FiscalRules(retention_years=10),
    "HR": FiscalRules(retention_years=11),
    "BG": FiscalRules(retention_years=10),
    "LT": FiscalRules(retention_years=10),
    "LV": FiscalRules(retention_years=5),
    "EE": FiscalRules(retention_years=7),
    "LU": FiscalRules(retention_years=10),
    "CY": FiscalRules(retention_years=6),
    "MT": FiscalRules(retention_years=6),
    "US": FiscalRules(
        retention_years=None,
        notes="Nessun obbligo federale di conservazione delle fatture: le regole "
              "sono statali e variano. La sales tax si determina per riga in base "
              "al nexus e alla giurisdizione di destinazione."),
}

_DEFAULT_FISCAL_RULES = FiscalRules()


@dataclass(frozen=True)
class EInvoicingRegime:
    """What a jurisdiction requires, and over which network.

    Dated by :data:`MANDATES_VERIFIED_AS_OF`. Operational guidance for choosing
    a format and a channel — **not legal advice**, and mandates move.
    """

    #: ``peppol`` | ``sdi`` | ``ksef`` | ``chorus`` | ``facturae`` | ``efactura``
    #: | ``mydata`` | ``rtir`` | ``none``. The dominant national channel.
    network: str = "peppol"
    #: ``mandatory`` | ``voluntary`` | ``none``
    b2g: str = "voluntary"
    #: ``mandatory`` | ``phased`` | ``voluntary`` | ``none``
    b2b: str = "voluntary"
    #: CustomizationID a domestic document should declare, when it differs from
    #: plain Peppol BIS.
    customization: str | None = None
    #: A national syntax that UBL does **not** satisfy. When set, this package
    #: renders a valid EN 16931 document but the country needs something else
    #: for the domestic mandate — say so rather than implying coverage.
    national_format: str | None = None
    #: Free-text operational note (deadlines, thresholds, gotchas).
    notes: str = ""

    @property
    def covered_by_this_package(self) -> bool:
        """True when our renderers produce what the country's channel accepts."""
        return self.national_format is None


@dataclass(frozen=True)
class CountryProfile:
    code: str
    name: str
    default_standard: str = "ubl"       # renderer key for a domestic seller
    tax_scheme: str = "VAT"             # UN/ECE 5153 (VAT | GST | STT | …)
    tax_id_label: str = "VAT"           # what the tax id is called locally
    tax_id_pattern: str | None = None   # structural fallback, no country prefix
    eu_member: bool = False
    currency_hint: str = "EUR"          # informative only, never enforced
    vat_rates: tuple[str, ...] = ()     # advisory, see _VAT_RATES
    regime: EInvoicingRegime = field(default_factory=EInvoicingRegime)
    fiscal_rules: FiscalRules = field(default_factory=FiscalRules)
    notes: str = ""

    # ── tax-id ─────────────────────────────────────────────────────────

    def validate_tax_id(self, value: str | None) -> bool:
        """Validate the tax id — check digit where one exists, else structure.

        Accepts printed forms: prefixes, spaces, dots and the Swiss ``MWST``
        suffix are normalized away first.
        """
        if not value:
            return False
        return validate_tax_id_full(self.code, value, pattern=self.tax_id_pattern)

    @property
    def tax_id_validation(self) -> str:
        """``"checksum"`` or ``"structural"`` — how strong the check above is."""
        return validation_level(self.code)

    def normalize_tax_id(self, value: str | None) -> str:
        """The bare identifier, decoration and country prefix removed."""
        return normalize_tax_id(self.code, value)

    # ── VAT rates ──────────────────────────────────────────────────────

    @property
    def rates(self) -> tuple:
        """Every rate in force here, with what each one covers."""
        return rates_for(self.code)

    def rate_for(self, category: ProductCategory):
        """The rate this country applies to a category, or ``None`` if unmapped.

        ``None`` is a real answer, not a failure: national reduced-rate law turns
        on distinctions an invoice does not carry, and a plausible-looking guess
        in a tax table is worse than a blank.
        """
        return rate_for(self.code, category)

    def rate_categories(self) -> dict:
        """Every category this module can state a rate for, in this country."""
        return categories_for(self.code)

    def is_known_vat_rate(self, rate) -> bool:
        """Whether ``rate`` is one this country actually uses.

        Advisory. An unknown rate is far more often a typo than a genuine
        special regime, but genuine special regimes exist — so this informs
        :meth:`~einvoice.models.Invoice.check`, never :meth:`validate`.
        """
        if not self.vat_rates:
            return True
        return Decimal(str(rate)).normalize() in {
            Decimal(r).normalize() for r in self.vat_rates
        }

    # ── invoice rules ──────────────────────────────────────────────────

    def validate_invoice(self, invoice: Invoice) -> None:
        """Country-specific checks for a seller of this country. Base: a valid
        seller tax id when one is given, and *some* fiscal identifier."""
        seller_id = invoice.seller.vat_number or invoice.seller.tax_code
        if invoice.seller.vat_number and not self.validate_tax_id(invoice.seller.vat_number):
            raise ValidationError(
                f"Cedente/Prestatore: {self.tax_id_label} '{invoice.seller.vat_number}' "
                f"non valida per {self.code}"
            )
        if seller_id is None:
            raise ValidationError("Cedente/Prestatore: identificativo fiscale mancante")

    def advisories(self, invoice: Invoice) -> list[str]:
        """Non-fatal findings for :meth:`~einvoice.models.Invoice.check`."""
        out: list[str] = []
        for ln in invoice.lines:
            if not self.is_known_vat_rate(ln.vat_rate):
                out.append(
                    f"Riga '{ln.description}': aliquota {ln.vat_rate}% non è fra quelle "
                    f"note per {self.code} ({', '.join(self.vat_rates)}) — "
                    "verificare che non sia un errore di battitura"
                )
        if invoice.buyer.vat_number and not profile_for(
            invoice.buyer.country_code
        ).validate_tax_id(invoice.buyer.vat_number):
            out.append(
                f"Cessionario/Committente: {invoice.buyer.vat_number} non supera la "
                f"validazione per {invoice.buyer.country_code}"
            )
        return out


class _ItalyProfile(CountryProfile):
    """Italy — FatturaPA/SdI rules (kept out of the neutral model)."""

    def validate_invoice(self, invoice: Invoice) -> None:
        from .enums import REGIMI_FISCALI, TransmissionFormat

        super().validate_invoice(invoice)
        if invoice.seller.vat_number is None:
            raise ValidationError("Cedente/Prestatore: la P.IVA è obbligatoria")
        if invoice.seller.tax_regime not in REGIMI_FISCALI:
            raise ValidationError(
                f"Cedente/Prestatore: RegimeFiscale '{invoice.seller.tax_regime}' non valido"
            )
        code, _ = invoice.resolved_recipient()
        if invoice.transmission_format is TransmissionFormat.PA and len(code) != 6:
            raise ValidationError(
                f"FPA12: CodiceDestinatario '{code}' deve essere di 6 caratteri"
            )
        if invoice.transmission_format is TransmissionFormat.PRIVATE and len(code) != 7:
            raise ValidationError(
                f"FPR12: CodiceDestinatario '{code}' deve essere di 7 caratteri"
            )
        for role, party in (("Cedente/Prestatore", invoice.seller),
                            ("Cessionario/Committente", invoice.buyer)):
            a = party.address
            if a and a.country == "IT" and not (
                len(a.postcode) == 5 and a.postcode.isdigit()
            ):
                raise ValidationError(f"{role}: CAP '{a.postcode}' non valido (5 cifre)")
        for ln in invoice.lines:
            if ln.vat_rate == 0 and ln.nature is None:
                raise ValidationError(
                    f"Riga '{ln.description}': aliquota 0 richiede una Natura IVA"
                )
            if ln.vat_rate > 0 and ln.nature is not None:
                raise ValidationError(
                    f"Riga '{ln.description}': Natura e aliquota > 0 sono mutuamente esclusive"
                )


class _NoVatNatureProfile(CountryProfile):
    """A jurisdiction with no Italian-style ``Natura`` code list.

    Shared by the US (sales tax) and Switzerland (MWST): both have zero-rated
    and exempt supplies, but neither has anything the FatturaPA ``Natura``
    codes describe, so letting one through would silently produce a document
    asserting an Italian VAT regime that does not exist there.
    """

    def validate_invoice(self, invoice: Invoice) -> None:
        super().validate_invoice(invoice)
        for ln in invoice.lines:
            if ln.nature is not None:
                raise ValidationError(
                    f"Riga '{ln.description}': le Nature IVA italiane non si applicano "
                    f"a un venditore {self.code} (usare aliquota 0 per le righe esenti)"
                )


# What the VAT identifier is actually called in each country, in the local
# vocabulary an operator will recognise on their own paperwork. A field
# labelled "VAT" everywhere is not wrong so much as useless: a German looking
# for where to type their USt-IdNr. should not have to guess that "VAT" means
# that. Where a country's own usage is a pair (Belgium is bilingual, Portugal
# distinguishes individuals from companies), both are given.
_TAX_ID_LABELS: dict[str, str] = {
    "AT": "UID-Nr.",
    "BE": "BTW-nr. / N° TVA",
    "BG": "ДДС номер",
    "CY": "ΦΠΑ / VAT No.",
    "CZ": "DIČ",
    "DE": "USt-IdNr.",
    "DK": "CVR-nr.",
    "EE": "KMKR number",
    "ES": "NIF / CIF",
    "FI": "ALV-numero",
    "FR": "N° TVA",
    "GR": "ΑΦΜ",
    "HR": "OIB / PDV ID",
    "HU": "Adószám",
    "IE": "VAT No.",
    "LT": "PVM kodas",
    "LU": "N° TVA",
    "LV": "PVN numurs",
    "MT": "VAT No.",
    "NL": "Btw-nummer",
    "PL": "NIP",
    "PT": "NIF / NIPC",
    "RO": "CUI / CIF",
    "SE": "Momsreg.nr.",
    "SI": "ID za DDV",
    "SK": "IČ DPH",
}


def _eu(code: str, currency: str = "EUR", *, regime: EInvoicingRegime | None = None,
        **kw) -> CountryProfile:
    return CountryProfile(
        code=code, name=_COUNTRY_NAMES[code], default_standard="ubl",
        tax_scheme="VAT", tax_id_label=_TAX_ID_LABELS.get(code, "VAT"),
        tax_id_pattern=_VAT_PATTERNS[code],
        eu_member=True, currency_hint=currency, vat_rates=_VAT_RATES[code],
        regime=regime or EInvoicingRegime(b2g="mandatory"),
        fiscal_rules=_FISCAL_RULES.get(code, _DEFAULT_FISCAL_RULES),
        **kw,
    )


COUNTRY_PROFILES: dict[str, CountryProfile] = {
    # ── Italy — FatturaPA is the domestic default ──────────────────────
    "IT": _ItalyProfile(
        code="IT", name=_COUNTRY_NAMES["IT"], default_standard="fatturapa",
        tax_scheme="VAT", tax_id_label="P.IVA", tax_id_pattern=_VAT_PATTERNS["IT"],
        eu_member=True, vat_rates=_VAT_RATES["IT"],
        fiscal_rules=_FISCAL_RULES["IT"],
        regime=EInvoicingRegime(
            network="sdi", b2g="mandatory", b2b="mandatory",
            notes="SdI obbligatorio B2B e B2G; dal 2024 anche per i forfettari. "
                  "Peppol BIS resta usabile per l'estero.",
        ),
        notes="FatturaPA/SdI obbligatoria; UBL per Peppol B2G/estero.",
    ),

    # ── EU-27 ─────────────────────────────────────────────────────────
    "AT": _eu("AT"),
    "BE": _eu("BE", regime=EInvoicingRegime(
        b2g="mandatory", b2b="mandatory",
        notes="B2B obbligatorio dal 2026-01-01 via Peppol (legge 2024).")),
    "BG": _eu("BG", "BGN"),
    "HR": _eu("HR"),
    "CY": _eu("CY"),
    "CZ": _eu("CZ", "CZK"),
    "DK": _eu("DK", "DKK", regime=EInvoicingRegime(
        b2g="mandatory", notes="B2G via NemHandel/Peppol; obblighi di "
                               "contabilità digitale in fasi (bogføringsloven).")),
    "EE": _eu("EE"),
    "FI": _eu("FI"),
    "FR": _eu("FR", regime=EInvoicingRegime(
        network="chorus", b2g="mandatory", b2b="phased",
        notes="B2G via Chorus Pro. Riforma B2B: ricezione obbligatoria per tutti "
              "dal 2026-09, emissione in fasi 2026-09 / 2027-09. Formati ammessi: "
              "Factur-X (CII), UBL, CII — vedi il renderer 'cii'.")),
    "DE": _eu("DE", regime=EInvoicingRegime(
        b2g="mandatory", b2b="phased", customization=XRECHNUNG_CUSTOMIZATION,
        notes="B2G: XRechnung obbligatoria. B2B: ricezione obbligatoria dal "
              "2025-01-01, emissione in fasi fino al 2028. XRechnung e "
              "ZUGFeRD/Factur-X (CII) sono entrambi ammessi.")),
    "GR": _eu("GR", regime=EInvoicingRegime(
        network="mydata", b2g="mandatory", b2b="phased",
        notes="Reporting myDATA obbligatorio; e-invoicing B2B in introduzione "
              "graduale. Prefisso VIES 'EL' gestito automaticamente.")),
    "HU": _eu("HU", "HUF", regime=EInvoicingRegime(
        network="rtir", b2g="mandatory", b2b="voluntary",
        notes="Nessun obbligo di e-invoice, ma reporting NAV RTIR in tempo "
              "reale obbligatorio: è un adempimento separato da questo pacchetto.")),
    "IE": _eu("IE"),
    "LV": _eu("LV"),
    "LT": _eu("LT"),
    "LU": _eu("LU"),
    "MT": _eu("MT"),
    "NL": _eu("NL", regime=EInvoicingRegime(
        b2g="mandatory", customization=NLCIUS_CUSTOMIZATION,
        notes="B2G: NLCIUS via Peppol/Digipoort. B2B volontario.")),
    "PL": _eu("PL", "PLN", regime=EInvoicingRegime(
        network="ksef", b2g="mandatory", b2b="phased",
        national_format="KSeF FA(2) XML",
        notes="KSeF obbligatorio in fasi dal 2026. Il formato nazionale FA(2) "
              "NON è UBL: questo pacchetto genera EN 16931 valido, ma per KSeF "
              "serve un convertitore verso FA(2).")),
    "PT": _eu("PT", regime=EInvoicingRegime(
        b2g="mandatory",
        notes="B2G obbligatorio. Servono anche ATCUD + QR code e SAF-T (PT): "
              "adempimenti nazionali fuori dal perimetro di questo pacchetto.")),
    "RO": _eu("RO", "RON", regime=EInvoicingRegime(
        network="efactura", b2g="mandatory", b2b="mandatory",
        customization=CIUS_RO_CUSTOMIZATION,
        notes="e-Factura obbligatoria B2G e B2B; CIUS-RO su UBL, trasmissione "
              "via il sistema ANAF.")),
    "SK": _eu("SK"),
    "SI": _eu("SI"),
    "ES": _eu("ES", regime=EInvoicingRegime(
        network="facturae", b2g="mandatory", b2b="phased",
        national_format="Facturae 3.2.x XML",
        notes="B2G via FACe in formato Facturae (XML nazionale, non UBL). "
              "B2B in arrivo con la legge Crea y Crece; obblighi Verifactu/"
              "TicketBAI separati.")),
    "SE": _eu("SE", "SEK"),

    # ── United Kingdom ────────────────────────────────────────────────
    "GB": CountryProfile(
        code="GB", name=_COUNTRY_NAMES["GB"], default_standard="ubl",
        tax_scheme="VAT", tax_id_label="VAT Reg. No.",
        tax_id_pattern=_VAT_PATTERNS["GB"], currency_hint="GBP",
        vat_rates=_VAT_RATES["GB"],
        fiscal_rules=_FISCAL_RULES["GB"],
        regime=EInvoicingRegime(
            b2g="voluntary", b2b="voluntary",
            notes="Nessun obbligo di e-invoicing. Making Tax Digital riguarda i "
                  "registri IVA, non il formato della fattura. Peppol (EAS 9932) "
                  "è usato dal NHS e da parte del settore pubblico."),
        notes="UBL EN 16931 per l'interscambio; nessun mandato nazionale.",
    ),

    # ── Switzerland ───────────────────────────────────────────────────
    "CH": _NoVatNatureProfile(
        code="CH", name=_COUNTRY_NAMES["CH"], default_standard="ubl",
        tax_scheme="VAT", tax_id_label="MWST/UID",
        tax_id_pattern=_VAT_PATTERNS["CH"], currency_hint="CHF",
        vat_rates=_VAT_RATES["CH"],
        fiscal_rules=_FISCAL_RULES["CH"],
        regime=EInvoicingRegime(
            network="peppol", b2g="mandatory", b2b="voluntary",
            notes="B2G: e-fattura obbligatoria verso l'amministrazione federale "
                  "sopra CHF 5'000. B2B volontario, in pratica via Peppol o i "
                  "circuiti eBill. Il QR-bill è lo standard di PAGAMENTO "
                  "domestico e resta separato dalla fattura elettronica."),
        notes="Non UE: nessuna cessione intracomunitaria, IVA all'importazione "
              "per i beni. UID CHE = P.IVA e numero di registro di commercio; "
              "EAS Peppol 0183.",
    ),

    # ── United States ─────────────────────────────────────────────────
    "US": _NoVatNatureProfile(
        code="US", name=_COUNTRY_NAMES["US"], default_standard="ubl",
        tax_scheme="STT", tax_id_label="EIN",
        tax_id_pattern=_VAT_PATTERNS["US"], currency_hint="USD",
        fiscal_rules=_FISCAL_RULES["US"],
        regime=EInvoicingRegime(
            network="peppol", b2g="voluntary", b2b="voluntary",
            notes="Nessun mandato federale. La rete di interscambio è "
                  "DBNAlliance (Peppol-like). L'imposta è sales tax "
                  "state/local: si dichiara per riga, non c'è un'IVA federale."),
        notes="UBL EN 16931-style con sales tax (UN/ECE 5153 'STT').",
    ),
}

# No currency hint: a country we have no profile for is a country whose usual
# currency we do not know, and claiming EUR made ``check()`` warn about a
# perfectly ordinary USD invoice.
_GENERIC = CountryProfile(code="", name="Generic", default_standard="ubl",
                          currency_hint="")


def supported_countries() -> list[str]:
    """ISO codes with a dedicated profile, sorted."""
    return sorted(COUNTRY_PROFILES)


def profile_for(country_code: str | None) -> CountryProfile:
    """The profile for an ISO 3166-1 alpha-2 code (permissive fallback)."""
    return COUNTRY_PROFILES.get((country_code or "").upper(), _GENERIC)


def validate_tax_id(country_code: str, value: str | None) -> bool:
    return profile_for(country_code).validate_tax_id(value)


def renderer_for_country(
    country_code: str,
    *,
    xrechnung: bool = False,
    b2g: bool = False,
    standard: str | None = None,
    **kwargs,
) -> InvoiceRenderer:
    """The right renderer for a seller in ``country_code``.

    Italy → FatturaPA; everyone else → UBL (Peppol BIS 3.0) carrying the
    profile's tax scheme.

    ``b2g=True`` selects the country's public-sector CIUS when it has one —
    XRechnung for Germany, NLCIUS for the Netherlands, CIUS-RO for Romania —
    because sending plain Peppol BIS to a receiver expecting a CIUS is a
    rejection, not a warning. ``xrechnung=True`` is kept as an explicit
    override. ``standard`` forces a renderer outright (e.g. ``"cii"`` for
    Factur-X / Chorus Pro).
    """
    from .formats.base import get_renderer

    profile = profile_for(country_code)
    chosen = standard or profile.default_standard

    if chosen == "fatturapa":
        return get_renderer("fatturapa", **kwargs)

    if xrechnung:
        kwargs.setdefault("customization", XRECHNUNG_CUSTOMIZATION)
    elif b2g and profile.regime.customization:
        kwargs.setdefault("customization", profile.regime.customization)
    if profile.tax_scheme != "VAT":
        kwargs.setdefault("tax_scheme", profile.tax_scheme)
    return get_renderer(chosen, **kwargs)
