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
an excerpt and the full programme never share a cached analysis, but nothing in `design`
branches on it yet — that's `designer-interface.md`'s contract, not yet built here);
`--mono-only` drops the per-channel arrays and roughly halves the file, which is fine for the
`flatten` strategy alone but starves `counterfactual` and the per-channel diagnosis of the
channels they need. Without those channels, sub-feed headroom is reported as unavailable.

**`design data/FILM.npz`** — the entry point. Exit status is 0 when a candidate was accepted, 1
when abstaining was the correct output — neither is an error. Key flags:

| flag | effect |
| --- | --- |
| `--strategy NAME` (repeatable) | run only the named strategies (`flatten`, `counterfactual`, `parametric`); default `all` |
| `--exclude LOW HIGH` (repeatable) | drop an authored feature (Hz) from the target and the judgement — still manual, see TODO.md |
| `--charts DIR` | write peak/average charts per candidate into `DIR/<name>/` |
| `--record PATH` / `--no-record` | where to write the run record (default: `<material>.run.json.gz` alongside it), or skip writing one |
| `--cache PATH` / `--fresh` / `--no-cache` | the stage cache: where to keep it (default: `<material>.cache.json.gz`), force a recompute and overwrite it, or use neither |
| `--quiet` | report only, no progress log |

**`replay data/FILM.run.json.gz`** — redraws from the record alone, without touching the
extraction. `--charts DIR` for the pictures, `--beq PATH` to export a beqdesigner project. Uses
the configuration recorded with the run, including exclusions and strategy selection. Refuses if
the schema, code or available source material has changed, and says why; `--force` draws it
anyway.

**`ledger [RECORDS...]`** — every `data/*.run.json.gz` by default, or specific ones named on the
command line. `--charts-dir DIR` (default `out/ledger`) is where charts are redrawn and, unless
`--out` says otherwise, where the page (`index.html`) is written alongside them;
`--files-manifest PATH` (default `<charts-dir>/files.json`) writes `{published filename: path
under --charts-dir}`, needed only when publishing the page somewhere other than opening it
straight off disk. A stale record is skipped with a warning rather than failing the whole page;
`--force` draws it anyway.

## How it works, and why

[AGENTS.md](AGENTS.md)'s "Working on `design/`" section is the full account — principles,
strategies and evidence pricing, the evidence/confidence model, publication/playback/
verification, and performance. [TODO.md](TODO.md) is the live backlog of what's still open and
unevidenced.

## Development

```bash
uv sync
uv run pytest              # ~2 minutes, ~420 tests
uv run ruff check beqforge tools tests
uv run ruff format beqforge tools tests
```

See [AGENTS.md](AGENTS.md) for the full layout, conventions and gotchas.

## Licence

MIT — see [LICENCE.md](LICENCE.md).
