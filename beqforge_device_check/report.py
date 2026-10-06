"""The human-readable page: per filter, designed vs predicted vs actual, and two verdicts.

Two questions are kept apart because they have different answers and different owners:

* Device: does the hardware play the coefficients it was sent as they predict? PASS,
  FAIL or UNRESOLVED against the accuracy requirement, including the bench uncertainty.
* Representation: can the device's coefficient format represent the filter at all?
  The predicted (e.g. float32) response against the designed one; computed, not measured.

A filter can PASS on the device and still be DEGRADED by its coefficients, as a very low,
high-Q section is in float32 at 96 kHz.
"""

import html
from pathlib import Path

import numpy as np

# Reference palette, light surface: categorical slots 1-3 (validated all-pairs) and
# text/grid tokens. Line style carries identity too, so colour is never alone.
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
INTENDED, PREDICTED, MEASURED = "#2a78d6", "#eb6834", "#1baf7a"

MARKS = {"pass": "PASS", "fail": "FAIL", "unresolved": "UNRESOLVED", "under-range": "—"}


def grouped(results: list[dict]) -> list[dict]:
    """One row per filter and level; reloads are dependent repeats, not more filters."""
    rows: dict[tuple, dict] = {}
    for item in results:
        if item.get("status") != "measured" and "device" not in item:
            continue
        row = rows.setdefault(
            (item["case"], item.get("level_dbfs")),
            {
                "case": item["case"],
                "name": item["name"],
                "filters": item["filters"],
                "level_dbfs": item.get("level_dbfs"),
                "loads": [],
            },
        )
        row["loads"].append(item)
    for row in rows.values():
        loads = row["loads"]
        outcomes = [load["device"]["outcome"] for load in loads]
        row["device"] = next(
            (o for o in ("fail", "unresolved", "under-range") if o in outcomes), "pass"
        )
        worst = max(loads, key=lambda load: load["device"].get("worst_db") or 0)
        row["device_worst_db"] = worst["device"].get("worst_db")
        row["device_worst_hz"] = worst["device"].get("worst_hz")
        row["representation"] = loads[0]["representation"]
    return list(rows.values())


def describe(filters: list[dict]) -> str:
    names = {"low_shelf": "low shelf", "peaking_eq": "peak", "high_shelf": "high shelf"}
    return "; ".join(
        f"{names.get(f['type'], f['type'])} {f['freq_hz']:g} Hz, "
        f"{f['gain_db']:+g} dB, Q {f['q']:g}"
        for f in filters
    )


def label(row: dict) -> str:
    """A single section by its parameters; a real cascade by its title."""
    if len(row["filters"]) == 1:
        return describe(row["filters"])
    return f"{row['name']} ({len(row['filters'])} sections)"


# Responses are drawn as beqdesigner and the catalogue draw them: linear, 1-160 Hz.
FREQUENCY_AXIS_HZ = (1, 160)
FREQUENCY_TICKS_HZ = (1, 20, 40, 60, 80, 100, 120, 140, 160)


def plain(axis) -> None:
    """Label a log axis with real values (0.01, 0.1, 1, 10), not powers of ten."""
    from matplotlib.ticker import FuncFormatter, NullFormatter

    axis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    axis.set_minor_formatter(NullFormatter())


def style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(True, which="both", color=GRID, linewidth=0.6)
    ax.tick_params(colors=MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_visible(False)


def judged_range(row: dict) -> str:
    load = min(row["loads"], key=lambda load: load["stored_model"].get("coverage", 0))
    stats = load["stored_model"]
    if stats.get("status") != "measured":
        return "nothing judged"
    return (
        f"{stats['coverage']:.0%} of bins, {stats['valid_low_hz']:.1f}-"
        f"{stats['valid_high_hz']:.0f} Hz"
    )


def filter_chart(row: dict, requirement: float, path: Path) -> None:
    import matplotlib.pyplot as plt

    load = row["loads"][0]
    f = np.asarray(load["frequencies"])
    curves = load["curves_db"]
    actual = np.array([np.nan if v is None else v for v in curves["measured"]])
    # Records written before every curve was kept whole carry only judged bins.
    full = curves.get("measured_minus_predicted", load["delta_stored_db"])
    difference = np.array([np.nan if v is None else v for v in full])
    judged = np.asarray(load["mask"], dtype=bool)
    fig, (top, bottom) = plt.subplots(
        2,
        1,
        figsize=(8, 5.2),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1.4]},
        facecolor=SURFACE,
    )
    top.plot(f, curves["intended"], color=INTENDED, lw=2, ls="--", label="Designed")
    top.plot(
        f, curves["predicted"], color=PREDICTED, lw=2, label="Predicted (coefficients)"
    )
    top.plot(f, actual, color=MEASURED, lw=1.5, label="Actual")
    top.set_ylabel("Response (dB)", color=MUTED, fontsize=9)
    top.set_title(
        f"{label(row)} at {row['level_dbfs']:.1f} dBFS; judged on {judged_range(row)}",
        color=INK,
        fontsize=10,
        loc="left",
    )
    top.legend(frameon=False, fontsize=8, labelcolor=INK)
    # Every bin is drawn; only judged bins are solid. An unjudged bin is one the bench
    # could not measure finely enough to tell a requirement-sized difference.
    bottom.axhspan(-requirement, requirement, color=GRID, alpha=0.6, lw=0)
    bottom.plot(f, difference, color=MEASURED, lw=1, alpha=0.35, label="Not judged")
    bottom.plot(
        f, np.where(judged, difference, np.nan), color=MEASURED, lw=1.5, label="Judged"
    )
    visible = np.isfinite(difference) & (f <= FREQUENCY_AXIS_HZ[1])
    if np.any(judged & visible):
        # Scale to the judged difference so a small one stays readable; a large
        # unjudged one is still plain in the response above.
        span = max(3 * requirement, 1.25 * np.max(np.abs(difference[judged & visible])))
        bottom.set_ylim(-span, span)
    bottom.set_ylabel("Actual − predicted\n(dB)", color=MUTED, fontsize=8)
    bottom.set_xlabel("Frequency (Hz)", color=MUTED, fontsize=9)
    bottom.set_xlim(*FREQUENCY_AXIS_HZ)
    bottom.set_xticks(FREQUENCY_TICKS_HZ)
    bottom.legend(frameon=False, fontsize=7, labelcolor=INK, loc="upper right")
    for ax in (top, bottom):
        style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def sweeps(rows: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """Single-section filters varying one parameter: (title, axis, rows) per family."""
    single = [r for r in rows if len(r["filters"]) == 1]
    families = []
    for vary, fixed in (("freq_hz", "q"), ("q", "freq_hz")):
        groups: dict[tuple, list] = {}
        for row in single:
            spec = row["filters"][0]
            groups.setdefault(
                (spec["type"], spec[fixed], spec["gain_db"], row["level_dbfs"]), []
            ).append(row)
        for (kind, value, gain, level), members in groups.items():
            if len({m["filters"][0][vary] for m in members}) < 3:
                continue
            members.sort(key=lambda m: m["filters"][0][vary])
            held = f"Q {value:g}" if fixed == "q" else f"{value:g} Hz"
            kind_name = "Low shelf" if kind == "low_shelf" else "Peak"
            title = f"{kind_name} {gain:+g} dB at {held}, {level:.1f} dBFS"
            families.append((title, vary, members))
    return families


def sweep_chart(title: str, vary: str, members: list[dict], requirement: float, path):
    import matplotlib.pyplot as plt

    x = [m["filters"][0][vary] for m in members]
    floor = 1e-4
    representation = [max(m["representation"]["worst_db"], floor) for m in members]
    device = [max(m["device_worst_db"] or floor, floor) for m in members]
    fig, ax = plt.subplots(figsize=(8, 3.6), facecolor=SURFACE)
    ax.plot(
        x,
        representation,
        color=PREDICTED,
        lw=2,
        marker="s",
        ms=6,
        label="Predicted vs designed (coefficients)",
    )
    ax.plot(
        x,
        device,
        color=MEASURED,
        lw=2,
        marker="o",
        ms=6,
        label="Actual vs predicted (device)",
    )
    ax.axhline(requirement, color=MUTED, lw=1, ls=":", label=f"{requirement:g} dB")
    ax.set_yscale("log")
    plain(ax.yaxis)
    if vary == "q":
        ax.set_xscale("log")
        plain(ax.xaxis)
    ax.set_xlabel("Centre frequency (Hz)" if vary == "freq_hz" else "Q", color=MUTED)
    ax.set_ylabel(f"Worst error (dB; < {floor:g} drawn at it)", color=MUTED, fontsize=9)
    ax.set_title(title, color=INK, fontsize=10, loc="left")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK)
    style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def model_chart(rows: list[dict], requirement: float, path: Path) -> None:
    import matplotlib.pyplot as plt

    floor = 1e-4
    x = [max(r["representation"]["worst_db"], floor) for r in rows]
    y = [max(r["device_worst_db"] or floor, floor) for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4), facecolor=SURFACE)
    ax.scatter(x, y, s=36, color=MEASURED, edgecolor=SURFACE, linewidth=1.5, zorder=3)
    ax.axhline(requirement, color=MUTED, lw=1, ls=":")
    ax.annotate(
        f"requirement {requirement:g} dB",
        (min(x), requirement),
        xytext=(0, 4),
        textcoords="offset points",
        color=MUTED,
        fontsize=8,
    )
    ax.set_xscale("log")
    ax.set_yscale("log")
    plain(ax.xaxis)
    plain(ax.yaxis)
    ax.set_xlabel("Predicted coefficient error (dB)", color=MUTED, fontsize=9)
    ax.set_ylabel(
        f"Device error vs prediction (dB; < {floor:g} drawn at it)",
        color=MUTED,
        fontsize=9,
    )
    style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def verdict(rows: list[dict], requirement: float, engine: dict) -> str:
    """The question the report exists to answer, answered first and in words.

    Yes only if every filter passes. Never stronger than the bins judged: where the bench
    could not resolve a requirement-sized difference, nothing is claimed either way, and
    the page says how much that is.
    """
    model = next(
        (r["representation"]["model"] for r in rows if r.get("representation")), "?"
    )
    fails = [r for r in rows if r["device"] == "fail"]
    open_ = [r for r in rows if r["device"] in ("unresolved", "under-range")]
    if fails:
        answer, css = "NO", "fail"
        lead = (
            f"{len(fails)} of {len(rows)} filter results differ from their simulated"
            f" response by more than {requirement:g} dB plus the bench uncertainty."
        )
    elif open_:
        answer, css = "NOT DETERMINED", "unresolved"
        lead = (
            f"No filter result is shown to differ, but {len(open_)} of {len(rows)} could"
            f" not be resolved to within {requirement:g} dB."
        )
    else:
        answer, css = "YES", "pass"
        lead = (
            f"All {len(rows)} filter results play their simulated response to within"
            f" {requirement:g} dB, including the bench uncertainty, on every bin judged."
        )
    coverage = [
        min(load["stored_model"].get("coverage", 0) for load in r["loads"])
        for r in rows
    ]
    unsettled = [
        r
        for r in rows
        if any(
            load.get("convergence", {}).get("outcome") == "unsettled"
            for load in r["loads"]
        )
    ]
    lines = [
        "<h2>Does the device play the simulated response?</h2>",
        f"<p style='font-size:18px'><b class='{css}'>{answer}.</b> {lead}</p>",
        (
            "<p class='muted'>Simulated: the published filters' coefficients as the"
            f" device stores them ({html.escape(str(model))}), computed. Actual: the"
            f" swept {html.escape(engine.get('profile', 'device'))} output with those"
            " coefficients loaded, divided by the same route with the filter bank"
            " empty.</p>"
        ),
    ]
    if fails:
        lines.append(
            "<ul>"
            + "".join(
                f"<li class='fail'>{html.escape(label(r))} at {r['level_dbfs']:.1f} dBFS:"
                f" {r['device_worst_db']:.2f} dB at {r['device_worst_hz']:.1f} Hz</li>"
                for r in fails
            )
            + "</ul>"
        )
    if coverage:
        lines.append(
            f"<p>Judged on a median {np.median(coverage):.0%} of each filter's bins"
            f" (lowest {min(coverage):.0%}). The rest are drawn in each chart but not"
            " judged: there the bench could not tell a"
            f" {requirement:g} dB difference from its own uncertainty.</p>"
        )
    if unsettled:
        lines.append(
            "<p>Not settled within the sweep, so judged only where it had:"
            f" {html.escape(', '.join(sorted({label(r) for r in unsettled})))}.</p>"
        )
    return "".join(lines)


def page(report: dict, output: Path, details: str) -> str:
    import matplotlib

    matplotlib.use("Agg")
    requirement = report["accuracy_db"]
    rows = grouped(report["results"])
    charts = output / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    device_fail = sum(r["device"] == "fail" for r in rows)
    device_open = sum(r["device"] in ("unresolved", "under-range") for r in rows)
    # Representation is a property of the filter, not of the level it was played at.
    filters = {r["case"]: r for r in rows}
    degraded = sum(
        r["representation"]["outcome"] == "degraded" for r in filters.values()
    )
    engine = report["engine"]
    lines = [
        "<!doctype html><meta charset='utf-8'><title>Device check report</title>",
        "<style>body{font:14px/1.45 system-ui,sans-serif;max-width:960px;margin:24px auto;"
        f"padding:0 16px;color:{INK};background:{SURFACE}}}table{{border-collapse:collapse;"
        "width:100%}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid "
        f"{GRID}}}th{{color:{MUTED};font-weight:600}}.pass{{color:#006300}}.fail{{color:"
        "#b3261e;font-weight:700}.unresolved{color:#8a5a00}.muted{color:" + MUTED + "}"
        "img{max-width:100%}</style>",
        "<h1>Device check</h1>",
        (
            f"<p class='muted'>{html.escape(engine.get('profile', ''))}, serial "
            f"{html.escape(str(engine.get('serial', '—')))}, helper "
            f"{html.escape(str(engine.get('helper_version', '—')))}. Accuracy requirement "
            f"{requirement:g} dB.</p>"
        ),
        verdict(rows, requirement, engine),
        "<h2>Summary</h2><ul>",
        f"<li><b>Device:</b> {len(rows) - device_fail - device_open} of {len(rows)} "
        "filter/level results play exactly as their coefficients predict"
        + (f"; <span class='fail'>{device_fail} FAIL</span>" if device_fail else "")
        + (f"; {device_open} unresolved" if device_open else "")
        + ".</li>",
        (
            f"<li><b>Coefficients:</b> {degraded} of {len(filters)} filters cannot be represented "
            f"within {requirement:g} dB by the device's coefficient format (predicted, "
            "independent of the hardware).</li>"
        ),
        (
            "<li class='muted'>After the run the bench route was re-applied and the master left "
            "muted: coefficients cannot be read back to verify restoration.</li></ul>"
        ),
    ]
    if len(rows) >= 5:
        lines.append("<h2>Device error against predicted coefficient error</h2>")
        model_chart(rows, requirement, charts / "model.png")
        lines.append(
            "<p class='muted'>Each point is one filter. If the device plays its"
            " coefficients as predicted, every point sits below the requirement line"
            " however large the coefficient error is.</p>"
            "<p><img alt='Device error against predicted coefficient error'"
            " src='charts/model.png'></p>"
        )
    families = sweeps(rows)
    if families:
        lines.append("<h2>Characterisation</h2>")
        for index, (title, vary, members) in enumerate(families):
            name = f"sweep-{index}.png"
            sweep_chart(title, vary, members, requirement, charts / name)
            lines.append(f"<p><img alt='{html.escape(title)}' src='charts/{name}'></p>")
    lines.append(
        "<h2>Filters</h2><table><tr><th>Filter</th><th>Level</th><th>Loads</th>"
        "<th>Device (actual vs predicted)</th><th>Judged</th>"
        "<th>Coefficients (predicted vs designed)</th></tr>"
    )
    for row in rows:
        mark = MARKS[row["device"]]
        device = f"<span class='{row['device']}'>{mark}</span>" + (
            f" <span class='muted'>worst {row['device_worst_db']:.4f} dB at "
            f"{row['device_worst_hz']:.1f} Hz</span>"
            if row["device_worst_db"] is not None
            else ""
        )
        rep = row["representation"]
        coefficients = (
            f"OK <span class='muted'>({rep['worst_db']:.3f} dB)</span>"
            if rep["outcome"] == "ok"
            else f"<span class='fail'>DEGRADED</span> {rep['worst_db']:.2f} dB at "
            f"{rep['worst_hz']:.1f} Hz"
        )
        chart = f"filter-{row['case'][:12]}-{row['level_dbfs']:g}.png"
        filter_chart(row, requirement, charts / chart)
        lines.append(
            f"<tr><td><a href='charts/{chart}'>{html.escape(label(row))}"
            f"</a></td><td>{row['level_dbfs']:.1f} dBFS</td><td>{len(row['loads'])}</td>"
            f"<td>{device}</td><td class='muted'>{judged_range(row)}</td>"
            f"<td>{coefficients}</td></tr>"
        )
    lines.append("</table>")
    for row in rows:
        chart = f"filter-{row['case'][:12]}-{row['level_dbfs']:g}.png"
        lines.append(
            f"<p><img alt='{html.escape(label(row))}' src='charts/{chart}'></p>"
        )
    lines.append(
        "<details><summary>Technical detail</summary>"
        + details
        + "<p><a href='report.json'>Every curve, uncertainty and evidence id"
        " (report.json)</a></p></details>"
    )
    return "\n".join(lines)


def catalogue_page(
    predictions: dict, threshold_db: float, output: Path, manifest: dict
) -> str:
    """Every catalogue entry's predicted coefficient error, worst first, for people."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    entries = [e for e in predictions["entries"] if "worst_db" in e]
    entries.sort(key=lambda e: e["worst_db"], reverse=True)
    errors = np.array([e["worst_db"] for e in entries])
    flagged = [e for e in entries if e["worst_db"] > threshold_db]
    distinct = len(predictions["cases"])
    low, high = predictions["band_hz"]
    (output / "charts").mkdir(parents=True, exist_ok=True)
    levels = np.geomspace(max(errors.min(), 1e-3), errors.max(), 200)
    fig, ax = plt.subplots(figsize=(8, 3.8), facecolor=SURFACE)
    ax.plot(
        levels,
        [100 * np.mean(errors > level) for level in levels],
        color=PREDICTED,
        lw=2,
    )
    ax.axvline(threshold_db, color=MUTED, lw=1, ls=":")
    ax.annotate(
        f"{100 * len(flagged) / len(entries):.0f}% above {threshold_db:g} dB",
        (threshold_db, 100 * len(flagged) / len(entries)),
        xytext=(8, 8),
        textcoords="offset points",
        color=INK,
        fontsize=9,
    )
    ax.set_xscale("log")
    plain(ax.xaxis)
    ax.set_xlabel(
        f"Predicted worst error over {low:g}-{high:g} Hz (dB)", color=MUTED, fontsize=9
    )
    ax.set_ylabel("Entries above it (%)", color=MUTED, fontsize=9)
    ax.set_title(
        f"{predictions['coefficient_format']} coefficients at {predictions['rate']} Hz",
        color=INK,
        fontsize=10,
        loc="left",
    )
    style(ax)
    fig.tight_layout()
    fig.savefig(output / "charts" / "catalogue-errors.png", dpi=130, facecolor=SURFACE)
    plt.close(fig)
    source = predictions["source"]
    index = write_cascades(manifest, predictions, output)
    rows = "".join(
        "<tr data-c='{c}'{flag}><td>{title}</td><td>{edition}</td><td>{year}</td>"
        "<td>{author}</td><td>{sections}</td><td><b>{worst:.2f}</b></td>"
        "<td>{hz:.1f}</td><td>{above:.2f}</td><td>{link}</td></tr>".format(
            c=index[e["case"]],
            flag=" class='hi'" if e["worst_db"] > threshold_db else "",
            title=html.escape(e["title"]),
            edition=html.escape(e.get("edition") or ""),
            year=html.escape(str(e.get("year") or "")),
            author=html.escape(e.get("author") or ""),
            sections=e["sections"],
            worst=e["worst_db"],
            hz=e["worst_hz"],
            above=e["from_10_hz_db"],
            link=f"<a href='{html.escape(e['url'])}'>page</a>" if e.get("url") else "",
        )
        for e in entries
        if e["case"] in index
    )
    percentiles = np.percentile(errors, [50, 90, 99])
    return "\n".join(
        [
            "<!doctype html><meta charset='utf-8'><title>Catalogue coefficient error</title>",
            (
                "<style>body{font:14px/1.45 system-ui,sans-serif;max-width:1100px;margin:24px auto;"
                f"padding:0 16px;color:{INK};background:{SURFACE}}}table{{border-collapse:collapse;"
                f"width:100%}}td,th{{text-align:left;padding:4px 8px;border-bottom:1px solid {GRID}}}"
                f"th{{color:{MUTED}}}.muted{{color:{MUTED}}}img{{max-width:100%}}"
                "input[type=search]{font:inherit;padding:4px 8px;width:100%;max-width:360px}"
                f"tbody tr{{cursor:pointer}}tbody tr:hover{{background:{GRID}}}"
                f"tr.sel{{outline:2px solid {INTENDED}}}#plot{{position:sticky;top:0;"
                f"background:{SURFACE};padding:8px 0;border-bottom:1px solid {GRID};z-index:1}}"
                f"#tip{{position:absolute;pointer-events:none;background:{SURFACE};border:1px "
                f"solid {GRID};padding:4px 8px;font-size:12px;display:none}}"
                f"svg text{{fill:{MUTED};font-size:11px}}</style>"
            ),
            "<h1>Catalogue coefficient error</h1>",
            (
                f"<p class='muted'>Predicted, not measured: each entry's published "
                f"coefficients rounded to {predictions['coefficient_format']} at "
                f"{predictions['rate']} Hz, against its designed filters. Snapshot "
                f"{html.escape(str(source.get('revision')))} ({source.get('entries')} "
                f"entries, sha256 {str(source.get('sha256'))[:12]}).</p>"
            ),
            (
                f"<p><b>{len(flagged)} of {len(entries)} entries</b> "
                f"({100 * len(flagged) / len(entries):.0f}%; {distinct} distinct cascades) "
                f"are predicted to err by more than {threshold_db:g} dB somewhere in "
                f"{low:g}-{high:g} Hz. Median {percentiles[0]:.2f} dB, 90th percentile "
                f"{percentiles[1]:.2f} dB, 99th {percentiles[2]:.2f} dB, worst "
                f"{errors.max():.2f} dB.</p>"
            ),
            (
                "<p><img alt='Share of entries above each predicted error' "
                "src='charts/catalogue-errors.png'></p>"
            ),
            "<h2>Entries</h2>",
            (
                "<p class='muted'>Click an entry to plot its designed response against the "
                f"response its {predictions['coefficient_format']} coefficients produce."
                "</p><div id='plot'><div id='title' style='font-weight:600'></div>"
                "<svg id='chart' viewBox='0 0 800 360' width='100%'"
                " role='img' aria-label='Designed and predicted response'></svg></div>"
                "<div id='tip'></div>"
            ),
            (
                "<p><input type='search' id='q' placeholder='Filter by title, author or year'>"
                f" <label><input type='checkbox' id='only' checked> only above {threshold_db:g}"
                " dB</label> <a href='predictions.csv'>All entries (CSV)</a></p>"
            ),
            (
                "<table><thead><tr><th>Title</th><th>Edition</th><th>Year</th><th>Author</th>"
                "<th>Sections</th><th>Worst (dB)</th><th>At (Hz)</th><th>Worst from 10 Hz (dB)"
                f"</th><th></th></tr></thead><tbody>{rows}</tbody></table>"
            ),
            "<script src='cascades.js'></script>",
            "<script>"
            + VIEWER_JS.replace("__RATE__", str(predictions["rate"]))
            .replace("__INTENDED__", INTENDED)
            .replace("__PREDICTED__", PREDICTED)
            .replace("__GRID__", GRID)
            .replace("__INK__", INK)
            + "</script>",
        ]
    )


def write_cascades(manifest: dict, predictions: dict, output: Path) -> dict[str, int]:
    """Every predicted cascade's coefficients, for the page to plot without a server.

    Exact coefficients at full round-trip precision; the page rounds them to float32
    with Math.fround, as numpy does. Where a published coefficient rounds to a different
    float32 than the exact one, that section's float32 coefficients are stored too, so
    the plot shows exactly what was predicted.
    """
    import json

    index, data = {}, []
    for case in manifest["cases"][1:]:
        if case["id"] not in predictions["cases"]:
            continue
        exact = np.asarray(case["exact_sos"], dtype=np.float64).reshape(-1, 6)
        sent = np.asarray(case.get("transport_sos", exact), dtype=np.float64)
        sent = sent.reshape(-1, 6).astype(np.float32)[:, [0, 1, 2, 4, 5]]
        exact5 = exact[:, [0, 1, 2, 4, 5]]
        overrides = [
            [i, *map(float, sent[i])]
            for i in range(len(exact5))
            if not np.array_equal(exact5[i].astype(np.float32), sent[i])
        ]
        index[case["id"]] = len(data)
        data.append([exact5.ravel().tolist(), overrides])
    (output / "cascades.js").write_text(
        "window.CASCADES=" + json.dumps(data, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    return index


# Plots one cascade: designed (exact) vs predicted (float32) magnitude over 2-200 Hz,
# with the difference beneath; a crosshair tooltip reads all three at any frequency.
VIEWER_JS = r"""
(() => {
const RATE = __RATE__, LO = 1, HI = 160, N = 640;
const F = Array.from({length: N}, (_, i) => LO + (HI - LO) * i / (N - 1));
const W = 800, L = 52, R = 16, T = 12, TOPH = 220, GAP = 30, BOTH = 80;
const svg = document.getElementById('chart'), tip = document.getElementById('tip');
function db(sections) {
  return F.map(f => {
    const w = 2 * Math.PI * f / RATE, c1 = Math.cos(w), s1 = -Math.sin(w);
    const c2 = Math.cos(2 * w), s2 = -Math.sin(2 * w);
    let mag = 1;
    for (const [b0, b1, b2, a1, a2] of sections) {
      const nr = b0 + b1 * c1 + b2 * c2, ni = b1 * s1 + b2 * s2;
      const dr = 1 + a1 * c1 + a2 * c2, di = a1 * s1 + a2 * s2;
      mag *= Math.sqrt((nr * nr + ni * ni) / (dr * dr + di * di));
    }
    return 20 * Math.log10(mag);
  });
}
function curves(c) {
  const [flat, overrides] = window.CASCADES[c];
  const exact = [], stored = [];
  for (let i = 0; i < flat.length; i += 5) {
    const s = flat.slice(i, i + 5);
    exact.push(s);
    stored.push(s.map(Math.fround));
  }
  for (const [i, ...s] of overrides) stored[i] = s;
  return [db(exact), db(stored)];
}
const x = f => L + (W - L - R) * (f - LO) / (HI - LO);
function scale(values, top, height) {
  let lo = Math.min(...values), hi = Math.max(...values);
  if (hi - lo < 1) { lo -= 0.5; hi += 0.5; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  return {lo, hi, y: v => top + height * (hi - v) / (hi - lo)};
}
function ticks(lo, hi) {
  const span = hi - lo, step = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20].find(s => span / s <= 6) || 50;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(+v.toFixed(2));
  return out;
}
function path(values, sy) {
  return values.map((v, i) => (i ? 'L' : 'M') + x(F[i]).toFixed(1) + ' ' + sy.y(v).toFixed(1)).join('');
}
let current = null;
function draw(row) {
  const [intended, predicted] = curves(+row.dataset.c);
  const diff = predicted.map((v, i) => v - intended[i]);
  const top = scale(intended.concat(predicted), T, TOPH);
  const bot = scale(diff.concat([0]), T + TOPH + GAP, BOTH);
  const parts = [];
  for (const f of [1, 20, 40, 60, 80, 100, 120, 140, 160]) {
    parts.push(`<line x1="${x(f)}" x2="${x(f)}" y1="${T}" y2="${T + TOPH + GAP + BOTH}" stroke="__GRID__"/>`);
    parts.push(`<text x="${x(f)}" y="${T + TOPH + GAP + BOTH + 16}" text-anchor="middle">${f}</text>`);
  }
  for (const s of [top, bot]) {
    for (const v of ticks(s.lo, s.hi)) {
      parts.push(`<line x1="${L}" x2="${W - R}" y1="${s.y(v)}" y2="${s.y(v)}" stroke="__GRID__"/>`);
      parts.push(`<text x="${L - 6}" y="${s.y(v) + 4}" text-anchor="end">${v}</text>`);
    }
  }
  parts.push(`<path d="${path(intended, top)}" fill="none" stroke="__INTENDED__" stroke-width="2" stroke-dasharray="6 4"/>`);
  parts.push(`<path d="${path(predicted, top)}" fill="none" stroke="__PREDICTED__" stroke-width="2"/>`);
  parts.push(`<path d="${path(diff, bot)}" fill="none" stroke="__PREDICTED__" stroke-width="2"/>`);
  parts.push(`<line x1="${L}" x2="${W - R}" y1="${bot.y(0)}" y2="${bot.y(0)}" stroke="__INK__" stroke-width="0.5"/>`);
  parts.push(`<text x="${W - R}" y="${T + 12}" text-anchor="end"><tspan fill="__INTENDED__">- - designed</tspan>  <tspan fill="__PREDICTED__">— float32 (miniDSP)</tspan></text>`);
  parts.push(`<text x="${L + 4}" y="${T + TOPH + GAP - 6}">float32 − designed (dB)</text>`);
  parts.push(`<text x="${W - R}" y="${T + TOPH + GAP + BOTH + 16}" text-anchor="end" dy="14">Hz</text>`);
  parts.push(`<line id="cross" y1="${T}" y2="${T + TOPH + GAP + BOTH}" stroke="__INK__" stroke-width="0.5" visibility="hidden"/>`);
  parts.push(`<rect x="${L}" y="${T}" width="${W - L - R}" height="${TOPH + GAP + BOTH}" fill="transparent" id="hit"/>`);
  svg.innerHTML = parts.join('');
  const cells = row.querySelectorAll('td');
  document.getElementById('title').textContent =
    `${cells[0].textContent}${cells[1].textContent ? ' (' + cells[1].textContent + ')' : ''} — ${cells[4].textContent} sections, worst ${cells[5].textContent} dB at ${cells[6].textContent} Hz`;
  if (current) current.classList.remove('sel');
  current = row; row.classList.add('sel');
  const hit = document.getElementById('hit'), cross = document.getElementById('cross');
  hit.onmousemove = ev => {
    const box = svg.getBoundingClientRect(), px = (ev.clientX - box.left) * W / box.width;
    const t = Math.max(0, Math.min(1, (px - L) / (W - L - R)));
    const i = Math.round(t * (N - 1));
    cross.setAttribute('x1', x(F[i])); cross.setAttribute('x2', x(F[i])); cross.setAttribute('visibility', 'visible');
    tip.style.display = 'block';
    tip.style.left = (ev.pageX + 12) + 'px'; tip.style.top = (ev.pageY + 12) + 'px';
    tip.innerHTML = `${F[i].toFixed(1)} Hz<br>designed ${intended[i].toFixed(2)} dB<br>float32 ${predicted[i].toFixed(2)} dB<br>difference ${diff[i] >= 0 ? '+' : ''}${diff[i].toFixed(2)} dB`;
  };
  hit.onmouseleave = () => { tip.style.display = 'none'; cross.setAttribute('visibility', 'hidden'); };
}
const rows = Array.from(document.querySelectorAll('tbody tr'));
const q = document.getElementById('q'), only = document.getElementById('only');
function filter() {
  const text = q.value.toLowerCase();
  let first = null;
  for (const r of rows) {
    r.hidden = (only.checked && !r.classList.contains('hi')) || !r.textContent.toLowerCase().includes(text);
    if (!r.hidden && !first) first = r;
  }
  if (text && first) draw(first);
}
q.oninput = filter; only.onchange = filter;
document.querySelector('tbody').onclick = ev => {
  if (ev.target.closest('a')) return;
  const row = ev.target.closest('tr');
  if (row) draw(row);
};
filter();
if (rows.length) draw(rows[0]);
})();
"""
