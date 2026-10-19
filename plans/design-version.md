# Say which answer a build gives: a design version (contract 1.4)

**Handoff, not built** (from beqdesigner's library run, 19 October 2026; TODO row 28). Agreed with the
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
   transport. A test should make forgetting hard: for example, a golden of answers on a few fixture requests
   whose expected file records the `DESIGN_VERSION` it was made with, so changing an answer without bumping
   (or bumping without regenerating) fails.
2. **Past releases.** Declare the versions they would have carried, in the plan or a doc table, so the
   caller can backfill entries made before 1.4: 0.2.0 = 1, 0.2.1 = 2, 0.2.2 = 3, 0.2.3 to 0.2.5 = 4, and
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
   `35c4437ecbb6`.)
3. **`design_settings`**: a short digest of the server-wide settings that can change an answer
   (strategies, exclusions, goal tolerance and tilt, content edge, device rate and coefficient precision),
   in a fixed canonical form. Always send it, defaults included: "all defaults" is a value
   too (the contract lets a designer with no such settings omit it). Leave out workers, cores, cache, record, log and shared-root settings.
4. **On the wire**, optional top-level fields on every response and on `GET /health`:
   `design_version`, `design_settings`, and `designer_build` (the string now in `beqforge_revision`; keep the
   commentary key too until the caller stops reading it). Returned whatever `contract_version` the request
   names, as the 1.1 and 1.3 fields are. Update the response and health schemas and the conformance list.

## Tests

The golden above; `design_settings` equal for equal settings, different for each setting that can change an
answer, and unchanged by workers/cores/cache/record; the fields present on a decline, a design and `/health`;
the exe smoke test and the image smoke test reading them from `/health`.
