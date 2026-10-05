# Device precision measurement preview

`beqforge-device-check` is separate from the film designer. It measures whether a frozen
cascade plays as predicted. It does not establish whether a catalogue BEQ is correct for a
soundtrack, and it changes no designer realisation assumptions or Q limits.

Install measurement extras with `uv sync --extra device-check`, or
`pip install 'beqforge[device-check]'`. The first profiles are miniDSP 2x4 HD (96 kHz,
float32 stated format, ten PEQs per input/output), CamillaDSP and a numerical float64 control.
Profile claims and measured evidence remain separate. Custom bench JSON can define other
explicit device capabilities; unknown storage precision must remain labelled unknown.

## One command

Once a bench file exists, a verification is one command:

```bash
beqforge-device-check verify --config bench.json                        # the pilot suite
beqforge-device-check verify --config bench.json --manifest cases.json  # a frozen manifest
```

It qualifies, assembles, runs and analyses, printing progress and a per-case summary, and
writes `results/<UTC time>/` (qualification, run, report) beside the bench. It measures only
what nothing stored already proves. Identity and device bypass never involve the cascades
under test, so they are kept in `store/` beside the bench, keyed on the bench, engine, sweep
settings, accuracy requirement, identity case and levels, and reused by any manifest that
shares those. Convergence is kept per cascade: a new manifest converges only the cascades no
stored record covers, and a repeat converges none. Change any of those inputs (another
machine, helper build, sweep settings) and the affected stages are measured again. An
all-digital bench waives direct loopback; an analogue bench stops and asks for it once
(`--direct-loopback 'how it is wired'`, after rewiring). The individual commands below remain
for inspecting or reproducing a stage by hand.

## The bench file

A bench file is JSON describing the device, the audio route and what you have established
about it. Every stage records its hash, so changing any field invalidates what was measured
with it (`verify` then measures again). Two worked examples, kept valid by
`tests/test_device_check_examples.py`:

* [`minidsp-2x4hd-usb-loopback.json`](device-check-examples/minidsp-2x4hd-usb-loopback.json):
  a miniDSP 2x4 HD measured as a pure USB loopback on Windows, the route set by device-check.
  Measured on real hardware.
* [`simulation.json`](device-check-examples/simulation.json): the offline numerical control.
  `verify --config docs/device-check-examples/simulation.json` runs the whole flow with no
  hardware, a good first check of an installation.

Either `beqforge-device-check setup` (interactive; `--profile`, `--executable`) or copy the
closest example and edit it. For the USB-loopback example, change:

1. `engine.executable`: the minidsp-rs helper, an absolute path (`"bundled"` in the
   standalone executable). It must report `minidsp 0.1.12`.
2. `engine.serial`: from `minidsp probe` (the unit is always selected by serial, never by
   discovery order).
3. `audio.input.name`, `audio.output.name`, `host_api`: exactly as `beqforge-device-check
   devices` lists them. Names differ by OS and host API; on Windows prefer `Windows WDM-KS`
   or WASAPI with `"exclusive": true` under `audio`, which bypass the Windows mixer.
4. `firmware_or_build`, `unit_id`: free text for the record (`unit_id` may be pseudonymous).

Then check it offline: `beqforge-device-check plan --config bench.json --out cases.json`
validates the file without touching the device.

| Field | Meaning |
| --- | --- |
| `profile` | The device profile, copied unchanged from `beqforge-device-check profiles` (routes, rates, stated coefficient format). Editing it changes what is claimed about the device. |
| `rate` | Stream and DSP rate; must be one of the profile's internal rates. |
| `route`, `channel` | The PEQ bank under test, e.g. `input` 0. |
| `engine_mode` | `minidsp`, `camilladsp-live`, `camilladsp-file` or `simulation`. |
| `engine.route_commands` | Optional: miniDSP setting commands device-check applies at the start of every live stage (see "Electrical bench"). Also the default restoration. |
| `engine.restore_commands` | Optional when `route_commands` is given: what to send after each stage. The master is always left muted. |
| `audio.input` / `audio.output` | Capture and playback device (`name`, `host_api`), how many channels to open, and which one carries the DUT. |
| `audio.output.reference_channel` | Optional: a playback channel that also carries the sweep, feeding the timing-reference path (needed when the reference is not split externally, as in a USB loopback). |
| `audio.exclusive` | Optional: open both ends in WASAPI exclusive mode (Windows WASAPI only). |
| `reference_channel` | Optional: the capture channel of a timing reference that bypasses the PEQ under test. Gives exact delay and measured clock drift. |
| `common_clock`, `clock_basis` | Whether playback and capture share one clock, and how you know. Completion needs either this or a `reference_channel`. |
| `all_digital`, `all_digital_basis` | Declare that playback and capture are the DUT's own digital interface; waives the direct-loopback stage, recorded with this reason. |
| `electrical_bench_acknowledged` | Your statement that nothing amplified is connected. A live stage refuses without it. |
| `firmware_or_build`, `physical_route`, `unit_id` | Free-text records of the device and wiring; device-check cannot detect wiring. |

## Offline check

```bash
beqforge-device-check self-test --out self-test/
beqforge-device-check setup --profile simulation-float64 --out bench.json
beqforge-device-check plan --config bench.json --suite pilot --out cases.json
beqforge-device-check qualify --config bench.json --manifest cases.json --accuracy-db 0.1 --out qualification/
beqforge-device-check run --config bench.json --manifest cases.json --qualification qualification/ --out run/
beqforge-device-check analyse run/ --out run/
beqforge-device-check bundle run/ --out results.zip
```

The engineering requirement is a predeclared experiment setting, not a filter acceptance
threshold. The default exponential sweep is 5 seconds, 2–200 Hz, after a 0.5-second pre-roll
(`--preroll`; it must exceed the transport delay and is the noise estimate) and before a zero
tail of at least 1 second (`--tail`). Each cascade's tail is extended to its own settling time
(decay to −120 dB), so only a ringing cascade pays for a long one; convergence doubles that
too. These are starting settings, not proof that 2 Hz is measurable; the convergence stage
tests them. The manifest freezes nominal −30/−50 dBFS blocks, reduced where a
sampled intermediate-gain screen requires more attenuation. This does not prove internal
state headroom; clipping still aborts a run. Unsupported/unstable cases are retained.

`self-test` exercises known-transfer recovery, evidence transactions, reports and a local ZIP.
It emits no live signal. It reports unavailable/stalled host audio discovery separately;
numerical success does not prove hardware compatibility. The capture implementation uses
bounded RAM rather than writing files inside the callback; maximum RAM is a bench setting.
Use `self-test --skip-audio-discovery --out DIR` for completely offline testing without
enumerating audio devices. This also exercises assembly/replay of all qualification stages.

## CamillaDSP reference

Install the explicitly pinned CamillaDSP 4.1.3 build separately and retain its provenance.
For a file-processing control:

```bash
beqforge-device-check setup --profile camilladsp-float64 --engine-mode camilladsp-file --executable /absolute/path/to/camilladsp --out camilla.json
beqforge-device-check plan --config camilla.json --out camilla-cases.json
```

Continue with `qualify`, `run` and `analyse` using that config/manifest. The control sends
explicit Free biquad coefficients at the profile's internal rate through raw float64 files.
Its result names that scope; file I/O does not validate the live virtual or physical route.
The float64 claim must be verified for the chosen build; float64 PCM alone does not prove it.
Live websocket control accepts an explicit mono bench template with resampling disabled.

## Electrical bench

Use `devices` to list named audio devices/host APIs, then guided `setup` for the miniDSP.
Connect measurement output → DUT input → DUT output → interface line input, with loudspeakers
and amplifiers disconnected. Record firmware, serial, actual internal rate, input/output ports,
transport rates/gains and enabled processing. Setup records an explicit bench acknowledgement
before a live signal. It cannot infer physical wiring from a USB control connection.

The miniDSP helper is currently an explicit external minidsp-rs 0.1.12 executable. Select a
serial, never discovery order. Provide complete restoration commands as JSON argument arrays;
master-status readback cannot recover the whole device configuration. The adapter restores
those commands but cannot verify coefficient bits, so it leaves the device muted and reports
unverified restoration. Review the saved state with the official device software before reuse.

Setup can also let device-check set the signal path itself, only when you type `CONFIGURE`.
Its bench then carries `engine.route_commands`: input 0 feeds only output 0 (the DUT path),
input 1 only output 1 (a timing reference that never passes input 0's PEQ bank), unused outputs
are muted, and gain, mute, delay, invert, PEQ, FIR, crossover and compressor on the used outputs
are neutral or bypassed — bypassed rather than cleared, so stored filters survive. Every live
stage except direct loopback applies the route at its start and records it in the snapshot;
without separate restoration commands, restoration re-applies it, muted. It also selects the USB
source, so it is for a pure USB loopback (USB playback → DSP → USB capture). It does not save or
read back the previous configuration. Commands are sent as one `minidsp -f` batch rather than
one helper process each, as are each case's coefficient loads.

Qualification has four recorded stages. Run them against the same frozen manifest, bench
configuration, sweep settings and predeclared accuracy requirement, using different output
directories. The default `--stage identity` gathers at least five independently loaded
active identities per level. It remains incomplete until the supporting stages are assembled:

```bash
beqforge-device-check qualify --config bench.json --manifest cases.json --accuracy-db 0.1 --stage identity --out qualification/
# Reconnect the interface output directly to its capture input before this stage.
# This stage opens the configured audio stream but sends no miniDSP control commands.
beqforge-device-check qualify --config bench.json --manifest cases.json --accuracy-db 0.1 --stage direct-loopback --path-description 'Interface output 1 directly to line input 1' --out direct/
# Restore the documented DUT wiring before the following stages.
beqforge-device-check qualify --config bench.json --manifest cases.json --accuracy-db 0.1 --stage device-bypass --path-description 'DUT route with selected input PEQ bank bypassed' --out bypass/
beqforge-device-check qualify --config bench.json --manifest cases.json --accuracy-db 0.1 --stage convergence --out convergence/
beqforge-device-check complete-qualification qualification/ --supporting direct/ --supporting bypass/ --supporting convergence/
```

The bypass stage bypasses the selected miniDSP PEQ bank, not every processing stage. Other
stages must already be disabled or documented in setup. Convergence doubles sweep duration
and retained tail independently for identity and every planned cascade; it does not refit or
remove gain. A large catalogue can take substantial time even at this stage. Start with the
pilot, then qualify the exact catalogue manifest/settings/levels before its batch.

An all-digital bench, where playback and capture are the DUT's own digital audio interface
(for example a pure USB loopback through a miniDSP), has no separate interface to loop back.
Declare it in the bench with `"all_digital": true` and an `all_digital_basis` (setup asks).
The direct-loopback stage then refuses to run, and completion accepts the identity, bypass and
convergence stages alone, recording the waiver and its basis in the qualification's
`waived_stages` and scope.

Completion checks hashes, matching settings/engine, masks and measured repeatability,
inversion/noise bounds and convergence. Only their common usable bins qualify. Missing,
stale or under-range evidence refuses completion. Set `common_clock: true` and describe its
established basis in `clock_basis`, or supply an independent `reference_channel` in the bench
JSON. Merely sharing a nominal sample rate is not a shared clock. Timing-reference captures
reject excess measured drift. Setup asks for these fields; wiring descriptions are operator
records, not automatic electrical-route detection.

Supporting raw captures/stimuli and transport records travel with completed qualification
and the run bundle. Numerical/file controls can run against identity-only qualification;
live `run` refuses incomplete qualification. No target OS or device is bench-validated yet.
The [F2 measurement plan](../plans/F2-device-precision-validation.md) retains the hardware
pilot, arithmetic/noise/ring-out experiments and release criteria.

The pinned miniDSP CLI parses PEQ coefficients as float32 and writes float32 to the 2x4 HD
transport. Reports therefore retain requested coefficients separately from the float32 sent
coefficients. Sending more decimal digits cannot remove that conversion. Sent bits are still
not coefficient storage readback or proof of recursive arithmetic. The source references are
[`FilterCommand::Set`](https://github.com/mrene/minidsp-rs/blob/v0.1.12/minidsp/src/bin/minidsp/main.rs)
and the [2x4 HD dialect](https://github.com/mrene/minidsp-rs/blob/v0.1.12/protocol/src/device/m2x4hd.rs).

Every run saves exact stimuli, raw captures, sent payloads, partial attempts, identities and
restoration status. Ctrl-C and failures stop the transaction; no timed-out sweep is retried
automatically. `run --resume` requires matching bench/manifest/qualification and starts with a
new identity. A surviving `.run.lock` needs operator inspection, not automatic deletion.

## Frozen catalogue

Supply a local ezbeq `database.json` snapshot and explicit source revision and attribution:

```bash
beqforge-device-check catalogue-plan --config bench.json --catalogue snapshot.json --revision SOURCE_REVISION --attribution 'SOURCE AND LICENCE' --complete-snapshot --out catalogue-cases.json
beqforge-device-check catalogue-entry --config bench.json --catalogue snapshot.json --revision SOURCE_REVISION --attribution 'SOURCE AND LICENCE' --entry ENTRY_DIGEST --out one-entry/
```

The second command freezes an entry-specific manifest first; qualify it, then run it.
Planning archives the original snapshot bytes and every supported/unsupported entry.
`--complete-snapshot` is an explicit completeness declaration, not a guessed result from one
downloaded page. Missing Q/type/channel applicability remains unsupported. Identical ordered
cascades can share a measurement; `--no-deduplicate` keeps reload variability separate.
Published offsets are retained and reported separately rather than silently applied/dropped.
Channel-specific schemas are currently unsupported and visible in the inventory.

`catalogue-analyse run-a/ run-b/ --out comparison/` retains matched cascades, all repeats/levels,
separate engine configurations and unmatched counts. Reports show signed errors and missing
bins, identity uncertainty, frequency excursions, individual traces and separate entry/unique
cascade weighting. A thousand catalogue entries on one device are not independent units.

Single-run HTML reports include catalogue error plots and qualified counts. JSON includes
per-frequency median, 90th/95th percentile, maximum error and fractions above the predeclared
requirement, separately weighted by entries and unique cascades. A 128-point logarithmic display
grid interpolates only between adjacent qualified native bins; no gap is bridged and every
frequency carries its denominator. Reloads contribute a cascade's maximum absolute error,
median signed error and maximum uncertainty, rather than counting as additional cascades.
Matched-device JSON compares equal levels on shared qualified bins, with signed differences,
combined uncertainty, missing coverage and individual reload-pair evidence IDs.

Per-case `accuracy_assessment` distinguishes bins inside the requirement including uncertainty,
bins exceeding it even after uncertainty, unresolved bins and unqualified bins. This applies
only to the measured valid band. Characteristics include section count, lowest corner, Q and
predicted quantisation departure for subsequent population investigation.

For offline precision controls, a simulation bench can set `storage_model` to `float32` or
`float64`, independently of `arithmetic` (`float32` or `float64`, default float64). The former
rounds stored coefficients; the latter selects SciPy's recursive processing precision. This
is a named numerical control, not an emulation of a proprietary DSP implementation. Different
settings require fresh qualification because they change engine identity.

Bundles are local exports; nothing uploads automatically. `--summary-only` excludes raw arrays
and is marked insufficient for replay. Bundling verifies registered evidence and excludes
unrelated files. Review the exported bench/device facts and restore settings before sharing.

## Standalone previews

`beqforge-device-check.spec` has separate folder and single-file modes. Prepare the helper
on the native target, then build with PyInstaller 6.22.3 and the locked `device-check` extra:

```sh
uv sync --locked --extra device-check
uv pip install pyinstaller==6.22.3
uv run python tools/prepare_device_check_helper.py --target linux-x86_64 --out build/device-helper --cache build/helper-cache
BEQFORGE_DEVICE_BUILD_MODE=onedir uv run pyinstaller --clean --noconfirm --distpath dist/folder beqforge-device-check.spec
uv run python tools/smoke_test_device_check.py dist/folder/beqforge-device-check/beqforge-device-check --out 'build/folder test é'
uv run pyinstaller --clean --noconfirm --distpath dist/single beqforge-device-check.spec
uv run python tools/smoke_test_device_check.py dist/single/beqforge-device-check --out 'build/single test é' --package dist/preview-linux-x86_64
```

The dedicated workflow builds Linux x86_64 on Ubuntu 22.04 (glibc 2.35 baseline), Windows
x86_64 on Windows Server 2022, and macOS arm64/x86_64 separately on macOS 15 runners.
These are build/test environments, not evidence of support for older operating systems.
Every target checks its native architecture and hash-pinned miniDSP 0.1.12 helper, preserves
upstream notices, and runs a substantive frozen numerical self-test before uploading a
checksum-bearing preview. Cross-platform CI has not yet run for this implementation.
The local Linux build on this development host does not claim the Ubuntu 22.04 baseline.

The single executable extracts its helper to PyInstaller's private runtime directory.
Saved bench files use `"executable": "bundled"` to resolve the current extraction directory;
an explicit path selects an external helper instead. Engine identity records its exact
version and SHA-256. CamillaDSP remains separately installed. Audio/USB drivers, Linux
host audio services, USB permissions and macOS microphone permission remain host setup.
The preview is unsigned and unnotarised; Windows ASIO has not been verified. Distribution
metadata and helper/native notices accompany the artifact. Hardware qualification and the
pilot are required on each claimed target before it can become a validated release.

## Offline exchange and interrupted captures

```sh
beqforge-device-check import-bundle results.zip --out imported-run/
beqforge-device-check analyse imported-run/ --out replayed-report/
```

Import requires per-file SHA-256, rejects duplicate/unregistered/traversing/symlink paths and
bounds uncompressed size to 2 GiB. It validates every file in a temporary directory before
exposing the destination. The destination must be new. Imported evidence is for offline
analysis; it cannot resume live control. Summary bundles retain their insufficient-for-replay
label. Local exports preserve bench identities and host configuration; automatic redacted
community export is still pending, so this preview does not claim a share-safe bundle.

A failed stream retains the samples captured so far, actual stream settings, callback
statuses and timestamps. The transaction marks them invalid, stops the run and attempts
restoration. A stream rate differing from the requested rate aborts. Partial capture does
not become a completed measurement and is never automatically retried.
