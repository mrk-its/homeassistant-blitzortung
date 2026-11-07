"""Tests for the geohash tile selection."""

import pytest
from homeassistant.const import UnitOfLength
from homeassistant.util.unit_conversion import DistanceConverter

from custom_components.blitzortung import geohash
from custom_components.blitzortung.const import (
    BINARY_TOPIC_GEOHASH_LEN,
    RADIUS_MAX,
    RADIUS_MAX_MI,
    RADIUS_MIN,
)
from custom_components.blitzortung.geohash_utils import (
    MAX_TILES,
    MIN_PRECISION,
    bbox,
    compute_geohash_tiles,
    fit_radius,
    geohash_overlap,
)


def test_small_radius_uses_finest_precision_with_nine_tiles() -> None:
    """A normal radius picks the finest precision that needs at most 9 tiles."""
    tiles = geohash_overlap(50.0, 10.0, 100)

    assert 0 < len(tiles) <= 9
    precision = len(next(iter(tiles)))
    assert len(compute_geohash_tiles(50.0, 10.0, 100, precision + 1)) > 9


@pytest.mark.parametrize(
    ("radius", "unit"),
    [(RADIUS_MAX, UnitOfLength.KILOMETERS), (RADIUS_MAX_MI, UnitOfLength.MILES)],
)
@pytest.mark.parametrize("lat", [0.0, 20.0, 38.0, 50.0, 60.0, 70.0, 80.0, -70.0])
def test_largest_radius_still_subscribes(
    lat: float, radius: int, unit: UnitOfLength
) -> None:
    """RADIUS_MAX gets all its precision-2 tiles, also when there are more than 9."""
    radius_km = DistanceConverter.convert(radius, unit, UnitOfLength.KILOMETERS)

    tiles = geohash_overlap(lat, 10.0, radius_km)

    assert tiles
    assert tiles == compute_geohash_tiles(lat, 10.0, radius_km, MIN_PRECISION)


@pytest.mark.parametrize("radius", [RADIUS_MIN, 100, 500, 1000, 2000, RADIUS_MAX])
@pytest.mark.parametrize("lat", [0.0, 38.0, 52.0, 70.0, 85.0, -45.0])
def test_never_subscribes_to_precision_one(lat: float, radius: int) -> None:
    """No radius or latitude yields a tile shorter than two characters."""
    tiles = geohash_overlap(lat, 10.0, radius)

    assert tiles
    assert min(len(tile) for tile in tiles) >= MIN_PRECISION == 2


@pytest.mark.parametrize(("lat", "radius"), [(52.0, 1000), (38.0, 1000), (70.0, 500)])
def test_large_radius_uses_precision_two_not_one(lat: float, radius: int) -> None:
    """A radius that needs more than 9 precision-2 tiles keeps all of them."""
    assert len(compute_geohash_tiles(lat, 10.0, radius, 2)) > 9

    tiles = geohash_overlap(lat, 10.0, radius)

    assert tiles == compute_geohash_tiles(lat, 10.0, radius, 2)


@pytest.mark.parametrize("lat", [0.0, 38.0, 52.0, 65.0, 70.0, -70.0])
def test_largest_radius_tile_count_is_bounded(lat: float) -> None:
    """RADIUS_MAX needs at most 32 subscriptions up to 70° latitude."""
    for lon in range(-180, 180, 5):
        assert len(geohash_overlap(lat, float(lon), RADIUS_MAX)) <= 32


@pytest.mark.parametrize("lat", [0.0, 52.0, 70.0, -70.0])
def test_fit_radius_keeps_radius_that_fits(lat: float) -> None:
    """Below about 75° latitude RADIUS_MAX fits in MAX_TILES and is kept."""
    assert fit_radius(lat, 10.0, RADIUS_MAX) == RADIUS_MAX


@pytest.mark.parametrize("lat", [80.0, 82.0, 85.0, 88.0, -85.0])
def test_fit_radius_shrinks_near_the_poles(lat: float) -> None:
    """Near the poles the radius shrinks to the largest one within MAX_TILES."""
    assert len(compute_geohash_tiles(lat, 10.0, RADIUS_MAX, 2)) > MAX_TILES

    radius = fit_radius(lat, 10.0, RADIUS_MAX)

    assert 0 < radius < RADIUS_MAX
    assert len(compute_geohash_tiles(lat, 10.0, radius, 2)) <= MAX_TILES
    # Bisection stops within ~1 km of the largest fitting radius.
    assert len(compute_geohash_tiles(lat, 10.0, radius + 1, 2)) > MAX_TILES


@pytest.mark.parametrize("lat", [75.0, 80.0, 85.0, 89.0, -89.0])
def test_fitted_radius_tile_count_is_bounded(lat: float) -> None:
    """With the fitted radius no location needs more than MAX_TILES subscriptions."""
    for lon in range(-180, 180, 15):
        radius = fit_radius(lat, float(lon), RADIUS_MAX)
        assert 0 < len(geohash_overlap(lat, float(lon), radius)) <= MAX_TILES


def test_fit_radius_honours_max_tiles() -> None:
    """A smaller cap gives a smaller radius."""
    radius = fit_radius(52.0, 10.0, RADIUS_MAX, max_tiles=4)

    assert radius < fit_radius(52.0, 10.0, RADIUS_MAX)
    assert len(compute_geohash_tiles(52.0, 10.0, radius, 2)) <= 4


def test_tiles_cover_the_whole_bounding_box() -> None:
    """Precision-2 tiles of a large radius contain every point of its box."""
    lat, lon, radius = 52.0, 21.0, 1000
    tiles = geohash_overlap(lat, lon, radius)
    box = bbox(lat, lon, radius)

    for point_lat in (box.s + 0.01, lat, box.n - 0.01):
        for point_lon in (box.w + 0.01, lon, box.e - 0.01):
            assert geohash.encode(point_lat, point_lon, 2) in tiles


def test_precision_capped_at_topic_geohash_length() -> None:
    """Subscriptions never go deeper than the geohash levels in strike topics."""
    tiles = geohash_overlap(50.0, 10.0, RADIUS_MIN, _max_tiles=10**6)

    assert {len(tile) for tile in tiles} == {BINARY_TOPIC_GEOHASH_LEN}


@pytest.mark.parametrize("lat", [0.0, 50.0, 70.0, -70.0])
def test_min_radius_fits_topic_geohash_length(lat: float) -> None:
    """RADIUS_MIN needs no more levels than the topic carries, so the cap is a no-op."""
    tiles = geohash_overlap(lat, 10.0, RADIUS_MIN)

    assert len(next(iter(tiles))) < BINARY_TOPIC_GEOHASH_LEN
