"""VAT rates by product category, and the non-rate fiscal rules.

Most of these guard *consistency and honesty* rather than individual numbers:
a rate table is data that goes stale, and what a test can usefully pin is that
the structure holds, that the package never contradicts itself, and that where
it does not know something it says so instead of guessing.
"""
from decimal import Decimal

import pytest

from einvoice import (
    ALWAYS_STANDARD_RATED,
    COMMONLY_EXEMPT,
    COUNTRY_RATES,
    EU_COUNTRIES,
    EU_OSS_THRESHOLD,
    NO_NATIONAL_VAT,
    RATES_VERIFIED_AS_OF,
    ProductCategory,
    RateKind,
    categories_for,
    profile_for,
    rate_for,
    rates_for,
    standard_rate,
    supported_countries,
)

# ── structure ──────────────────────────────────────────────────────────────


def test_every_supported_country_has_a_rate_table_or_says_why_not():
    for code in supported_countries():
        if not rates_for(code):
            assert code in NO_NATIONAL_VAT, (
                f"{code} has no rates and no explanation of why"
            )
            assert NO_NATIONAL_VAT[code], f"{code}: empty explanation"


@pytest.mark.parametrize("code", sorted(c for c in COUNTRY_RATES if COUNTRY_RATES[c]))
def test_every_country_has_exactly_one_standard_rate(code):
    standard = [r for r in rates_for(code) if r.kind is RateKind.STANDARD]
    assert len(standard) == 1, f"{code}: {len(standard)} standard rates"


@pytest.mark.parametrize("code", sorted(c for c in COUNTRY_RATES if COUNTRY_RATES[c]))
def test_the_standard_rate_is_the_highest(code):
    """If a "reduced" rate exceeded the standard one, something is mislabelled."""
    entries = rates_for(code)
    standard = next(r for r in entries if r.kind is RateKind.STANDARD)
    assert all(r.rate <= standard.rate for r in entries), code


@pytest.mark.parametrize("code", sorted(c for c in COUNTRY_RATES if COUNTRY_RATES[c]))
def test_rates_are_listed_highest_first(code):
    rates = [r.rate for r in rates_for(code)]
    assert rates == sorted(rates, reverse=True), code


@pytest.mark.parametrize("code", sorted(c for c in COUNTRY_RATES if COUNTRY_RATES[c]))
def test_no_country_lists_the_same_rate_twice(code):
    rates = [r.rate for r in rates_for(code)]
    assert len(rates) == len(set(rates)), f"{code}: duplicate rate"


@pytest.mark.parametrize("code", sorted(c for c in COUNTRY_RATES if COUNTRY_RATES[c]))
def test_a_category_maps_to_one_rate_per_country(code):
    """Two rates claiming the same category would make `rate_for` order-dependent."""
    seen: dict[ProductCategory, Decimal] = {}
    for entry in rates_for(code):
        for category in entry.categories:
            assert category not in seen, (
                f"{code}: {category.value} claimed by both {seen[category]}% "
                f"and {entry.rate}%"
            )
            seen[category] = entry.rate


@pytest.mark.parametrize("code", sorted(c for c in COUNTRY_RATES if COUNTRY_RATES[c]))
def test_every_rate_is_a_plausible_percentage(code):
    for entry in rates_for(code):
        assert Decimal("0") <= entry.rate <= Decimal("30"), f"{code}: {entry.rate}"


def test_the_tables_are_dated():
    """Tax rates go stale; a reader must be able to see how old these are."""
    assert RATES_VERIFIED_AS_OF.year >= 2026


# ── the two tables must agree ──────────────────────────────────────────────


@pytest.mark.parametrize("code", sorted(supported_countries()))
def test_the_profile_rate_list_matches_the_category_table(code):
    """`CountryProfile.vat_rates` is derived from `COUNTRY_RATES` precisely so
    the two cannot drift. This is what would notice if that stopped being true."""
    profile = profile_for(code)
    derived = tuple(str(entry.rate) for entry in rates_for(code))
    assert profile.vat_rates == derived


@pytest.mark.parametrize("code", sorted(supported_countries()))
def test_every_mapped_rate_is_accepted_by_the_plausibility_check(code):
    """A rate the package itself publishes must not then be flagged as unusual."""
    profile = profile_for(code)
    for entry in rates_for(code):
        assert profile.is_known_vat_rate(entry.rate), f"{code}: {entry.rate}"


# ── lookups ────────────────────────────────────────────────────────────────


def test_standard_goods_resolves_to_the_standard_rate():
    assert rate_for("IT", ProductCategory.STANDARD_GOODS) == Decimal("22")
    assert rate_for("DE", ProductCategory.STANDARD_GOODS) == Decimal("19")
    assert rate_for("CH", ProductCategory.STANDARD_GOODS) == Decimal("8.1")


@pytest.mark.parametrize(("code", "category", "expected"), [
    ("IT", ProductCategory.BOOKS, "4"),
    ("DE", ProductCategory.BOOKS, "7"),
    ("FR", ProductCategory.PHARMACEUTICALS, "2.1"),
    ("CH", ProductCategory.ACCOMMODATION, "3.8"),
    ("LU", ProductCategory.FOODSTUFFS, "3"),
    ("HU", ProductCategory.PHARMACEUTICALS, "5"),
])
def test_known_category_rates(code, category, expected):
    assert rate_for(code, category) == Decimal(expected)


def test_zero_rating_is_a_rate_not_an_absence():
    """The UK and Ireland zero-rate a wide list. Zero-rated is taxable at 0% and
    preserves input-VAT deduction — reporting it as "unknown" would erase a
    distinction the seller cares about."""
    assert rate_for("GB", ProductCategory.CHILDRENS_CLOTHING) == Decimal("0")
    assert rate_for("GB", ProductCategory.FOODSTUFFS) == Decimal("0")
    assert rate_for("IE", ProductCategory.BOOKS) == Decimal("0")


def test_an_unmapped_category_returns_none_rather_than_a_guess():
    """The honest answer to "what does Bulgaria charge for haircuts?" is that
    this package does not know."""
    assert rate_for("BG", ProductCategory.HAIRDRESSING) is None
    assert rate_for("IT", ProductCategory.REPAIR_SERVICES) is None


def test_a_country_with_no_national_vat_returns_none_for_everything():
    assert standard_rate("US") is None
    assert rate_for("US", ProductCategory.BOOKS) is None
    assert "US" in NO_NATIONAL_VAT


def test_an_unknown_country_is_empty_not_an_error():
    assert rates_for("ZZ") == ()
    assert standard_rate("ZZ") is None
    assert rate_for("ZZ", ProductCategory.BOOKS) is None


def test_categories_for_lists_what_is_actually_mapped():
    italian = categories_for("IT")
    assert italian[ProductCategory.BOOKS] == Decimal("4")
    assert ProductCategory.REPAIR_SERVICES not in italian


def test_commonly_exempt_is_documented_as_distinct_from_zero_rated():
    """Exempt removes the right to deduct input VAT; zero-rated does not. Both
    show 0 on the invoice, which is exactly why the distinction needs naming."""
    assert ProductCategory.FINANCIAL_SERVICES in COMMONLY_EXEMPT
    assert ProductCategory.INSURANCE in COMMONLY_EXEMPT
    assert ProductCategory.FOODSTUFFS not in COMMONLY_EXEMPT


# ── profile-level access ───────────────────────────────────────────────────


def test_the_profile_exposes_the_same_answers():
    italy = profile_for("IT")
    assert italy.rate_for(ProductCategory.BOOKS) == Decimal("4")
    assert italy.rate_categories()[ProductCategory.ACCOMMODATION] == Decimal("10")
    assert len(italy.rates) == len(COUNTRY_RATES["IT"])


# ── fiscal rules ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("code", sorted(supported_countries()))
def test_every_country_has_fiscal_rules(code):
    rules = profile_for(code).fiscal_rules
    assert rules is not None
    if rules.retention_years is not None:
        assert 3 <= rules.retention_years <= 15, f"{code}: {rules.retention_years}"


@pytest.mark.parametrize("code", sorted(supported_countries()))
def test_a_stated_threshold_is_a_positive_amount(code):
    threshold = profile_for(code).fiscal_rules.simplified_invoice_threshold
    assert threshold is None or threshold > 0, code


def test_the_rules_carry_what_an_integrator_actually_asks():
    italy = profile_for("IT").fiscal_rules
    assert italy.retention_years == 10
    assert italy.simplified_invoice_threshold == Decimal("400")
    assert italy.issue_deadline_days == 12
    assert italy.domestic_reverse_charge is True
    assert italy.notes


def test_the_oss_threshold_is_eu_wide_not_per_country():
    """A recurring misunderstanding: the 10 000 EUR ceiling is a *combined*
    turnover across all member states, not one per country."""
    assert Decimal("10000") == EU_OSS_THRESHOLD
    assert all(profile_for(c).eu_member for c in EU_COUNTRIES)


def test_a_country_without_a_retention_rule_says_none_rather_than_zero():
    assert profile_for("US").fiscal_rules.retention_years is None
    assert profile_for("US").fiscal_rules.notes


# ── the advisory that uses all of this ─────────────────────────────────────


def _invoice(category, rate, country="IT"):
    from datetime import date

    from einvoice import Address, Invoice, LineItem, Party

    vat = {"IT": "07643520567", "DE": "136695976"}[country]
    return Invoice(
        number="R-1", date=date(2026, 8, 24),
        seller=Party(name="S", vat_number=vat, country_code=country,
                     address=Address("Via Roma 1", "20100", "Milano", "MI",
                                     country)),
        buyer=Party(name="B", vat_number=vat, country_code=country,
                    sdi_code="ABCDEFG",
                    address=Address("Via Verdi 9", "00100", "Roma", "RM", country)),
        lines=[LineItem("X", Decimal("1"), Decimal("100"), Decimal(rate),
                        category=category)],
    )


def test_a_line_at_the_wrong_rate_for_its_category_is_flagged():
    flagged = _invoice(ProductCategory.BOOKS, "22")
    assert "rate_category" in {a.code for a in flagged.check()}


def test_a_line_at_the_right_rate_says_nothing():
    assert _invoice(ProductCategory.BOOKS, "4").check() == []


def test_an_unmapped_category_is_silence_not_a_complaint():
    assert _invoice(ProductCategory.REPAIR_SERVICES, "22").check() == []


def test_a_line_with_no_category_is_never_flagged():
    """The field is optional; not using it must cost nothing."""
    assert _invoice(None, "22").check() == []


def test_the_advisory_names_both_rates():
    message = next(a.message for a in _invoice(ProductCategory.BOOKS, "22").check()
                   if a.code == "rate_category")
    assert "22" in message and "4" in message and "books" in message


def test_the_category_is_never_rendered_into_any_format():
    """No e-invoicing standard carries it, so it must not leak into the XML."""
    from einvoice.formats import get_renderer

    invoice = _invoice(ProductCategory.BOOKS, "4")
    for standard in ("fatturapa", "ubl", "cii"):
        assert b"books" not in get_renderer(standard).render(invoice).content


# ── the vocabulary must stay answerable and self-consistent ────────────────


def test_no_category_is_dead_vocabulary():
    """A category nobody can ever get an answer for misleads: it looks like
    coverage and behaves like a gap. Every one must be mapped somewhere, or be
    always-standard, or be commonly exempt.
    """
    mapped = {c for entries in COUNTRY_RATES.values()
              for entry in entries for c in entry.categories}
    answerable = mapped | ALWAYS_STANDARD_RATED | COMMONLY_EXEMPT | {
        ProductCategory.STANDARD_GOODS}
    dead = sorted(c.value for c in ProductCategory if c not in answerable)
    assert dead == [], f"categories nothing can answer: {dead}"


def test_an_exempt_category_is_never_also_given_a_rate():
    """The package contradicted itself here: COMMONLY_EXEMPT listed medical care
    while the Italian and Maltese tables gave it a reduced rate. Medical care by
    a registered practitioner is exempt EU-wide; what those bands cover is
    socio-sanitary services, which is a different thing.
    """
    contradictions = [
        (category.value, code)
        for category in COMMONLY_EXEMPT
        for code in supported_countries()
        if rate_for(code, category) is not None
    ]
    assert contradictions == [], f"exempt but rated: {contradictions}"


@pytest.mark.parametrize("category", sorted(ALWAYS_STANDARD_RATED, key=lambda c: c.value))
@pytest.mark.parametrize("code", ["IT", "DE", "FR", "GB", "CH"])
def test_always_standard_categories_resolve_to_the_standard_rate(category, code):
    """"Is alcohol reduced-rated along with the rest of the food?" is a question
    people get wrong, and "no, standard" beats silence."""
    assert rate_for(code, category) == standard_rate(code)


def test_a_category_is_never_both_always_standard_and_exempt():
    assert not (ALWAYS_STANDARD_RATED & COMMONLY_EXEMPT)


def test_country_codes_are_case_insensitive():
    assert rate_for("it", ProductCategory.BOOKS) == rate_for("IT", ProductCategory.BOOKS)
    assert standard_rate("de") == standard_rate("DE")
