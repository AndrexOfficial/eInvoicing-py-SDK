"""Country profiles — per-country rules, tax-id formats and format defaults.

One :class:`CountryProfile` per supported country ties together:

* the **default rendering standard** for a domestic seller (``fatturapa`` for
  Italy, ``ubl`` — Peppol BIS Billing 3.0 — everywhere else);
* the **tax scheme** the renderer should stamp (``VAT`` in the EU/UK, ``STT``
  — UN/ECE 5153 state/provincial sales tax — in the US);
* a structural **tax-id pattern** (EU VAT numbers, UK VAT, US EIN) used by
  validation;
* the **country-specific invoice rules**: the Italian ones (RegimeFiscale,
  Natura, CodiceDestinatario, CAP) apply only to Italian sellers, so the same
  neutral :class:`~einvoice.models.Invoice` validates cleanly for a German,
  British or American seller.

Coverage: the 27 EU member states, the United Kingdom and the United States.
``profile_for()`` falls back to a permissive generic profile for anything
else, so the engine never hard-fails on an unlisted country.

    from einvoice import profile_for, renderer_for_country

    profile_for("DE").validate_tax_id("DE811193231")   # True
    renderer_for_country("US")   # UblRenderer(tax_scheme="STT")
    renderer_for_country("DE", xrechnung=True)  # XRechnung CIUS CustomizationID
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .errors import ValidationError

if TYPE_CHECKING:  # pragma: no cover
    from .formats.base import InvoiceRenderer
    from .models import Invoice

__all__ = [
    "CountryProfile", "COUNTRY_PROFILES", "EU_COUNTRIES",
    "profile_for", "renderer_for_country", "validate_tax_id",
    "XRECHNUNG_CUSTOMIZATION",
]

#: XRechnung 3.0 CIUS (Germany B2G) — layer on top of EN 16931; pass it as the
#: UBL ``customization`` for German public-sector buyers.
XRECHNUNG_CUSTOMIZATION = (
    "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
)

#: ISO 3166-1 alpha-2 codes of the 27 EU member states.
EU_COUNTRIES = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
})

# Structural VAT-number patterns (VIES formats), WITHOUT the country prefix —
# the model stores the bare number and prefixes it for UBL/VIES. Structural
# only: no checksum verification (that is the job of a VIES lookup).
_VAT_PATTERNS: dict[str, str] = {
    "AT": r"U\d{8}",
    "BE": r"[01]\d{9}",
    "BG": r"\d{9,10}",
    "HR": r"\d{11}",
    "CY": r"\d{8}[A-Z]",
    "CZ": r"\d{8,10}",
    "DK": r"\d{8}",
    "EE": r"\d{9}",
    "FI": r"\d{8}",
    "FR": r"[A-HJ-NP-Z0-9]{2}\d{9}",
    "DE": r"\d{9}",
    "GR": r"\d{9}",
    "HU": r"\d{8}",
    "IE": r"\d{7}[A-W][A-I]?|\d[A-Z+*]\d{5}[A-W]",
    "IT": r"\d{11}",
    "LV": r"\d{11}",
    "LT": r"\d{9}(\d{3})?",
    "LU": r"\d{8}",
    "MT": r"\d{8}",
    "NL": r"\d{9}B\d{2}",
    "PL": r"\d{10}",
    "PT": r"\d{9}",
    "RO": r"\d{2,10}",
    "SK": r"\d{10}",
    "SI": r"\d{8}",
    "ES": r"[A-Z0-9]\d{7}[A-Z0-9]",
    "SE": r"\d{12}",
    # United Kingdom: 9 or 12 digits, or GD/HA + 3 digits (gov/health bodies).
    "GB": r"\d{9}(\d{3})?|GD\d{3}|HA\d{3}",
    # United States: EIN (Employer Identification Number), optional dash.
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
    "GB": "United Kingdom", "US": "United States",
}


@dataclass(frozen=True)
class CountryProfile:
    code: str
    name: str
    default_standard: str = "ubl"       # renderer key for a domestic seller
    tax_scheme: str = "VAT"             # UN/ECE 5153 (VAT | GST | STT | …)
    tax_id_label: str = "VAT"           # what the tax id is called locally
    tax_id_pattern: str | None = None   # bare number, no country prefix
    eu_member: bool = False
    currency_hint: str = "EUR"          # informative only, never enforced
    notes: str = ""

    # ── tax-id ─────────────────────────────────────────────────────────

    def validate_tax_id(self, value: str | None) -> bool:
        """Structural check of the bare tax id (prefix stripped if present)."""
        if not value:
            return False
        if self.tax_id_pattern is None:
            return True
        v = value.strip().upper().replace(" ", "")
        for prefix in {self.code, "EL" if self.code == "GR" else self.code}:
            if v.startswith(prefix):
                v = v[len(prefix):]
                break
        return re.fullmatch(self.tax_id_pattern, v) is not None

    # ── invoice rules ──────────────────────────────────────────────────

    def validate_invoice(self, invoice: Invoice) -> None:
        """Country-specific checks for a seller of this country. Base: a
        structurally valid seller tax id when a pattern is known."""
        seller_id = invoice.seller.vat_number or invoice.seller.tax_code
        if invoice.seller.vat_number and not self.validate_tax_id(invoice.seller.vat_number):
            raise ValidationError(
                f"Cedente/Prestatore: {self.tax_id_label} '{invoice.seller.vat_number}' "
                f"non valida per {self.code}"
            )
        if seller_id is None:
            raise ValidationError("Cedente/Prestatore: identificativo fiscale mancante")


class _ItalyProfile(CountryProfile):
    """Italy — FatturaPA/SdI rules (moved here from the neutral model)."""

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


class _UsProfile(CountryProfile):
    """United States — sales tax, no VAT: Italian VAT natures must not leak in."""

    def validate_invoice(self, invoice: Invoice) -> None:
        super().validate_invoice(invoice)
        for ln in invoice.lines:
            if ln.nature is not None:
                raise ValidationError(
                    f"Riga '{ln.description}': le Nature IVA italiane non si applicano "
                    "a un venditore US (usare aliquota 0 per righe esenti)"
                )


def _eu(code: str, currency: str = "EUR", **kw) -> CountryProfile:
    return CountryProfile(
        code=code, name=_COUNTRY_NAMES[code], default_standard="ubl",
        tax_scheme="VAT", tax_id_label="VAT", tax_id_pattern=_VAT_PATTERNS[code],
        eu_member=True, currency_hint=currency, **kw,
    )


COUNTRY_PROFILES: dict[str, CountryProfile] = {
    # Italy keeps FatturaPA as the domestic default.
    "IT": _ItalyProfile(
        code="IT", name=_COUNTRY_NAMES["IT"], default_standard="fatturapa",
        tax_scheme="VAT", tax_id_label="P.IVA", tax_id_pattern=_VAT_PATTERNS["IT"],
        eu_member=True, notes="FatturaPA/SdI obbligatoria; UBL per Peppol B2G/estero.",
    ),
    # Rest of the EU-27 — Peppol BIS Billing 3.0 over UBL.
    "AT": _eu("AT"), "BE": _eu("BE"), "BG": _eu("BG", "BGN"), "HR": _eu("HR"),
    "CY": _eu("CY"), "CZ": _eu("CZ", "CZK"), "DK": _eu("DK", "DKK"),
    "EE": _eu("EE"), "FI": _eu("FI"), "FR": _eu("FR"),
    "DE": _eu("DE", notes="B2G: XRechnung CIUS — renderer_for_country('DE', xrechnung=True)."),
    "GR": _eu("GR", notes="Prefisso VIES 'EL' (gestito automaticamente)."),
    "HU": _eu("HU", "HUF"), "IE": _eu("IE"), "LV": _eu("LV"), "LT": _eu("LT"),
    "LU": _eu("LU"), "MT": _eu("MT"), "NL": _eu("NL"), "PL": _eu("PL", "PLN"),
    "PT": _eu("PT"), "RO": _eu("RO", "RON"), "SK": _eu("SK"), "SI": _eu("SI"),
    "ES": _eu("ES"), "SE": _eu("SE", "SEK"),
    # United Kingdom — EN 16931 UBL, GB VAT. No national e-invoicing mandate
    # (MTD covers VAT records); UBL export or Peppol (EAS 9932) both work.
    "GB": CountryProfile(
        code="GB", name=_COUNTRY_NAMES["GB"], default_standard="ubl",
        tax_scheme="VAT", tax_id_label="VAT Reg. No.",
        tax_id_pattern=_VAT_PATTERNS["GB"], currency_hint="GBP",
        notes="HMRC MTD: nessun obbligo e-invoice; UBL EN 16931 per l'interscambio.",
    ),
    # United States — sales tax (UN/ECE 5153 "STT"), EIN as the tax id.
    "US": _UsProfile(
        code="US", name=_COUNTRY_NAMES["US"], default_standard="ubl",
        tax_scheme="STT", tax_id_label="EIN",
        tax_id_pattern=_VAT_PATTERNS["US"], currency_hint="USD",
        notes="Nessun mandato federale; UBL EN 16931-style con sales tax (DBNAlliance-ready).",
    ),
}

_GENERIC = CountryProfile(code="", name="Generic", default_standard="ubl")


def profile_for(country_code: str | None) -> CountryProfile:
    """The profile for an ISO 3166-1 alpha-2 code (permissive fallback)."""
    return COUNTRY_PROFILES.get((country_code or "").upper(), _GENERIC)


def validate_tax_id(country_code: str, value: str | None) -> bool:
    return profile_for(country_code).validate_tax_id(value)


def renderer_for_country(country_code: str, *, xrechnung: bool = False, **kwargs) -> InvoiceRenderer:
    """The default renderer for a seller of ``country_code``.

    Italy → FatturaPA; everyone else → UBL (Peppol BIS 3.0) with the profile's
    tax scheme. ``xrechnung=True`` swaps in the German XRechnung CIUS
    ``CustomizationID``. Extra kwargs go to the renderer constructor.
    """
    from .formats.base import get_renderer

    profile = profile_for(country_code)
    if profile.default_standard == "fatturapa":
        return get_renderer("fatturapa", **kwargs)
    if xrechnung:
        kwargs.setdefault("customization", XRECHNUNG_CUSTOMIZATION)
    if profile.tax_scheme != "VAT":
        kwargs.setdefault("tax_scheme", profile.tax_scheme)
    return get_renderer("ubl", **kwargs)
