# Device precision measurement preview

`beqforge-device-check` is separate from the film designer. It measures whether a frozen
cascade plays as predicted. It does not establish whether a catalogue BEQ is correct for a
soundtrack, and it changes no designer realisation assumptions or Q limits.

Install measurement extras with `uv sync --extra device-check`, or
`pip install 'beqforge[device-check]'`. The first profiles are miniDSP 2x4 HD (96 kHz,
float32 stated format, ten PEQs per input/output), CamillaDSP and a numerical float64 control.
Profile claims and measured evidence remain separate. Custom bench JSON can define other
explicit device capabilities; unknown storage precision must remain labelled unknown.

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
threshold. The default sweep is 30 seconds, 2–200 Hz, with pre-roll and a 15-second zero tail.
These are starting settings, not proof that 2 Hz is measurable. Extend the tail when a case's
pole decay requires it. The manifest freezes nominal −30/−50 dBFS blocks, reduced where a
sampled intermediate-gain screen requires more attenuation. This does not prove internal
state headroom; clipping still aborts a run. Unsupported/unstable cases are retained.

`self-test` exercises known-transfer recovery, evidence transactions, reports and a local ZIP.
It emits no live signal. It reports unavailable/stalled host audio discovery separately;
numerical success does not prove hardware compatibility. The capture implementation uses
bounded RAM rather than writing files inside the callback; maximum RAM is a bench setting.

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

The miniDSP helper is currently an explicit external minidsp-rs 0.1.9 executable. Select a
serial, never discovery order. Provide complete restoration commands as JSON argument arrays;
master-status readback cannot recover the whole device configuration. The adapter restores
those commands but cannot verify coefficient bits, so it leaves the device muted and reports
unverified restoration. Review the saved state with the official device software before reuse.

Qualification currently gathers active identity repeatability at both levels. It is labelled
**incomplete**: direct interface loopback, device bypass, sweep/tail convergence, clock/noise
and pilot evidence must be added before a live batch is licensed. Numerical/file controls can
run against identity qualification; live `run` refuses incomplete qualification. No published
target OS or device is bench-validated yet. See the [F2 measurement plan](../plans/F2-device-precision-validation.md)
for the remaining protocol, arithmetic/noise/ring-out tests and release criteria.

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

Bundles are local exports; nothing uploads automatically. `--summary-only` excludes raw arrays
and is marked insufficient for replay. Bundling verifies registered evidence and excludes
unrelated files. Review the exported bench/device facts and restore settings before sharing.
