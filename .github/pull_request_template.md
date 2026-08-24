## What this changes

<!-- One or two sentences. What behaviour is different afterwards? -->

## Checks

- [ ] `pytest -q` passes
- [ ] `ruff check .` and `mypy` are clean
- [ ] New behaviour has a test that **fails without the change** (revert it, watch it go red)

<!-- If this touches tax data (rates, country profiles, mandates): -->
- [ ] Moved the relevant `*_VERIFIED_AS_OF` date
- [ ] Anything that cannot be stated with confidence is *absent*, not guessed

<!-- If this touches a renderer or parser: -->
- [ ] Round-trip still exact (`tests/test_parsing.py`)
- [ ] Any new format limitation is documented in `docs/PARSING.md`
