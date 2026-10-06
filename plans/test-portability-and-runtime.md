# Test portability and runtime — 2026-10-06

GitHub Actions run `37471444376` failed in the designer/optimiser test job on
macOS and Windows. Its jobs took about 15, 23 and 30 minutes on macOS, Linux
and Windows respectively; device-check jobs completed within three minutes.

The bundled optimiser seed declares a Linux x86_64 numerical environment.
The seed-reuse test incorrectly required a hit on every host. It now supplies
the declared identity to exercise reuse, and separate tests require rejection
when the operating system, architecture, dependencies or long-double precision
differs. Production environment checks and seed bytes remain unchanged.

Windows concurrent cache writers can encounter a transient permission/sharing
violation when atomically replacing the destination. Publication now retries
Windows errors 5, 32 and 33 up to five attempts, with a total backoff of 150 ms.
Other errors and exhausted retries retain the existing unavailable-cache policy.
Tests simulate both successful retry and exhaustion, checking temporary cleanup.

Threaded HTTP designer tests use the real serial fitter; numerical tests retain
the production pool and exact serial/parallel comparisons on every OS.
The HTTP cache/transport helper limits searches to one section, retaining real
analysis, fitting, judgement and cache handling. The accepted-candidate HTTP test
retains its original section budget. Production numerical code is unchanged.
CI limits numerical-library threads to one and reports the slowest 25 tests.

An interrupted local baseline completed 174 tests in 153 seconds; its HTTP cache
tests cost 35 and 43 seconds and forked from a server thread. Switching to serial
alone increased the repeated-cache test to 88 seconds locally, so it was not
sufficient: the irrelevant escalation work also needed bounding. These partial
runs are diagnostic evidence, not full-suite speed comparisons.

Native macOS/Windows confirmation and hosted-runner timings require the next
GitHub Actions run.

Final validation used the existing Python 3.13 environment with all workflow
dependencies, the sleep inhibitor and the CI numerical-thread limits:
`782 passed, 2 skipped, 1 warning in 334.28s`. The existing digital-silence
subtraction warning remains. The HTTP setting-change/cache test fell from
43.03 seconds in the diagnostic baseline to 3.70 seconds; the accepted-candidate
test still exercises the full budget (20.72 seconds). This is a per-test local
comparison, not a measured hosted-runner or whole-suite speedup.

Ruff check and formatting checks passed for all changed Python files, and
`git diff --check` passed. Repository-wide Ruff reports 176 existing issues
outside those files. No designer production module or shared arithmetic changed,
so the real-material designer regression probe was not required.

## Hosted-runner follow-up

[Actions run 37482206312](https://github.com/3ll3d00d/beqforge/actions/runs/37482206312)
passed on all platforms. Pytest times were 7m54s on Linux, 9m23s on macOS and
11m26s on Windows. Linux's apparent remaining slowdown was installation:
the ffmpeg step took 8m40s, downloading 94.1 MB across 99 packages from
`azure.archive.ubuntu.com`. Actual Linux pytest time fell from 22m41s to 7m54s.

The Linux installation now reuses existing ffmpeg/ffprobe commands when present,
uses Ubuntu's archive mirror instead of the observed slow Azure mirror, and
omits recommended packages. Real ffmpeg integration coverage remains enabled.
The shell block passes `bash -n`; native installation timing awaits the next run.

The escalation stopping test alone cost 44.78s on Linux (32.00s on macOS,
57.69s on Windows). It now controls the fit residual and records submitted
section counts, testing both early settling and full escalation without running
the optimiser. The independent numerical enumeration-equivalence and parallel
tests still execute real searches. Validation: all 47 filter/parallel tests passed
in 52.64s with the inhibitor; the modified test's call took under 0.005s.
Formatting and whitespace checks passed. Ruff reports three existing import/dict
style issues elsewhere in `tests/test_design_filters.py`.
