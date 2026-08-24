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

## Publishing this as a standalone repository

The directory is already self-contained — `pyproject.toml`, `LICENSE`,
`CHANGELOG.md`, `.gitignore` and `.github/workflows/ci.yml` all live here, and
nothing under `src/` imports anything outside the package. Extracting it is:

```bash
cp -R einvoice/ ../einvoice-standalone && cd ../einvoice-standalone
rm -rf .venv .pytest_cache .ruff_cache dist build *.egg-info
git init && git add . && git commit -m "einvoice 0.4.0"
git remote add origin git@github.com:<you>/einvoice.git
git push -u origin main
```

Then update the four `[project.urls]` entries in `pyproject.toml` to the real
repository, and the CI workflow runs as-is.

To keep history rather than starting fresh, `git subtree split -P einvoice -b einvoice-only`
from the host repo gives a branch containing only this directory's commits.

### The sync obligation

Until it is published and consumed from PyPI, this package is **vendored into
two host repositories** (TableOS and GymOS) and the two copies must stay
byte-identical. A change to one is not done until it is mirrored:

```bash
diff -r --exclude=.venv --exclude=.pytest_cache --exclude=.ruff_cache \
        --exclude=build --exclude='*.egg-info' --exclude=__pycache__ \
        --exclude=uv.lock --exclude=dist TableOS/einvoice GymOS/einvoice
```

That command must print nothing. Divergence here is not hypothetical: before
0.4.0 the two host repos carried *separate* HTTP clients for the same vendors,
and they disagreed about Aruba's auth host and upload path — so at most one of
them could have been correct, and nothing pointed that out.

Once the package is on PyPI both hosts should depend on a version instead, and
this section can go.
