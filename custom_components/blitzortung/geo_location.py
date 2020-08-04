"""Support for Blitzortung geo location events."""
import bisect
from datetime import timedelta
import logging
import time

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    CONF_UNIT_SYSTEM_IMPERIAL,
    LENGTH_KILOMETERS,
    LENGTH_MILES,
)
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util.dt import utc_from_timestamp

from .const import DOMAIN, ATTRIBUTION, ATTR_EXTERNAL_ID, ATTR_PUBLICATION_DATE

_LOGGER = logging.getLogger(__name__)


DEFAULT_EVENT_NAME = "Lightning Strike"
DEFAULT_ICON = "mdi:flash"

SIGNAL_DELETE_ENTITY = "blitzortung_delete_entity_{0}"


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    manager = BlitzortungEventManager(
        hass,
        async_add_entities,
        coordinator.latitude,
        coordinator.longitude,
        coordinator.radius,
        coordinator.idle_reset_seconds,
    )

    coordinator.register_lightning_receiver(manager.lightning_cb)
    await manager.async_init()


class Strikes(list):
    def __init__(self):
        self._keys = []
        self._key_fn = lambda strike: strike._publication_date
        self._max_key = 0
        super().__init__()

    def insort(self, item):
        k = self._key_fn(item)
        if k > self._max_key:
            self._max_key = k
            self._keys.append(k)
            self.append(item)
            _LOGGER.info("optimized insert")
            return
        _LOGGER.info("standard insert")

        i = bisect.bisect_right(self._keys, k)
        self._keys.insert(i, k)
        self.insert(i, item)

    def cleanup(self, k):
        i = bisect.bisect_right(self._keys, k)
        if i:
            del self._keys[0:i]
            to_delete = self[0:i]
            self[0:i] = []
            return to_delete
        return ()


class BlitzortungEventManager:
    """Define a class to handle Blitzortung events."""

    def __init__(
        self, hass, async_add_entities, latitude, longitude, radius, window_seconds,
    ):
        """Initialize."""
        self._async_add_entities = async_add_entities
        self._hass = hass
        self._latitude = latitude
        self._longitude = longitude
        self._managed_strike_ids = set()
        self._radius = radius
        self._strikes = Strikes()
        self._window_seconds = window_seconds

        if hass.config.units.name == CONF_UNIT_SYSTEM_IMPERIAL:
            self._unit = LENGTH_MILES
        else:
            self._unit = LENGTH_KILOMETERS

    def lightning_cb(self, lightning):
        _LOGGER.info("geo_location lightning: %s", lightning)
        event = BlitzortungEvent(
            lightning["distance"],
            lightning["lat"],
            lightning["lon"],
            "km",
            lightning["time"] / 1e9,
        )
        self._strikes.insort(event)
        self._async_add_entities([event])

    @callback
    def _remove_events(self, ids_to_remove):
        """Remove old geo location events."""
        _LOGGER.debug("Going to remove %s", ids_to_remove)
        for strike_id in ids_to_remove:
            async_dispatcher_send(self._hass, SIGNAL_DELETE_ENTITY.format(strike_id))

    async def async_update(self):
        to_delete = self._strikes.cleanup(time.time() - self._window_seconds)
        if to_delete:
            for item in to_delete:
                async_dispatcher_send(
                    self._hass, SIGNAL_DELETE_ENTITY.format(item._strike_id)
                )
        _LOGGER.info("tick!")

    async def async_init(self):
        """Schedule regular updates based on configured time interval."""

        async def update(event_time):
            """Update."""
            await self.async_update()

        await self.async_update()
        async_track_time_interval(self._hass, update, timedelta(seconds=1))


class BlitzortungEvent(GeolocationEvent):
    """Define a lightning strike event."""

    def __init__(self, distance, latitude, longitude, unit, publication_date):
        """Initialize entity with data provided."""
        self._distance = distance
        self._latitude = latitude
        self._longitude = longitude
        self._publication_date = publication_date
        self._remove_signal_delete = None
        self._strike_id = f"{self._publication_date}-{self._latitude}-{self._longitude}"
        self._unit_of_measurement = unit

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        attributes = {}
        for key, value in (
            (ATTR_EXTERNAL_ID, self._strike_id),
            (ATTR_ATTRIBUTION, ATTRIBUTION),
            (ATTR_PUBLICATION_DATE, utc_from_timestamp(self._publication_date)),
        ):
            attributes[key] = value
        return attributes

    @property
    def distance(self):
        """Return distance value of this external event."""
        return self._distance

    @property
    def icon(self):
        """Return the icon to use in the front-end."""
        return DEFAULT_ICON

    @property
    def latitude(self):
        """Return latitude value of this external event."""
        return self._latitude

    @property
    def longitude(self):
        """Return longitude value of this external event."""
        return self._longitude

    @property
    def name(self):
        """Return the name of the event."""
        return DEFAULT_EVENT_NAME

    @property
    def source(self) -> str:
        """Return source value of this external event."""
        return DOMAIN

    @property
    def should_poll(self):
        """Disable polling."""
        return False

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @callback
    def _delete_callback(self):
        """Remove this entity."""
        self._remove_signal_delete()
        self.hass.async_create_task(self.async_remove())

    async def async_added_to_hass(self):
        """Call when entity is added to hass."""
        self._remove_signal_delete = async_dispatcher_connect(
            self.hass,
            SIGNAL_DELETE_ENTITY.format(self._strike_id),
            self._delete_callback,
        )
