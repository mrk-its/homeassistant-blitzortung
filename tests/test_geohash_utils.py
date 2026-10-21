"""Tests for the geohash tile selection."""

import pytest
from homeassistant.const import UnitOfLength
from homeassistant.util.unit_conversion import DistanceConverter

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


@pytest.mark.parametrize("unit", [UnitOfLength.KILOMETERS, UnitOfLength.MILES])
@pytest.mark.parametrize("lat", [0.0, 20.0, 38.0, 50.0, 60.0, 70.0, 80.0, -70.0])
def test_largest_radius_still_subscribes(lat: float, unit: UnitOfLength) -> None:
    """RADIUS_MAX gets all its precision-1 tiles, also when there are more than 9."""
    radius_km = DistanceConverter.convert(RADIUS_MAX, unit, UnitOfLength.KILOMETERS)

    tiles = geohash_overlap(lat, 10.0, radius_km)

    assert tiles
    assert tiles == compute_geohash_tiles(lat, 10.0, radius_km, 1)
