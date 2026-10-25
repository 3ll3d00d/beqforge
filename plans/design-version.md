# Say which answer a build gives: a design version (contract 1.4)

**Built, 19 October 2026** (handed over from beqdesigner's library run the same day; was TODO row 28;
see [Outcome](#outcome-19-october-2026)). Agreed with the
beqdesigner maintainer; the caller's side is beqdesigner's `design/design-version.md` (TODO L3), which
becomes contract 1.4 once both sides are built.

## The problem

Each response names its build (`beqforge_revision`: `e1a2c24b1172+src:008f1c30d377 (frozen build)` from the
exe, `unknown+src:76b2edd7e060` from the image, both 0.2.5). After the library run, deciding which of 1,281
titles a release changes meant computing `record._source_digest()` at every tag and reading the commit log:
0.2.1, 0.2.2 and 0.2.3 changed answers; 0.2.4 and 0.2.5 did not. The caller cannot do that, and two
packagings of one release never compare equal.

`beqoptimiser` already solved the same problem for its seed (`1e8d6ee`, `core.NUMERICAL_VERSION`, bumped
only by a change that alters a result). This is that, for the designer.

## Change

1. **`DESIGN_VERSION`**, an integer constant in `beqforge` (one place, beside the contract version), bumped
   by any change that can alter `candidates`, `rejected`, a decline or a 1.3 fit figure for an unchanged
   request. Not by wording-only changes (`commentary`, `decline_message`), speed, packaging, the server or the
   transport. An answer change is judged against the golden's tolerance, not bit for bit: one version can
   differ in the last digits between platforms (the exe and the image), and the caller compares versions,
   never figures. Adding an output without changing existing ones is not a bump: contract 1.3's fit figures
   (`92407e8`) are not, so entries designed at 4 just lack them. A test should make forgetting hard: for example, a golden of answers on a few fixture requests
   whose expected file records the `DESIGN_VERSION` it was made with, so changing an answer without bumping
   (or bumping without regenerating) fails.
2. **Past releases.** Declare the versions they would have carried, in the plan or a doc table, so the
   caller can backfill entries made before 1.4: releases before 0.2.0 (0.0.x, 0.1.0, which also shipped
   `serve-designer`) = 0, meaning before versioning and always out of date; 0.2.0 = 1, 0.2.1 = 2, 0.2.2 = 3, 0.2.3 to 0.2.5 = 4, and
   the first release with this field 4 if it changes no answer, else 5. Include each release's source
   digest (container) and revision (frozen), which the caller sees as the build:

   | Release | revision | `src:` digest |
   |---|---|---|
   | 0.2.0 | `9f07a67` (tag) | `eeb06d1cb9a6` |
   | 0.2.1 | `7a1702fa94de` | `c1ae12bafc27` |
   | 0.2.2 | `fd9ae22846a6` | `745e6c61342a` |
   | 0.2.3 | `2f1a0ccefd69` | `3f0cbd9447c7` |
   | 0.2.4 | `a110332e314d` | `d81a799f2b7b` |
   | 0.2.5 | `e1a2c24b1172` | `76b2edd7e060` |

   (Digests computed from each tag's tree; frozen builds report a different `src:` because the bundled
   sources differ, e.g. 0.2.5 frozen `008f1c30d377`, 0.2.4 frozen `04ac01018d49`, 0.2.3 frozen
   `35c4437ecbb6`.) Checked on 19 October 2026: the tag commits match the revisions, and `_source_digest`
   recomputed from each tag's tree gives the container digests above (frozen digests not checked). The
   commit log agrees with the versions: 0.2.4 changed only the server (`6c71633`), and 0.2.5's parallel
   decomposition (`007d179`) records exact-preserving evidence.
3. **`design_settings`**: a short digest of the server-wide settings that can change an answer
   (strategies, exclusions, goal tolerance and tilt, content edge, device rate and coefficient precision),
   (`--strategy`, `--exclude`, `--goal-tolerance`, `--goal-tilt`, `--content-edge`, `--device-rate`,
   `--coefficient-bits`, `--integer-bits`), in a fixed canonical form: settings at their default are left
   out, so all defaults digests the empty set and adding a flag whose default keeps today's behaviour changes
   no digest (changing a default that alters answers is a `DESIGN_VERSION` bump anyway); exclusions sorted;
   floats in a fixed form; strategy order kept only if order can change the ranking (check when building).
   Always send it: an absent `design_settings` means a designer has no such settings. Leave out workers,
   cores, cache, record, log and shared-root settings. `/health` may also carry `design_settings_detail`,
   the non-default settings as an object, for a person to read when live designers disagree; never a key.
4. **On the wire**, optional top-level fields on every response and on `GET /health`:
   `design_version` (an int), `design_settings`, and `designer_build` (the string now in `beqforge_revision`; keep the
   commentary key too until the caller stops reading it). Returned whatever `contract_version` the request
   names, as the 1.1 and 1.3 fields are. Update the response and health schemas and the conformance list.

## Tests

The golden above, compared within its tolerance on every CI platform; `design_settings` equal for equal
settings, different for each setting that can change an answer, equal to the empty set's digest at all
defaults, and unchanged by workers/cores/cache/record; the fields present on a decline, a design and `/health`;
the exe smoke test and the image smoke test reading them from `/health`.

## Outcome (19 October 2026)

Built as agreed and released in 0.2.7, the first release with the field, at design version 4
(no answer changed). `v0.2.6` was tagged first and never published: its release tests failed
(see [Correction](#correction-after-the-v026-release-tests)). `CONTRACT_VERSION` is `"1.4"`.

* **`beqforge/designer.py`**: `DESIGN_VERSION = 4`, an int, with the past-release table in its
  docstring. `design_settings_detail(params)` returns the eight settings above where they differ
  from `PipelineParams()`. `design_settings_digest(params)` is the SHA-256 of that detail as
  canonical JSON, behind a `design-settings-v1` prefix, first 12 hex. All defaults digests the
  empty set: `9cf04c30b0f0`. `DesignResponse` carries `design_version`, `design_settings` and
  `designer_build`, set by `design()` on a design and a decline alike. `response_to_json` writes
  them top-level whatever `contract_version` the request names. `validate_response` checks each
  one is absent or well formed: a non-negative int (not a bool), non-empty strings. The
  `beqforge_revision` commentary key and the decline message's bracket are unchanged.
* **Strategy order is kept.** Ranking is order-independent except for exact ties (`Report.accepted`
  takes the first of equal keys). But candidates are built in strategy order, and `rejected` is a
  stable sort of them, so the order can change an answer.
* **`tools/designer_server.py`**: `/health` adds `design_version`, `design_settings`,
  `design_settings_detail` and `designer_build`, computed once when the server starts. The
  startup log names the version and the digest. `main()` is split into `build_parser()` and
  `pipeline_params(args, parser)`, so a test can check that a server started with no flags sends
  the empty set, and that workers, cores, cache, records and the shared root leave it alone.
* **Guard**: `tests/test_design_golden.py` and `tests/fixtures/design_golden.json`. Five fixed
  requests reach every strategy, an acceptance and both kinds of decline: the synthetic BW4 at
  24 Hz LFE title under `flatten`, `counterfactual` and `parametric` one at a time; the same title
  unfiltered (`within_programme_ripple`); and a mix with no channels. They run in about 45 s
  locally, the per-strategy fits taking 8-16 s each. Each case's answer is compared at 1e-4
  relative / 1e-3 absolute: filters and figures, the rejected designs' figures and how many
  reasons each has, and a decline's reason. Wording and the build are not compared. The golden
  records the `DESIGN_VERSION` it was made with, so an answer moving without a bump fails, and so
  does a bump without regenerating (`BEQFORGE_REGENERATE_GOLDEN=1`). The cross-platform
  tolerance is untested until CI runs it on macOS and Windows: a push to `main` does that, a
  feature branch push does not.
* **Smoke checks**: `tools/smoke_test_exe.py` requires `/health` to report `DESIGN_VERSION`, a
  settings digest and a frozen build, and the response to carry the same three.
  `packaging/designer/smoke.py` (the image) requires an int version, a digest and a build on
  `/health`, and that both responses agree with it. `tests/test_designer_image.py` runs that
  check in-process.
* **Not here**: the response and health schemas and the conformance list belong to
  beqdesigner's `designer-interface.md` and `designer-conformance-tests.md`, and are that
  side's to update when 1.4 goes into the contract.

**Regression check**: the probe snapshot was taken before (committed `d5194a7`) and after, and
compared at `--tol 0`: all 11 titles unchanged, so no real runs were needed. No decision can change: the pipeline is untouched, and the
golden shows this code gives the answers design version 4 names. Full suite (`-n auto`): 898 passed, 2
skipped. An earlier run failed the 11 startup tests that mock the server, because the startup log
read the mocked server's identity; it now digests the params itself. The synthetic protocol and corpus weren't run: nothing touches evidence, ceiling,
acceptance or selection.

Later versions (the table in `DESIGN_VERSION`'s docstring is the authority): 0.2.8 is still 4; 0.2.9 is 5, built by
the library review's fixes 2-4 and O2 ([outcomes](library-review-improvements.md#outcomes)). Contract 1.5's
adjustments (0.2.9) did not bump it: a request without adjustments gets the same answer. 6 (unreleased) makes the fit reproducible across processors
and honours the request's bass management ([TODO 1](playback-contract.md#outcome)) (TODO 28, [outcome](library-review-improvements.md#built-a-reproducible-fit-input-22-october-2026-design_version-6)).
6 shipped in 0.2.10 and 0.2.11. 7 (unreleased) chooses among the fits within the fitter's residual bar
by the judge, fewest sections first (TODO 32, [outcome](library-review-improvements.md#row-32-choosing-among-near-equal-fits-25-october-2026-design_version-7)).

### Correction after the v0.2.6 release tests

Every CI platform failed the golden for the synthetic title under `counterfactual` and
`parametric`; nothing else failed. The answers were materially different, not last-digit:

| Where | counterfactual | parametric boost (`mv_adjust_db`) |
|---|---|---|
| This machine (Ryzen 8840HS, AVX-512, OpenBLAS SkylakeX kernels) | 2 sections, 8.89 dB | 15.21 dB |
| The same, `OPENBLAS_CORETYPE=Haswell` | as above | 15.78 dB |
| Linux and macOS runners | 3 sections, 9.21 dB | 16.49 dB |
| Windows runner | 2 sections, as here | 16.49 dB |

On one machine the answer is repeatable: one and three fit workers gave the same filter, and
there is no default stage cache. So last-digit differences in BLAS kernels grow into a different
local optimum. `flatten` and both declines matched on every platform. The golden now holds only
those three cases. The handoff's "one version can differ in the last digits between platforms"
is wrong for these two strategies: one design version is one algorithm, not one filter on every
machine. The caller compares versions, never figures, so the contract is unaffected. Whether real
titles behave the same way is unmeasured, because the probe compares runs on one machine; it's
a backlog item ("Fit sensitivity to arithmetic"). beqdesigner was told.

Design version 6 (TODO 28) brought `counterfactual` back into the golden on every platform;
`parametric` still differs by 0.06 dB on macOS arm64 and stays out
([verdict](library-review-improvements.md#built-a-reproducible-fit-input-22-october-2026-design_version-6)). It also carries
the sub feed from the request's bass management (TODO 1) and O2's exception for a passband
whose knee lands under 10 Hz ([TODO 31](library-v5-review.md#o2-at-the-knee-design-version-6-23-october-2026)).

