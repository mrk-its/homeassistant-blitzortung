"""Blitzortung sensor platform."""

import logging

from homeassistant.const import CONF_NAME, DEGREE, UnitOfLength, EntityCategory
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from . import BlitzortungConfigEntry
from .const import (
    ATTR_LAT,
    ATTR_LIGHTNING_AZIMUTH,
    ATTR_LIGHTNING_COUNTER,
    ATTR_LON,
    ATTRIBUTION,
    BLITZORTUNG_CONFIG,
    DOMAIN,
    SERVER_STATS,
    SW_VERSION,
)


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry: BlitzortungConfigEntry, async_add_entities):
    integration_name = config_entry.data[CONF_NAME]

    coordinator = config_entry.runtime_data

    unique_prefix = config_entry.unique_id

    sensors = [
        klass(coordinator, integration_name, unique_prefix)
        for klass in (DistanceSensor, AzimuthSensor, CounterSensor)
    ]

    async_add_entities(sensors, False)

    config = hass.data[BLITZORTUNG_CONFIG]
    if config.get(SERVER_STATS):
        server_stat_sensors = {}

        def on_message(message):
            if not message.topic.startswith("$SYS/broker/"):
                return
            topic = message.topic.replace("$SYS/broker/", "")
            if topic.startswith("load") and not topic.endswith("/1min"):
                return
            if topic.startswith("clients") and topic != "clients/connected":
                return
            sensor = server_stat_sensors.get(topic)
            if not sensor:
                sensor = ServerStatSensor(
                    topic, coordinator, integration_name, unique_prefix
                )
                server_stat_sensors[topic] = sensor
                async_add_entities([sensor], False)
            sensor.on_message(topic, message)

        coordinator.register_message_receiver(on_message)


class BlitzortungSensor(SensorEntity):
    """Define a Blitzortung sensor."""

    _attr_icon = "mdi:flash"
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, coordinator, integration_name, unique_prefix):
        """Initialize."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{unique_prefix}-{self.kind}"
        self._attr_name = f"Lightning {self.kind.capitalize()}"
        self._attr_attribution = ATTRIBUTION
        self._attr_device_info = DeviceInfo(
            name=integration_name,
            identifiers={(DOMAIN, integration_name)},
            model="Blitzortung Lightning Detector",
            sw_version=SW_VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self):
        return self.coordinator.is_connected

    async def async_added_to_hass(self):
        """Connect to dispatcher listening for entity data notifications."""
        self.coordinator.register_sensor(self)

    async def async_update(self):
        await self.coordinator.async_request_refresh()

    def update_lightning(self, lightning):
        pass

    def on_message(self, message):
        pass

    def tick(self):
        pass


class LightningSensor(BlitzortungSensor):
    """Define a Blitzortung lightning sensor."""

    INITIAL_STATE = None

    def __init__(self, *args, **kwargs):
        """Initialize."""
        super().__init__(*args, **kwargs)
        self._attr_native_value = self.INITIAL_STATE

    def tick(self):
        if (
            self._attr_native_value != self.INITIAL_STATE
            and self.coordinator.is_inactive
        ):
            self._attr_native_value = self.INITIAL_STATE
            self.async_write_ha_state()


class DistanceSensor(LightningSensor):
    """Define a Blitzortung distance sensor."""

    kind = SensorDeviceClass.DISTANCE
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS

    def update_lightning(self, lightning):
        self._attr_native_value = lightning["distance"]
        self._attrs[ATTR_LAT] = lightning[ATTR_LAT]
        self._attrs[ATTR_LON] = lightning[ATTR_LON]
        self.async_write_ha_state()


class AzimuthSensor(LightningSensor):
    """Define a Blitzortung azimuth sensor."""

    kind = ATTR_LIGHTNING_AZIMUTH
    _attr_native_unit_of_measurement = DEGREE

    def update_lightning(self, lightning):
        self._attr_native_value = lightning["azimuth"]
        self._attrs[ATTR_LAT] = lightning[ATTR_LAT]
        self._attrs[ATTR_LON] = lightning[ATTR_LON]
        self.async_write_ha_state()


class CounterSensor(LightningSensor):
    """Define a Blitzortung counter sensor."""

    kind = ATTR_LIGHTNING_COUNTER
    _attr_native_unit_of_measurement = "↯"
    INITIAL_STATE = 0

    def update_lightning(self, lightning):
        self._attr_native_value = self._attr_native_value + 1
        self.async_write_ha_state()


class ServerStatSensor(BlitzortungSensor):
    """Define a Blitzortung server stats sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, topic, coordinator, integration_name, unique_prefix):
        """Initialize."""
        self._topic = topic

        topic_parts = topic.replace("$SYS/broker/", "").split("/")
        self.kind = "_".join(topic_parts)
        if self.kind.startswith("load"):
            self.data_type = float
        elif self.kind in ("uptime", "version"):
            self.data_type = str
        else:
            self.data_type = int

        if self.kind == "clients_connected":
            self.kind = "server_stats"

        self._name = " ".join(part.capitalize() for part in topic_parts)

        super().__init__(coordinator, integration_name, unique_prefix)

    @property
    def native_unit_of_measurement(self):
        if self.data_type in (int, float):
            return "." if self.kind == "server_stats" else " "
        else:
            return None

    @classmethod
    def for_topic(cls, topic, coordinator, integration_name, unique_prefix):
        return cls(topic, coordinator, integration_name, unique_prefix)

    def on_message(self, topic, message):
        if topic == self._topic:
            payload = message.payload.decode("utf-8")
            try:
                self._attr_native_value = self.data_type(payload)
            except ValueError:
                self._attr_native_value = str(payload)
            if self.hass:
                self.async_write_ha_state()
