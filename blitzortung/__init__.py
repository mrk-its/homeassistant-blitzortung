"""The blitzortung integration."""
import asyncio
import datetime
import json
import logging
import math
import random
import re
from urllib.parse import urlencode

import async_timeout

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import async_get_registry as get_dev_reg
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import const
from .const import DATA_UNSUBSCRIBE, DOMAIN, PLATFORMS

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
        datetime.timedelta(seconds=10),
    )

    blitzortung_data = hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_refresh()

    async def start_platforms():
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_setup(entry, component)
                for component in PLATFORMS
            ]
        )

    hass.async_create_task(start_platforms())

    _LOGGER.info("Blitzortung started!")
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
        self.latitude = latitude
        self.longitude = longitude
        self.radius = radius
        self.ligting_history = []
        self.http_client = aiohttp_client.async_get_clientsession(hass)
        self.host_nr = 1

        lat_delta = radius * 360 / 40000
        lon_delta = lat_delta / math.cos(latitude * math.pi / 180.0)

        print(lat_delta, lon_delta)

        west = longitude - lon_delta
        east = longitude + lon_delta

        north = latitude + lat_delta
        south = latitude - lat_delta

        self.url_template = (
            const.BASE_URL_TEMPLATE
            + "?"
            + urlencode(
                {
                    "north": north,
                    "south": south,
                    "east": east,
                    "west": west,
                    "number": 100,
                    "sig": 0,
                }
            )
        )

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    @property
    def last_time(self):
        return self.ligting_history and self.ligting_history[0]["time"] or None

    def latest_lightnings(self):
        for lightning in reversed(self.data or ()):
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

            yield lightning

    async def _async_update_data(self):
        """Update data"""
        initial = not bool(self.ligting_history)
        latest = []
        url = self.url_template.format(data_host_nr=self.host_nr + 1)
        try:
            with async_timeout.timeout(5):
                self.logger.info("fetching data from: %s", url)
                resp = await self.http_client.get(url)
        except Exception as e:
            self.logger.debug("err: %r", e)
            self.host_nr = (self.host_nr + 1) % 3
            raise

        if resp.status != 200:
            self.host_nr = (self.host_nr + 1) % 3
            raise UpdateFailed(f"status: {resp.status}")

        while True:
            line = await resp.content.readline()
            if not line:
                break
            data = json.loads(line)
            if not self.last_time or data["time"] > self.last_time:
                latest.append(data)
            else:
                break

        self.ligting_history[0:0] = latest

        return [] if initial else latest
