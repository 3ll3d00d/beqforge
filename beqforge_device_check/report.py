"""The human-readable page: per filter, intended vs predicted vs measured, and two verdicts.

Two questions are kept apart because they have different answers and different owners:

* Device: does the hardware play the coefficients it was sent as they predict? PASS,
  FAIL or UNRESOLVED against the accuracy requirement, including the bench uncertainty.
* Representation: can the device's coefficient format represent the filter at all?
  The predicted (e.g. float32) response against the intended one; computed, not measured.

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


def style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(True, which="both", color=GRID, linewidth=0.6)
    ax.tick_params(colors=MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_visible(False)


def filter_chart(row: dict, requirement: float, path: Path) -> None:
    import matplotlib.pyplot as plt

    load = row["loads"][0]
    f = np.asarray(load["frequencies"])
    curves = load["curves_db"]
    measured = np.array([np.nan if v is None else v for v in curves["measured"]])
    error = np.array([np.nan if v is None else v for v in load["delta_stored_db"]])
    fig, (top, bottom) = plt.subplots(
        2,
        1,
        figsize=(8, 5.2),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1.4]},
        facecolor=SURFACE,
    )
    top.semilogx(f, curves["intended"], color=INTENDED, lw=2, ls="--", label="Intended")
    top.semilogx(
        f, curves["predicted"], color=PREDICTED, lw=2, label="Predicted (coefficients)"
    )
    # FFT bins are linear in frequency: pick markers evenly on the log axis instead.
    valid = np.flatnonzero(np.isfinite(measured))
    picks = (
        np.unique(
            valid[
                np.searchsorted(
                    f[valid], np.geomspace(f[valid][0], f[valid][-1], 48)
                ).clip(0, len(valid) - 1)
            ]
        )
        if len(valid)
        else valid
    )
    top.semilogx(
        f[picks],
        measured[picks],
        color=MEASURED,
        ls="none",
        marker="o",
        ms=4,
        label="Measured",
    )
    top.set_ylabel("Response (dB)", color=MUTED, fontsize=9)
    top.set_title(
        f"{label(row)} at {row['level_dbfs']:.1f} dBFS",
        color=INK,
        fontsize=10,
        loc="left",
    )
    top.legend(frameon=False, fontsize=8, labelcolor=INK)
    bottom.semilogx(f, error, color=MEASURED, lw=1.5)
    bottom.axhspan(-requirement, requirement, color=GRID, alpha=0.6, lw=0)
    bottom.set_ylabel("Measured − predicted\n(dB)", color=MUTED, fontsize=8)
    bottom.set_xlabel("Frequency (Hz)", color=MUTED, fontsize=9)
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
        label="Coefficients vs intended (predicted)",
    )
    ax.plot(
        x, device, color=MEASURED, lw=2, marker="o", ms=6, label="Device vs predicted"
    )
    ax.axhline(requirement, color=MUTED, lw=1, ls=":", label=f"{requirement:g} dB")
    ax.set_yscale("log")
    if vary == "q":
        ax.set_xscale("log")
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
        "<th>Device (measured vs predicted)</th>"
        "<th>Coefficients (predicted vs intended)</th></tr>"
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
            f"<td>{device}</td><td>{coefficients}</td></tr>"
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


def catalogue_page(predictions: dict, threshold_db: float, output: Path) -> str:
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
    rows = "".join(
        "<tr><td>{title}</td><td>{edition}</td><td>{year}</td><td>{author}</td>"
        "<td>{sections}</td><td><b>{worst:.2f}</b></td><td>{hz:.1f}</td>"
        "<td>{above:.2f}</td></tr>".format(
            title=(
                f"<a href='{html.escape(e['url'])}'>{html.escape(e['title'])}</a>"
                if e.get("url")
                else html.escape(e["title"])
            ),
            edition=html.escape(e.get("edition") or ""),
            year=html.escape(str(e.get("year") or "")),
            author=html.escape(e.get("author") or ""),
            sections=e["sections"],
            worst=e["worst_db"],
            hz=e["worst_hz"],
            above=e["from_10_hz_db"],
        )
        for e in flagged
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
                "input{font:inherit;padding:4px 8px;width:100%;max-width:360px}</style>"
            ),
            "<h1>Catalogue coefficient error</h1>",
            (
                f"<p class='muted'>Predicted, not measured: each entry's published "
                f"coefficients rounded to {predictions['coefficient_format']} at "
                f"{predictions['rate']} Hz, against its intended filters. Snapshot "
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
            f"<h2>Entries above {threshold_db:g} dB</h2>",
            (
                "<p><input id='q' placeholder='Filter by title, author or year' "
                "oninput=\"for(const r of document.querySelectorAll('tbody tr'))"
                'r.hidden=!r.textContent.toLowerCase().includes(this.value.toLowerCase())">'
                " <a href='predictions.csv'>All entries (CSV)</a></p>"
            ),
            (
                "<table><thead><tr><th>Title</th><th>Edition</th><th>Year</th><th>Author</th>"
                "<th>Sections</th><th>Worst (dB)</th><th>At (Hz)</th><th>Worst from 10 Hz (dB)"
                f"</th></tr></thead><tbody>{rows}</tbody></table>"
            ),
        ]
    )
