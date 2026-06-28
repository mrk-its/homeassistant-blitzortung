"""Tests for the Blitzortung geo_location module."""

import json
from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blitzortung.mqtt import Message


async def test_geo_location_entity_lifecycle(
    hass: HomeAssistant,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """Test geo location entity is created via lightning data and removed on unload."""
    await hass.config_entries.async_setup(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry_coordinates.state is ConfigEntryState.LOADED

    coordinator = mock_config_entry_coordinates.runtime_data

    payload = json.dumps(
        {
            "lat": 50.01,
            "lon": 10.01,
            "time": 1_000_000_000,
            "status": 0,
            "region": 0,
        }
    )
    message = Message(
        topic="blitzortung/1.1/u/3/3/#",
        payload=payload,
        qos=0,
        retain=False,
    )
    await coordinator.on_mqtt_message(message)
    await hass.async_block_till_done()

    geo_entity_ids = hass.states.async_entity_ids("geo_location")
    assert len(geo_entity_ids) == 1
    entity_id = geo_entity_ids[0]
    assert hass.states.get(entity_id) is not None

    await hass.config_entries.async_unload(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id) is None
    assert entity_id not in hass.states.async_entity_ids()
