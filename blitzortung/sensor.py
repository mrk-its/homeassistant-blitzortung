import logging
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    ATTR_DEVICE_CLASS,
    CONF_NAME,
    LENGTH_KILOMETERS,
    DEGREE,
)
from homeassistant.helpers.entity import Entity

from .const import (
    ATTR_LIGHTNING_AZIMUTH,
    ATTR_LIGHTNING_DISTANCE,
    DOMAIN,
)

ATTRIBUTION = "Data provided by Blitzortung"

ATTR_ICON = "icon"
ATTR_LABEL = "label"
ATTR_UNIT = "unit"
ATTR_LIGHTNING_PROPERTY = "lightning_prop"

SENSOR_TYPES = {
    ATTR_LIGHTNING_DISTANCE: {
        ATTR_DEVICE_CLASS: None,
        ATTR_ICON: "mdi:blur",
        ATTR_LABEL: ATTR_LIGHTNING_DISTANCE.capitalize(),
        ATTR_UNIT: LENGTH_KILOMETERS,
        ATTR_LIGHTNING_PROPERTY: ATTR_LIGHTNING_DISTANCE,
    },
    ATTR_LIGHTNING_AZIMUTH: {
        ATTR_DEVICE_CLASS: None,
        ATTR_ICON: "mdi:blur",
        ATTR_LABEL: ATTR_LIGHTNING_AZIMUTH.capitalize(),
        ATTR_UNIT: DEGREE,
        ATTR_LIGHTNING_PROPERTY: ATTR_LIGHTNING_AZIMUTH,
    },
}

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    _LOGGER.info("config_entry_data: %s %s", config_entry.data, config_entry.entry_id)
    name = config_entry.data[CONF_NAME]

    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    sensors = []
    for sensor in SENSOR_TYPES:
        unique_id = f"{config_entry.unique_id}-lightning-{sensor.lower()}"
        sensors.append(BlitzortungSensor(coordinator, name, sensor, unique_id))

    async_add_entities(sensors, False)


class BlitzortungSensor(Entity):
    """Define a Blitzortung sensor."""

    def __init__(self, coordinator, name, kind, unique_id):
        """Initialize."""
        self.coordinator = coordinator
        self._name = name
        self._unique_id = unique_id
        self.kind = kind
        self._device_class = None
        self._state = None
        self._icon = None
        self._unit_of_measurement = None
        self._attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}

    @property
    def name(self):
        """Return the name."""
        return f"{self._name} Lightning {SENSOR_TYPES[self.kind][ATTR_LABEL]}"

    @property
    def should_poll(self):
        """Return the polling requirement of the entity."""
        return False

    @property
    def state(self):
        """Return the state."""
        return self._state

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self._attrs

    @property
    def icon(self):
        """Return the icon."""
        self._icon = SENSOR_TYPES[self.kind][ATTR_ICON]
        return self._icon

    @property
    def device_class(self):
        """Return the device_class."""
        return SENSOR_TYPES[self.kind][ATTR_DEVICE_CLASS]

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return self._unique_id

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in."""
        return SENSOR_TYPES[self.kind][ATTR_UNIT]

    @property
    def available(self):
        return True
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    def update_sensor(self):
        for lightning in self.coordinator.latest_lightnings():
            _LOGGER.debug("ligting: %s", lightning)
            self._state = lightning[SENSOR_TYPES[self.kind][ATTR_LIGHTNING_PROPERTY]]
            self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Connect to dispatcher listening for entity data notifications."""
        self.async_on_remove(self.coordinator.async_add_listener(self.update_sensor))

    async def async_update(self):
        await self.coordinator.async_request_refresh()
