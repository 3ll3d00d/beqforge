"""Generate a resumable whole-catalogue coefficient report and static README charts.

Run with the optimiser and designer extras (SciPy and Matplotlib). No audio is used.
"""

import argparse
import hashlib
import json
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import numpy as np

from beqoptimiser import (
    Float32,
    ResultCache,
    Section,
    Settings,
    core,
    magnitude,
    stable,
)
from beqoptimiser.cache import implementation_identity
from beqoptimiser.cli import optimise_entry

RATES = (48000, 96000)
FREQUENCIES = np.geomspace(2, 200, 1024)
BANDS = ((2, 5), (5, 10), (10, 20), (20, 40), (40, 80), (80, 200))


def cascades(entry, rate):
    """Reconstruct the reference and the exact baseline loading policy of the CLI."""
    filters = entry["filters"]
    if isinstance(filters, str):
        filters = json.loads(filters)
    reference, sent = [], []
    for section in filters:
        count = section.get("count", 1)
        row = Section(
            section["type"], section["freq"], section["q"], section["gain"]
        ).sos(rate)
        reference.extend([row] * count)
        cached = section.get("biquads", {}).get(str(rate))
        sent.extend(
            (
                [float(v) for v in cached["b"]]
                + [1.0]
                + [-float(v) for v in cached["a"]]
                if cached
                else row
            )
            for _ in range(count)
        )
    return np.asarray(reference), Float32().quantise(np.asarray(sent))


def replacement_cascade(report, baseline):
    if report["variant"] is None:
        return baseline
    return np.asarray(
        [
            [*map(float, row["b"]), 1.0, *(-float(v) for v in row["a"])]
            for row in report["variant"]["biquads"]
        ]
    )


def clean(value):
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(item) for item in value]
    return value


def cached_search_magnitude(rate, fallback):
    """Cache unchanged section responses, preserving the core's arithmetic order.

    Only the fixed search grid is accelerated. Independent eligibility validation
    remains on the library implementation. Each process owns its bounded cache.
    """
    frequencies = np.geomspace(*Settings().band_hz, Settings().grid_points)
    z = np.exp(
        -2j * np.longdouble(np.pi) * np.asarray(frequencies, dtype=np.longdouble) / rate
    )
    responses = {}

    def response(sos, requested, requested_rate):
        if requested_rate != rate or not np.array_equal(requested, frequencies):
            return fallback(sos, requested, requested_rate)
        total = np.zeros(z.shape, dtype=np.longdouble)
        for row in np.asarray(sos, dtype=np.longdouble):
            # Padding bytes in longdouble are not portable hash keys.
            key = tuple(float(value) for value in row)
            if key not in responses:
                b0, b1, b2, _, a1, a2 = row
                responses[key] = 20 * np.log10(
                    np.abs((b0 + z * (b1 + z * b2)) / (1 + z * (a1 + z * a2)))
                )
            total += responses[key]
        if len(responses) > 8192:
            responses.clear()
        return np.asarray(total, dtype=float)

    return response


def evaluate(job):
    key, entry, rate, cache = job
    original_magnitude = core.magnitude
    core.magnitude = cached_search_magnitude(rate, original_magnitude)
    try:
        report = optimise_entry(entry, rate=rate, cache=ResultCache(cache))
    except (ValueError, KeyError, TypeError, OverflowError) as error:
        report = {
            "result": {"outcome": "unsupported"},
            "variant": None,
            "reason": str(error),
        }
    finally:
        core.magnitude = original_magnitude
    report = clean(report)
    return key, report


def job_key(entry, rate, code_digest):
    # Metadata and volume do not alter a transfer function; retain validation fields.
    relevant = {
        key: entry[key]
        for key in (
            "filters",
            "mv",
            "channel_cascades",
            "channelFilters",
            "channel_scope",
        )
        if key in entry
    }
    return hashlib.sha256(
        json.dumps(
            [relevant, rate, asdict(Settings()), code_digest], sort_keys=True
        ).encode()
    ).hexdigest()


def title_key(entry):
    return (
        entry.get("title"),
        str(entry.get("year", "")),
        entry.get("content_type", ""),
        str(entry.get("season", "")),
        str(entry.get("episode", "")),
    )


def statistics(before, after):
    return {
        name: {
            "before": np.percentile(before, percentile, axis=0).tolist(),
            "after": np.percentile(after, percentile, axis=0).tolist(),
        }
        for name, percentile in (
            ("median", 50),
            ("p95", 95),
            ("p99", 99),
            ("maximum", 100),
        )
    }


def render(entries, results, output, provenance):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output.mkdir(parents=True, exist_ok=True)
    assets = output / "assets"
    assets.mkdir(exist_ok=True)
    plt.rcParams.update(
        {
            "figure.dpi": 130,
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "savefig.facecolor": "white",
        }
    )
    summaries, rows, example_candidates = {}, [], []
    for rate in RATES:
        before, after, ordinals = [], [], []
        outcomes = Counter()
        improved_titles = set()
        nonfinite = 0
        for ordinal, entry in enumerate(entries):
            report = results[ordinal, rate]
            result = report["result"]
            outcome = result["outcome"]
            outcomes[outcome] += 1
            original = result.get("original_error_db")
            replacement = report["variant"] is not None
            final = result.get("candidate_error_db") if replacement else original
            rows.append(
                {
                    "ordinal": ordinal,
                    "title": entry.get("title"),
                    "year": entry.get("year"),
                    "author": entry.get("author"),
                    "rate": rate,
                    "outcome": outcome,
                    "original_max_error_db": original,
                    "published_max_error_db": final,
                    "replacement": replacement,
                    "reason": report.get("reason"),
                }
            )
            if replacement:
                improved_titles.add(title_key(entry))
                if original is not None:
                    example_candidates.append((original, ordinal, rate))
            if outcome == "unsupported":
                continue
            reference, baseline = cascades(entry, rate)
            published = replacement_cascade(report, baseline)
            if original is None or not stable(baseline):
                nonfinite += 1
                continue
            ideal = magnitude(reference, FREQUENCIES, rate)
            b = np.abs(magnitude(baseline, FREQUENCIES, rate) - ideal)
            a = np.abs(magnitude(published, FREQUENCIES, rate) - ideal)
            if not np.all(np.isfinite(b)) or not np.all(np.isfinite(a)):
                nonfinite += 1
                continue
            before.append(b)
            after.append(a)
            ordinals.append(ordinal)
        before, after = np.asarray(before), np.asarray(after)
        pointwise = statistics(before, after)
        bands = []
        for low, high in BANDS:
            mask = (FREQUENCIES >= low) & (FREQUENCIES <= high)
            bands.append(
                {
                    "low_hz": low,
                    "high_hz": high,
                    **statistics(
                        np.max(before[:, mask], axis=1), np.max(after[:, mask], axis=1)
                    ),
                }
            )
        summaries[str(rate)] = {
            "outcomes": dict(outcomes),
            "replaced_entries": outcomes["replacement"],
            "improved_entries": outcomes["improvement"],
            "improved_distinct_titles": len(improved_titles),
            "finite_curve_entries": len(before),
            "nonfinite_or_unstable_entries": nonfinite,
            "pointwise_absolute_error_db": pointwise,
            "band_maximum_absolute_error_db": bands,
        }
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharex=True)
        for ax, names, title in (
            (axes[0], ("median", "p95", "p99"), "Typical and tail errors"),
            (axes[1], ("maximum",), "Worst error at each frequency"),
        ):
            for name in names:
                for stage, colour, style in (
                    ("before", "#c45c20", "--"),
                    ("after", "#087e8b", "-"),
                ):
                    ax.plot(
                        FREQUENCIES,
                        pointwise[name][stage],
                        color=colour,
                        linestyle=style,
                        alpha={"median": 0.5, "p95": 0.75, "p99": 1, "maximum": 1}[
                            name
                        ],
                        label=f"{stage.title()} {name}",
                    )
            ax.axhline(0.5, color="#555555", lw=1, linestyle=":", label="0.5 dB margin")
            ax.set(
                xscale="log",
                yscale="symlog",
                ylim=(0, None),
                xlabel="Frequency (Hz)",
                ylabel="Absolute response error (dB)",
                title=title,
            )
            ax.grid(alpha=0.2)
            ax.legend(fontsize=8)
        fig.suptitle(
            f"{rate // 1000} kHz · {len(before):,} finite catalogue entries · publishable replacements only"
        )
        fig.tight_layout()
        fig.savefig(assets / f"aggregate-{rate}.png")
        plt.close(fig)
    chosen, seen = [], set()
    for _, ordinal, _ in sorted(example_candidates, reverse=True):
        if title_key(entries[ordinal]) not in seen:
            chosen.append(ordinal)
            seen.add(title_key(entries[ordinal]))
        if len(chosen) == 2:
            break
    for index, ordinal in enumerate(chosen, 1):
        entry = entries[ordinal]
        fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True)
        for column, rate in enumerate(RATES):
            report = results[ordinal, rate]
            reference, baseline = cascades(entry, rate)
            published = replacement_cascade(report, baseline)
            ideal = magnitude(reference, FREQUENCIES, rate)
            unoptimised = magnitude(baseline, FREQUENCIES, rate)
            optimised = magnitude(published, FREQUENCIES, rate)
            for curve, label, colour, style in (
                (ideal, "Authored ideal", "#555555", ":"),
                (unoptimised, "Original float32", "#c45c20", "--"),
                (optimised, "Published after optimisation", "#087e8b", "-"),
            ):
                axes[0, column].plot(
                    FREQUENCIES, curve, color=colour, linestyle=style, label=label
                )
            axes[0, column].set(
                title=f"{rate // 1000} kHz · {report['result']['outcome']}",
                ylabel="Filter gain (dB)",
            )
            axes[0, column].legend(fontsize=8)
            axes[1, column].plot(
                FREQUENCIES,
                unoptimised - ideal,
                color="#c45c20",
                linestyle="--",
                label="Original error",
            )
            axes[1, column].plot(
                FREQUENCIES, optimised - ideal, color="#087e8b", label="Published error"
            )
            axes[1, column].axhspan(
                -0.5, 0.5, color="#087e8b", alpha=0.12, label="±0.5 dB margin"
            )
            axes[1, column].set(
                xlabel="Frequency (Hz)", ylabel="Signed response error (dB)"
            )
            axes[1, column].legend(fontsize=8)
            for ax in axes[:, column]:
                ax.set_xscale("log")
                ax.grid(alpha=0.2)
        fig.suptitle(
            f"{entry['title']} ({entry.get('year', '')}) · {entry.get('author', '')} · {', '.join(entry.get('audioTypes', []))}"
        )
        fig.tight_layout()
        fig.savefig(assets / f"example-{index}.png")
        plt.close(fig)
    improved_entries = {row["ordinal"] for row in rows if row["replacement"]}
    improved_titles = {title_key(entries[ordinal]) for ordinal in improved_entries}
    document = {
        "provenance": provenance,
        "entry_count": len(entries),
        "distinct_title_count": len({title_key(e) for e in entries}),
        "improved_entries_either_rate": len(improved_entries),
        "improved_titles_either_rate": len(improved_titles),
        "frequencies_hz": FREQUENCIES.tolist(),
        "rates": summaries,
        "examples": chosen,
    }
    (output / "statistics.json").write_text(
        json.dumps(document, indent=2, allow_nan=False) + "\n"
    )
    import gzip

    with gzip.open(output / "entry-results.json.gz", "wt") as stream:
        json.dump(rows, stream, allow_nan=False)
    lines = [
        "# Published BEQ coefficient optimisation",
        "",
        "This report compares the authored RBJ response with the response predicted after float32 coefficient loading. It uses only the published filters; it does not measure film audio or validate hardware.",
        "",
        f"The complete pinned [BEQCatalogue](https://github.com/3ll3d00d/beqcatalogue) snapshot contains **{len(entries):,} entries** and **{document['distinct_title_count']:,} distinct title identities**. **{len(improved_entries):,} entries ({len(improved_titles):,} title identities) gained published coefficients (a replacement within the margin or an improvement on the original) at one or both rates.** Each entry is evaluated separately at 48 and 96 kHz, so replacements across rates must not be counted as unique titles.",
        "",
        "A title identity is title + year + content type + season + episode. Editions, languages, audio formats and authors can have separate catalogue entries. All statistics weight each catalogue entry once per rate.",
        "",
        "| Rate | Already within 0.5 dB | Published replacements | Published improvements | No replacement | Unresolved | Unsupported |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for rate in RATES:
        counts = summaries[str(rate)]["outcomes"]
        lines.append(
            f"| {rate // 1000} kHz | "
            + " | ".join(
                f"{counts.get(k, 0):,}"
                for k in (
                    "within_margin",
                    "replacement",
                    "improvement",
                    "no_replacement",
                    "unresolved",
                    "unsupported",
                )
            )
            + " |"
        )
    lines += [
        "",
        "## Whole-catalogue error by frequency",
        "",
        "“After” uses an optimised cascade when it passes the 0.5 dB maximum-error margin across 2–200 Hz and the 0.5 dB out-of-band guard (a replacement), or when it misses those but is strictly better than the original across 2–200 Hz and no worse than the original out of band (an improvement). Both must be stable, converge numerically and survive publication. Otherwise it retains the original.",
        "",
        "The charts show pointwise absolute-error median, 95th and 99th percentiles, and maximum. The table reports those statistics of each entry’s maximum sampled error within each frequency band. These are different summaries: a pointwise percentile need not follow one particular entry. Chart axes use a logarithmic frequency scale and a symmetric logarithmic error scale to retain the tails.",
        "",
    ]
    for rate in RATES:
        summary = summaries[str(rate)]
        lines += [
            f"### {rate // 1000} kHz",
            "",
            f"![Whole-catalogue errors at {rate // 1000} kHz](assets/aggregate-{rate}.png)",
            "",
            f"Curves include {summary['finite_curve_entries']:,} finite, stable original cascades; {summary['nonfinite_or_unstable_entries']:,} unstable/nonfinite originals and {summary['outcomes'].get('unsupported', 0):,} unsupported entries are excluded from numerical percentiles and retained in the outcome counts above.",
            "",
            "| Band (Hz) | Median before → after (dB) | 95th percentile before → after (dB) | Maximum before → after (dB) |",
            "| --- | ---: | ---: | ---: |",
        ]
        for band in summary["band_maximum_absolute_error_db"]:
            lines.append(
                f"| {band['low_hz']}–{band['high_hz']} | "
                + " | ".join(
                    f"{band[k]['before']:.3f} → {band[k]['after']:.3f}"
                    for k in ("median", "p95", "maximum")
                )
                + " |"
            )
        lines.append("")
    lines += [
        "## Two badly performing entries",
        "",
        "These are the two distinct title identities with the largest original maximum error among entries that received a publishable replacement at either rate. They illustrate successful repairs; the whole-catalogue results above also include every unsuccessful search.",
        "",
    ]
    for index, ordinal in enumerate(chosen, 1):
        entry = entries[ordinal]
        lines += [
            f"### {entry['title']} ({entry.get('year', '')})",
            "",
            f"[Catalogue entry]({entry.get('catalogue_url', '')}) · filter author: {entry.get('author', 'unknown')}",
            "",
            f"![Original and optimised responses](assets/example-{index}.png)",
            "",
            "| Rate | Original maximum error | Published maximum error | Outcome |",
            "| --- | ---: | ---: | --- |",
        ]
        for rate in RATES:
            row = next(
                row for row in rows if row["ordinal"] == ordinal and row["rate"] == rate
            )
            lines.append(
                f"| {rate // 1000} kHz | {row['original_max_error_db']:.3f} dB | {row['published_max_error_db']:.3f} dB | {row['outcome']} |"
            )
        lines.append("")
    lines += [
        "## Reproducing this report",
        "",
        f"Snapshot SHA-256: `{provenance['catalogue_sha256']}`. Optimiser/report source digest: `{provenance['code_sha256']}`. Settings and dependency versions are recorded in [statistics.json](statistics.json); all entry/rate outcomes are in [entry-results.json.gz](entry-results.json.gz). Source catalogue filters remain attributed to their original authors.",
        "",
        "```bash",
        "uv sync --extra optimiser --extra designer",
        "uv run python -m tools.optimiser_catalogue_report /path/to/beqcatalogue/docs/database.json \\",
        "  --cache-dir /tmp/beq-catalogue-report-cache --out docs/optimiser-report --workers 12",
        "```",
        "",
        "The cache deduplicates identical filter/load requests and resumes interrupted work. The entire catalogue is still counted. The static PNGs and summaries are checked into this repository; viewing them needs no running service.",
        "",
        "The ideal is the authored double-precision RBJ magnitude response. Baselines use complete published coefficients at the selected rate when present, otherwise regenerated RBJ coefficients, then float32 transport/storage. Both rates are simulated independently. Optimisation uses the default six passes and 512-point search grid; eligibility uses independently refined 8,192/16,384-point grids with 0.000001 dB convergence tolerance. Aggregates and charts use 1,024 logarithmically spaced frequencies from 2 to 200 Hz, so band tables are sampled estimates rather than the refined eligibility maxima.",
        "",
        "This predicts coefficient-rounding error, not the device’s internal multiply/accumulate error. It preserves the authored target, section count and volume offset. A replacement meeting the margin does not establish that the authored BEQ itself is appropriate for the film.",
        "",
        "[Library and CLI usage](../optimiser.md)",
        "",
    ]
    (output / "README.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("docs/optimiser-report"))
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    raw = args.catalogue.read_bytes()
    entries = json.loads(raw)
    root = Path(__file__).resolve().parents[1]
    sources = sorted(
        [
            *root.joinpath("beqoptimiser").glob("*.py"),
            *root.joinpath("beq_common").glob("*.py"),
            Path(__file__),
        ]
    )
    digest = hashlib.sha256(b"".join(path.read_bytes() for path in sources)).hexdigest()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    jobs, keys = {}, {}
    for ordinal, entry in enumerate(entries):
        for rate in RATES:
            key = job_key(
                entry, rate, json.dumps(implementation_identity(), sort_keys=True)
            )
            keys[ordinal, rate] = key
            jobs.setdefault(key, (key, entry, rate, str(args.cache_dir)))
    print(
        f"{len(entries):,} entries; {len(jobs):,} distinct filter/rate jobs; {args.workers} workers",
        flush=True,
    )
    reports = {}
    start = time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(evaluate, job) for job in jobs.values()]
        for completed, future in enumerate(as_completed(futures), 1):
            key, report = future.result()
            reports[key] = report
            if completed % 100 == 0 or completed == len(jobs):
                print(
                    f"{completed:,}/{len(jobs):,} completed in {time.monotonic() - start:.0f}s",
                    flush=True,
                )
    import matplotlib
    import scipy

    provenance = {
        "catalogue_sha256": hashlib.sha256(raw).hexdigest(),
        "code_sha256": digest,
        "settings": asdict(Settings()),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "matplotlib": matplotlib.__version__,
        "unique_filter_rate_jobs": len(jobs),
    }
    render(
        entries,
        {index: reports[key] for index, key in keys.items()},
        args.out,
        provenance,
    )
    print("ALLDONE: whole-catalogue report written", flush=True)


if __name__ == "__main__":
    main()
