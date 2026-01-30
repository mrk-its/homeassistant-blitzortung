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

    async def connect(self) -> None:
        """Connect to MQTT broker."""
        await self.mqtt_client.async_connect()
        _LOGGER.info("Connected to Blitzortung proxy mqtt server")
        for geohash_code in self.geohash_overlap:
            geohash_part = "/".join(geohash_code)
            unsub = await self.mqtt_client.async_subscribe(
                f"blitzortung/1.1/{geohash_part}/#", self.on_mqtt_message, qos=0
            )
            self._geohash_unsubscribers.append(unsub)
        if self.server_stats:
            await self.mqtt_client.async_subscribe(
                "$SYS/broker/#", self.on_mqtt_message, qos=0
            )
        await self.mqtt_client.async_subscribe(
            "component/hello", self.on_hello_message, qos=0
        )

        self._disconnect_callbacks.append(
            async_track_time_interval(self.hass, self._tick, DEFAULT_UPDATE_INTERVAL)
        )

    async def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        self.unloading = True
        await self.mqtt_client.async_disconnect()
        for cb in self._disconnect_callbacks:
            cb()

        if self._location_unsubscribe:
            self._location_unsubscribe()
            self._location_unsubscribe = None

    def on_hello_message(self, message: Message, *args: Any) -> None:  # noqa: ARG002
        """Handle incoming hello message."""

        def parse_version(version_str: str) -> tuple[int, int, int]:
            """Parse version string into a tuple of integers."""
            return tuple(map(int, version_str.split(".")))

        data = json_loads_object(message.payload)
        latest_version_str = data.get("latest_version")
        if latest_version_str:
            default_message = (
                f"New version {latest_version_str} is available. "
                f"[Check it out](https://github.com/mrk-its/homeassistant-blitzortung)"
            )
            latest_version_message = data.get("latest_version_message", default_message)
            latest_version_title = data.get("latest_version_title", "Blitzortung")
            latest_version = parse_version(latest_version_str)
            current_version = parse_version(__version__)
            if latest_version > current_version:
                _LOGGER.info("new version is available: %s", latest_version_str)
                self.hass.components.persistent_notification.async_create(
                    title=latest_version_title,
                    message=latest_version_message,
                    notification_id="blitzortung_new_version_available",
                )

    async def on_mqtt_message(self, message: Message, *args: Any) -> None:  # noqa: ARG002
        """Handle incoming MQTT messages."""
        for cb in self.callbacks:
            cb(message)
        if message.topic.startswith("blitzortung/1.1"):
            lightning = json_loads_object(message.payload)
            self.compute_polar_coords(lightning)
            if lightning[SensorDeviceClass.DISTANCE] < self.radius:
                _LOGGER.debug("lightning data: %s", lightning)
                self.last_time = time.time()
                for cb in self.lightning_callbacks:
                    await cb(lightning)
                for sensor in self.sensors:
                    sensor.update_lightning(lightning)

    def register_sensor(self, sensor: BlitzortungEntity) -> None:
        """Register a sensor to be updated on each lightning strike."""
        self.sensors.append(sensor)
        self.register_on_tick(sensor.tick)

    def register_message_receiver(self, message_cb: Callable) -> None:
        """Register a callback to be called on each MQTT message."""
        self.callbacks.append(message_cb)

    def register_lightning_receiver(self, lightning_cb: Callable) -> None:
        """Register a callback to be called on each lightning strike."""
        self.lightning_callbacks.append(lightning_cb)

    def register_on_tick(self, on_tick_cb: Callable) -> None:
        """Register a callback to be called on each tick."""
        self.on_tick_callbacks.append(on_tick_cb)

    @property
    def is_inactive(self) -> bool:
        """Check if the coordinator is inactive."""
        return bool(
            self.time_window_seconds
            and (time.time() - self.last_time) >= self.time_window_seconds
        )

    @property
    def is_connected(self) -> bool:
        """Check if the MQTT client is connected."""
        return self.mqtt_client.connected

    async def _tick(self, *args: Any) -> None:  # noqa: ARG002
        """Call registered callbacks on each tick."""
        for cb in self.on_tick_callbacks:
            cb()
