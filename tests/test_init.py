"""Tests for the Blitzortung __init__.py module."""

from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blitzortung import BlitzortungCoordinator, async_migrate_entry
from custom_components.blitzortung.const import (
    ATTR_LIGHTNING_AZIMUTH,
    ATTR_LIGHTNING_DISTANCE,
    CONF_CONFIG_TYPE,
    CONF_LOCATION_ENTITY,
    CONFIG_TYPE_COORDINATES,
    CONFIG_TYPE_TRACKER,
)


async def test_async_setup_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_mqtt: MagicMock
) -> None:
    """Test async_setup_entry."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED


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
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=0.0,
        longitude=0.0,
        location_entity=None,
        radius=100,
        max_tracked_lightnings=500,
        time_window_seconds=600,
        server_stats=False,
    )
    lightning = {"lat": lightning_lat, "lon": lightning_lon}
    coordinator.compute_polar_coords(lightning)
    assert lightning[ATTR_LIGHTNING_DISTANCE] == expected_distance
    assert lightning[ATTR_LIGHTNING_AZIMUTH] == expected_azimuth


@pytest.mark.asyncio
async def test_migrate_entry_v5_to_v6_tracker(hass: HomeAssistant) -> None:
    """Migrate v5 entry with location_entity to v6 tracker mode."""
    entry = MockConfigEntry(
        domain="blitzortung",
        data={
            CONF_NAME: "Test",
            CONF_LOCATION_ENTITY: "device_tracker.boat",
        },
        version=5,
        unique_id="50.0-10.0",
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == 6
    assert entry.data == {
        CONF_NAME: "Test",
        CONF_CONFIG_TYPE: CONFIG_TYPE_TRACKER,
        CONF_LOCATION_ENTITY: "device_tracker.boat",
    }


@pytest.mark.asyncio
async def test_migrate_entry_v5_to_v6_coordinates(hass: HomeAssistant) -> None:
    """Migrate v5 entry without location_entity to v6 coordinates mode."""
    entry = MockConfigEntry(
        domain="blitzortung",
        data={
            CONF_NAME: "Test",
            CONF_LATITUDE: 52.1,
            CONF_LONGITUDE: 4.3,
        },
        version=5,
        unique_id="52.1-4.3",
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == 6
    assert entry.data == {
        CONF_NAME: "Test",
        CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        CONF_LATITUDE: 52.1,
        CONF_LONGITUDE: 4.3,
    }


@pytest.mark.asyncio
async def test_migrate_entry_v5_to_v6_coordinates_defaults(hass: HomeAssistant) -> None:
    """Migrate v5 entry without coords defaults to hass config values."""
    entry = MockConfigEntry(
        domain="blitzortung",
        data={CONF_NAME: "Test"},
        version=5,
        unique_id="defaults",
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == 6
    assert entry.data == {
        CONF_NAME: "Test",
        CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        CONF_LATITUDE: hass.config.latitude,
        CONF_LONGITUDE: hass.config.longitude,
    }
