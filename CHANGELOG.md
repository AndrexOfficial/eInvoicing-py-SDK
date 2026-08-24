# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] — 2026-08-24

The release that makes the package usable **outside** the applications it grew
in: a portable serialization format, a command line, and the packaging metadata
a standalone distribution needs.

### Added

- **JSON serialization** (`einvoice.serde`) — `invoice_to_dict` /
  `invoice_from_dict` / `invoice_to_json` / `invoice_from_json`. One portable
  shape for the domain model, so an invoice can be a fixture, a queue payload or
  an audit record. Money is carried as strings (never floats) and enums as their
  standard codes (`TD01`, `MP05`, `N2.2`). Decode errors name the offending
  path — `lines[1].unit_price` — instead of failing generically.
- **Command line** (`python -m einvoice`, or the `einvoice` script):
  `validate`, `render`, `totals`, `normalize`, `sign`, `countries`,
  `transports`, `renderers`. Exit codes separate *invalid invoice* (`1`) from
  *invalid command* (`2`) so CI can tell a finding from a typo.
- **`GenericHubTransport`** — a REST intermediary driven entirely by
  configuration (`upload_path`, `content_field`, `auth_scheme`, …). Registered
  for **InfoCert**, **Notartel** and **Wolters Kluwer**, which previously had
  no home in the package. Its status map accepts Italian, English and raw SdI
  vocabulary (`consegnato` / `delivered` / `RC`).
- **`py.typed`** marker (PEP 561), so downstream type-checkers read the
  annotations the package already had.
- Packaging metadata for standalone distribution: trove classifiers, project
  URLs, an `all` extra, ruff + mypy configuration, MIT `LICENSE` file,
  `CONTRIBUTING.md`, CI workflow.

### Changed

- Author metadata is no longer tied to one host application.

### Notes

- No breaking changes: every 0.3.x import path still resolves.
- Test suite grew from 103 to 157 cases.

## [0.3.0]

### Added

- **Country profiles** (`einvoice.countries`) for the EU-27, the UK and the US:
  default standard per seller country, tax-id patterns (VIES VAT, GB VAT reg.,
  US EIN), tax scheme (VAT / sales tax) and per-country validation. The Italian
  constraints (RegimeFiscale, CodiceDestinatario, CAP, Natura) apply only to
  Italian sellers, so one neutral `Invoice` validates everywhere.
- **CAdES `.p7m` signing** (`einvoice.signer`) from a PKCS#12 certificate, and
  **conservation packages** (`einvoice.conservation`) — ZIP + manifest hashes +
  IPdA-like index, with a webhook upload provider.
- **UBL/Peppol BIS 3.0** renderer with a dedicated `CreditNote` root, Peppol EAS
  endpoints per country, VAT categories S/Z/E/AE/K/G/O, and the **XRechnung
  3.0** CIUS for German B2G.
- **Transport layer**: FattureInCloud, Aruba, Zucchetti, Peppol Access Point and
  file export behind one registry, with normalized statuses and notifications.
- **`EInvoiceEngine`** tying validate → render → sign → transmit → archive to a
  unified state machine with an audit trail.

## [0.2.0]

### Added

- Full FatturaPA 1.2.2 code lists: `TipoDocumento` TD01–TD28 (including the
  deferred **TD24**), `Natura` N1–N7 with post-2021 dotted sub-codes,
  `ModalitaPagamento` MP01–MP23, validated `RegimeFiscale`.
- Optional fiscal blocks: ritenuta, bollo virtuale, cassa previdenziale,
  document- and line-level discounts, article codes, accounting periods, VAT
  exigibility, document rounding, art. 73, references (order / contract / DDT /
  linked invoices), attachments.

## [0.1.0]

### Added

- Country-neutral, EN 16931-aligned `Invoice` domain model with exact `Decimal`
  money and VAT summarisation.
- FatturaPA XML builder and SdI file naming (`sdi_filename`, base-36
  progressive).
