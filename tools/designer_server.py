#!/usr/bin/env python3
"""Serve `beqforge.designer.design` as an HTTP-bound beqdesigner filter designer.

    uv run python tools/designer_server.py --port 8420

Implements designer-interface.md §7.1 — one POST of a JSON `DesignRequest` to `/design`
per `design()` call, a JSON `DesignResponse` back. Register it on the beqdesigner side with:

    from pipeline.designer.registry import register_designer
    from pipeline.designer.http_binding import http_designer
    register_designer('beqforge.v1', http_designer('http://host:8420/design'))

Device realisation, which strategies run, and authored exclusions are server-wide configuration
(the wire request carries none of that — see `beqforge.designer.design`'s docstring); restart
with different flags to change them. `GET /health` is a plain liveness check, not part of the
contract.
"""

import argparse
import json
import logging
import math
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# the package is not installed into the venv, and tools/ rather than the repo root is what
# lands on sys.path when this is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beqforge.designer import (  # noqa: E402
    ContractViolation,
    design,
    request_from_json,
    response_to_json,
    validate_response,
)
from beqforge.filters import Realisation  # noqa: E402
from beqforge.pipeline import STRATEGIES, PipelineParams  # noqa: E402

logger = logging.getLogger(__name__)

DESIGN_PATH = "/design"


class _Handler(BaseHTTPRequestHandler):
    params: PipelineParams  # set on the class before serving

    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._respond(200, {"status": "ok"})
            return
        self._respond(404, {"error": f"unknown path {self.path!r}"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != DESIGN_PATH:
            self._respond(
                404, {"error": f"unknown path {self.path!r}, expected {DESIGN_PATH!r}"}
            )
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
            request = request_from_json(body)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as malformed:
            logger.warning(f"malformed request body: {malformed}")
            self._respond(400, {"error": f"malformed DesignRequest: {malformed}"})
            return

        response = design(request, self.params)
        try:
            validate_response(response)
        except ContractViolation as bug:
            # our own mapping is wrong, never the caller's fault -- never ship it.
            logger.error(f"response failed self-validation: {bug}")
            self._respond(
                500, {"error": f"designer produced an invalid response: {bug}"}
            )
            return
        outcome = (
            "declined"
            if response.decline_reason
            else f"{len(response.candidates)} candidate(s)"
        )
        logger.info(f"POST {DESIGN_PATH}: {outcome}")
        self._respond(200, response_to_json(response))

    def _respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument(
        "--device-rate",
        type=float,
        default=96000.0,
        metavar="HZ",
        help="published device sample rate",
    )
    parser.add_argument(
        "--coefficient-bits",
        type=int,
        default=28,
        help="device fixed-point coefficient word length",
    )
    parser.add_argument(
        "--integer-bits",
        type=int,
        default=5,
        help="device coefficient integer bits, including sign",
    )
    parser.add_argument(
        "--exclude",
        nargs=2,
        type=float,
        action="append",
        metavar=("LOW", "HIGH"),
        help="authored feature to drop, in Hz; repeatable",
    )
    parser.add_argument(
        "--strategy",
        action="append",
        metavar="NAME",
        help=(
            "target-derivation strategy to run; repeatable. "
            f"One of {', '.join(sorted(STRATEGIES))}, or 'all'. Default: all"
        ),
    )
    parser.add_argument("--quiet", action="store_true", help="only warnings and above")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(message)s",
    )

    chosen = args.strategy or ["all"]
    if "all" in chosen:
        strategies = tuple(STRATEGIES)
    else:
        unknown = [s for s in chosen if s not in STRATEGIES]
        if unknown:
            parser.error(
                f"unknown strategy {', '.join(unknown)}; have {', '.join(sorted(STRATEGIES))}"
            )
        strategies = tuple(chosen)

    if not math.isfinite(args.device_rate) or args.device_rate <= 0:
        parser.error("device rate must be finite and positive")
    if not 0 < args.integer_bits < args.coefficient_bits:
        parser.error("device format requires 0 < integer bits < coefficient bits")

    params = PipelineParams(
        realisation=Realisation(
            fs=args.device_rate,
            coefficient_bits=args.coefficient_bits,
            integer_bits=args.integer_bits,
        ),
        strategies=strategies,
        exclude_bands_hz=tuple(tuple(b) for b in (args.exclude or ())),  # type: ignore[misc]
    )

    _Handler.params = params
    # single-threaded, deliberately: beqforge.filters' fitter forks worker processes
    # (ProcessPoolExecutor, PARALLEL_FITS) when a fit escalates past one section count, and
    # forking a multi-threaded process risks a deadlock (a lock held by another thread at fork
    # time is never released in the child). Serving one request at a time keeps the process
    # single-threaded when that fork happens. Costs nothing real: the contract is one
    # synchronous POST per design() call (designer-interface.md §1), so there is no concurrent
    # request to lose.
    server = HTTPServer((args.host, args.port), _Handler)
    logger.info(
        f"beqforge designer server: http://{args.host}:{args.port}{DESIGN_PATH} "
        f"(strategies: {', '.join(strategies)})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
