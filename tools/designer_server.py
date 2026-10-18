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
import itertools
import json
import logging
import logging.handlers
import math
import multiprocessing
import os
import queue
import signal
import sys
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from multiprocessing.queues import SimpleQueue
from pathlib import Path
from typing import override

# the package is not installed into the venv, and tools/ rather than the repo root is what
# lands on sys.path when this is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beqforge.designer import (  # noqa: E402
    CONTRACT_VERSION,
    ContractViolation,
    design,
    request_from_json,
    response_to_json,
    validate_response,
)
from beqforge import filters, record  # noqa: E402
from beqforge.accept import AcceptParams  # noqa: E402
from beqforge.cache import DirStore, Store  # noqa: E402
from beqforge.reference import UnusableReference  # noqa: E402
from beqforge.filters import Realisation  # noqa: E402
from beqforge.pipeline import STRATEGIES, PipelineParams  # noqa: E402

logger = logging.getLogger(__name__)

DESIGN_PATH = "/design"

MAX_WORKERS = 8
"""The most designs one server runs at once: the range beqdesigner accepts for an endpoint's
`parallel` (its designer-interface.md §7.2)."""


class _EnvironmentParser(argparse.ArgumentParser):
    """Environment defaults use the same conversions and validation as CLI arguments."""

    def __init__(self, **kwargs):
        self.environment_actions: list[tuple[argparse.Action, bool]] = []
        super().__init__(**kwargs)

    @override
    def add_argument(self, *args, **kwargs) -> argparse.Action:
        action = super().add_argument(*args, **kwargs)
        if action.dest != "help":
            self.environment_actions.append((action, kwargs.get("action") == "append"))
            name = f"BEQFORGE_{action.dest.upper()}"
            action.help = f"{action.help or ''} (env: {name})".strip()
        return action

    @override
    def parse_args(self, args=None, namespace=None) -> argparse.Namespace:
        arguments = list(sys.argv[1:] if args is None else args)
        if "--help" in arguments or "-h" in arguments:
            return super().parse_args(arguments, namespace)
        explicit = {argument.split("=", 1)[0] for argument in arguments}
        if self.allow_abbrev:
            options = [
                option
                for action, _ in self.environment_actions
                for option in action.option_strings
            ]
            for flag in tuple(explicit):
                matches = [option for option in options if option.startswith(flag)]
                if flag.startswith("--") and len(matches) == 1:
                    explicit.add(matches[0])
        defaults: list[str] = []
        for action, repeatable in self.environment_actions:
            name = f"BEQFORGE_{action.dest.upper()}"
            value = os.environ.get(name)
            if value is None or explicit.intersection(action.option_strings):
                continue
            option = action.option_strings[0]
            if isinstance(action, argparse.BooleanOptionalAction):
                lowered = value.strip().lower()
                if lowered not in ("1", "true", "yes", "on", "0", "false", "no", "off"):
                    self.error(f"{name} must be true/false, yes/no, on/off or 1/0")
                if lowered in ("1", "true", "yes", "on"):
                    defaults.append(option)
            elif repeatable:
                try:
                    items = json.loads(value)
                except ValueError:
                    self.error(f"{name} must be a JSON array")
                if not isinstance(items, list):
                    self.error(f"{name} must be a JSON array")
                for item in items:
                    if action.nargs == 2:
                        if not isinstance(item, list) or len(item) != 2:
                            self.error(f"{name} must be a JSON array of pairs")
                        defaults.extend([option, *(str(part) for part in item)])
                    else:
                        if not isinstance(item, str):
                            self.error(f"{name} must be a JSON array of strings")
                        defaults.append(f"{option}={item}")
            else:
                defaults.append(f"{option}={value}")
        return super().parse_args([*defaults, *arguments], namespace)


def _prepare_directory(path: Path) -> None:
    """Create the directory and exercise an actual write before accepting requests."""
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path, prefix=".beqforge-startup-") as probe:
        probe.write(b"beqforge directory check\n")
        probe.flush()


@dataclass(frozen=True, slots=True)
class DesignSettings:
    """Everything server-wide a design needs: what the worker process is started with."""

    params: PipelineParams
    record_dir: Path | None = None
    cache: Store | None = None
    shared_root: Path | None = None


# The worker process's own state, set once by `_start_worker`.
_worker_settings: DesignSettings | None = None
_worker_logs: SimpleQueue | None = None


class _LogToParent(logging.handlers.QueueHandler):
    """A `QueueHandler` onto a `SimpleQueue`, which has no `put_nowait`. A `SimpleQueue` and
    not a `Queue` because `Queue.put` starts a feeder thread, and the worker must stay
    single-threaded when the fitter forks (see `_DesignWorker`)."""

    @override
    def enqueue(self, record: logging.LogRecord) -> None:
        self.queue.put(record)


def _start_worker(
    settings: DesignSettings, logs: SimpleQueue, level: int, fit_workers: int | None
) -> None:
    global _worker_settings, _worker_logs
    _worker_settings = settings
    _worker_logs = logs
    if fit_workers is not None:
        # this worker's share of the machine, when it designs beside others (`fit_share`)
        filters.FIT_WORKERS = fit_workers
    root = logging.getLogger()
    root.handlers[:] = [_LogToParent(logs)]
    root.setLevel(level)
    if hasattr(os, "setpgrp"):
        # its own process group, the fitter's processes in it too: `_DesignWorker.close`
        # stops them all, and a terminal's Ctrl-C reaches only the server, which does that
        os.setpgrp()


def _ready() -> None:
    """A no-op task: once it answers, the worker has started and imported the pipeline."""


def _design_in_worker(raw: bytes, token: int) -> tuple[int, dict, dict[str, float]]:
    """One request body to (status, JSON payload, timings), in the worker process.

    Every log record the request produced is in the log queue ahead of `token`, so the
    parent can wait for them before answering (`_DesignWorker.run`).
    """
    assert _worker_settings is not None and _worker_logs is not None
    settings = _worker_settings
    try:
        started = time.perf_counter()
        try:
            body = json.loads(raw)
            parsed = time.perf_counter()
            request = request_from_json(body, shared_root=settings.shared_root)
            decoded = time.perf_counter()
        except UnusableReference as refused:
            # a well-formed reference this server cannot honour: a configuration error on one
            # side or the other, never a decline and never retried inline (§3, §4)
            logger.warning(f"unusable reference: {refused}")
            return (
                422,
                {
                    "error": f"cannot use {refused.array} by reference: {refused.reason}",
                    "array": refused.array,
                    "reason": refused.reason,
                },
                {},
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as malformed:
            logger.warning(f"malformed request body: {malformed}")
            return 400, {"error": f"malformed DesignRequest: {malformed}"}, {}

        response = design(
            request,
            settings.params,
            record_dir=settings.record_dir,
            cache=settings.cache,
        )
        designed = time.perf_counter()
        try:
            validate_response(response)
        except ContractViolation as bug:
            # our own mapping is wrong, never the caller's fault -- never ship it.
            logger.error(f"response failed self-validation: {bug}")
            return 500, {"error": f"designer produced an invalid response: {bug}"}, {}
        outcome = (
            "declined"
            if response.decline_reason
            else f"{len(response.candidates)} candidate(s)"
        )
        logger.info(f"POST {DESIGN_PATH}: {outcome}")
        payload = response_to_json(response)
        return (
            200,
            payload,
            {
                "parse": parsed - started,
                "decode": decoded - parsed,
                "design": designed - decoded,
                "worker": time.perf_counter() - started,
            },
        )
    finally:
        _worker_logs.put(token)


def fit_share(workers: int, cores: int | None = None) -> int | None:
    """Each design worker's fit pool when `workers` designs run at once, or None to leave
    `filters.FIT_WORKERS` alone.

    One design's pool is the physical cores less one (`filters.FIT_WORKERS`): wider than that,
    one design's fits gain nothing from SMT threads. Several designs at once are what can use
    them, so they share the logical processors, less one, capped at that width each. Dividing
    the physical cores instead gave two designs together the machine one already had, and
    `--workers 2` gained nothing on an SMT machine. Only the time a fit takes depends on its
    pool, never its answer. An explicit `BEQ_FIT_WORKERS` is left as each design's own, as
    it always was.

    `cores` (`--cores`) caps the processors the server's designs use between them, for a
    machine that has other work to do: they share it evenly, still at most one design's
    width each, whether or not `BEQ_FIT_WORKERS` set that width.
    """
    if cores is not None:
        return max(1, min(filters.FIT_WORKERS, cores // workers))
    if workers <= 1 or os.environ.get("BEQ_FIT_WORKERS"):
        return None
    threads = os.process_cpu_count() or os.cpu_count() or 1
    return max(1, min(filters.FIT_WORKERS, (threads - 1) // workers))


class _DesignWorker:
    """One long-lived process that runs designs, one at a time, for a threaded server.

    The fitter forks worker processes (`beqforge.filters.PARALLEL_FITS`, a default-context
    `ProcessPoolExecutor`) when a fit escalates past one section count, and forking a
    multi-threaded process risks a deadlock: a lock another thread holds at fork time is never
    released in the child. The HTTP server is threaded, so `/health` answers while a design
    runs; the design itself runs here, in a process started with "spawn" (no inherited threads
    or locks) whose only thread is the one running the design. Each worker designs one title
    at a time; a server with `--workers N` has N of them, each its own process, so one that
    dies fails only its own request.

    The worker's log records come back over a queue and are handled by the parent's loggers,
    so they reach whatever handlers the server (or a test's `caplog`) has configured.
    """

    def __init__(
        self,
        settings: DesignSettings,
        log_level: int = logging.INFO,
        fit_workers: int | None = None,
    ):
        self._context = multiprocessing.get_context("spawn")
        self._settings = settings
        self._log_level = log_level
        self._fit_workers = fit_workers
        self._logs: SimpleQueue = self._context.SimpleQueue()
        self._tokens = itertools.count()
        self._flushed: dict[int, threading.Event] = {}
        self._flushed_lock = threading.Lock()
        self._forwarder = threading.Thread(
            target=self._forward_logs, name="design-worker-logs", daemon=True
        )
        self._forwarder.start()
        self._pool_lock = threading.Lock()
        self._closed = False
        self._pool = self._start()

    def _start(self) -> ProcessPoolExecutor:
        pool = ProcessPoolExecutor(
            max_workers=1,
            mp_context=self._context,
            initializer=_start_worker,
            initargs=(self._settings, self._logs, self._log_level, self._fit_workers),
        )
        # start it now: a worker that cannot import the pipeline fails here, not on a title
        pool.submit(_ready).result()
        return pool

    def _forward_logs(self) -> None:
        while (item := self._logs.get()) is not None:
            if isinstance(item, int):
                with self._flushed_lock:
                    event = self._flushed.pop(item, None)
                if event is not None:
                    event.set()
                continue
            named = logging.getLogger(item.name)
            if named.isEnabledFor(item.levelno):
                named.handle(item)

    def run(self, raw: bytes) -> tuple[int, dict, dict[str, float]]:
        """Design one request body; raises `BrokenProcessPool` if the worker died doing it,
        having started a new worker for the next request."""
        token = next(self._tokens)
        flushed = threading.Event()
        with self._flushed_lock:
            self._flushed[token] = flushed
        pool = self._pool
        try:
            result = pool.submit(_design_in_worker, raw, token).result()
        except BrokenProcessPool:
            with self._flushed_lock:
                self._flushed.pop(token, None)
            with self._pool_lock:
                if self._pool is pool and not self._closed:
                    logger.error("design worker died; starting another")
                    self._pool = self._start()
            raise
        flushed.wait(timeout=10.0)
        return result

    def close(self) -> None:
        # an idle worker exits as soon as it is told to; one still designing is stopped, with
        # the fitter's processes, rather than waited for: a stopping server has no one to
        # answer, and `docker stop` allows 10 s
        with self._pool_lock:
            self._closed = True
            pool = self._pool
        workers = list(pool._processes.values())
        pool.shutdown(wait=False, cancel_futures=True)
        for process in workers:
            process.join(timeout=1)
            if process.is_alive():
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except (AttributeError, ProcessLookupError):
                    process.terminate()
                process.join(timeout=5)
        self._logs.put(None)
        self._forwarder.join(timeout=5)


class DesignServer(ThreadingHTTPServer):
    """A thread per connection for HTTP, the designs themselves in `workers` `_DesignWorker`s.

    A request takes whichever worker is idle and waits for one when none is, so at most
    `workers` designs run at once and the rest queue in arrival order.
    """

    def __init__(
        self,
        address: tuple[str, int],
        settings: DesignSettings,
        log_level: int = logging.INFO,
        workers: int = 1,
        cores: int | None = None,
    ):
        if not 1 <= workers <= MAX_WORKERS:
            raise ValueError(f"workers must be 1-{MAX_WORKERS}, not {workers}")
        if cores is not None and cores < workers:
            raise ValueError(f"cores must be at least workers ({workers}), not {cores}")
        self.settings = settings
        self.workers: list[_DesignWorker] = []
        self._idle: queue.SimpleQueue[_DesignWorker] = queue.SimpleQueue()
        share = fit_share(workers, cores)
        try:
            for _ in range(workers):
                worker = _DesignWorker(settings, log_level, share)
                self.workers.append(worker)
                self._idle.put(worker)
            super().__init__(address, _Handler)
        except BaseException:
            self._close_workers()
            raise

    def design(self, raw: bytes) -> tuple[int, dict, dict[str, float]]:
        """`_DesignWorker.run` on the next idle worker."""
        worker = self._idle.get()
        try:
            return worker.run(raw)
        finally:
            self._idle.put(worker)

    def _close_workers(self) -> None:
        # together, not one after another: each may take a few seconds to stop a design, and
        # `docker stop` allows 10 s for all of them
        closing = [threading.Thread(target=worker.close) for worker in self.workers]
        for thread in closing:
            thread.start()
        for thread in closing:
            thread.join()

    @override
    def server_close(self) -> None:
        super().server_close()
        self._close_workers()


class _Handler(BaseHTTPRequestHandler):
    server: DesignServer

    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            # 1.2: what a caller registering a by-reference designer checks first, so a
            # server without a shared root shows up at registration, not on its first title.
            # "parallel" is how many designs it runs at once, for a caller to send it that
            # many rather than be told centrally. "status" stays for anything already polling it.
            self._respond(
                200,
                {
                    "status": "ok",
                    "contract_version": CONTRACT_VERSION,
                    "shared_root": self.server.settings.shared_root is not None,
                    "parallel": len(self.server.workers),
                },
            )
            return
        self._respond(404, {"error": f"unknown path {self.path!r}"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != DESIGN_PATH:
            self._respond(
                404, {"error": f"unknown path {self.path!r}, expected {DESIGN_PATH!r}"}
            )
            return
        started = time.perf_counter()
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        read = time.perf_counter()
        try:
            status, payload, timing = self.server.design(raw)
        except BrokenProcessPool:
            self._respond(500, {"error": "the design worker died during this request"})
            return
        returned = time.perf_counter()
        self._respond(status, payload)
        if timing:
            # the wire's share of a request, apart from the design itself: what decides
            # whether requests by reference are worth having (IMPROVEMENT_PLAN R2a/R2b).
            # "queued" is the wait behind other requests plus the trip to the worker.
            logger.info(
                f"request timing: body {length / 1e6:.1f} MB, read {read - started:.2f} s, "
                f"parse {timing['parse']:.2f} s, decode {timing['decode']:.2f} s, "
                f"design {timing['design']:.2f} s, "
                f"respond {time.perf_counter() - returned:.2f} s, "
                f"queued {returned - read - timing['worker']:.2f} s"
            )

    def _respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = _EnvironmentParser(description=__doc__)
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
        "--goal-tolerance",
        type=float,
        default=1.5,
        metavar="DB",
        help="how far from the goal a low end may sit and need no correction (default 1.5)",
    )
    parser.add_argument(
        "--goal-tilt",
        type=float,
        default=0.0,
        metavar="DB_PER_OCT",
        help=(
            "the low end asked for below the knee: 0 flat (default), positive a rise toward "
            "the bottom, negative a gentle rolloff"
        ),
    )
    parser.add_argument(
        "--content-edge",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "opt-in: judge from the content edge, not the tracking floor — recovers steep "
            "filters partway down to where the programme meets the noise, but can lift that "
            "noise where loud scenes stand clear of it (IMPROVEMENT_PLAN, steep filters)"
        ),
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
    parser.add_argument(
        "--record-dir",
        type=Path,
        metavar="DIR",
        help=(
            "write each request's run record here (designer-<digest>.run.json.gz), "
            "replayable with `beqforge replay`; responses name the file"
        ),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        metavar="DIR",
        help=(
            "keep the stage cache here, one file per entry, and reuse any stage whose key "
            "has not moved: a repeat request skips the analysis. Several servers may "
            "share one directory. Created and checked for writes at startup. Off by default"
        ),
    )
    parser.add_argument(
        "--shared-root",
        type=Path,
        metavar="DIR",
        help=(
            "accept audio by reference (contract 1.2): an array may name a WAV by a path "
            "relative to DIR, beqdesigner's work_dir as this host sees it. Paths escaping "
            "DIR, even through a symlink, are refused. Off by default: a reference is then "
            "answered 422. Created and checked for writes at startup"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help=(
            f"how many designs to run at once, 1-{MAX_WORKERS} (default 1); more queue. "
            "Reported on /health as `parallel`. Concurrent designs share the logical "
            "processors (SMT threads included), each at most one design's usual width, "
            "unless BEQ_FIT_WORKERS is set"
        ),
    )
    parser.add_argument(
        "--cores",
        type=int,
        default=None,
        metavar="N",
        help=(
            "the most processors this server's designs use between them, at least --workers "
            "(default: all of them, less one). Shared evenly by concurrent designs"
        ),
    )
    parser.add_argument(
        "--quiet",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="only warnings and above",
    )
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
    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error(f"workers must be 1-{MAX_WORKERS}")
    if args.cores is not None and args.cores < args.workers:
        parser.error(f"cores must be at least workers ({args.workers})")

    params = PipelineParams(
        realisation=Realisation(
            fs=args.device_rate,
            coefficient_bits=args.coefficient_bits,
            integer_bits=args.integer_bits,
        ),
        strategies=strategies,
        exclude_bands_hz=tuple(tuple(b) for b in (args.exclude or ())),  # type: ignore[misc]
        judge_from_content_edge=args.content_edge,
        accept=AcceptParams(
            target_tilt_db_per_octave=args.goal_tilt,
            goal_tolerance_db=args.goal_tolerance,
        ),
    )

    for option, directory in (
        ("--cache-dir", args.cache_dir),
        ("--shared-root", args.shared_root),
    ):
        if directory is not None:
            try:
                _prepare_directory(directory)
            except OSError as error:
                parser.error(
                    f"{option} {directory}: cannot create or write directory: {error}"
                )

    settings = DesignSettings(
        params=params,
        record_dir=args.record_dir,
        cache=DirStore(args.cache_dir) if args.cache_dir else None,
        shared_root=args.shared_root.resolve() if args.shared_root else None,
    )
    server = DesignServer(
        (args.host, args.port),
        settings,
        log_level=logging.WARNING if args.quiet else logging.INFO,
        workers=args.workers,
        cores=args.cores,
    )
    share = fit_share(args.workers, args.cores)
    logger.info(
        f"beqforge designer server: http://{args.host}:{args.port}{DESIGN_PATH} "
        f"(strategies: {', '.join(strategies)}; build {record.revision()}"
        + f"; {args.workers} design(s) at once"
        + (f", {share} fit worker(s) each" if share is not None else "")
        + (f"; records to {args.record_dir}" if args.record_dir else "")
        + (f"; stage cache in {args.cache_dir}" if args.cache_dir else "")
        + (f"; audio by reference under {args.shared_root}" if args.shared_root else "")
        + ")"
    )
    # SIGTERM (`docker stop`, a supervisor, a smoke test) stops the server as Ctrl-C does, so
    # `server_close` stops the design worker rather than leaving it behind. As a container's
    # PID 1 the server would otherwise ignore SIGTERM until Docker's SIGKILL.
    previous = signal.signal(signal.SIGTERM, _interrupt)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        signal.signal(signal.SIGTERM, previous)
    return 0


def _interrupt(signum: int, frame) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    # Windows defaults a redirected/piped stdout (and stderr, where the log goes) to the system codepage rather than
    # UTF-8, which crashes on any non-ASCII output; force UTF-8 so a print never dies
    # on the encoding rather than the content.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
