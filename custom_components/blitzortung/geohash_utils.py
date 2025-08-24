"""Geohash utils."""

import math
from collections import namedtuple

from . import geohash

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


def geohash_overlap(lat: float, lon: float, radius: int, _max_tiles: int = 9) -> set:
    """Find geohash tiles that overlap with a given radius around a point."""
    result = set()
    for precision in range(1, 13):
        tiles = compute_geohash_tiles(lat, lon, radius, precision)
        if len(tiles) <= 9:  # noqa: PLR2004
            result = tiles
            precision += 1  # noqa: PLW2901
        else:
            break
    return result
