"""SDI file naming.

The Sistema di Interscambio requires the transmitted file to be named
``{IdPaese}{IdCodice}_{progressivo}.xml`` where ``progressivo`` is a unique
alphanumeric ([A-Z0-9]) string, max 5 chars, that the transmitter must not
reuse. We encode a monotonically increasing counter in base-36 so a platform
only has to persist a single integer per transmitter.
"""
from __future__ import annotations

import re
import string

_ALPHABET = string.digits + string.ascii_uppercase  # base-36: 0-9 A-Z
_MAX = 36 ** 5  # progressivo space with 5 chars


def to_base36(n: int, width: int = 5) -> str:
    """Encode a non-negative int as a zero-padded base-36 string."""
    if n < 0:
        raise ValueError("progressivo deve essere >= 0")
    if n >= _MAX:
        raise ValueError("progressivo esaurito: oltre 60M invii, ruota l'IdCodice trasmittente")
    out = ""
    while n:
        n, rem = divmod(n, 36)
        out = _ALPHABET[rem] + out
    return out.rjust(width, "0")


def sdi_filename(country_code: str, fiscal_code: str, progressive: int | str) -> str:
    """Build the SDI transmission filename.

    ``progressive`` may be an int (encoded to base-36) or an already-formatted
    alphanumeric string.
    """
    prog = progressive if isinstance(progressive, str) else to_base36(progressive)
    prog = prog.upper()
    if not prog or len(prog) > 5 or any(c not in _ALPHABET for c in prog):
        raise ValueError("progressivo non valido: max 5 caratteri [A-Z0-9]")
    return f"{country_code.upper()}{fiscal_code}_{prog}.xml"


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(*parts: str | None, suffix: str = ".xml", fallback: str = "invoice") -> str:
    """A filesystem-safe name from whatever identifiers are available.

    Deliberately NOT :func:`sdi_filename`: that name is an Italian
    transmission requirement, and applying it to a UBL or CII document
    produced two bugs at once — a Swiss VAT number's dots leaked into the
    name, and a seller without a VAT number produced the literal
    ``"GBNone_00001.xml"``. Here a missing part is skipped, not stringified.
    """
    cleaned = [
        _UNSAFE.sub("-", str(part)).strip("-")
        for part in parts
        if part not in (None, "")
    ]
    stem = "_".join(c for c in cleaned if c) or fallback
    return f"{stem[:120]}{suffix}"
