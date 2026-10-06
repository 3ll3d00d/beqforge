# Device-specific optimisation of published catalogue filters

Design plan, 2026-10-05; initial numerical implementation, 2026-10-06. Status: library/CLI implemented in the shared beqforge distribution; catalogue publication, ezbeq selection and hardware validation open.
Tracked under F2 in [TODO.md](../TODO.md), alongside the separate
[device measurement work](F2-device-precision-validation.md).
The [distribution consolidation outcome](F2-package-consolidation.md) records the final
single-project packaging and independent workflow boundaries.

## Purpose and scope

Given a published BEQ cascade and a named device representation, produce a replacement
whose realised response more closely reproduces the original ideal filter response.
The catalogue filter is the reference for this task. No soundtrack, extraction, diagnosis,
evidence ceiling or judgement of whether the authored BEQ suits the film is involved.
This does not change the rule that catalogue filters are never targets for the audio-derived
designer pipeline.

The replacement is specific to internal sample rate, coefficient storage, transport and
loading path. Support both 48 kHz and 96 kHz in the initial implementation, with float32
coefficient storage. Optimise and validate each rate independently; coefficients and success
at one rate cannot be transferred to the other. The measured miniDSP 2x4 HD pilot motivates
the 96 kHz model, but does not establish hardware agreement at 48 kHz.
Design storage precision as an extensible specification, separate from rate and transport:
initial float32 support, with later floating-point and fixed-point formats implementing the
same conversion, representable-neighbour, range and stability-validation contracts. Include
format parameters, rounding rules and model version in provenance and cache identity;
search code must not hard-code float32 ULP operations for every format.
Coefficient-response predictions and time-domain arithmetic simulations must remain
separately labelled; SciPy float32 filtering is not an implementation model of the hardware.

Intended delivery is an independent Python package within the single beqforge distribution,
installed by beqcatalogue with the `optimiser` dependency profile during catalogue generation. beqcatalogue publishes device-specific optimised variants;
ezbeq selects the appropriate variant and loads it onto the target device. A CLI exposes
the same library for development and validation; device-check verifies the resulting frozen
cascades. First implement and validate one entry offline, then a pinned catalogue snapshot,
before integrating publication and loading. This planning work does not authorise automatic
publication or loading a live device.

## beqcatalogue and ezbeq integration

Local source inspection on 2026-10-05 confirms:

* beqcatalogue's `beqcatalogue/iir.py:to_map` publishes parameters plus a `biquads` mapping
  keyed by sample rate, with numerator `b` and additive-feedback `a` coefficient strings.
* ezbeq's `ezbeq/minidsp.py:MinidspBeqCommandGenerator.as_bq` uses those published
  coefficients when the descriptor's sample rate is present; otherwise it regenerates
  RBJ coefficients from the parameters. Its 2x4 HD descriptor specifies 96 kHz.

This makes direct coefficient optimisation a supported candidate for the intended miniDSP
loading path; it need not wait for evidence that parameter tweaks fail. Benchmark both
approaches before choosing the initial production mode.

Do not replace the original `filters[*].biquads['96000']` indiscriminately: the existing
lookup distinguishes rates, not storage formats or validated device behaviour. Retain the
authored `filters` and their coefficients, and add a versioned, optional entry-level variant
collection. Final field names and schema must be agreed in the two consumer repositories.
Each variant identifies its target profile, internal rate, transport/storage formats,
loading model version, full ordered cascade, source digest, optimiser version/settings and
before/after validation metrics. Keep the original volume offset and author attribution.

ezbeq selects a variant only for an explicitly supported descriptor/loading path, using
its internal DSP rate rather than incoming audio rate, and checks section capacity and
schema support. A missing, stale or unsupported variant falls back to the authored filter.
Old ezbeq versions continue using authored `filters`. Initially require explicit opt-in to
variant selection until publication and device validation are complete. Composite devices
resolve variants per child device; one device's coefficients cannot be reused indiscriminately.

The variant's stored coefficients are authoritative for custom-coefficient output. Do not
regenerate them from provenance parameters. Expand repeated section counts in variants so
each section may be optimised independently. Rebuild catalogue digests/versioning according
to the existing catalogue update contract so ezbeq refreshes changed publication content;
retain a separate digest of the unoptimised source to detect stale variants.

Test catalogue serialisation through ezbeq parsing, selection and generated miniDSP commands,
then transport float conversion, against the optimiser's predicted stored coefficient bits.
Verify rate mismatch, unsupported devices, original fallback, counts, feedback sign, offsets
and slot capacity. Catalogue/API views that omit coefficients continue showing authored
parameters; any view presenting an optimised response must evaluate the selected coefficients.

## Reference and loading contract

1. Preserve source bytes, revision, attribution, entry identity, section order, repeated
   section counts and volume offset. Never overwrite a source snapshot or F2 baseline.
2. Where published frequency/Q/gain parameters exist, render their RBJ cascade in high
   precision at the selected device rate. This is the ideal target, without rounding the
   source parameters to beqforge's publication precision.
3. Compute the original realised baseline from the coefficients the selected loader would
   actually send: published rate-specific biquads where applicable, otherwise regenerated
   RBJ coefficients, followed by transport and storage conversion. Record the choice.
   Incomplete cached coefficient sets require an explicit loading policy, not an assumed
   mixture of cached and regenerated sections.
4. If only coefficients exist, they define the reference at their declared rate. An already
   rounded set cannot reveal its pre-rounding intention. Report that limitation and do
   not describe matching that reference as recovery of unpublished author intent.
5. Reject unknown rates/formats, malformed or unsupported sections, ambiguous channel
   applicability, nonfinite values and unstable ideal references. An original cascade
   unstable after storage may be investigated for repair, but cannot be a usable fallback.
6. Freeze the export contract before searching: accepted filter types, section budget,
   parameter decimal precision, coefficient text precision, feedback convention and whether
   the consumer honours custom coefficients or regenerates them. Optimise what is reloadable.

Existing `catalogue.import_snapshot` and `coefficients` supply most of the decoding and
prediction primitives. Audit importer validation and cached-coefficient selection against
the actual chosen loading path before reuse. Preserve its current measurement semantics.

## Objective and constraints

The public API and CLI expose `margin_db`, default **0.5 dB**, finite and strictly positive.
It is the maximum permitted absolute error against the original ideal response over the
declared matching band, not RMS error, improvement amount or per-section error.

Apply the following policy independently for each rate/device representation:

* Validate the original realised response first. If its maximum absolute error is at or
  below `margin_db`, return `within_margin`, without searching or providing an alternative.
* Only search for alternatives when the original maximum absolute error exceeds the margin.
* Return a replacement only if its independently validated, exported/reloaded maximum
  absolute error is at or below the same margin and every other constraint passes.
* An improvement that still exceeds the margin returns `no_replacement`, with diagnostics
  and no replacement filter in the public result or published variant. Search exhaustion
  does not establish that a qualifying replacement is impossible.

Equality belongs to the within-margin case. Numerical validation must resolve the boundary;
if numerical uncertainty straddles it, refine evaluation or return unresolved, rather than
rounding a displayed error into eligibility. Diagnostic trial records may retain unsuccessful
coefficients, but they must not appear as consumable alternatives or replacement exports.

For original ideal response H_ref and candidate response H_play after export, reload,
transport and storage conversion, minimise:

    E_inf = max_f |20 log10(|H_play(f)| / |H_ref(f)|)|

Score the complete cascade, not independent section errors. A candidate may intentionally
have a different unrounded response if rounding brings playback closer to the reference.
This differs from the current designer fitter's maximum of ideal-target error and device
drift; reusing that objective unchanged would solve a different problem.

Use the existing 2–200 Hz prediction band for directly comparable first experiments.
Declare that scope. Include a guard band outside it, sampling through the remaining
usable frequency range up to below Nyquist, plus analytic DC and Nyquist limits where
finite. A user may request a wider matching band, including below 2 Hz; there is no claim
of preservation outside the evaluated range. Do not conceal a low-frequency peak below
the scoring floor or a change above 200 Hz.

Start with a dense logarithmic grid, insert section corners and resonance neighbourhoods,
then refine around local error extrema. Validate finalists on a separate denser grid and
refine maxima until their value converges within a predeclared numerical tolerance.
Discrete samples are empirical verification, not a mathematical uniform-error bound.
Handle zeros and nonfinite dB ratios explicitly rather than silently clipping them.

Hard constraints:

* Every exported/stored section is stable; report pole radius and settling time. Freeze a
  permitted settling-time/stability-margin policy before evaluation, tied to the use case.
* Obey the actual device's section capacity, coefficient range and supported export schema.
* Freeze allowable guard-band departure before search; a bass improvement cannot excuse
  an unreported change elsewhere.
* Preserve the source volume offset. Report cascade peak gain and any increase separately;
  without audio, no soundtrack clipping prediction is available.

Use worst error as the primary score. Within a declared tie tolerance prefer lower RMS
error, then the simpler/less changed candidate. Report signed error, its frequency, RMS,
phase departure, section count, stability and settling time. Magnitude matching alone
does not guarantee preservation of phase, transients or intermediate section headroom.
For parameter tweaks, record phase changes; before allowing structural refits, decide
whether complex-response matching or explicit phase constraints are required.

## Search stages

Always include the original as a candidate when usable. Every stage has a fixed evaluation
budget, deterministic seeds, recorded bounds and a timeout outcome; lack of convergence
does not imply that no better representation exists.

### A. Parameter tweaks — first implementation

Keep section types, count and order. Search nearby frequency, Q and gain values in the
consumer's export precision. Begin with a local discrete neighbourhood of the source,
then bounded multistart search if needed. Freeze neighbourhood bounds before the benchmark;
report when they bind. Rounding produces flat regions and discontinuities, so do not rely
on gradients or a continuous optimiser's residual alone.

Evaluate candidates after the actual serialisation/reload path. A cached coefficient set
must be regenerated or removed consistently with changed parameters; stale cached biquads
must never accompany an apparently optimised parameter set.

### B. Direct coefficient search — conditional second stage

For consumers accepting custom biquads, search neighbouring representable float32 values
using ULP steps, with a0 fixed at one. Use stability-aware coordinate/block moves over
numerator and denominator coefficients; evaluate cascade interactions. A naive exhaustive
Cartesian search over five coefficients per section is not practical.

Validate exact text round-trip and additive-feedback conversion. Export as custom
coefficients with source parameters retained only as provenance: the result may no longer
be exactly representable as an RBJ shelf or PEQ. Never emit misleading frequency/Q/gain
metadata implying that regenerating RBJ coefficients reproduces it.

### C. Cascade refit — research escalation

Only if A/B leave materially degraded cases, refit the original curve with alternative
section parameters/types and, within hardware capacity, additional sections. Use the
source as a warm start. Resolve phase policy first, evaluate intermediate amplification
and cancellation, and benchmark cost and quality against A/B. This is a separate outcome
from a small tweak; no initial commitment to extra sections or the designer's fitter.

Section reordering does not improve coefficient-only transfer error. Investigate it only
as a separately measured arithmetic/headroom effect.

## Architecture and artefacts

Keep the feature outside `beqforge.pipeline` in the top-level `beqoptimiser` package of
one published distribution, `beqforge`. Its optional `optimiser` profile supplies SciPy,
alongside the common NumPy dependency, without plotting or capture dependencies. The
`designer`, `device-check` and aggregate `all` profiles support the other concrete use cases.
Each workflow has its own CLI and imports no sibling workflow package. Shared rate-independent
types, RBJ arithmetic and publication precision live in `beq_common`, beneath all workflows.
One root pyproject, lockfile and version govern releases. Python 3.13/3.14 matches the
current beqcatalogue consumer requirement checked during implementation.

Expose a pure single-cascade API accepting original parameters or coefficient reference,
device/loading specification and optimisation settings, returning a typed result with
exportable coefficients, metrics, provenance and outcome. Batch/catalogue schema adaptation
belongs to beqcatalogue or a separate adapter, not the numerical API. Proposed module split:
input/result types, RBJ/reference arithmetic, loading model, search and independent validation.
Use the shared primitive package; the optimiser cannot import the designer's internal modules. Check numerical equivalence
against existing catalogue, ezbeq and device-check arithmetic and decimal formatting.

beqcatalogue calls the library at build time, ezbeq loads published results without running
optimisation, and device-check consumes exact exported cascades for prediction and measurement.
The CLI calls the same public API. Avoid separate optimisers in any of the three applications.

The existing frozen measurement manifests remain immutable. The optimiser creates a new
manifest for the replacement, linked to the original, so device-check can measure both.
Do not change catalogue prediction to silently substitute optimised filters.

Proposed CLI surface, to finalise with stage A:

    <optimiser-cli> catalogue-optimise --catalogue snapshot.json \
        --revision REV --attribution SOURCE --entry ENTRY_ID \
        --config bench.json --mode parameters --out optimised/

Batch mode is explicit and deduplicates identical optimisation requests. Cache identity
includes source ideal/transport cascades, rate, loading/export model, constraints, score
grids, search settings and implementation version. Reassociate results with every source
entry, reporting both entry-weighted and unique-cascade distributions.

Write versioned JSON provenance/results, original and replacement coefficient exports,
replacement measurement manifest, CSV and HTML showing ideal, original realised and
replacement realised curves plus signed error. Include exact exported bytes and hashes.
Outcomes: `within_margin`, `replacement`, `no_replacement`, `unresolved`, `unsupported`.
The public replacement field is populated only for `replacement`; catalogue variants and
replacement coefficient exports are emitted only for that outcome. Record the requested
margin and both maximum errors. Retain the original when usable for every other outcome,
report the reason, and retain failed trials only in the diagnostic audit record.

## Validation and implementation sequence

1. **Freeze protocol and source.** Pin a catalogue snapshot and selected loading contract.
   Predeclare matching/guard bands, tolerances, budgets, constraints and held-out evaluation
   partition. Split by unique cascade so duplicated entries do not leak between development
   and evaluation. Catalogue scoring here measures filter reproduction, not BEQ correctness.
2. **Baseline and scorer.** Reproduce existing float32 catalogue predictions; test source
   parameters versus cached coefficients, repeated sections, offsets and export round-trip.
   Use identity, ordinary shelves/peaks, the measured 5 Hz Q 6 case, opposing sections,
   already accurate filters, unstable rounded filters and extrema between grid points.
3. **Stage A prototype.** Demonstrate improvement on predeclared difficult cases, no
   recommended regression on accurate controls, deterministic output and graceful budget
   exhaustion. Compare source and replacement on the independent validation grid.
   Exercise both 48 and 96 kHz, including a case qualifying at only one rate. Test original
   error below, equal to and above 0.5 dB; replacement error below, equal to and above it;
   configurable margins; near-boundary numerical uncertainty; no search for within-margin
   originals; and no public alternative/export for improved but out-of-margin trials.
   Test the format interface with an additional precision model to expose float32-specific
   assumptions, without claiming that model is production- or hardware-validated.
4. **Catalogue evaluation.** Freeze the search configuration before running the held-out
   partition. Report before/after worst-error distributions, counts meeting a declared
   0.5 dB default margin at each rate (report the existing bench's 0.1 dB criterion separately), unchanged and
   unresolved cases, cost and constraint failures. Inspect every recommended replacement
   with unexpected shape, phase or settling behaviour. Do not tune on held-out outcomes.
5. **Stage B decision.** Implement only if the selected consumer supports custom biquads
   and A leaves demonstrated failures. Compare A and B under the same frozen protocol.
6. **Arithmetic controls.** Run frozen original/replacement pairs through float64 and
   float32 time-domain simulations at multiple levels, with settling tails and zero-input
   checks. Separate coefficient error from arithmetic residuals; evaluate ordering and
   intermediate headroom where the simulation permits. These are software controls.
7. **Hardware verification.** Freeze pairs, use qualified bench settings and the existing
   device-check lifecycle. Measure a stratified sample plus the largest improvements and
   fragile cases, identities and both levels. Compare measured playback with each stored
   coefficient prediction and with the original ideal reference, including uncertainty.
   An unresolvable bench result stays unresolved. Hardware agreement supports only that
   named model/rate/loading path, not every 32-bit DSP.
8. **Publication and loading integration.** Add beqcatalogue's build-time dependency and
   optional variant generation, then ezbeq selection/command integration with end-to-end
   tests. Establish deterministic regeneration, cache invalidation and catalogue refresh
   behaviour. Validate generated commands and measure a selected pair loaded through ezbeq.
   Prepare reviewable publication artefacts before any requested live publication.
9. **Document delivery.** Add library/CLI usage, variant schema and consumer examples,
   record measured outcomes here and update TODO status. Ship offline recommendations first,
   then the validated opt-in catalogue-to-ezbeq path.

Run the full test suite and relevant lint checks for implementation. Changes confined to
device-check need no designer probe. If shared `beqforge/` arithmetic or fitting changes,
follow AGENTS.md's probe/refit and regression requirements before committing those changes.

Completion means reproducible single-entry and batch optimisation, export round-trip
verification, independent before/after scoring with fallback, immutable source provenance,
and measured validation outcomes with scope stated. Numerical delivery may precede hardware
verification, but must be labelled predicted rather than hardware-validated.

## Initial implementation outcome — 2026-10-06

The initial `packages/beqoptimiser` subproject was superseded by the consolidated distribution
layout below. The numerical API depends only on NumPy/SciPy. Its API accepts ideal and optionally distinct sent SOS,
internal rate, storage/transport precision models and configurable settings. Its CLI and
catalogue-entry adapter emit separate reports and optional custom-coefficient variants,
with source/snapshot fingerprints, version, settings and loading-model provenance. The
original catalogue is not rewritten. Initial section capacity is ten for the adapter.

Implemented direct coefficient search first because the intended ezbeq miniDSP path already
accepts custom coefficients. Search is deterministic and bounded, jointly checking the five
coefficients of each section over neighbouring representable values, scoring the cascade.
Float32 and fixed-point precision implementations share a protocol; fixed point is a
numerical extensibility control, not a new hardware qualification. Parameter search,
structural refits, cross-entry deduplication/cache, HTML and measurement-manifest adapters
remain open. No shared `beqforge/` code or designer decisions changed, so no designer probe
was required.

The margin policy skips search for an already adequate original and emits no replacement
for partial improvements outside the margin. Two independent validation grids plus extremum
refinement check error convergence; numerical boundary uncertainty returns unresolved.
Replacement validation also checks the outside-band response including DC/Nyquist, stability
and coefficient round-trip through 17-digit decimal export, transport and storage.
These checks are numerical estimates rather than a proof of a uniform error bound.

31 targeted tests passed, including RBJ equivalence, both rates, independent rate
outcomes, no-search/failed-search policy, configurable margin and boundary uncertainty,
guard rejection, an additional precision model, input validation, source preservation,
cached coefficients, repeated sections, deterministic output, candidate boundary cases,
source-overwrite protection and additive-feedback export. A wheel was built and installed into a
scratch directory without importing beqforge. Numerical examples, +12 dB peaks:

| Internal rate | Frequency / Q | Original maximum error | Trial maximum error | Outcome at 0.5 dB |
| --- | --- | --- | --- | --- |
| 48 kHz | 10 Hz / 2 | 0.7463 dB | 0.1485 dB | replacement |
| 96 kHz | 10 Hz / 0.7 | 0.8486 dB | 0.1989 dB | replacement |
| 48 kHz | 5 Hz / 6 | 2.7195 dB | 1.2177 dB | no replacement |
| 96 kHz | 5 Hz / 6 | 18.8439 dB | 4.7562 dB | no replacement |

These development examples demonstrate the policy and some local-search benefit, not a
held-out catalogue success rate or hardware accuracy. Next: agree the variant/profile
contract in beqcatalogue and ezbeq, freeze catalogue evaluation, and verify selected original
and replacement pairs through the real loading path. No catalogue content was published
and no live device was loaded.

A development smoke run used the local 15,323-entry catalogue, selecting 16 evenly spaced
ordinals (`i * (n - 1) // 15`, i = 0..15) before inspecting their errors. Input file SHA-256:
`e63ff69e4bf82f74d10fc503979f70c4e2a525f97512ff0dfcb91f875becc9e8`;
local catalogue checkout revision `f398ffd380d1dc9bb14d848f7d0d3e6a590ade0e` (the content
hash, not that revision alone, identifies the generated database). Using the installed
wheel, default search settings and 0.5 dB matching/guard margins:

| Rate | Already within margin, no search | Qualifying replacements | No replacement |
| --- | --- | --- | --- |
| 48 kHz | 8 | 8 | 0 |
| 96 kHz | 3 | 10 | 3 |

This small deterministic development sample is an integration smoke check, not the frozen
held-out protocol or an estimate of population success. No failed trial was exported as a
variant. Scratch input/results were written under `/tmp`, preserving the catalogue source.

The existing repository suite produced 680 passes and two skips in the sandbox; all 17
failures/errors were localhost socket or uv cache restrictions. Rerunning those 17 with
the required access passed, giving 697 existing tests passed and two skipped overall.
Package lint/format and documentation whitespace checks passed. The root pytest configuration collects optimiser tests alongside the existing suite.

## Whole-catalogue static report — 2026-10-06

[The checked-in report](../docs/optimiser-report/README.md) evaluates every entry in the
15,323-entry snapshot, at both 48 and 96 kHz, using the default float32 transport/storage,
0.5 dB matching/guard margins and six search passes. The source SHA-256 is the same as the
smoke snapshot above; it matches `docs/database.json` at catalogue commit
`43e97a8d349961236b409fec2af7383997183724` (2026-09-10). The report records source/settings
and dependency fingerprints, compressed entry/rate outcomes, aggregate frequency statistics,
and four static PNGs. Root README and optimiser usage link to it.

| Rate | Within margin | Qualifying replacements | Search yielded no replacement | Unsupported |
| --- | ---: | ---: | ---: | ---: |
| 48 kHz | 10,584 | 4,573 | 114 | 52 |
| 96 kHz | 2,499 | 10,400 | 2,372 | 52 |

There were no unresolved results. The 52 unsupported entries have no published filters.
Overall, 11,871 entries, representing 8,596 of 10,511 title identities, qualify at one or
both rates. Title identity explicitly includes title, year, content type, season and
episode; separate formats/editions/authors still count as catalogue entries. The 14,973
rate-specific replacements must not be mistaken for unique improved entries.

The frequency aggregates weight each entry once per rate, retaining original coefficients
where no qualifying replacement exists. Two unstable/nonfinite original cascades at 48 kHz
and three at 96 kHz are counted separately and excluded from paired finite-curve percentiles.
One of those unstable originals (`I Am Number Four`, 96 kHz) gains a stable qualifying
replacement. The 2–5 Hz median sampled band-maximum error falls from 0.253 to 0.117 dB at
48 kHz and from 1.056 to 0.176 dB at 96 kHz. Unsolved originals retain the worst-case tail:
the 96 kHz 2–5 Hz maximum remains 16.632 dB. The report also includes pointwise median,
95th/99th percentiles and maxima, and six band tables through 200 Hz.

Examples were selected mechanically as the two distinct title identities with the highest
finite original error among qualifying repairs: `Breaking` (2022), 96 kHz, 12.766 → 0.318 dB;
and `Tracers` (2015), 96 kHz, 12.653 → 0.418 dB. Each example also shows its 48 kHz curves.
These are successful examples; failed searches remain in all aggregate results.

`tools/optimiser_catalogue_report.py` resumes from an external cache and deduplicates identical
filter/load requests (29,320 distinct requests for 30,646 entry/rate evaluations). Its bounded
per-section search-response cache preserves the core's arithmetic and summation order;
independent eligibility validation uses the unchanged library response calculation. Exact
response/worker comparisons, publication-retention checks and whole-report coverage tests
passed: 47 focused tests, plus new-file Ruff and whitespace checks. The full numerical search
took 4,407 seconds under the sleep inhibitor; chart/statistics rendering followed. No designer
or shared arithmetic implementation changed for this report, so no designer probe was needed.
Catalogue/ezbeq integration and hardware checks remain the next work.

### Automatic library cache and bundled seed (6 October 2026)

`beqoptimiser.optimise` and the catalogue adapter now share an automatic result cache.
Numerical request keys cover coefficients, sample rate, complete settings and precision
configuration, numerical source/version, dependency versions and execution architecture.
Catalogue identity and volume offset are regenerated on every adapter call. Atomic writes,
checksums and publication-policy validation permit safe concurrent reuse; invalid entries
are misses, unavailable cache storage does not prevent calculation, and custom precisions
without an explicit implementation/configuration identity bypass caching.

The historical report cache was imported after verifying the catalogue fingerprint, archived
report implementation and unchanged numerical core. The installed distribution includes
29,268 distinct numerical results covering 30,542 supported entry/rate cases; 104 cases have
no filters. The seed is scoped to its recorded Linux x86_64 / NumPy 2.4.2 / SciPy 1.18.1
numerical environment. Other environments calculate and populate their own cache.

A full replay of all supported cases matched the historical numerical reports and replacement
coefficients with zero core optimiser calls, including fresh per-entry publication identities
and volume offsets. It took 10.75 seconds with the sleep inhibitor held. The 71 focused
optimiser, report, cache and package-boundary tests passed, as did Ruff, whitespace checks and
a fresh offline installation of the built optimiser wheel, including bundled-seed reuse.
The wheel and source distribution explicitly include the seed and provenance manifest.
No designer or shared numerical implementation changed, so no designer probe was required.
