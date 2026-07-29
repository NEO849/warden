"""
warden/drift.py — measured statistical drift: PSI (binned) and KS (raw-sample) distribution-shift scores.

Turns Warden's confidence MAGNITUDE from prior-only into something partly MEASURED: when DataHub
holds a DatasetFieldProfileClass histogram for both an old and a new source, this module scores how
far the two distributions moved, and warden/agent.py folds that score in as a second, independent
Bayes evidence term ("drift_stat") ALONGSIDE the existing structural source-delta term.

Warden stays a SUPERSET, never a subset, of a pure PSI/KS monitor: the drift_stat term only fires
when a profile pair exists for both the old and new source (see check_model_inputs in warden/agent.py
for the profile gate). Where no profile exists, or where PSI/KS itself stays quiet because the new
distribution coincidentally looks like the old one under a semantically different column (the
run_ml_drift_demo.py hero case: signup_ts → ingest_ts, same shape, different meaning), the existing
STRUCTURAL source-delta term still fires on its own — a PSI/KS-only monitor would miss that case.

Pure stdlib. Industry-standard PSI bands (credit-risk scorecard monitoring / MLOps drift-monitoring
convention, e.g. used by Evidently AI, Fiddler, and classic credit-risk PSI literature):
    PSI < 0.10           -> no significant population shift ("stable")
    0.10 <= PSI <= 0.25   -> moderate shift, worth investigating
    PSI > 0.25            -> significant shift, distributions have materially diverged

Spec: scratchpad/confidence_model.md companion (drift term), Block 1 (measured drift -> Bayes term).
"""
from __future__ import annotations

import bisect
import math
import random

EPS = 1e-6                     # eps floor against log(0) / div-by-0 on empty/zero-mass bins
PSI_STABLE = 0.10              # below this: industry band says "no shift"
PSI_SIGNIFICANT = 0.25         # above this: industry band says "significant shift"
_MODERATE_QUALITY_CAP = 0.6    # quality reached exactly at PSI_SIGNIFICANT; keeps the piecewise fn continuous
_SATURATION_RATE = 0.15        # how fast quality approaches 1.0 above PSI_SIGNIFICANT


def psi(expected: list[float], actual: list[float]) -> float:
    """Population Stability Index between two histograms of the SAME binning.

    expected/actual are bin HEIGHTS (counts or frequencies) — the shape DataHub's
    DatasetFieldProfileClass.histogram already stores, not raw samples. Internally normalized to
    proportions, so raw counts and pre-normalized frequencies both work unchanged.
    """
    if len(expected) != len(actual):
        raise ValueError(
            f"histogram bin-count mismatch: expected has {len(expected)} bins, actual has {len(actual)}"
        )
    e_total = sum(expected) or EPS
    a_total = sum(actual) or EPS
    total = 0.0
    for e, a in zip(expected, actual):
        e_pct = max(e / e_total, EPS)   # eps floor: an empty bin must not send log() to -inf
        a_pct = max(a / a_total, EPS)
        total += (a_pct - e_pct) * math.log(a_pct / e_pct)
    return total


def _ecdf_count_le(sorted_vals: list[float], x: float) -> int:
    """Count of values <= x via binary search (bisect_right). stdlib-only."""
    return bisect.bisect_right(sorted_vals, x)


def ks_stat(a: list[float], b: list[float]) -> float:
    """Kolmogorov-Smirnov statistic: max distance between two empirical CDFs.

    Takes raw samples (not pre-binned), stdlib-only (bisect for the O(n log n) CDF evaluation).
    """
    if not a or not b:
        return 0.0
    a_sorted = sorted(a)
    b_sorted = sorted(b)
    na, nb = len(a_sorted), len(b_sorted)
    points = sorted(set(a_sorted) | set(b_sorted))
    max_d = 0.0
    for x in points:
        fa = _ecdf_count_le(a_sorted, x) / na
        fb = _ecdf_count_le(b_sorted, x) / nb
        d = abs(fa - fb)
        if d > max_d:
            max_d = d
    return max_d


def psi_to_quality(psi_value: float) -> float:
    """Calibrate a raw PSI value to a [0,1] Bayes evidence-quality scalar for Belief.update().

    Piecewise, continuous at both band edges (industry PSI bands, see module docstring):
        psi < 0.10           -> 0.0                                    (stable: no evidence weight)
        0.10 <= psi <= 0.25   -> linear ramp 0.0 -> 0.6                 (moderate: partial weight)
        psi > 0.25            -> 0.6 + 0.4*(1 - exp(-(psi-0.25)/0.15))  (significant: saturates -> 1.0)
    """
    if psi_value < PSI_STABLE:
        return 0.0
    if psi_value <= PSI_SIGNIFICANT:
        span = PSI_SIGNIFICANT - PSI_STABLE
        return (psi_value - PSI_STABLE) / span * _MODERATE_QUALITY_CAP
    return _MODERATE_QUALITY_CAP + (1.0 - _MODERATE_QUALITY_CAP) * (
        1.0 - math.exp(-(psi_value - PSI_SIGNIFICANT) / _SATURATION_RATE)
    )


def sample(seed: int, n: int, mean: float, stdev: float) -> list[float]:
    """Seedable synthetic sampler for the demo — a LOCAL random.Random(seed), never the process-global
    `random` module state, so repeated runs (and parallel scenarios) are fully reproducible."""
    rng = random.Random(seed)
    return [rng.gauss(mean, stdev) for _ in range(n)]


def histogram(values: list[float], boundaries: list[float]) -> list[float]:
    """Bin raw samples into len(boundaries)-1 buckets using half-open intervals [b[i], b[i+1]),
    with the final bucket closed on the right so the max boundary value is counted."""
    heights = [0.0] * (len(boundaries) - 1)
    last = len(boundaries) - 2
    for v in values:
        for i in range(len(boundaries) - 1):
            if boundaries[i] <= v < boundaries[i + 1] or (i == last and v == boundaries[-1]):
                heights[i] += 1.0
                break
    return heights


if __name__ == "__main__":
    # Worked example: (a) a stable distribution (two independent draws from the SAME population)
    # should score PSI < 0.10; (b) a genuinely drifted distribution (shifted mean + wider spread)
    # should score PSI > 0.25. Both compare histograms the way check_model_inputs will: binned
    # heights over a shared boundary set, exactly what DatasetFieldProfileClass.histogram stores.
    BOUNDARIES = [-4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0, 10.0]

    print("=== (a) stable: two independent samples of the SAME distribution ===")
    stable_expected = sample(seed=1, n=3000, mean=2.0, stdev=1.0)
    stable_actual = sample(seed=2, n=3000, mean=2.0, stdev=1.0)
    h_e = histogram(stable_expected, BOUNDARIES)
    h_a = histogram(stable_actual, BOUNDARIES)
    psi_stable = psi(h_e, h_a)
    ks_stable = ks_stat(stable_expected, stable_actual)
    print(f"   PSI={psi_stable:.4f}  KS={ks_stable:.4f}  quality={psi_to_quality(psi_stable):.4f}"
          f"  (expect PSI<{PSI_STABLE})")

    print("\n=== (b) drifted: mean shifted + wider spread ===")
    drift_expected = sample(seed=1, n=3000, mean=2.0, stdev=1.0)
    drift_actual = sample(seed=3, n=3000, mean=5.0, stdev=1.6)
    h_e2 = histogram(drift_expected, BOUNDARIES)
    h_a2 = histogram(drift_actual, BOUNDARIES)
    psi_drift = psi(h_e2, h_a2)
    ks_drift = ks_stat(drift_expected, drift_actual)
    print(f"   PSI={psi_drift:.4f}  KS={ks_drift:.4f}  quality={psi_to_quality(psi_drift):.4f}"
          f"  (expect PSI>{PSI_SIGNIFICANT})")

    ok = psi_stable < PSI_STABLE and psi_drift > PSI_SIGNIFICANT
    print("\ndrift.py WORKED EXAMPLE", "GREEN" if ok else "check thresholds/seeds")
