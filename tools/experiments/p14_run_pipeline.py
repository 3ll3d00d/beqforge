"""Run the real pipeline over the four titles with the surrogate fitter patched in.

Patched rather than committed: the evidence so far is residuals against targets, and what
decides adoption is whether `accept` reaches the same verdicts. This produces records the
verdict comparison can read, without the package having to believe in it yet.
"""

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import beqforge.filters as F  # noqa: E402
import surrogate  # noqa: E402

F._fit_structure = surrogate.surrogate_structure

from beqforge import record  # noqa: E402
from beqforge.material import load  # noqa: E402
from beqforge.pipeline import PipelineParams, run  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(message)s")
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for name in ("test_71", "test2_71", "test3_71", "test4_71"):
    material_path = Path(f"data/{name}.npz")
    started = time.perf_counter()
    material = load(material_path)
    params = PipelineParams()
    report = run(material, params, cache_path=None)
    record.write(out / f"{name}.run.json.gz", report, params, material_path, None)
    print(
        f"{name}: {report.timings.total_s:.1f}s pipeline, "
        f"{time.perf_counter() - started:.1f}s wall, accepted={report.accepted.label if report.accepted else None}",
        flush=True,
    )
print("ALLDONE")
