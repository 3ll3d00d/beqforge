# beqforge

Derives a corrective BEQ filter directly from a film's own audio track — the mix's own low end
is the evidence, not a catalogue of other people's filters. It decomposes the sub-managed feed,
prices what the evidence actually licenses, fits a publishable biquad cascade against that
target, and verifies the cascade it would actually play before recommending it. It abstains,
rather than guesses, when the evidence isn't there.

> NB: Code and requirements are LLM generated with human guidance/review.

One published distribution, `beqforge`, provides three independent workflow packages:

| Use case | Python package | Install profile | Command |
| --- | --- | --- | --- |
| Derive BEQ from audio | `beqforge` | `beqforge[designer]` | `beqforge` |
| Measure device playback | `beqforge_device_check` | `beqforge[device-check]` | `beqforge-device-check` |
| Optimise published coefficients | `beqoptimiser` | `beqforge[optimiser]` | `beqoptimiser` |

Install `beqforge[all]` for all three. NumPy is the common runtime dependency; each profile
adds its own requirements. The workflow packages never import one another. Shared filter
types, RBJ arithmetic and publication precision live in `beq_common`, which imports no
workflow code. All packages, commands and profiles ship in the same wheel and use one version.

[Optimiser usage](docs/optimiser.md) describes the 48/96 kHz coefficient-only library and CLI.
It requires no audio and does not participate in the audio-derived design pipeline.
The [whole-catalogue optimisation report](docs/optimiser-report/README.md) includes static
before/after charts, improvement counts and aggregate errors at 48 and 96 kHz.
The optimiser automatically reuses a bundled catalogue seed and caches new numerical results;
[cache configuration](docs/optimiser.md#automatic-result-cache) supports catalogue build jobs.

Extracted from the [`beqanalyser`](https://github.com/3ll3d00d/beqanalyser) project, whose
clustering pipeline summarises the existing [BEQ catalogue](https://beqcatalogue.readthedocs.io)
instead — the two share only the RBJ biquad arithmetic (now `beq_common/biquad.py`).

## Prerequisites

* Python 3.13 or 3.14 (pinned in `pyproject.toml`)
* [`uv`](https://docs.astral.sh/uv/) for dependency management
* `ffmpeg` on `PATH` — the only non-Python dependency, needed by `tools/extract.py`

## Install

For day-to-day use once published:

```bash
uv tool install "beqforge[designer]"      # or: pipx install "beqforge[designer]"
beqforge design data/FILM.npz
```

For working on this repo:

```bash
git clone <this repo>
cd beqforge
uv sync --all-extras
uv run python tools/design_beq.py data/FILM.npz
```

Both forms run the same code — `beqforge <subcommand>` dispatches straight to the matching
script under `tools/`, so every flag and every `--help` below applies to either invocation.

## Running the pipeline

Five scripts, each runnable on its own — a full pass is the first three in order; the last two
redraw pictures from what `design_beq.py` already wrote, so they cost no rerun. Every one takes
`--help` for its full flag list; this covers what you'd reach for day to day.

| step | command | produces |
| --- | --- | --- |
| 1. extract | `beqforge extract FILM.mkv --out data/` | `data/FILM.npz` — a 1 kHz mono mix plus per-channel decomposition, from one ffmpeg pass |
| 2. sanity-check *(optional)* | `beqforge summarise data/FILM.npz` | structural facts and an average spectrum — enough to tell a good extraction from a broken one before spending a run on it |
| 3. design | `beqforge design data/FILM.npz` | a filter and its reasoning, printed; `data/FILM.run.json.gz` written alongside the material unless `--no-record` |
| 4. redraw charts *(optional, no rerun)* | `beqforge replay data/FILM.run.json.gz --charts charts/` | peak/average PNGs per candidate, drawn from the record — no extraction, no rerun |
| 5. build the ledger *(optional, no rerun)* | `beqforge ledger` | one HTML report across every `data/*.run.json.gz`; open `out/ledger/index.html` directly in a browser |

**`extract FILM.mkv --out data/`** — `--stream N` picks a non-default audio stream (default 0);
`--name` overrides the output basename (default: the source filename's stem); `--excerpt`
records the material as less than the complete programme (folded into the stage cache's key so
an excerpt and the full programme never share a cached analysis; `design` abstains outright on
an excerpt, per `designer-interface.md`'s `coverage` field);
`--mono-only` drops the per-channel arrays and roughly halves the file. It is useful for
inspection but cannot support a design: the pipeline requires
channel decomposition and declines mono-only material. Sub-feed headroom is unavailable
without the channels.

**`design data/FILM.npz`** — the entry point. Exit status is 0 when a candidate was accepted, 1
when abstaining was the correct output — neither is an error. Key flags:

| flag | effect |
| --- | --- |
| `--strategy NAME` (repeatable) | run only the named strategies (`flatten`, `counterfactual`, `parametric`); default `all` |
| `--exclude LOW HIGH` (repeatable) | omit an authored feature (Hz) from evidence, targets and judgement; remaining fragmented evidence causes a decline — still manual, see TODO.md |
| `--goal-tilt DB_PER_OCT` | the low end you want below the knee: `0` flat (default), positive a rise toward the bottom, negative a gentle rolloff. Every target is built toward it, and results are judged and ranked against it |
| `--goal-tolerance DB` | how far from that goal the low end may already sit and be left alone (default `1.5`); a title with nothing beyond it declines with `within_goal_tolerance` |
| `--content-edge` | **opt-in, experimental.** Judge from where the title's contrast stops licensing the deficit, not from the tracking floor, so a steep filter is recovered partway, down to where the programme meets the noise, instead of declined. The price: below that point, noise can be lifted where loud scenes stand clear of it. See [TODO.md](TODO.md), "Fresh validation protocol and steep-filter policy" |
| `--charts DIR` | write peak/average charts per candidate into `DIR/<name>/` |
| `--record PATH` / `--no-record` | where to write the run record (default: `<material>.run.json.gz` alongside it), or skip writing one |
| `--cache PATH` / `--fresh` / `--no-cache` | the stage cache: where to keep it (default: `<material>.cache.json.gz`), force a recompute and overwrite it, or use neither |
| `--quiet` | report only, no progress log |

**`replay data/FILM.run.json.gz`** — redraws from the record alone, without touching the
extraction. `--charts DIR` for the pictures, `--beq PATH` to export a beqdesigner project. Uses
the configuration recorded with the run, including exclusions and strategy selection. Refuses if
the schema, code or available source material has changed, and says why; `--force` draws it
anyway.

**`serve-designer`** — runs this pipeline as a live beqdesigner filter designer over HTTP,
implementing `designer-interface.md` v1.5 §7.1 rather than working from a `.npz`/`--beq` export.
See "beqdesigner integration" below.

**`ledger [RECORDS...]`** — every `data/*.run.json.gz` by default, or specific ones named on the
command line. `--charts-dir DIR` (default `out/ledger`) is where charts are redrawn and, unless
`--out` says otherwise, where the page (`index.html`) is written alongside them;
`--files-manifest PATH` (default `<charts-dir>/files.json`) writes `{published filename: path
under --charts-dir}`, needed only when publishing the page somewhere other than opening it
straight off disk. A stale record is skipped with a warning rather than failing the whole page;
`--force` draws it anyway.

## beqdesigner integration

`beqforge serve-designer` runs this pipeline as a live, HTTP-bound filter designer for
[`beqdesigner`](https://github.com/3ll3d00d/beqdesigner), implementing its
`design/designer-interface.md` v1.5 contract (§7.1's HTTP binding) rather than the file-based
`.npz` → `design` → `--beq` export flow above:

```bash
beqforge serve-designer --port 8420
```

beqdesigner registers it by URL on its side:

```python
from pipeline.designer.registry import register_designer
from pipeline.designer.http_binding import http_designer
register_designer('beqforge.v1', http_designer('http://host:8420/design'))
```

Device realisation, which strategies run, authored exclusions, the goal (`--goal-tilt`,
`--goal-tolerance`, as for `design`) and the opt-in `--content-edge` are server-wide flags (see `--help`); everything
per-title — the audio itself, its coverage, an optional per-channel decomposition and
bass-management model — arrives in the request. The server keeps each request's full run record
(`designer-<audio>-<request>-v<design version>.run.json.gz`: one per request and design version, so a redesign
by a newer release keeps the older record), which `beqforge replay`
can redraw and export, and writes its log to `designer.log` (10 MB, five kept) as well as the
console. Both go to the per-user data directory unless moved with `--record-dir DIR` and
`--log-dir DIR`: `%LOCALAPPDATA%\beqforge` on Windows, `~/Library/Application Support/beqforge` on
macOS, `$XDG_STATE_HOME/beqforge` (else `~/.local/state/beqforge`) elsewhere, under `records` and
`logs`. `--no-record` and `--no-log-file` turn them off. `/health` reports both locations
(`record_dir`, `log_file`), `null` when off.

**Stage cache.** `--cache-dir DIR` enables the server's persistent stage cache (off by
default). Repeat requests reuse analysis and unchanged parametric proposals; changed effective
parameters or stage code invalidate only affected entries. Entries are addressed by content,
written atomically, and retained without eviction. Packaged executables use baked stage
digests. On the measured two-hour, eight-channel Alto Knights request this reduced design
time from 110 s cold to 50 s warm. See the [completed cache record](plans/R2a-server-stage-cache.md).

`--cache-dir` and `--shared-root` create missing directories, including parents, at startup.
The server checks each with a temporary-file write and removes the probe before listening.
An unusable directory causes a startup error naming the option and path.

**Audio by reference (contract 1.2).** `--shared-root DIR` permits request arrays to name a WAV
relative to that root plus the SHA-256 of its decoded column, instead of inline base64 audio.
The server resolves, decodes and checks each reference; an unusable reference gets HTTP 422
naming the array, rather than a design decline. Inline requests remain supported.
`GET /health` reports `contract_version`, whether `shared_root` is enabled, and 1.4's design
version, settings and build. Each request
logs read, parse, decode, design and response timings; `tools/experiments/request_timing.py`
measures cold and warm requests.

**Several designs at once.** `--workers N` (1-8, default 1) runs N designs at once, each in
its own worker process; further requests queue. `GET /health` reports it as `parallel`, so a
caller can send each server as many designs as it takes rather than be configured with that
number. Concurrent designs share the machine's logical processors, SMT threads included, each
at most the width one design uses alone (`BEQ_FIT_WORKERS`, if set, stays each design's own).
`--cores N` caps the processors the designs use between them, for a machine with other work to
do: concurrent designs split N evenly, and N must be at least `--workers`. The share changes
how long a fit takes, never its answer.

Every `serve-designer` configuration option can also be set through an environment variable.
Explicit CLI options take precedence; for repeatable options, CLI values replace the entire
environment list. `--help` lists the variable beside each option. Other subcommands retain
their existing CLI configuration.

| Option | Environment variable | Value |
| --- | --- | --- |
| `--host` | `BEQFORGE_HOST` | hostname or address |
| `--port` | `BEQFORGE_PORT` | integer |
| `--device-rate` | `BEQFORGE_DEVICE_RATE` | Hz |
| `--coefficient-bits` | `BEQFORGE_COEFFICIENT_BITS` | integer |
| `--integer-bits` | `BEQFORGE_INTEGER_BITS` | integer |
| `--exclude` | `BEQFORGE_EXCLUDE` | JSON array of frequency pairs, e.g. `[[18,22],[40,42]]` |
| `--goal-tolerance` | `BEQFORGE_GOAL_TOLERANCE` | dB |
| `--goal-tilt` | `BEQFORGE_GOAL_TILT` | dB per octave |
| `--content-edge` | `BEQFORGE_CONTENT_EDGE` | boolean |
| `--strategy` | `BEQFORGE_STRATEGY` | JSON array of names, e.g. `["flatten","counterfactual"]` |
| `--record-dir` | `BEQFORGE_RECORD_DIR` | path |
| `--record` | `BEQFORGE_RECORD` | boolean, default on |
| `--log-dir` | `BEQFORGE_LOG_DIR` | path |
| `--log-file` | `BEQFORGE_LOG_FILE` | boolean, default on |
| `--cache-dir` | `BEQFORGE_CACHE_DIR` | path |
| `--shared-root` | `BEQFORGE_SHARED_ROOT` | path |
| `--workers` | `BEQFORGE_WORKERS` | integer, 1-8 |
| `--cores` | `BEQFORGE_CORES` | integer, at least `--workers` |
| `--quiet` | `BEQFORGE_QUIET` | boolean |

Booleans accept `true`/`false`, `yes`/`no`, `on`/`off` or `1`/`0`, ignoring case.
`--no-content-edge` and `--no-quiet` disable settings enabled through the environment, and a
false value in the environment turns off a setting that defaults on (`BEQFORGE_RECORD=false`).
Environment values undergo the same argument validation as CLI values.

```bash
BEQFORGE_PORT=8420 \
BEQFORGE_CACHE_DIR=/var/cache/beqforge \
BEQFORGE_SHARED_ROOT=/srv/beq-audio \
BEQFORGE_STRATEGY='["flatten"]' \
beqforge serve-designer
```

**Rejected candidates.** Every candidate failed by the judge is returned in `rejected` with
its failure reasons, for review beside the accepted answer or decline. The server validates
responses against the contract before sending them.

**What a response says.** An accepted candidate's `commentary` opens with a plain-language
diagnosis, in this order:

* `found` — the reference plateau and its level; which channels carry it, and which are
  absent or digital silence; down to where there is real bass content (the low end rising and
  falling with the rest of the soundtrack); the judged band; the goal.
* `correction` — the filter; how much of what the low end is missing the content supports
  lifting; and, frequency by frequency, what was wanted, what the content supports, and the
  low end against the reference before → after.
* `clipping` — whether the filtered sub feed clips, and if so how far to turn the sub channel
  down, measured over the whole programme on the bass-managed sub feed (yours if the request
  carried `bass_management`, otherwise the assumed LR4 80 Hz model, and it says which).
  Clipping is reported, never used to reject a filter. The typed `gain_reduction_db` field is
  filled only when the request carries `bass_management`, as the contract requires.
* `fit` — how closely the filter, as the device plays it, delivers the boost the content
  supports: the typical error, the share of that boost within ±0.5 dB, and the worst miss,
  where and which way. It is a match to that target, not a verdict on whether the target is
  right; `correction` says how much of what is missing that target restores.
* `alternatives` — why each other candidate was rejected or not chosen.

The commentary then continues with `target_notes`, `verdict_notes` (what the checks themselves
noticed), `effective_params` and `beqforge_revision` (which build answered). The same fit is
in typed fields (contract 1.3): `residual_db` is the worst absolute error over
`residual_band_hz`, the band the fit was actually scored on, measured on the published filter
as the device plays it; `residual_at_hz` and `residual_direction` say where and which way;
`residual_rms_db` and `residual_within_tolerance` (against `residual_tolerance_db`) weight
each frequency by the boost asked for there, as `confidence` does. The raw
recovered and shaping fractions are kept in the run record, not the response. A decline's `decline_message` gives the reason first, then `| found: …` with
the same diagnosis, then the build in brackets. `beqforge/designer.py` is the
pure `design(request) -> response` adapter, independently testable without a socket;
`tools/designer_server.py` is the HTTP transport around it.

**Which answer a build gives (contract 1.4).** Every response, design or decline, and
`GET /health` carry `design_version`, `design_settings` and `designer_build`, whatever
`contract_version` the request names. `design_version` is an integer bumped only by a change
that can alter an answer for an unchanged request: the candidates, the rejected designs, a
decline or a fit figure. Wording, speed and
packaging don't bump it, so the executable and the image of one release report the same
version and different `designer_build`s (the string also in `beqforge_revision`). `GET
/health` also names the release, `designer_release` (`0.2.11`), for people: a build names a
revision, not a release. Releases
before it: 0.0.x and 0.1.0 are 0, 0.2.0 is 1, 0.2.1 is 2, 0.2.2 is 3, and 0.2.3 to 0.2.5
are 4, as is 0.2.7, the first release to report it. One version is one algorithm, not one
filter on every machine: the `counterfactual` and `parametric` fits can land on a different
filter on a different processor, so compare versions, never figures. `design_settings` is a 12-hex digest of the server-wide settings that can change an
answer (`--strategy`, `--exclude`, `--goal-tolerance`, `--goal-tilt`, `--content-edge`,
`--device-rate`, `--coefficient-bits`, `--integer-bits`) that differ from their defaults, so a
server started with none of them always sends the same digest. `/health` also reports those
settings as `design_settings_detail`, for reading when two designers disagree. A caller keys
each title on (`design_version`, `design_settings`) to tell which titles a new release would
answer differently.

### Running the designer in a container

`ghcr.io/3ll3d00d/beqforge-designer:<version>` runs `beqforge serve-designer` for a beqdesigner
pipeline service beside it (beqdesigner's `docker/compose.example.yaml` runs both). It is
published for linux/amd64 and linux/arm64 by `.github/workflows/build-designer-image.yml` for
each `vX.Y.Z` tag, from the same commit as that release; `latest` follows the newest release.
The release workflow (`build-executable.yml`) calls it only once the release tests have passed,
as it does for the executables and PyPI; pushes to `main` and pull requests build and
smoke-test the image without publishing it.
A manual run of that workflow with `publish` set publishes the current version's image from a
later commit, and refuses unless the designer's code is identical to that version's tag (0.2.0's
image was published this way, the recipe having arrived after the release).
Pin a version: a catalogue designed over several days should come from one designer build.

The image's defaults, all overridable with the environment variables above:

| Setting | Default | Mount |
| --- | --- | --- |
| `BEQFORGE_HOST`, `BEQFORGE_PORT` | `0.0.0.0`, `8420` | |
| `BEQFORGE_SHARED_ROOT` | `/work` | the pipeline's work directory, so audio is sent by reference |
| `BEQFORGE_CACHE_DIR` | `/cache` | a volume, so a restart keeps the stage cache |
| `BEQFORGE_RECORD_DIR` | `/records` | a volume, so run records outlive the container |
| `BEQFORGE_LOG_FILE` | `false` | none: `docker logs` keeps the console log |

It runs as uid/gid 1000 (`--build-arg PUID=… PGID=…` to change), which must be able to write
the shared root, the cache and the records: the server checks each with a write at startup. Its
`HEALTHCHECK` asks `/health`, which answers while a design runs: designs run in separate
worker processes, `BEQFORGE_WORKERS` (default 1) at a time, so a caller sending more at once
queues them; size the caller's timeout for that. `docker stop` stops a design in progress.

Build and check it locally from the repository root:

```bash
docker build -f packaging/designer/Dockerfile -t beqforge-designer .
python3 packaging/designer/smoke.py beqforge-designer
```

The smoke script checks `/health`, one design inline and one by reference, and that their run
records reached `/records`;
`tests/test_designer_image.py` runs the same check against an in-process server.

### Running the designer on Windows

The release's `beqforge-windows-x86_64.exe` runs the same server natively, for a beqdesigner
container (or install) that calls out to a Windows machine. Put `beqforge-designer.cmd`, which
is attached to the same release (source: `packaging/designer/beqforge-designer.cmd`), beside the
exe and double-click it, or run the exe directly:

```bat
beqforge-windows-x86_64.exe serve-designer --host 0.0.0.0 --port 8420 ^
  --shared-root D:\beq\work --cache-dir %LOCALAPPDATA%\beqforge\cache
```

The launcher sets the image's defaults through the environment variables above, each only if
not already set: `BEQFORGE_HOST=0.0.0.0`, `BEQFORGE_PORT=8420`,
`BEQFORGE_CACHE_DIR=%LOCALAPPDATA%\beqforge\cache` and
`BEQFORGE_RECORD_DIR=%LOCALAPPDATA%\beqforge\records`, so every request's run record is kept even
by releases before 0.2.10, which keep none unless told to. The log goes to
`%LOCALAPPDATA%\beqforge\logs\designer.log` as well as the window, so it outlives the window.
Arguments pass through to `serve-designer`.

* **Listen on the network.** The CLI's default host is `127.0.0.1`, which a container cannot
  reach; the launcher uses `0.0.0.0`. Windows Firewall asks the first time: allow private
  networks.
* **Shared root.** For audio by reference, set `BEQFORGE_SHARED_ROOT` (or edit the commented
  line in the launcher) to the Windows folder bind-mounted into beqdesigner's container as its
  work directory. Without it, beqdesigner must send audio inline.
* **beqdesigner's side.** Under Docker Desktop on the same machine, register
  `http://host.docker.internal:8420/design`; from another machine, use this one's LAN address.
  Check `http://<address>:8420/health` from there first.
* **Several at once.** Set `BEQFORGE_WORKERS` (or pass `--workers 2`) for a machine that can
  design more than one title at a time; `/health` reports it as `parallel`. To leave room for
  other work, set `BEQFORGE_CORES` to the most processors the designer may use between them.
* **The rest.** The exe is unsigned, so SmartScreen warns on first run. `serve-designer` does not need `ffmpeg`. Close the window, or
  press Ctrl+C, to stop.

### Building and releasing

For a machine without Python/`uv`, a standalone `beqforge` executable (every subcommand,
including `serve-designer`) is built for Linux/macOS/Windows by
`.github/workflows/build-executable.yml` on every `vX.Y.Z` tag, and attached to the matching
GitHub release. `beqforge.spec` is the PyInstaller build recipe; `tools/smoke_test_exe.py`
proves a built executable's `serve-designer` actually accepts a real request (not just
`--help`) before it ships — the platform-specific failure mode worth catching is Windows'
`multiprocessing` `spawn` inside a frozen executable, which only a real fit exercises. To build
one locally: `uv pip install pyinstaller && uv run pyinstaller beqforge.spec`.

The same workflow builds and checks the Python wheel and source distribution, verifies all
five dependency profiles, and reuses a successful branch-push run of `tests.yml` on `main`
at the exact tagged commit. If matching tests are still running, or GitHub's API fails to answer, it
keeps checking for up to 15 minutes;
without a successful result, it runs the reusable tests workflow against the release commit.
GitHub release creation and executable builds require those tests to pass on Linux, macOS
and Windows, including device-check tests and isolated dependency profiles. PyPI publication
also requires every executable build to pass. Release tags must match
`beq_common.__version__` exactly (`v0.1.0` for `0.1.0`);
bump that version before creating a new release tag. Both distributions are also attached
to the GitHub release. Manual workflow runs always run fresh tests and build artifacts without
publishing to PyPI.

One-time setup: configure a PyPI Trusted Publisher for project `beqforge`, owner `3ll3d00d`,
repository `beqforge`, workflow `build-executable.yml`, and GitHub environment `pypi`.
Create that environment in the repository settings. For the first publication, register a
pending publisher on PyPI if the project does not yet exist. Publishing uses GitHub's OIDC
identity with no API-token secret; see the
[PyPI Trusted Publishing guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

## Device check (preview)

`beqforge-device-check` is a separate tool from the designer. It measures whether a frozen
cascade actually plays on a DSP as predicted: miniDSP 2x4 HD, CamillaDSP, or a numerical
float64 control. It sweeps the device, recovers its response and compares that with the
response the frozen coefficients predict. It does not judge whether a BEQ is right for a
soundtrack, and nothing it measures feeds back into the designer's decisions.

```bash
uv sync --extra device-check          # or: pip install 'beqforge[device-check]'
beqforge-device-check self-test --out self-test/     # offline, no live signal
beqforge-device-check verify --config docs/device-check-examples/simulation.json  # whole flow, no hardware
```

A verification is one command against a bench file describing the device and audio route:

```bash
beqforge-device-check verify --config bench.json                        # the pilot suite
beqforge-device-check verify --config bench.json --manifest cases.json  # a frozen manifest
```

It qualifies the bench, runs the cases and writes a report under `results/` beside the bench,
printing progress and a per-case verdict against the accuracy requirement (0.1 dB by default).
Qualification stages are stored and reused, so it measures only what this bench, helper build
and sweep settings have not already proven; a repeat measures just the cases. Start a bench
file from `beqforge-device-check setup` or from an example in
[`docs/device-check-examples/`](docs/device-check-examples/), such as a miniDSP 2x4 HD measured
as a pure USB loopback. The individual stages (`plan`, `qualify`, `complete-qualification`,
`run`, `analyse`, `bundle`) remain available, as do frozen catalogue runs and offline evidence
bundles. Standalone preview executables (unsigned) are built by
`.github/workflows/build-device-check.yml`. See the [device-check guide](docs/device-check.md)
for the bench file, wiring, qualification stages, catalogue runs and packaging, and the
[F2 measurement plan](plans/F2-device-precision-validation.md) for the design behind it.

## How a filter is designed

The idea in one line: **find out how much low bass the film's own soundtrack is missing, work
out how much of that is safe to put back, and build the simplest filter that does it.**

**1. Look at what the soundtrack actually contains.** A well-mastered mix has a level it
holds across the bass range, its "plateau". Many film mixes then sag below some frequency —
sometimes by design, sometimes because a rolloff was applied in mastering. The gap between
that sag and the plateau is the *deficit*, and it is what a BEQ (bass EQ) exists to fill. The
plateau is found from each title's own audio; no frequency range is assumed in advance.

**2. Decide how much of the deficit is believable.** Boosting is only safe where there is real
bass to lift. The tool compares the loudest passages with the quietest ones, frequency by
frequency: where big bass events clearly stand out from the background, the boost is
justified; where they don't, whatever is down there is probably noise, and boosting it would
just make the noise louder. So every frequency gets a *ceiling* on how much boost the evidence
supports, and the wanted correction is cut down to fit under it — a boost may be smaller than
the sag it aims at, but never larger than the evidence allows. If there is no evidence at all
(a short excerpt, no channel information, no real bass events), no boost is allowed and the
tool declines to design anything.

**3. Propose targets in more than one way.** Three strategies each say "this is the boost
curve we want", and all of them go through the same ceiling:

* **flatten** — take the mix's own low end and simply raise the sag back to the plateau.
* **counterfactual** — look at the individual channels, undo the attenuation that appears to
  have been applied to any that look filtered, rebuild the mix, and see how much the low end
  would have gained. It tries several limits on how far to undo each channel.
* **parametric** — fit a textbook rolloff shape to the mix and invert it.

They often disagree, and that disagreement is information, so the tool keeps them all.

**4. Fit a filter you could actually publish.** Each target is matched with the fewest
biquad sections that follow it closely (up to four), using values rounded the way a real
device would store them. It has to be stable, and it can't lean on a tiny bass boost far below
where the film has any content.

**5. Check the filter, not just the fit.** The finished filter is applied to the film's real
audio and the corrected low end is examined. It is rejected if it does not achieve what the
evidence allowed, boosts something that isn't content, leaves a step or sharp cliff, is wobblier
than the original material, stops short of where content continues, or has a section doing
almost nothing. A filter that matches its target perfectly still fails if the target itself
was wrong — which is why the check is made on the corrected result, not on the match.

**6. Pick one, or none.** Of the candidates that pass, the tool prefers the one closest to
the goal, and where two are effectively tied, the one with fewer sections. If nothing passes,
it says so and gives the reasons; that is a valid answer, not a failure.

**The goal is yours to set.** "Put the missing bass back" needs a definition of how the low
end *should* look, and that is a preference, not something the audio can say. By default the
goal is flat below the knee, and a low end already within 1.5 dB of it is left alone. So is a
low end whose shortfall is no bigger than the ripple the soundtrack shows anyway, higher up
where nothing is missing — that is texture, not a missing low end. The goal
can instead rise toward the bottom or roll off gently (`--goal-tilt`), and the tolerance can be
widened or narrowed (`--goal-tolerance`). Steps 1-3 build toward the goal you set, and steps
5-6 judge and rank against it, so changing it changes what is proposed, not just what is
kept.

Two things are reported alongside the answer rather than folded into a score: how much of the
sag the filter actually recovers (it is often only part), and how much headroom the boosted
subwoofer signal would need. Headroom is measured on the bass-managed sub feed, which is where
a BEQ really runs, and it is reported, never used to reject a filter. The tool also cannot tell
from the audio alone whether a sag was a deliberate mastering choice, so choosing to restore it
is always a preference; the guarantee is only that the boost stays within what was measured.
[AGENTS.md](AGENTS.md) has the precise rules behind each step.

## How it works, and why

[AGENTS.md](AGENTS.md)'s "Working on `design/`" section is the full account — principles,
strategies and evidence pricing, the evidence/confidence model, publication/playback/
verification, and performance. [TODO.md](TODO.md) is the sole prioritised backlog, including
open policy questions, parked experiments and validation material. Historical evidence lives
in [implemented changes](plans/done-design-and-pipeline.md),
[research decisions](plans/research-design-decisions.md) and
[baseline evidence](plans/done-baseline-evidence.md).

## Development

```bash
uv sync --all-extras
uv run --all-extras pytest
uv run ruff check beq_common beqforge beqforge_device_check beqoptimiser tools tests
uv run ruff format beq_common beqforge beqforge_device_check beqoptimiser tools tests
```

See [AGENTS.md](AGENTS.md) for the full layout, conventions and gotchas.

## Licence

MIT — see [LICENCE.md](LICENCE.md).
