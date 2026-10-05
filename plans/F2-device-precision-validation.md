# F2: measuring device coefficient precision and arithmetic

Experiment plan, 2026-09-30; implementation preview updated 2026-10-02. Hardware execution
and any change to device assumptions remain open in [TODO.md](../TODO.md). Implementation
and numerical/software-control outcomes are recorded below; no hardware precision conclusion,
fitter, acceptance rule or Q limit is changed.

## Question and scope

Does a published BEQ cascade play the response predicted by beqforge on a named device?
Separate publication rounding, coefficient transport/storage and recursive DSP arithmetic.
Then ask whether the current model is useful for predicting error, and whether the historical
Q 5.2–6.0 restriction is supported by measurements. A sweep measures a transfer function;
it cannot alone establish internal word length or rule out noise and limit cycles.

The first experiment uses minidsp-rs to load exact biquad coefficients into a miniDSP and
a Python sounddevice/pyfar backend to sweep an electrical loopback. REW remains an optional
independent measurement cross-check. Repeat the same cases through CamillaDSP and JRiver
on the same host, with their own identity references. Double-precision software is a control
and another engine to validate, not proof of hardware behaviour.

Prototype under `tools/experiments/`, then ship a separate `beqforge-device-check` executable
with importable harness modules in a dedicated package, separate from `pipeline.run` and the
designer server. The existing wheel excludes `tools/experiments/`, so a distributable entry
point must not depend on that directory. Hardware and proprietary applications must not become dependencies
of ordinary design runs or CI.

## Interfaces and feasibility

[minidsp-rs PEQ commands](https://minidsp-rs.pages.dev/cli/input/peq) support coefficient
loading; importing to `all` clears unused slots and unbypasses imported PEQs. Its
[HTTP API](https://minidsp-rs.pages.dev/daemon/http) supports indexed coefficient updates and
device discovery. Prefer the CLI for the first implementation; pin its release and explicitly
select the device rather than relying on discovery order. Confirm the actual model's support,
section capacity and coefficient sign convention in a one-section pilot. Neither successful
loading nor master-status readback proves the stored coefficient bits.

The [REW API](https://www.roomeqwizard.com/help/help_en-GB/html/api.html) requires Pro for
automated sweeps. Archive the installed `/doc.json`. Use `/audio`, `/measure/sweep/configuration`
and `/measure/command`; match asynchronous command IDs to results and measurements by UUID.
Retrieve unsmoothed `/measurements/:id/frequency-response` and unnormalised impulse data.
Arrays are Base64 big-endian float32; reconstruct the returned frequency axis. Avoid forced
PPO resampling, which adds smoothing. Use bounded polling rather than long blocking requests.

[CamillaDSP documentation](https://github.com/HEnquist/camilladsp) describes default float64
processing, an optional float32 build and configuration updates through its websocket server.
Pin the build and precision. Prefer explicit coefficient loading and capture the active config.
JRiver control/import and its installed version's DSP precision remain feasibility tasks:
confirm a repeatable filter-load and playback route before promising fully unattended runs.
A 64-bit application or PCM container is not evidence of double-precision DSP. Manual loading
with a recorded acknowledgement is an acceptable pilot, but not an unattended batch backend.

## Bench setup and qualification

Record miniDSP model/serial/firmware/plugin, active preset, physical input/output, internal DSP
rate, host OS, drivers, interface model, transport rates, gains and every enabled processing
stage. A REW capture rate is not necessarily the device's internal rate. Record format claims
as documented, inferred or unknown; do not assume every miniDSP uses 5.23 fixed point.

Use an electrical path with loudspeakers/amplifiers disconnected (the source is the Python
backend by default; REW can occupy the same position):

`measurement output -> device input -> one device output -> interface line input -> capture`.

Prefer digital input/output where the chosen model permits it. Otherwise use line-level
conversion, measure its low-frequency floor, and retain that limitation. USB control does not
imply a USB audio return. Disable Dirac, room EQ, crossovers, compressors, bass management,
resampling and OS enhancements where possible; document unavoidable stages. Use one route,
fixed gains and a common clock where available. A second reference channel can track timing
and drift if the interface supports it. Confirm it does not bypass the intended DUT route.

Qualification precedes the filter matrix:

1. Measure direct interface loopback, device bypass, and active identity sections separately.
   An identity cascade preserves the active processing route and slot count; bypass may differ.
2. Repeat identities at least five times, across reloads and the proposed signal levels.
   Estimate frequency-dependent repeatability, noise floor, clock drift and gain stability.
3. Choose sweep duration and IR windows from the lowest tested frequency and slowest pole
   decay; lengthen until the result converges. Disable frequency-dependent windowing and
   preserve low-frequency tails. Start with 2–200 Hz, but qualify rather than assume 2 Hz
   is measurable. Include a wider diagnostic sweep to catch wrong rates/signs/routing.
4. Choose a fixed input level for each block from the worst case's internal/intermediate and
   output gain, not just its final response. Pilot nominal levels of −30 and −50 dBFS,
   reducing them as needed. Reject clipping, dropouts or under-range measurements.
5. Freeze the valid band and a frequency-dependent uncertainty budget before the main run.
   If the bench cannot resolve the predicted effect, improve it or mark the case unresolved.
   A ratio cannot recover information below the capture floor.

For software use `measurement output -> virtual input -> engine -> capture`, then optionally repeat through
the same physical interface. Each route gets its own identities. Confirm capture is after DSP
with a conspicuous pilot filter. Record virtual PCM width, output quantisation/dither, latency,
resampling and engine rate. File-in/file-out processing is useful as an additional numerical
control where supported; do not substitute it for the live path without naming that scope.

## Cases: a versioned manifest of n cascades

Generate predictions and freeze coefficients before connecting to the device. Preserve both
continuous parameters and canonical `publication_filters` output; normal operation loads the
published version. Do not refit between engines or silently clamp unsupported parameters.

| Family | Purpose |
| --- | --- |
| Identity and a moderate, easily measured peak | Routing, gain, feedback sign and rate controls |
| Single low shelves and peaks at 5, 10, 15, 20, 30 and 60 Hz | Cancellation near DC and frequency dependence |
| Q 0.707, 2, 5.2, 6.0 and selected unconstrained fits above 6 | Separate Q from coefficient sensitivity |
| One through four sections, constructive and opposing gain | Cascade dependence and intermediate headroom |
| Published baseline cascades, spanning low and high predicted drift | Relevance to real designs, without treating titles as truth |
| Exact, float32-rounded and 5.23-rounded coefficients where loadable | Distinguish candidate storage models and transport precision |
| Selected cases with reversed section order | Arithmetic/state sensitivity despite identical ideal transfer |

These values are experimental coverage, not per-title decision bands or proposed limits.
Select signed gains within actual device range, including representative BEQ boosts. Keep
stress cases distinct from publishable cases. Screen stability after every candidate rounding
and transport representation; omit unstable loads with a recorded reason. Near-boundary
coefficient cases are useful only if the transport can represent the difference.

Run 48/96 kHz comparisons only on engines that actually support different internal rates.
Changing the input/capture rate of a fixed-rate device does not test this hypothesis. Coefficient
precision and sample arithmetic are separate: float32-rounded coefficients processed in
float64 are a storage control, not a simulation of float32 recursive arithmetic.

Start with identity, one benign section and one strongly precision-sensitive stable section.
After this pilot, freeze the expanded manifest, its n, levels, repeats and random seed. Run
at least three independently loaded repeats per case/level, with randomised case order and
bracketing identities. Estimate runtime from the pilot including settling and noise captures.

## Transaction for each case

1. Persist the planned case and recoverable device state. Mute during loading; select the test
   preset, clear every unused slot, set routing/gains and load all sections in the stated order.
2. Check load results and available readback. Store the sent text/payload, numerical coefficients
   and any actual readback separately. If readback is unavailable, label storage unverified.
3. Unmute and wait a bounded settling interval derived from pole decay and confirmed by pilot.
   Run the sweep; correlate the command result and UUID, check warnings/levels, and save the
   raw response, IR and measurement file before advancing.
4. For designated cases run the noise/ring-out protocol below. Reload for independent repeats.
5. Measure another identity at the scheduled bracket. Abort a block on drift or failed quality
   checks, retaining partial evidence. Do not automatically retry a timed-out sweep while the
   old command might still be active.

Use explicit states, finite timeouts, a run lock and append-only completion records. Resume
only after re-establishing the recorded device state and remeasuring identity. Restore the
saved configuration on completion/failure where possible; if restoration cannot be verified,
report the remaining state and leave the output muted. Archive REW settings too. No blanket
deletion of existing REW measurements.

## Comparison: remove the bench, then test the prediction

Let `M_i(f)` be the measured complex response with case i and `M_0(f)` the matching active
identity through the same path, gain and rate. From bracketing references estimate a stable
baseline and its uncertainty; retain both brackets so drift is visible.

`H_measured = M_i / M_0`

`delta_exact_db = 20 log10 |H_measured / H_exact|`

`delta_stored_db = 20 log10 |H_measured / H_stored|`

`predicted_quantisation_db = 20 log10 |H_stored / H_exact|`

Thus `delta_exact_db = predicted_quantisation_db + delta_stored_db`.
Compute `H_exact` from the published cascade at the actual engine rate and `H_stored` from
verified stored coefficients, or explicitly labelled candidate models when storage is unknown.
Also evaluate `H_sent`, after text serialisation and control-transport conversion, to locate
error before the device. Compare pre-publication parameters separately; parameter rounding
must not be attributed to coefficient storage.

Evaluate predictions at native measured frequencies, with sufficient numerical precision for
near-DC cancellation, and retain phase/complex residuals. Align only independently determined
transport delay; preserve filter phase. Do not fit away gain offsets or low-frequency trends.
Report unknown latency as a phase limitation if no trustworthy timing reference exists.
Mask bins failing qualification or output SNR; never divide by a noise-dominated identity or
stopband and present it as precision error.

Per case report signed residual curves, worst absolute error and its frequency, RMS error on
a declared log-frequency weighting, contiguous excursions, phase residual, repeat spread,
valid-band coverage and predicted versus observed error. Retain individual traces rather than
only an averaged curve. A hardware residual includes arithmetic, transport and bench error;
a better-fitting storage model alone does not uniquely identify internal arithmetic.

## Arithmetic, noise and limit cycles

For selected benign, high-Q and cancelling cases, acquire native-rate time-domain captures:

* True digital zero where possible, before excitation and after a sweep/burst ring-out.
* Low-level tones at sensitive frequencies, at multiple levels; compare gain, distortion and
  residual noise after sufficient settling.
* A finite burst followed by a long zero segment, repeated with fresh state and without reset.
* Optional controlled dither as a paired experiment, recording its amplitude and placement.

Emit exact zero samples from the Python backend. For optional REW measurements, disable
silence-filling dither for zero-input tests. Check whether the driver/engine adds dither, noise or automatic mute. Extend capture beyond predicted linear decay. An analogue
input's noise can keep exciting poles, so analogue silence cannot prove a zero-input limit
cycle; seek a digital-zero route or report a bound. Compare noise spectra, decay envelopes,
tonal persistence and level dependence against identity and float64 controls. A steady tone
may be a bench spur: vary coefficients/order and repeat before attributing it to the DUT.

Sweeps cannot identify an exact recursive word length. Claim only behaviour established above
the measured floor; more specific arithmetic identification needs independent implementation
information or discriminating experiments. Failure to observe a cycle sets a detection bound,
not proof of its absence.

## Harness design and alternatives

Proposed components: a manifest/prediction generator, engine adapters (`identify`, `snapshot`,
`load`, `readback`, `restore`), measurement adapters (`qualify`, `sweep`, `capture`), and an
offline analyser. Capability flags cover raw coefficients, readback, digital zero, actual rates
and manual loading. Failed/missing capabilities must be visible in results.

### Primary Python measurement backend

Use [sounddevice](https://python-sounddevice.readthedocs.io/en/latest/usage.html) for PortAudio
playback/capture and [pyfar signals](https://pyfar.readthedocs.io/en/stable/modules/pyfar.signals.html)
for exponential sweeps. [pyfar DSP](https://pyfar.readthedocs.io/en/stable/modules/pyfar.dsp.html)
provides regularised inversion. NumPy/SciPy handle predictions, complex ratios, PSDs and
analysis; archive arrays in a portable, non-pickle format. Freeze tested dependency versions
compatible with the project's Python 3.13 before implementation. These are measurement/build
extras, not additions to ordinary design dependencies.

Use `playrec()` for the development pilot only. The shipped backend uses a full-duplex
`sounddevice.Stream` with explicit device, host API, sample rate, channels, latency and sample
format. Enumerate devices and supported configurations; verify requested settings before
opening the stream. Resolve saved names/host APIs/channel counts each run, displaying the
selected physical routes; device indices alone are not persistent identifiers. If a selection
is ambiguous, require setup rather than choosing the default output.

Keep the audio callback short: copy precomputed stimulus chunks, collect input chunks and
record status/timestamps/sample counts. No device-control calls, FFTs, plotting, disk writes or
blocking queues in the callback. Bound buffers, offload capture storage to a writer, and abort
with a saved failure record on overflow/underflow, buffer exhaustion, missing samples or writer
failure. Float32 is sufficient as an initial audio transport format; use float64 for analysis.
Record actual transport precision separately from the engine's internal arithmetic. Do not
claim float64 playback/capture because the analysis arrays are float64.

Each stimulus contains measured pre-roll, an exponential sweep, and a zero tail long enough
for the slowest case. Preserve the exact emitted waveform/hash, peak/RMS, fade settings and
sample positions. Initial pilot: a 30-second 2–200 Hz sweep, extended until doubling duration
and tail/window length changes the recovered response by less than the frozen uncertainty
budget. This is a starting configuration, not a qualified resolution claim at 2 Hz. Check
sweep peaks after synthesis/scaling and do not normalise recordings. Silence, tone and burst
protocols reuse the same capture path with no automatic dither.

Process captures offline:

1. Check sample count, callback status, clipping, channel activity and noise captures.
2. Estimate transport delay with a recorded reference channel or correlation to the stimulus.
   Keep full pre-roll/tail until alignment is established; do not discard slow filter decay.
3. Estimate clock mismatch from a reference or separated timing markers. Prefer a common-clock
   interface. Qualify a maximum drift from simulations; refuse excess drift initially rather
   than silently resampling. A later correction must save the estimated ppm and both original
   and corrected captures, and pass independent tests.
4. Recover the linear impulse/complex response using pyfar inversion of the exact stimulus,
   with zero-padding sufficient for linear convolution and the tail. Record FFT normalisation,
   padding, regularisation bounds/strength and windows. Regularisation must not flatten the
   effect under test: report only a band where its bias has been independently bounded.
5. Keep the linear-response window separate from harmonic sweep products; verify that the
   chosen window preserves low-frequency tails. Distortion/low-level noise are separate
   diagnostics, not evidence to mix into the linear ratio.
6. Apply the identity comparison and validity masks above; generate the offline report.

Validate recovery before interpreting hardware: independently render known biquads at native
rate with a time-domain reference and inject delay, noise, gain, truncation, clipping, dropouts
and clock mismatch. Test identity, a high-Q low-frequency section and a cancelling cascade.
Predictions must not be the same estimator applied twice. Establish accuracy and mask behaviour
against analytical responses; compare selected electrical measurements with REW when available.
REW is an independent cross-check, not a licence prerequisite for running or releasing the tool.

pyroomacoustics' experimental `measure_ir` is a possible disposable pilot, but is not the chosen
shipped backend: direct control over stream status, raw zero captures and retained tails is
part of this protocol. Keep REW as a second adapter sharing manifests, comparison maths and
result schema, so paired captures can be analysed by the same offline report.

### Standalone user workflow

Ship a console executable named `beqforge-device-check` (Windows: `.exe`) with a guided `setup`
command. A GUI is outside the first release. Proposed commands, not existing interfaces:

```text
beqforge-device-check devices
beqforge-device-check setup --out bench.json
beqforge-device-check qualify --config bench.json --out qualification/
beqforge-device-check plan --config bench.json --suite pilot --out cases.json
beqforge-device-check run --config bench.json --manifest cases.json --out run/
beqforge-device-check analyse run/ --out report/
beqforge-device-check bundle run/ --out results.zip
beqforge-device-check self-test --out self-test/
```

`setup` collects named device/firmware/internal rate, engine, audio route, line-input/output
channels and device-control executable path. Show a wiring guide and require an explicit
acknowledgement that the selected route is a disconnected electrical bench before its first
signal; retain this acknowledgement in the setup. `devices`, `plan`, `analyse`, `bundle` and
`self-test` emit no live signal and change no device state. `run` shows the frozen cases,
level, expected duration and restoration state; once started it progresses without per-case
prompts. Ctrl-C stops playback, saves partial results and invokes bounded mute/restoration.

Qualification records which bands/levels are usable; `run` requires qualification matching
its routing, rate, levels and relevant settings. Mark qualification stale after setup changes.
A hardware-control failure stops automatic loading. Manual engine loading is an explicit mode
that identifies each required case; it must never masquerade as an unattended run. Store all
results under the user's chosen writable directory, outside the executable extraction area.

Provide a compact HTML report and machine-readable JSON with per-case measured/predicted
curves, uncertainty, valid band, quality failures and completeness. The shareable ZIP includes
manifest, coefficients, stimulus, raw recordings, logs and offline report inputs; offer a
summary-only bundle clearly marked insufficient for full replay. Display bundle contents and
size. No automatic upload; exclude credentials, unrelated files and unnecessary host-identifying
paths, while retaining device/firmware and driver facts needed to interpret the measurement.

### Published catalogue modes

Add two first-class modes alongside the synthetic/published-baseline manifest suites:

```text
beqforge-device-check catalogue-entry --config bench.json --catalogue snapshot.json --entry ENTRY_ID --out run/
beqforge-device-check catalogue-plan --config bench.json --catalogue snapshot.json --out catalogue-cases.json
beqforge-device-check run --config bench.json --manifest catalogue-cases.json --out catalogue-run/
beqforge-device-check catalogue-analyse catalogue-run/ --out catalogue-report/
beqforge-device-check catalogue-analyse run-a/ run-b/ --out device-comparison/
```

The published BEQ catalogue supplies real-world cascades for an engine accuracy experiment.
It is not ground truth for the soundtrack's mastering or the correctness of a BEQ target.
No film audio or acoustical measurement is needed: load each entry's published filters and
measure their electrical response. Never run the designer, refit, or simplify an entry to make
it easier for a device. Preserve section order and published parameters and calculate the
ideal response at that engine's verified internal rate.

Implement a catalogue importer after identifying the authoritative published source and
schema (including revisions, entry IDs, channel/filter scope and alternate versions). Accept
an explicit local snapshot from day one; add fetching through an explicit source URL/revision
once verified. Archive the exact downloaded bytes, retrieval time, source revision/hash and
licence/attribution. Resolve all pages/shards before marking a snapshot complete. Catalogue
contents can change; a run always measures a frozen snapshot, not a moving 'latest'. Treat
imported metadata as data, never executable commands or paths. Do not guess missing Q, slope,
filter type or channel applicability; name unsupported fields and affected entries.

**One entry:** resolve a stable entry ID within the snapshot, show title/version and cascade,
then use the same qualified load/identity/sweep/repeat transaction as the other suites.
Compare measured response with the ideal published cascade and the transport/storage model.
Report the signed delta curve, worst error/frequency, RMS error, phase where qualified,
uncertainty, valid band and quality checks. Include a filter table and the actual sent payload.
Global gain/offset is part of the manifest: state whether it is applied or reported separately,
and keep identical bench attenuation in identity and filtered measurements so the cascade
ratio remains meaningful. Do not silently drop an entry's gain metadata.

**Entire catalogue:** first build an inventory mapping every published entry/version to its
canonical cascade and measurement case. 'Entire' means every record in the selected complete
snapshot, with explicit outcomes for entries that cannot be loaded. Multi-channel entries
require separate cases for distinct applicable cascades, with their channel mappings retained;
an electrical single-route test does not establish multichannel summation/headroom accuracy.
Use device capacities and supported filter types to classify entries as measurable or
unsupported before loading. Entries needing too many sections remain unsupported, never
truncated. Stability and headroom checks apply to imported filters too.

Deduplicate exactly identical ordered cascades at the same rate/gain/route into one measured
case, retaining every source-entry mapping. Order-sensitive variants remain distinct. The
catalogue inventory still accounts for all entries; users can disable deduplication to study
reload variability. Use a representative pilot subset to estimate runtime and storage, then
show totals for entries, unique cases, unsupported entries, repeats and expected duration
before the full run. Permit explicit resumable shards/subsets, marking their reports partial
until the inventory is completely accounted for. Completed cases are keyed by snapshot,
manifest, bench/config hash and measurement protocol; never reuse measurements after a
configuration change without fresh qualification and matching references.

Long runs use randomised, recorded ordering, independently loaded repeats, periodic identity
brackets and qualification checkpoints. Keep the same stimulus level within each qualified
block; where different attenuation is necessary, pair with matching references and record it.
Abort/invalidate affected blocks after significant reference drift. Save each completed case
atomically so a disconnected device or overnight interruption costs only the unfinished block.
Resume establishes routing/device state and measures a new reference before proceeding.
Preserve all failed attempts with reasons; retrying must not select only favourable traces.

### Catalogue analysis across real devices

Analyse each named model/firmware/rate/route as a separate configuration first, then compare
matched cases across configurations and contributor bundles. Group software engines separately
from hardware. Show exact-coefficient departure as the principal real-world delta, and departure
from the proposed storage model as an attribution diagnostic. Neither analogue conversion nor
an unknown coefficient format may be silently assigned to recursive arithmetic.

The report should include:

* Inventory completeness: measured, unsupported, unstable, failed, under-range and incomplete
  entries/cases; qualified frequency coverage and reasons for every exclusion.
* Per-case residual curves and error summaries with uncertainty, identity drift and repeat
  spread. Plot the most discrepant cases and provide links to their filters/raw evidence.
* Median, 90th/95th percentile and maximum absolute error, and fractions exceeding predeclared
  engineering tolerances, both per frequency and per cascade over its valid band. Retain signed
  bias as well as absolute error. No tolerance is tuned to make the catalogue appear accurate.
* Error versus lowest corner, gain, Q, section count, opposing sections, predicted quantisation
  sensitivity and engine rate. Use these as exploratory explanations, not automatic new limits.
* Matched-cascade comparisons between models and between physical units of the same model,
  firmware and repeated sessions. Show identity/measurement variation beside device differences.
  With one physical unit, report that unit's results; do not estimate population variability.

Publish both entry-weighted and unique-cascade-weighted summaries: repeated catalogue versions
must not inflate evidence of independent DSP behaviour. Frequency summaries state denominators
because valid bands differ. Common-band comparisons use matched masks and list omitted cases;
do not replace missing/noise-dominated bins with zero error. Catalogue-wide maxima are sensitive
to measurement noise and coverage; show qualified uncertainty and the responsible case.
Separate within-run repeats, sessions, physical units and model differences. Any confidence
interval must respect those dependencies; a thousand entries on one box are not a thousand
independent devices. Catalogue accuracy says nothing about how frequently users play each entry.

For community evidence, define a versioned exchange schema including device identity (optional
pseudonymous unit ID), model/firmware, actual internal rate, transport/storage claims, route,
qualification, source/manifest hashes, raw captures and analyser version. Contributor bundles
are explicitly exported, never auto-uploaded. Compare only compatible snapshots/protocols,
or their explicitly matched intersections, and expose different capture interfaces/routing as
possible confounders. Reject malformed archives safely without evaluating objects or writing
outside the chosen import directory. Duplicate bundles/reanalyses must not count as new units.

The delivery outcome is a reproducible account of how closely published cascades play on the
measured devices, with the degree of observed variation and the measurement limits visible.
A recommendation to change realisation assumptions or Q limits remains a separate F2 decision
requiring the arithmetic tests and regression process above.

### Packaging and cross-platform release

Use a dedicated PyInstaller spec and workflow target, reusing the existing repository's build
revision stamping and platform smoke-test pattern. Build on each target OS/architecture:
[PyInstaller's operating model](https://pyinstaller.org/en/stable/operating-mode.html) requires
platform-specific builds. A standalone executable contains Python, the measurement packages
and their native dependencies; users do not install Python, uv or REW.

First release targets Windows x86_64, Linux x86_64, and macOS arm64 plus x86_64, contingent on
real build/bench verification. Pin runner architecture and verify the binary architecture;
the existing workflow's `macos-latest` label must not be reused as proof of an x86_64 build.
Declare minimum OS versions and a Linux glibc baseline. Cross-platform means separately
verified downloads, not one binary that works on every OS.

[sounddevice installation notes](https://python-sounddevice.readthedocs.io/en/latest/installation.html)
explain the platform-specific PortAudio libraries and Windows ASIO selection. Explicitly bundle
and test PortAudio/CFFI/native numerical libraries and pyfar data/imports with PyInstaller hooks.
Bundle a tested Linux PortAudio build or record a concrete release blocker; do not discover
missing `libportaudio` on a user's first measurement. System audio services and hardware drivers
remain host prerequisites. Windows WASAPI, macOS CoreAudio and Linux ALSA are initial bench
paths; virtual engine routing needs documented platform-specific setup. Add ASIO only after
its build, selection-before-import and redistribution requirements are verified.

The first release should include a pinned minidsp-rs helper for each supported target inside
the single executable, extracting it only to a controlled temporary directory. Verify helper
availability, architecture and licence/notice requirements before committing to those assets.
Invoke by absolute path with argument arrays, bound subprocesses, and embed its version/hash
in results. Support an explicit external-helper override and log it. If a target cannot legally
or technically bundle the helper, ship an explicitly labelled external-helper variant with
setup diagnostics; do not call that target's miniDSP workflow self-contained. CamillaDSP,
JRiver and optional REW remain separately installed engines/applications. Drivers, USB access
permissions and virtual audio devices cannot be packaged away.

Prototype packaging in one-folder mode for diagnosing native dependencies, then publish onefile
assets once extraction/child-process behaviour passes. Measure startup/extraction time and
capture reliability; do not switch packaging modes silently. Review macOS microphone permission
and USB access for the frozen console process, sign/notarise macOS artifacts where available,
and document Windows signing status. Test installed downloads, including paths with spaces,
non-ASCII names and a normal account's permissions. Ship checksums, versioned example bench
configs/manifests, notices and a short wiring/qualification/troubleshooting guide.

Release checks have two layers:

* Every platform/architecture CI build runs the actual frozen `self-test`: native imports,
  known-transfer stimulus/recovery, mock engine transactions including timeout/stale-slot
  cleanup, evidence writing, ZIP creation and offline report regeneration. `devices` verifies
  the packaged PortAudio library can initialise even on a runner with no audio hardware;
  no available devices is a supported result. No `--help`-only smoke test.
* A release candidate passes real playback/capture qualification and the pilot on each claimed
  OS/architecture, with at least one verified miniDSP route per OS. Retain OS/architecture,
  helper/driver versions and result bundles. CI simulation cannot prove hardware compatibility.
  Targets awaiting bench evidence are preview assets with that limitation, not validated ones.

Store a unique run directory with manifest/hash, repository revision, coefficient files,
transport logs, device/config snapshots, API schemas, stimulus/measurement settings, raw
captures and exact emitted stimuli from the Python backend, optional REW `.mdat`, extracted arrays and machine-readable analysis.
The report must be regenerable offline, including uncertainty/masks and all excluded cases.
Do not overwrite baseline title records or reuse the ordinary design stage cache.

## Delivery and decision criteria

1. **Feasibility record:** name device/interface, verify loading/sign/rate, Python dependencies and audio stream, capture
   routing and restoration; resolve JRiver loading and precision independently.
2. **Qualified pilot:** identity repeatability and a measured valid band, plus benign and
   sensitive case results. Establish limits of detection and freeze the main protocol.
3. **Hardware batch:** reproducible manifests, reload repeats, bracketing references and noise
   tests. A complete batch can legitimately report inconclusive cases.
4. **Software controls:** identical manifest on CamillaDSP and feasible JRiver routes, with
   independently verified active precision and engine-specific reference measurements.
5. **Standalone release:** frozen Python-backend self-tests on all targets, real bench pilot
   records, documented setup and reproducible offline bundles. Prototype success alone is
   not release completion.
6. **Catalogue modes:** single-entry report, complete frozen catalogue inventory, resumable
   batch capture and offline distributions/matched-device comparisons; unsupported entries
   remain visible. Validate the importer and aggregation on a small fixture before a full run.
7. **Evidence report:** compare measured and predicted errors, explain exceptions, retain raw
   evidence, and recommend keeping or revising the model with its device/rate/level scope.

Before the main batch, choose an engineering accuracy requirement independently of measured
filter outcomes. Qualification uncertainty must be small enough to distinguish that requirement
and the predicted quantisation effects. Freeze the uncertainty method and reporting criteria;
do not turn exploratory discrepancies into a retrospective pass threshold. A software control
passes when measured error meets the declared requirement within qualified uncertainty;
it does not demonstrate bit-exact float64 arithmetic through float32 API data or analogue I/O.
The hardware storage model is supported only where its residual agrees within that same
budget across levels/repeats, including the sensitive cases. Persistent excess or level/order
dependence requires investigation; unresolved storage remains an attribution limitation.

F2's Q-limit question needs comparisons matched for corner/gain and quantisation sensitivity,
including above-limit fits. A single high-Q failure does not justify a blanket cap, and a good
sweep does not establish low-level arithmetic safety. Do not infer all miniDSP models from one.

Planning changes need documentation review only. Later harness tests should cover coefficient
conventions/serialisation, API decoding/IDs, stale slots, timeouts, masks and offline replay;
include an independent known-transfer test. Any subsequent change under `beqforge/` follows
AGENTS.md's regression process; changes to limits/selection also require the synthetic protocol
and negative corpus. Record measured outcomes here and update TODO status only after evidence.

## Implementation sequence and outcomes

Implementation started 2026-10-01 after merging the outstanding dependency PRs. Work proceeds
one tested commit at a time: (1) profiles/frozen predictions, (2) stimulus/recovery and quality
checks, (3) evidence transactions/qualification, (4) engine adapters and software controls,
(5) catalogue inventory/comparison, (6) guided console workflow, (7) preview packaging.
Actual bench evidence is required separately before calling a release or device profile validated.

The first hardware target is the owner's miniDSP 2x4 HD, stated to use 32-bit floating point
at 96 kHz. Its rate and input/output capacities follow ezbeq's `Minidsp24HD` descriptor:
10 sections per input/output PEQ route, two inputs and four outputs. CamillaDSP at the same
rate is the requested software reference. Profiles retain capability and arithmetic claims
separately from measurement evidence; no designer realisation default or Q limit is changed.
The interface/physical route, firmware and restored configuration still need bench setup.

### 1. Profiles and frozen predictions

Added the dedicated `beqforge_device_check` package. Versioned manifests preserve continuous
and canonical published filters, exact coefficients, float32/float64/5.23 candidate storage
models, stability, ordered cases and reproducibly randomised independent reloads. Unsupported
capacity/rate and unstable rounded cases remain visible; nothing is clamped or truncated.
miniDSP serialisation reverses feedback signs relative to the RBJ/SciPy denominator.
Extended-precision response evaluation is independent of time-domain recovery.

Validation: four tests passed, covering ezbeq-compatible 2x4 HD capabilities, immutable hash
checks, independent SciPy frequency-response agreement, feedback sign and a low-frequency
case that becomes unstable after float32 rounding. Ruff passed for the new package/tests.
This is an offline foundation, not a measured device claim. No code under `beqforge/` changed.

### 2. Stimulus, recovery and capture foundation

Pinned measurement-only extras to sounddevice 0.5.6 and pyfar 0.8.1, verified on Python 3.13.
The exact emitted float32 sweep includes pre-roll and zero tail, hashes and sample positions.
Offline pyfar regularised inversion preserves the full tail and native FFT frequencies, records
its calculable inversion bias, masks under-range bins and does not remove gain/filter phase.
An independent timing channel estimates transport delay and relative drift; excess drift is
refused rather than resampled. Unverified latency remains a phase limitation.

The explicit sounddevice Stream backend checks names/host APIs/channels/rate, uses bounded
preallocated RAM buffers, records callback statuses/timestamps and writes completed captures
outside the callback. Device discovery is isolated in a timeout-bounded subprocess: native
PortAudio initialisation succeeded on this host, but discovery stalled and was stopped.
No live signal was emitted and no miniDSP settings changed. Streaming remains bench-unverified.

Validation: all ten foundation/recovery tests pass; known-transfer error was below 0.002 dB
for identity, a high-Q low-frequency peak and a cancelling shelf cascade. Injected delay,
clock mismatch, clipping, truncation, callback dropouts, noise masking and preserved gain
are covered. These are numerical checks, not a qualified 2 Hz bench result. Ruff passes.

### 3. Evidence transactions and identity repeatability

Added exclusive run locking, append-only attempt states, atomic non-pickle capture/stimulus/
analysis files, reloads, identity brackets, drift aborts and explicit resume. Every resume
remeasures identity; completed keys include manifest, bench, level and ordinal. Captures and
sent payloads survive a failure, and restoration is attempted on completion/failure. ZIP
export includes only registered evidence with verified hashes; summary-only archives are
marked insufficient for replay. No automatic upload or retry is implemented.

Identity qualification loads at least five independent repeats per level and freezes
frequency masks/repeat spread and the independently supplied engineering requirement. It is
honestly labelled incomplete until convergence, direct loopback and bypass are demonstrated;
only the numerical control can batch-run against this initial qualification. Live paths
require the recorded disconnected-bench acknowledgement before qualification emits a signal.

Validation: fourteen F2 tests passed, including partial failure/restoration, explicit resume,
stale qualifications, concurrent lock refusal and unrelated-file exclusion. Ruff passed.
The numerical engine processes captures with independent SciPy `sosfilt`. Live restoration
and the broader qualification protocol remain adapter/bench tasks.

### 4. miniDSP and CamillaDSP adapters

Added bounded helper processes with version/hash checks and argument arrays. miniDSP selection
requires an explicit serial and rechecks it before commands; each load clears all unused
selected-route slots and explicitly activates sections. Feedback signs match ezbeq's loader.
The miniDSP adapter requires user-supplied complete restoration commands because master status
cannot reconstruct its configuration. Restoration remains unverified without coefficient
readback, so it leaves the device muted and reports the outstanding state. Emergency
restoration failures are recorded without losing the run record. No hardware was changed here.

CamillaDSP supports a pinned raw file-in/file-out control and an explicit mono live websocket
bench template. Commands are correlated by name with finite bounds; active configuration,
version, mute and restoration are checked. Parameter readback is labelled separately from
coefficient-bit readback. websocket-client 1.9.2 is an optional pinned measurement dependency.

Validation: nineteen F2 tests passed, including helper timeouts (no retry), feedback signs,
unused-slot clearing, unverified restore, websocket response matching and restoration failure.
The official Linux amd64 CamillaDSP 4.1.3 (05e9cfc) binary processed identity, benign and
sensitive pilot cascades at 96 kHz. Recovered valid-bin error against independent analytical
predictions was below 1e-6 dB (observed approximately 9.15e-9 dB). This validates this binary's
file-processing control only; its live path, other builds and the miniDSP remain unmeasured.
The helper was downloaded into scratch space, not vendored or installed globally. Ruff passes.

### 5. Frozen catalogue import and offline reports

Added an explicit local ezbeq `database.json` importer, using the schema and feedback convention
in the sibling ezbeq implementation. Snapshot bytes/revision/attribution/completeness are
identified; content-derived IDs are labelled when no published ID/digest exists. Published
parameters/order/counts, volume adjustment and supplied rate-specific coefficients are retained.
Exactly identical ordered cascades can share a case while every source version remains in the
inventory. Capacity, malformed/missing Q, instability and presently unsupported channel-specific
schemas remain explicit unsupported outcomes. There is no fetch/refit/truncation or guessed
channel applicability. Multi-channel schema support remains a follow-up rather than a claim.

Offline analysis preserves individual native-bin signed exact, sent and candidate-stored errors,
phase limitations, uncertainty/masks, excursions, worst frequency and log-weighted RMS without
bridging invalid gaps. Bracketing identities normalise the bench without fitting away gain.
Qualification arrays are hashed, carried with the run and applied to its valid masks; engine/build
changes invalidate qualification. Reports include published filter tables, JSON and discrepancy
plots. Catalogue aggregation separates entry and unique-cascade weighting, and comparison retains
all reloads/levels and unmatched-case counts rather than treating repeats as new devices.

Validation: twenty-five F2 tests passed, including full numerical run → offline report → ZIP,
source coefficients/signs, capacities, dedup/order, masked gaps and catalogue/reload weighting.
Ruff passed. Uncertainty is currently identity-repeatability plus bounded inversion bias; broader
qualification and population/error-model claims remain open. Nothing under `beqforge/` changed.

### 6. Console workflow and reproducible pilot preview

Added the separate `beqforge-device-check` entry point, guided setup, explicit device inventory,
frozen pilot/matrix/catalogue planning, qualification, run/resume, offline analysis and ZIP
export. `docs/device-check.md` documents the commands and the outstanding live qualification.
Frozen stimulus levels account for the largest intermediate cascade response plus 6 dB margin;
case identifiers include those levels. Camilla active parameter readback is correctly distinct
from coefficient-bit readback. Existing designer defaults and runtime dependencies are unchanged.

Validation: 661 tests passed, one skipped, with the real Camilla file-control test enabled;
Ruff passed. The CLI self-test independently recovered identity, benign and sensitive transfers
with worst valid-bin error approximately 6.7e-9 dB, completed numerical transactions, regenerated
the offline report and exported its evidence. PortAudio discovery timed out after its bounded
10-second subprocess on this host; this is recorded as a live-audio limitation. The repository's
explicit test-package marker prevents optional dependency test packages shadowing its helpers.
Live qualification remains incomplete: no miniDSP or audio interface measurement was performed.

### 7. Native standalone preview builds

Added a dedicated spec and preview-only workflow with explicit Linux x86_64, Windows x86_64,
macOS arm64 and macOS x86_64 runner targets. Builds check the host architecture, use pinned
PyInstaller 6.22.3, bundle the hash-pinned miniDSP 0.1.9 helper, preserve upstream/native notices
and distribution metadata, and record implementation/library/helper hashes. Saved setups resolve
`bundled` against the current private extraction directory, with an external-helper override.
Linux fails the build without discoverable PortAudio. The workflow diagnoses a folder build
before the onefile build and uploads checksum-bearing previews, never validated releases.

Both local Linux folder and onefile builds passed the substantive frozen self-test, including
known transfer recovery (~6.8e-9 dB worst valid-bin error), helper timeout/no retry, unused-slot
clearing, evidence/report/ZIP generation, native PortAudio initialisation and device discovery.
The actual bundled helper's version and hash are checked without probing/changing USB devices.
Tests ran from paths containing spaces and a non-ASCII character. The onefile preview is about
96 MB; an initial onefile self-test took 10.7 seconds including extraction. The first prototype
revealed an empty source digest because the frozen entry script is outside the package; package
resolution and the stamped implementation digest were corrected and checked by the smoke tool.
Twenty-six F2 tests pass; one optional real-Camilla test skips unless its binary is supplied.
The complete suite passed in checkpoint 6, and `uv lock --check` and Ruff pass.

This host's Linux build is a local preview, not evidence of the workflow's Ubuntu 22.04/glibc
2.35 baseline. Cross-platform CI has not run; macOS permission/signing/notarisation, Windows
signing/drivers and actual playback/capture remain unverified. The Linux audio discovery timeout
seen in the source run did not occur in either frozen preview. No hardware measurements were
made and no designer behaviour changed.

### 8. Interrupted capture evidence and bounded offline import

Stream interruptions now carry the captured sample prefix, actual stream settings, callback
statuses/timestamps and failure to the transaction writer. Missing frames, timeout and actual
rate mismatch abort rather than losing partial audio or marking it completed. Restoration still
runs. The miniDSP identity now includes its electrical-route scope used by run records.

ZIP exchange records per-file SHA-256. Import rejects duplicate/unregistered/traversing/symlink
members, checks size bounds and every hash in a temporary directory, and exposes only a fully
validated new destination. Imported evidence cannot resume live control. Local bundles retain
bench provenance; automatic credential/path redaction for community sharing remains unfinished
and is explicitly documented rather than claiming share-safe exports.

Validation: thirty-three F2 tests passed, one optional real-Camilla test skipped. Tests verify
that interrupted samples/statuses survive restoration; exported/imported complete numerical
runs regenerate identical report results; malformed paths/hashes/oversized bundles leave no
visible destination. Ruff passes. The frozen self-test now includes import/offline replay too.

Remaining F2 work at checkpoint 8 was deliberately open: direct interface/bypass and duration/tail convergence
qualification, live pilot and arithmetic/noise/ring-out experiments, JRiver feasibility,
channel-specific catalogue formats, shared-frequency matched comparison/denominators, redacted
community exchange and cross-platform CI/bench verification. The current preview validates a
numerical/control workflow, not the device precision conclusions or the full protocol.

### 9. Runnable qualification and catalogue population analysis

The owner selected miniDSP serial 914267. Only minidsp-rs 0.1.9 CLI discovery/status was used;
status reported USB source, preset 0 and an unmuted 0 dB master. No filter, gain, mute or
routing settings were changed, and no audio stream or live signal was opened. The device
was then disconnected because this host was unstable; live work resumes on a different host.

Corrected a precision attribution error: the pinned CLI's `PeqCommand::Set` parses `Vec<f32>`
and its 2x4 HD dialect encodes `Float32LE`, confirmed from the v0.1.9 source. Payload records
now separate requested coefficients from the actual float32 transport values. More decimal
digits cannot evade that conversion. Storage remains unverified, and recursive arithmetic
is a distinct hypothesis. Numerical controls now independently select stored-coefficient
precision and SciPy float32/float64 recursive processing, explicitly not a proprietary-device
emulator. This changes neither the designer nor its realisation assumptions.

Added direct-interface and selected-PEQ-bank bypass repeatability stages, independent sweep
duration/tail doubling on every planned cascade, and offline qualification assembly. Direct
loopback opens only the named audio route and sends no DUT controls; the operator must rewire
and record the path. Bypass is expressly the selected PEQ bank, not the whole DSP. Completion
requires matching bench/manifest/settings/engine and hashed evidence for all stages, a recorded
clock basis or timing reference, and common usable bins within the frozen uncertainty budget.
Identity uncertainty now uses measured repeat spread, output-noise bounds and inversion bias
rather than adding an arbitrary 0.01 dB. Supporting raw recordings and transport evidence are
copied into the completed qualification and run bundles; stale/missing evidence refuses a run.
The checks do not establish a zero-input arithmetic detection bound or verify physical wiring.

Filter reports now classify qualified bins as within the engineering requirement, exceeding it
despite uncertainty, or unresolved. They retain unqualified coverage and filter characteristics.
Catalogue population reports add signed bias, median/90th/95th/maximum absolute errors,
exceedance fractions and qualified denominators at each frequency, separately weighted by
entries and unique cascades. Reloads remain dependent. The declared 128-point logarithmic
display grid interpolates adjacent valid bins only; it never bridges a masked gap. HTML plots
show error distributions with the qualified counts. Matched-device comparisons now calculate
signed differences and combined uncertainty on shared valid bins at matching levels, retain
each reload pair and expose omitted levels/coverage. Offline replay verifies registered
analysis/transport hashes and qualification identity before producing a report.

Validation: 48 verifier tests passed, one optional real-Camilla test skipped; Ruff and
`git diff --check` passed. The full repository run passed 660 tests and skipped two; its
16 localhost HTTP tests and one extractor test initially failed because the sandbox blocked
sockets and uv's cache. All 17 passed in environment-specific reruns. The final timing-reference
guards were then covered by the complete verifier test set without repeating unaffected
designer tests. Independent timing references cannot select the DUT capture channel, an
out-of-range channel or a boolean; common-clock claims require a boolean and recorded basis.

Source, rebuilt Linux folder and final single-file preview self-tests passed independent
identity/benign/sensitive recovery (worst valid-bin error approximately 6.8e-9 dB), qualification
assembly, raw-evidence export/import and identical offline replay. Audio discovery was explicitly
disabled in all self-tests; no hardware was probed or measured. The final single-file smoke
test held the sleep inhibitor and completed in 21.3 seconds. The executable is 96,237,560 bytes,
SHA-256 `2d2c436c25cbad4c4406cde67dde7b65bc535a37014a9aeac1fb36e8cf3d1488`.
The ignored local delivery directory `dist/device-check-linux-x86_64-preview/` contains the
executable, guide, notices, smoke record and `SHA256SUMS`. This is a build for this development
host, not evidence of the workflow's Ubuntu/glibc baseline or compatibility with another OS.

The documented commands are runnable on the next host after installing the measurement extra
or using a matching standalone preview and completing setup. Remaining evidence/development:
real bench qualification and live pilot, low-level/noise/ring-out experiments and arithmetic
detection bounds, JRiver feasibility, explicitly characterised channel-specific catalogue
schemas, community-bundle redaction, cross-platform build/bench verification. A complete
catalogue inventory may legitimately account for unsupported entries; those entries are never
silently dropped, clamped or truncated. No hardware/model/Q-limit validation is claimed.

### 10. minidsp-rs 0.1.12 helper and batched device commands

The helper pin moved from minidsp-rs 0.1.9 to 0.1.12 (`engines.MINIDSP_VERSION`, used by the
adapter, setup, self-test and `tools/prepare_device_check_helper.py`). Release archives carry no
published digest, so the four target archives were downloaded and hashed on 2026-10-05; the
Windows `minidsp.exe` inside matches an independently downloaded copy byte for byte. Every
archive still has the binary at its root, and the upstream LICENSE is unchanged.

The source diff v0.1.9..v0.1.12 was reviewed for the claims this adapter makes. Unchanged:
`FilterCommand::Set` parses `Vec<f32>` (the earlier citation named it `PeqCommand::Set`, a
mislabel now corrected); `protocol/src/device/m2x4hd.rs` is byte-identical, still `Float32LE`;
the input/output PEQ handler is untouched; `probe` output and master `status` only changed
formatting idiom. The changes are a new Flex HTx device, crossover `group` accepting `all`,
and pending commands failing promptly when the transport closes. The 0.1.12 `--help` was read
for every command shape the adapter issues; all match.

Loading and restoration now go through one helper process using minidsp-rs's `-f FILE`
(one command per line, run in order against the `-d` device, stopping at the first failure),
after one serial check. A four-section load was nine helper processes, each preceded by a
probe; it is now one probe and one helper process. Failure semantics are unchanged: a failed
batch is a partially applied one and the transaction restores. Restoration's batch mutes first.

Python's range widened to `>=3.13,<3.15`; the lock adds only 3.14 wheels at unchanged versions.

Validation (Windows 11, Python 3.14.8): 49 device-check tests passed, one skipped. The full suite
ran 632 passed, 53 skipped, one failed: `test_material_round_trips_through_the_extractor` needs
`ffmpeg`, absent on this host. Ruff passes on every changed file.
Serial 914267 was only probed and its master status read (preset 0, USB, 0 dB, unmuted); nothing
on it was changed.

An opt-in bench route followed (`engines.usb_loopback_route`, setup's `CONFIGURE` answer,
`engine.route_commands`): every setting on the DUT and reference paths stated explicitly, applied
as one batch at the start of each live stage except direct loopback, recorded in the snapshot,
and the default restoration set. It neither saves nor reads back the prior configuration. The
owner's bench is a pure USB loopback (USB playback → 2x4 HD → USB capture), one device clock.

Console progress followed: every sweep logs its case, level, counter, sweep/tail length, usable
bins, lowest usable SNR, delay and drift; stages log their plan and estimated time, per-level
results, route application and restoration (stderr; stdout stays the JSON result).

Sweep timing changed from a fixed 2 s pre-roll + 30 s sweep + 15 s tail (47 s for every case)
to a 0.5 s pre-roll + 5 s sweep + a tail of at least 1 s, extended per cascade to its own
settling time (decay to -120 dB; `SweepSettings.for_settling`). The 15 s tail existed only for
the slowest cascade. Convergence's tail variant doubles `settling_multiple` with `tail_s`, so an
extended tail is doubled too. Pilot identity stage: 10 sweeps of 6.5 s instead of 47 s. The
pre-roll still bounds the transport delay and is the noise estimate; neither the shorter sweep
nor the shorter pre-roll is asserted adequate: the convergence stage is what tests them.

### 11. One-command verification with stored stages

`beqforge-device-check verify --config bench.json [--manifest ...]` qualifies, assembles, runs
and analyses in one command (`beqforge_device_check/verify.py`). Identity and device bypass are
measured against a derived identity-only manifest and stored beside the bench, keyed on bench,
engine identity, sweep settings, accuracy requirement and that derived manifest (identity case,
levels, repeats); any manifest sharing those reuses them. Convergence records now list the
cascades they cover; `complete` accepts several, combines their per-level budgets by maximum,
and records `identity_case` and `convergence_covers`; `run` accepts a qualification built for
another manifest only when it covers that manifest (same identity case and levels, every
planned cascade converged). Repeating a verification measures only the run itself.

Fixed with it: per-cascade tails (section 10) gave a long-settling cascade a longer capture and
so a finer FFT grid than the identity sweeps it is divided by, which broke convergence
(`operands could not be broadcast`, met on the bench) and would have broken analysis. The
identity is now recovered again from its saved raw sweep at the cascade's FFT length
(`transactions.recompute`, `recover(size=...)`): exact, since both signals are finite. Zero-
padding the stored impulse response was tried first and is wrong: the 2-200 Hz deconvolution
band edges make that response ring and wrap (identity magnitude 0.02-1.03 instead of 1).
Qualification budgets are carried onto the finer grid conservatively (`measurement.carried`).

### 12. First hardware result, characterisation suites and a readable report

The first verified pilot on the 2x4 HD (USB loopback, 96 kHz, minidsp-rs 0.1.12) answers the
two questions F2 asks separately. The device plays exactly what its float32 coefficients
predict: worst 0.0074 dB over 2-200 Hz for both filters, at -30 and -50 dBFS, with three reloads
agreeing to about 0.003 dB. The coefficients are another matter: a 5 Hz, Q 6, +12 dB peak in
float32 at 96 kHz moves its resonance to 3.7 Hz and errs by 18.8 dB; a 60 Hz, Q 0.707, +3 dB peak
errs by 0.033 dB. Storage-model agreement is not proof of the internal arithmetic, but within
this band it leaves nothing for the arithmetic to explain.

Since reloads agreed and level made no difference, the generated suites now load each filter
once, with one control loaded three times; take an identity every four loads (the manifest's
`identity_bracket_every`, previously recorded but not implemented); default to one level
(-30 dBFS, `--levels` to add more). New suites: `grid` (shelf and peak, 10-20 Hz in 1 Hz steps at
Q 0.707, then shelf Q 0.5-1 and peak Q 0.5-2 at 10 Hz) and `boundary` (realistic shelves
and peaks, 10-60 Hz, whose predicted float32 error steps from 0.01 dB to the 2-4 dB these filters
reach at most). Nothing below 10 Hz: shelves and peaks are not used lower in practice. Even so,
ordinary filters err well past the requirement in float32, and erratically: +12 dB, Q 0.707 low
shelves are predicted to err by 1.67 dB at 10 Hz, 3.18 dB at 11 Hz, 0.44 dB at 12 Hz and 0.15 dB at
20 Hz, and a +6 dB, Q 0.707 shelf at 15 Hz by 0.40 dB. Catalogue manifests keep their previous
population design (three loads, both levels, every load bracketed).

The report leads with a summary and one row per filter and level: Device PASS/FAIL/UNRESOLVED
(measured vs predicted, with uncertainty) and Coefficients OK/DEGRADED (predicted vs intended),
each with a chart of intended, predicted and measured responses; swept parameters get error
charts. The per-load detail against the exact filter remains, collapsed, and in report.json.
