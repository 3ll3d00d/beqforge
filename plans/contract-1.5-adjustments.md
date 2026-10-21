# Contract 1.5: design adjustments (beqforge's side)

**Handoff; built 21 October 2026 (see [Outcome](#outcome))** (from beqdesigner, 21 October 2026; TODO row 30). beqdesigner's side is built and committed
on its `main` (not yet pushed or released); this is what beqforge needs to do for a person to be able to ask it for a different design from the
browser.

## What 1.5 is

The contract text is beqdesigner's `design/designer-interface.md` v1.5: §2 "Adjustments", §3 "Adjustment outcomes",
§7 and §7.1, with the conformance list in `design/designer-conformance-tests.md` ("1.5: adjustments") and the
machine-checkable shapes in `docs/schema/http_designer_{request,response,health}.schema.json`. In short:

* A request may carry `adjustments`: a list of `{id, kind, params, text}`. The caller sends them only when there are
  some, and then says `contract_version: "1.5"`; a request without them is exactly a 1.4 request and **must get exactly
  a 1.4 answer** (the golden test).
* The designer answers **each** adjustment in `adjustment_outcomes`: `{id, outcome, applied, reason}`, `outcome` one of
  `honoured`, `adapted` (`applied` and `reason` required), `declined` or `not_understood` (`reason` required, `applied`
  null). One per adjustment, on a design and a decline alike. An unknown kind is `not_understood`; bad parameters are
  `declined` with the reason; neither is an error. Only a body that is not the shape (no `id`/`kind`, ids repeated)
  may be refused.
* §2's old line "no headroom/max-boost/device preference crosses in" is restated as **no *unstated* preference**: the
  designer still must not infer what the caller wants; what the caller states, it weighs against the evidence and
  answers. §4 is unchanged: an adjustment can make a design narrower or weaker, never make beqforge publish what its
  evidence does not support. A declined adjustment does not decline the design.
* `GET /health` may list `adjustment_kinds`: `{kind: {description, params: {name: {type, unit, minimum, maximum,
  default, description}}}}`. beqdesigner builds its form from this list and sends adjustments only to a designer whose
  `/health` says 1.5 or later.
* A designer may define kinds of its own, prefixed `x-` (`x-beqforge-strategy`).

This reopens nothing parked by itself, but it is the mechanism several parked rows were waiting for a reason to want:
19 (fraction dial: "no user/title has needed ... as a preference"), 20 (protective corner override) and 15 (authored
features: `--exclude` per title instead of per server). Row 21 (device configuration on the wire) stays parked:
device realisation is not an adjustment.

## The kinds, and where each lands in beqforge

Every one is already a server-wide dial; 1.5 makes it per request. Apply them in `designer.design()` with
`dataclasses.replace` on `params`, exactly as `bass_management` is applied today, **after** `design_settings_digest`
is computed (the digest describes the server, not the request; contract §2: adjustments "never change
`design_settings`").

| kind | params | beqforge | outcome rules (proposed) |
| --- | --- | --- | --- |
| `exclude_band` | `low_hz`, `high_hz` | append to `PipelineParams.exclude_bands_hz` (the same list `--exclude` fills; `diagnose` merges it with `ExtractionParams.exclude_bands_hz` at `diagnose.py:650`) | `declined` if `low_hz >= high_hz` or outside the analysed band (`DiagnoseParams.band_hz`); `adapted` if clipped to the band (say the band used); otherwise `honoured`. If the exclusion removes the only rolloff, the design declines as it would on the evidence and the decline message says so. |
| `floor` | `hz` | `PipelineParams.lowest_frequency_hz = max(server value, hz)` (placement floor, shared with `DesignParams.lowest_frequency_hz` through `pipeline.py:1224`); consider also excluding `[0, hz)` from targets so `flatten`'s held-flat region does not restore below it | `declined` if `hz` is at or above the top of the judged band (nothing left to correct); `adapted` if below the server's floor (the server's stands: say so); otherwise `honoured`. |
| `max_boost` | `db` | `parametric_max_boost_db = min(server, db)`; `restore_caps_db = tuple(min(c, db) for c in caps)` (deduplicated); the protective corner follows the cap already (TODO row 20) | `honoured` when applied (a cap only makes a design weaker); `adapted` if the accepted candidate still exceeds it after realisation (report the realised peak); `declined` for `db <= 0`. A cap that leaves nothing that passes is an evidence decline, not a declined adjustment. |
| `goal_tilt` | `db_per_octave` | `AcceptParams.target_tilt_db_per_octave` (`--goal-tilt`): replaces the server's value for this request | `declined` outside the range the tilt check can judge (decide it: the docstring's "roughly 6 dB of headroom for +2 dB/octave" suggests a bound like ±3); otherwise `honoured`, `applied` the value used. Note `pipeline.py:1043` resets the tilt to 0 for one path: decide whether a requested tilt is honoured there or reported `adapted`. |
| `note` | -- | none | `not_understood`, with a reason ("free text is kept in the run record, not acted on"). Put `text` in the run record either way. |

Candidates for beqforge's own kinds, advertised on `/health` (optional, later):

* `x-beqforge-strategy` (`names`: list): `PipelineParams.strategies` for this request (`--strategy`).
* `x-beqforge-goal-tolerance` (`db`): `AcceptParams.goal_tolerance_db` (`--goal-tolerance`).
* `x-beqforge-content-edge` (`on`): `judge_from_content_edge` (`--content-edge`, opt-in, row 6).

The contract reserves `ceiling`, `goal_tolerance`, `strategies`, `max_sections` and `exclude_times` for later
contract versions; using `x-` names now avoids colliding with them.

## The work

1. **Wire format** (`designer.py`): `DesignRequest.adjustments` (parsed in `request_from_json`; refuse only a
   malformed list), `DesignResponse.adjustment_outcomes` (written by `response_to_json` only when there are
   adjustments), `CONTRACT_VERSION = "1.5"`, and `validate_response` taught the outcome rules (one per id, ids known,
   `reason`/`applied` per outcome). The server already echoes the request's `contract_version`.
2. **Applying them** (`designer.design()`): a small pure function `apply_adjustments(params, adjustments) -> (params,
   outcomes_so_far)` that validates parameters, builds the per-request `PipelineParams` and the provisional outcomes;
   then, after `run()`, a second pass that turns a provisional `honoured` into `adapted` where the answer shows the
   adjustment could not be met as asked (`max_boost` exceeded after realisation; a `goal_tilt` path that ran flat).
3. **`/health`** (`tools/designer_server.py`): `"contract_version": "1.5"` and `adjustment_kinds` with each kind's
   description and parameters (units, bounds, defaults: the server's current values, so the form opens on what the
   server would do).
4. **The cache** (`cache.key_for` reprs the params each stage is given): check that every stage that reads an
   adjusted field is keyed on the *adjusted* params (the analysis stage reads `exclude_bands_hz`, the parametric
   proposal reads the caps and the floor), so a request with adjustments never reuses a stage made without them. A
   test: the same audio designed with and without an `exclude_band` gives different targets and both are cached.
5. **The run record**: record the adjustments and outcomes (and the `note` text) beside the params, so `replay.py`
   reproduces an adjusted design.
6. **Identity**: no `DESIGN_VERSION` bump, provided a request without adjustments is answered exactly as before
   (`tests/test_design_golden.py` unchanged). `design_settings` unchanged by adjustments.

## Tests and regression

* Unit (`tests/test_design_designer.py`, `tests/test_design_designer_server.py`): parsing and writing; one outcome per
  adjustment; unknown kind `not_understood`; bad params `declined`; order does not matter; `/health` lists the kinds;
  a pre-1.5 request (no `adjustments`) gives the 1.4 body byte-for-byte.
* Direction, per kind (beqdesigner's conformance list, "Designer side"): on a fixture where the evidence allows it,
  `max_boost` lowers the peak boost, `floor` moves the lowest corrected frequency up, `exclude_band` leaves the band
  uncorrected, `goal_tilt` raises the low end of the goal; and each is declined or adapted, with a reason, on a fixture
  where it cannot be met. An adjustment never turns a judge failure into a candidate.
* Regression (beqforge/AGENTS.md "Regression checking"): the default path must not move: `probe.py snapshot`
  before/after with `compare --tol 0` (adjustments are opt-in per request, like `--content-edge`, so the default
  snapshot is the gate) and the golden. The adjusted paths are the server flags that already exist, now per request;
  if a mapping goes beyond them (the `floor` target exclusion, a new tilt bound), give that path its own snapshot pair
  as an opt-in.

## Done when

beqforge answers a 1.5 request's adjustments as above, lists its kinds on `/health`, the golden and the default probe
are unchanged, and a release is published. beqdesigner needs no change: its browser's *Ask the designer to change
something* enables itself when `/v1/status` reports the kinds (its TODO row WP, chunk WP6).

## beqdesigner references

`design/web-parity.md` (WP6, WP7), `design/designer-interface.md` v1.5, `src/main/python/pipeline/designer/contract.py`
(`DesignAdjustment`, `AdjustmentOutcome`), `convert.validate_outcomes`, `http_binding.check_takes_adjustments` and
`reported_adjustment_kinds`, and `src/test/python/test_pipeline_designer_adjustments.py` (what the caller sends and
how it checks the answers).

## Outcome

Built on branch `contract-1.5-adjustments` (from `cf331b9`):

* `beqforge/adjustments.py`: the shape check (`adjustments_from_json`; a malformed body is a 400, an unknown kind or a
  bad parameter is answered), `apply_adjustments` (the mapping above, first by id of a one-value kind, the rest
  declined), `finish_outcomes` (a cap the realised filters pass by more than the fit's own `residual_target_db` is
  `adapted` with the peak; an applied adjustment on a declined design says so), `kinds_for` (`/health`, defaults the
  server's settings) and `MAX_TILT_DB_PER_OCTAVE` = 3.
* `max_boost` did not bind on `flatten` as first mapped (the restore caps and the parametric cap are other strategies'):
  it is now also `PipelineParams.max_target_boost_db`, a ceiling `priced_by_evidence` applies to every strategy's
  target, `None` (no ceiling) unless a request sets it. On the synthetic 24 Hz BW4 title a 6 dB cap takes the peak from
  about 12 dB to 6.3 dB.
* `designer.py`: `CONTRACT_VERSION = "1.5"`, the request and response fields, `_validate_outcomes`, applied after
  `design_settings_digest`; `tools/designer_server.py`: `adjustment_kinds` on `/health`.
* Not done: the note's text is not written into the run record (the record has the adjusted params).
* No `DESIGN_VERSION` bump: a request without adjustments is untouched.

Evidence: `tests/test_design_adjustments.py` (31, four real designs for direction: the cap lowers the peak, the tilt
raises the master-volume figure, the floor keeps every section at or above 15 Hz, excluding 10-18 Hz declines the
title with the adjustment saying why); `tests/test_design_golden.py` unchanged; the full suite 936 passed, 2 skipped;
`probe.py snapshot`/`compare --tol 0` over the 11 baseline titles before (`cf331b9`) and after: every title unchanged.
