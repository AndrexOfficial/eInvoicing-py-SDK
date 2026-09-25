"""Il testo che FatturaPA sa portare.

Every free-text field of FatturaPA is typed ``String…LatinType`` — Basic Latin
plus Latin-1 Supplement, nothing else — and a few (``Numero``, ``UnitaMisura``,
``CodiceTipo``…) accept Basic Latin only. The renderer used to copy text across
untouched, so a dish called «Pizza d’autore» (a typographic apostrophe, U+2019,
which is *not* Latin-1) produced a file SdI rejects as ``00200 — file non
conforme al formato``. Nobody types U+2019 on purpose: keyboards, word
processors and phone autocorrect put it there, which is why it is the common
case and not an exotic one.

The rule this module applies:

* **Typography is rewritten**, because it carries no meaning the ASCII form
  does not: curly quotes, dashes, the ellipsis, non-breaking and zero-width
  spaces, the euro sign (``EUR``).
* **Letters are folded when they can be**: ``ő ł ș č ı`` become ``o l s c i``.
  Every Latin-script language of the EU survives this readable.
* **Decoration is dropped**: emoji and pictographs, variation selectors,
  stray combining marks. «Pizza 🔥» becomes «Pizza».
* **Letters that cannot be written in Latin are refused**, never replaced.
  A customer called «Борщ» or a dish called «寿司» has no Latin-1 spelling this
  module can invent, and a question mark where a name was is how the previous
  defect of this kind went unnoticed for months. The error names the field and
  the characters, so the operator knows what to rewrite.
"""
from __future__ import annotations

import unicodedata

from ..errors import ValidationError

__all__ = ["to_latin", "unwritable_characters"]

#: Punctuation and symbols with an obvious Latin-1/ASCII spelling.
_REWRITE: dict[str, str] = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "ʼ": "'", "ʹ": "'", "‹": "<", "›": ">",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-", "⁃": "-", "•": "-", "‧": "-",
    "…": "...", "⁄": "/", "∕": "/",
    "€": "EUR", "₤": "L", "‰": " per mille", "™": "(TM)",
    "≤": "<=", "≥": ">=", "≠": "!=", "≈": "~",
    "←": "<-", "→": "->", "↔": "<->", "ˆ": "^", "˜": "~",
    # Letters NFKD does not decompose.
    "Ł": "L", "ł": "l", "Đ": "D", "đ": "d", "ı": "i",
    "Ħ": "H", "ħ": "h", "Ŧ": "T", "ŧ": "t", "Ŋ": "N",
    "ŋ": "n", "ĸ": "k", "Œ": "OE", "œ": "oe", "Ĳ": "IJ",
    "ĳ": "ij", "Ŀ": "L", "ŀ": "l", "ſ": "s", "ƒ": "f",
}

_SPACES = frozenset("\t\n\r        "
                    "       　")


def _allowed(ch: str, ascii_only: bool) -> bool:
    code = ord(ch)
    if ascii_only:
        return 0x20 <= code <= 0x7E
    # Latin-1 minus the C0/C1 controls (and DEL), which XML either forbids or
    # a receiver would choke on; the soft hyphen is invisible and dropped.
    return (0x20 <= code <= 0x7E) or (0xA0 <= code <= 0xFF and code != 0xAD)


def _fold(ch: str, ascii_only: bool) -> str | None:
    """A spelling of ``ch`` the field accepts, ``""`` to drop it, ``None`` if
    it is a letter that cannot be written."""
    if ch in _SPACES:
        return " "
    if ch in _REWRITE:
        out = _REWRITE[ch]
        return out if all(_allowed(c, ascii_only) for c in out) else None
    category = unicodedata.category(ch)
    if category == "Nd":
        return str(unicodedata.digit(ch))
    decomposed = "".join(
        c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)
    )
    if decomposed and decomposed != ch and all(
            _allowed(c, ascii_only) or c in _REWRITE for c in decomposed):
        return "".join(c if _allowed(c, ascii_only) else _REWRITE[c] for c in decomposed)
    if category.startswith("L"):
        return None
    if category == "Pd":
        return "-"
    if category in ("Pi", "Pf"):
        return '"'
    # Emoji, pictographs, math and currency symbols without a spelling, marks,
    # format and control characters: decoration, not content.
    return ""


def unwritable_characters(value: str, *, ascii_only: bool = False) -> str:
    """The letters in ``value`` that no Latin spelling exists for, in order.

    For a UI that wants to warn *while* the operator types a customer name,
    instead of when the invoice is issued. Empty string means "fine".
    """
    seen: list[str] = []
    for ch in value:
        if _allowed(ch, ascii_only):
            continue
        if _fold(ch, ascii_only) is None and ch not in seen:
            seen.append(ch)
    return "".join(seen)


def to_latin(value: str, *, field: str, max_len: int | None = None,
             ascii_only: bool = False, required: bool = True) -> str:
    """``value`` rewritten for a FatturaPA text field, or a
    :class:`~einvoice.errors.ValidationError` that says what to change.

    Runs of whitespace collapse to one space (the XSD types are
    ``normalizedString``: tabs and newlines would become spaces anyway).
    ``max_len`` is checked *after* rewriting, since ``…`` becomes three
    characters and ``€`` becomes ``EUR``.
    """
    out: list[str] = []
    refused: list[str] = []
    for ch in value:
        if _allowed(ch, ascii_only):
            out.append(ch)
            continue
        folded = _fold(ch, ascii_only)
        if folded is None:
            if ch not in refused:
                refused.append(ch)
        else:
            out.append(folded)
    if refused:
        alphabet = "ASCII" if ascii_only else "latino (Latin-1)"
        raise ValidationError(
            f"{field}: contiene caratteri che FatturaPA non ammette "
            f"({''.join(refused[:12])!r}). Il formato accetta solo l'alfabeto "
            f"{alphabet}: riscrivere il testo in caratteri latini."
        )
    text = " ".join("".join(out).split())
    if required and not text:
        raise ValidationError(f"{field}: vuoto (il campo è obbligatorio)")
    if max_len is not None and len(text) > max_len:
        raise ValidationError(
            f"{field}: {len(text)} caratteri, FatturaPA ne ammette al massimo {max_len}"
        )
    return text
