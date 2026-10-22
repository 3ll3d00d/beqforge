# Keep run records and the server log by default

**Handoff, built 22 October 2026 (see [Outcome](#outcome))** (from the beqdesigner library run, 19 October 2026; TODO row 27).

## What went wrong

`serve-designer` writes a run record only when given `--record-dir` / `BEQFORGE_RECORD_DIR`, and logs
only to its console. The Windows designer (frozen 0.2.4/0.2.5, `beqforge-designer.cmd`) was started
without one and designed **432** library titles, 111 of them declines, leaving no record of any. Their
review can see the response (filters, decline reason and message) but not the evidence behind it:
strata, band tracking, filter and noise floors, plateau search. The only way back is to design those
titles again. The `.10` container kept all of its 903 records only because its deployment set the
variable by hand. The image creates `/records` but neither sets the variable nor declares the volume.

Records are about 190 KiB each (903 records, 171 MB), so a whole library is a few hundred MB.

## Change

1. **Records on by default.** With no `--record-dir`, write to the platform's conventional per-user
   data location, the same convention `beqforge-designer.cmd` already uses for the stage cache:
   - Windows: `%LOCALAPPDATA%\beqforge\records`
   - macOS: `~/Library/Application Support/beqforge/records`
   - Linux: `$XDG_STATE_HOME/beqforge/records` (else `~/.local/state/beqforge/records`)

   Put the default in `serve-designer` itself, not only in the `.cmd`, so every way of starting it
   (exe, `uv run`, the image) gets it. `--no-record` (`BEQFORGE_RECORD=false`) turns it off;
   `--record-dir` still overrides the location. Created and checked for writes at startup like
   `--cache-dir`, and a directory that cannot be written is a startup error, not a silent loss.
2. **The image.** Set `BEQFORGE_RECORD_DIR=/records` and declare `VOLUME ["/records"]` beside
   `/cache`; document mounting it (beqdesigner mounts the share's `work/records`).
3. **A log file.** Also write the server log, rotating (say 10 MB x 5), to `logs/designer.log` beside
   the records (`--log-dir` / `BEQFORGE_LOG_DIR` to move it, `--no-log-file` to stop). The console log
   stays. Today a crash or a 500 on the Windows machine leaves nothing once the window closes.
4. **Say where.** Log the record and log locations at startup, and report `record_dir` (or `null`)
   on `/health`, so a caller can tell a designer that keeps nothing. beqdesigner's pipeline can then
   warn on its status page. Optional field; no contract version change needed for an addition the
   caller ignores, but list it in the contract's `/health` description.
5. **Retention (optional).** `--record-keep N` days or a size cap; default keep everything, since a
   library's worth is small and records are what replay and the decline review need.

## Tests

Default location per platform (monkeypatched environment), `--no-record`, an unwritable directory
failing startup, `/health` reporting the directory, the image smoke test (`packaging/designer/smoke.py`)
checking a record lands in `/records`, and the exe smoke test (`tools/smoke_test_exe.py`) run with no
`--record-dir` finding a record in the default location.

## Outcome

Built as proposed, except that the image keeps no log file (`docker logs` keeps its console)
and retention (item 5) is not built: a library's records are a few hundred MB, and nothing yet
asks for a cap.

* `tools/designer_server.py`: `data_dir()` is the platform's per-user place (`%LOCALAPPDATA%`,
  `~/Library/Application Support`, `$XDG_STATE_HOME` or `~/.local/state`, each `/beqforge`).
  Records default to its `records` and the log to `logs/designer.log`, rotating at 10 MB with five
  kept, as well as the console. `--record`/`--no-record` and `--log-file`/`--no-log-file`
  (`BEQFORGE_RECORD`, `BEQFORGE_LOG_FILE`) turn them off; `--record-dir`, `--log-dir` move them.
  Both are created and write-checked at startup, as `--cache-dir` is, so an unwritable one is a
  startup error. The startup line names both, or says no records are kept. `/health` adds
  `record_dir` and `log_file`, `null` when off: optional fields a caller may ignore, so no
  contract version.
* The environment parser turned on a boolean when its variable was true and otherwise left the
  default, so a false variable could not turn off a flag that defaults on. It now passes the
  `--no-` form.
* The image sets `BEQFORGE_RECORD_DIR=/records`, declares `VOLUME ["/cache", "/records"]` and sets
  `BEQFORGE_LOG_FILE=false`, since `docker logs` already keeps the console. Its smoke script checks
  that `/health` names `/records` and that the two designs left their records there.
* `beqforge-designer.cmd` keeps setting `BEQFORGE_RECORD_DIR` (`9ab5941`), for releases before
  this one; the comment says why.

Tests: `tests/test_designer_server_startup.py` (records and the log by default, under a redirected
`data_dir`; every new option from the environment; false values turning them off; the platform
directories; the four directory options' startup checks), `/health` in
`tests/test_design_designer_server.py`, and the recipe in `tests/test_designer_image.py`. No
pipeline change, so no probe: nothing a design reads moved.
