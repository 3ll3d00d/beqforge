# Shared primitives

Read the repository [AGENTS.md](../AGENTS.md) first. Commands and paths below are relative to
the repository root. This package imports no workflow package and contains only neutral
primitives needed across workflows.

| File | Responsibility |
| --- | --- |
| `types.py` | Shared filter specifications and design types |
| `biquad.py` | Canonical RBJ biquad arithmetic |
| `publication.py` | Canonical publication rounding |
| `provenance.py` | Shared source/build revision handling |
| `__init__.py` | The single distribution version and public shared types |

Changes can reach multiple workflows. Read the affected packages' instructions before editing;
designer-reachable changes require the regression procedure in
[beqforge/AGENTS.md](../beqforge/AGENTS.md). Shared modules reached by the designer must remain
covered by its record and stage source fingerprints. Optimiser cache implementation identity
and frozen device-check provenance must continue to reflect their numerical dependencies.

RBJ arithmetic also exists in the designer's vectorised `beqforge.filters._sos_from_parameters`.
When changing the equations, update both implementations together and retain their equivalence
test. `beqforge/biquad.py` and legacy designer type exports are compatibility paths to shared
primitives; do not turn them into independent implementations.

The version in `beq_common.__version__` is consumed by Hatch, every workflow and provenance.
A version change can invalidate recorded/cache identities, including the bundled optimiser
seed; account for that when preparing a release. Frozen builds have no checkout source to
hash, so preserve their baked revision stamps.

Check affected numerical tests, fingerprint/invalidation tests and
`tests/test_package_boundaries.py`. Shared-code changes must retain isolated dependency
profiles and avoid importing SciPy, plotting or device libraries merely to expose types or
RBJ arithmetic.
