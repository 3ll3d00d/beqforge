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
