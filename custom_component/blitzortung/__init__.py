"""The blitzortung integration."""
import asyncio
import json
import logging
import math
import time

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .mqtt import MQTT
from .geohash_utils import geohash_overlap
from . import const
from .const import DOMAIN, PLATFORMS
from .version import __version__


_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass: HomeAssistant, config: dict):
    """Initialize basic config of blitzortung component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up blitzortung from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    coordinator = BlitzortungDataUpdateCoordinator(
        hass,
        entry.data[CONF_LATITUDE],
        entry.data[CONF_LONGITUDE],
        entry.data[const.CONF_RADIUS],
        const.DEFAULT_UPDATE_INTERVAL,
    )

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.connect()
    await coordinator.async_refresh()

    async def start_platforms():
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_setup(entry, component)
                for component in PLATFORMS
            ]
        )

    hass.async_create_task(start_platforms())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    # cleanup platforms
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if not unload_ok:
        return False

    hass.data[DOMAIN].pop(entry.entry_id)

    return True


class BlitzortungDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, latitude, longitude, radius, update_interval):
        """Initialize."""
        self.hass = hass
        self.latitude = latitude
        self.longitude = longitude
        self.radius = radius
        self.http_client = aiohttp_client.async_get_clientsession(hass)
        self.host_nr = 1
        self.last_time = 0
        self.sensors = []
        self.geohash_overlap = geohash_overlap(
            self.latitude, self.longitude, self.radius
        )
        _LOGGER.info(
            "lat: %s, lon: %s, radius: %skm, geohashes: %s",
            self.latitude,
            self.longitude,
            self.radius,
            self.geohash_overlap,
        )

        # lat_delta = radius * 360 / 40000
        # lon_delta = lat_delta / math.cos(latitude * math.pi / 180.0)

        # west = longitude - lon_delta
        # east = longitude + lon_delta

        # north = latitude + lat_delta
        # south = latitude - lat_delta

        self.mqtt_client = MQTT(hass, "blitzortung.ha.sed.pl", 1883,)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            update_method=self._do_update,
        )

    def compute_polar_coords(self, lightning):
        dy = (lightning["lat"] - self.latitude) * math.pi / 180
        dx = (
            (lightning["lon"] - self.longitude)
            * math.pi
            / 180
            * math.cos(self.latitude * math.pi / 180)
        )
        distance = round(math.sqrt(dx * dx + dy * dy) * 6371, 1)
        azimuth = round(math.atan2(dx, dy) * 180 / math.pi)

        lightning[const.ATTR_LIGHTNING_DISTANCE] = distance
        lightning[const.ATTR_LIGHTNING_AZIMUTH] = azimuth

    async def connect(self):
        await self.mqtt_client.async_connect()
        _LOGGER.info("Connected to Blitzortung proxy mqtt server")
        for geohash_code in self.geohash_overlap:
            geohash_part = "/".join(geohash_code)
            await self.mqtt_client.async_subscribe(
                "blitzortung/1.0/{}/#".format(geohash_part), self.on_mqtt_message, qos=0
            )
        await self.mqtt_client.async_subscribe(
            "$SYS/broker/clients/connected", self.on_mqtt_message, qos=0
        )
        await self.mqtt_client.async_subscribe(
            "component/hello", self.on_hello_message, qos=0
        )

    def on_hello_message(self, message, *args):
        def parse_version(version_str):
            return tuple(map(int, version_str.split(".")))

        data = json.loads(message.payload)
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

    def on_mqtt_message(self, message, *args):
        for sensor in self.sensors:
            sensor.on_message(message)
        if message.topic.startswith("blitzortung/1.0"):
            lightning = json.loads(message.payload)
            self.compute_polar_coords(lightning)
            if lightning[const.ATTR_LIGHTNING_DISTANCE] < self.radius:
                _LOGGER.debug("ligntning data: %s", lightning)
                self.last_time = lightning["time"]
                for sensor in self.sensors:
                    sensor.update_lightning(lightning)

    def register_sensor(self, sensor):
        self.sensors.append(sensor)

    @property
    def is_inactive(self):
        dt = time.time() - self.last_time / 1e9
        return dt > const.INACTIVITY_RESET_SECONDS

    @property
    def is_connected(self):
        return self.mqtt_client.connected

    async def _do_update(self):
        is_inactive = self.is_inactive
        if not self.is_connected or is_inactive:
            for sensor in self.sensors:
                if is_inactive:
                    sensor.update_sensor(None)
                sensor.async_write_ha_state()
