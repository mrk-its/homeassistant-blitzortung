"""Configuration for pytest."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.device_tracker import DOMAIN as DEVICE_TRACKER_DOMAIN
from homeassistant.const import (
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
    STATE_HOME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blitzortung.const import (
    CONF_CONFIG_TYPE,
    CONF_LOCATION_ENTITY,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    CONFIG_TYPE_COORDINATES,
    CONFIG_TYPE_ENTITY,
    DOMAIN,
)


@pytest.fixture
def mock_config_entry_coordinates(hass: HomeAssistant) -> MockConfigEntry:
    """Mock config entry for coordinates."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        },
        unique_id="50.0-10.0",
        version=6,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: 500,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)

    return entry


@pytest.fixture
def mock_config_entry_location_entity(hass: HomeAssistant) -> MockConfigEntry:
    """Mock config entry for location entity."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test phone",
            CONF_CONFIG_TYPE: CONFIG_TYPE_ENTITY,
            CONF_LOCATION_ENTITY: "device_tracker.test_phone",
        },
        unique_id="device_tracker_unique_1234",
        version=6,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: 500,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)

    return entry


@pytest.fixture
def mock_mqtt() -> Generator[MagicMock]:
    """Mock the Perplexity client."""
    with patch("custom_components.blitzortung.MQTT") as mock_mqtt_class:
        mock_mqtt = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt
        mock_mqtt.async_connect = AsyncMock()
        mock_mqtt.async_subscribe = AsyncMock()
        mock_mqtt.async_disconnect = AsyncMock()
        mock_mqtt.connected = True

        yield mock_mqtt_class


@pytest.fixture
def mock_location_entity(hass: HomeAssistant) -> str:
    """Mock a location entity."""
    entity_id = f"{DEVICE_TRACKER_DOMAIN}.test_phone"

    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        DEVICE_TRACKER_DOMAIN,
        DEVICE_TRACKER_DOMAIN,
        "unique_1234",
        suggested_object_id="test_phone",
        original_name="Test phone",
    )

    attrs = {ATTR_LATITUDE: 50.0, ATTR_LONGITUDE: 10.0}
    hass.states.async_set(entity_id, STATE_HOME, attrs)

    return entity_id


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: bool) -> None:
    """Enable custom integrations."""
