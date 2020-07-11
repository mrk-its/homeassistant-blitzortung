import logging
from typing import Optional, Dict

from homeassistant.const import (
    ATTR_ATTRIBUTION,
    CONF_NAME,
    LENGTH_KILOMETERS,
)
from homeassistant.helpers.entity import Entity

from .const import (
    ATTR_LIGHTNING_AZIMUTH,
    ATTR_LIGHTNING_COUNTER,
    ATTR_LIGHTNING_DISTANCE,
    DOMAIN,
    ATTR_LAT,
    ATTR_LON,
)

ATTRIBUTION = "Data provided by blitzortung.org"

ATTR_ICON = "icon"
ATTR_LABEL = "label"
ATTR_UNIT = "unit"
ATTR_LIGHTNING_PROPERTY = "lightning_prop"

DEGREE = "°"

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    name = config_entry.data[CONF_NAME]

    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    unique_prefix = config_entry.unique_id

    sensors = [
        klass(coordinator, name, unique_prefix)
        for klass in (DistanceSensor, AzimuthSensor, CounterSensor, ServerStatsSensor)
    ]

    async_add_entities(sensors, False)


class BlitzortungSensor(Entity):
    """Define a Blitzortung sensor."""

    def __init__(self, coordinator, name, unique_prefix):
        """Initialize."""
        self.coordinator = coordinator
        self._name = name
        self.entity_id = f"sensor.{name}-{self.name}"
        self._unique_id = f"{unique_prefix}-{self.kind}"
        self._device_class = None
        self._state = None
        self._unit_of_measurement = None
        self._attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}

    should_poll = False
    icon = "mdi:flash"
    device_class = None

    @property
    def available(self):
        return self.coordinator.is_connected

    @property
    def label(self):
        return self.kind.capitalize()

    @property
    def name(self):
        """Return the name."""
        return f"Lightning {self.label}"

    @property
    def state(self):
        """Return the state."""
        return self._state

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self._attrs

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return self._unique_id

    async def async_added_to_hass(self):
        """Connect to dispatcher listening for entity data notifications."""
        # self.async_on_remove(self.coordinator.async_add_listener(self._update_sensor))
        self.coordinator.register_sensor(self)

    async def async_update(self):
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        return {
            "name": f"{self._name} Lightning Detector",
            "identifiers": {(DOMAIN, self._name)},
            "model": "Lightning Detector",
            "sw-version": "0.0.1",
        }

    def update_lightning(self, lightning):
        pass

    def on_message(self, message):
        pass


class DistanceSensor(BlitzortungSensor):
    kind = ATTR_LIGHTNING_DISTANCE
    unit_of_measurement = LENGTH_KILOMETERS

    def update_lightning(self, lightning: Optional[Dict]):
        self._state = lightning and lightning["distance"]
        self._attrs[ATTR_LAT] = lightning and lightning[ATTR_LAT]
        self._attrs[ATTR_LON] = lightning and lightning[ATTR_LON]
        self.async_write_ha_state()


class AzimuthSensor(BlitzortungSensor):
    kind = ATTR_LIGHTNING_AZIMUTH
    unit_of_measurement = DEGREE

    def update_lightning(self, lightning: Optional[Dict]):
        self._state = lightning and lightning["azimuth"]
        self._attrs[ATTR_LAT] = lightning and lightning[ATTR_LAT]
        self._attrs[ATTR_LON] = lightning and lightning[ATTR_LON]
        self.async_write_ha_state()


class CounterSensor(BlitzortungSensor):
    kind = ATTR_LIGHTNING_COUNTER
    unit_of_measurement = "↯"

    def update_lightning(self, lightning: Optional[Dict]):
        if not lightning:
            self._state = 0
        else:
            self._state = (self._state or 0) + 1
        self.async_write_ha_state()


class ServerStatsSensor(BlitzortungSensor):
    kind = "server_stats"
    unit_of_measurement = "."

    name = "Clients Connected"

    def on_message(self, message):
        if message.topic == "$SYS/broker/clients/connected":
            self._state = int(message.payload)
            self.async_write_ha_state()
