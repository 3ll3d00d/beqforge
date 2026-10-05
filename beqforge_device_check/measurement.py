"""Exact float32 stimuli and offline recovery; importing this module opens no audio."""

import hashlib
from dataclasses import asdict, dataclass, replace

import numpy as np
from scipy.fft import next_fast_len
from scipy.signal import welch

from beqforge_device_check.profiles import finite


class CaptureInterrupted(RuntimeError):
    """Aborted stream carrying its bounded partial evidence to the transaction writer."""

    def __init__(self, message: str, samples: np.ndarray, metadata: dict):
        super().__init__(message)
        self.samples = samples
        self.metadata = metadata


@dataclass(frozen=True, slots=True)
class SweepSettings:
    rate: int = 96000
    low_hz: float = 2
    high_hz: float = 200
    duration_s: float = 5
    # Must exceed the transport delay; the silence before the sweep is the noise estimate.
    preroll_s: float = 0.5
    # The minimum tail. Each cascade's tail is extended to its own settling time
    # (decay to -120 dB) times `settling_multiple`; see `for_settling`.
    tail_s: float = 1
    level_dbfs: float = -30
    fade_s: float = 0.05
    maximum_bytes: int = 512 * 1024**2
    settling_multiple: float = 1

    def __post_init__(self) -> None:
        for name in (
            "low_hz",
            "high_hz",
            "duration_s",
            "preroll_s",
            "tail_s",
            "level_dbfs",
            "fade_s",
            "settling_multiple",
        ):
            finite(getattr(self, name), name)
        if not 0 < self.low_hz < self.high_hz < self.rate / 2:
            raise ValueError("invalid sweep frequency range")
        if (
            min(
                self.duration_s,
                self.preroll_s,
                self.tail_s,
                self.fade_s,
                self.settling_multiple,
            )
            <= 0
        ):
            raise ValueError(
                "sweep, pre-roll, tail, fades and settling multiple must be positive"
            )
        if self.fade_s * 2 >= self.duration_s or self.level_dbfs > -3:
            raise ValueError("fade exceeds sweep duration or sweep level is too high")
        if self.sample_count * 4 > self.maximum_bytes:
            raise ValueError("stimulus exceeds configured buffer bound")

    def for_settling(self, settling_s: float) -> "SweepSettings":
        """The settings one cascade is swept with: its tail covers its own decay."""
        tail = max(self.tail_s, settling_s * self.settling_multiple)
        return self if tail == self.tail_s else replace(self, tail_s=tail)

    @property
    def sample_count(self) -> int:
        return sum(
            round(s * self.rate) for s in (self.preroll_s, self.duration_s, self.tail_s)
        )


def waveform_hash(samples: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(samples, dtype="<f4").tobytes()).hexdigest()


def sweep(settings: SweepSettings) -> tuple[np.ndarray, dict]:
    import pyfar as pf

    count = round(settings.duration_s * settings.rate)
    fade = round(settings.fade_s * settings.rate)
    values = (
        pf.signals.exponential_sweep_time(
            count,
            [settings.low_hz, settings.high_hz],
            n_fade_out=fade,
            sampling_rate=settings.rate,
        )
        .time[0]
        .copy()
    )
    values[:fade] *= np.sin(np.linspace(0, np.pi / 2, fade)) ** 2
    values *= 10 ** (settings.level_dbfs / 20) / np.max(np.abs(values))
    start = round(settings.preroll_s * settings.rate)
    samples = np.zeros(settings.sample_count, dtype=np.float32)
    samples[start : start + count] = values
    return samples, {
        "settings": asdict(settings),
        "hash": waveform_hash(samples),
        "sweep_start": start,
        "sweep_stop": start + count,
        "peak": float(np.max(np.abs(samples))),
        "rms": float(np.sqrt(np.mean(samples.astype(float) ** 2))),
        "transport_format": "float32",
        "dither": "none emitted by harness",
    }


def carried(
    source: np.ndarray, frequencies: np.ndarray, mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Map per-bin evidence onto a finer grid without inventing any.

    Returns (lower, upper, exact, valid): a target bin between two source bins is valid
    only if both are, and per-bin budgets take the worse neighbour (see `worst`).
    """
    source = np.asarray(source, dtype=float)
    mask = np.asarray(mask, dtype=bool)
    upper = np.minimum(np.searchsorted(source, frequencies), len(source) - 1)
    lower = np.maximum(upper - 1, 0)
    exact = source[upper] == frequencies
    valid = (frequencies >= source[0]) & (frequencies <= source[-1])
    valid &= np.where(exact, mask[upper], mask[lower] & mask[upper])
    return lower, upper, exact, valid


def worst(values, lower, upper, exact, *, larger: bool = True) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    pick = np.maximum if larger else np.minimum
    return np.where(exact, values[upper], pick(values[lower], values[upper]))


def capture_quality(
    samples: np.ndarray, expected_count: int, *, statuses: list[str] | None = None
) -> list[str]:
    values = np.asarray(samples)
    failures = []
    if values.ndim != 1 or len(values) != expected_count:
        failures.append("missing/truncated samples")
    if np.any(~np.isfinite(values)):
        failures.append("non-finite capture")
    if values.size and np.max(np.abs(values)) >= 0.999:
        failures.append("capture clipping")
    if values.size == 0 or not np.any(values):
        failures.append("silent capture")
    if statuses:
        failures.extend(f"stream status: {status}" for status in statuses)
    return failures


def reference_delay(
    stimulus: np.ndarray, reference: np.ndarray, metadata: dict
) -> tuple[int, float]:
    """Transport delay and relative clock drift from a reference that bypasses the DUT.

    The whole sweep is deconvolved, so the delay comes from a 2-200 Hz impulse response
    rather than a short narrowband segment (whose correlation ripples are near-equal and
    pick the wrong cycle). Drift is then read from phase: a log sweep plays frequency f
    at time t(f), so a clock mismatch eps makes group delay tau0 + eps * t(f). Only use a
    reference that bypasses the filter under test; never silently resample a capture.
    """
    if len(stimulus) != len(reference):
        raise ValueError("reference and stimulus lengths differ")
    settings = SweepSettings(**metadata["settings"])
    rate, start, stop = settings.rate, metadata["sweep_start"], metadata["sweep_stop"]
    if stop - start < rate:
        raise ValueError("insufficient timing-reference content")
    size = next_fast_len(2 * len(stimulus))
    frequencies = np.fft.rfftfreq(size, 1 / rate)
    # Keep clear of the faded sweep ends, where the excitation is weakest.
    band = (frequencies >= settings.low_hz * 1.2) & (
        frequencies <= settings.high_hz / 1.2
    )
    transfer = np.zeros(len(frequencies), dtype=complex)
    transfer[band] = (
        np.fft.rfft(reference.astype(float), size)[band]
        / np.fft.rfft(stimulus.astype(float), size)[band]
    )
    impulse = np.fft.irfft(transfer, size)[: len(stimulus)]
    coarse = int(np.argmax(np.abs(impulse)))
    f = frequencies[band]
    phase = np.unwrap(np.angle(transfer[band] * np.exp(2j * np.pi * f * coarse / rate)))
    played = start / rate + (stop - start) / rate * np.log(
        f / settings.low_hz
    ) / np.log(settings.high_hz / settings.low_hz)
    # phase(f) = a - 2 pi tau0 f - 2 pi eps * integral of t(f) df
    integral = np.concatenate(
        [[0.0], np.cumsum(0.5 * (played[1:] + played[:-1]) * np.diff(f))]
    )
    basis = np.column_stack([np.ones_like(f), -2 * np.pi * f, -2 * np.pi * integral])
    (_, tau0, eps), *_ = np.linalg.lstsq(basis, phase, rcond=None)
    # Align at the start of the sweep, where the delay applies to the captured samples.
    delay = coarse + (tau0 + eps * start / rate) * rate
    return round(delay), float(eps * 1e6)


def recover(
    stimulus: np.ndarray,
    captured: np.ndarray,
    metadata: dict,
    *,
    delay_samples: int = 0,
    reference: np.ndarray | None = None,
    maximum_drift_ppm: float = 5,
    statuses: list[str] | None = None,
    minimum_snr_db: float = 40,
    maximum_bias_db: float = 0.01,
    size: int | None = None,
) -> dict:
    """Regularised inversion at native FFT frequencies; preserve all filter decay.

    Delay is supplied independently or obtained from a timing reference. Without one,
    phase includes unknown transport latency. No gain or trend is fitted away.
    """
    import pyfar as pf

    settings = SweepSettings(**metadata["settings"])
    if waveform_hash(stimulus) != metadata["hash"]:
        raise ValueError("emitted stimulus hash mismatch")
    failures = capture_quality(captured, len(stimulus), statuses=statuses)
    drift = None
    if reference is not None and np.max(np.abs(reference)) < 0.01 * metadata["peak"]:
        # A silent reference gives a meaningless delay/drift estimate, not a small one.
        failures.append(
            "timing reference channel carries no stimulus (40 dB below the sweep);"
            " check its routing and the reference playback channel"
        )
        reference = None
    if reference is not None:
        delay_samples, drift = reference_delay(stimulus, reference, metadata)
        if abs(drift) > maximum_drift_ppm:
            failures.append(
                f"clock drift {drift:.3f} ppm exceeds {maximum_drift_ppm:g} ppm"
            )
    if failures:
        return {"failures": failures, "drift_ppm": drift, "valid": False}
    if delay_samples < 0 or delay_samples >= metadata["sweep_start"]:
        return {
            "failures": ["transport delay exceeds preserved pre-roll"],
            "valid": False,
        }
    recorded = np.asarray(captured, dtype=float)
    aligned = np.pad(recorded[delay_samples:], (0, delay_samples))
    # A longer sweep's FFT length puts this on its finer native grid: exact, since both
    # signals are finite and zero-padding them cannot wrap.
    minimum = next_fast_len(2 * len(stimulus))
    if size is not None and size < minimum:
        raise ValueError("analysis length is shorter than this capture needs")
    size = size or minimum
    excitation = pf.Signal(
        np.pad(stimulus.astype(float), (0, size - len(stimulus))), settings.rate
    )
    # Explicit final regularisation makes its per-bin bias independently calculable.
    power = np.abs(excitation.freq_raw[0]) ** 2
    epsilon = np.full(power.shape, np.max(power) * 1e-12)
    regularisation = pf.Signal(
        np.sqrt(epsilon), settings.rate, n_samples=size, domain="freq"
    )
    inverse = pf.dsp.RegularizedSpectrumInversion.from_magnitude_spectrum(
        excitation,
        regularisation,
        beta=1,
    ).invert
    measured = np.fft.rfft(aligned, n=size) * inverse.freq_raw[0]
    frequencies = np.fft.rfftfreq(size, 1 / settings.rate)
    band = (frequencies >= settings.low_hz) & (frequencies <= settings.high_hz)
    bias = power / (power + epsilon)
    bias_db = -20 * np.log10(np.maximum(bias, 1e-300))
    noise = recorded[: metadata["sweep_start"] - delay_samples]
    nf, psd = welch(noise, fs=settings.rate, nperseg=min(len(noise), 8192))
    # Expected FFT noise energy: PSD * rate * number of recorded samples / 2.
    noise_amplitude = np.sqrt(
        np.interp(frequencies, nf, psd) * settings.rate * len(recorded) / 2
    )
    output_fft = np.abs(np.fft.rfft(aligned, n=size))
    snr_db = 20 * np.log10(
        np.maximum(output_fft, 1e-300) / np.maximum(noise_amplitude, 1e-150)
    )
    mask = (snr_db >= minimum_snr_db) & (bias_db <= maximum_bias_db)
    return {
        "valid": True,
        "failures": [],
        "frequencies": frequencies[band],
        "response": measured[band],
        "mask": mask[band],
        "snr_db": snr_db[band],
        "inversion_bias_db": bias_db[band],
        "impulse": np.fft.irfft(measured, n=size),
        "delay_samples": delay_samples,
        "drift_ppm": drift,
        "phase_limitation": None
        if reference is not None or delay_samples
        else "transport latency unverified",
        "processing": {
            "fft_size": size,
            "fft_normalisation": "unscaled forward, 1/N inverse",
            "regularisation_relative_power": 1e-12,
            "window": "full retained capture",
            "maximum_bias_db": maximum_bias_db,
            "minimum_snr_db": minimum_snr_db,
        },
    }
