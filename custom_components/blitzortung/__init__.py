"""The blitzortung integration."""

import logging
import math
import time

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME, UnitOfLength
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval

from homeassistant.util.json import json_loads_object
from homeassistant.util.unit_system import IMPERIAL_SYSTEM
from homeassistant.util.unit_conversion import DistanceConverter

from .const import (
    ATTR_LIGHTNING_DISTANCE,
    ATTR_LIGHTNING_AZIMUTH,
    BLITZORTUNG_CONFIG,
    CONF_IDLE_RESET_TIMEOUT,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    DEFAULT_IDLE_RESET_TIMEOUT,
    DEFAULT_MAX_TRACKED_LIGHTNINGS,
    DEFAULT_RADIUS,
    DEFAULT_TIME_WINDOW,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    PLATFORMS,
    SERVER_STATS,
)
from .geohash_utils import geohash_overlap
from .mqtt import MQTT, MQTT_CONNECTED, MQTT_DISCONNECTED
from .version import __version__

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Optional(SERVER_STATS, default=False): bool})},
    extra=vol.ALLOW_EXTRA,
)

BlitzortungConfigEntry = ConfigEntry["BlitzortungCoordinator"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Initialize basic config of blitzortung component."""
    hass.data[BLITZORTUNG_CONFIG] = config.get(DOMAIN) or {}
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: BlitzortungConfigEntry):
    """Set up blitzortung from a config entry."""
    config = hass.data[BLITZORTUNG_CONFIG]

    latitude = config_entry.data[CONF_LATITUDE]
    longitude = config_entry.data[CONF_LONGITUDE]
    radius = config_entry.options[CONF_RADIUS]
    max_tracked_lightnings = config_entry.options[CONF_MAX_TRACKED_LIGHTNINGS]
    time_window_seconds = config_entry.options[CONF_TIME_WINDOW] * 60

    if max_tracked_lightnings >= 500:
        _LOGGER.warning(
            "Large number of tracked lightnings: %s, it may lead to"
            "bigger memory usage / unstable frontend",
            max_tracked_lightnings,
        )

    if hass.config.units == IMPERIAL_SYSTEM:
        radius_mi = radius
        radius = DistanceConverter.convert(
            radius, UnitOfLength.MILES, UnitOfLength.KILOMETERS
        )
        _LOGGER.info("imperial system, %s mi -> %s km", radius_mi, radius)

    config_entry.runtime_data = BlitzortungCoordinator(
        hass,
        latitude,
        longitude,
        radius,
        max_tracked_lightnings,
        time_window_seconds,
        DEFAULT_UPDATE_INTERVAL,
        server_stats=config.get(SERVER_STATS),
    )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    await config_entry.runtime_data.connect()

    if not config_entry.update_listeners:
        config_entry.add_update_listener(async_update_options)

    return True


async def async_update_options(hass, config_entry: BlitzortungConfigEntry):
    """Update options."""
    _LOGGER.info("async_update_options")
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: BlitzortungConfigEntry):
    """Unload a config entry."""
    await config_entry.runtime_data.disconnect()
    _LOGGER.debug("Disconnected")

    return await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)


async def async_migrate_entry(hass, entry: BlitzortungConfigEntry):
    _LOGGER.debug("Migrating Blitzortung entry from Version %s", entry.version)
    if entry.version == 1:
        latitude = entry.data[CONF_LATITUDE]
        longitude = entry.data[CONF_LONGITUDE]
        radius = entry.data[CONF_RADIUS]
        name = entry.data[CONF_NAME]

        entry.unique_id = f"{latitude}-{longitude}-{name}-lightning"
        entry.data = {CONF_NAME: name}
        entry.options = {
            CONF_LATITUDE: latitude,
            CONF_LONGITUDE: longitude,
            CONF_RADIUS: radius,
        }
        entry.version = 2
    if entry.version == 2:
        entry.options = dict(entry.options)
        entry.options[CONF_IDLE_RESET_TIMEOUT] = DEFAULT_IDLE_RESET_TIMEOUT
        entry.version = 3
    if entry.version == 3:
        entry.options = dict(entry.options)
        entry.options[CONF_TIME_WINDOW] = entry.options.pop(
            CONF_IDLE_RESET_TIMEOUT, DEFAULT_TIME_WINDOW
        )
        entry.version = 4
    if entry.version == 4:
        new_data = entry.data.copy()

        latitude = entry.options.get(CONF_LATITUDE, hass.config.latitude)
        longitude = entry.options.get(CONF_LONGITUDE, hass.config.longitude)
        radius = entry.options.get(CONF_RADIUS, DEFAULT_RADIUS)
        time_window = entry.options.get(CONF_TIME_WINDOW, DEFAULT_TIME_WINDOW)
        max_tracked_lightnings = entry.options.get(
            CONF_MAX_TRACKED_LIGHTNINGS, DEFAULT_MAX_TRACKED_LIGHTNINGS
        )

        new_data[CONF_LATITUDE] = latitude
        new_data[CONF_LONGITUDE] = longitude
        new_options = {
            CONF_RADIUS: radius,
            CONF_TIME_WINDOW: time_window,
            CONF_MAX_TRACKED_LIGHTNINGS: max_tracked_lightnings,
        }

        hass.config_entries.async_update_entry(
            entry, data=new_data, options=new_options, version=5
        )

    return True


class BlitzortungCoordinator:
    def __init__(
        self,
        hass,
        latitude,
        longitude,
        radius,  # unit: km
        max_tracked_lightnings,
        time_window_seconds,
        update_interval,
        server_stats=False,
    ):
        """Initialize."""
        self.hass = hass
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

        _LOGGER.info(
            "lat: %s, lon: %s, radius: %skm, geohashes: %s",
            self.latitude,
            self.longitude,
            self.radius,
            self.geohash_overlap,
        )

        self.mqtt_client = MQTT(
            hass,
            "blitzortung.ha.sed.pl",
            1883,
        )

        self._disconnect_callbacks.append(
            async_dispatcher_connect(
                self.hass, MQTT_CONNECTED, self._on_connection_change
            )
        )
        self._disconnect_callbacks.append(
            async_dispatcher_connect(
                self.hass, MQTT_DISCONNECTED, self._on_connection_change
            )
        )

    @callback
    def _on_connection_change(self, *args, **kwargs):
        if self.unloading:
            return
        for sensor in self.sensors:
            sensor.async_write_ha_state()

    def compute_polar_coords(self, lightning):
        dy = (lightning["lat"] - self.latitude) * math.pi / 180
        dx = (
            (lightning["lon"] - self.longitude)
            * math.pi
            / 180
            * math.cos(self.latitude * math.pi / 180)
        )
        distance = round(math.sqrt(dx * dx + dy * dy) * 6371, 1)
        azimuth = round(math.atan2(dx, dy) * 180 / math.pi) % 360

        lightning[ATTR_LIGHTNING_DISTANCE] = distance
        lightning[ATTR_LIGHTNING_AZIMUTH] = azimuth

    async def connect(self):
        await self.mqtt_client.async_connect()
        _LOGGER.info("Connected to Blitzortung proxy mqtt server")
        for geohash_code in self.geohash_overlap:
            geohash_part = "/".join(geohash_code)
            await self.mqtt_client.async_subscribe(
                "blitzortung/1.1/{}/#".format(geohash_part), self.on_mqtt_message, qos=0
            )
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

    async def disconnect(self):
        self.unloading = True
        await self.mqtt_client.async_disconnect()
        for cb in self._disconnect_callbacks:
            cb()

    def on_hello_message(self, message, *args):
        def parse_version(version_str):
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

    async def on_mqtt_message(self, message, *args):
        for callback in self.callbacks:
            callback(message)
        if message.topic.startswith("blitzortung/1.1"):
            lightning = json_loads_object(message.payload)
            self.compute_polar_coords(lightning)
            if lightning[SensorDeviceClass.DISTANCE] < self.radius:
                _LOGGER.debug("lightning data: %s", lightning)
                self.last_time = time.time()
                for callback in self.lightning_callbacks:
                    await callback(lightning)
                for sensor in self.sensors:
                    sensor.update_lightning(lightning)

    def register_sensor(self, sensor):
        self.sensors.append(sensor)
        self.register_on_tick(sensor.tick)

    def register_message_receiver(self, message_cb):
        self.callbacks.append(message_cb)

    def register_lightning_receiver(self, lightning_cb):
        self.lightning_callbacks.append(lightning_cb)

    def register_on_tick(self, on_tick_cb):
        self.on_tick_callbacks.append(on_tick_cb)

    @property
    def is_inactive(self):
        return bool(
            self.time_window_seconds
            and (time.time() - self.last_time) >= self.time_window_seconds
        )

    @property
    def is_connected(self):
        return self.mqtt_client.connected

    async def _tick(self, *args):
        for cb in self.on_tick_callbacks:
            cb()
