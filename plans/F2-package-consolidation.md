# Consolidated distribution and workflow boundaries

Implemented 2026-10-06. One published entity, `beqforge`, contains three independent
workflow packages and a neutral shared primitive package. The optimiser subproject,
nested pyproject, separate licence/version and separate test tree have been removed.

| Workflow | Package | Dependency profile | Entry point |
| --- | --- | --- | --- |
| Audio-derived designer | `beqforge` | `designer` | `beqforge` |
| Device measurement | `beqforge_device_check` | `device-check` | `beqforge-device-check` |
| Published coefficient optimisation | `beqoptimiser` | `optimiser` | `beqoptimiser` |

`all` installs every use case. NumPy is the common runtime dependency. SciPy is installed
by the workflow profiles; plotting belongs to designer/device-check, and capture/control
libraries belong to device-check. Ruff and scipy-stubs are development dependencies.
One root pyproject and lockfile govern installation. The version lives in
`beq_common.__version__`; Hatch reads it for wheel and source-distribution metadata.
All packages, CLIs and extras ship in one wheel. The distribution retains Python 3.13/3.14,
matching the current beqcatalogue consumer requirement.

`beq_common` owns `BiquadSpec`, the existing RBJ classes, canonical publication rounding
and distribution provenance. It imports no workflow. None of the three workflows imports
a sibling workflow. The designer retains compatibility exports at its existing public
paths, while device-check imports the shared primitives directly. Optimiser's numerical
implementation lives in `beqoptimiser/core.py`, with public exports in `__init__.py` and
its separate CLI in `cli.py`. Its section rendering uses the shared RBJ classes.

The shared RBJ implementation is AST-identical to the original designer implementation.
No target, ceiling, fitter objective, acceptance or selection logic was changed. Record
fingerprints include the shared source files; analysis cache keys include shared types,
and parametric cache keys additionally include shared RBJ/publication modules. Tests check
that changes invalidate the dependent stages without unnecessarily dropping analysis.
Frozen device-check provenance/stamping uses the neutral package instead of importing the
designer's record module. The legacy `beqforge_revision` provenance field still names the
single distribution build.

Validation:

* Full suite: **739 passed, two skipped**. Includes optimiser, workflow import isolation,
  source fingerprint, frozen cache, designer and device-check tests.
* Wheel and source distribution built from the one root project. Fresh isolated installs
  of base, designer, optimiser and device-check passed their CLI checks. The aggregate
  profile passed all three commands and a real numerical replacement check at each rate.
* Base installs NumPy without SciPy. Optimiser installs NumPy/SciPy without matplotlib,
  pyfar, sounddevice or websocket-client. Development tools do not leak into runtime profiles.
* `tools/smoke_test_install.py` reproduces profile checks against a built wheel in temporary
  environments using locked dependency constraints; CI runs it for all five profiles.
* The existing designer executable workflow now explicitly installs its profile. Device-check
  retains its measurement profile and separate frozen entry point.

The required real-material probe uses scratch symlinks and scratch caches, preserving all
baseline records and caches. The first warm-before/cold-after comparison had no analysis,
verdict or winner change at the probe's reporting precision. Three parametric targets moved
by at most approximately 0.0002 dB. Cached versus recomputed mix spectra differed by about
1.4e-14 dB, which affected the parametric identification fit. Validation therefore also
compares fully recomputed original committed code with fully recomputed consolidated code
in the same environment. This cold-before/cold-after comparison is **unchanged for all
11 titles at `--tol 0`**, covering analysis, targets, rejudged candidates and winners.
The older stored run records predate changes already present in
the committed designer, so a fresh original-code record is the complete-output reference.
The full `28_Years_Later` run was repeated on original and consolidated code using freshly
computed analysis. `compare_records.py` reports **identical**, ignoring only fingerprint
and timings. This covers the fitted/published cascades, corrected curves, headroom and
report content beyond the probe's fields. Baseline records were not overwritten.

Scratch evidence and built artefacts are under `/tmp/beqforge-consolidation/`. Nothing was
published and no device was loaded. Catalogue publication/ezbeq variant selection remain
the separately recorded F2 integration work; this consolidation adds no new workflow API.

### PyPI release publication (6 October 2026)

The executable release workflow now builds wheel/sdist artifacts, checks a tag against the
wheel's declared version, validates metadata with strict Twine checks, and exercises all five
dependency profiles. Package validation precedes release creation. A tag-push publication job
waits for every executable build to succeed, attaches the same distributions to the release,
and uploads to PyPI through Trusted Publishing in the `pypi` GitHub environment. Manual runs
build artifacts without publishing. The README records the required PyPI publisher identity
and one-time environment setup; no release tag or actual PyPI upload was performed here.

Added README metadata to the distribution. Both built artifacts passed strict Twine checks;
the wheel passed a fresh offline installation with the `all` dependency profile and all
three commands. The workflow passed actionlint. No workflow implementation or numerical
behaviour changed inside the Python packages, so no designer regression probe was required.

### Release test gate (6 October 2026)

`tests.yml` is now callable as a reusable workflow while retaining branch-push validation.
The executable release workflow calls it on its own release commit, running designer/shared/
optimiser tests, device-check tests on Linux/macOS/Windows, and all five isolated dependency
profiles. Release creation, executable builds and PyPI publication depend on successful tests.
The manual-build condition explicitly requires successful tests and package validation, so a
skipped release-creation job cannot bypass a failed upstream check. Publication still requires
all executable builds to pass and only runs for a release-tag push. Both changed workflows
passed actionlint and whitespace checks; no release run or publication was triggered locally.
