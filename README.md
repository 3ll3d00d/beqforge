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

* Python 3.13 (pinned in `pyproject.toml`)
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
`--mono-only` drops the per-channel arrays and roughly halves the file, which is fine for the
`flatten` strategy alone but starves `counterfactual` and the per-channel diagnosis of the
channels they need. Without those channels, sub-feed headroom is reported as unavailable.

**`design data/FILM.npz`** — the entry point. Exit status is 0 when a candidate was accepted, 1
when abstaining was the correct output — neither is an error. Key flags:

| flag | effect |
| --- | --- |
| `--strategy NAME` (repeatable) | run only the named strategies (`flatten`, `counterfactual`, `parametric`); default `all` |
| `--exclude LOW HIGH` (repeatable) | drop an authored feature (Hz) from the target and the judgement — still manual, see TODO.md |
| `--goal-tilt DB_PER_OCT` | the low end you want below the knee: `0` flat (default), positive a rise toward the bottom, negative a gentle rolloff. Every target is built toward it, and results are judged and ranked against it |
| `--goal-tolerance DB` | how far from that goal the low end may already sit and be left alone (default `1.5`); a title with nothing beyond it declines with `within_goal_tolerance` |
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
implementing `designer-interface.md` v1.0 §7.1 rather than working from a `.npz`/`--beq` export.
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
`design/designer-interface.md` v1.0 contract (§7.1's HTTP binding) rather than the file-based
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

Device realisation, which strategies run, authored exclusions and the goal (`--goal-tilt`,
`--goal-tolerance`, as for `design`) are server-wide flags (see `--help`); everything
per-title — the audio itself, its coverage, an optional per-channel decomposition and
bass-management model — arrives in the request. `--record-dir DIR` also writes each request's
full run record into `DIR` (`designer-<digest>.run.json.gz`, named by a digest of the request's
audio), which `beqforge replay` can redraw and export.

**What a response says.** An accepted candidate's `commentary` opens with a plain-language
diagnosis, in this order:

* `found` — the reference plateau and its level; which channels carry it, and which are
  absent or digital silence; how far down the programme tracks it; where the attenuation
  stops being level-invariant; which channels show a steep knee; the judged band; the goal.
* `correction` — how much boost the deficit asked for against how much the evidence allowed
  (as a share of what the low end is missing), the filter, the low end against the reference
  before → after, and how much of the boost lies below the frequency where loud and quiet
  scenes stop agreeing on the shape of the low end — the part not backed by that fixed-filter
  check, which rests on your goal instead.
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
verification, and performance. [TODO.md](TODO.md) is the live backlog of what's still open and
unevidenced, and [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) is the reviewed list of weaknesses in
the process itself, each with a check, and the kinds of test material needed to run them.

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
