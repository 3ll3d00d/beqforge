# R2a — the designer server uses the stage cache: implementation plan

**Status:** agreed, not built. Tracked as R2a in [IMPROVEMENT_PLAN.md](../IMPROVEMENT_PLAN.md)
(priority 9). Its answers to beqdesigner are in that file's Progress, "R2 split". The other
side is beqdesigner's `design/designer-by-reference.md` (their `63976c2`). R2b, requests by
reference, is parked. Nothing in this plan builds any part of it (see "Not in this plan").

## What changes, and what does not

Today `designer.design` calls `pipeline.run(material, params)` with no cache. Every request
repeats `diagnose`/`extract`/`identify` (21-100 s) and the parametric fit. After R2a, a
server started with `--cache-dir DIR` reuses any stage whose key has not moved. Without the
flag it behaves exactly as today.

The contract, the response, the decisions and the record's content do not change. Each
step below is exact-preserving for decisions. Only step 1 changes a cache key, so it costs
every title one cold recompute.

Only the per-request `bass_management` varies between requests. Goal dials, strategies and
exclusions are server-wide flags. A redesign that R2a speeds up is therefore either:
- a repeat request, for example a re-queued title, or the same title after beqdesigner
  changed something it does not send; or
- a request after the server was restarted with different flags.

The first should reuse every cached stage. The second should reuse the analysis and
recompute only what the changed flag reaches. That is C3's key, already in place.

## Current state, as read at `e96129a`

- `cache.load`/`cache.store` keep **one gzipped JSON file per title**, beside the material
  (`<name>.cache.json.gz`), with one entry per stage. `store` reads the whole file, adds
  the stage and rewrites the file **in place**, so a concurrent reader can see a partial file.
  `_read_document` treats a partial file as a miss, but the rewrite also races another
  writer: last writer wins and a stage is lost.
- `cache.key_for` = schema, stage, `material_fingerprint`, `repr` of the params,
  `digest_of(modules)`.
- `material_fingerprint` hashes `material.name` as well as `fs`, coverage and the samples.
  The server names every request `"designer-request"` (`designer.py:275`).
- `digest_of` reads the `.py` sources from the package directory. A PyInstaller onefile
  build ships bytecode in its archive, not sources. So in a frozen build, `key_for` should
  raise as soon as any cache is in use. That may already affect `beqforge design` in the
  frozen executable, whose default is a cache beside the material. **Not yet verified.**
  Step 3 checks it first and records what it finds.
- `pipeline.run(material, params, cache_path=None, fresh=False)` is the only consumer.
  Its callers are `tools/design_beq.py`, `probe.py`, `refit_probe.py`, two old experiment
  scripts and two tests.

## Steps

Each step is its own commit with its tests, and goes through AGENTS.md's "Regression
checking". Take one probe snapshot on `e96129a` before step 1 and keep it as the reference
for every step. None of the steps is meant to move a decision, so the check each time is
`probe.py compare --tol 0`, which must show nothing. Record the outcome in
IMPROVEMENT_PLAN.md's Progress with each commit.

### 1. Take the name out of the material fingerprint

- `material_fingerprint` stops hashing `material.name`. Nothing any stage stores depends on
  the name, and step 1's test checks that the analysis and proposals payloads carry no
  material name.
- Do not bump `SCHEMA`. The fingerprint changes anyway, so every stored entry is a miss.
- Update the docstring: the key is the samples, so a renamed or moved file still hits.
- Tests:
  - two `Material`s with the same samples and different names get the same key;
  - changing `fs`, coverage, a channel label or one sample changes it;
  - `test_every_key_field_is_load_bearing` still passes.
- Regression: this is a key change only. The probe snapshot recomputes the analysis once
  (about 4 minutes) and must show nothing at `--tol 0`. One real run, checked with
  `compare_records.py` against its baseline record, must be identical apart from the
  fingerprint and timings.

### 2. Atomic, immutable entries, and a directory store

The store needs two layouts: the CLI's one file per title, kept as it is, and a directory
for the server, since a request has no material path to sit beside.

- `cache.py` gains a small `Store` protocol (`load(stage, key)`, `store(stage, key,
  payload)`) with two implementations:
  - **`FileStore(path)`** is today's layout and behaviour. The only change is that `store`
    writes to a temporary file in the same directory (`tempfile.NamedTemporaryFile(dir=...,
    delete=False)`), `fsync`s it, and then `os.replace`s it over the target. A reader then
    sees the old file or the new one, never a partial one.
    - Two writers on the same title can still lose one stage: read-modify-write, last one
      wins. That costs a recompute, never a wrong answer. It is documented, not locked.
  - **`DirStore(root)`** keeps one file per entry: `<root>/<stage>/<sha256 of the canonical
    JSON key>.json.gz`, written the same way.
    - The name is the key, so different configurations sit side by side. A server
      restarted with a different goal dial does not evict the old parametric entry, and
      going back to the old dial hits it again.
    - An entry is never rewritten with different content. Two writers of the same key write
      the same payload, so `os.replace` over an existing entry is harmless.
    - `load` still compares the stored key with the requested one, as a guard against a
      corrupted file or a hash collision. A mismatch is a miss.
    - Log a miss as "no entry" at INFO. The per-field "what moved" message stays for
      `FileStore`, and `DirStore` cannot give it cheaply.
- `pipeline.run`'s `cache_path` accepts `Path | cache.Store | None`. A `Path` is wrapped in
  `FileStore`, so no caller changes in this step.
- **Size.** `DirStore` never evicts. Before step 4 ships, measure one title's analysis and
  parametric entry sizes (the store already logs MB) and write down what a 100-title
  library costs. Eviction is out of scope unless that number says otherwise. If it is
  needed, oldest `mtime` first under a `--cache-max-gb`, touching an entry on hit.
- Tests:
  - both stores round-trip bit-identically (reuse the existing round-trip tests, run
    against both);
  - `DirStore` keeps two keys for one stage side by side;
  - a key mismatch inside an entry is a miss;
  - a truncated entry is a miss;
  - **no reader ever sees a partial entry.** A subprocess writes an entry large enough to
    take measurable time, many times over, while another loads it in a loop. Every load is
    either a miss or the full payload, never an exception or a truncated one. Test this for
    both stores.
- Regression: exact-preserving for the CLI. `probe.py compare --tol 0` must show nothing.
  One real run with a warm cache must give a record identical to its baseline under
  `compare_records.py`.

### 3. Stage digests in the frozen build

- **First, find out.** Build the executable (`uv run pyinstaller beqforge.spec`) and run
  `beqforge design` on a short harness `.npz` with its default cache. Record in Progress
  whether it raises. If it does, that is a live bug, independent of R2a, and this step
  fixes it too.
- `beqforge.spec` writes `STAGE_DIGESTS.json` next to `BUILD_REVISION`: a map from each
  module tuple in use (`ANALYSIS_MODULES` and every `Strategy.cache_modules`, joined with
  `"\0"`) to `digest_of(tuple)`, computed from the tree being built. Read the tuples off
  `cache` and `pipeline.STRATEGIES`, never duplicate them, just as the spec reads
  `_SUBCOMMANDS` off `cli.py`.
- When `sys.frozen` is set, `digest_of` reads that map. A frozen build without the file, or
  without the tuple it is asked about, raises `cache.CacheUnavailable`. `run` catches that,
  logs one warning, and runs uncached. It never keys on nothing, and it never crashes the
  run.
- An unfrozen build computes the digests exactly as today, so the digests are identical in
  both builds by construction. A test asserts that the spec's map-building function, called
  in-process, equals `digest_of` for every tuple.
- Tests:
  - with `sys.frozen` patched and a baked map present, keys equal the unfrozen keys;
  - with no map present, `run` completes uncached and logs the warning;
  - the map covers every `cache_modules` tuple in `STRATEGIES`.
- Regression: no pipeline change for an unfrozen run, so the probe must show nothing.
  `smoke_test_exe.py` must still pass; step 5 extends it.

### 4. `serve-designer --cache-dir DIR`

- `tools/designer_server.py` gains `--cache-dir DIR`, off by default like `--record-dir`.
  When set, the handler builds one `cache.DirStore(DIR)` at start-up and passes it through
  `designer.design(..., cache=store)` to `run`.
- `designer.design` gains `cache: cache.Store | None = None`. Nothing else in the adapter
  changes.
- Several servers, or a server and the CLI, may point at one directory. Step 2's atomic
  writes are what make that safe, and the server stays single-threaded (AGENTS.md). The CLI
  keeps its per-title file by default. `design_beq.py --cache DIR/` could opt into
  `DirStore` later, but that is not part of R2a: beqdesigner's WAVs and our `.npz` differ at
  the 24-bit rounding level, so the CLI and the server would not share keys for the same
  title anyway.
- The start-up log line names the cache directory, as it already names the record
  directory.
- Tests (`test_design_designer_server.py`, in-process server):
  - the same request twice: the second logs `analysis: reused` and
    `parametric: reused`, and both responses are identical;
  - a second server on the same directory with a different `--goal-tilt`: the analysis is
    reused and parametric is recomputed;
  - a second request differing only in `bass_management`: the analysis is reused;
  - with no `--cache-dir`, nothing is written.
- Regression: the server path is not in the probe. The check is that, for the same request,
  the cached server's run record (`--record-dir`) is identical under `compare_records.py`
  to an uncached server's.

### 5. Prove it in the executable, and time it

- `smoke_test_exe.py` starts the executable with `--cache-dir <tmp>` and sends its request
  twice. It passes only if:
  - both responses are identical apart from timing;
  - the second request's record's timings name the stages `analysis/cached` and
    `target/parametric (cached)`;
  - the cache directory holds entries.

  That is the pass for "the frozen executable hits the cache", on every platform CI builds.
- Timings: the server logs one line per request, split into body read, JSON parse, base64
  decode and validation, `run` (with its own stage timings), and response encode. Then
  `tools/experiments/request_timing.py` POSTs one real title (from `data/`, encoded as
  beqdesigner would) cold, then warm, then warm again, under `systemd-inhibit`. Its report
  gives:
  - the wire share of a warm request: read, parse and decode, against the total;
  - the size of the request body.
- Write the figures into IMPROVEMENT_PLAN.md's Progress under R2a. **That result is what
  decides R2b.** If the wire is a small share of a warm request, R2b stays parked and
  beqdesigner is told so. If not, R2b is proposed for unparking, with the numbers.

## Done when

- Every step is committed with its tests and a Progress entry.
- `smoke_test_exe.py` passes the warm-hit check on all CI platforms.
- The warm/cold timings are recorded.
- The R2a status row reads **done** and the R2b row reflects the timing decision.
- beqdesigner is told the outcome, so their D1 can proceed or close.

## Not in this plan

- **Anything R2b needs:** reading `file` arrays, `--shared-root`, the 422 paths, `/health`
  capability fields, `record_path`, and a `design-request.json` loader. They wait until
  R2a's timings exist and beqdesigner has agreed the answers to their §6.
- **Sharing the stage cache with beqdesigner.** Withdrawn (Q2).
- **Keying on per-array digests.** Declined (Q4).
