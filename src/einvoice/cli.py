"""``python -m einvoice`` — inspect, validate, render and sign from a shell.

Not a convenience wrapper: it is how you check the engine's answer against a
real accountant's expectations without standing up a host application. Point it
at a JSON invoice (see :mod:`einvoice.serde`) and it prints exactly the bytes a
transport would send.

    python -m einvoice validate fattura.json
    python -m einvoice render fattura.json --standard fatturapa -o IT0123_00001.xml
    python -m einvoice render fattura.json --country DE --xrechnung
    python -m einvoice totals fattura.json
    python -m einvoice sign fattura.xml --p12 cert.p12 --passphrase ...
    python -m einvoice countries IT
    python -m einvoice transports

Exit codes: ``0`` success, ``1`` invalid input (validation, bad JSON, signing
failure), ``2`` CLI usage error. That split matters in CI — a rejected invoice
is a finding, a mistyped flag is not.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .countries import COUNTRY_PROFILES, profile_for, renderer_for_country, validate_tax_id
from .errors import EInvoiceError
from .formats import available_renderers, get_renderer
from .serde import invoice_from_json, invoice_to_json
from .transport import available_transports

EXIT_OK, EXIT_INVALID, EXIT_USAGE = 0, 1, 2


def _load(path: str):
    """Read a JSON invoice from a path, or from stdin when given ``-``."""
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return invoice_from_json(raw)


def _renderer_for(args):
    if args.country:
        return renderer_for_country(args.country, xrechnung=args.xrechnung)
    return get_renderer(args.standard)


# ────────────────────────────────────────────────────────────  commands ──


def cmd_validate(args) -> int:
    invoice = _load(args.path)
    invoice.validate()
    profile = profile_for(invoice.seller.country_code)
    print(f"OK  {invoice.number} — {invoice.date}  ({profile.name}, standard {profile.default_standard})")
    print(f"    imponibile {invoice.taxable_total()}  IVA {invoice.tax_total()}  "
          f"totale {invoice.total_document()} {invoice.currency}")
    if invoice.withholdings:
        print(f"    ritenuta {invoice.withholding_total()}  netto a pagare {invoice.total_payable()}")
    return EXIT_OK


def cmd_render(args) -> int:
    invoice = _load(args.path)
    rendered = _renderer_for(args).render(invoice)
    if args.out:
        Path(args.out).write_bytes(rendered.content)
        print(f"{rendered.standard} → {args.out} ({len(rendered.content)} byte)", file=sys.stderr)
    else:
        # Bytes, not text: the XML declares its own encoding and must not be
        # re-encoded by the terminal on the way out.
        sys.stdout.buffer.write(rendered.content)
    return EXIT_OK


def cmd_totals(args) -> int:
    """Print the computed VAT breakdown — the numbers an accountant checks."""
    invoice = _load(args.path)
    rows = [
        {"aliquota": str(v.vat_rate), "natura": v.nature.value if v.nature else None,
         "imponibile": str(v.taxable), "imposta": str(v.tax)}
        for v in invoice.vat_summary()
    ]
    print(json.dumps({
        "numero": invoice.number,
        "riepiloghi": rows,
        "imponibile_totale": str(invoice.taxable_total()),
        "imposta_totale": str(invoice.tax_total()),
        "totale_documento": str(invoice.total_document()),
        "netto_a_pagare": str(invoice.total_payable()),
        "valuta": invoice.currency,
    }, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_normalize(args) -> int:
    """Round-trip a JSON invoice through the model — canonical form, defaults
    filled in. Useful for diffing two fixtures that should be equivalent."""
    print(invoice_to_json(_load(args.path)))
    return EXIT_OK


def cmd_sign(args) -> int:
    from .signer import sign_cades, sign_filename

    xml = Path(args.path).read_bytes()
    signed = sign_cades(xml, args.p12, args.passphrase)
    out = args.out or sign_filename(args.path)
    Path(out).write_bytes(signed)
    print(f"firmato → {out} ({len(signed)} byte)", file=sys.stderr)
    return EXIT_OK


def cmd_countries(args) -> int:
    if args.code:
        profile = profile_for(args.code)
        print(json.dumps({
            "code": profile.code, "name": profile.name,
            "default_standard": profile.default_standard,
            "tax_scheme": profile.tax_scheme,
            "tax_id_pattern": profile.tax_id_pattern,
            "peppol": profile.code in COUNTRY_PROFILES,
        }, indent=2, ensure_ascii=False))
        if args.tax_id:
            ok = validate_tax_id(args.code, args.tax_id)
            print(f"tax id {args.tax_id!r}: {'valido' if ok else 'NON valido'} per {profile.code}")
            return EXIT_OK if ok else EXIT_INVALID
        return EXIT_OK
    for code in sorted(COUNTRY_PROFILES):
        profile = COUNTRY_PROFILES[code]
        print(f"{code}  {profile.default_standard:<10} {profile.tax_scheme:<4} {profile.name}")
    return EXIT_OK


def cmd_transports(_args) -> int:
    print("\n".join(available_transports()))
    return EXIT_OK


def cmd_renderers(_args) -> int:
    print("\n".join(available_renderers()))
    return EXIT_OK


# ──────────────────────────────────────────────────────────────  parser ──


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="einvoice",
        description="Motore di fatturazione elettronica — validazione, rendering, firma.",
    )
    parser.add_argument("--version", action="version", version=f"einvoice {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_source(p):
        p.add_argument("path", help="fattura JSON ('-' per stdin)")
        return p

    with_source(sub.add_parser("validate", help="valida la fattura e stampa i totali")).set_defaults(func=cmd_validate)
    with_source(sub.add_parser("totals", help="stampa i riepiloghi IVA calcolati")).set_defaults(func=cmd_totals)
    with_source(sub.add_parser("normalize", help="riscrive il JSON in forma canonica")).set_defaults(func=cmd_normalize)

    render = with_source(sub.add_parser("render", help="genera l'XML dello standard scelto"))
    render.add_argument("--standard", default="fatturapa", choices=available_renderers(),
                        help="renderer esplicito (default: fatturapa)")
    render.add_argument("--country", help="scegli il renderer dal paese del cedente (es. DE, FR)")
    render.add_argument("--xrechnung", action="store_true", help="CIUS XRechnung (Germania B2G)")
    render.add_argument("-o", "--out", help="file di destinazione (default: stdout)")
    render.set_defaults(func=cmd_render)

    sign = sub.add_parser("sign", help="firma CAdES .p7m di un XML già generato")
    sign.add_argument("path", help="file XML da firmare")
    sign.add_argument("--p12", required=True, help="certificato PKCS#12 (.p12/.pfx)")
    sign.add_argument("--passphrase", default=None, help="passphrase del P12")
    sign.add_argument("-o", "--out", help="file .p7m di destinazione")
    sign.set_defaults(func=cmd_sign)

    countries = sub.add_parser("countries", help="elenca o descrive i profili paese")
    countries.add_argument("code", nargs="?", help="codice ISO del paese (es. IT)")
    countries.add_argument("--tax-id", help="verifica una partita IVA / tax id per quel paese")
    countries.set_defaults(func=cmd_countries)

    sub.add_parser("transports", help="elenca i canali di trasmissione").set_defaults(func=cmd_transports)
    sub.add_parser("renderers", help="elenca i renderer disponibili").set_defaults(func=cmd_renderers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except EInvoiceError as exc:
        # A rejected invoice is the tool working, so it gets a clean message
        # rather than a traceback the caller has to read past.
        print(f"errore: {exc}", file=sys.stderr)
        return EXIT_INVALID
    except FileNotFoundError as exc:
        print(f"file non trovato: {exc.filename}", file=sys.stderr)
        return EXIT_INVALID
    except (ValueError, RuntimeError) as exc:
        print(f"errore: {exc}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
