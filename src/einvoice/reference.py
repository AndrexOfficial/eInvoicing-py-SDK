"""JSON-safe views of the reference data, for platforms that expose it in a UI.

Everything here is already available as typed objects (:func:`profile_for`,
:func:`rates_for`, :class:`FiscalRules`). This module exists because the two
products that embed the package were each hand-maintaining their own copy of
the same country table in TypeScript — four countries where the package knows
thirty, kept in sync by comment. Reference data that is copied is reference
data that drifts, and a fiscal setup screen offering the wrong tax-id label is
wrong in a way nobody notices until an invoice is refused.

So: one endpoint per platform, serving this.

    from einvoice.reference import country_reference, all_country_references

    country_reference("IT")      # a dict, ready for JSON
    all_country_references()     # every supported country, same shape

Decimals become strings (never floats — money and rates do not survive binary
floating point) and dates become ISO strings, so the result passes through
``json.dumps`` unchanged.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from .countries import (
    COUNTRY_PROFILES,
    MANDATES_VERIFIED_AS_OF,
    CountryProfile,
    profile_for,
    supported_countries,
)
from .rates import COMMONLY_EXEMPT, NO_NATIONAL_VAT, RATES_VERIFIED_AS_OF, ProductCategory, rates_for

__all__ = [
    "country_reference",
    "all_country_references",
    "product_categories",
    "reference_metadata",
]


def _num(value: Decimal | None) -> str | None:
    """Decimal → string. Never float: 7.7 is not 7.7."""
    return None if value is None else str(value)


def _rates(code: str) -> list[dict[str, Any]]:
    return [
        {
            "rate": _num(r.rate),
            "kind": r.kind.value,
            "categories": [c.value for c in r.categories],
            "note": r.note or None,
        }
        for r in rates_for(code)
    ]


def country_reference(code: str) -> dict[str, Any]:
    """Everything a fiscal-setup screen needs for one country.

    Unlike :func:`profile_for`, this is **strict**. That function is
    deliberately permissive — it falls back to a generic profile so rendering
    an invoice never crashes on an unfamiliar country code. A setup screen is
    the opposite situation: it is *asking* what a country requires, and a
    generic answer presented as Portugal's rules is a wrong answer wearing a
    flag. So an unsupported code raises here, and the UI can say "not covered"
    instead of showing a plausible invention.

    :raises KeyError: the country is not supported.
    """
    normalized = (code or "").upper()
    if normalized not in COUNTRY_PROFILES:
        raise KeyError(
            f"{code!r} non è fra i paesi supportati: "
            f"{', '.join(sorted(supported_countries()))}"
        )
    p: CountryProfile = profile_for(normalized)
    rules = p.fiscal_rules
    regime = p.regime
    return {
        "code": p.code,
        "name": p.name,
        "eu_member": p.eu_member,
        "currency": p.currency_hint,
        "tax_scheme": p.tax_scheme,
        # What to call the identifier field, and what shape it must have.
        "tax_id_label": p.tax_id_label,
        "tax_id_pattern": p.tax_id_pattern,
        "default_standard": p.default_standard,
        "vat_rates": [_num(Decimal(r)) for r in p.vat_rates],
        "rates": _rates(p.code),
        "no_national_vat": NO_NATIONAL_VAT.get(p.code),
        "regime": {
            "network": regime.network,
            "b2g": regime.b2g,
            "b2b": regime.b2b,
            "customization": regime.customization,
            "national_format": regime.national_format,
            "notes": regime.notes or None,
        },
        "rules": {
            "retention_years": rules.retention_years,
            "simplified_invoice_threshold": _num(rules.simplified_invoice_threshold),
            "issue_deadline_days": rules.issue_deadline_days,
            "domestic_reverse_charge": rules.domestic_reverse_charge,
            "notes": rules.notes or None,
        },
        "notes": p.notes or None,
    }


def all_country_references() -> list[dict[str, Any]]:
    """Every supported country, sorted by code."""
    return [country_reference(code) for code in sorted(supported_countries())]


def product_categories() -> list[dict[str, Any]]:
    """The category vocabulary, for a "what is being sold" picker.

    ``commonly_exempt`` marks the categories that carry no rate at all rather
    than a reduced one — the distinction that decides whether input VAT is
    deductible, and the one most often collapsed into "0%".
    """
    return [
        {"value": c.value, "commonly_exempt": c in COMMONLY_EXEMPT}
        for c in sorted(ProductCategory, key=lambda c: c.value)
    ]


def reference_metadata() -> dict[str, str]:
    """When this data was last checked against the authorities.

    Worth surfacing next to the data itself: an operator reading a rate
    deserves to know how old the answer is.
    """
    return {
        "rates_verified_as_of": RATES_VERIFIED_AS_OF.isoformat(),
        "mandates_verified_as_of": MANDATES_VERIFIED_AS_OF.isoformat(),
    }
