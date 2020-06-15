import logging

from homeassistant.const import (
    ATTR_ATTRIBUTION,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    CONF_NAME,
    DEGREE,
    LENGTH_KILOMETERS,
)
from homeassistant.core import callback
from homeassistant.helpers.entity import Entity

from .const import (
    ATTR_LIGHTNING_AZIMUTH,
    ATTR_LIGHTNING_COUNTER,
    ATTR_LIGHTNING_DISTANCE,
    DOMAIN,
)

ATTRIBUTION = "Data provided by blitzortung.org"

ATTR_ICON = "icon"
ATTR_LABEL = "label"
ATTR_UNIT = "unit"
ATTR_LIGHTNING_PROPERTY = "lightning_prop"

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    name = config_entry.data[CONF_NAME]

    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    unique_prefix = f"{coordinator.latitude}-{coordinator.longitude}-{name}-lightning"

    sensors = [
        klass(coordinator, name, unique_prefix)
        for klass in (DistanceSensor, AzimuthSensor, CounterSensor)
    ]

    async_add_entities(sensors, False)


class BlitzortungSensor(Entity):
    """Define a Blitzortung sensor."""

    def __init__(self, coordinator, name, unique_prefix):
        """Initialize."""
        self.coordinator = coordinator
        self._name = name
        self.entity_id = f"sensor.{name}-lightning-{self.label}"
        self._unique_id = f"{unique_prefix}-{self.kind}"
        self._device_class = None
        self._state = None
        self._unit_of_measurement = None
        self._attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}

    should_poll = False
    icon = "mdi:flash"
    device_class = None
    available = True

    @property
    def label(self):
        return self.kind.capitalize()

    @property
    def name(self):
        """Return the name."""
        return f"Lighting {self.label}"

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
        self.async_on_remove(self.coordinator.async_add_listener(self._update_sensor))

    async def async_update(self):
        await self.coordinator.async_request_refresh()

    @callback
    def _update_sensor(self):
        updated = self.update_sensor()
        if not updated and self._state is not None and self.coordinator.is_inactive:
            self._state = None
            self._attrs.pop(ATTR_LATITUDE, None)
            self._attrs.pop(ATTR_LONGITUDE, None)
            self.async_write_ha_state()

    @property
    def device_info(self):
        return {
            "name": f"{self._name} Lightning Detector",
            "identifiers": {(DOMAIN, self._name)},
            "model": "Lightning Detector",
            "sw-version": "0.0.1",
        }


class DistanceSensor(BlitzortungSensor):
    kind = ATTR_LIGHTNING_DISTANCE
    unit_of_measurement = LENGTH_KILOMETERS

    def update_sensor(self):
        updated = False
        for lightning in self.coordinator.latest_lightnings():
            self._state = lightning["distance"]
            self._attrs[ATTR_LATITUDE] = lightning["lat"]
            self._attrs[ATTR_LONGITUDE] = lightning["lon"]
            updated = True
            self.async_write_ha_state()
        return updated


class AzimuthSensor(BlitzortungSensor):
    kind = ATTR_LIGHTNING_AZIMUTH
    unit_of_measurement = DEGREE

    def update_sensor(self):
        updated = False
        for lightning in self.coordinator.latest_lightnings():
            self._state = lightning["azimuth"]
            self._attrs[ATTR_LATITUDE] = lightning["lat"]
            self._attrs[ATTR_LONGITUDE] = lightning["lon"]
            updated = True
            self.async_write_ha_state()
        return updated


class CounterSensor(BlitzortungSensor):
    kind = ATTR_LIGHTNING_COUNTER
    unit_of_measurement = "↯"

    def update_sensor(self):
        updated = False
        for lightning in self.coordinator.latest_lightnings():
            self._state = (self._state or 0) + 1
            updated = True
            self.async_write_ha_state()
        return updated
