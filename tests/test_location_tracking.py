"""Tests for tracker-based location updates."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE, STATE_HOME
from homeassistant.core import HomeAssistant

from custom_components.blitzortung.__init__ import BlitzortungCoordinator
from custom_components.blitzortung.const import MIN_LOCATION_CHANGE_METERS


@pytest.mark.asyncio
async def test_handle_tracker_entity_change_triggers_refresh(
    hass: HomeAssistant, mock_tracker_entity: str
) -> None:
    """A significant tracker update should refresh geohash subscriptions."""
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=None,
        longitude=None,
        tracker_entity=mock_tracker_entity,
        radius=100,
        max_tracked_lightnings=100,
        time_window_seconds=600,
        server_stats=False,
    )

    coordinator.sensors = [MagicMock(async_write_ha_state=MagicMock())]
    coordinator._async_refresh_geohash_subscriptions = AsyncMock()

    hass.states.async_set(
        mock_tracker_entity,
        STATE_HOME,
        attributes={ATTR_LATITUDE: 51.0, ATTR_LONGITUDE: 10.0},
    )
    await hass.async_block_till_done()

    coordinator._async_refresh_geohash_subscriptions.assert_awaited_once()
    coordinator.sensors[0].async_write_ha_state.assert_called_once()


async def test_apply_tracker_entity_state_ignores_jitter(
    hass: HomeAssistant, mock_tracker_entity: str
) -> None:
    """Movement below MIN_LOCATION_CHANGE_METERS should be ignored."""
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=None,
        longitude=None,
        tracker_entity=mock_tracker_entity,
        radius=100,
        max_tracked_lightnings=100,
        time_window_seconds=600,
        server_stats=False,
    )

    # Move by a tiny amount that is effectively "jitter".
    hass.states.async_set(
        mock_tracker_entity,
        STATE_HOME,
        attributes={
            ATTR_LATITUDE: 50.0,
            ATTR_LONGITUDE: 10.0 + (MIN_LOCATION_CHANGE_METERS / 1_000_000),
        },
    )
    await hass.async_block_till_done()

    assert coordinator.latitude == 50.0
    assert coordinator.longitude == 10.0


async def test_apply_tracker_entity_state_handles_missing_state(
    hass: HomeAssistant, mock_tracker_entity: str
) -> None:
    """Missing/invalid states should be handled gracefully."""
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=None,
        longitude=None,
        tracker_entity=mock_tracker_entity,
        radius=100,
        max_tracked_lightnings=100,
        time_window_seconds=600,
        server_stats=False,
    )

    hass.states.async_set(mock_tracker_entity, STATE_HOME)
    await hass.async_block_till_done()

    assert coordinator.latitude == 50.0
    assert coordinator.longitude == 10.0
