"""The translation catalog — completeness, and the placeholders inside it.

Two failure modes are worth machinery here, because neither is visible when
reading the file.

*A missing language.* Nobody notices: :func:`translate` falls back to English
and the screen looks fine to whoever is testing it, which is usually not the
person who needed Bulgarian.

*A lost placeholder.* A translator (or a hurried edit) drops ``{base_url}`` and
the sentence still reads perfectly — it just no longer tells the operator the
host. That is the whole content of the step, silently gone.
"""
import re

import pytest

from einvoice import supported_countries
from einvoice.i18n import (
    _CATALOG,
    DEFAULT_LOCALE,
    LOCALES,
    LOCALES_BY_COUNTRY,
    available_locales,
    catalog_for,
    locale_for_country,
    normalize_locale,
    translate,
    translation_keys,
)

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def test_locales_are_sorted_and_unique():
    assert list(LOCALES) == sorted(set(LOCALES))
    assert DEFAULT_LOCALE in LOCALES


@pytest.mark.parametrize("key", translation_keys())
def test_every_key_exists_in_every_language(key):
    """English fallback hides a gap; this is what makes the gap visible."""
    missing = sorted(set(LOCALES) - set(_CATALOG[key]))

    assert not missing, f"{key} missing: {', '.join(missing)}"


@pytest.mark.parametrize("key", translation_keys())
def test_every_translation_carries_the_same_placeholders(key):
    """A dropped ``{base_url}`` reads fine and says nothing."""
    expected = set(_PLACEHOLDER.findall(_CATALOG[key][DEFAULT_LOCALE]))
    for locale, text in _CATALOG[key].items():
        assert set(_PLACEHOLDER.findall(text)) == expected, f"{key}/{locale}"


@pytest.mark.parametrize("key", translation_keys())
def test_no_translation_is_blank(key):
    for locale, text in _CATALOG[key].items():
        assert text.strip(), f"{key}/{locale} is empty"


def test_every_supported_country_has_a_default_language():
    """A country whose rules we state, in a language we cannot render, is
    half-supported — and the picker has nothing sensible to preselect."""
    assert set(LOCALES_BY_COUNTRY) == set(supported_countries())
    for code, langs in LOCALES_BY_COUNTRY.items():
        assert langs, code
        assert set(langs) <= set(LOCALES), code


@pytest.mark.parametrize("tag,expected", [
    ("pt-BR", "pt"), ("zh_Hans", "zh"), ("EN-gb", "en"), ("it", "it"),
    ("", DEFAULT_LOCALE), (None, DEFAULT_LOCALE), ("klingon", DEFAULT_LOCALE),
    ("  DE  ", "de"),
])
def test_normalize_locale_is_forgiving(tag, expected):
    """It sits behind a query parameter: a typo should degrade, not 400."""
    assert normalize_locale(tag) == expected


def test_unknown_key_returns_itself():
    """A visible ``step.nope`` is a bug report; an empty string is a mystery."""
    assert translate("step.nope", "it") == "step.nope"


def test_missing_language_falls_back_to_english():
    assert translate("label.setup", "xx") == translate("label.setup", "en")


def test_placeholder_mismatch_does_not_raise():
    """A settings page must not 500 because a parameter was not supplied."""
    text = translate("step.known_base_url", "en")

    assert "{base_url}" in text
    assert translate("step.known_base_url", "en", wrong="x").endswith("host.")


def test_catalog_for_is_complete_and_flat():
    catalog = catalog_for("sv")

    assert set(catalog) == set(translation_keys())
    assert all(isinstance(v, str) and v for v in catalog.values())


def test_locale_for_country_prefers_the_first_official_language():
    assert locale_for_country("BE") == "nl"
    assert locale_for_country("CH") == "de"
    assert locale_for_country("ZZ") == DEFAULT_LOCALE


def test_available_locales_is_a_copy():
    """Handing out the module tuple invites a caller to mutate the catalog."""
    first = available_locales()
    first.append("xx")

    assert "xx" not in available_locales()


def test_the_language_can_be_passed_by_keyword():
    """It could not, and that was the worst failure this module can have: the
    ``/`` marker sent ``locale="it"`` into ``**params`` and the call answered in
    English, silently, with no error anywhere."""
    assert translate("label.setup", locale="it") == translate("label.setup", "it") == "Configurazione"


@pytest.mark.parametrize("key", translation_keys())
def test_no_string_formats_the_arguments_of_translate_itself(key):
    """``key`` is still positional-only, and ``locale`` is now a real parameter.
    A catalog string carrying ``{key}`` or ``{locale}`` would collide with them
    and reintroduce the bug from the other side."""
    for text in _CATALOG[key].values():
        assert not {"key", "locale"} & set(_PLACEHOLDER.findall(text)), key
