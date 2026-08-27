"""Setup instructions for a platform, composed rather than written.

A preset says *what* to send where. It never said **how to get in the door** —
which account to open, which of the five credential fields this vendor actually
wants, whether there is a sandbox, and what will bite you. Both products
embedding this package showed the same five inputs for every provider and no
instructions at all, so "configure FattureInCloud" meant filling a Base URL
that FattureInCloud does not use and leaving a Company ID it cannot work
without.

Writing sixty-five prose guides would have solved that in one language. Instead
each preset names an ordered sequence of **step keys** from
:mod:`einvoice.i18n`, and the sequence is mostly *derived* — from the
credentials it declares, from whether its host is knowable, from whether it has
a sandbox. So a platform added as a one-line dict entry arrives with a complete
guide in thirty-one languages, and a guide cannot drift from the preset it
describes, because it is generated from it.

    from einvoice.onboarding import setup_guide

    guide = setup_guide("fattureincloud", "de")
    [s["text"] for s in guide["steps"]]
    [f["label"] for f in guide["credentials"]]     # only the two it needs

What is *not* derived: the vendor-specific warnings (a signed contract, OAuth2,
a qualified certificate, a national syntax this package does not emit). Those
are declared per preset, because no amount of looking at a credentials tuple
reveals that KSeF wants FA(2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .formats.catalog import RENDERER_SPECS
from .i18n import DEFAULT_LOCALE, normalize_locale, translate
from .transport.providers import PROVIDER_PRESETS, ProviderPreset, preset_for

__all__ = [
    "SetupStep",
    "SETUP_FLAGS",
    "setup_steps",
    "setup_caveats",
    "credential_fields",
    "setup_guide",
    "all_setup_guides",
]

#: Vendor facts that no credential tuple reveals, declared on the preset.
SETUP_FLAGS = {
    #: Credentials come with a signed contract, not from a self-service portal.
    "contract",
    #: OAuth2 client registration rather than a static key.
    "oauth2",
    #: A qualified certificate is part of the connection (mTLS, national PKI).
    "certificate",
}

#: Credential key → the i18n stem for its label and hint.
_CREDENTIAL_LABELS = {
    "api_key": "credential.api_key",
    "access_token": "credential.api_key",
    "username": "credential.username",
    "password": "credential.password",
    "company_id": "credential.company_id",
    "base_url": "credential.base_url",
}

#: Credential keys whose value must never be echoed back to a client.
_SECRET_CREDENTIALS = frozenset({"api_key", "access_token", "password"})


@dataclass(frozen=True)
class SetupStep:
    """One instruction, before translation.

    Kept as ``(key, params)`` rather than a rendered string so the same step
    list serves every language, and so a client that would rather write its own
    copy can switch on the key.
    """

    key: str
    params: dict[str, str] = field(default_factory=dict)

    def text(self, locale: str | None = DEFAULT_LOCALE) -> str:
        return translate(self.key, locale, **self.params)


def _renderer_syntax(renderer: str) -> str:
    """Human name of the format a preset expects — ``FatturaPA 1.2.2``.

    The syntax name rather than the registry key: an operator has to recognise
    it in the vendor's own onboarding form, where it will not say ``ubl``.
    """
    spec = RENDERER_SPECS.get((renderer or "").lower())
    return spec.syntax if spec else renderer


def setup_steps(preset: ProviderPreset) -> list[SetupStep]:
    """The ordered actions for one platform.

    Order follows the real sequence: get an account, get access, collect what
    the form below needs, point it at the right host, agree on the format, try
    it somewhere harmless, then save.
    """
    platform = {"platform": preset.name}
    steps = [SetupStep("step.create_account", platform)]

    if "contract" in preset.setup_flags:
        steps.append(SetupStep("step.contract_required", platform))
    elif preset.kind != "national_portal":
        # "Ask them to switch the API on, it is off by default on most plans"
        # is a true sentence about a vendor and a false one about a government
        # channel: a national portal has no plans and nothing to switch on.
        steps.append(SetupStep("step.request_api_access", platform))
    if "certificate" in preset.setup_flags:
        steps.append(SetupStep("step.certificate_required"))
    if "oauth2" in preset.setup_flags:
        steps.append(SetupStep("step.oauth2_required"))

    creds = set(preset.credentials)
    if creds & {"api_key", "access_token"}:
        steps.append(SetupStep("step.copy_api_key"))
    if "company_id" in creds:
        steps.append(SetupStep("step.copy_company_id"))
    if creds & {"username", "password"}:
        steps.append(SetupStep("step.copy_username_password"))

    if preset.needs_base_url:
        steps.append(SetupStep("step.ask_base_url", platform))
    else:
        steps.append(SetupStep("step.known_base_url", {"base_url": preset.base_url or ""}))

    if not preset.incompatible_national_format:
        # Where the channel refuses what we generate, saying "this platform
        # expects UBL" next to a caveat saying it accepts only FA(2) reads as a
        # contradiction. The caveat is the true statement; it stands alone.
        steps.append(SetupStep("step.render_format",
                               {"format": _renderer_syntax(preset.renderer)}))

    if "receive" in preset.supports:
        steps.append(SetupStep("step.receive_inbound"))

    if preset.sandbox_url:
        steps.append(SetupStep("step.sandbox_url", {"sandbox_url": preset.sandbox_url}))
    else:
        steps.append(SetupStep("step.sandbox_missing"))

    steps.append(SetupStep("step.test_before_live"))
    steps.append(SetupStep("step.store_credentials"))
    return steps


def setup_caveats(preset: ProviderPreset) -> list[SetupStep]:
    """What will bite you, separated from what to do.

    Kept out of :func:`setup_steps` on purpose: a warning inside a numbered
    checklist reads as a step to tick off, and "this channel will not accept
    what we generate" is not a step, it is a reason to stop.
    """
    caveats: list[SetupStep] = []
    if preset.incompatible_national_format:
        caveats.append(SetupStep("step.national_format_warning",
                                 {"format": preset.incompatible_national_format}))
    if not preset.endpoints_verified:
        caveats.append(SetupStep("step.confirm_paths", {"platform": preset.name}))
    return caveats


def credential_fields(preset: ProviderPreset, locale: str | None = DEFAULT_LOCALE) -> list[dict[str, Any]]:
    """The inputs this platform's form should show — and only those.

    ``base_url`` is appended when the host is not knowable in advance, which is
    why it is optional-looking in the presets and mandatory in practice: the
    transport cannot be built without it.
    """
    resolved = normalize_locale(locale)
    keys = list(preset.credentials)
    if preset.needs_base_url and "base_url" not in keys:
        keys.append("base_url")

    fields: list[dict[str, Any]] = []
    for key in keys:
        stem = _CREDENTIAL_LABELS.get(key)
        fields.append({
            "key": key,
            "label": translate(stem, resolved) if stem else key,
            "hint": translate(f"{stem}.hint", resolved) if stem else None,
            "secret": key in _SECRET_CREDENTIALS,
            "required": True,
        })
    return fields


def setup_guide(key: str, locale: str | None = DEFAULT_LOCALE) -> dict[str, Any]:
    """Everything a setup screen needs for one platform, in one language.

    JSON-safe throughout, so a host can serve it straight from an endpoint.

    :raises ProviderConfigError: unknown platform key.
    """
    preset = preset_for(key)
    resolved = normalize_locale(locale)
    return {
        "key": preset.key,
        "name": preset.name,
        "locale": resolved,
        "kind": preset.kind,
        "kind_label": translate(f"kind.{preset.kind}", resolved),
        "countries": list(preset.countries),
        "transport": preset.transport,
        "renderer": preset.renderer,
        "renderer_syntax": _renderer_syntax(preset.renderer),
        "supports": list(preset.supports),
        "capabilities": [
            {"key": cap, "label": translate(f"capability.{cap}", resolved)}
            for cap in preset.supports
        ],
        "credentials": credential_fields(preset, resolved),
        "needs_base_url": preset.needs_base_url,
        "base_url": preset.base_url,
        "sandbox_url": preset.sandbox_url,
        "docs_url": preset.docs_url,
        "endpoints_verified": preset.endpoints_verified,
        "verification_label": translate(
            "label.verified_yes" if preset.endpoints_verified else "label.verified_no", resolved
        ),
        "steps": [{"key": s.key, "text": s.text(resolved)} for s in setup_steps(preset)],
        "caveats": [{"key": s.key, "text": s.text(resolved)} for s in setup_caveats(preset)],
        # The preset's own free-text note. Authored in Italian and NOT part of
        # the translated catalog — surfaced with its language stated so a client
        # can label it rather than pass it off as the operator's own language.
        "notes": preset.notes or None,
        "notes_language": "it" if preset.notes else None,
        "labels": {
            "setup": translate("label.setup", resolved),
            "credentials": translate("label.credentials", resolved),
            "steps": translate("label.steps", resolved),
            "caveats": translate("label.caveats", resolved),
            "documentation": translate("label.documentation", resolved),
            "markets": translate("label.markets", resolved),
            "category": translate("label.category", resolved),
            "format": translate("label.format", resolved),
            "capabilities": translate("label.capabilities", resolved),
        },
    }


def all_setup_guides(locale: str | None = DEFAULT_LOCALE, *,
                     country: str | None = None,
                     kind: str | None = None) -> list[dict[str, Any]]:
    """Every platform's guide, optionally narrowed the way a picker would.

    Filtering here rather than in the caller keeps the country ordering that
    :func:`~einvoice.transport.providers.providers_for_country` establishes —
    platforms naming the country first, aggregators after.
    """
    if country:
        from .transport.providers import providers_for_country
        presets = providers_for_country(country, kind=kind)
    elif kind:
        from .transport.providers import providers_of_kind
        presets = providers_of_kind(kind)
    else:
        presets = [PROVIDER_PRESETS[k] for k in sorted(PROVIDER_PRESETS)]
    return [setup_guide(p.key, locale) for p in presets]
