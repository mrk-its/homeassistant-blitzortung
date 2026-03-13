"""Configuration for pytest."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blitzortung.const import (
    CONF_CONFIG_TYPE,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    CONF_TRACKER_ENTITY,
    CONFIG_TYPE_COORDINATES,
    CONFIG_TYPE_TRACKER,
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
def mock_config_entry_tracker(hass: HomeAssistant) -> MockConfigEntry:
    """Mock config entry for tracker entity."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test phone",
            CONF_CONFIG_TYPE: CONFIG_TYPE_TRACKER,
            CONF_TRACKER_ENTITY: "device_tracker.test_phone",
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


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: bool) -> None:
    """Enable custom integrations."""
