"""
Parse the fields we need out of a raw TLE line 2, per the fixed-width format
defined at https://celestrak.org/NORAD/documentation/tle-fmt.php

We only parse eccentricity and mean motion here — full orbital element
parsing for propagation is handled by the sgp4 library directly in Phase 2,
which reads line1/line2 itself. This module exists purely to support
altitude-band filtering during ingestion.
"""

from __future__ import annotations


def parse_eccentricity(line2: str) -> float:
    # Columns 27-33 (1-indexed), decimal point assumed: "0001234" -> 0.0001234
    raw = line2[26:33].strip()
    return float(f"0.{raw}")


def parse_mean_motion(line2: str) -> float:
    # Columns 53-63 (1-indexed): revolutions per day
    raw = line2[52:63].strip()
    return float(raw)


def parse_norad_id_from_line1(line1: str) -> int:
    # Columns 3-7 (1-indexed)
    return int(line1[2:7].strip())
