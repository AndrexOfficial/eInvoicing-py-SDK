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
    python -m einvoice providers aruba --setup --lang de
    python -m einvoice renderers --country FR --lang fr

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
from .countries import (
    COUNTRY_PROFILES,
    EU_OSS_THRESHOLD,
    MANDATES_VERIFIED_AS_OF,
    profile_for,
    renderer_for_country,
    validate_tax_id,
)
from .errors import EInvoiceError
from .formats import available_renderers, get_renderer
from .i18n import available_locales
from .parsing import compare_declared_totals, detect_standard, parse_invoice
from .rates import (
    NO_NATIONAL_VAT,
    RATES_VERIFIED_AS_OF,
    ProductCategory,
    RateKind,
    rate_for,
    rates_for,
    standard_rate,
)
from .serde import invoice_from_json, invoice_to_json
from .transport import (
    PROVIDER_KINDS,
    PROVIDER_PRESETS,
    available_providers,
    available_transports,
    preset_for,
    providers_for_country,
    providers_of_kind,
)

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


def cmd_parse(args) -> int:
    """Read a received e-invoice and print it as our JSON shape.

    The inbound half: point it at whatever a supplier sent and get back a
    document you can diff, store or re-render.
    """
    raw = sys.stdin.buffer.read() if args.path == "-" else Path(args.path).read_bytes()
    invoice = parse_invoice(raw, standard=args.standard)
    if args.out:
        Path(args.out).write_text(invoice_to_json(invoice), encoding="utf-8")
        print(f"{detect_standard(raw)} → {args.out}", file=sys.stderr)
    else:
        print(invoice_to_json(invoice))
    return EXIT_OK


def cmd_inspect(args) -> int:
    """Summarise a received document: who, how much, and does it add up.

    Exits 1 when the total the supplier states disagrees with what their own
    lines produce — the one discrepancy worth stopping a pipeline for.
    """
    raw = sys.stdin.buffer.read() if args.path == "-" else Path(args.path).read_bytes()
    standard = detect_standard(raw)
    invoice = parse_invoice(raw, standard=standard)
    totals = compare_declared_totals(raw)

    print(f"formato      {standard}")
    print(f"documento    {invoice.number}  del {invoice.date}  "
          f"({invoice.document_type.value})")
    print(f"cedente      {invoice.seller.display_name()}  "
          f"[{invoice.seller.country_code} {invoice.seller.vat_number or '—'}]")
    print(f"cessionario  {invoice.buyer.display_name()}  "
          f"[{invoice.buyer.country_code} {invoice.buyer.vat_number or '—'}]")
    print(f"righe        {len(invoice.lines)}")
    print(f"imponibile   {invoice.taxable_total()} {invoice.currency}")
    print(f"imposta      {invoice.tax_total()} {invoice.currency}")
    print(f"totale       calcolato {totals['computed']} {invoice.currency}"
          + (f" · dichiarato {totals['declared']}" if totals["declared"] is not None else ""))

    for finding in invoice.check():
        print(f"rilievo      {finding.code}: {finding.message}")

    difference = totals["difference"]
    if difference:
        print(f"DISALLINEAMENTO  il totale dichiarato differisce di {difference} "
              f"{invoice.currency} da quanto risulta dalle righe")
        return EXIT_INVALID
    return EXIT_OK


def cmd_check(args) -> int:
    """Advisory findings — what a human should look at before sending.

    Exits 0 even when it finds something: these are warnings, not errors, and a
    pipeline that treats them as failures would block legitimate invoices. Use
    ``--strict`` to opt into a non-zero exit.
    """
    invoice = _load(args.path)
    findings = invoice.check()
    if not findings:
        print("nessun rilievo")
        return EXIT_OK
    for finding in findings:
        print(f"{finding.code}: {finding.message}")
    return EXIT_INVALID if args.strict else EXIT_OK


def cmd_countries(args) -> int:
    if args.code:
        profile = profile_for(args.code)
        regime = profile.regime
        print(json.dumps({
            "code": profile.code, "name": profile.name,
            "eu_member": profile.eu_member,
            "default_standard": profile.default_standard,
            "tax_scheme": profile.tax_scheme,
            "tax_id_label": profile.tax_id_label,
            "tax_id_validation": profile.tax_id_validation,
            "tax_id_pattern": profile.tax_id_pattern,
            "currency": profile.currency_hint,
            "vat_rates": list(profile.vat_rates),
            "einvoicing": {
                "network": regime.network,
                "b2g": regime.b2g,
                "b2b": regime.b2b,
                "customization": regime.customization,
                "national_format": regime.national_format,
                "covered_by_this_package": regime.covered_by_this_package,
                "notes": regime.notes,
            },
            "notes": profile.notes,
            "regulatory_data_verified_as_of": MANDATES_VERIFIED_AS_OF.isoformat(),
        }, indent=2, ensure_ascii=False))
        if args.tax_id:
            ok = validate_tax_id(args.code, args.tax_id)
            level = profile.tax_id_validation
            print(f"tax id {args.tax_id!r}: {'valido' if ok else 'NON valido'} "
                  f"per {profile.code} (verifica: {level})")
            return EXIT_OK if ok else EXIT_INVALID
        return EXIT_OK
    print(f"{'ISO':4} {'STD':<10} {'TAX':<4} {'B2G':<10} {'B2B':<10} {'ID':<11} NOME")
    for code in sorted(COUNTRY_PROFILES):
        profile = COUNTRY_PROFILES[code]
        r = profile.regime
        flag = "" if r.covered_by_this_package else "  ⚠ formato nazionale"
        print(f"{code:4} {profile.default_standard:<10} {profile.tax_scheme:<4} "
              f"{r.b2g:<10} {r.b2b:<10} {profile.tax_id_validation:<11} "
              f"{profile.name}{flag}")
    print(f"\ndati normativi verificati al {MANDATES_VERIFIED_AS_OF.isoformat()} — "
          "verificare presso l'autorità fiscale nazionale prima di farne affidamento")
    return EXIT_OK


def cmd_rates(args) -> int:
    """VAT rates in force in a country, and what each one covers."""
    code = args.country.upper()
    entries = rates_for(code)
    if not entries:
        reason = NO_NATIONAL_VAT.get(code)
        print(reason or f"Nessuna tabella di aliquote per {code!r}.")
        return EXIT_OK if reason else EXIT_INVALID

    if args.category:
        try:
            category = ProductCategory(args.category)
        except ValueError:
            print(f"Categoria sconosciuta: {args.category!r}. Disponibili: "
                  + ", ".join(c.value for c in ProductCategory), file=sys.stderr)
            return EXIT_USAGE
        found = rate_for(code, category)
        if found is None:
            print(f"{code}: aliquota per '{category.value}' non mappata in questo "
                  "pacchetto — verificare presso l'autorità fiscale.")
            return EXIT_OK
        print(f"{code}  {category.value}  →  {found}%")
        return EXIT_OK

    print(f"{'ALIQUOTA':>9}  {'TIPO':<14} CATEGORIE")
    for entry in entries:
        # "everything else" is a property of the standard rate alone; saying it
        # of an unmapped zero rate would claim the opposite of what it means.
        categories = ", ".join(c.value for c in entry.categories) or (
            "(tutto ciò che non rientra sotto)" if entry.kind is RateKind.STANDARD
            else "(nessuna categoria mappata)")
        print(f"{str(entry.rate) + '%':>9}  {entry.kind.value:<14} {categories}")
        if entry.note:
            print(f"{'':>9}  {'':<14} — {entry.note}")
    print(f"\naliquote verificate al {RATES_VERIFIED_AS_OF.isoformat()}; la "
          "mappatura per categoria è parziale per scelta — una categoria non "
          "elencata è una che questo pacchetto non sa dichiarare con certezza")
    return EXIT_OK


def cmd_rules(args) -> int:
    """The non-rate obligations: retention, thresholds, deadlines."""
    profile = profile_for(args.country)
    rules = profile.fiscal_rules
    print(json.dumps({
        "country": profile.code or args.country.upper(),
        "name": profile.name,
        "currency": profile.currency_hint,
        "standard_rate": str(standard_rate(profile.code)) if standard_rate(profile.code) else None,
        "retention_years": rules.retention_years,
        "simplified_invoice_threshold": (
            str(rules.simplified_invoice_threshold)
            if rules.simplified_invoice_threshold is not None else None),
        "issue_deadline_days": rules.issue_deadline_days,
        "domestic_reverse_charge": rules.domestic_reverse_charge,
        "eu_oss_threshold": str(EU_OSS_THRESHOLD) if profile.eu_member else None,
        "notes": rules.notes,
        "einvoicing": {
            "network": profile.regime.network,
            "b2g": profile.regime.b2g,
            "b2b": profile.regime.b2b,
            "national_format": profile.regime.national_format,
        },
        "verified_as_of": MANDATES_VERIFIED_AS_OF.isoformat(),
    }, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_providers(args) -> int:
    """List the e-invoicing platforms with a ready-made preset."""
    if args.key and args.setup:
        return _print_setup_guide(args.key, args.lang)

    if args.key:
        preset = preset_for(args.key)
        print(json.dumps({
            "key": preset.key, "name": preset.name,
            "countries": list(preset.countries), "kind": preset.kind,
            "transport": preset.transport, "renderer": preset.renderer,
            "supports": list(preset.supports),
            "credentials": list(preset.credentials),
            "needs_base_url": preset.needs_base_url,
            "base_url": preset.base_url, "sandbox_url": preset.sandbox_url,
            "endpoints_verified": preset.endpoints_verified,
            "docs": preset.docs_url, "extra_defaults": preset.extra,
            "setup_flags": list(preset.setup_flags),
            "incompatible_national_format": preset.incompatible_national_format,
            "notes": preset.notes,
        }, indent=2, ensure_ascii=False))
        return EXIT_OK

    if args.kinds:
        for kind, description in sorted(PROVIDER_KINDS.items()):
            print(f"{kind:<20} {len(providers_of_kind(kind)):>3}  {description}")
        return EXIT_OK

    if args.country:
        presets = providers_for_country(args.country, kind=args.kind)
    elif args.kind:
        presets = providers_of_kind(args.kind)
    else:
        presets = [PROVIDER_PRESETS[k] for k in available_providers()]

    # Widths from the data, not guessed — one long key used to shear the table.
    key_w = max((len(p.key) for p in presets), default=3) + 1
    print(f"{'KEY':<{key_w}} {'MERCATI':<14} {'CATEGORIA':<20} {'FORMATO':<10} VERIF  NOME")
    for preset in presets:
        mark = "sì" if preset.endpoints_verified else "—"
        markets = ",".join(preset.countries)
        print(f"{preset.key:<{key_w}} {markets[:13]:<14} {preset.kind:<20} "
              f"{preset.renderer:<10} {mark:<6} {preset.name}")
    print(f"\n{len(presets)} piattaforme. 'verif' = endpoint implementati su contratto "
          "pubblico e coperti dai test; altrimenti confermare i path sulla "
          "documentazione del tuo account.")
    return EXIT_OK


def cmd_transports(_args) -> int:
    print("\n".join(available_transports()))
    return EXIT_OK


def _print_setup_guide(key: str, lang: str | None) -> int:
    """The human-readable form of :func:`einvoice.onboarding.setup_guide`.

    Printed rather than dumped as JSON because this is the one CLI output meant
    to be *read* — it is the same text a host would put on its settings screen,
    and seeing it here is how you check a new preset before shipping it.
    """
    from .onboarding import setup_guide

    guide = setup_guide(key, lang)
    labels = guide["labels"]
    print(f"{guide['name']}  [{guide['key']}]")
    print(f"{labels['category']}: {guide['kind_label']}")
    print(f"{labels['markets']}: {', '.join(guide['countries'])}")
    print(f"{labels['format']}: {guide['renderer_syntax']}  ({guide['renderer']})")
    print(f"{labels['capabilities']}: {', '.join(c['label'] for c in guide['capabilities'])}")
    print(f"{guide['verification_label']}")
    if guide["docs_url"]:
        print(f"{labels['documentation']}: {guide['docs_url']}")

    print(f"\n{labels['credentials']}")
    for field in guide["credentials"]:
        secret = " ***" if field["secret"] else ""
        print(f"  · {field['key']}{secret} — {field['label']}")
        if field["hint"]:
            print(f"      {field['hint']}")

    print(f"\n{labels['steps']}")
    for n, step in enumerate(guide["steps"], 1):
        print(f"  {n}. {step['text']}")

    if guide["caveats"]:
        print(f"\n{labels['caveats']}")
        for caveat in guide["caveats"]:
            print(f"  ! {caveat['text']}")
    if guide["notes"]:
        print(f"\n[{guide['notes_language']}] {guide['notes']}")
    return EXIT_OK


def cmd_renderers(args) -> int:
    """Describe the document formats, not just name them.

    The bare registry keys are six strings of which three are aliases, so the
    old one-per-line listing could not tell you that ``zugferd`` and ``facturx``
    build the same bytes — which is the only question the list gets asked.
    """
    from .reference import all_renderer_references, renderer_reference

    lang = getattr(args, "lang", None)
    if getattr(args, "key", None):
        print(json.dumps(renderer_reference(args.key, lang), indent=2, ensure_ascii=False))
        return EXIT_OK

    specs = all_renderer_references(lang, country=getattr(args, "country", None))
    for spec in specs:
        alias = f"  (= {', '.join(spec['aliases'])})" if spec["aliases"] else ""
        print(f"{spec['key']:<10} {spec['syntax']:<32} {', '.join(spec['countries'])}{alias}")
        print(f"           {spec['description']}")
        for profile in spec["profiles"]:
            where = f" [{', '.join(profile['countries'])}]" if profile["countries"] else ""
            print(f"           · {profile['name']}{where}")
    if not getattr(args, "country", None):
        print(f"\nAlias risolti: {', '.join(sorted(set(available_renderers())))}")
    return EXIT_OK


def cmd_locales(_args) -> int:
    """Languages the setup labels come in."""
    from .reference import locale_reference

    print(json.dumps(locale_reference(), indent=2, ensure_ascii=False))
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

    parse = sub.add_parser("parse", help="legge una fattura ricevuta → JSON")
    parse.add_argument("path", help="XML ricevuto ('-' per stdin)")
    parse.add_argument("--standard", choices=["fatturapa", "ubl", "cii"],
                       help="forza il formato invece di rilevarlo")
    parse.add_argument("-o", "--out", help="file JSON di destinazione")
    parse.set_defaults(func=cmd_parse)

    inspect = sub.add_parser("inspect", help="riepiloga una fattura ricevuta")
    inspect.add_argument("path", help="XML ricevuto ('-' per stdin)")
    inspect.set_defaults(func=cmd_inspect)

    check = with_source(sub.add_parser(
        "check", help="rilievi non bloccanti (aliquote, regimi, date)"))
    check.add_argument("--strict", action="store_true",
                       help="esci con codice 1 se ci sono rilievi")
    check.set_defaults(func=cmd_check)

    rates = sub.add_parser("rates", help="aliquote IVA di un paese, per categoria")
    rates.add_argument("country", help="codice ISO (es. IT, DE, CH)")
    rates.add_argument("--category", help="aliquota per una categoria specifica")
    rates.set_defaults(func=cmd_rates)

    rules = sub.add_parser("rules", help="obblighi non-aliquota: conservazione, soglie, termini")
    rules.add_argument("country", help="codice ISO (es. IT, DE, CH)")
    rules.set_defaults(func=cmd_rules)

    providers = sub.add_parser("providers", help="piattaforme di e-invoicing supportate")
    providers.add_argument("key", nargs="?", help="dettaglio di una piattaforma")
    providers.add_argument("--country", help="filtra per paese (es. IT, FR, CH)")
    providers.add_argument("--kind", help="filtra per categoria (vedi --kinds)")
    providers.add_argument("--setup", action="store_true",
                           help="istruzioni di configurazione per quella piattaforma")
    providers.add_argument("--lang", default=None, choices=available_locales(),
                           help="lingua delle etichette (default: en)")
    providers.add_argument("--kinds", action="store_true",
                           help="elenca le categorie disponibili")
    providers.set_defaults(func=cmd_providers)

    countries = sub.add_parser("countries", help="elenca o descrive i profili paese")
    countries.add_argument("code", nargs="?", help="codice ISO del paese (es. IT)")
    countries.add_argument("--tax-id", help="verifica una partita IVA / tax id per quel paese")
    countries.set_defaults(func=cmd_countries)

    sub.add_parser("transports", help="elenca i canali di trasmissione").set_defaults(func=cmd_transports)
    renderers = sub.add_parser("renderers", help="descrive i formati documentali disponibili")
    renderers.add_argument("key", nargs="?", help="dettaglio di un formato in JSON")
    renderers.add_argument("--country", help="solo i formati accettati in quel paese (es. FR)")
    renderers.add_argument("--lang", default=None, choices=available_locales(),
                           help="lingua delle etichette (default: en)")
    renderers.set_defaults(func=cmd_renderers)

    sub.add_parser("locales", help="lingue disponibili per le etichette di setup").set_defaults(func=cmd_locales)
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
