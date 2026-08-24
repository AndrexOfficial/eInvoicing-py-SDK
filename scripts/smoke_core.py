#!/usr/bin/env python3
"""Prove the core works with **no optional dependencies installed**.

The package's headline claim is that generating a compliant e-invoice needs
nothing but the standard library. That is only true while it is tested, and it
is the kind of claim a single stray top-level ``import httpx`` breaks silently.

This script is what CI runs in an environment where ``httpx`` and
``cryptography`` are deliberately absent. It lives in the repository rather than
inline in the workflow because an inline copy drifts: the previous one used VAT
numbers that stopped validating when check-digit verification landed, and
nothing noticed until someone read the workflow. Here it is exercised by the
test suite too (``tests/test_smoke_script.py``), so it cannot rot unseen.

    python scripts/smoke_core.py
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from decimal import Decimal

OPTIONAL = ("httpx", "cryptography")


def assert_optional_deps_absent() -> None:
    present = [name for name in OPTIONAL if importlib.util.find_spec(name) is not None]
    if present:
        raise SystemExit(
            f"{', '.join(present)} must NOT be installed for this check — it "
            "exists to prove the core needs neither."
        )


def main() -> int:
    from einvoice import (
        Address,
        DocumentType,
        Invoice,
        LineItem,
        Party,
        ProductCategory,
        __version__,
        parse_invoice,
        rate_for,
        supported_countries,
    )
    from einvoice.formats import available_renderers, get_renderer

    # Real, checksum-valid identifiers. Made-up ones stopped working the day
    # check-digit validation landed, which is precisely how the old inline
    # version of this snippet broke.
    seller = Party(name="Studio Rossi", vat_number="07643520567",
                   address=Address("Via Roma 1", "20100", "Milano", "MI"))
    buyer = Party(name="ACME Srl", vat_number="09876543217", sdi_code="ABCDEFG",
                  address=Address("Via Verdi 9", "00100", "Roma", "RM"))
    invoice = Invoice(
        number="2026/0001", date=date(2026, 6, 5),
        seller=seller, buyer=buyer,
        lines=[LineItem.from_gross("Cena", 1, Decimal("122.00"), 22)],
    )
    invoice.validate()

    # Every renderer produces bytes, and every one of them reads back.
    for standard in ("fatturapa", "ubl", "cii"):
        rendered = get_renderer(standard).render(invoice)
        if not rendered.content.startswith(b"<?xml"):
            raise SystemExit(f"{standard}: not XML")
        restored = parse_invoice(rendered.content)
        if restored.total_document() != invoice.total_document():
            raise SystemExit(
                f"{standard}: round-trip total {restored.total_document()} "
                f"!= {invoice.total_document()}"
            )

    # A credit note has to land on the right root without any extra installed.
    credit = Invoice(
        number="NC-1", date=date(2026, 6, 6), seller=seller, buyer=buyer,
        document_type=DocumentType.CREDIT_NOTE,
        lines=[LineItem("Reso", Decimal("1"), Decimal("100"), Decimal("22"))],
    )
    if b"<CreditNote" not in get_renderer("ubl").render(credit).content:
        raise SystemExit("credit note did not use the UBL CreditNote root")

    # The reference data loads without any optional dependency either.
    if rate_for("IT", ProductCategory.BOOKS) != Decimal("4"):
        raise SystemExit("rate table did not load")

    print(
        f"core OK on einvoice {__version__} without {' or '.join(OPTIONAL)}: "
        f"{len(available_renderers())} renderers, "
        f"{len(supported_countries())} countries, render+parse round-trip clean"
    )
    return 0


if __name__ == "__main__":
    assert_optional_deps_absent()
    sys.exit(main())
