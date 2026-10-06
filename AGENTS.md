# AGENTS.md

Repository-wide working notes for coding agents. Human-facing documentation lives in
[README.md](README.md). Commands and paths here are relative to the repository root.

## Repository structure and boundaries

One published distribution, `beqforge`, contains independent workflow packages and neutral
shared primitives. One root `pyproject.toml` and `uv.lock` govern every package; do not create
separate projects, versions or release processes for individual workflows. Workflow packages
must not import each other; shared primitives must not import workflows.

| Directory | Scope | Instructions |
| --- | --- | --- |
| `beqforge/` | Audio-derived BEQ designer | [beqforge/AGENTS.md](beqforge/AGENTS.md) |
| `beqforge_device_check/` | DSP measurement and qualification | [beqforge_device_check/AGENTS.md](beqforge_device_check/AGENTS.md) |
| `beqoptimiser/` | Published coefficient optimisation | [beqoptimiser/AGENTS.md](beqoptimiser/AGENTS.md) |
| `beq_common/` | Shared filter arithmetic, types and provenance | [beq_common/AGENTS.md](beq_common/AGENTS.md) |
| `tools/`, `tests/` | Scripts and tests for the packages | Read the owning package's instructions before editing |
| `docs/`, `plans/` | Human-facing guides and recorded outcomes | Read the owning package's instructions for behavioural changes |
| `.github/workflows/`, root `*.spec` | CI, release and executable packaging | Read the affected package's instructions too |

The distribution offers `designer`, `device-check`, `optimiser` and `all` dependency profiles,
and separate `beqforge`, `beqforge-device-check` and `beqoptimiser` entry points.
`beq_common.__version__` is the single version source. NumPy is the base runtime dependency;
install other dependencies through the relevant extra. Package boundary and isolated-profile
checks live in `tests/test_package_boundaries.py` and `tools/smoke_test_install.py`.

[TODO.md](TODO.md) is the sole prioritised backlog, including open decision questions and
validation requirements. Completed implementations and research decisions live under `plans/`;
these are historical evidence, not additional work queues. Record behavioural changes and
validation outcomes in the relevant plan, and update any backlog item they resolve.

## Development and validation

Python is pinned to `>=3.13,<3.15`. If the venv's interpreter disappears, `uv sync` may recreate
it against another interpreter in that range.

```bash
uv sync --all-extras
uv run pytest
uv run ruff check beqforge beqforge_device_check beqoptimiser beq_common tools tests
uv run ruff format beqforge beqforge_device_check beqoptimiser beq_common tools tests
uv build
```

Run tests appropriate to the change and the checks required by the owning package.
Designer changes and changes to shared primitives reached by the designer require the
regression procedure in [beqforge/AGENTS.md](beqforge/AGENTS.md). Changes confined to device
check or optimiser do not require that probe. Documentation-only changes need link/content
checks, not numerical runs. Do not edit modules while a background validation process is
importing them; use an isolated worktree for simultaneous experiments.

## Packaging and releases

The root build configuration includes every workflow and the optimiser's bundled seed in one
wheel and source distribution. `.github/workflows/tests.yml` checks isolated dependency
profiles. `.github/workflows/build-executable.yml` builds release executables and distributions;
tag pushes publish to PyPI after validation and successful executable builds. Tags must match
the shared version exactly (`vX.Y.Z`). Manual runs build artifacts without publishing.
PyPI uses the `pypi` environment and Trusted Publishing; setup details are in the README.
Device-check preview executable packaging has its own workflow, not a separate Python release.

## Conventions

* British spelling in prose and identifiers (`normalise`, `summarise`, `analyser`, `LICENCE.md`).
* Modern typing throughout: `X | None`, builtin generics, `@dataclass(frozen=True, slots=True)`
  for params objects, `@override` where applicable. Don't reintroduce `typing.Optional`/`List`.
* Logging via `logging.getLogger(__name__)`, f-strings, phase banners as `"=" * 80`. No print
  statements outside `tools/`'s own reporting output.
* Numeric code stays vectorised over numpy.

## Long-running jobs and timing

Keep one waiter per condition: record its task/session ID and reuse it. Wait on a completion
fact, such as a sentinel in the job's output, rather than a racy process lookup. Every waiter
must have a ceiling and must terminate on failure as well as success. Clean up your outstanding
waiters before finishing; leaked shells and queued jobs interfere with later timings.

This machine suspends. Hold the sleep inhibitor when timing work:

```bash
systemd-inhibit --what=sleep:idle --why="beq timing" --mode=block uv run python tools/TOOL.py ...
```

A run spanning suspension is not valid timing evidence even if its output is correct. Compare
recorded execution time with wall time and repeated-run CPU figures; repeat contaminated runs.
