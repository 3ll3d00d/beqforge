# Device-check package

Read the repository [AGENTS.md](../AGENTS.md) first. This guidance also applies to device-check
scripts, `tests/test_device_check_*.py`, bench examples and `beqforge-device-check.spec`.
Commands and repository paths below are relative to the repository root.

## Scope and evidence

`beqforge-device-check` measures whether a frozen cascade plays on a real DSP as predicted.
It reads shared publication arithmetic from `beq_common`, and never feeds a decision into the
designer. Keep device-profile claims, predicted coefficient error and measured device error
separate. A match to the coefficient response does not establish the internal processing
precision, nor whether an authored BEQ suits a soundtrack. Unknown precision stays unknown.

The guide is [docs/device-check.md](../docs/device-check.md); implementation and measured
outcomes are in [plans/F2-device-precision-validation.md](../plans/F2-device-precision-validation.md).
Worked bench files live in `docs/device-check-examples/` and are checked by
`tests/test_device_check_examples.py`.

## Layout

| Module | Responsibility |
| --- | --- |
| `profiles.py` | Explicit device capabilities and precision claims |
| `coefficients.py`, `manifest.py`, `catalogue.py` | Frozen coefficients, source identity and catalogue manifests |
| `audio.py`, `engines.py` | Capture and device adapters, including miniDSP and CamillaDSP |
| `measurement.py`, `transactions.py` | Sweeps, response recovery and recoverable measurement transactions |
| `qualification.py`, `verify.py` | Qualification stages and reuse of evidence before further measurement |
| `analyse.py`, `report.py` | Predicted/measured errors and readable reports |
| `evidence.py` | Atomic evidence writes, attempts, locks and bundles |
| `cli.py` | Independent command-line entry point |

Preserve frozen coefficient identity, source hashes and the evidence required to replay a run.
Qualification reuse must be invalidated by changes to the bench, engine/helper, settings,
accuracy requirement, identity case or levels. Convergence evidence is per cascade.
The direct-loopback requirement depends on the declared audio route; do not silently waive it.

When a cascade needs a longer capture/finer FFT than the identity sweep, recover the identity
again from its saved raw sweep at the cascade's FFT size. Zero-padding a recovered impulse
response is not equivalent because of band-edge ringing and wrapping. Carry qualification
budgets conservatively to the new grid.

## Running and checking

```bash
uv sync --extra device-check
uv run --extra device-check pytest tests/test_device_check_*.py
uv run --extra device-check beqforge-device-check verify --config docs/device-check-examples/simulation.json
```

Use the simulation bench for an offline end-to-end check. Hardware qualification and measured
claims need actual bench evidence; a simulation does not establish device performance.
Changes confined to this package do not need the designer probe. Changes to shared arithmetic
used by the designer do; read both shared and designer instructions before making those edits.

## Executable packaging

`beqforge-device-check.spec` builds onedir/onefile previews; `BEQFORGE_DEVICE_BUILD_MODE`
selects the mode. `tools/prepare_device_check_helper.py` fetches the hash-pinned native
minidsp-rs helper and licence. `tools/smoke_test_device_check.py` runs the frozen self-test
without a live signal and assembles the checksum-bearing preview. The build workflow checks
both folder and single-file builds, including a non-ASCII output path.

Preserve the helper's pinned bytes: macOS binary processing can re-sign/rewrite it, so the
spec adds it as data after Analysis there. Elsewhere it stays a binary so dependencies are
collected. Write diagnostic text and checksum manifests with explicit UTF-8 encoding; Windows'
default CP1252 cannot represent all captured diagnostics. Frozen builds must retain shared and
device implementation provenance rather than depending on checkout source files.
