"""Tests for tracker-based location updates."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant, State

from custom_components.blitzortung.__init__ import BlitzortungCoordinator
from custom_components.blitzortung.const import MIN_LOCATION_CHANGE_METERS


@pytest.mark.asyncio
async def test_handle_location_entity_change_triggers_refresh(
    hass: HomeAssistant,
) -> None:
    """A significant tracker update should refresh geohash subscriptions."""
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=50.0,
        longitude=10.0,
        location_entity=None,
        radius=100,
        max_tracked_lightnings=100,
        time_window_seconds=600,
        server_stats=False,
    )

    coordinator.sensors = [MagicMock(async_write_ha_state=MagicMock())]
    coordinator._async_refresh_geohash_subscriptions = AsyncMock()  # noqa: SLF001

    new_state = State(
        "device_tracker.test",
        "home",
        attributes={"latitude": 51.0, "longitude": 10.0},
    )
    coordinator._handle_location_entity_change(  # noqa: SLF001
        SimpleNamespace(data={"new_state": new_state})
    )
    await hass.async_block_till_done()

    coordinator._async_refresh_geohash_subscriptions.assert_awaited_once()  # noqa: SLF001
    coordinator.sensors[0].async_write_ha_state.assert_called_once()


def test_apply_location_entity_state_ignores_jitter(hass: HomeAssistant) -> None:
    """Movement below MIN_LOCATION_CHANGE_METERS should be ignored."""
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=50.0,
        longitude=10.0,
        location_entity=None,
        radius=100,
        max_tracked_lightnings=100,
        time_window_seconds=600,
        server_stats=False,
    )

    # Move by a tiny amount that is effectively "jitter".
    jitter_state = State(
        "device_tracker.test",
        "home",
        attributes={
            "latitude": 50.0,
            "longitude": 10.0 + (MIN_LOCATION_CHANGE_METERS / 1_000_000),
        },
    )

    assert coordinator._apply_location_entity_state(jitter_state) is False  # noqa: SLF001
    assert coordinator.latitude == 50.0
    assert coordinator.longitude == 10.0


def test_apply_location_entity_state_handles_missing_state(
    hass: HomeAssistant,
) -> None:
    """Missing/invalid states should be handled gracefully."""
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=50.0,
        longitude=10.0,
        location_entity=None,
        radius=100,
        max_tracked_lightnings=100,
        time_window_seconds=600,
        server_stats=False,
    )

    assert coordinator._apply_location_entity_state(None) is False  # noqa: SLF001

    no_attrs = State("device_tracker.test", "home", attributes={})
    assert coordinator._apply_location_entity_state(no_attrs) is False  # noqa: SLF001


@pytest.mark.asyncio
async def test_refresh_geohash_subscriptions_when_moved(
    hass: HomeAssistant,
) -> None:
    """When overlap changes and connected, MQTT subscriptions are refreshed."""
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=50.0,
        longitude=10.0,
        location_entity=None,
        radius=100,
        max_tracked_lightnings=100,
        time_window_seconds=600,
        server_stats=False,
    )

    unsub_1 = MagicMock()
    coordinator._geohash_unsubscribers = [unsub_1]  # noqa: SLF001

    async_subscribe = AsyncMock(return_value=MagicMock())
    coordinator.mqtt_client = SimpleNamespace(
        connected=True,
        async_subscribe=async_subscribe,
    )

    # Move far enough to almost certainly change geohash overlap.
    coordinator.latitude = 52.0
    await coordinator._async_refresh_geohash_subscriptions()  # noqa: SLF001

    unsub_1.assert_called_once()
    assert async_subscribe.await_count > 0
