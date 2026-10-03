"""Tests for the Blitzortung sensor module."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.components.recorder import Recorder, get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.json import json_dumps
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.blitzortung.const import ATTR_LAT, ATTR_LON, DOMAIN
from custom_components.blitzortung.mqtt import Message


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """Order recorder_mock before hass, which the conftest autouse fixture creates."""


@pytest.mark.parametrize("key", ["distance", "azimuth"])
async def test_strike_coordinates_not_recorded(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
    key: str,
) -> None:
    """Test per-strike lat/lon are live attributes but never reach the recorder."""
    start_time = dt_util.utcnow() - timedelta(minutes=1)
    await hass.config_entries.async_setup(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()

    payload = json_dumps(
        {"lat": 50.01, "lon": 10.01, "time": 1_000_000_000, "status": 0, "region": 0}
    )
    message = Message(
        topic="blitzortung/1.1/u/3/3/#", payload=payload, qos=0, retain=False
    )
    await mock_config_entry_coordinates.runtime_data.on_mqtt_message(message)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{mock_config_entry_coordinates.entry_id}-{key}"
    )
    assert entity_id is not None

    assert hass.states.get(entity_id).attributes[ATTR_LAT] == 50.01
    assert hass.states.get(entity_id).attributes[ATTR_LON] == 10.01

    states = await get_instance(hass).async_add_executor_job(
        get_significant_states, hass, start_time, None, [entity_id]
    )
    recorded = states[entity_id][-1].attributes
    assert ATTR_UNIT_OF_MEASUREMENT in recorded
    assert ATTR_LAT not in recorded
    assert ATTR_LON not in recorded
