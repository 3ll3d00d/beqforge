# CLAUDE.md

@AGENTS.md

## Additional notes for Claude Code

* Read `AGENTS.md` above before touching pipeline code — the strategies/evidence-pricing rules,
  "never trust a residual", and "never calibrate against the catalogue" are what most often send
  you down a wrong turn here.
* Before committing any change under `beqforge/`, follow AGENTS.md's "Regression checking": probe
  snapshot before and after, real runs only for the titles the probe names, the synthetic
  protocol for anything that can change a decision, and the outcome written into
  `TODO.md` and the completed evidence under `plans/`. Don't substitute a full nine-title rerun, and don't skip it.
* Don't run `uv run python tools/design_beq.py` casually against real material — a run is
  40-80 s a title. Wrap any timed run in `systemd-inhibit` (see AGENTS.md's "Waiting on a long
  run") and use the background-task workflow rather than a foreground `sleep` loop.
* The stage cache (`beqforge/cache.py`) is on by default and keyed per stage; `--fresh` forces a
  recompute, `--no-cache` uses neither. Don't assume a change took effect without one of these if
  you're re-running against the same material.
* Never commit anything under `data/`, `out/` or `charts/`, or generated `.run.json.gz`/`.beq`
  files — all gitignored, all either large or reproducible from a record.
* The working tree is usually mid-experiment with uncommitted changes. Check `git status` and
  diff against `HEAD` before assuming committed code reflects current intent.
* The backlog in `TODO.md` is documented, not assigned. Fix an item only when asked, or when it
  directly blocks the task at hand — and say so if you do.
