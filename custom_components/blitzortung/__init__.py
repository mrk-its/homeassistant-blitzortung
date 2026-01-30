"""The blitzortung integration."""

import logging
import math
import time
from collections.abc import Callable
from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME, UnitOfLength
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ENABLE_DIAGNOSTICS,
    CONF_LOCATION_ENTITY,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_SERVER_STATS,
    CONF_TIME_WINDOW,
    DEFAULT_ENABLE_DIAGNOSTICS,
    DEFAULT_MAX_TRACKED_LIGHTNINGS,
    DEFAULT_RADIUS,
    DEFAULT_SERVER_STATS,
    DEFAULT_TIME_WINDOW,
    DOMAIN,
    PLATFORMS,
)
from .geohash_utils import geohash_overlap
from .mqtt import BlitzortungMqttClient

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Optional(CONF_NAME): cv.string})}, extra=vol.ALLOW_EXTRA
)

SERVICE_TRIGGER_EVENT_SCHEMA = vol.Schema({})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Blitzortung component."""
    hass.data.setdefault(DOMAIN, {})

    async def handle_trigger_event(call: ServiceCall) -> None:
        """Handle the service call."""
        coordinator: BlitzortungCoordinator | None = None
        for entry_data in hass.data[DOMAIN].values():
            if isinstance(entry_data, dict) and "coordinator" in entry_data:
                coordinator = entry_data["coordinator"]
                break

        if coordinator is None:
            _LOGGER.warning("No Blitzortung coordinator found to trigger event")
            return

        coordinator.trigger_event()

    hass.services.async_register(
        DOMAIN,
        "trigger_event",
        handle_trigger_event,
        schema=SERVICE_TRIGGER_EVENT_SCHEMA,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Blitzortung from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Backwards compatibility for older entries
    latitude = entry.data.get(CONF_LATITUDE, hass.config.latitude)
    longitude = entry.data.get(CONF_LONGITUDE, hass.config.longitude)

    location_entity = entry.data.get(CONF_LOCATION_ENTITY)

    radius = entry.options.get(CONF_RADIUS, entry.data.get(CONF_RADIUS, DEFAULT_RADIUS))
    max_tracked_lightnings = entry.options.get(
        CONF_MAX_TRACKED_LIGHTNINGS,
        entry.data.get(CONF_MAX_TRACKED_LIGHTNINGS, DEFAULT_MAX_TRACKED_LIGHTNINGS),
    )
    time_window_seconds = entry.options.get(
        CONF_TIME_WINDOW,
        entry.data.get(CONF_TIME_WINDOW, DEFAULT_TIME_WINDOW),
    )
    server_stats = entry.options.get(
        CONF_SERVER_STATS, entry.data.get(CONF_SERVER_STATS, DEFAULT_SERVER_STATS)
    )
    enable_diagnostics = entry.options.get(
        CONF_ENABLE_DIAGNOSTICS,
        entry.data.get(CONF_ENABLE_DIAGNOSTICS, DEFAULT_ENABLE_DIAGNOSTICS),
    )

    coordinator = BlitzortungCoordinator(
        hass=hass,
        latitude=latitude,
        longitude=longitude,
        location_entity=location_entity,
        radius=radius,
        max_tracked_lightnings=max_tracked_lightnings,
        time_window_seconds=time_window_seconds,
        _update_interval=60,
        server_stats=server_stats,
    )

    mqtt_client = BlitzortungMqttClient(
        hass=hass,
        coordinator=coordinator,
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "mqtt_client": mqtt_client,
        "enable_diagnostics": enable_diagnostics,
    }

    await mqtt_client.async_connect()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_data = hass.data[DOMAIN].pop(entry.entry_id)

    coordinator: BlitzortungCoordinator = entry_data["coordinator"]
    mqtt_client: BlitzortungMqttClient = entry_data["mqtt_client"]

    coordinator.unloading = True

    await mqtt_client.async_disconnect()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    coordinator.shutdown()

    return unload_ok


class BlitzortungCoordinator:
    """Coordinator for Blitzortung data."""

    def __init__(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
        location_entity: str | None,
        radius: int,  # unit: km
        max_tracked_lightnings: int,
        time_window_seconds: int,
        _update_interval: int,
        server_stats: bool = False,
    ) -> None:
        """Initialize."""
        self.hass = hass
        self._static_latitude = latitude
        self._static_longitude = longitude

        # ✅ Ensure location_entity is always a string or None.
        # This prevents Home Assistant helpers from crashing (they call .lower()).
        self.location_entity = (
            location_entity
            if isinstance(location_entity, str) and location_entity
            else None
        )

        self.latitude = latitude
        self.longitude = longitude
        self.radius = radius
        self.max_tracked_lightnings = max_tracked_lightnings
        self.time_window_seconds = time_window_seconds
        self.server_stats = server_stats
        self.last_time = 0
        self.sensors = []
        self.callbacks = []
        self.lightning_callbacks = []
        self.on_tick_callbacks = []
        self.geohash_overlap = geohash_overlap(
            self.latitude, self.longitude, self.radius
        )
        self._disconnect_callbacks = []
        self.unloading = False

        self._location_unsubscribe: Callable[[], None] | None = None

        if self.location_entity:
            _LOGGER.info("Tracking location entity: %s", self.location_entity)
            state = hass.states.get(self.location_entity)
            if state and state.attributes:
                self.latitude = state.attributes.get(CONF_LATITUDE, self.latitude)
                self.longitude = state.attributes.get(CONF_LONGITUDE, self.longitude)
            else:
                _LOGGER.warning(
                    "Location entity %s does not have coordinates yet, using static",
                    self.location_entity,
                )
            self.geohash_overlap = geohash_overlap(
                self.latitude, self.longitude, self.radius
            )
            self._location_unsubscribe = async_track_state_change_event(
                self.hass, [self.location_entity], self._handle_location_entity_change
            )

        _LOGGER.info(
            "lat: %s, lon: %s, radius: %skm, geohashes: %s",
            self.latitude,
            self.longitude,
            self.radius,
            self.geohash_overlap,
        )

    @callback
    def _handle_location_entity_change(self, event: Any) -> None:
        """Handle changes for the tracked location entity."""
        if self.unloading:
            return

        new_state = event.data.get("new_state")
        if not new_state or not new_state.attributes:
            return

        latitude = new_state.attributes.get(CONF_LATITUDE)
        longitude = new_state.attributes.get(CONF_LONGITUDE)

        if latitude is None or longitude is None:
            return

        self.latitude = latitude
        self.longitude = longitude
        self.geohash_overlap = geohash_overlap(self.latitude, self.longitude, self.radius)

        _LOGGER.debug(
            "Updated dynamic location to lat=%s lon=%s geohashes=%s",
            self.latitude,
            self.longitude,
            self.geohash_overlap,
        )

    def register_sensor(self, sensor: Any) -> None:
        """Register a sensor."""
        self.sensors.append(sensor)

    def unregister_sensor(self, sensor: Any) -> None:
        """Unregister a sensor."""
        if sensor in self.sensors:
            self.sensors.remove(sensor)

    def register_callback(self, callback_func: Callable[..., None]) -> None:
        """Register a callback."""
        self.callbacks.append(callback_func)

    def unregister_callback(self, callback_func: Callable[..., None]) -> None:
        """Unregister a callback."""
        if callback_func in self.callbacks:
            self.callbacks.remove(callback_func)

    def register_lightning_callback(self, callback_func: Callable[..., None]) -> None:
        """Register a lightning callback."""
        self.lightning_callbacks.append(callback_func)

    def unregister_lightning_callback(self, callback_func: Callable[..., None]) -> None:
        """Unregister a lightning callback."""
        if callback_func in self.lightning_callbacks:
            self.lightning_callbacks.remove(callback_func)

    def register_on_tick_callback(self, callback_func: Callable[..., None]) -> None:
        """Register an on-tick callback."""
        self.on_tick_callbacks.append(callback_func)

    def unregister_on_tick_callback(self, callback_func: Callable[..., None]) -> None:
        """Unregister an on-tick callback."""
        if callback_func in self.on_tick_callbacks:
            self.on_tick_callbacks.remove(callback_func)

    def register_disconnect_callback(self, callback_func: Callable[..., None]) -> None:
        """Register a disconnect callback."""
        self._disconnect_callbacks.append(callback_func)

    def unregister_disconnect_callback(self, callback_func: Callable[..., None]) -> None:
        """Unregister a disconnect callback."""
        if callback_func in self._disconnect_callbacks:
            self._disconnect_callbacks.remove(callback_func)

    def shutdown(self) -> None:
        """Shutdown the coordinator."""
        if self._location_unsubscribe:
            self._location_unsubscribe()
            self._location_unsubscribe = None

        for cb in list(self._disconnect_callbacks):
            try:
                cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error running disconnect callback")

        self._disconnect_callbacks.clear()

    def trigger_event(self) -> None:
        """Trigger an event for debugging/testing purposes."""
        now = dt_util.utcnow()
        payload = {
            "timestamp": now.isoformat(),
            "lat": self.latitude,
            "lon": self.longitude,
            "distance": 0.0,
            "azimuth": 0.0,
            "device_class": SensorDeviceClass.DISTANCE,
            "unit_of_measurement": UnitOfLength.KILOMETERS,
        }
        self._fire_lightning_event(payload)

    def _fire_lightning_event(self, payload: dict[str, Any]) -> None:
        """Fire a lightning event and notify callbacks."""
        self.hass.bus.fire(f"{DOMAIN}_lightning", payload)

        for cb in list(self.lightning_callbacks):
            try:
                cb(payload)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error in lightning callback")

    def compute_polar_coords(
        self, lightning_lat: float, lightning_lon: float
    ) -> tuple[float, int]:
        """Compute distance (km) and azimuth (deg) from current location to lightning."""
        # Haversine formula distance
        r = 6371.0
        lat1 = math.radians(self.latitude)
        lon1 = math.radians(self.longitude)
        lat2 = math.radians(lightning_lat)
        lon2 = math.radians(lightning_lon)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        distance = r * c

        # Bearing
        y = math.sin(dlon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(
            dlon
        )
        bearing = math.degrees(math.atan2(y, x))
        azimuth = int((bearing + 360) % 360)

        return round(distance, 1), azimuth
