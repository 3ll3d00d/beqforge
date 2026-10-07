# Published BEQ coefficient optimisation

This report compares the authored RBJ response with the response predicted after float32 coefficient loading. It uses only the published filters; it does not measure film audio or validate hardware.

The complete pinned [BEQCatalogue](https://github.com/3ll3d00d/beqcatalogue) snapshot contains **15,476 entries** and **10,586 distinct title identities**. **13,107 entries (9,175 title identities) gained published coefficients (a replacement within the margin or an improvement on the original) at one or both rates.** Each entry is evaluated separately at 48 and 96 kHz, so replacements across rates must not be counted as unique titles.

A title identity is title + year + content type + season + episode. Editions, languages, audio formats and authors can have separate catalogue entries. All statistics weight each catalogue entry once per rate.

| Rate | Already within 0.5 dB | Published replacements | Published improvements | No replacement | Unresolved | Unsupported |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 48 kHz | 10,702 | 4,616 | 106 | 0 | 0 | 52 |
| 96 kHz | 2,525 | 10,641 | 2,258 | 0 | 0 | 52 |

## Whole-catalogue error by frequency

“After” uses an optimised cascade when it meets the 0.5 dB maximum-error margin across 2–200 Hz (a replacement), or when it misses the margin but is strictly better than the original across 2–200 Hz (an improvement). Only 2–200 Hz is assessed. Both must be stable, converge numerically and survive publication. Otherwise it retains the original.

The charts show pointwise absolute-error median, 95th and 99th percentiles, and maximum. The table reports those statistics of each entry’s maximum sampled error within each frequency band. These are different summaries: a pointwise percentile need not follow one particular entry. Chart axes use a logarithmic frequency scale and a symmetric logarithmic error scale to retain the tails.

### 48 kHz

![Whole-catalogue errors at 48 kHz](assets/aggregate-48000.png)

Curves include 15,422 finite, stable original cascades; 2 unstable/nonfinite originals and 52 unsupported entries are excluded from numerical percentiles and retained in the outcome counts above.

| Band (Hz) | Median before → after (dB) | 95th percentile before → after (dB) | Maximum before → after (dB) |
| --- | ---: | ---: | ---: |
| 2–5 | 0.253 → 0.117 | 1.172 → 0.430 | 4.060 → 1.251 |
| 5–10 | 0.262 → 0.134 | 1.049 → 0.408 | 5.451 → 1.356 |
| 10–20 | 0.197 → 0.122 | 0.644 → 0.372 | 5.665 → 1.534 |
| 20–40 | 0.098 → 0.066 | 0.332 → 0.218 | 1.031 → 0.942 |
| 40–80 | 0.033 → 0.020 | 0.117 → 0.074 | 0.421 → 0.281 |
| 80–200 | 0.010 → 0.006 | 0.034 → 0.023 | 0.109 → 0.057 |

### 96 kHz

![Whole-catalogue errors at 96 kHz](assets/aggregate-96000.png)

Curves include 15,421 finite, stable original cascades; 3 unstable/nonfinite originals and 52 unsupported entries are excluded from numerical percentiles and retained in the outcome counts above.

| Band (Hz) | Median before → after (dB) | 95th percentile before → after (dB) | Maximum before → after (dB) |
| --- | ---: | ---: | ---: |
| 2–5 | 1.057 → 0.174 | 4.650 → 0.721 | 16.632 → 4.735 |
| 5–10 | 1.074 → 0.202 | 4.178 → 0.774 | 13.281 → 5.719 |
| 10–20 | 0.794 → 0.223 | 2.569 → 0.856 | 8.521 → 5.709 |
| 20–40 | 0.397 → 0.161 | 1.325 → 0.598 | 4.106 → 3.538 |
| 40–80 | 0.138 → 0.043 | 0.468 → 0.204 | 1.179 → 1.121 |
| 80–200 | 0.040 → 0.011 | 0.134 → 0.048 | 0.365 → 0.260 |

## Two badly performing entries

These are the two distinct title identities with the largest original maximum error among entries that received a publishable replacement at either rate. They illustrate successful repairs; the whole-catalogue results above also include every unsuccessful search.

### Mojin: The Worm Valley (2018)

[Catalogue entry](https://beqcatalogue.readthedocs.io/en/latest/mobe1969/mojin-the-worm-valley/#dts-hd-ma-51) · filter author: mobe1969

![Original and optimised responses](assets/example-1.png)

| Rate | Original maximum error | Published maximum error | Outcome |
| --- | ---: | ---: | --- |
| 48 kHz | 1.605 dB | 0.348 dB | replacement |
| 96 kHz | 16.632 dB | 1.263 dB | improvement |

### Death Note (2006)

[Catalogue entry](https://beqcatalogue.readthedocs.io/en/latest/mobe1969/death-note/#dts-hd-ma-51) · filter author: mobe1969

![Original and optimised responses](assets/example-2.png)

| Rate | Original maximum error | Published maximum error | Outcome |
| --- | ---: | ---: | --- |
| 48 kHz | 0.271 dB | 0.271 dB | within_margin |
| 96 kHz | 14.773 dB | 0.534 dB | improvement |

## Reproducing this report

Snapshot SHA-256: `ed4454b612ef3e30aa734962119015a50c4addf7cb8bc5192fbbfe8869428dda`. Optimiser/report source digest: `36e3eb32ef10a56e1468969022e1dd29b7b7a5b43d8661979abc4616c98469a7`. Settings and dependency versions are recorded in [statistics.json](statistics.json); all entry/rate outcomes are in [entry-results.json.gz](entry-results.json.gz). Source catalogue filters remain attributed to their original authors.

```bash
uv sync --extra optimiser --extra designer
uv run python -m tools.optimiser_catalogue_report /path/to/beqcatalogue/docs/database.json \
  --cache-dir /tmp/beq-catalogue-report-cache --out docs/optimiser-report --workers 12
```

The cache deduplicates identical filter/load requests and resumes interrupted work. The entire catalogue is still counted. The static PNGs and summaries are checked into this repository; viewing them needs no running service.

The ideal is the authored double-precision RBJ magnitude response. Baselines use complete published coefficients at the selected rate when present, otherwise regenerated RBJ coefficients, then float32 transport/storage. Both rates are simulated independently. Optimisation uses the default six passes and 512-point search grid; eligibility uses independently refined 8,192/16,384-point grids with 0.000001 dB convergence tolerance. Aggregates and charts use 1,024 logarithmically spaced frequencies from 2 to 200 Hz, so band tables are sampled estimates rather than the refined eligibility maxima.

This predicts coefficient-rounding error, not the device’s internal multiply/accumulate error. It preserves the authored target, section count and volume offset. A replacement meeting the margin does not establish that the authored BEQ itself is appropriate for the film.

[Library and CLI usage](../optimiser.md)
