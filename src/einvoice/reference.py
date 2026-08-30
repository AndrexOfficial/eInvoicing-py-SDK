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
from .i18n import translate
from .rates import COMMONLY_EXEMPT, NO_NATIONAL_VAT, RATES_VERIFIED_AS_OF, ProductCategory, rates_for

__all__ = [
    "country_reference",
    "all_country_references",
    "product_categories",
    "reference_metadata",
    "provider_reference",
    "all_provider_references",
    "provider_kind_reference",
    "renderer_reference",
    "all_renderer_references",
    "locale_reference",
    "device_reference",
    "all_device_references",
    "pos_payment_reference",
    "fiscal_device_catalogue",
    "pos_terminal_catalogue",
]


def _num(value: Decimal | None) -> str | None:
    """Decimal → string. Never float: 7.7 is not 7.7."""
    return None if value is None else str(value)


def _label(prefix: str, value: str | None, locale: str | None) -> str | None:
    """Il nome leggibile di un valore di vocabolario, o ``None`` se non c'è.

    Restituire ``None`` invece del valore grezzo è deliberato: chi consuma deve
    poter distinguere «non tradotto» da «tradotto», e un'etichetta che copia
    l'identificatore è indistinguibile da un'etichetta mancante.
    """
    if not value:
        return None
    chiave = f"{prefix}.{value}"
    tradotto = translate(chiave, locale)
    return None if tradotto == chiave else tradotto


def _device(code: str) -> dict[str, Any]:
    """The cash-register regime, JSON-safe.

    Never absent and never raising: an unprofiled country answers
    ``"unknown"``, which is a usable answer where a missing key is not. Kept
    untranslated on purpose, like ``regime`` next to it — the values are a
    vocabulary the caller branches on, and the two would drift apart if one of
    them started arriving as prose.
    """
    from .devices import device_regime

    regime = device_regime(code)
    return {
        "requirement": regime.requirement,
        "reporting": regime.reporting,
        "device_name": regime.device_name or None,
        "certified_software": regime.certified_software,
        "receipt_lottery": regime.receipt_lottery,
        "pos_link_required": regime.pos_link_required,
        "pos_link_since": regime.pos_link_since.isoformat() if regime.pos_link_since else None,
        "needs_a_device": regime.needs_a_device,
        "notes": regime.notes or None,
    }


def _rates(code: str, locale: str | None = None) -> list[dict[str, Any]]:
    return [
        {
            "rate": _num(r.rate),
            "kind": r.kind.value,
            # Il valore resta: il codice ci si dirama sopra. Accanto c'è la
            # parola che legge una persona — perché finora i prodotti
            # stampavano «super_reduced» accanto a etichette tradotte.
            "kind_label": _label("rate_kind", r.kind.value, locale),
            "categories": [c.value for c in r.categories],
            "note": r.note or None,
        }
        for r in rates_for(code)
    ]


def country_reference(code: str, locale: str | None = None) -> dict[str, Any]:
    """Everything a fiscal-setup screen needs for one country.

    ``locale`` sceglie la lingua delle **etichette** (``kind_label``,
    ``b2b_label``, ``b2g_label``): i valori accanto a cui stanno restano
    invariati, perché sono identificatori su cui il codice si dirama. Omesso,
    si ottiene l'inglese. Le lingue sono quelle di :mod:`einvoice.i18n`.

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
        "rates": _rates(p.code, locale),
        "no_national_vat": NO_NATIONAL_VAT.get(p.code),
        "regime": {
            "network": regime.network,
            "b2g": regime.b2g,
            "b2b": regime.b2b,
            "b2g_label": _label("mandate", regime.b2g, locale),
            "b2b_label": _label("mandate", regime.b2b, locale),
            "customization": regime.customization,
            "national_format": regime.national_format,
            "notes": regime.notes or None,
        },
        # The other half of "what does this country require of me": the
        # e-invoicing regime says how a FATTURA travels, this says whether
        # selling over a counter needs a certified device at all. A POS product
        # asks both questions and used to get only one answered.
        "fiscal_device": _device(p.code),
        "rules": {
            "retention_years": rules.retention_years,
            "simplified_invoice_threshold": _num(rules.simplified_invoice_threshold),
            "issue_deadline_days": rules.issue_deadline_days,
            "domestic_reverse_charge": rules.domestic_reverse_charge,
            "notes": rules.notes or None,
        },
        "notes": p.notes or None,
    }


def all_country_references(locale: str | None = None) -> list[dict[str, Any]]:
    """Every supported country, sorted by code. ``locale`` come sopra."""
    return [country_reference(code, locale) for code in sorted(supported_countries())]


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


# ────────────────────────────────────────── platforms and formats ──
#
# The country table was not the only thing being hand-maintained downstream.
# Both products also carried their own hard-coded provider list — one of six
# entries, one of ten, neither matching the transport registry — rendered as
# raw keys (``wolters_kluwer``) with a fixed set of five credential inputs and
# no setup instructions anywhere. Same failure as the country copies, same fix:
# the package knows, so the package serves it.


def provider_reference(key: str, locale: str | None = None) -> dict[str, Any]:
    """One platform, with its localized setup guide.

    Thin by design — :func:`einvoice.onboarding.setup_guide` does the work; this
    exists so a host has a single import (``einvoice.reference``) for everything
    its fiscal-setup screen needs.

    :raises ProviderConfigError: unknown platform key.
    """
    from .onboarding import setup_guide

    return setup_guide(key, locale)


def all_provider_references(locale: str | None = None, *, country: str | None = None,
                            kind: str | None = None) -> list[dict[str, Any]]:
    """Every platform a picker could offer, optionally narrowed to a country.

    With ``country`` the ordering is the one
    :func:`~einvoice.transport.providers.providers_for_country` establishes:
    platforms that name the country, then the aggregators that merely cover it.
    """
    from .onboarding import all_setup_guides

    return all_setup_guides(locale, country=country, kind=kind)


def provider_kind_reference(locale: str | None = None) -> list[dict[str, Any]]:
    """The platform categories, labelled in one language.

    A flat list of sixty-five platforms is not navigable; the categories are how
    a picker becomes one, and they differ in ways that change the integration.
    """
    from .i18n import translate
    from .transport.providers import PROVIDER_KINDS, providers_of_kind

    return [
        {
            "key": kind,
            "label": translate(f"kind.{kind}", locale),
            "count": len(providers_of_kind(kind)),
        }
        for kind in sorted(PROVIDER_KINDS)
    ]


def renderer_reference(key: str, locale: str | None = None) -> dict[str, Any]:
    """One document format, described rather than merely named.

    :raises RenderError: unknown renderer key.
    """
    from .formats.catalog import renderer_spec
    from .i18n import translate

    spec = renderer_spec(key)
    return {
        "key": spec.key,
        "standard": spec.standard,
        "is_alias": spec.is_alias,
        "name": translate(f"renderer.{spec.standard}.name", locale),
        "description": translate(f"renderer.{spec.standard}.description", locale),
        "syntax": spec.syntax,
        "aliases": list(spec.aliases),
        "mime": spec.mime,
        "extension": spec.extension,
        "countries": list(spec.countries),
        "options": list(spec.options),
        "docs_url": spec.docs_url,
        "profiles": [
            {"key": pr.key, "name": pr.name, "countries": list(pr.countries), "how": pr.how}
            for pr in spec.profiles
        ],
    }


def all_renderer_references(locale: str | None = None, *,
                            country: str | None = None) -> list[dict[str, Any]]:
    """The formats worth offering, aliases collapsed.

    Without ``country`` the three real renderers, national one last; with it,
    only the ones that country's recipients accept — see
    :func:`einvoice.formats.catalog.renderers_for_country` for why another
    country's national format is excluded rather than merely deprioritized.
    """
    from .formats.catalog import RENDERER_SPECS, renderers_for_country

    specs = (renderers_for_country(country) if country
             else [s for s in RENDERER_SPECS.values() if not s.is_alias and s.key != "peppol"])
    return [renderer_reference(s.key, locale) for s in specs]


def locale_reference() -> dict[str, Any]:
    """Which languages the labels above come in, and the default per country.

    A host that lets an operator pick a language needs to know which ones are
    real here; one that only knows the country can read ``default_by_country``
    instead of guessing.
    """
    from .i18n import DEFAULT_LOCALE, LOCALES_BY_COUNTRY, available_locales

    return {
        "locales": available_locales(),
        "default": DEFAULT_LOCALE,
        "default_by_country": {c: langs[0] for c, langs in sorted(LOCALES_BY_COUNTRY.items())},
    }


def device_reference(code: str) -> dict[str, Any]:
    """The cash-register regime of one country, on its own.

    Permissive where :func:`country_reference` is strict, and for the same
    reason turned around: "do I need a till?" has a useful answer even when it
    is "we have not checked this country" — a ``KeyError`` in the middle of a
    setup screen has none.
    """
    from .devices import FISCAL_DEVICES_VERIFIED_AS_OF

    return {
        "code": (code or "").upper(),
        **_device(code),
        "verified_as_of": FISCAL_DEVICES_VERIFIED_AS_OF.isoformat(),
    }


def all_device_references() -> list[dict[str, Any]]:
    """Every country the device table names, sorted."""
    from .devices import FISCAL_DEVICE_REGIMES

    return [device_reference(code) for code in sorted(FISCAL_DEVICE_REGIMES)]


def pos_payment_reference() -> list[dict[str, Any]]:
    """How each till payment maps onto ``ModalitaPagamento``.

    ``exact`` is the field worth rendering: the MP list was written for
    invoicing, and for a couple of very common counter payments there is no
    dedicated code. A UI that hides that difference hides the only part an
    accountant would have wanted to see.
    """
    from .pos import PAYMENT_MEANS_BY_POS, PosPaymentMethod

    return [
        {
            "method": method.value,
            "payment_means": (mapping.code.value if mapping.code else None),
            "exact": mapping.exact,
            "note": mapping.note or None,
        }
        for method, mapping in ((m, PAYMENT_MEANS_BY_POS[m]) for m in PosPaymentMethod)
    ]


def fiscal_device_catalogue(country: str | None = None) -> list[dict[str, Any]]:
    """Le famiglie di dispositivi fiscali, in JSON.

    Con ``country`` restano solo quelle utilizzabili lì, quelle che lo nominano
    prima: l'omologazione è nazionale, e un elenco che mescolasse i paesi
    manderebbe qualcuno a comprare un RT italiano per un negozio di Monaco.

    ``fiscal=False`` marca le termiche ESC/POS. Sono a catalogo perché in sala
    ci sono comunque, e perché scambiarle per un RT è l'errore che costa una
    sanzione.
    """
    from .devices import FISCAL_DEVICE_MODELS, devices_for_country

    models = (devices_for_country(country) if country
              else [FISCAL_DEVICE_MODELS[k] for k in sorted(FISCAL_DEVICE_MODELS)])
    return [
        {
            "key": d.key,
            "vendor": d.vendor,
            "models": list(d.models),
            "countries": list(d.countries),
            "protocol": d.protocol,
            "public_protocol": d.public_protocol,
            "connection": list(d.connection),
            "capabilities": list(d.capabilities),
            "driver_hint": d.driver_hint,
            "fiscal": d.fiscal,
            "docs_url": d.docs_url or None,
            "notes": d.notes or None,
        }
        for d in models
    ]


def pos_terminal_catalogue(country: str | None = None) -> list[dict[str, Any]]:
    """Le famiglie di terminali di pagamento, in JSON.

    Nessuna di queste voci dichiara di essere implementata da qualcuno: questo
    pacchetto non parla con nessun terminale, e chi lo incorpora sa quali ha
    davvero cablato. Qui c'è l'anagrafica — chi produce cosa, che via di
    integrazione espone, dove sta la documentazione.
    """
    from .devices import POS_TERMINALS, terminals_for_country

    terminals = (terminals_for_country(country) if country
                 else [POS_TERMINALS[k] for k in sorted(POS_TERMINALS)])
    return [
        {
            "key": t.key,
            "vendor": t.vendor,
            "models": list(t.models),
            "countries": list(t.countries),
            "integration": t.integration,
            "connection": list(t.connection),
            "docs_url": t.docs_url or None,
            "notes": " ".join(x for x in (t.countries_note, t.notes) if x) or None,
        }
        for t in terminals
    ]
