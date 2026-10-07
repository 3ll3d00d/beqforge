# Optimiser package

Read the repository [AGENTS.md](../AGENTS.md) first. This guidance also applies to optimiser
scripts, fixtures, tests and the static catalogue report. Commands and repository paths below
are relative to the repository root.

## Scope and contracts

Reproduce a published filter's ideal response using coefficients suitable for the target
representation, without audio or device access. The package imports neutral `beq_common`
primitives, not the designer or measurement workflow. It ships as `beqforge[optimiser]` with
NumPy/SciPy and the separate `beqoptimiser` CLI. There is no separate project or version.

Read [docs/optimiser.md](../docs/optimiser.md) and the
[implementation plan](../plans/F2-catalogue-filter-optimisation.md) before changing numerical
behaviour or publication policy. Catalogue publication and ezbeq loading are downstream
integration concerns; predicting coefficient responses does not prove hardware arithmetic
or soundtrack suitability.

Both 48 and 96 kHz must work independently. Precision models are separate from sample rate;
keep storage and transport configurable so future representations can be added.

Search only when maximum absolute magnitude error exceeds the configured margin (default
0.5 dB over 2–200 Hz). Candidates are assessed over that matching band only: return a
`replacement` when independent validation meets the margin, and an `improvement` when it does
not but is strictly better than the original. Both carry coefficients and must pass the
stability and publication/reload checks; the maintainer chose to publish any genuine
in-band improvement rather than only within-margin results, and to ignore out-of-band error
(still reported as `guard_error_db`). Every other outcome carries `replacement=None`.
Near-boundary uncertainty must remain unresolved. Do not weaken these rules further to raise
published counts. Entry/rate results and distinct improved titles are different counts.

The source cascade, section count/order and original volume offset are preserved. Magnitude
matching does not imply phase preservation. Use the ideal RBJ response as the reference and
complete published rate-specific coefficients as the sent baseline when available; reject
incomplete cached coefficients or ambiguous channel scope. Publication uses 17-digit decimal
strings with additive feedback; internal SOS uses subtractive feedback.

## Layout and cache

| File | Responsibility |
| --- | --- |
| `core.py` | Precision models, deterministic bounded search and independent validation |
| `cache.py` | Public cached optimisation, immutable numerical results and seed lookup |
| `cli.py` | Catalogue preparation, current-entry metadata, variant export and CLI |
| `__init__.py` | Public library exports, including the cached `optimise` wrapper |
| `data/seed.json.gz`, `data/seed-manifest.json` | Bundled numerical results and provenance |

Cache numerical results only: source catalogue identity, title metadata and volume offsets
are rebuilt on every adapter call. Keys must cover coefficients, rate, all settings, precision
configuration, numerical source/version, dependency versions and execution architecture.
Custom precision implementations without a complete explicit `cache_identity()` bypass caching.
Corrupt entries are misses; unwritable storage must not prevent calculation or seed reuse.
Use atomic writes and retain checksums, request identity and publication-policy validation.

Bundled seeds are reusable only in their recorded numerical environment. Changes to numerical
code or settings invalidate them; do not relabel old results as compatible. Rebuild the seed
with `tools/build_optimiser_seed.py` from a committed report's library cache (see
docs/optimiser.md). The historical report-cache importer is `tools/seed_optimiser_cache.py`:
preserve its source/environment checks.
The root build explicitly includes the seed and manifest in wheel and source distribution.

## Running and checking

```bash
uv sync --extra optimiser
uv run --extra optimiser pytest tests/test_optimiser*.py tests/test_package_boundaries.py
uv run --extra optimiser beqoptimiser --help
```

Use `cache=False`, `BEQOPTIMISER_CACHE=0` or CLI `--no-cache` when numerical checks require
fresh calculation. Cover both rates, threshold/fallback policy, precision/transport handling,
feedback sign, export/reload and cache invalidation when changing those behaviours.
Changes confined to this package do not need the designer probe; shared arithmetic changes do.

`tools/optimiser_catalogue_report.py` uses the library cache and generates static charts,
aggregate statistics and per-entry outcomes in `docs/optimiser-report/`. Pin catalogue and
implementation provenance; include unsuccessful cases in aggregates, retaining their original
response when no replacement qualifies. Keep charts and numerical summaries consistent.
