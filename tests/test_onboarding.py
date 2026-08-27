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
    applied. An operator filling a Base URL FattureInCloud does not use, and
    skipping the Company ID it cannot work without, has been misled by the form."""
    keys = [f["key"] for f in credential_fields(preset_for("fattureincloud"), "it")]

    assert keys == ["api_key", "company_id"]
    assert "base_url" not in keys       # its host is known


def test_credential_fields_add_base_url_when_the_host_is_unknowable():
    keys = [f["key"] for f in credential_fields(preset_for("infocert"), "it")]

    assert keys[-1] == "base_url"


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
