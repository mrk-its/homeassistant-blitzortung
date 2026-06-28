"""Tests for the Blitzortung __init__.py module."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

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
from homeassistant.helpers import issue_registry as ir
from homeassistant.util.unit_system import IMPERIAL_SYSTEM
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
    RADIUS_MAX,
)
from custom_components.blitzortung.mqtt import Message


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


async def test_async_setup_entry_location_entity(
    hass: HomeAssistant,
    mock_config_entry_location_entity: MockConfigEntry,
    mock_location_entity: str,
    mock_mqtt: MagicMock,
) -> None:
    """Test async_setup_entry for location entity entry."""
    await hass.config_entries.async_setup(mock_config_entry_location_entity.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_location_entity.state is ConfigEntryState.LOADED


async def test_async_setup_entry_not_ready_location_entity_no_coordinates(
    hass: HomeAssistant,
    mock_config_entry_location_entity: MockConfigEntry,
    mock_location_entity: str,
    mock_mqtt: MagicMock,
) -> None:
    """Test ConfigEntryNotReady is raised when location entity has no coordinates."""
    hass.states.async_set(mock_location_entity, STATE_HOME)
    await hass.config_entries.async_setup(mock_config_entry_location_entity.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_location_entity.state is ConfigEntryState.SETUP_RETRY


async def test_async_setup_entry_not_ready_location_entity_mqtt_fails(
    hass: HomeAssistant,
    mock_config_entry_location_entity: MockConfigEntry,
    mock_location_entity: str,
    mock_mqtt: MagicMock,
) -> None:
    """Test ConfigEntryNotReady is raised when MQTT connection fails."""
    mock_mqtt.return_value.async_connect.side_effect = HomeAssistantError("test error")
    await hass.config_entries.async_setup(mock_config_entry_location_entity.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_location_entity.state is ConfigEntryState.SETUP_RETRY


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
async def test_handle_location_entity_change_triggers_refresh(
    hass: HomeAssistant, mock_location_entity: str
) -> None:
    """A significant tracker update should refresh geohash subscriptions."""
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=None,
        longitude=None,
        location_entity=mock_location_entity,
        radius=100,
        max_tracked_lightnings=100,
        time_window_seconds=600,
        server_stats=False,
    )

    coordinator.sensors = [MagicMock(async_write_ha_state=MagicMock())]
    coordinator._async_refresh_geohash_subscriptions = AsyncMock()

    hass.states.async_set(
        mock_location_entity,
        STATE_HOME,
        attributes={ATTR_LATITUDE: 51.0, ATTR_LONGITUDE: 10.0},
    )
    await hass.async_block_till_done()

    coordinator._async_refresh_geohash_subscriptions.assert_awaited_once()
    coordinator.sensors[0].async_write_ha_state.assert_called_once()


async def test_apply_location_entity_state_ignores_jitter(
    hass: HomeAssistant, mock_location_entity: str
) -> None:
    """Movement below the minimum location change should be ignored."""
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=None,
        longitude=None,
        location_entity=mock_location_entity,
        radius=100,
        max_tracked_lightnings=100,
        time_window_seconds=600,
        server_stats=False,
    )

    # Move by a tiny amount that is effectively "jitter".
    hass.states.async_set(
        mock_location_entity,
        STATE_HOME,
        attributes={
            ATTR_LATITUDE: 50.0,
            ATTR_LONGITUDE: 10.0 + (coordinator.min_location_change / 1_000_000),
        },
    )
    await hass.async_block_till_done()

    assert coordinator.latitude == 50.0
    assert coordinator.longitude == 10.0


async def test_apply_location_entity_state_handles_missing_state(
    hass: HomeAssistant, mock_location_entity: str
) -> None:
    """Missing/invalid states should be handled gracefully."""
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=None,
        longitude=None,
        location_entity=mock_location_entity,
        radius=100,
        max_tracked_lightnings=100,
        time_window_seconds=600,
        server_stats=False,
    )

    hass.states.async_set(mock_location_entity, STATE_HOME)
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
        location_entity=None,
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


async def test_async_setup_entry_imperial_system(
    hass: HomeAssistant,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """Test that radius is converted from miles to km for imperial systems."""
    hass.config.units = IMPERIAL_SYSTEM

    await hass.config_entries.async_setup(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_coordinates.state is ConfigEntryState.LOADED
    coordinator = mock_config_entry_coordinates.runtime_data
    # 100 miles ≈ 160.9 km
    assert coordinator.radius > 150


async def test_async_update_options_reloads_entry(
    hass: HomeAssistant,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """Test that updating options triggers a reload."""
    await hass.config_entries.async_setup(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry_coordinates.state is ConfigEntryState.LOADED

    # Trigger option update to fire async_update_options
    hass.config_entries.async_update_entry(
        mock_config_entry_coordinates,
        options={
            CONF_RADIUS: 200,
            CONF_MAX_TRACKED_LIGHTNINGS: 500,
            CONF_TIME_WINDOW: 10,
        },
    )
    await hass.async_block_till_done()

    # Entry should still be loaded after reload
    assert mock_config_entry_coordinates.state is ConfigEntryState.LOADED


async def test_async_unload_entry(
    hass: HomeAssistant,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """Test unloading a config entry."""
    await hass.config_entries.async_setup(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry_coordinates.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_coordinates.state is ConfigEntryState.NOT_LOADED


def test_on_connection_change_updates_sensors(
    hass: HomeAssistant,
) -> None:
    """Test that connection change triggers sensor state update."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    sensor = MagicMock()
    coordinator.sensors.append(sensor)

    coordinator._on_connection_change()

    sensor.async_write_ha_state.assert_called_once()


def test_on_connection_change_skipped_when_unloading(
    hass: HomeAssistant,
) -> None:
    """Test that connection change is ignored when unloading."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    coordinator.unloading = True
    sensor = MagicMock()
    coordinator.sensors.append(sensor)

    coordinator._on_connection_change()

    sensor.async_write_ha_state.assert_not_called()


async def test_handle_location_entity_change_skipped_when_unloading(
    hass: HomeAssistant,
    mock_location_entity: str,
) -> None:
    """Test that tracker entity changes are ignored when unloading."""
    coordinator = BlitzortungCoordinator(
        hass, None, None, mock_location_entity, 100, 100, 600, False
    )
    coordinator.unloading = True
    coordinator._async_refresh_geohash_subscriptions = AsyncMock()

    hass.states.async_set(
        mock_location_entity,
        STATE_HOME,
        attributes={ATTR_LATITUDE: 55.0, ATTR_LONGITUDE: 15.0},
    )
    await hass.async_block_till_done()

    coordinator._async_refresh_geohash_subscriptions.assert_not_awaited()


async def test_handle_location_entity_change_cancels_pending_refresh(
    hass: HomeAssistant,
    mock_location_entity: str,
) -> None:
    """Test that a pending refresh task is cancelled on rapid location changes."""
    coordinator = BlitzortungCoordinator(
        hass, None, None, mock_location_entity, 100, 100, 600, False
    )
    coordinator._async_refresh_geohash_subscriptions = AsyncMock()

    # Create a non-done pending task mock
    pending_task = MagicMock()
    pending_task.done.return_value = False
    coordinator._pending_refresh_task = pending_task

    hass.states.async_set(
        mock_location_entity,
        STATE_HOME,
        attributes={ATTR_LATITUDE: 55.0, ATTR_LONGITUDE: 15.0},
    )
    await hass.async_block_till_done()

    pending_task.cancel.assert_called_once()


async def test_refresh_geohash_subscriptions_no_coords(
    hass: HomeAssistant,
) -> None:
    """Test that refresh is a no-op when coordinates are None."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    coordinator.latitude = None
    coordinator.longitude = None

    # Should return without doing anything
    await coordinator._async_refresh_geohash_subscriptions()


async def test_refresh_geohash_subscriptions_same_geohash(
    hass: HomeAssistant,
) -> None:
    """Test that no subscriptions change when geohash overlap is unchanged."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    coordinator.mqtt_client = MagicMock(connected=True, async_subscribe=AsyncMock())

    # Calling with unchanged coords should be a no-op
    await coordinator._async_refresh_geohash_subscriptions()

    coordinator.mqtt_client.async_subscribe.assert_not_awaited()


async def test_refresh_geohash_subscriptions_unsub_exception(
    hass: HomeAssistant,
) -> None:
    """Test that exceptions during unsubscribe are caught gracefully."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)

    bad_unsub = MagicMock(side_effect=RuntimeError("already removed"))
    coordinator._geohash_unsubscribers = [bad_unsub]

    coordinator.mqtt_client = MagicMock(
        connected=True,
        async_subscribe=AsyncMock(return_value=MagicMock()),
    )

    # Move far enough to change geohash
    coordinator.latitude = 55.0
    await coordinator._async_refresh_geohash_subscriptions()

    # The bad unsub was called (and the exception was swallowed)
    bad_unsub.assert_called_once()
    assert coordinator.mqtt_client.async_subscribe.await_count > 0


async def test_connect_with_server_stats(
    hass: HomeAssistant,
) -> None:
    """Test that server_stats=True subscribes to $SYS/broker/#."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, True)
    coordinator.mqtt_client = MagicMock(
        async_connect=AsyncMock(),
        async_subscribe=AsyncMock(return_value=MagicMock()),
        async_disconnect=AsyncMock(),
    )

    await coordinator.connect()

    topics = [
        call.args[0] for call in coordinator.mqtt_client.async_subscribe.call_args_list
    ]
    assert any("$SYS/broker/#" in t for t in topics)

    await coordinator.disconnect()


async def test_disconnect_cancels_pending_refresh(
    hass: HomeAssistant,
) -> None:
    """Test that disconnect cancels pending refresh task."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    coordinator.mqtt_client = MagicMock(
        async_connect=AsyncMock(),
        async_subscribe=AsyncMock(return_value=MagicMock()),
        async_disconnect=AsyncMock(),
    )
    await coordinator.connect()

    pending_task = MagicMock()
    pending_task.done.return_value = False
    coordinator._pending_refresh_task = pending_task

    await coordinator.disconnect()

    pending_task.cancel.assert_called_once()
    assert coordinator._pending_refresh_task is None


def test_on_hello_message_new_version_available(
    hass: HomeAssistant,
) -> None:
    """Test that a hello message with newer version triggers notification."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)

    payload = json.dumps({"latest_version": "99.0.0"})
    message = Message(
        topic="component/hello",
        payload=payload,
        qos=0,
        retain=False,
    )

    with patch(
        "custom_components.blitzortung.async_create_notification"
    ) as mock_notify:
        coordinator.on_hello_message(message)
        mock_notify.assert_called_once()
        assert "99.0.0" in mock_notify.call_args.kwargs.get(
            "message", mock_notify.call_args[1].get("message", "")
        )


def test_on_hello_message_same_version(
    hass: HomeAssistant,
) -> None:
    """Test that a hello message with same/older version does not notify."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)

    payload = json.dumps({"latest_version": "0.0.0"})
    message = Message(
        topic="component/hello",
        payload=payload,
        qos=0,
        retain=False,
    )

    with patch(
        "custom_components.blitzortung.async_create_notification"
    ) as mock_notify:
        coordinator.on_hello_message(message)
        mock_notify.assert_not_called()


def test_on_hello_message_custom_message_and_title(
    hass: HomeAssistant,
) -> None:
    """Test that custom message and title from hello payload are used."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)

    payload = json.dumps(
        {
            "latest_version": "99.0.0",
            "latest_version_message": "Custom update message",
            "latest_version_title": "Custom Title",
        }
    )
    message = Message(
        topic="component/hello",
        payload=payload,
        qos=0,
        retain=False,
    )

    with patch(
        "custom_components.blitzortung.async_create_notification"
    ) as mock_notify:
        coordinator.on_hello_message(message)
        mock_notify.assert_called_once_with(
            title="Custom Title",
            message="Custom update message",
            notification_id="blitzortung_new_version_available",
        )


async def test_on_mqtt_message_lightning_within_radius(
    hass: HomeAssistant,
) -> None:
    """Test that a lightning strike within radius triggers callbacks and sensors."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)

    sensor = MagicMock()
    coordinator.sensors.append(sensor)

    lightning_cb = AsyncMock()
    coordinator.lightning_callbacks.append(lightning_cb)

    message_cb = MagicMock()
    coordinator.callbacks.append(message_cb)

    payload = json.dumps({"lat": 50.01, "lon": 10.01})
    message = Message(
        topic="blitzortung/1.1/u/3/3/#",
        payload=payload,
        qos=0,
        retain=False,
    )

    await coordinator.on_mqtt_message(message)

    message_cb.assert_called_once_with(message)
    lightning_cb.assert_awaited_once()
    sensor.update_lightning.assert_called_once()


async def test_on_mqtt_message_lightning_outside_radius(
    hass: HomeAssistant,
) -> None:
    """Test if a lightning strike outside radius doesn't trigger lightning callbacks."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)

    lightning_cb = AsyncMock()
    coordinator.lightning_callbacks.append(lightning_cb)

    # Very far away
    payload = json.dumps({"lat": 0.0, "lon": 0.0})
    message = Message(
        topic="blitzortung/1.1/s/0/0/#",
        payload=payload,
        qos=0,
        retain=False,
    )

    await coordinator.on_mqtt_message(message)

    lightning_cb.assert_not_awaited()


async def test_on_mqtt_message_non_lightning_topic(
    hass: HomeAssistant,
) -> None:
    """Test that non-lightning messages call callbacks but skip lightning logic."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)

    message_cb = MagicMock()
    coordinator.callbacks.append(message_cb)

    message = Message(
        topic="$SYS/broker/clients/connected",
        payload="5",
        qos=0,
        retain=False,
    )

    await coordinator.on_mqtt_message(message)

    message_cb.assert_called_once_with(message)


def test_register_sensor(hass: HomeAssistant) -> None:
    """Test that register_sensor adds sensor and registers tick."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    sensor = MagicMock()
    sensor.tick = MagicMock()

    coordinator.register_sensor(sensor)

    assert sensor in coordinator.sensors
    assert sensor.tick in coordinator.on_tick_callbacks


def test_is_inactive_when_no_lightning(hass: HomeAssistant) -> None:
    """Test is_inactive returns True when time window has passed."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    coordinator.last_time = time.time() - 700  # older than 600s window

    assert coordinator.is_inactive is True


def test_is_inactive_when_recent_lightning(hass: HomeAssistant) -> None:
    """Test is_inactive returns False when lightning was recent."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    coordinator.last_time = time.time()

    assert coordinator.is_inactive is False


async def test_tick_calls_registered_callbacks(hass: HomeAssistant) -> None:
    """Test that _tick calls all registered on_tick callbacks."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    cb1 = MagicMock()
    cb2 = MagicMock()
    coordinator.on_tick_callbacks.extend([cb1, cb2])

    await coordinator._tick()

    cb1.assert_called_once()
    cb2.assert_called_once()


async def test_max_tracked_lightnings_warning(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test warning logged and issue created when max_tracked_lightnings > 500."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        },
        unique_id="50.0-10.0-warn",
        version=6,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: 600,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)

    with patch("custom_components.blitzortung._LOGGER") as mock_logger:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    mock_logger.warning.assert_called()

    issue_id = f"max_tracked_lightnings_warning_{entry.entry_id}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.severity == "warning"
    assert issue.is_fixable
    assert issue.translation_key == "max_tracked_lightnings_warning"
    assert issue.translation_placeholders == {"max_tracked_lightnings": "600"}


async def test_max_tracked_lightnings_below_threshold_no_issue(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test no repair issue is created when max_tracked_lightnings <= 500."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        },
        unique_id="50.0-10.0-safe",
        version=6,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: 400,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    issue_id = f"max_tracked_lightnings_warning_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_max_tracked_lightnings_issue_deleted_on_unload(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test repair issue is deleted when config entry is unloaded."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        },
        unique_id="50.0-10.0-unload",
        version=6,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: 600,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"max_tracked_lightnings_warning_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_max_tracked_lightnings_issue_deleted_when_options_reduced(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test repair issue is deleted when options are updated to below threshold."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        },
        unique_id="50.0-10.0-reduce",
        version=6,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: 600,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"max_tracked_lightnings_warning_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: 400,
            CONF_TIME_WINDOW: 10,
        },
    )
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


def test_apply_location_entity_state_with_none_state(
    hass: HomeAssistant,
) -> None:
    """Test _apply_location_entity_state returns False when state is None."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    coordinator.location_entity = "device_tracker.nonexistent"

    result = coordinator._apply_location_entity_state(None)

    assert result is False


def test_coordinator_init_tracker_no_state(
    hass: HomeAssistant,
) -> None:
    """Test coordinator init with tracker entity that has no state."""
    coordinator = BlitzortungCoordinator(
        hass,
        latitude=None,
        longitude=None,
        location_entity="device_tracker.missing",
        radius=100,
        max_tracked_lightnings=100,
        time_window_seconds=600,
        server_stats=False,
    )

    assert coordinator.latitude is None
    assert coordinator.longitude is None
    assert coordinator.geohash_overlap == set()


async def test_refresh_geohash_subscriptions_disconnected(
    hass: HomeAssistant,
) -> None:
    """Test that refresh skips MQTT re-subscribe when disconnected."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    coordinator.mqtt_client = MagicMock(
        connected=False,
        async_subscribe=AsyncMock(),
    )

    # Move far enough to change geohash overlap
    coordinator.latitude = 55.0
    await coordinator._async_refresh_geohash_subscriptions()

    # Geohash overlap should update but no MQTT subscriptions
    coordinator.mqtt_client.async_subscribe.assert_not_awaited()


def test_register_message_receiver(hass: HomeAssistant) -> None:
    """Test that register_message_receiver adds a callback."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    cb = MagicMock()
    coordinator.register_message_receiver(cb)

    assert cb in coordinator.callbacks


async def test_radius_max_warning(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test issue created when radius > RADIUS_MAX."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        },
        unique_id="50.0-10.0-radius-warn",
        version=6,
        options={
            CONF_RADIUS: RADIUS_MAX + 1000,
            CONF_MAX_TRACKED_LIGHTNINGS: 100,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    issue_id = f"radius_max_warning_{entry.entry_id}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.severity == "warning"
    assert issue.is_fixable
    assert issue.translation_key == "radius_max_warning"
    assert issue.translation_placeholders == {
        "radius": str(RADIUS_MAX + 1000),
        "radius_max": str(RADIUS_MAX),
    }


async def test_radius_below_max_no_issue(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test no repair issue is created when radius <= RADIUS_MAX."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        },
        unique_id="50.0-10.0-radius-safe",
        version=6,
        options={
            CONF_RADIUS: RADIUS_MAX,
            CONF_MAX_TRACKED_LIGHTNINGS: 100,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    issue_id = f"radius_max_warning_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_radius_issue_deleted_on_unload(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test repair issue is deleted when config entry is unloaded."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        },
        unique_id="50.0-10.0-radius-unload",
        version=6,
        options={
            CONF_RADIUS: RADIUS_MAX + 1000,
            CONF_MAX_TRACKED_LIGHTNINGS: 100,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"radius_max_warning_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_radius_issue_deleted_when_options_reduced(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test repair issue is deleted when radius options are reduced."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        },
        unique_id="50.0-10.0-radius-reduce",
        version=6,
        options={
            CONF_RADIUS: RADIUS_MAX + 1000,
            CONF_MAX_TRACKED_LIGHTNINGS: 100,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"radius_max_warning_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_RADIUS: RADIUS_MAX,
            CONF_MAX_TRACKED_LIGHTNINGS: 100,
            CONF_TIME_WINDOW: 10,
        },
    )
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
