"""Geohash utils."""

import math
from collections import namedtuple

from . import geohash
from .const import BINARY_TOPIC_GEOHASH_LEN

Box = namedtuple("Box", ["s", "w", "n", "e"])  # noqa: PYI024


def geohash_bbox(gh: str) -> Box:
    """Get the bounding box for a geohash."""
    ret = geohash.bbox(gh)
    return Box(ret["s"], ret["w"], ret["n"], ret["e"])


def bbox(lat: float, lon: float, radius: int) -> Box:
    """Compute a bounding box around a point with a given radius in meters."""
    lat_delta = radius * 360 / 40000
    lon_delta = lat_delta / math.cos(lat * math.pi / 180.0)
    return Box(lat - lat_delta, lon - lon_delta, lat + lat_delta, lon + lon_delta)


def overlap(a1: float, a2: float, b1: float, b2: float) -> bool:
    """Check if two ranges overlap."""
    return a1 < b2 and a2 > b1


def box_overlap(box1: Box, box2: Box) -> bool:
    """Check if two bounding boxes overlap."""
    return overlap(box1.s, box1.n, box2.s, box2.n) and overlap(
        box1.w, box1.e, box2.w, box2.e
    )


def compute_geohash_tiles(lat: float, lon: float, radius: int, precision: int) -> set:
    """Compute geohash tiles that overlap with a given radius around a point."""
    bounds = bbox(lat, lon, radius)
    center = geohash.encode(lat, lon, precision)

    stack = set()
    checked = set()

    stack.add(center)
    checked.add(center)

    while stack:
        current = stack.pop()
        for neighbor in geohash.neighbors(current):
            if neighbor not in checked and box_overlap(geohash_bbox(neighbor), bounds):
                stack.add(neighbor)
                checked.add(neighbor)
    return checked


# A precision-1 tile is 1/32 of the globe; the broker may refuse such broad
# subscriptions, so large radii take many precision-2 tiles instead.
MIN_PRECISION = 2
# Near the poles precision-2 tiles get narrow: RADIUS_MAX needs up to 64 of them
# above 85°N. fit_radius() shrinks the radius so one entry stays within this.
MAX_TILES = 32
# Bisection steps in fit_radius(): RADIUS_MAX / 2**10 is about 1 km.
_FIT_STEPS = 10


def fit_radius(
    lat: float, lon: float, radius: float, max_tiles: int = MAX_TILES
) -> float:
    """Largest radius up to ``radius`` whose MIN_PRECISION tiles fit in max_tiles."""
    if len(compute_geohash_tiles(lat, lon, radius, MIN_PRECISION)) <= max_tiles:
        return radius
    low, high = 0.0, float(radius)
    for _ in range(_FIT_STEPS):
        mid = (low + high) / 2
        if len(compute_geohash_tiles(lat, lon, mid, MIN_PRECISION)) <= max_tiles:
            low = mid
        else:
            high = mid
    return low


def geohash_overlap(lat: float, lon: float, radius: int, _max_tiles: int = 9) -> set:
    """Find geohash tiles that overlap with a given radius around a point."""
    result = set()
    for precision in range(MIN_PRECISION, BINARY_TOPIC_GEOHASH_LEN + 1):
        tiles = compute_geohash_tiles(lat, lon, radius, precision)
        # Keep MIN_PRECISION even above _max_tiles: an empty set subscribes to
        # nothing, so a large radius would silently get no strikes.
        if precision == MIN_PRECISION or len(tiles) <= _max_tiles:
            result = tiles
        else:
            break
    return result
