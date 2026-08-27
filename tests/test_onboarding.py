"""Setup guides — generated from the presets, so they cannot drift from them.

The point of generating rather than writing these is that a preset added as a
one-line dict entry arrives with instructions in every language. That only
holds if every key a preset can produce actually exists in the catalog, so
most of what follows is that cross-check: walk all sixty-five presets, build
every guide, and assert nothing came out as a raw key.
"""
import json

import pytest

from einvoice.errors import ProviderConfigError, RenderError
from einvoice.formats.catalog import (
    RENDERER_SPECS,
    _assert_registry_agreement,
    renderer_spec,
    renderers_for_country,
)
from einvoice.i18n import LOCALES, translation_keys
from einvoice.onboarding import (
    SETUP_FLAGS,
    credential_fields,
    setup_caveats,
    setup_guide,
    setup_steps,
)
from einvoice.reference import (
    all_provider_references,
    all_renderer_references,
    locale_reference,
    provider_kind_reference,
    renderer_reference,
)
from einvoice.transport import PROVIDER_KINDS, PROVIDER_PRESETS, preset_for

_KEYS = set(translation_keys())


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_every_step_a_preset_can_produce_has_a_translation(key):
    """An untranslated step surfaces as ``step.whatever`` on a settings page."""
    preset = PROVIDER_PRESETS[key]
    for step in [*setup_steps(preset), *setup_caveats(preset)]:
        assert step.key in _KEYS, step.key


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_every_preset_declares_only_known_setup_flags(key):
    """A typo'd flag is silently ignored — and the warning never appears."""
    assert set(PROVIDER_PRESETS[key].setup_flags) <= SETUP_FLAGS


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_every_preset_has_a_translated_kind_and_capabilities(key):
    preset = PROVIDER_PRESETS[key]

    assert f"kind.{preset.kind}" in _KEYS
    for capability in preset.supports:
        assert f"capability.{capability}" in _KEYS, capability


@pytest.mark.parametrize("kind", sorted(PROVIDER_KINDS))
def test_every_kind_is_labelled(kind):
    assert f"kind.{kind}" in _KEYS


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_every_guide_is_json_safe_and_free_of_raw_keys(key):
    guide = setup_guide(key, "el")
    json.dumps(guide)

    for step in [*guide["steps"], *guide["caveats"]]:
        assert step["text"] != step["key"], step["key"]
        assert not step["text"].startswith(("step.", "label.")), step["text"]
    assert not guide["kind_label"].startswith("kind.")


def test_credential_fields_show_only_what_the_platform_needs():
    """The bug this replaces: five inputs for every provider, of which two
    applied. An operator filling a Base URL as if it were mandatory, and
    skipping the Company ID FattureInCloud cannot work without, has been misled
    by the form."""
    fields = credential_fields(preset_for("fattureincloud"), "it")

    assert [f["key"] for f in fields] == ["api_key", "company_id", "base_url"]
    assert [f["required"] for f in fields] == [True, True, False]


def test_a_known_host_makes_base_url_optional_not_absent():
    """Every transport reads ``config.base_url or <its default>``, so a supplied
    value is a real override — and ``step.known_base_url`` tells the operator to
    leave the field empty, which is only an instruction if the field exists."""
    base_url = next(f for f in credential_fields(preset_for("aruba"), "it")
                    if f["key"] == "base_url")

    assert base_url["required"] is False
    assert base_url["optional_label"] == "facoltativo"
    assert base_url["placeholder"] == "https://ws.fatturazioneelettronica.aruba.it"


def test_credential_fields_require_base_url_when_the_host_is_unknowable():
    fields = credential_fields(preset_for("infocert"), "it")
    base_url = fields[-1]

    assert base_url["key"] == "base_url"
    assert base_url["required"] is True
    assert base_url["optional_label"] is None
    assert base_url["placeholder"] is None


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_base_url_is_required_exactly_when_the_preset_cannot_default_it(key):
    """The two facts must not drift: a field marked optional whose transport
    then refuses to build is a form that lies about what it needs."""
    preset = PROVIDER_PRESETS[key]
    if preset.is_manual:
        return          # no form at all — see test_a_manual_channel_collects_nothing
    base_url = next(f for f in credential_fields(preset, "en") if f["key"] == "base_url")

    assert base_url["required"] is preset.needs_base_url


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_secrets_are_marked_as_secrets(key):
    """A host that renders these fields decides on ``type=password`` from here."""
    for field in credential_fields(PROVIDER_PRESETS[key], "en"):
        assert field["secret"] is (field["key"] in {"api_key", "access_token", "password"})


def test_a_channel_that_refuses_our_format_does_not_also_claim_to_want_it():
    """KSeF takes FA(2) only. Printing "this platform expects UBL" beside
    "this platform accepts only FA(2)" makes the guide argue with itself."""
    guide = setup_guide("ksef", "en")

    assert not any(s["key"] == "step.render_format" for s in guide["steps"])
    assert any(s["key"] == "step.national_format_warning" for s in guide["caveats"])


def test_a_verified_preset_carries_no_confirm_paths_caveat():
    assert setup_caveats(preset_for("aruba")) == []
    assert any(s.key == "step.confirm_paths" for s in setup_caveats(preset_for("storecove")))


def test_a_national_portal_is_not_told_to_ask_for_api_access():
    """True of a vendor with pricing plans, false of a government channel."""
    assert not any(s.key == "step.request_api_access" for s in setup_steps(preset_for("chorus_pro")))


def test_the_italian_preset_note_is_labelled_as_italian():
    """It is not part of the translated catalog. Handing it to a Greek operator
    unlabelled passes off Italian prose as their own language."""
    guide = setup_guide("aruba", "el")

    assert guide["notes"]
    assert guide["notes_language"] == "it"


def test_unknown_platform_raises_the_registry_error():
    with pytest.raises(ProviderConfigError):
        setup_guide("nope", "en")


# ── renderer catalog ──────────────────────────────────────────────────


def test_every_described_renderer_can_actually_be_built():
    assert _assert_registry_agreement() == []


@pytest.mark.parametrize("key", sorted(RENDERER_SPECS))
def test_every_renderer_spec_is_labelled(key):
    spec = renderer_spec(key)

    assert f"renderer.{spec.standard}.name" in _KEYS
    assert f"renderer.{spec.standard}.description" in _KEYS


def test_aliases_resolve_to_the_thing_they_alias():
    assert renderer_spec("zugferd").standard == "cii"
    assert renderer_spec("facturx").standard == "cii"
    assert renderer_spec("peppol").standard == "ubl"


def test_another_countrys_national_format_is_not_offered():
    """Offering FatturaPA to a French seller is offering a guaranteed rejection."""
    assert "fatturapa" not in [s.key for s in renderers_for_country("FR")]
    assert [s.key for s in renderers_for_country("IT")][0] == "fatturapa"


def test_renderer_listing_collapses_aliases():
    keys = [r["key"] for r in all_renderer_references("en")]

    assert keys == ["fatturapa", "ubl", "cii"]


def test_unknown_renderer_raises_the_format_error():
    with pytest.raises(RenderError):
        renderer_reference("nope")


# ── reference views ───────────────────────────────────────────────────


def test_country_filter_keeps_the_national_platforms_first():
    italian = all_provider_references("it", country="IT")
    first_wide = next(i for i, p in enumerate(italian) if "IT" not in p["countries"])

    assert all("IT" in p["countries"] for p in italian[:first_wide])


def test_kind_reference_counts_match_the_registry():
    total = sum(k["count"] for k in provider_kind_reference("en"))

    assert total == len(PROVIDER_PRESETS)


def test_locale_reference_agrees_with_the_catalog():
    reference = locale_reference()

    assert reference["locales"] == list(LOCALES)
    assert set(reference["default_by_country"].values()) <= set(LOCALES)


def test_the_guide_never_points_at_a_field_the_form_does_not_render():
    """``step.known_base_url`` says "leave the field empty"; a form without that
    field turns the instruction into a reference to nothing."""
    for key, preset in PROVIDER_PRESETS.items():
        steps = {s.key for s in setup_steps(preset)}
        fields = {f["key"] for f in credential_fields(preset, "en")}
        if {"step.known_base_url", "step.ask_base_url"} & steps:
            assert "base_url" in fields, key


# ── canali senza API ──────────────────────────────────────────────────
#
# The Agenzia delle Entrate portal, the SdI PEC address and AssoInvoice are
# among the most used channels in Italy and none of them speaks REST. Modelling
# them as hub presets would have shipped three entries that look integrated and
# fail on first use.

MANUAL = ["agenzia_entrate", "sdipec", "assoinvoice"]


@pytest.mark.parametrize("key", MANUAL)
def test_a_manual_channel_exports_a_file_instead_of_pretending_to_have_an_api(key):
    preset = preset_for(key)

    assert preset.is_manual
    assert preset.transport == "file"
    assert preset.credentials == ()
    assert preset.needs_base_url is False, "there is no host to ask for"


@pytest.mark.parametrize("key", MANUAL)
def test_a_manual_channel_collects_nothing(key):
    """A Base URL box next to "upload it yourself" is not an honest form."""
    assert credential_fields(preset_for(key), "it") == []


@pytest.mark.parametrize("key", MANUAL)
def test_a_manual_channel_says_who_carries_the_file(key):
    steps = [s.key for s in setup_steps(preset_for(key))]

    assert "step.render_format" in steps
    assert {"step.manual_delivery", "step.manual_delivery_pec"} & set(steps)
    # None of the API sequence applies.
    assert not {"step.request_api_access", "step.copy_api_key", "step.ask_base_url",
                "step.known_base_url", "step.store_credentials"} & set(steps)


@pytest.mark.parametrize("key", MANUAL)
def test_a_manual_channel_admits_that_nothing_polls(key):
    """The one thing it silently costs: "sent" becomes a state only a person
    can move the record into."""
    assert "step.no_status_tracking" in [c.key for c in setup_caveats(preset_for(key))]


@pytest.mark.parametrize("key", MANUAL)
def test_a_manual_channel_shows_no_endpoint_badge(key):
    """Neither "verified" nor "to confirm" says anything true about a channel
    with no endpoints."""
    assert setup_guide(key, "en")["verification_label"] is None


def test_the_pec_step_carries_the_address_it_is_about():
    guide = setup_guide("sdipec", "it")
    pec = next(s for s in guide["steps"] if s["key"] == "step.manual_delivery_pec")

    assert "sdi01@pec.fatturapa.it" in pec["text"]
    assert guide["delivery_target"] == "sdi01@pec.fatturapa.it"


@pytest.mark.parametrize("key", ["fattura24", "libero_sifattura", "fattura_per_tutti",
                                 "fatturaelettronica_app"])
def test_the_new_rest_presets_ask_the_caller_for_the_host(key):
    """None of these four has been called from here, so none of them ships a
    URL: the project rule is that an unverified endpoint is the caller's to
    supply, not ours to invent."""
    preset = preset_for(key)

    assert preset.endpoints_verified is False
    assert preset.needs_base_url is True
    assert preset.base_url is None


def test_every_platform_named_by_the_italian_market_roundup_is_present():
    """The list a shop owner actually meets when they go looking."""
    expected = {
        "fattura24", "aruba", "fattureincloud", "libero_sifattura",
        "fattura_per_tutti", "fiscozen", "fatturaelettronica_app", "danea",
        "agenzia_entrate", "assoinvoice", "sdipec",
    }

    assert expected <= set(PROVIDER_PRESETS)
