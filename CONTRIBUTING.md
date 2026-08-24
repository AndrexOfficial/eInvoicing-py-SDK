# Contributing

Thanks for helping. This package produces **fiscal documents that tax
authorities reject or accept**, so the bar for correctness is higher than for
ordinary application code — the rules below exist for that reason, not for
style.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # 157 tests, ~1s
ruff check .
mypy
```

## The three rules that matter

### 1. The core stays dependency-free

`models`, `formats`, `countries`, `naming`, `serde`, `lifecycle` and `enums`
must import **nothing outside the standard library**. `httpx` (transports) and
`cryptography` (signing) are optional extras and are imported *inside the
function that uses them*, so a host that only needs XML generation can install
the package anywhere. A top-level `import httpx` anywhere in the core is a bug,
not a cleanup opportunity.

### 2. Money is `Decimal`, always

Never `float`. Not in a calculation, not in a JSON payload, not in a test
fixture. `0.1 + 0.2 != 0.3` is precisely the class of error that makes an
invoice wrong by a cent and gets it rejected downstream. Use the helpers in
`money.py` (`D`, `q2`, `q6`) so rounding is `ROUND_HALF_UP` everywhere, which is
what the Italian rules require.

### 3. Country rules live in country profiles

Italian constraints belong in the `IT` profile in `countries.py`, never in
`models.py` or in a renderer. The whole point of the design is that one neutral
`Invoice` validates for an Italian, German, British or American seller. A
`if country == "IT"` branch outside `countries.py` is a design regression.

## Adding a transport

Subclass `Transport`, implement `transmit` / `fetch_status` (and
`parse_notification` if the provider pushes outcomes), normalize the vendor's
statuses onto the `STATUS_*` constants, and register it in
`transport/registry.py`.

**Before writing a new module, check whether `GenericHubTransport` already
covers it.** Most Italian intermediaries are the same REST shape with different
field names, and configuration beats a module we cannot test against a live
contract. Write a dedicated adapter only when the provider's flow genuinely
differs (multi-step auth, a structured document API rather than an XML upload).

Never commit real credentials or endpoints you have not verified. If an
endpoint is unconfirmed, say so in the module docstring — an honest
`# confirm against your account contract` is worth more than a confident guess.

## Tests

Every change needs a test that **fails without it**. Please check that: revert
your fix, watch the test go red, restore it. A test that passes either way
documents nothing.

- Name what the behaviour *is*, not which function it calls:
  `test_expiry_ends_only_the_expired_session`, not `test_refresh_2`.
- Assert on outcomes a domain expert would recognise — totals, XML elements,
  normalized statuses — not on internal call order.
- For XML, assert on the elements that matter to the standard rather than
  string-comparing whole documents; whole-document snapshots break on
  irrelevant formatting and hide real regressions in the noise.

## Scope

In scope: more country profiles, more renderers (CII, ZUGFeRD), more transports,
sharper validation against published rules.

Out of scope: anything that assumes a specific host application (a database, a
web framework, an ORM). The package is deliberately a library. If a change only
makes sense inside one product, it belongs in that product's integration layer.

## How this SDK is consumed

It is a normal Python dependency, installed from this repository:

```toml
# in the host's pyproject.toml
dependencies = [
    "einvoice @ git+https://github.com/AndrexOfficial/eInvoicing-py-SDK.git@0.4.0",
]
```

Current consumers: **TableOS** and **GymOS** (`backend/pyproject.toml` in each).
Both pin a **release tag, not a branch**. That is deliberate: this package
generates fiscal documents, and `@main` would silently change the bytes a host
transmits to SdI between two builds of the same commit. Moving a pin is an
explicit edit, reviewed like any other — which also means a published tag must
never be force-moved, or you break that guarantee for everyone already on it.

Tags here are bare versions, **without a `v` prefix**: `0.4.0`, not `v0.4.0`.

Hosts building in Docker need **`git`** in the image, or pip cannot resolve a
`git+https` requirement.

### Releasing

1. Land the change here, with tests.
2. Bump `version` in `pyproject.toml` and add a `CHANGELOG.md` entry.
3. Tag it: `git tag 0.4.1 && git push --tags` (no `v` prefix).
4. Update the pin in each consumer's `backend/pyproject.toml`, and run that
   product's test suite before merging — a green suite here does not prove a
   host still works, only that the engine does.

Nothing is vendored into the consumers any more. Earlier, the package lived as a
byte-identical copy inside both host repos, which went exactly as you would
expect: they drifted, and each ended up with a *different* HTTP client for the
same vendors — the two Aruba implementations disagreed about the auth host and
the upload path, so at most one of them could have been correct, and nothing
pointed that out. If you find yourself copying this directory into an
application, that is the failure you are signing up for.

### Publishing to PyPI

Not published yet. When it is, consumers should depend on a version specifier
(`einvoice>=0.4,<0.5`) instead of a git URL, and the pinning discussion above
becomes ordinary dependency resolution.
