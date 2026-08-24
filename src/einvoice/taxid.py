"""Tax-identifier validation — structure *and*, where possible, check digits.

Most VAT numbers carry a check digit. A regex only proves a number has the
right shape, so ``IT01234567891`` passes it while being arithmetically
impossible — and a typo in a counterparty's VAT number is not a cosmetic
problem: it routes the invoice to nobody and gets it rejected downstream.

So each country here is one of two honest states, and
:func:`validation_level` will tell you which:

``"checksum"``
    The check digit is verified. A typo is caught.
``"structural"``
    Only the shape is verified, because the algorithm is not public, has
    several incompatible variants in circulation, or would reject legitimate
    numbers. Stated plainly rather than implied.

Neither level proves the number *exists* or is *active* — that needs a VIES
(EU), HMRC (UK) or UID-register (CH) lookup, which is a network call and
deliberately outside this package.

Every algorithm below is pinned by a test against a real, published number for
that country (``tests/test_taxid.py``). An algorithm that cannot be pinned that
way is not shipped as a checksum: wrongly rejecting a real customer's VAT
number is far worse than accepting a typo.
"""
from __future__ import annotations

import re
from collections.abc import Callable

__all__ = [
    "normalize_tax_id",
    "validate_tax_id_full",
    "validation_level",
    "CHECKSUM_COUNTRIES",
]

# ─────────────────────────────────────────────────────────── normalization ──

#: Separators and decorations that appear in printed VAT numbers but are not
#: part of the identifier: ``CHE-116.281.710 MWST``, ``FR 40 303 265 045``.
_NOISE = re.compile(r"[\s.\-/]")
#: Swiss UID suffixes naming the register the number is enrolled in.
_CH_SUFFIX = re.compile(r"(MWST|TVA|IVA|VAT)$")

#: Shortest valid bare identifier, for countries where a leading country code
#: could also be part of the number itself. Only France qualifies today — see
#: :func:`normalize_tax_id`.
_MIN_BARE_LENGTH = {"FR": 11}


def normalize_tax_id(country_code: str, value: str | None) -> str:
    """Strip decoration and any country prefix, upper-case the rest.

    ``"CHE-116.281.710 MWST"`` → ``"CHE116281710"``;
    ``"IT 0123 4567 891"`` → ``"01234567891"``. Greece is the special case
    every VAT implementation trips over: the ISO country code is ``GR`` but
    the VIES prefix is ``EL``, and both appear in the wild.
    """
    if not value:
        return ""
    v = _NOISE.sub("", value).upper()
    country = (country_code or "").upper()
    if country == "CH":
        v = _CH_SUFFIX.sub("", v)
    prefixes = ("EL", "GR") if country == "GR" else (country,)
    for prefix in prefixes:
        if prefix and v.startswith(prefix):
            # CHE is the Swiss identifier's own prefix, not the country code —
            # stripping "CH" from "CHE116281710" would leave "E116281710".
            if country == "CH" and v.startswith("CHE"):
                break
            stripped = v[len(prefix):]
            # France is the only country whose *bare* number can begin with its
            # own ISO code: the 2-character key is drawn from [0-9A-HJ-NP-Z],
            # which includes both F and R. So "FR123456789" is ambiguous — it
            # could be a prefixed 9-digit number (there is no such thing) or a
            # bare number with the key "FR". Length settles it: stripping a
            # real prefix must leave a plausible identifier behind, and
            # stripping here would leave one too short.
            if len(stripped) < _MIN_BARE_LENGTH.get(country, 0):
                break
            v = stripped
            break
    return v


# ──────────────────────────────────────────────────────────────  helpers ──


def _weighted(digits: str, weights: list[int]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=False))


def _luhn_ok(number: str) -> bool:
    total, double = 0, False
    for ch in reversed(number):
        d = int(ch)
        if double:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        double = not double
    return total % 10 == 0


def _mod11_10(number: str) -> bool:
    """ISO 7064 MOD 11,10 — used by Germany and Croatia."""
    product = 10
    for ch in number[:-1]:
        s = (int(ch) + product) % 10 or 10
        product = (s * 2) % 11
    return (11 - product) % 10 == int(number[-1])


# ─────────────────────────────────────────────────────────── per country ──
# Each returns True/False for an already-normalized (prefix-stripped) value.


def _at(v: str) -> bool:                                   # ATU + 8 digits
    if not re.fullmatch(r"U\d{8}", v):
        return False
    body = v[1:8]
    # Odd positions count as-is, even positions are doubled and cross-summed;
    # the check digit is (96 − S) mod 10. No constant is added to S — an early
    # draft of this had one and rejected every real Austrian number.
    total = sum(
        (int(d) if i % 2 == 0 else sum(divmod(int(d) * 2, 10)))
        for i, d in enumerate(body)
    )
    return (96 - total) % 10 == int(v[8])


def _be(v: str) -> bool:                                   # 10 digits, mod 97
    if not re.fullmatch(r"[01]\d{9}", v):
        return False
    return int(v[:8]) % 97 == 97 - int(v[8:])


def _dk(v: str) -> bool:                                   # 8 digits, mod 11
    if not re.fullmatch(r"\d{8}", v):
        return False
    return _weighted(v, [2, 7, 6, 5, 4, 3, 2, 1]) % 11 == 0


def _de(v: str) -> bool:                                   # 9 digits, ISO 7064
    return bool(re.fullmatch(r"\d{9}", v)) and _mod11_10(v)


def _hr(v: str) -> bool:                                   # 11 digits, ISO 7064
    return bool(re.fullmatch(r"\d{11}", v)) and _mod11_10(v)


def _ee(v: str) -> bool:                                   # 9 digits
    if not re.fullmatch(r"\d{9}", v):
        return False
    total = _weighted(v[:8], [3, 7, 1, 3, 7, 1, 3, 7])
    return (10 - total % 10) % 10 == int(v[8])


def _fi(v: str) -> bool:                                   # 8 digits, mod 11
    if not re.fullmatch(r"\d{8}", v):
        return False
    rem = _weighted(v[:7], [7, 9, 10, 5, 8, 4, 2]) % 11
    if rem == 1:
        return False                                       # number not issued
    return (0 if rem == 0 else 11 - rem) == int(v[7])


def _fr(v: str) -> bool:
    """2-char key + 9-digit SIREN. Only the numeric key is verifiable:
    alphabetic keys use an unpublished algorithm, so they pass on structure."""
    if not re.fullmatch(r"[A-HJ-NP-Z0-9]{2}\d{9}", v):
        return False
    key, siren = v[:2], v[2:]
    if not key.isdigit():
        return True                                        # structural only
    return int(key) == (12 + 3 * (int(siren) % 97)) % 97


def _gr(v: str) -> bool:                                   # 9 digits, mod 11
    if not re.fullmatch(r"\d{9}", v):
        return False
    total = sum(int(d) * 2 ** (8 - i) for i, d in enumerate(v[:8]))
    return (total % 11) % 10 == int(v[8])


def _hu(v: str) -> bool:                                   # 8 digits
    if not re.fullmatch(r"\d{8}", v):
        return False
    total = _weighted(v[:7], [9, 7, 3, 1, 9, 7, 3])
    return (10 - total % 10) % 10 == int(v[7])


def _ie(v: str) -> bool:
    """Two live formats: the modern ``1234567FA`` and the legacy ``1A23456B``
    where the second character encodes part of the number."""
    alphabet = "WABCDEFGHIJKLMNOPQRSTUV"
    if re.fullmatch(r"\d{7}[A-W][A-IW]?", v):
        body, check = v[:7], v[7]
        extra = v[8] if len(v) > 8 and v[8] != "W" else ""
        total = _weighted(body, [8, 7, 6, 5, 4, 3, 2])
        if extra:                                          # 9-char variant
            total += (alphabet.index(extra)) * 9
        return alphabet[total % 23] == check
    if re.fullmatch(r"\d[A-Z+*]\d{5}[A-W]", v):            # legacy layout
        body = v[2:7] + "0" + v[0]
        total = _weighted(body, [8, 7, 6, 5, 4, 3, 2])
        return alphabet[total % 23] == v[7]
    return False


def _it(v: str) -> bool:                                   # 11 digits, Luhn
    return bool(re.fullmatch(r"\d{11}", v)) and _luhn_ok(v)


def _lu(v: str) -> bool:                                   # 8 digits, mod 89
    if not re.fullmatch(r"\d{8}", v):
        return False
    return int(v[:6]) % 89 == int(v[6:])


def _nl(v: str) -> bool:
    """``123456789B01``. Only the classic mod-11 form is verifiable: since 2020
    sole traders carry a randomly generated number with no check digit, so a
    failing mod-11 is not proof of a typo — it falls back to structural."""
    if not re.fullmatch(r"\d{9}B\d{2}", v):
        return False
    body = v[:9]
    if _weighted(body[:8], [9, 8, 7, 6, 5, 4, 3, 2]) % 11 == int(body[8]):
        return True
    return True                                            # see docstring


def _pl(v: str) -> bool:                                   # 10 digits, mod 11
    if not re.fullmatch(r"\d{10}", v):
        return False
    rem = _weighted(v[:9], [6, 5, 7, 2, 3, 4, 5, 6, 7]) % 11
    return rem != 10 and rem == int(v[9])


def _pt(v: str) -> bool:                                   # 9 digits, mod 11
    if not re.fullmatch(r"\d{9}", v):
        return False
    rem = _weighted(v[:8], [9, 8, 7, 6, 5, 4, 3, 2]) % 11
    expected = 0 if rem < 2 else 11 - rem
    return expected == int(v[8])


def _se(v: str) -> bool:                                   # 12 digits, Luhn/10
    if not re.fullmatch(r"\d{10}0[1-9]", v):
        return False
    return _luhn_ok(v[:10])


def _si(v: str) -> bool:                                   # 8 digits, mod 11
    if not re.fullmatch(r"[1-9]\d{7}", v):
        return False
    rem = 11 - _weighted(v[:7], [8, 7, 6, 5, 4, 3, 2]) % 11
    if rem == 11:
        rem = 0
    return rem != 10 and rem == int(v[7])


def _sk(v: str) -> bool:                                   # 10 digits, mod 11
    if not re.fullmatch(r"[1-9]\d[2346-9]\d{7}", v):
        return False
    return int(v) % 11 == 0


def _gb(v: str) -> bool:
    """9 or 12 digits (mod-97, both the old and the 9755 variant), or the
    ``GD``/``HA`` government and health-authority ranges."""
    if re.fullmatch(r"(GD|HA)\d{3}", v):
        return True
    if not re.fullmatch(r"\d{9}(\d{3})?", v):
        return False
    body = v[:9]
    total = _weighted(body[:7], [8, 7, 6, 5, 4, 3, 2])
    check = int(body[7:9])
    return (total + check) % 97 == 0 or (total + check + 55) % 97 == 0


def _ch(v: str) -> bool:
    """Swiss UID: ``CHE`` + 9 digits, mod-11 check digit.

    The same number is the VAT number (with an ``MWST``/``TVA``/``IVA``
    suffix in print) and the commercial-register identifier.
    """
    if not re.fullmatch(r"CHE\d{9}", v):
        return False
    digits = v[3:]
    total = _weighted(digits[:8], [5, 4, 3, 2, 7, 6, 5, 4])
    rem = 11 - total % 11
    if rem == 10:
        return False                                       # never issued
    return (0 if rem == 11 else rem) == int(digits[8])


def _us_ein(v: str) -> bool:
    """US EIN — 9 digits with a valid campus prefix. There is no check digit,
    so this is the strongest check available offline."""
    if not re.fullmatch(r"\d{9}", v):
        return False
    invalid_prefixes = {"07", "08", "09", "17", "18", "19", "28", "29",
                        "49", "78", "79", "89"}
    return v[:2] not in invalid_prefixes and v[:2] != "00"


#: Countries whose check digit is actually verified. Everything else in
#: ``COUNTRY_PROFILES`` is structural — see the module docstring.
_VALIDATORS: dict[str, Callable[[str], bool]] = {
    "AT": _at, "BE": _be, "CH": _ch, "DE": _de, "DK": _dk, "EE": _ee,
    "FI": _fi, "FR": _fr, "GB": _gb, "GR": _gr, "HR": _hr, "HU": _hu,
    "IE": _ie, "IT": _it, "LU": _lu, "PL": _pl, "PT": _pt, "SE": _se,
    "SI": _si, "SK": _sk,
}

#: Structure-only, and deliberately so.
_STRUCTURAL_ONLY = {
    "BG": "tre algoritmi diversi (persona fisica / giuridica / straniera)",
    "CY": "mappatura del check digit non pubblicata integralmente",
    "CZ": "quattro varianti (azienda, persona fisica, casi speciali)",
    "ES": "check digit alfanumerico con regole diverse per tipo di soggetto",
    "LT": "due lunghezze con algoritmi distinti e regola di riporto",
    "LV": "algoritmi diversi per persone giuridiche e fisiche",
    "MT": "algoritmo non pubblicato in forma stabile",
    "NL": "dal 2020 le partite IVA individuali non hanno check digit",
    "RO": "lunghezza variabile 2–10, regole non uniformi",
    "US": "l'EIN non ha check digit (si verifica solo il prefisso di campus)",
}

CHECKSUM_COUNTRIES = frozenset(_VALIDATORS) - {"NL"}


def validation_level(country_code: str) -> str:
    """``"checksum"`` or ``"structural"`` for a country — say which, don't imply."""
    return "checksum" if (country_code or "").upper() in CHECKSUM_COUNTRIES else "structural"


def validate_tax_id_full(country_code: str, value: str | None, *, pattern: str | None) -> bool:
    """Validate a tax id: check digit where we have one, structure otherwise.

    ``pattern`` is the country profile's structural fallback, applied when no
    checksum algorithm is registered.
    """
    country = (country_code or "").upper()
    v = normalize_tax_id(country, value)
    if not v:
        return False
    validator = _VALIDATORS.get(country)
    if validator is not None:
        return validator(v)
    if country == "US":
        return _us_ein(v)
    if pattern is None:
        return True
    return re.fullmatch(pattern, v) is not None
