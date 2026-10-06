# beqoptimiser

The `beqoptimiser` Python package and command ship in the single **beqforge** distribution.
They reproduce a published BEQ filter's ideal response more accurately with finite-precision
device coefficients. No audio, device control, designer or capture imports. Python 3.13/3.14,
NumPy and SciPy; the optimiser profile does not install plotting or measurement dependencies.

Install from this checkout:

```bash
pip install '.[optimiser]'
```

Once the distribution is published, beqcatalogue can depend on `beqforge[optimiser]`, retaining
`from beqoptimiser import ...` in its code. A wheel from this repository is installable with
its `optimiser` extra. There is no separate optimiser project, release or version.

## Python API

```python
from beqoptimiser import Float32, Section, Settings, optimise

rate = 48000  # independently repeat at 96000
reference = [Section("PeakingEQ", freq=10, q=2, gain=12).sos(rate)]
result = optimise(
    reference,
    rate=rate,
    precision=Float32(),
    transport=Float32(),
    settings=Settings(margin_db=0.5),
)
if result.replacement is not None:
    # Normalised SOS rows: b0, b1, b2, 1, a1, a2 (subtractive feedback).
    replacement = result.replacement
```

`reference` is the unrounded ideal cascade. Optional `sent` specifies a different original
transport cascade, such as published cached coefficients. Rate is the internal DSP rate;
48 and 96 kHz are supported. The source is never modified. Independent storage and transport
precision models implement `quantise`, `neighbours` and a versioned identifying `name`.
`FixedPoint` supplies a second model for numerical investigation; only float32 has been used
in the initial device-motivated examples. No hardware validity follows from a format name.

The default matching band is 2–200 Hz. The maximum absolute cascade magnitude error must
exceed the configurable 0.5 dB margin before search begins. A replacement is returned only
when its independently evaluated maximum error meets that margin, its outside-band error
meets `guard_margin_db` (also 0.5 dB by default), it is stable, and publication/reloading
preserves its stored coefficients. Guard checks include near-DC, DC and Nyquist.

Outcomes are `within_margin`, `replacement`, `no_replacement` and `unresolved`.
Invalid API inputs raise `ValueError`; the CLI reports unsupported entries individually.
`replacement` is `None` for every unsuccessful outcome, even when a trial improves the
original. Near-boundary numerical uncertainty or disagreement between validation grids
returns `unresolved`. Equality is conceptually inside the margin, but floating-point
estimates within the numerical uncertainty require resolution rather than a replacement.

Search is deterministic, bounded by `passes`, and keeps section count/order. Each section's
five coefficients are searched jointly over neighbouring representable values, scoring the
whole cascade. This is a local search; exhaustion does not prove an acceptable cascade is
impossible. It does not yet refit sections or change topology. Worst errors are estimated
using two independent dense grids with local extremum refinement, not certified mathematical
bounds. Magnitude matching can change phase/transients; there is no phase-preservation claim.
No audio means no soundtrack clipping prediction; the original volume offset is preserved.

## Catalogue adapter and CLI

```python
from beqoptimiser.cli import optimise_entry

report = optimise_entry(authored_entry, rate=96000)
# report["variant"] is None unless a qualifying replacement exists.
```

The adapter accepts common catalogue shelf/PEQ filters, expands counts up to a total of ten
sections, preserves source identity and volume offset, and serialises custom biquads as
17-digit decimal numerator and additive-feedback strings. Complete cached rate-specific
biquads define the original sent baseline; without any cached coefficients it uses RBJ.
Incomplete cached sets and ambiguous channel applicability are rejected.

```bash
beqoptimiser database.json --out optimisation.json
beqoptimiser entry.json --rate 48000 --margin-db 0.5 --out optimisation.json
```

Both rates are processed by default. Outputs are separate reports/optional variants;
original catalogue files are never rewritten. Outputs include snapshot and source digests,
loading model, precision, rate, settings, optimiser version and predicted errors. Nonfinite
CLI diagnostic values are JSON `null`.

The initial variant schema is an integration proposal, not a field already understood by
released ezbeq. beqcatalogue publication and ezbeq selection still need consumer changes.
Do not replace a shared rate-keyed coefficient map for all devices: selection must match
precision, internal rate and loading path. Old consumers must retain authored filters.

## Verification

From the parent checkout:

```bash
uv run --extra optimiser pytest tests/test_optimiser.py
```

Package boundary tests prevent imports between workflows; `tools/smoke_test_install.py`
checks isolated wheel installations for each dependency profile.

Numerical tests cover both rates, margin/fallback policy, cached coefficients, feedback sign,
export round-trip and equivalence with existing RBJ arithmetic. Published catalogue evaluation
and qualified hardware testing remain separate work. The optimiser predicts coefficient
responses; it does not claim that the authored correction suits a film or model float32
recursive processing arithmetic.

The [whole-catalogue report](optimiser-report/README.md) provides checked-in static response
charts, per-rate outcome counts and aggregate error distributions for a pinned catalogue snapshot.
Its source is the [10 September 2026 catalogue snapshot](https://github.com/3ll3d00d/beqcatalogue/blob/43e97a8d349961236b409fec2af7383997183724/docs/database.json),
verified against the SHA-256 recorded in the report.
