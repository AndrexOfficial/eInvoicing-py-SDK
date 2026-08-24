"""Decimal money helpers shared across the module."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")
MICRO = Decimal("0.000001")


def D(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


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
