"""Constants for the Blitzortung integration."""

import datetime as dt
from dataclasses import dataclass
from typing import Any

from homeassistant.util.hass_dict import HassKey

from .version import __version__


@dataclass
class BlitzortungConfig:
    """Configuration for Blitzortung integration."""

    config: dict[str, Any]


SW_VERSION = __version__

PLATFORMS = ["sensor", "geo_location"]

DOMAIN = "blitzortung"
BLITZORTUNG_CONFIG: HassKey[BlitzortungConfig] = HassKey(DOMAIN)
ATTR_LIGHTNING_AZIMUTH = "azimuth"
ATTR_LIGHTNING_COUNTER = "counter"
ATTR_LIGHTNING_DISTANCE = "distance"

SERVER_STATS = "server_stats"

CONF_RADIUS = "radius"
CONF_IDLE_RESET_TIMEOUT = "idle_reset_timeout"
CONF_TIME_WINDOW = "time_window"
CONF_MAX_TRACKED_LIGHTNINGS = "max_tracked_lightnings"
CONF_MAP_AREA = "map_area"
CONF_MAP_RADIUS = "map_radius"
CONF_MAP_CENTER_OVERRIDE = "map_center_override"
CONF_MAP_CENTER = "map_center"

CONF_LOCATION_ENTITY = "location_entity"
CONF_CONFIG_TYPE = "config_type"
CONFIG_TYPE_ENTITY = "entity"
CONFIG_TYPE_COORDINATES = "coordinates"

DEFAULT_IDLE_RESET_TIMEOUT = 120
DEFAULT_RADIUS = 100
DEFAULT_MAX_TRACKED_LIGHTNINGS = 100
DEFAULT_TIME_WINDOW = 120
DEFAULT_MAP_RADIUS = 0  # 0 = same as the detection radius
DEFAULT_UPDATE_INTERVAL = dt.timedelta(seconds=60)

# Batch per second: HA drops a client's whole websocket once 1024 messages stay
# queued for 10 s, which a per-strike stream to a sleeping phone could reach.
STREAM_FLUSH_INTERVAL = 1  # seconds
STREAM_SNAPSHOT_CHUNK = 2000
# 16 bytes per buffered strike, so this keeps the history under 1 MB.
STRIKE_BUFFER_MAX = 50_000

# Options bounds. Enforced by the options-flow schema so users can't accidentally
# enter values that would explode memory, evict every strike on the next tick,
# or otherwise put the integration in a degenerate state.
RADIUS_MIN = 1
# 4000 covers the actual usable upper bound regardless of unit. For metric
# users that's 4000 km; for imperial that's 4000 mi = 6437 km. Both stay
# under the geohash_overlap() empty-set cliff at most latitudes: above
# ~6700 km the bounding box exceeds precision-1 tile coverage and the
# function silently returns no subscriptions, so no strikes ever arrive.
RADIUS_MAX = 4000
MAP_RADIUS_MIN = 0
TIME_WINDOW_MIN = 1  # minutes
TIME_WINDOW_MAX = 1440  # 24 hours; longer than this churns the recorder hard.
MAX_TRACKED_LIGHTNINGS_MIN = 0  # 0 = sensors only, no geo_location entities
MAX_TRACKED_LIGHTNINGS_MAX = 1000
MAX_TRACKED_LIGHTNINGS_WARNING = 500
MIN_LOCATION_CHANGE_MULTIPLIER = 0.25

ATTR_LAT = "lat"
ATTR_LON = "lon"
ATTRIBUTION = "Data provided by blitzortung.org"
ATTR_EXTERNAL_ID = "external_id"
ATTR_PUBLICATION_DATE = "publication_date"

BLIZORTUNG_URL = "https://map.blitzortung.org/#10/{lat}/{lon}"

ZONE_HOME = "zone.home"
