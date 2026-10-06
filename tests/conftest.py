"""Keep threaded HTTP tests free of repeated process-pool startup."""

import pytest


@pytest.fixture(autouse=True)
def serial_http_fits(request, monkeypatch):
    # The test server runs in a thread: fork is unsafe there, and spawn repeatedly
    # imports the numerical stack. Numerical/parallel tests retain the real pool.
    # Avoid importing designer dependencies in isolated device-check profiles.
    if request.path.name == "test_design_designer_server.py":
        from beqforge import filters

        monkeypatch.setattr(filters, "PARALLEL_FITS", False)
