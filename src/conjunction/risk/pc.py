"""
Phase 4 — probability of collision (Pc), closed-form isotropic-covariance
approximation.

Real per-object position covariance is not available from Space-Track's
basic GP/TLE product, so — consistent with this project's convention of
stating simplifications outright (see the sphere-Earth note in
risk/geodesy.py) — we assume a generic isotropic combined covariance
(same sigma in both encounter-plane axes) and use the exact identity:

    Pc = P(||N(d, sigma^2 * I_2)|| <= R)
       = ncx2.cdf((R/sigma)^2, df=2, nc=(d/sigma)^2)

where d is the miss distance, sigma the combined per-axis uncertainty, and
R the combined hard-body radius.

Two documented simplifications:
1. Isotropic assumed covariance — real conjunction assessment combines two
   full 3x3 covariances projected into the encounter plane; we have neither.
   DEFAULT_COMBINED_SIGMA_KM = 1.0 km reflects typical TLE-only tracking
   uncertainty (far coarser than operational ephemeris covariance).
2. The 3D minimum separation is used as d directly, rather than projecting
   onto the plane perpendicular to relative velocity (the b-plane). This
   slightly overestimates Pc for near-tangential encounters. The relative
   velocity at TCA is already computed in risk/pairwise.py, so a b-plane
   projection is a natural future refinement.

DEFAULT_HBR_KM = 0.02 (20 m combined hard-body radius) is the commonly cited
generic default when object dimensions are unknown.
"""

from __future__ import annotations

from scipy.stats import ncx2

DEFAULT_COMBINED_SIGMA_KM = 1.0
DEFAULT_HBR_KM = 0.02


def probability_of_collision(
    miss_distance_km: float,
    combined_sigma_km: float = DEFAULT_COMBINED_SIGMA_KM,
    hbr_km: float = DEFAULT_HBR_KM,
) -> float:
    """Probability that the true miss distance falls within the combined
    hard-body radius, under the isotropic-covariance model above."""
    if combined_sigma_km <= 0:
        raise ValueError("combined_sigma_km must be positive")
    x = (hbr_km / combined_sigma_km) ** 2
    nc = (miss_distance_km / combined_sigma_km) ** 2
    return float(ncx2.cdf(x, df=2, nc=nc))
