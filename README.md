# beqforge

Derives a corrective BEQ filter directly from a film's own audio track — the mix's own low end
is the evidence, not a catalogue of other people's filters. It decomposes the sub-managed feed,
prices what the evidence actually licenses, fits a publishable biquad cascade against that
target, and verifies the cascade it would actually play before recommending it. It abstains,
rather than guesses, when the evidence isn't there.

> NB: Code and requirements are LLM generated with human guidance/review.

Extracted from the [`beqanalyser`](https://github.com/3ll3d00d/beqanalyser) project, whose
clustering pipeline summarises the existing [BEQ catalogue](https://beqcatalogue.readthedocs.io)
instead — the two share only the RBJ biquad arithmetic (`beqforge/biquad.py`).

## Prerequisites

* Python 3.13 or 3.14 (pinned in `pyproject.toml`)
* [`uv`](https://docs.astral.sh/uv/) for dependency management
* `ffmpeg` on `PATH` — the only non-Python dependency, needed by `tools/extract.py`

## Install

For day-to-day use once published:

```bash
uv tool install beqforge      # or: pipx install beqforge
beqforge design data/FILM.npz
```

For working on this repo:

```bash
git clone <this repo>
cd beqforge
uv sync
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
implementing `designer-interface.md` v1.2 §7.1 rather than working from a `.npz`/`--beq` export.
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
`design/designer-interface.md` v1.2 contract (§7.1's HTTP binding) rather than the file-based
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
bass-management model — arrives in the request. `--record-dir DIR` also writes each request's
full run record into `DIR` (`designer-<digest>.run.json.gz`, named by a digest of the request's
audio), which `beqforge replay` can redraw and export.

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
`GET /health` reports `contract_version` and whether `shared_root` is enabled. Each request
logs read, parse, decode, design and response timings; `tools/experiments/request_timing.py`
measures cold and warm requests.

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
| `--cache-dir` | `BEQFORGE_CACHE_DIR` | path |
| `--shared-root` | `BEQFORGE_SHARED_ROOT` | path |
| `--quiet` | `BEQFORGE_QUIET` | boolean |

Booleans accept `true`/`false`, `yes`/`no`, `on`/`off` or `1`/`0`, ignoring case.
`--no-content-edge` and `--no-quiet` disable settings enabled through the environment.
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
* `alternatives` — why each other candidate was rejected or not chosen.

The commentary then continues with `target_notes`, `verdict_notes` (what the checks themselves
noticed), `effective_params` and `beqforge_revision` (which build answered). The raw
recovered and shaping fractions are kept in the run record, not the response. A decline's `decline_message` gives the reason first, then `| found: …` with
the same diagnosis, then the build in brackets. `beqforge/designer.py` is the
pure `design(request) -> response` adapter, independently testable without a socket;
`tools/designer_server.py` is the HTTP transport around it.

For a machine without Python/`uv`, a standalone `beqforge` executable (every subcommand,
including `serve-designer`) is built for Linux/macOS/Windows by
`.github/workflows/build-executable.yml` on every `vX.Y.Z` tag, and attached to the matching
GitHub release. `beqforge.spec` is the PyInstaller build recipe; `tools/smoke_test_exe.py`
proves a built executable's `serve-designer` actually accepts a real request (not just
`--help`) before it ships — the platform-specific failure mode worth catching is Windows'
`multiprocessing` `spawn` inside a frozen executable, which only a real fit exercises. To build
one locally: `uv pip install pyinstaller && uv run pyinstaller beqforge.spec`.

## Device check (preview)

`beqforge-device-check` is a separate tool from the designer. It measures whether a frozen
cascade actually plays on a DSP as predicted: miniDSP 2x4 HD, CamillaDSP, or a numerical
float64 control. It sweeps the device, recovers its response and compares that with the
response the frozen coefficients predict. It does not judge whether a BEQ is right for a
soundtrack, and nothing it measures feeds back into the designer's decisions.

```bash
uv sync --extra device-check          # or: pip install 'beqforge[device-check]'
beqforge-device-check self-test --out self-test/     # offline, no live signal
```

A run goes through `setup` → `plan` → `qualify` → `run` → `analyse` → `bundle`. It can also
measure frozen catalogue cascades and import offline evidence bundles. Standalone preview
executables (unsigned, hardware qualification still outstanding) are built by
`.github/workflows/build-device-check.yml`. See the [device-check guide](docs/device-check.md)
for the bench wiring, qualification stages, catalogue runs and packaging, and the
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
uv sync
uv run pytest              # ~2 minutes, ~460 tests
uv run ruff check beqforge tools tests
uv run ruff format beqforge tools tests
```

See [AGENTS.md](AGENTS.md) for the full layout, conventions and gotchas.

## Licence

MIT — see [LICENCE.md](LICENCE.md).
