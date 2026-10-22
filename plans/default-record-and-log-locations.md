# Keep run records and the server log by default

**Handoff, partly built** (from the beqdesigner library run, 19 October 2026; TODO row 27). `9ab5941` makes
`beqforge-designer.cmd` default `BEQFORGE_RECORD_DIR` to `%LOCALAPPDATA%\beqforge\records`, and the Windows library
machine now writes its records there. The rest of the change below (the default in `serve-designer` itself, the image,
the log file, `/health`) is not built.

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
