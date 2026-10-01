"""Exact float32 stimuli and offline recovery; importing this module opens no audio."""

import hashlib
from dataclasses import asdict, dataclass

import numpy as np
from scipy.fft import next_fast_len
from scipy.signal import correlate, welch

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
    duration_s: float = 30
    preroll_s: float = 2
    tail_s: float = 15
    level_dbfs: float = -30
    fade_s: float = 0.05
    maximum_bytes: int = 512 * 1024**2

    def __post_init__(self) -> None:
        for name in (
            "low_hz",
            "high_hz",
            "duration_s",
            "preroll_s",
            "tail_s",
            "level_dbfs",
            "fade_s",
        ):
            finite(getattr(self, name), name)
        if not 0 < self.low_hz < self.high_hz < self.rate / 2:
            raise ValueError("invalid sweep frequency range")
        if min(self.duration_s, self.preroll_s, self.tail_s, self.fade_s) <= 0:
            raise ValueError("sweep, pre-roll, tail and fades must be positive")
        if self.fade_s * 2 >= self.duration_s or self.level_dbfs > -3:
            raise ValueError("fade exceeds sweep duration or sweep level is too high")
        if self.sample_count * 4 > self.maximum_bytes:
            raise ValueError("stimulus exceeds configured buffer bound")

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
    stimulus: np.ndarray, reference: np.ndarray, rate: int
) -> tuple[int, float]:
    """Two independently captured reference segments expose relative clock mismatch.

    Only use a reference that shares timing but bypasses the filter under test. Correlating
    DUT audio would confuse its phase with delay. Never silently resample either capture.
    """
    if len(stimulus) != len(reference):
        raise ValueError("reference and stimulus lengths differ")
    active = np.flatnonzero(stimulus)
    if len(active) < rate:
        raise ValueError("insufficient timing-reference content")
    width = min(rate * 2, (active[-1] - active[0]) // 3)
    starts = [int(active[0]), int(active[-1]) - width]
    delays = []
    margin = rate // 2
    for start in starts:
        lo, hi = max(0, start - margin), min(len(reference), start + width + margin)
        segment = stimulus[start : start + width]
        observed = reference[lo:hi].astype(float)
        correlation = correlate(observed, segment, mode="valid", method="fft")
        energy = correlate(observed**2, np.ones(width), mode="valid", method="fft")
        normalised = correlation / np.sqrt(np.maximum(energy, 1e-100))
        delays.append(int(np.argmax(normalised) + lo - start))
    ppm = (delays[1] - delays[0]) / (starts[1] - starts[0]) * 1e6
    return delays[0], float(ppm)


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
    if reference is not None:
        delay_samples, drift = reference_delay(stimulus, reference, settings.rate)
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
    size = next_fast_len(2 * len(stimulus))
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
