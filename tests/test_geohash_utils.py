"""Tests for the geohash tile selection."""

import pytest

from custom_components.blitzortung.const import RADIUS_MAX
from custom_components.blitzortung.geohash_utils import (
    compute_geohash_tiles,
    geohash_overlap,
)


def test_small_radius_uses_finest_precision_with_nine_tiles() -> None:
    """A normal radius picks the finest precision that needs at most 9 tiles."""
    tiles = geohash_overlap(50.0, 10.0, 100)

    assert 0 < len(tiles) <= 9
    precision = len(next(iter(tiles)))
    assert len(compute_geohash_tiles(50.0, 10.0, 100, precision + 1)) > 9


@pytest.mark.parametrize("lat", [0.0, 20.0, 38.0, 50.0, 60.0])
def test_largest_imperial_radius_still_subscribes(lat: float) -> None:
    """RADIUS_MAX in miles needs more than 9 top-level tiles; use them all."""
    radius_km = RADIUS_MAX * 1.609344

    tiles = geohash_overlap(lat, 10.0, radius_km)

    assert tiles == compute_geohash_tiles(lat, 10.0, radius_km, 1)
    assert len(tiles) > 9
