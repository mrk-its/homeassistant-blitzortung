"""Tests for the Blitzortung __init__.py module."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
    STATE_HOME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blitzortung import BlitzortungCoordinator
from custom_components.blitzortung.const import (
    ATTR_LIGHTNING_AZIMUTH,
    ATTR_LIGHTNING_DISTANCE,
    CONF_CONFIG_TYPE,
    CONF_IDLE_RESET_TIMEOUT,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    CONFIG_TYPE_COORDINATES,
    DEFAULT_IDLE_RESET_TIMEOUT,
    DEFAULT_MAX_TRACKED_LIGHTNINGS,
    DEFAULT_TIME_WINDOW,
    DOMAIN,
    MIN_LOCATION_CHANGE_METERS,
)


async def test_async_setup_entry_coordinates(
    hass: HomeAssistant,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """Test async_setup_entry for coordinates entry."""
    await hass.config_entries.async_setup(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_coordinates.state is ConfigEntryState.LOADED


@pytest.mark.parametrize(
    "error",
    [HomeAssistantError("test error"), OSError("connection refused")],
)
async def test_async_setup_entry_not_ready_coordinates(
    hass: HomeAssistant,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
    error: Exception,
) -> None:
    """Test ConfigEntryNotReady is raised when MQTT connection fails."""
    mock_mqtt.return_value.async_connect.side_effect = error

    await hass.config_entries.async_setup(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_coordinates.state is ConfigEntryState.SETUP_RETRY


async def test_async_setup_entry_tracker(
    hass: HomeAssistant,
    mock_config_entry_tracker: MockConfigEntry,
    mock_tracker_entity: str,
    mock_mqtt: MagicMock,
) -> None:
    """Test async_setup_entry for tracker entry."""
    await hass.config_entries.async_setup(mock_config_entry_tracker.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_tracker.state is ConfigEntryState.LOADED


async def test_async_setup_entry_not_ready_tracker_no_coordinates(
    hass: HomeAssistant,
    mock_config_entry_tracker: MockConfigEntry,
    mock_tracker_entity: str,
    mock_mqtt: MagicMock,
) -> None:
    """Test ConfigEntryNotReady is raised when tracker entity has no coordinates."""
    hass.states.async_set(mock_tracker_entity, STATE_HOME)
    await hass.config_entries.async_setup(mock_config_entry_tracker.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_tracker.state is ConfigEntryState.SETUP_RETRY


async def test_async_setup_entry_not_ready_tracker_mqtt_fails(
    hass: HomeAssistant,
    mock_config_entry_tracker: MockConfigEntry,
    mock_tracker_entity: str,
    mock_mqtt: MagicMock,
) -> None:
    """Test ConfigEntryNotReady is raised when MQTT connection fails."""
    mock_mqtt.return_value.async_connect.side_effect = HomeAssistantError("test error")
    await hass.config_entries.async_setup(mock_config_entry_tracker.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_tracker.state is ConfigEntryState.SETUP_RETRY


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
    coordinator = BlitzortungCoordinator(hass, 0.0, 0.0, None, 100, 500, 600, False)
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
    assert config_entry.version == 6
    assert config_entry.data[CONF_CONFIG_TYPE] == CONFIG_TYPE_COORDINATES


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
    assert config_entry.version == 6
    assert config_entry.data[CONF_CONFIG_TYPE] == CONFIG_TYPE_COORDINATES

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
    assert config_entry.version == 6
    assert config_entry.data[CONF_CONFIG_TYPE] == CONFIG_TYPE_COORDINATES

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
    assert config_entry.version == 6
    assert config_entry.data[CONF_CONFIG_TYPE] == CONFIG_TYPE_COORDINATES

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


@pytest.mark.asyncio
async def test_refresh_geohash_subscriptions_when_moved(
    hass: HomeAssistant,
) -> None:
    """When overlap changes and connected, MQTT subscriptions are refreshed."""
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=50.0,
        longitude=10.0,
        tracker_entity=None,
        radius=100,
        max_tracked_lightnings=100,
        time_window_seconds=600,
        server_stats=False,
    )

    unsub_1 = MagicMock()
    coordinator._geohash_unsubscribers = [unsub_1]

    async_subscribe = AsyncMock(return_value=MagicMock())
    coordinator.mqtt_client = MagicMock(
        connected=True,
        async_subscribe=async_subscribe,
    )

    # Move far enough to almost certainly change geohash overlap.
    coordinator.latitude = 52.0
    await coordinator._async_refresh_geohash_subscriptions()

    unsub_1.assert_called_once()
    assert async_subscribe.await_count > 0
