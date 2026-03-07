"""Tests for the Blitzortung __init__.py module."""

from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blitzortung import BlitzortungCoordinator
from custom_components.blitzortung.const import (
    ATTR_LIGHTNING_AZIMUTH,
    ATTR_LIGHTNING_DISTANCE,
    CONF_IDLE_RESET_TIMEOUT,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    DEFAULT_IDLE_RESET_TIMEOUT,
    DEFAULT_MAX_TRACKED_LIGHTNINGS,
    DEFAULT_TIME_WINDOW,
    DOMAIN,
)


async def test_async_setup_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_mqtt: MagicMock
) -> None:
    """Test async_setup_entry."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED


@pytest.mark.parametrize(
    "error",
    [HomeAssistantError("test error"), OSError("connection refused")],
)
async def test_async_setup_entry_not_ready(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_mqtt: MagicMock,
    error: Exception,
) -> None:
    """Test ConfigEntryNotReady is raised when MQTT connection fails."""
    mock_mqtt.return_value.async_connect.side_effect = error

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize(
    ("lightning_lat", "lightning_lon", "expected_distance", "expected_azimuth"),
    [
        (0.0, 0.0, 0.0, 0),
        (1.0, 0.0, 111.2, 0),
        (0.0, 1.0, 111.2, 90),
        (-1.0, 0.0, 111.2, 180),
        (0.0, -1.0, 111.2, 270),
    ],
)
def test_compute_polar_coords(
    lightning_lat: float,
    lightning_lon: float,
    expected_distance: float,
    expected_azimuth: int,
) -> None:
    """Test compute_polar_coords with various lightning locations."""
    hass = MagicMock()
    coordinator = BlitzortungCoordinator(hass, 0.0, 0.0, 100, 500, 600, 60, False)
    lightning = {"lat": lightning_lat, "lon": lightning_lon}
    coordinator.compute_polar_coords(lightning)
    assert lightning[ATTR_LIGHTNING_DISTANCE] == expected_distance
    assert lightning[ATTR_LIGHTNING_AZIMUTH] == expected_azimuth


async def test_migrate_entry_v1_unique_id(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test that migrating from v1 generates the correct unique_id."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_RADIUS: 100,
        },
        options={},
        unique_id="v1-unique-id",
        version=1,
    )
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.unique_id == "50.0-10.0"
    assert config_entry.version == 5


async def test_migrate_entry_v2_adds_idle_reset_timeout(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test that migrating from v2 adds idle_reset_timeout with default value."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NAME: "Test Location"},
        options={
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_RADIUS: 100,
        },
        unique_id="v2-unique-id",
        version=2,
    )
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.unique_id == "50.0-10.0"
    assert config_entry.version == 5

    # v2->v3 adds idle_reset_timeout with the default; later migrations rename it,
    # so by v5 the default value is exposed as time_window
    assert config_entry.options[CONF_TIME_WINDOW] == DEFAULT_IDLE_RESET_TIMEOUT
    assert (
        config_entry.options[CONF_MAX_TRACKED_LIGHTNINGS]
        == DEFAULT_MAX_TRACKED_LIGHTNINGS
    )


async def test_migrate_entry_v3_renames_idle_reset_to_time_window(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test that migrating from v3 renames idle_reset_timeout to time_window."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NAME: "Test Location"},
        options={
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_RADIUS: 100,
            CONF_IDLE_RESET_TIMEOUT: 45,
        },
        unique_id="v3-unique-id",
        version=3,
    )
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.unique_id == "50.0-10.0"
    assert config_entry.version == 5

    # idle_reset_timeout value should have been moved to time_window
    assert config_entry.options[CONF_TIME_WINDOW] == 45
    assert CONF_IDLE_RESET_TIMEOUT not in config_entry.options


async def test_migrate_entry_v4_uses_defaults_when_missing(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test that migrating from v4 uses hass config and defaults for missing values."""
    hass.config.latitude = 50.0
    hass.config.longitude = 10.0

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NAME: "Test Location"},
        options={},
        unique_id="v4-unique-id",
        version=4,
    )
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.unique_id == "50.0-10.0"
    assert config_entry.version == 5

    # Should fall back to hass.config values
    assert config_entry.data[CONF_LATITUDE] == 50.0
    assert config_entry.data[CONF_LONGITUDE] == 10.0

    # Should use defaults
    assert config_entry.options[CONF_RADIUS] == 100
    assert config_entry.options[CONF_TIME_WINDOW] == DEFAULT_TIME_WINDOW
    assert (
        config_entry.options[CONF_MAX_TRACKED_LIGHTNINGS]
        == DEFAULT_MAX_TRACKED_LIGHTNINGS
    )
