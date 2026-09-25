"""Il testo che FatturaPA sa portare: riscrivere la tipografia, rifiutare le lettere.

The rule under test is the asymmetry: punctuation and decoration may be
rewritten or dropped silently — they carry nothing the ASCII form does not —
while a *letter* with no Latin spelling must stop the document with a message
naming it. A question mark where a customer's name was is how the last defect
of this family went unnoticed.
"""
from __future__ import annotations

import pytest

from einvoice.errors import ValidationError
from einvoice.formats.latin import to_latin, unwritable_characters


@pytest.mark.parametrize("raw, expected", [
    ("Pizza d’autore", "Pizza d'autore"),
    ("“Menù” – serata…", '"Menù" - serata...'),
    ("Buono da 50 €", "Buono da 50 EUR"),
    ("Łódź, Kraków", "Lódz, Kraków"),
    ("Straße 5, Göteborg", "Straße 5, Göteborg"),        # Latin-1 already
    ("Ștefan Ţepeş, Dvořák, Ősz", "Stefan Tepes, Dvorák, Osz"),
    ("Ħal Qormi, Đakovo, ı", "Hal Qormi, Dakovo, i"),
    ("Pizza 🔥 piccante ️", "Pizza piccante"),
    ("a b​c\td\ne", "a bc d e"),
    ("½ litro, 2 × 3", "½ litro, 2 × 3"),
    ("ﬁletto", "filetto"),
])
def test_latin1_fields(raw, expected):
    assert to_latin(raw, field="x") == expected


@pytest.mark.parametrize("raw, expected", [
    ("m²", "m2"),
    ("½", "1/2"),
    ("Café", "Cafe"),
])
def test_ascii_fields(raw, expected):
    assert to_latin(raw, field="x", ascii_only=True) == expected


@pytest.mark.parametrize("raw, letters", [
    ("Борщ", "Борщ"),
    ("寿司 misto", "寿司"),
    ("Ελλάδα", "Ελλάδα"),
    ("ต้มยำ", "ตมยำ"),
])
def test_letters_without_a_latin_spelling_are_refused_and_named(raw, letters):
    with pytest.raises(ValidationError) as exc:
        to_latin(raw, field="Riga 3: descrizione")
    assert "Riga 3: descrizione" in str(exc.value)
    assert all(ch in str(exc.value) for ch in letters[:3])
    assert unwritable_characters(raw)


def test_length_is_measured_after_rewriting():
    """«…» becomes three characters and «€» three more: the limit is on what is
    written, not on what was typed."""
    assert to_latin("€" * 20, field="x", max_len=60) == "EUR" * 20
    with pytest.raises(ValidationError, match="al massimo 59"):
        to_latin("€" * 20, field="x", max_len=59)


def test_required_and_optional():
    with pytest.raises(ValidationError, match="vuoto"):
        to_latin("🔥", field="x")
    assert to_latin("🔥", field="x", required=False) == ""


def test_unwritable_characters_is_empty_for_writable_text():
    assert unwritable_characters("Trattoria d’Angelo — Ősz") == ""
