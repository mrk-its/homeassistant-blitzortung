"""Blitzortung sensor platform."""

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_PLATFORM,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    EntityCategory,
    UnitOfLength,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import UNDEFINED

from . import BlitzortungConfigEntry, BlitzortungCoordinator
from .const import (
    ATTR_LAT,
    ATTR_LIGHTNING_AZIMUTH,
    ATTR_LIGHTNING_COUNTER,
    ATTR_LIGHTNING_DISTANCE,
    ATTR_LON,
    ATTR_REFERENCE_LAT,
    ATTR_REFERENCE_LON,
    BLITZORTUNG_CONFIG,
    BLIZORTUNG_URL,
    DOMAIN,
    SERVER_STATS,
    SW_VERSION,
)
from .entity import BlitzortungEntity
from .mqtt import Message

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class BlitzortungSensorEntityDescription(SensorEntityDescription):
    """Blitzortun sensor entity description."""

    entity_class: type["BlitzortungSensor"]


class BlitzortungSensor(BlitzortungEntity, SensorEntity):
    """Define a Blitzortung sensor."""

    def __init__(
        self,
        coordinator: BlitzortungCoordinator,
        description: BlitzortungSensorEntityDescription,
        integration_name: str,
        unique_prefix: str,
    ) -> None:
        """Initialize."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{unique_prefix}-{description.key}"
        if description.name is UNDEFINED:
            self._attr_name = f"Server {description.key.replace('_', ' ').lower()}"
        self._integration_name = integration_name
        self._unique_prefix = unique_prefix
        self.entity_description = description

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            name=self._integration_name,
            identifiers={(DOMAIN, self._unique_prefix)},
            model="Blitzortung Lightning Detector",
            sw_version=SW_VERSION,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=BLIZORTUNG_URL.format(
                lat=self.coordinator.latitude, lon=self.coordinator.longitude
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if the sensor is available."""
        return self.coordinator.is_connected

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        base: dict[str, Any] = {
            ATTR_REFERENCE_LAT: self.coordinator.latitude,
            ATTR_REFERENCE_LON: self.coordinator.longitude,
        }
        if getattr(self, "_attr_extra_state_attributes", None):
            base.update(self._attr_extra_state_attributes)
        return base

    async def async_added_to_hass(self) -> None:
        """Connect to dispatcher listening for entity data notifications."""
        self.coordinator.register_sensor(self)

    async def async_update(self) -> None:
        """Update the sensor data."""
        await self.coordinator.async_request_refresh()


class LightningSensor(BlitzortungSensor):
    """Define a Blitzortung lightning sensor."""

    INITIAL_STATE: int | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize."""
        super().__init__(*args, **kwargs)
        self._attr_native_value = self.INITIAL_STATE

    def tick(self) -> None:
        """Handle tick."""
        if (
            self._attr_native_value != self.INITIAL_STATE
            and self.coordinator.is_inactive
        ):
            self._attr_native_value = self.INITIAL_STATE
            self.async_write_ha_state()


class DistanceSensor(LightningSensor):
    """Define a Blitzortung distance sensor."""

    def update_lightning(self, lightning: dict[str, Any]) -> None:
        """Update the sensor data."""
        self._attr_native_value = lightning[ATTR_LIGHTNING_DISTANCE]
        self._attr_extra_state_attributes = {
            ATTR_LAT: lightning[ATTR_LAT],
            ATTR_LON: lightning[ATTR_LON],
        }
        self.async_write_ha_state()


class AzimuthSensor(LightningSensor):
    """Define a Blitzortung azimuth sensor."""

    def update_lightning(self, lightning: dict[str, Any]) -> None:
        """Update the sensor data."""
        self._attr_native_value = lightning[ATTR_LIGHTNING_AZIMUTH]
        self._attr_extra_state_attributes = {
            ATTR_LAT: lightning[ATTR_LAT],
            ATTR_LON: lightning[ATTR_LON],
        }
        self.async_write_ha_state()


class CounterSensor(LightningSensor):
    """Define a Blitzortung counter sensor."""

    INITIAL_STATE = 0

    def update_lightning(self, _lightning: dict[str, Any]) -> None:
        """Update the sensor data."""
        self._attr_native_value = self._attr_native_value + 1
        self.async_write_ha_state()


class ServerStatSensor(BlitzortungSensor):
    """Define a Blitzortung server stats sensor."""

    def __init__(
        self,
        topic: str,
        coordinator: BlitzortungCoordinator,
        description: BlitzortungSensorEntityDescription,
        integration_name: str,
        unique_prefix: str,
    ) -> None:
        """Initialize."""
        self._topic = topic

        topic_parts = topic.split("/")
        self.kind = "_".join(topic_parts)
        if self.kind.startswith("load"):
            self.data_type = float
        elif self.kind == "version":
            self.data_type = str
        else:
            self.data_type = int
        if self.data_type in (int, float):
            self._attr_state_class = SensorStateClass.MEASUREMENT

        super().__init__(coordinator, description, integration_name, unique_prefix)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""
        if self.kind == "uptime":
            return UnitOfTime.SECONDS
        if self.data_type in (int, float):
            return "clients" if self.kind == "clients_connected" else " "
        return None

    def on_message(self, topic: str, message: Message) -> None:
        """Handle incoming MQTT messages."""
        if topic == self._topic:
            payload = message.payload.decode("utf-8")
            if self.kind == "uptime":
                payload = payload.split(" ")[0]
            try:
                self._attr_native_value = self.data_type(payload)
            except ValueError:
                self._attr_native_value = str(payload)
            if self.hass:
                self.async_write_ha_state()


SENSORS: tuple[BlitzortungSensorEntityDescription, ...] = (
    BlitzortungSensorEntityDescription(
        key=ATTR_LIGHTNING_AZIMUTH,
        name="Lightning Azimuth",
        icon="mdi:compass-outline",
        native_unit_of_measurement=DEGREE,
        entity_class=AzimuthSensor,
    ),
    BlitzortungSensorEntityDescription(
        key=ATTR_LIGHTNING_DISTANCE,
        name="Lightning Distance",
        icon="mdi:map-marker-distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_class=DistanceSensor,
    ),
    BlitzortungSensorEntityDescription(
        key=ATTR_LIGHTNING_COUNTER,
        name="Lightning Counter",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_class=CounterSensor,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BlitzortungConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Blitzortung sensor platform from a config entry."""
    coordinator = config_entry.runtime_data
    config = hass.data[BLITZORTUNG_CONFIG]

    # This block of code can be removed in some time. For now it has to stay to clean up
    # user registry after https://github.com/mrk-its/homeassistant-blitzortung/pull/128
    entity_reg = er.async_get(hass)
    if entities := er.async_entries_for_config_entry(entity_reg, config_entry.entry_id):
        for entity in entities:
            if entity.entity_id.startswith(SENSOR_PLATFORM):
                continue
            entity_reg.async_remove(entity.entity_id)

    integration_name = config_entry.title
    unique_prefix = config_entry.entry_id

    sensors: list[BlitzortungSensor] = [
        sensor.entity_class(
            coordinator=coordinator,
            description=sensor,
            integration_name=integration_name,
            unique_prefix=unique_prefix,
        )
        for sensor in SENSORS
    ]

    if config.get(SERVER_STATS):
        device_reg = dr.async_get(hass)
        device_reg.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            identifiers={(DOMAIN, unique_prefix)},
            name=integration_name,
            manufacturer="Blitzortung",
            model="Blitzortung Lightning Detector",
            sw_version=SW_VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    sensors.extend(
        ServerStatSensor(
            topic=topic,
            coordinator=coordinator,
            description=BlitzortungSensorEntityDescription(
                key=(
                    f"server_"
                    f"{topic.removeprefix('$SYS/broker/').replace('/', '_')}"
                ),
                name=UNDEFINED,
                entity_category=EntityCategory.DIAGNOSTIC,
                icon="mdi:server",
                entity_class=ServerStatSensor,
            ),
            integration_name=integration_name,
            unique_prefix=unique_prefix,
        )
        for topic in (
            "$SYS/broker/clients/connected",
            "$SYS/broker/load/bytes/received/1min",
            "$SYS/broker/load/bytes/sent/1min",
            "$SYS/broker/load/messages/received/1min",
            "$SYS/broker/load/messages/sent/1min",
            "$SYS/broker/load/publish/received/1min",
            "$SYS/broker/load/publish/sent/1min",
            "$SYS/broker/uptime",
            "$SYS/broker/version",
        )
    )
    def on_sys_message(message: Message) -> None:
        for s in sensors:
            if isinstance(s, ServerStatSensor):
                s.on_message(message.topic, message)

    coordinator.register_message_receiver(on_sys_message)

    async_add_entities(sensors)
