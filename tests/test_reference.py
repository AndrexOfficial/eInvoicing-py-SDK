"""The JSON view a hosting platform serves to its fiscal-setup screen.

This exists because two products were hand-maintaining a TypeScript copy of
the same country table — four countries against the thirty here, kept in sync
by a comment at the top of each file. What these tests protect is the property
that made copying tempting and wrong: the view must stay *complete* (every
supported country, no silent gaps) and *serialisable* (a Decimal that reaches
JSON as a float is a rate that stops being the rate).
"""
import json
from decimal import Decimal

import pytest

from einvoice import supported_countries
from einvoice.reference import (
    all_country_references,
    country_reference,
    product_categories,
    reference_metadata,
)


def test_every_supported_country_is_served():
    """A country the package supports but the UI cannot see is a silent gap."""
    served = {c["code"] for c in all_country_references()}

    assert served == set(supported_countries())


def test_an_unsupported_country_raises_rather_than_inventing_a_profile():
    """A guessed tax-id label is wrong in a way nobody notices until refusal."""
    with pytest.raises(KeyError):
        country_reference("XX")


def test_the_whole_payload_survives_json():
    payload = {
        "countries": all_country_references(),
        "categories": product_categories(),
        "meta": reference_metadata(),
    }

    assert json.loads(json.dumps(payload)) == payload


def test_no_float_ever_appears_in_it():
    """0.1 + 0.2 is the reason. Rates travel as strings, exactly as written."""
    def walk(node):
        if isinstance(node, float):
            raise AssertionError(f"float leaked into the reference data: {node}")
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)

    walk(all_country_references())


def test_rates_are_strings_that_read_back_as_the_same_decimal():
    for country in all_country_references():
        for rate in country["rates"]:
            assert isinstance(rate["rate"], str)
            Decimal(rate["rate"])          # never raises
    assert Decimal(country_reference("CH")["rates"][0]["rate"]) == Decimal("8.1")


def test_it_carries_what_a_setup_screen_actually_asks_for():
    it = country_reference("IT")

    assert it["tax_id_label"] == "P.IVA"          # the field label
    assert it["tax_id_pattern"]                    # and its shape
    assert it["default_standard"] == "fatturapa"   # which document to produce
    assert it["regime"]["network"] == "sdi"        # and where it goes
    assert it["rules"]["retention_years"] == 10
    assert it["rules"]["simplified_invoice_threshold"] == "400"


def test_a_country_with_no_vat_says_so_instead_of_showing_zero():
    """The US has no federal VAT. An empty rate list plus an explanation beats
    a fabricated 0%, which would make every real sales tax look anomalous."""
    us = country_reference("US")

    assert us["rates"] == []
    assert us["no_national_vat"], "the reason must travel with the emptiness"
    assert country_reference("IT")["no_national_vat"] is None


def test_the_category_vocabulary_marks_what_is_exempt_rather_than_zero_rated():
    cats = {c["value"]: c["commonly_exempt"] for c in product_categories()}

    assert cats["medical_care"] is True       # exempt: no rate at all
    assert cats["books"] is False             # rated, just reduced


def test_the_data_says_how_old_it_is():
    meta = reference_metadata()

    assert meta["rates_verified_as_of"].count("-") == 2       # ISO
    assert meta["mandates_verified_as_of"].count("-") == 2


def test_every_country_answers_the_same_questions():
    """A UI iterates these; a missing key there is a blank field in production."""
    expected = set(country_reference("IT"))

    for country in all_country_references():
        assert set(country) == expected, f"{country['code']} has a different shape"
        assert country["name"] and country["tax_id_label"]


def test_no_country_is_left_with_a_placeholder_identifier_label():
    """"VAT" is not a label, it is the absence of one.

    A German operator looking for where to type their USt-IdNr. should not
    have to work out that the field marked "VAT" is the one. The products
    embedding this package had each hand-written their own local labels for
    four countries precisely because the package gave them nothing better.
    """
    generic = [c["code"] for c in all_country_references() if c["tax_id_label"] in ("VAT", "Tax ID", "")]

    assert not generic, f"these countries still have a placeholder label: {generic}"


def test_the_labels_are_the_local_vocabulary_not_a_translation_of_ours():
    labels = {c["code"]: c["tax_id_label"] for c in all_country_references()}

    assert labels["DE"] == "USt-IdNr."
    assert labels["IT"] == "P.IVA"
    assert labels["PL"] == "NIP"
    assert labels["US"] == "EIN"          # not VAT at all — there is none
