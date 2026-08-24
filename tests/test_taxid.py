"""Tax-id validation — the check digits, and the honesty about coverage.

The numbers below are real, published identifiers of well-known organisations.
That matters more than it looks: an algorithm that rejects a genuine VAT number
is far worse than one that accepts a typo, because it blocks invoices to real
customers. Every checksum shipped is pinned here against a number known to be
in use, and four of these algorithms were wrong on the first attempt — this
file is what caught them.
"""
import pytest

from einvoice.countries import COUNTRY_PROFILES, profile_for
from einvoice.taxid import (
    CHECKSUM_COUNTRIES,
    normalize_tax_id,
    validate_tax_id_full,
    validation_level,
)

# country → a real, published identifier
REAL_NUMBERS = {
    "AT": "ATU13585627",
    "BE": "BE0428759497",
    "CH": "CHE-116.281.710 MWST",
    "DE": "DE136695976",
    "DK": "DK13585628",
    "EE": "EE100931558",
    "FI": "FI20774740",
    "FR": "FR40303265045",
    "GB": "GB980780684",
    "GR": "EL094014249",
    "HR": "HR69435151530",
    "HU": "HU12892312",
    "IE": "IE6388047V",
    "IT": "IT07643520567",
    "LU": "LU15027442",
    "PL": "PL5260001246",
    "PT": "PT502011378",
    "SE": "SE556012579001",
    "SI": "SI50223054",
    "SK": "SK2020317068",
}


@pytest.mark.parametrize(("country", "number"), sorted(REAL_NUMBERS.items()))
def test_real_numbers_are_accepted(country, number):
    """The regression that matters: never reject a number actually in use."""
    assert validate_tax_id_full(country, number, pattern=None), f"{country}:{number}"


@pytest.mark.parametrize(("country", "number"), sorted(REAL_NUMBERS.items()))
def test_a_single_digit_typo_is_caught(country, number):
    """A one-digit slip must fail — otherwise the checksum earns nothing.

    The *first* digit is bumped rather than the last. Corrupting the last one
    looks more natural but is wrong for Sweden, where the trailing "01" is a
    group suffix and the check digit sits two places earlier — the first draft
    of this test asserted otherwise and failed, correctly.
    """
    if country not in CHECKSUM_COUNTRIES:
        pytest.skip(f"{country} is structural-only by design")
    normalized = normalize_tax_id(country, number)
    index = next(i for i, ch in enumerate(normalized) if ch.isdigit())
    bumped = str((int(normalized[index]) + 1) % 10)
    corrupted = normalized[:index] + bumped + normalized[index + 1:]

    assert not validate_tax_id_full(country, corrupted, pattern=None), (
        f"{country}: {corrupted} should fail validation"
    )


def test_every_checksum_country_reports_itself_as_such():
    for country in CHECKSUM_COUNTRIES:
        assert validation_level(country) == "checksum"


def test_structural_countries_say_so_rather_than_implying_a_checksum():
    """Claiming a check we do not perform would be the worst outcome here."""
    for country in ("ES", "NL", "CZ", "BG", "CY", "LT", "LV", "MT", "RO", "US"):
        assert validation_level(country) == "structural"


def test_every_profiled_country_validates_its_own_real_number_or_is_structural():
    """No profile may be strict in a way nothing exercises."""
    for code, profile in COUNTRY_PROFILES.items():
        if code in REAL_NUMBERS:
            assert profile.validate_tax_id(REAL_NUMBERS[code]), code
        else:
            assert profile.tax_id_validation == "structural", (
                f"{code} claims a checksum but has no pinned real number"
            )


# ── normalization ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(("country", "printed", "bare"), [
    ("CH", "CHE-116.281.710 MWST", "CHE116281710"),
    ("CH", "CHE-116.281.710 TVA", "CHE116281710"),
    ("CH", "CHE116281710", "CHE116281710"),
    ("IT", "IT 0764 3520 567", "07643520567"),
    ("IT", "07643520567", "07643520567"),
    ("GR", "EL094014249", "094014249"),
    ("GR", "GR094014249", "094014249"),
    ("FR", "FR 40 303 265 045", "40303265045"),
    ("US", "12-3456789", "123456789"),
])
def test_printed_forms_normalize(country, printed, bare):
    assert normalize_tax_id(country, printed) == bare


def test_swiss_prefix_is_not_mistaken_for_the_country_code():
    """Stripping "CH" from "CHE116281710" would leave "E116281710"."""
    assert normalize_tax_id("CH", "CHE116281710") == "CHE116281710"


def test_greece_accepts_both_its_codes():
    """ISO says GR, VIES says EL, and both turn up in supplier data."""
    assert validate_tax_id_full("GR", "EL094014249", pattern=None)
    assert validate_tax_id_full("GR", "GR094014249", pattern=None)


def test_empty_is_never_valid():
    for value in (None, "", "   "):
        assert not validate_tax_id_full("IT", value, pattern=None)


# ── shape-valid but arithmetically impossible ──────────────────────────────


@pytest.mark.parametrize(("country", "number"), [
    ("IT", "01234567890"),      # 11 digits, fails Luhn
    ("DE", "136695977"),        # one off the real one
    ("CH", "CHE-116.281.711"),  # one off the real one
    ("BE", "0428759498"),
    ("AT", "ATU13585628"),
])
def test_right_shape_wrong_arithmetic_is_rejected(country, number):
    """Exactly the class a regex cannot see, and the reason this module exists."""
    assert not validate_tax_id_full(country, number, pattern=None)


def test_structural_fallback_still_applies_a_pattern():
    profile = profile_for("ES")
    assert profile.validate_tax_id("A28015865")
    assert not profile.validate_tax_id("nonsense")


def test_us_ein_rejects_an_unissued_campus_prefix():
    """The EIN has no check digit, so the prefix is the only offline signal."""
    assert validate_tax_id_full("US", "12-3456789", pattern=None)
    assert not validate_tax_id_full("US", "07-1234567", pattern=None)
    assert not validate_tax_id_full("US", "00-1234567", pattern=None)
