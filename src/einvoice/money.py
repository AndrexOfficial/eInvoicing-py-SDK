"""Decimal money helpers shared across the module.

Every amount in the package goes through :func:`D`, which makes it the one
place to enforce what "an amount" means here: a finite decimal. Nothing else
has to re-check.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .errors import ValidationError

CENTS = Decimal("0.01")
MICRO = Decimal("0.000001")


def D(value) -> Decimal:
    """Coerce to :class:`Decimal`, rejecting anything that is not a real amount.

    ``NaN`` and the infinities are valid Decimals and arithmetically contagious:
    one of them in a line price used to pass ``validate()`` untouched and then
    surface either as a document total of ``NaN`` or as an ``InvalidOperation``
    from deep inside XML generation. Both are worse than refusing the value at
    the point it enters — which is here, because this is the funnel.
    """
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError(f"Importo non valido: {value!r}") from exc
    if not result.is_finite():
        raise ValidationError(
            f"Importo non finito: {value!r}. Gli importi devono essere numeri reali."
        )
    return result


def q2(value) -> Decimal:
    return D(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def q6(value) -> Decimal:
    return D(value).quantize(MICRO, rounding=ROUND_HALF_UP)


def fmt2(value) -> str:
    return f"{q2(value):.2f}"


def fmt6(value) -> str:
    return f"{q6(value):.6f}"


def fmt_rate(value) -> str:
    return f"{q2(value):.2f}"


def fmt_price(value) -> str:
    """A unit price with the precision it actually carries: 2 decimals minimum,
    up to 6 when the number needs them.

    Formatting a unit price with :func:`fmt2` looks harmless and is not. A price
    of ``0.123456`` becomes ``0.12``, and the line total — computed from the
    full-precision value — no longer follows from the quantity and the price
    printed beside it. That is an internally inconsistent document: EN 16931
    requires the line net amount to equal quantity x price, and a receiver
    recomputing it gets a different answer. FatturaPA never had the problem
    because it always wrote six decimals.
    """
    quantized = q6(value).normalize()
    exponent = quantized.as_tuple().exponent
    # `D` guarantees a finite value, so the exponent is an int rather than one
    # of the NaN/Infinity markers the type allows.
    decimals = -int(exponent)
    return f"{quantized:.{max(2, min(decimals, 6))}f}"
