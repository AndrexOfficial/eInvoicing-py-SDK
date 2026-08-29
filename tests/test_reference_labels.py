"""The country reference must hand out words, not identifiers.

Both embedding products were printing this package's vocabulary raw: "22% ·
super_reduced" next to labels translated into fourteen languages, and
"mandatory" under a heading that said *Obbligo B2B*. Each product then grew its
own translation table — which is how two Polish words for the reduced rate get
into two codebases that are supposed to agree.

So the words live here, beside the data they describe, and travel with it.

The identifier stays: ``kind`` is what code branches on, ``kind_label`` is what
a person reads. Replacing the first with the second would have been the easy
change and the wrong one.
"""
from __future__ import annotations

import pytest

from einvoice.i18n import LOCALES, translate
from einvoice.rates import RateKind
from einvoice.reference import all_country_references, country_reference

MANDATES = ("mandatory", "voluntary", "phased")


def test_the_identifier_survives_next_to_the_label():
    it = country_reference("IT", "it")
    assert it["regime"]["b2b"] == "mandatory"
    assert it["regime"]["b2b_label"] == "obbligatoria"


@pytest.mark.parametrize("locale", LOCALES)
def test_every_rate_kind_has_a_label_in_every_language(locale: str):
    """A kind the catalog has never heard of would come back as ``None`` — and
    a screen showing a blank where a rate type belongs is a bug report."""
    for kind in RateKind:
        etichetta = translate(f"rate_kind.{kind.value}", locale)
        assert etichetta != f"rate_kind.{kind.value}", f"{kind.value} non tradotto in {locale}"
        assert etichetta.strip()


@pytest.mark.parametrize("locale", LOCALES)
def test_every_mandate_the_data_declares_has_a_label(locale: str):
    """The set is taken from the country table, not from a list kept by hand:
    a profile that starts declaring something new fails here."""
    dichiarati = set()
    for paese in all_country_references():
        regime = paese["regime"]
        dichiarati.update(v for v in (regime["b2b"], regime["b2g"]) if v)

    assert dichiarati <= set(MANDATES), f"mandati nuovi nei dati: {sorted(dichiarati - set(MANDATES))}"
    for mandato in dichiarati:
        etichetta = translate(f"mandate.{mandato}", locale)
        assert etichetta != f"mandate.{mandato}", f"{mandato} non tradotto in {locale}"
        assert etichetta.strip()


def test_no_country_comes_back_with_a_missing_label():
    """Ogni paese supportato, non solo l'Italia."""
    for paese in all_country_references("fr"):
        for aliquota in paese["rates"]:
            assert aliquota["kind_label"], f"{paese['code']}: {aliquota['kind']} senza etichetta"
        for campo in ("b2b", "b2g"):
            if paese["regime"][campo]:
                assert paese["regime"][f"{campo}_label"], f"{paese['code']}: {campo} senza etichetta"


def test_an_unknown_locale_falls_back_instead_of_failing():
    """Un prodotto che passa 'klingon' deve vedere l'inglese, non un errore."""
    assert country_reference("IT", "klingon")["regime"]["b2b_label"] == "mandatory"


def test_omitting_the_locale_still_works():
    """La firma è retrocompatibile: chi chiamava senza lingua continua a farlo."""
    assert country_reference("IT")["regime"]["b2b_label"] == "mandatory"
    assert len(all_country_references()) >= 30


def test_the_label_is_none_when_the_value_is_absent():
    """Distinguere «non tradotto» da «tradotto» richiede che il vuoto sia vuoto."""
    from einvoice.reference import _label

    assert _label("mandate", None, "it") is None
    assert _label("mandate", "", "it") is None
    assert _label("mandate", "inesistente", "it") is None
