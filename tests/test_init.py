"""Tests for the Blitzortung __init__.py module."""

from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blitzortung import BlitzortungCoordinator
from custom_components.blitzortung.const import (
    ATTR_LIGHTNING_AZIMUTH,
    ATTR_LIGHTNING_DISTANCE,
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
