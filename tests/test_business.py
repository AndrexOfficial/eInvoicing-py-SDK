"""Business types resolve *through* the country table; they never restate it.

The distinction this module exists to keep: what you **sell** decides the rate
and lives in `einvoice.rates`, dated and partial on purpose; what you **are**
decides the scheme (margin, flat-rate, exemption) and lives in
`einvoice.business`. A second per-country table of business rules would
contradict the first one the day either moved, so there isn't one — and these
tests are what stops one appearing.
"""
from __future__ import annotations

import pytest

from einvoice.business import (
    BusinessType,
    VatScheme,
    business_profile,
    business_schemes,
    business_supplies,
    business_types,
)
from einvoice.i18n import LOCALES, translate
from einvoice.rates import COMMONLY_EXEMPT, ProductCategory, rate_for, standard_rate

# ── the vocabulary is complete and translated ────────────────────────────


@pytest.mark.parametrize("locale", LOCALES)
def test_every_business_type_has_a_name(locale: str):
    for tipo in BusinessType:
        chiave = f"business_type.{tipo.value}"
        assert translate(chiave, locale) != chiave, f"{tipo.value} non tradotto in {locale}"


@pytest.mark.parametrize("locale", LOCALES)
def test_every_scheme_has_a_name(locale: str):
    for schema in VatScheme:
        chiave = f"vat_scheme.{schema.value}"
        assert translate(chiave, locale) != chiave, f"{schema.value} non tradotto in {locale}"


def test_every_business_type_declares_what_it_supplies():
    """Anche la tupla vuota è una dichiarazione: «niente in Allegato III»."""
    for tipo in BusinessType:
        assert isinstance(business_supplies(tipo), tuple)


def test_supplied_categories_are_real_categories():
    for tipo in BusinessType:
        for categoria in business_supplies(tipo):
            assert isinstance(categoria, ProductCategory)


# ── the rate is never restated, only resolved ────────────────────────────


def test_the_rate_comes_from_the_country_table_and_nowhere_else():
    """Se un giorno qualcuno scrivesse le aliquote dentro business.py, questo
    test lo vedrebbe: il profilo deve coincidere con la tabella per paese."""
    for tipo in (BusinessType.RESTAURANT, BusinessType.HOTEL, BusinessType.BOOKSHOP):
        for paese in ("IT", "DE", "FR", "ES"):
            profilo = business_profile(tipo, paese)
            for voce in profilo["supplies"]:
                categoria = ProductCategory(voce["category"])
                if voce["exempt"]:
                    assert voce["rate"] is None
                    continue
                atteso = rate_for(paese, categoria) or standard_rate(paese)
                assert voce["rate"] == str(atteso), f"{tipo.value}/{paese}/{categoria.value}"


def test_a_category_the_country_does_not_map_falls_to_the_standard_rate():
    """L'Italia non mette lo sport fra le ridotte: una palestra sta al 22%.
    Non è una regola scritta qui — è quello che dice la tabella."""
    palestra = business_profile(BusinessType.GYM, "IT")
    assert palestra["supplies"][0]["rate"] == str(standard_rate("IT"))


def test_an_exempt_activity_has_no_rate_and_says_why():
    medico = business_profile(BusinessType.MEDICAL_PRACTICE, "IT")
    cura = medico["supplies"][0]
    assert cura["exempt"] is True
    assert cura["rate"] is None, "esente non è zero: il diritto alla detrazione si perde"
    assert VatScheme.EXEMPT_ACTIVITY.value in [s["value"] for s in medico["schemes"]]


def test_a_country_without_a_national_vat_answers_none_not_zero():
    """Negli Stati Uniti l'imposta la determina un motore che il pacchetto non
    modella: rispondere «0%» avrebbe fatto sembrare normale ogni sales tax."""
    profilo = business_profile(BusinessType.RETAIL_GENERAL, "US")
    assert profilo["standard_rate"] is None
    assert all(v["rate"] is None for v in profilo["supplies"])


# ── the schemes that attach to the activity ──────────────────────────────


@pytest.mark.parametrize(
    ("tipo", "atteso"),
    [
        (BusinessType.TRAVEL_AGENCY, VatScheme.TRAVEL_MARGIN),
        (BusinessType.FARM, VatScheme.FARMER_FLAT_RATE),
        (BusinessType.SECOND_HAND_DEALER, VatScheme.SECOND_HAND_MARGIN),
        (BusinessType.FINANCIAL_SERVICES, VatScheme.EXEMPT_ACTIVITY),
    ],
)
def test_the_activity_carries_its_special_scheme(tipo: BusinessType, atteso: VatScheme):
    assert atteso in business_schemes(tipo)


def test_the_small_enterprise_scheme_is_offered_to_everyone():
    """Sotto soglia riguarda chiunque: ometterlo su un'attività piccola
    sarebbe l'omissione che costa."""
    for tipo in BusinessType:
        assert VatScheme.SMALL_ENTERPRISE in business_schemes(tipo)


def test_every_scheme_names_its_articles():
    """I numeri d'articolo sono l'unico appiglio stabile: soglie e opzioni si
    muovono, la direttiva no. Servono a chi deve chiedere al commercialista."""
    profilo = business_profile(BusinessType.TRAVEL_AGENCY, "IT")
    articoli = {s["value"]: s["articles"] for s in profilo["schemes"]}
    assert articoli[VatScheme.TRAVEL_MARGIN.value] == "306-310"
    assert articoli[VatScheme.SMALL_ENTERPRISE.value] == "282-292d"


# ── the two cases that a hand-written table gets wrong ───────────────────


def test_a_driving_school_is_not_exempt_education():
    """Corte di giustizia UE, C-449/17 (14 marzo 2019): la scuola guida non è
    «istruzione scolastica» esente. Una tabella scritta a occhio la mette
    fra le esenti, perché «scuola» è nel nome."""
    autoscuola = business_profile(BusinessType.DRIVING_SCHOOL, "IT")
    assert autoscuola["supplies"] == []
    assert autoscuola["standard_rate"] == str(standard_rate("IT"))
    assert VatScheme.EXEMPT_ACTIVITY.value not in [s["value"] for s in autoscuola["schemes"]]


def test_a_vet_is_not_covered_by_the_medical_exemption():
    """L'esenzione dell'art. 132(1)(c) è per le cure alle persone."""
    assert ProductCategory.MEDICAL_CARE in COMMONLY_EXEMPT
    assert business_supplies(BusinessType.VETERINARY) == ()
    veterinario = business_profile(BusinessType.VETERINARY, "IT")
    assert VatScheme.EXEMPT_ACTIVITY.value not in [s["value"] for s in veterinario["schemes"]]


# ── the picker ───────────────────────────────────────────────────────────


def test_the_picker_is_complete_and_translated():
    voci = business_types("it")
    assert len(voci) == len(list(BusinessType))
    assert all(v["label"] and v["label"].strip() for v in voci)
    ristorante = next(v for v in voci if v["value"] == "restaurant")
    assert ristorante["label"] == "ristorante"
    assert ristorante["supplies"][0] == "restaurant"


def test_an_unknown_business_type_raises_instead_of_guessing():
    with pytest.raises(ValueError):
        business_profile("pizzeria_del_futuro", "IT")


def test_omitting_the_locale_still_works():
    profilo = business_profile(BusinessType.RESTAURANT, "IT")
    assert profilo["business_label"] == "restaurant"
