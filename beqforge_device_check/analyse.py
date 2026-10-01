"""Offline identity ratios and signed error reports; no hardware calls."""

import html
import json
from pathlib import Path

import numpy as np

from beqforge_device_check.coefficients import response, rounded
from beqforge_device_check.evidence import atomic_json, register
from beqforge_device_check.manifest import digest, validate


def summarise(
    frequencies: np.ndarray, delta: np.ndarray, mask: np.ndarray, tolerance: float
) -> dict:
    valid = np.flatnonzero(mask)
    if not len(valid):
        return {"status": "under-range", "valid_bins": 0, "coverage": 0}
    worst = valid[np.argmax(np.abs(delta[valid]))]
    # Trapezoid weights only between adjacent valid bins; do not bridge a masked gap.
    weights = np.zeros(len(frequencies))
    adjacent = mask[:-1] & mask[1:]
    intervals = np.diff(np.log(frequencies)) * adjacent
    weights[:-1] += intervals / 2
    weights[1:] += intervals / 2
    rms = (
        float(np.sqrt(np.sum(weights * delta**2) / np.sum(weights)))
        if np.sum(weights)
        else float(abs(delta[worst]))
    )
    excursions = []
    indices = np.flatnonzero(mask & (np.abs(delta) > tolerance))
    if len(indices):
        for segment in np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1):
            excursions.append(
                {
                    "low_hz": float(frequencies[segment[0]]),
                    "high_hz": float(frequencies[segment[-1]]),
                    "peak_db": float(np.max(np.abs(delta[segment]))),
                }
            )
    return {
        "status": "measured",
        "valid_bins": len(valid),
        "coverage": float(np.mean(mask)),
        "worst_db": float(abs(delta[worst])),
        "signed_worst_db": float(delta[worst]),
        "worst_hz": float(frequencies[worst]),
        "rms_log_weighted_db": rms,
        "valid_low_hz": float(frequencies[valid[0]]),
        "valid_high_hz": float(frequencies[valid[-1]]),
        "excursions": excursions,
    }


def analyse(directory: Path, output: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    validate(manifest)
    run = json.loads((directory / "run.json").read_text())
    qualification = json.loads((directory / "qualification.json").read_text())
    if run.get("manifest_hash") != manifest["hash"]:
        raise ValueError("run manifest identity differs")
    cases = {case["id"]: case for case in manifest["cases"]}
    results = []
    output.mkdir(parents=True, exist_ok=True)
    for completed in run["completed"]:
        case = cases[completed["case"]]
        item = {
            "case": case["id"],
            "name": case["name"],
            "filters": case["publication_filters"],
            "gain_db": case["gain_db"],
            "gain_application": case["gain_application"],
            "status": completed["status"],
            "reason": completed.get("reason"),
            "match_key": digest(
                [case["publication_filters"], case["rate"], case["gain_db"]]
            ),
        }
        if completed["status"] != "measured":
            results.append(item)
            continue
        attempt = completed["result"]["attempt"]
        with (
            np.load(
                directory / "analysis" / f"{attempt}.npz", allow_pickle=False
            ) as data,
            np.load(
                directory / "analysis" / f"{completed['before']}.npz",
                allow_pickle=False,
            ) as left,
            np.load(
                directory / "analysis" / f"{completed['after']}.npz", allow_pickle=False
            ) as right,
        ):
            frequencies = data["frequencies"]
            if not np.array_equal(
                frequencies, left["frequencies"]
            ) or not np.array_equal(frequencies, right["frequencies"]):
                raise ValueError("reference frequency axes differ")
            mask = data["mask"] & left["mask"] & right["mask"]
            level = completed["result"]["level_dbfs"]
            with np.load(
                directory / "analysis" / f"qualification-{level:g}.npz",
                allow_pickle=False,
            ) as qualified:
                if not np.array_equal(frequencies, qualified["frequencies"]):
                    raise ValueError("qualification frequency axis differs")
                mask &= qualified["mask"]
                uncertainty = qualified["uncertainty_db"].copy()
            # Geometric magnitude and circular phase midpoint preserve gain and phase;
            # unlike averaging complex values they cannot attenuate a delayed reference.
            baseline = np.sqrt(np.abs(left["response"] * right["response"])) * np.exp(
                1j
                * (
                    np.angle(left["response"])
                    + np.angle(right["response"] * np.conj(left["response"])) / 2
                )
            )
            safe = np.maximum(np.abs(baseline), 1e-300) * np.exp(
                1j * np.angle(baseline)
            )
            measured = data["response"] / safe
            exact = response(
                np.asarray(case["exact_sos"]).reshape(-1, 6), frequencies, case["rate"]
            )
            transport = json.loads(
                (directory / "transport" / f"{attempt}.json").read_text()
            )
            sent = np.asarray(transport["sent_sos"]).reshape(-1, 6)
            sent_h = response(sent, frequencies, case["rate"])
            model = transport.get("model", manifest["profile"]["coefficient_format"])
            stored = transport.get("readback_sos")
            stored_sos = (
                np.asarray(stored).reshape(-1, 6)
                if stored is not None
                else rounded(sent, model)
            )
            stored_h = response(stored_sos, frequencies, case["rate"])
            delta = 20 * np.log10(np.maximum(np.abs(measured / exact), 1e-300))
            stored_delta = 20 * np.log10(
                np.maximum(np.abs(measured / stored_h), 1e-300)
            )
            predicted = 20 * np.log10(np.maximum(np.abs(stored_h / exact), 1e-300))
            identity_drift = 20 * np.log10(
                np.maximum(np.abs(right["response"] / left["response"]), 1e-300)
            )
            item.update(
                {
                    "attempt": attempt,
                    "level_dbfs": completed["result"]["level_dbfs"],
                    "exact": summarise(
                        frequencies, delta, mask, qualification["accuracy_db"]
                    ),
                    "stored_model": summarise(
                        frequencies, stored_delta, mask, qualification["accuracy_db"]
                    ),
                    "storage_verified": transport["storage_verified"],
                    "storage_model": model,
                    "uncertainty_db": uncertainty.tolist(),
                    "phase_limitation": completed["result"]["phase_limitation"],
                    "identity_drift_max_db": float(np.max(np.abs(identity_drift[mask])))
                    if np.any(mask)
                    else None,
                    "frequencies": frequencies.tolist(),
                    "mask": mask.tolist(),
                    "delta_exact_db": [
                        float(v) if m else None
                        for v, m in zip(delta, mask, strict=True)
                    ],
                    "delta_stored_db": [
                        float(v) if m else None
                        for v, m in zip(stored_delta, mask, strict=True)
                    ],
                    "predicted_quantisation_db": predicted.tolist(),
                    "sent_error_db": (
                        20 * np.log10(np.maximum(abs(sent_h / exact), 1e-300))
                    ).tolist(),
                    "phase_delta_degrees": [
                        float(v) if m else None
                        for v, m in zip(
                            np.angle(measured / exact, deg=True), mask, strict=True
                        )
                    ],
                }
            )
            item["status"] = item["exact"]["status"]
        results.append(item)
    report = {
        "schema_version": 1,
        "manifest_hash": manifest["hash"],
        "bench_hash": run["bench_hash"],
        "engine": run["engine"],
        "scope": run["scope"],
        "complete": run.get("complete", False),
        "qualified": qualification["qualified"],
        "accuracy_db": qualification["accuracy_db"],
        "restored": run["restored"],
        "failures": run["failures"],
        "results": results,
        "qualification_scope": qualification["scope"],
        "limitations": "Storage-model agreement cannot identify recursive arithmetic. This unit/session does not establish population behaviour.",
    }
    inventory_path = directory / "inventory.json"
    if inventory_path.exists():
        report["catalogue"] = catalogue_summary(
            json.loads(inventory_path.read_text()), report
        )
    atomic_json(output / "report.json", report)
    rows = []
    charts = plot_discrepancies(results, output)
    for item in results:
        stats = item.get("exact", {})
        rows.append(
            f"<tr><td>{html.escape(item['name'])}<details><summary>Published filters</summary><pre>{html.escape(json.dumps(item['filters'], indent=2))}</pre>Offset {item['gain_db']} dB: {item['gain_application']}</details></td><td>{item['status']}</td><td>{stats.get('worst_db', '—')}</td><td>{stats.get('worst_hz', '—')}</td><td>{stats.get('coverage', '—')}</td></tr>"
        )
    body = f"<!doctype html><meta charset='utf-8'><title>F2 device report</title><h1>F2 device response</h1><p>{html.escape(run['scope'])}. Qualified: {qualification['qualified']}. Complete: {report['complete']}. Restored: {run['restored']}.</p><p>{html.escape(report['limitations'])}</p><p>Positive delta means more output than the published cascade predicts. Invalid bins are missing, never zero.</p><table><tr><th>Case</th><th>Outcome</th><th>Worst absolute delta (dB)</th><th>Frequency (Hz)</th><th>Valid fraction</th></tr>{''.join(rows)}</table><p><a href='report.json'>Machine-readable signed curves and evidence IDs</a></p>"
    body += "".join(
        f"<p><img alt='Signed device response errors' src='{name}'></p>"
        for name in charts
    )
    (output / "report.html").write_text(body, encoding="utf-8")
    if output.resolve() == directory.resolve():
        register(directory)
    return report


def plot_discrepancies(results: list[dict], output: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plotted = set()
    paths = []
    for item in sorted(
        (r for r in results if r["status"] == "measured"),
        key=lambda r: r["exact"]["worst_db"],
        reverse=True,
    ):
        if item["case"] in plotted or len(paths) >= 10:
            continue
        plotted.add(item["case"])
        frequencies = np.asarray(item["frequencies"])
        delta = np.asarray(item["delta_exact_db"], dtype=float)
        uncertainty = np.asarray(item["uncertainty_db"])
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.semilogx(frequencies, delta, label="Measured / exact")
        ax.semilogx(
            frequencies, item["delta_stored_db"], label="Measured / storage model"
        )
        ax.semilogx(
            frequencies,
            item["predicted_quantisation_db"],
            label="Predicted coefficient effect",
        )
        ax.fill_between(
            frequencies,
            delta - uncertainty,
            delta + uncertainty,
            alpha=0.2,
            label="Identity uncertainty",
        )
        ax.set(xlabel="Frequency (Hz)", ylabel="Signed delta (dB)", title=item["name"])
        ax.grid(True, alpha=0.3)
        ax.legend()
        name = f"charts/{item['case']}.png"
        (output / "charts").mkdir(exist_ok=True)
        fig.savefig(output / name, dpi=150, bbox_inches="tight")
        plt.close(fig)
        paths.append(name)
    return paths


def compare(reports: list[dict]) -> dict:
    """Matched cascades only; retain each configuration and qualified masks."""
    if len(reports) < 2:
        raise ValueError("device comparison requires at least two reports")
    groups = []
    for report in reports:
        group = {}
        for item in report["results"]:
            if item["status"] == "measured":
                group.setdefault(item["match_key"], []).append(item)
        groups.append(group)
    common = set.intersection(*(set(group) for group in groups))
    return {
        "schema_version": 1,
        "scope": "matched cascade comparison; repeats are not independent devices",
        "configurations": [
            {"engine": r["engine"], "bench_hash": r["bench_hash"], "scope": r["scope"]}
            for r in reports
        ],
        "matched_cases": [
            {"match_key": key, "configurations": [group[key] for group in groups]}
            for key in sorted(common)
        ],
        "unmatched_counts": [len(group) - len(common) for group in groups],
    }


def distribution(values: list[float], tolerance: float) -> dict:
    if not values:
        return {"count": 0}
    data = np.asarray(values)
    return {
        "count": len(values),
        "median_db": float(np.median(data)),
        "p90_db": float(np.percentile(data, 90)),
        "p95_db": float(np.percentile(data, 95)),
        "maximum_db": float(np.max(data)),
        "fraction_exceeding_requirement": float(np.mean(data > tolerance)),
    }


def catalogue_summary(inventory: dict, report: dict) -> dict:
    # Within-case reloads/levels remain traces, not additional devices/cascades.
    groups = {}
    for item in report["results"]:
        groups.setdefault(item["case"], []).append(item)
    entries, unique = [], {}
    for entry in inventory["entries"]:
        item = {
            k: entry.get(k)
            for k in ("id", "title", "edition", "case", "reason", "scope")
        }
        traces = groups.get(entry.get("case"), [])
        good = [trace for trace in traces if trace["status"] == "measured"]
        if entry["status"] == "unsupported":
            item["status"] = "unsupported"
        elif not traces:
            item["status"] = "incomplete"
        elif not good:
            item["status"] = "under-range"
        elif not report["complete"]:
            item["status"] = "incomplete"
        else:
            item["status"] = "measured"
        if good:
            worst = max(trace["exact"]["worst_db"] for trace in good)
            item["worst_db"] = worst
            unique[entry["case"]] = worst
            item["traces"] = len(good)
        entries.append(item)
    counts = {
        status: sum(item["status"] == status for item in entries)
        for status in ("measured", "unsupported", "under-range", "incomplete")
    }
    entry_values = [item["worst_db"] for item in entries if "worst_db" in item]
    return {
        "source": inventory["source"],
        "entries": entries,
        "counts": counts,
        "complete": inventory["source"]["complete_snapshot_declared"]
        and not counts["incomplete"],
        "entry_weighted": distribution(entry_values, report["accuracy_db"]),
        "unique_cascade_weighted": distribution(
            list(unique.values()), report["accuracy_db"]
        ),
        "uncertainty": "Distributions describe this unit/session; reloads and catalogue versions are dependent. No population confidence interval.",
    }
