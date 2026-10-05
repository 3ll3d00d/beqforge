"""Offline identity ratios and signed error reports; no hardware calls."""

import html
import json
from pathlib import Path

import numpy as np

from beqforge_device_check.coefficients import response, rounded
from beqforge_device_check.evidence import (
    atomic_json,
    evidence_name,
    file_hash,
    register,
)
from beqforge_device_check.manifest import digest, validate
from beqforge_device_check.measurement import carried, worst
from beqforge_device_check.transactions import recompute


def summarise(
    frequencies: np.ndarray,
    delta: np.ndarray,
    mask: np.ndarray,
    tolerance: float | np.ndarray,
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
    registry = json.loads((directory / "files.json").read_text())
    for relative, expected in registry.items():
        is_input = relative in (
            "manifest.json",
            "run.json",
            "qualification.json",
            "inventory.json",
        ) or relative.split("/")[0] in ("analysis", "transport")
        if is_input and (
            not evidence_name(relative) or file_hash(directory / relative) != expected
        ):
            raise ValueError(f"offline evidence changed: {relative}")
    manifest = json.loads((directory / "manifest.json").read_text())
    validate(manifest)
    run = json.loads((directory / "run.json").read_text())
    qualification = json.loads((directory / "qualification.json").read_text())
    if qualification["hash"] != digest(
        {k: v for k, v in qualification.items() if k != "hash"}
    ):
        raise ValueError("qualification hash mismatch")
    if run.get("manifest_hash") != manifest["hash"]:
        raise ValueError("run manifest identity differs")
    cases = {case["id"]: case for case in manifest["cases"]}
    bench_path = directory / "bench.json"
    bench = json.loads(bench_path.read_text()) if bench_path.is_file() else {}
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

        def trace(name: str) -> dict:
            path = directory / "analysis" / f"{name}.npz"
            with np.load(path, allow_pickle=False) as arrays:
                return {key: arrays[key].copy() for key in arrays.files}

        data = trace(attempt)
        frequencies = data["frequencies"]
        # A long-settling cascade's longer tail gives it a finer grid than its identity
        # brackets: they are recovered again on it from their raw sweeps.
        left, right = (
            bracket
            if np.array_equal(bracket["frequencies"], frequencies)
            else recompute(directory, name, bench, len(data["impulse"]))
            for name, bracket in (
                (name, trace(name))
                for name in (completed["before"], completed["after"])
            )
        )
        mask = data["mask"] & left["mask"] & right["mask"]
        level = completed["result"]["level_dbfs"]
        qualified = trace(f"qualification-{level:g}")
        lower, upper, exact, valid = carried(
            qualified["frequencies"], frequencies, qualified["mask"]
        )
        mask &= valid
        uncertainty = worst(qualified["uncertainty_db"], lower, upper, exact)
        uncertainty += data["inversion_bias_db"] + np.maximum(
            left["inversion_bias_db"], right["inversion_bias_db"]
        )
        # Geometric magnitude and circular phase midpoint preserve gain and phase;
        # unlike averaging complex values they cannot attenuate a delayed reference.
        baseline = np.sqrt(np.abs(left["response"] * right["response"])) * np.exp(
            1j
            * (
                np.angle(left["response"])
                + np.angle(right["response"] * np.conj(left["response"])) / 2
            )
        )
        safe = np.maximum(np.abs(baseline), 1e-300) * np.exp(1j * np.angle(baseline))
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
        stored_delta = 20 * np.log10(np.maximum(np.abs(measured / stored_h), 1e-300))
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
                    float(v) if m else None for v, m in zip(delta, mask, strict=True)
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
        valid_error = np.abs(delta[mask])
        valid_budget = uncertainty[mask]
        item["accuracy_assessment"] = {
            "scope": "qualified magnitude bins only; not a recursive arithmetic claim",
            "requirement_db": qualification["accuracy_db"],
            "within_requirement_bins": int(
                np.sum(valid_error + valid_budget <= qualification["accuracy_db"])
            ),
            "exceeds_requirement_bins": int(
                np.sum(valid_error - valid_budget > qualification["accuracy_db"])
            ),
            "unresolved_bins": int(
                np.sum(
                    (valid_error + valid_budget > qualification["accuracy_db"])
                    & (valid_error - valid_budget <= qualification["accuracy_db"])
                )
            ),
            "unqualified_bins": int(np.sum(~mask)),
        }
        assessment = item["accuracy_assessment"]
        assessment["outcome"] = (
            "under-range"
            if not len(valid_error)
            else "exceeds-requirement"
            if assessment["exceeds_requirement_bins"]
            else "unresolved"
            if assessment["unresolved_bins"]
            else "within-requirement"
        )
        item["characteristics"] = {
            "sections": len(case["publication_filters"]),
            "lowest_corner_hz": min(
                (f["freq_hz"] for f in case["publication_filters"]), default=None
            ),
            "maximum_q": max(
                (f["q"] for f in case["publication_filters"]), default=None
            ),
            "rate": case["rate"],
            "predicted_quantisation": summarise(
                frequencies, predicted, mask, qualification["accuracy_db"]
            ),
        }
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
            f"<tr><td>{html.escape(item['name'])}<details><summary>Published filters</summary><pre>{html.escape(json.dumps(item['filters'], indent=2))}</pre>Offset {item['gain_db']} dB: {item['gain_application']}</details></td><td>{item.get('accuracy_assessment', {}).get('outcome', item['status'])}</td><td>{stats.get('worst_db', '—')}</td><td>{stats.get('worst_hz', '—')}</td><td>{stats.get('coverage', '—')}</td></tr>"
        )
    body = f"<!doctype html><meta charset='utf-8'><title>F2 device report</title><h1>F2 device response</h1><p>{html.escape(run['scope'])}. Qualified: {qualification['qualified']}. Complete: {report['complete']}. Restored: {run['restored']}.</p><p>{html.escape(report['limitations'])}</p><p>Positive delta means more output than the published cascade predicts. Invalid bins are missing, never zero.</p><table><tr><th>Case</th><th>Outcome</th><th>Worst absolute delta (dB)</th><th>Frequency (Hz)</th><th>Valid fraction</th></tr>{''.join(rows)}</table><p><a href='report.json'>Machine-readable signed curves and evidence IDs</a></p>"
    body += "".join(
        f"<p><img alt='Signed device response errors' src='{name}'></p>"
        for name in charts
    )
    if "catalogue" in report:
        population = report["catalogue"]
        body += f"<h2>Catalogue population</h2><p>Complete inventory: {population['complete']}. Outcomes: {html.escape(json.dumps(population['counts']))}.</p>"
        body += "<p>Distributions describe this device/session. Unique cascades and source entries are counted separately; reloads are dependent. Each frequency reports its qualified denominator.</p>"
        body += f"<pre>{html.escape(json.dumps({key: population[key] for key in ('entry_weighted', 'unique_cascade_weighted')}, indent=2))}</pre>"
        if plot_population(population["per_frequency"], output):
            body += "<p><img alt='Catalogue error distributions and qualified counts' src='charts/catalogue-population.png'></p>"
    (output / "report.html").write_text(body, encoding="utf-8")
    if output.resolve() == directory.resolve():
        register(directory)
    return report


def plot_population(population: dict, output: Path) -> bool:
    if not population["frequencies"]:
        return False
    import matplotlib.pyplot as plt

    frequencies = population["frequencies"]
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    for name, label in (
        ("unique_cascade_weighted", "Unique cascades"),
        ("entry_weighted", "Catalogue entries"),
    ):
        stats = population[name]
        axes[0].semilogx(
            frequencies,
            [s.get("p95_db", np.nan) for s in stats],
            label=f"{label}: 95th percentile",
        )
        axes[1].semilogx(frequencies, [s["count"] for s in stats], label=label)
    axes[0].semilogx(
        frequencies,
        [s.get("maximum_db", np.nan) for s in population["unique_cascade_weighted"]],
        label="Maximum qualified error",
        alpha=0.6,
    )
    axes[0].set(
        ylabel="Absolute measured / expected error (dB)",
        title="Catalogue population on this device/session",
    )
    axes[1].set(xlabel="Frequency (Hz)", ylabel="Qualified count")
    for axis in axes:
        axis.grid(True, alpha=0.3)
        axis.legend()
    (output / "charts").mkdir(exist_ok=True)
    fig.tight_layout()
    fig.savefig(output / "charts" / "catalogue-population.png", dpi=150)
    plt.close(fig)
    return True


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
            {
                "match_key": key,
                "configurations": [group[key] for group in groups],
                "comparisons": [
                    compare_traces(groups[left][key], groups[right][key], left, right)
                    for left in range(len(groups))
                    for right in range(left + 1, len(groups))
                ],
            }
            for key in sorted(common)
        ],
        "unmatched_counts": [len(group) - len(common) for group in groups],
    }


def sample_trace(
    trace: dict, frequencies: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Interpolate only within adjacent qualified bins, never across missing evidence."""
    source = np.asarray(trace["frequencies"], dtype=float)
    values = np.asarray(trace["delta_exact_db"], dtype=float)
    uncertainty = np.asarray(trace["uncertainty_db"], dtype=float)
    mask = np.asarray(trace["mask"], dtype=bool)
    if (
        source.ndim != 1
        or not len(source)
        or any(array.shape != source.shape for array in (values, uncertainty, mask))
        or np.any(~np.isfinite(source))
        or np.any(source <= 0)
        or np.any(np.diff(source) <= 0)
    ):
        raise ValueError("invalid comparison frequency axis/arrays")
    mask &= np.isfinite(values) & np.isfinite(uncertainty) & (uncertainty >= 0)
    upper = np.searchsorted(source, frequencies)
    upper = np.minimum(upper, len(source) - 1)
    exact = source[upper] == frequencies
    lower = np.maximum(upper - 1, 0)
    valid = (frequencies >= source[0]) & (frequencies <= source[-1])
    valid &= np.where(exact, mask[upper], mask[lower] & mask[upper])
    # Interpolation is for matching grids only; it is not additional measurement.
    result = np.interp(frequencies, source, np.where(mask, values, 0))
    # Retain the larger endpoint uncertainty rather than interpolating it down.
    budget = np.where(
        exact, uncertainty[upper], np.maximum(uncertainty[lower], uncertainty[upper])
    )
    return result, budget, valid


def compare_traces(
    left: list[dict], right: list[dict], left_index: int, right_index: int
) -> dict:
    """Pair only equal stimulus levels and retain every reload without population claims."""
    pairs = []
    omitted = 0
    for first in left:
        for second in right:
            if first.get("level_dbfs") != second.get("level_dbfs"):
                continue
            if "frequencies" not in first or "frequencies" not in second:
                omitted += 1
                continue
            frequencies = np.asarray(first["frequencies"], dtype=float)
            first_values, first_budget, first_mask = sample_trace(first, frequencies)
            second_values, second_budget, second_mask = sample_trace(
                second, frequencies
            )
            mask = first_mask & second_mask
            delta = second_values - first_values
            budget = first_budget + second_budget
            pairs.append(
                {
                    "left_attempt": first.get("attempt"),
                    "right_attempt": second.get("attempt"),
                    "level_dbfs": first.get("level_dbfs"),
                    "frequencies": frequencies.tolist(),
                    "mask": mask.tolist(),
                    "delta_right_minus_left_db": [
                        float(v) if m else None
                        for v, m in zip(delta, mask, strict=True)
                    ],
                    "combined_uncertainty_db": [
                        float(v) if m else None
                        for v, m in zip(budget, mask, strict=True)
                    ],
                    "qualified_pair_bins": int(np.sum(mask)),
                    "outside_common_mask_bins": int(np.sum(~mask)),
                    "bins_exceeding_combined_uncertainty": int(
                        np.sum(mask & (np.abs(delta) > budget))
                    ),
                    "summary": summarise(frequencies, delta, mask, budget),
                    "interpolation": "right trace sampled on left native grid; no extrapolation or bridging invalid bins",
                }
            )
    return {
        "left_configuration": left_index,
        "right_configuration": right_index,
        "sign": "right minus left exact-coefficient departure",
        "pairs": pairs,
        "omitted_missing_curves": omitted,
        "unmatched_left_levels": sorted(
            {t["level_dbfs"] for t in left if "level_dbfs" in t}
            - {t["level_dbfs"] for t in right if "level_dbfs" in t}
        ),
        "unmatched_right_levels": sorted(
            {t["level_dbfs"] for t in right if "level_dbfs" in t}
            - {t["level_dbfs"] for t in left if "level_dbfs" in t}
        ),
        "scope": "individual reload pairs; pair counts are not independent devices or a population estimate",
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
        "per_frequency": frequency_population(inventory, groups, report["accuracy_db"]),
        "uncertainty": "Distributions describe this unit/session; reloads and catalogue versions are dependent. No population confidence interval.",
    }


def frequency_population(inventory: dict, groups: dict, requirement: float) -> dict:
    """One contribution per cascade per display frequency; reloads remain dependent."""
    traces = [
        t
        for items in groups.values()
        for t in items
        if t["status"] == "measured" and "frequencies" in t
    ]
    if not traces:
        return {"frequencies": [], "scope": "no qualified response curves available"}
    low = min(t["frequencies"][0] for t in traces)
    high = max(t["frequencies"][-1] for t in traces)
    frequencies = np.geomspace(low, high, 128)
    contributions = {}
    for case, items in groups.items():
        values, budgets = [], []
        for trace in items:
            if trace["status"] != "measured" or "frequencies" not in trace:
                continue
            delta, budget, mask = sample_trace(trace, frequencies)
            values.append(np.where(mask, delta, np.nan))
            budgets.append(np.where(mask, budget, np.nan))
        if values:
            contributions[case] = (np.asarray(values), np.asarray(budgets))
    weights = {
        case: sum(entry.get("case") == case for entry in inventory["entries"])
        for case in contributions
    }
    summaries = {"entry_weighted": [], "unique_cascade_weighted": []}
    for index in range(len(frequencies)):
        unique_signed, unique_absolute, unique_budget, entry_weights = [], [], [], []
        for case, (values, budgets) in contributions.items():
            mask = np.isfinite(values[:, index]) & np.isfinite(budgets[:, index])
            if not np.any(mask) or not weights[case]:
                continue
            unique_signed.append(float(np.median(values[mask, index])))
            unique_absolute.append(float(np.max(np.abs(values[mask, index]))))
            unique_budget.append(float(np.max(budgets[mask, index])))
            entry_weights.append(weights[case])
        for name, weighting in (
            ("unique_cascade_weighted", np.ones(len(entry_weights), dtype=int)),
            ("entry_weighted", entry_weights),
        ):
            absolute = np.repeat(unique_absolute, weighting)
            signed = np.repeat(unique_signed, weighting)
            budget = np.repeat(unique_budget, weighting)
            stats = distribution(absolute.tolist(), requirement)
            if len(absolute):
                stats["median_signed_db"] = float(np.median(signed))
                stats["maximum_uncertainty_db"] = float(np.max(budget))
                stats["fraction_resolved_exceeding_requirement"] = float(
                    np.mean(absolute - budget > requirement)
                )
            summaries[name].append(stats)
    return {
        "frequencies": frequencies.tolist(),
        **summaries,
        "scope": "128 log-spaced display frequencies within measured axes; interpolate adjacent qualified bins only; denominator reported at every frequency",
        "reload_aggregation": "maximum absolute error and uncertainty, median signed error per cascade; reloads are not independent population members",
    }
