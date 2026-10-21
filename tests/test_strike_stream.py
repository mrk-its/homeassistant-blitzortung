"""Tests for the map area and the websocket strike stream."""

import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_dumps
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import IMPERIAL_SYSTEM
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.blitzortung import BlitzortungCoordinator
from custom_components.blitzortung.const import (
    CONF_MAP_CENTER,
    CONF_MAP_CENTER_OVERRIDE,
    CONF_MAP_RADIUS,
    CONF_TIME_WINDOW,
    STREAM_FLUSH_INTERVAL,
)
from custom_components.blitzortung.geohash_utils import geohash_overlap
from custom_components.blitzortung.mqtt import Message
from custom_components.blitzortung.websocket_api import STRIKE_STREAM

HOME = (50.0, 10.0)
TAMPA = (27.95, -82.46)


def _strike_message(lat: float, lon: float, time_ns: int | None = None) -> Message:
    """Build a strike message shaped like the proxy's JSON payload."""
    payload = {"lat": lat, "lon": lon, "status": 0, "region": 1}
    payload["time"] = time.time_ns() if time_ns is None else time_ns
    return Message(
        topic="blitzortung/1.1/u/0/x/#",
        payload=json_dumps(payload),
        qos=0,
        retain=False,
    )


def _coordinator(
    hass: HomeAssistant,
    map_radius: float = 0,
    map_center: tuple[float, float] | None = None,
) -> BlitzortungCoordinator:
    return BlitzortungCoordinator(
        hass,
        *HOME,
        None,
        100,
        100,
        600,
        False,
        map_radius=map_radius,
        map_center=map_center,
    )


def _no_nested_tiles(tiles: set[str]) -> bool:
    return not any(
        other != tile and tile.startswith(other) for tile in tiles for other in tiles
    )


def test_default_subscriptions_unchanged(hass: HomeAssistant) -> None:
    """Without a map area the MQTT subscriptions are the same as before."""
    coordinator = _coordinator(hass)

    assert coordinator.map_radius == 100
    assert coordinator.geohash_overlap == geohash_overlap(*HOME, 100)


def test_map_radius_adds_tiles_without_nesting(hass: HomeAssistant) -> None:
    """A wider map area adds coarser tiles and drops the tiles they contain."""
    coordinator = _coordinator(hass, map_radius=2000)

    tiles = coordinator.geohash_overlap
    assert tiles == geohash_overlap(*HOME, 2000)
    assert _no_nested_tiles(tiles)


def test_map_center_adds_tiles_for_both_areas(hass: HomeAssistant) -> None:
    """A custom map center is covered alongside the detection area."""
    coordinator = _coordinator(hass, map_radius=500, map_center=TAMPA)

    assert coordinator.geohash_overlap == geohash_overlap(*HOME, 100) | geohash_overlap(
        *TAMPA, 500
    )
    assert _no_nested_tiles(coordinator.geohash_overlap)


def test_map_center_without_entity_coordinates(hass: HomeAssistant) -> None:
    """A custom map area is subscribed before the location entity reports."""
    coordinator = BlitzortungCoordinator(
        hass,
        None,
        None,
        "device_tracker.missing",
        100,
        100,
        600,
        False,
        map_center=TAMPA,
    )

    assert coordinator.geohash_overlap == geohash_overlap(*TAMPA, 100)


async def test_strike_in_map_area_feeds_stream_only(hass: HomeAssistant) -> None:
    """A strike outside the radius but inside the map area skips sensors."""
    coordinator = _coordinator(hass, map_radius=2000)
    sensor = MagicMock()
    coordinator.sensors.append(sensor)
    lightning_cb = AsyncMock()
    coordinator.lightning_callbacks.append(lightning_cb)
    strike_cb = MagicMock()
    coordinator.register_strike_receiver(strike_cb)

    time_ns = time.time_ns()
    await coordinator.on_mqtt_message(_strike_message(45.0, 10.0, time_ns))

    sensor.update_lightning.assert_not_called()
    lightning_cb.assert_not_awaited()
    strike_cb.assert_called_once_with([45.0, 10.0, time_ns // 1_000_000])
    assert len(coordinator.strikes) == 1
    assert coordinator.last_time == 0


async def test_strike_in_radius_feeds_sensors_and_stream(hass: HomeAssistant) -> None:
    """A strike inside the detection radius also goes to map cards."""
    coordinator = _coordinator(hass)
    sensor = MagicMock()
    coordinator.sensors.append(sensor)
    strike_cb = MagicMock()
    coordinator.register_strike_receiver(strike_cb)

    await coordinator.on_mqtt_message(_strike_message(50.01, 10.01))

    sensor.update_lightning.assert_called_once()
    strike_cb.assert_called_once()
    assert len(coordinator.strikes) == 1


@pytest.mark.parametrize(
    ("map_radius", "map_center"), [(0, None), (2000, None), (500, TAMPA)]
)
async def test_strike_outside_both_areas_dropped(
    hass: HomeAssistant, map_radius: float, map_center: tuple[float, float] | None
) -> None:
    """A strike from a tile edge outside both areas reaches nothing."""
    coordinator = _coordinator(hass, map_radius=map_radius, map_center=map_center)
    strike_cb = MagicMock()
    coordinator.register_strike_receiver(strike_cb)

    await coordinator.on_mqtt_message(_strike_message(-30.0, 120.0))

    strike_cb.assert_not_called()
    assert len(coordinator.strikes) == 0


async def test_strike_at_custom_map_center(hass: HomeAssistant) -> None:
    """Distance to the map area uses the custom center, not home."""
    coordinator = _coordinator(hass, map_radius=500, map_center=TAMPA)

    await coordinator.on_mqtt_message(_strike_message(28.5, -81.4))

    assert len(coordinator.strikes) == 1


async def test_strike_with_no_entity_coordinates(hass: HomeAssistant) -> None:
    """Without home coordinates a map-area strike is still streamed."""
    coordinator = BlitzortungCoordinator(
        hass,
        None,
        None,
        "device_tracker.missing",
        100,
        100,
        600,
        False,
        map_center=TAMPA,
    )
    sensor = MagicMock()
    coordinator.sensors.append(sensor)

    await coordinator.on_mqtt_message(_strike_message(*TAMPA))

    sensor.update_lightning.assert_not_called()
    assert len(coordinator.strikes) == 1


async def test_wider_map_radius_waits_for_entity_coordinates(
    hass: HomeAssistant,
) -> None:
    """A map area centered on the entity has no center until it reports."""
    coordinator = BlitzortungCoordinator(
        hass,
        None,
        None,
        "device_tracker.missing",
        100,
        100,
        600,
        False,
        map_radius=2000,
    )

    await coordinator.on_mqtt_message(_strike_message(*HOME))

    assert coordinator.geohash_overlap == set()
    assert len(coordinator.strikes) == 0


async def test_repeated_strike_streamed_once(hass: HomeAssistant) -> None:
    """The proxy's repeat of a strike doesn't reach map cards twice."""
    coordinator = _coordinator(hass)
    strike_cb = MagicMock()
    coordinator.register_strike_receiver(strike_cb)
    time_ns = time.time_ns()

    await coordinator.on_mqtt_message(_strike_message(50.01, 10.01, time_ns))
    await coordinator.on_mqtt_message(_strike_message(50.01, 10.01, time_ns))

    strike_cb.assert_called_once()
    assert len(coordinator.strikes) == 1


async def test_strike_without_time_not_buffered(hass: HomeAssistant) -> None:
    """A payload without a strike time can't be aged, so it isn't streamed."""
    coordinator = _coordinator(hass)
    payload = json_dumps({"lat": 50.01, "lon": 10.01})

    await coordinator.on_mqtt_message(
        Message(topic="blitzortung/1.1/u/0/x/#", payload=payload, qos=0, retain=False)
    )

    assert len(coordinator.strikes) == 0


async def test_tick_expires_strikes(hass: HomeAssistant) -> None:
    """Strikes older than the time window are dropped on tick."""
    coordinator = _coordinator(hass)
    await coordinator.on_mqtt_message(
        _strike_message(50.01, 10.01, time.time_ns() - 601 * 10**9)
    )
    await coordinator.on_mqtt_message(_strike_message(50.01, 10.01))

    await coordinator._tick()

    assert len(coordinator.strikes) == 1


async def test_setup_reads_map_options(
    hass: HomeAssistant,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """Setup passes the map radius and custom center to the coordinator."""
    hass.config_entries.async_update_entry(
        mock_config_entry_coordinates,
        options={
            **mock_config_entry_coordinates.options,
            CONF_MAP_RADIUS: 1000,
            CONF_MAP_CENTER_OVERRIDE: True,
            CONF_MAP_CENTER: {CONF_LATITUDE: TAMPA[0], CONF_LONGITUDE: TAMPA[1]},
        },
    )

    await hass.config_entries.async_setup(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_coordinates.runtime_data
    assert coordinator.map_radius == 1000
    assert coordinator.map_center == TAMPA


async def test_setup_ignores_map_center_when_override_off(
    hass: HomeAssistant,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """A stored center is kept for the form but not used while switched off."""
    hass.config_entries.async_update_entry(
        mock_config_entry_coordinates,
        options={
            **mock_config_entry_coordinates.options,
            CONF_MAP_CENTER_OVERRIDE: False,
            CONF_MAP_CENTER: {CONF_LATITUDE: TAMPA[0], CONF_LONGITUDE: TAMPA[1]},
        },
    )

    await hass.config_entries.async_setup(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_coordinates.runtime_data.map_center is None


async def test_setup_converts_map_radius_for_imperial(
    hass: HomeAssistant,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """The map radius is in miles on imperial systems, like the radius."""
    hass.config.units = IMPERIAL_SYSTEM
    hass.config_entries.async_update_entry(
        mock_config_entry_coordinates,
        options={**mock_config_entry_coordinates.options, CONF_MAP_RADIUS: 1000},
    )

    await hass.config_entries.async_setup(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_coordinates.runtime_data.map_radius == pytest.approx(
        1609.344
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> BlitzortungCoordinator:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _flush(hass: HomeAssistant) -> None:
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=STREAM_FLUSH_INTERVAL + 0.1)
    )


async def test_ws_snapshot_then_batches(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """A subscriber gets the buffered strikes, then new strikes once per batch."""
    coordinator = await _setup(hass, mock_config_entry_coordinates)
    first_ns = time.time_ns()
    await coordinator.on_mqtt_message(_strike_message(50.01, 10.01, first_ns))
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "blitzortung/subscribe_strikes"})
    result = await client.receive_json(timeout=5)
    assert result["success"]
    snapshot = await client.receive_json(timeout=5)
    assert snapshot["event"] == {
        "time_window": 600,
        "strikes": [[50.01, 10.01, first_ns // 1_000_000]],
    }

    second_ns = time.time_ns()
    await coordinator.on_mqtt_message(_strike_message(50.02, 10.02, second_ns))
    await coordinator.on_mqtt_message(_strike_message(50.03, 10.03, second_ns + 1))
    _flush(hass)
    batch = await client.receive_json(timeout=5)
    assert batch["event"] == {
        "strikes": [
            [50.02, 10.02, second_ns // 1_000_000],
            [50.03, 10.03, (second_ns + 1) // 1_000_000],
        ]
    }


async def test_ws_streams_without_strike_entities(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """Map cards get strikes when no geo_location entities are created."""
    hass.config_entries.async_update_entry(
        mock_config_entry_coordinates,
        options={**mock_config_entry_coordinates.options, "max_tracked_lightnings": 0},
    )
    coordinator = await _setup(hass, mock_config_entry_coordinates)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "blitzortung/subscribe_strikes"})
    assert (await client.receive_json(timeout=5))["success"]
    await client.receive_json(timeout=5)

    time_ns = time.time_ns()
    await coordinator.on_mqtt_message(_strike_message(50.01, 10.01, time_ns))
    _flush(hass)

    assert (await client.receive_json(timeout=5))["event"] == {
        "strikes": [[50.01, 10.01, time_ns // 1_000_000]]
    }
    assert hass.states.async_entity_ids("geo_location") == []


async def test_ws_snapshot_when_empty(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """With nothing buffered the first event still carries the time window."""
    await _setup(hass, mock_config_entry_coordinates)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "blitzortung/subscribe_strikes"})
    assert (await client.receive_json(timeout=5))["success"]

    assert (await client.receive_json(timeout=5))["event"] == {
        "time_window": 600,
        "strikes": [],
    }


async def test_ws_snapshot_is_chunked(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """A long history is sent in several events; only the first has the window."""
    coordinator = await _setup(hass, mock_config_entry_coordinates)
    for i in range(5):
        await coordinator.on_mqtt_message(_strike_message(50.0 + i / 100, 10.0))
    client = await hass_ws_client(hass)

    with patch("custom_components.blitzortung.websocket_api.STREAM_SNAPSHOT_CHUNK", 2):
        await client.send_json_auto_id({"type": "blitzortung/subscribe_strikes"})
        assert (await client.receive_json(timeout=5))["success"]
        events = [(await client.receive_json(timeout=5))["event"] for _ in range(3)]

    assert [len(event["strikes"]) for event in events] == [2, 2, 1]
    assert [("time_window" in event) for event in events] == [True, False, False]


async def test_ws_entry_filter(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_config_entry_location_entity: MockConfigEntry,
    mock_location_entity: str,
    mock_mqtt: MagicMock,
) -> None:
    """A subscription for one entry gets only that entry's strikes."""
    # Setting up one entry sets up the whole domain, so both are loaded.
    coordinates = await _setup(hass, mock_config_entry_coordinates)
    tracked = mock_config_entry_location_entity.runtime_data
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "blitzortung/subscribe_strikes",
            "entry_id": mock_config_entry_location_entity.entry_id,
        }
    )
    assert (await client.receive_json(timeout=5))["success"]
    assert (await client.receive_json(timeout=5))["event"]["strikes"] == []

    time_ns = time.time_ns()
    await coordinates.on_mqtt_message(_strike_message(50.01, 10.01, time_ns))
    await tracked.on_mqtt_message(_strike_message(50.02, 10.02, time_ns))
    _flush(hass)

    assert (await client.receive_json(timeout=5))["event"] == {
        "strikes": [[50.02, 10.02, time_ns // 1_000_000]]
    }


async def test_ws_survives_reload_and_sends_new_time_window(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """After an options reload the same subscription gets the new strikes."""
    await _setup(hass, mock_config_entry_coordinates)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "blitzortung/subscribe_strikes"})
    assert (await client.receive_json(timeout=5))["success"]
    await client.receive_json(timeout=5)

    hass.config_entries.async_update_entry(
        mock_config_entry_coordinates,
        options={**mock_config_entry_coordinates.options, CONF_TIME_WINDOW: 30},
    )
    await hass.async_block_till_done()
    _flush(hass)
    assert (await client.receive_json(timeout=5))["event"] == {"time_window": 1800}

    time_ns = time.time_ns()
    await mock_config_entry_coordinates.runtime_data.on_mqtt_message(
        _strike_message(50.01, 10.01, time_ns)
    )
    _flush(hass)
    assert (await client.receive_json(timeout=5))["event"] == {
        "strikes": [[50.01, 10.01, time_ns // 1_000_000]]
    }


async def test_ws_unsubscribe_stops_batching(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """Without subscribers strikes are only buffered, not queued for sending."""
    coordinator = await _setup(hass, mock_config_entry_coordinates)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "blitzortung/subscribe_strikes"})
    subscription = (await client.receive_json(timeout=5))["id"]
    await client.receive_json(timeout=5)

    await client.send_json_auto_id(
        {"type": "unsubscribe_events", "subscription": subscription}
    )
    assert (await client.receive_json(timeout=5))["success"]
    await coordinator.on_mqtt_message(_strike_message(50.01, 10.01))

    stream = hass.data[STRIKE_STREAM]
    assert stream._subscribers == []
    assert stream._pending == []
    assert len(coordinator.strikes) == 1


async def test_ws_allowed_for_non_admin(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """Dashboards of non-admin users can show strikes too."""
    await _setup(hass, mock_config_entry_coordinates)
    client = await hass_ws_client(hass, hass_read_only_access_token)

    await client.send_json_auto_id({"type": "blitzortung/subscribe_strikes"})

    assert (await client.receive_json(timeout=5))["success"]
