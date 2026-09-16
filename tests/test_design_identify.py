"""Detection as a model comparison.

The question is not "does adding an attenuation term reduce the residual" — it always does,
`A` has three free parameters — but "does it buy more than letting the natural envelope curve
one degree further". A rolloff is not a polynomial; a natural envelope is close to one, and
the whole risk §2.3 names is a smooth envelope being reported as a filter.

Envelopes are constructed here rather than extracted, so every case has a known truth.
"""

import numpy as np
import pytest

from beqforge.extraction import Envelopes
from beqforge.identify import IdentifyParams, identify_rolloff
from beqforge.rolloff import DB_PER_OCTAVE_PER_ORDER, attenuation_db

FREQS = np.linspace(4.0, 470.0, 478)
OCTAVES = np.log2(FREQS / FREQS[0])


def envelopes(mean_db: np.ndarray) -> Envelopes:
    return Envelopes(
        freqs=FREQS,
        mean_db=mean_db,
        peak_db=mean_db + 20.0,
        quiet_db=mean_db - 20.0,
        coherence=np.full_like(FREQS, 0.8),
        reference_band_hz=(60.0, 120.0),
        loud_frames=100,
        quiet_frames=100,
        total_frames=1000,
        margin_se_db=np.full_like(FREQS, np.inf),
    )


def natural(curvature: float = -0.9) -> np.ndarray:
    """A smooth envelope with no rolloff in it at all."""
    return 3.0 * OCTAVES + curvature * OCTAVES**2


def with_rolloff(corner_hz: float, order: int, curvature: float = -0.9) -> np.ndarray:
    return natural(curvature) + attenuation_db(
        FREQS, corner_hz, order * DB_PER_OCTAVE_PER_ORDER, 2.0 * order
    )


@pytest.mark.parametrize("curvature", [-0.3, -0.6, -0.9, -1.2])
def test_a_curved_envelope_is_not_a_rolloff(curvature: float) -> None:
    """The expensive failure of §2.3: inventing a rolloff in content that has none."""
    found = identify_rolloff(envelopes(natural(curvature)))
    assert not found.detected, (
        f"claimed a rolloff on a smooth envelope: {found.improvement_db:+.3f} dB"
    )


def test_a_cubic_envelope_is_not_a_rolloff() -> None:
    """The case that slipped through `improvement_db > 0.0` at 0.031 dB."""
    cubic = 2.0 * OCTAVES - 0.5 * OCTAVES**2 + 0.05 * OCTAVES**3
    assert not identify_rolloff(envelopes(cubic)).detected


@pytest.mark.parametrize(("corner_hz", "order"), [(25.0, 4), (35.0, 4), (18.0, 8)])
def test_a_real_rolloff_is_detected(corner_hz: float, order: int) -> None:
    found = identify_rolloff(envelopes(with_rolloff(corner_hz, order)))
    assert found.detected
    assert found.fit.corner_hz == pytest.approx(corner_hz, rel=0.15)


def test_the_null_is_deliberately_more_flexible_than_the_alternative() -> None:
    """Nested, the comparison stops discriminating.

    A quadratic envelope with no rolloff fits a linear-plus-attenuation model 0.7 dB better
    than a linear one — the attenuation term is simply serving as curvature. Against an
    envelope one degree higher the same case scores zero, and the separation from a real
    rolloff goes from 3x to 7x.
    """
    smooth = envelopes(natural(-0.9))
    nested = IdentifyParams(null_envelope_margin=0, min_improvement_db=0.0)
    deliberate = IdentifyParams()

    assert identify_rolloff(smooth, nested).improvement_db > 0.5
    assert identify_rolloff(smooth, deliberate).improvement_db < 0.05


def test_the_margin_is_reported_alongside_the_verdict() -> None:
    """§3.6 asks for a margin, not a pass mark, so both have to be legible."""
    found = identify_rolloff(envelopes(with_rolloff(25.0, 4)))
    assert f"{found.min_improvement_db:.2f}" in str(found)
    assert "model improvement" in str(found)


def test_the_verdict_survives_realistic_bin_scatter() -> None:
    """Every case above is a noiseless analytic curve; a real `mean_db` is not one.

    1.5 dB of per-bin scatter is a plausible real-material estimate (comparable to the
    residual smoothing steps elsewhere in `design/` are built to tolerate). Neither verdict
    should flip on it, and the fitted corner should stay close to the true one.
    """
    rng = np.random.default_rng(42)
    noise = rng.normal(0.0, 1.5, size=FREQS.shape)

    natural_found = identify_rolloff(envelopes(natural(-0.9) + noise))
    assert not natural_found.detected, (
        f"claimed a rolloff on noisy smooth content: {natural_found.improvement_db:+.3f} dB"
    )

    rolloff_found = identify_rolloff(envelopes(with_rolloff(25.0, 4) + noise))
    assert rolloff_found.detected
    assert rolloff_found.fit.corner_hz == pytest.approx(25.0, rel=0.2)
