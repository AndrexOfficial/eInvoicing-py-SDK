"""Platform presets — Fiscozen, Storecove, Chorus Pro and the rest.

A preset is a claim about a vendor: this transport, these credentials, that
renderer. The tests below mostly guard the claims we make *about our own
confidence* — a preset that quietly pretends its endpoints are verified is
worse than no preset at all, because it fails on first use in production.
"""
import pytest

from einvoice.errors import ProviderConfigError
from einvoice.formats import available_renderers
from einvoice.transport import (
    PROVIDER_KINDS,
    PROVIDER_PRESETS,
    available_providers,
    available_transports,
    preset_for,
    providers_for_country,
    providers_of_kind,
    transport_for_provider,
)


def test_the_registry_is_not_empty_and_is_sorted():
    names = available_providers()
    assert names == sorted(names)
    assert len(names) >= 20


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_every_preset_points_at_a_real_transport_and_renderer(key):
    """A preset naming a transport that does not exist fails only at send time."""
    preset = PROVIDER_PRESETS[key]
    assert preset.transport in available_transports(), preset.transport
    assert preset.renderer in available_renderers(), preset.renderer


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_every_preset_declares_its_key_consistently(key):
    assert PROVIDER_PRESETS[key].key == key


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_unverified_presets_require_a_base_url_or_name_one(key):
    """If we have not called it, the caller must supply the host — the whole
    point of the honesty flag is that we do not invent one."""
    preset = PROVIDER_PRESETS[key]
    if not preset.endpoints_verified:
        assert preset.needs_base_url or preset.base_url, (
            f"{key}: unverified preset must either ask for base_url or carry a "
            "documented one"
        )


def test_verified_presets_are_the_ones_with_dedicated_adapters():
    """Only the transports this package implements end-to-end may claim it."""
    verified = {k for k, p in PROVIDER_PRESETS.items() if p.endpoints_verified}
    assert verified == {"aruba", "fattureincloud"}


# ── Fiscozen, the one that was asked for by name ───────────────────────────


def test_fiscozen_is_registered_for_italy_and_renders_fatturapa():
    preset = preset_for("fiscozen")
    assert preset.country == "IT"
    # SdI takes FatturaPA. Sending UBL would be rejected.
    assert preset.renderer == "fatturapa"
    assert preset in providers_for_country("IT")


def test_fiscozen_says_plainly_that_its_endpoints_are_unconfirmed():
    preset = preset_for("fiscozen")
    assert preset.endpoints_verified is False
    assert preset.needs_base_url
    assert preset.docs_url


def test_building_a_transport_without_credentials_names_what_is_missing():
    with pytest.raises(ProviderConfigError) as exc:
        transport_for_provider("fiscozen")
    message = str(exc.value)
    assert "api_key" in message and "base_url" in message
    assert "fiscozen.it" in message, "the error should point at the vendor's docs"


def test_building_a_transport_with_credentials_works():
    transport = transport_for_provider(
        "fiscozen", api_key="secret", base_url="https://api.fiscozen.example",
    )
    assert transport.name == "fiscozen"
    assert transport.base == "https://api.fiscozen.example"


def test_caller_extra_overrides_the_preset_defaults():
    """Vendors rename fields between plan tiers; the caller must win."""
    transport = transport_for_provider(
        "fiscozen", api_key="k", base_url="https://x",
        extra={"content_field": "documentXml"},
    )
    assert transport.config.extra["content_field"] == "documentXml"
    # ...while untouched preset defaults survive the merge.
    assert transport.config.extra["upload_path"] == "/invoices"


# ── the rest of the registry ───────────────────────────────────────────────


def test_sandbox_url_is_preferred_in_sandbox_mode():
    live = transport_for_provider("aruba", username="u", password="p", sandbox=False)
    test = transport_for_provider("aruba", username="u", password="p", sandbox=True)
    assert "demows" in test.base and "demows" not in live.base


def test_explicit_base_url_beats_the_preset():
    transport = transport_for_provider(
        "aruba", username="u", password="p", base_url="https://my.gateway",
    )
    assert transport.base == "https://my.gateway"


def test_national_platforms_that_need_a_foreign_syntax_say_so():
    """KSeF and FACe do NOT take UBL. A preset that stayed silent about that
    would send a valid EN 16931 document straight into a rejection."""
    for key in ("ksef", "face"):
        assert "NON è UBL" in preset_for(key).notes


def test_chorus_pro_defaults_to_cii():
    """France's portal is the reason the CII renderer exists."""
    assert preset_for("chorus_pro").renderer == "cii"


def test_providers_for_country_puts_the_ones_that_name_it_first():
    """A platform that lists the country explicitly is a better starting point
    than a global aggregator, so the ordering carries information."""
    italian = providers_for_country("IT")
    names_it = [i for i, p in enumerate(italian) if "IT" in p.countries]
    others = [i for i, p in enumerate(italian) if "IT" not in p.countries]
    assert names_it and others
    assert max(names_it) < min(others), "explicit-country presets must come first"
    assert {"fiscozen", "aruba", "fattureincloud"} <= {p.key for p in italian}


def test_a_multi_market_platform_is_found_from_every_market_it_serves():
    """B2Brouter's primary market is Spain but it also covers Italy — looking
    up either must find it, which a single-country field could not express."""
    for code in ("ES", "IT"):
        assert "b2brouter" in {p.key for p in providers_for_country(code)}


def test_swiss_and_french_lookups_return_something_usable():
    assert any(p.key == "ebill_ch" for p in providers_for_country("CH"))
    assert any(p.key == "chorus_pro" for p in providers_for_country("FR"))


def test_unknown_provider_lists_the_known_ones():
    with pytest.raises(ProviderConfigError, match="fiscozen"):
        preset_for("not-a-platform")


# ── the registry has to stay navigable as it grows ─────────────────────────


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_every_preset_declares_a_known_kind(key):
    assert PROVIDER_PRESETS[key].kind in PROVIDER_KINDS


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_every_preset_names_at_least_one_market(key):
    preset = PROVIDER_PRESETS[key]
    assert preset.countries, key
    for code in preset.countries:
        assert code in ("EU", "global") or (len(code) == 2 and code.isupper()), code


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_every_preset_declares_what_it_can_do(key):
    assert set(PROVIDER_PRESETS[key].supports) <= {"send", "status", "receive", "notify"}
    assert "send" in PROVIDER_PRESETS[key].supports


@pytest.mark.parametrize("key", sorted(PROVIDER_PRESETS))
def test_every_preset_points_somewhere_a_human_can_read(key):
    """A preset without documentation is a dead end for whoever has to wire it."""
    preset = PROVIDER_PRESETS[key]
    assert preset.docs_url.startswith("http"), key
    assert preset.notes, key


def test_every_kind_has_members():
    """A category nothing belongs to is a category that misleads."""
    for kind in PROVIDER_KINDS:
        assert providers_of_kind(kind), kind


def test_unknown_kind_lists_the_real_ones():
    with pytest.raises(ProviderConfigError, match="access_point"):
        providers_of_kind("not-a-kind")


def test_kind_filters_within_a_country():
    portals = providers_for_country("FR", kind="national_portal")
    assert [p.key for p in portals] == ["chorus_pro"]


def test_the_markets_we_claim_to_cover_all_have_a_platform():
    """The package profiles 30 countries; a country with no route to send is a
    gap worth knowing about rather than discovering at integration time."""
    from einvoice import supported_countries

    uncovered = [c for c in supported_countries()
                 if not any("EU" in p.countries or "global" in p.countries or c in p.countries
                            for p in PROVIDER_PRESETS.values())]
    assert uncovered == [], f"no provider serves: {uncovered}"


def test_countries_with_a_national_mandate_have_a_national_route():
    """Where a country runs its own portal, a global aggregator is not enough —
    something must name that portal."""
    for code, portal in [("FR", "chorus_pro"), ("PL", "ksef"), ("RO", "efactura_anaf"),
                         ("ES", "face"), ("IT", "aruba"), ("NL", "digipoort"),
                         ("DK", "nemhandel"), ("CH", "ebill_ch")]:
        assert portal in {p.key for p in providers_for_country(code)}, code


def test_serves_understands_aggregators():
    storecove = preset_for("storecove")      # countries=("EU",)
    fiscozen = preset_for("fiscozen")        # countries=("IT",)
    assert storecove.serves("PT") and storecove.serves("IT")
    assert fiscozen.serves("IT") and not fiscozen.serves("PT")
