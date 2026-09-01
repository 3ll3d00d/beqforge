# CLAUDE.md

@AGENTS.md

## Additional notes for Claude Code

* Read `AGENTS.md` above before touching pipeline code — the `Points`-at-the-boundary rule, the
  band-limited vs full-range split, and the dead `assess()` path are what most often send you down a
  wrong turn.
* Don't run `python -m beqanalyser` casually. It blocks on `plt.show()`, and without a cached
  `database.bin` it downloads the whole catalogue. Prefer a small synthetic dataset (see "Running things"
  in `AGENTS.md`) for verifying pipeline changes.
* Never commit `database.bin`, `database.bin.sha256`, `*.npy`, `beq_composites.csv` or generated PNGs —
  all gitignored, all large.
* The working tree is usually mid-experiment with uncommitted changes. Check `git status` and diff against
  `HEAD` before assuming committed code reflects current intent.
* The known issues listed in `AGENTS.md` and README §7 are documented, not assigned. Fix one only when
  asked, or when it directly blocks the task at hand — and say so if you do.
