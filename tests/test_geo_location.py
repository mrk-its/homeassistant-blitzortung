"""Tests for the Blitzortung geo_location module."""

import json
import logging
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.components.geo_location import DOMAIN as GEO_LOCATION_DOMAIN

from custom_components.blitzortung.const import (
    CONF_CONFIG_TYPE,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    CONFIG_TYPE_COORDINATES,
    DOMAIN,
)
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

    geo_entity_ids = hass.states.async_entity_ids(GEO_LOCATION_DOMAIN)
    assert len(geo_entity_ids) == 1
    entity_id = geo_entity_ids[0]
    assert hass.states.get(entity_id) is not None

    await hass.config_entries.async_unload(mock_config_entry_coordinates.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id) is None
    assert entity_id not in hass.states.async_entity_ids(GEO_LOCATION_DOMAIN)


async def test_geo_location_delete_callback_no_warning(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that _delete_callback doesn't trigger double-removal dispatcher warnings."""
    caplog.set_level(logging.WARNING, logger="homeassistant.helpers.dispatcher")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
            "name": "Test",
            "latitude": 50.0,
            "longitude": 10.0,
        },
        unique_id="50.0-10.0-test",
        version=6,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: 1,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    coordinator = entry.runtime_data

    payload1 = json.dumps(
        {
            "lat": 50.01,
            "lon": 10.01,
            "time": 1_000_000_000,
            "status": 0,
            "region": 0,
        }
    )
    message1 = Message(
        topic="blitzortung/1.1/u/3/3/#",
        payload=payload1,
        qos=0,
        retain=False,
    )
    await coordinator.on_mqtt_message(message1)
    await hass.async_block_till_done()

    geo_entity_ids = hass.states.async_entity_ids(GEO_LOCATION_DOMAIN)
    assert len(geo_entity_ids) == 1
    first_entity_id = geo_entity_ids[0]

    payload2 = json.dumps(
        {
            "lat": 50.02,
            "lon": 10.02,
            "time": 2_000_000_000,
            "status": 0,
            "region": 0,
        }
    )
    message2 = Message(
        topic="blitzortung/1.1/u/3/3/#",
        payload=payload2,
        qos=0,
        retain=False,
    )
    await coordinator.on_mqtt_message(message2)
    await hass.async_block_till_done()

    geo_entity_ids = hass.states.async_entity_ids(GEO_LOCATION_DOMAIN)
    assert len(geo_entity_ids) == 1
    second_entity_id = geo_entity_ids[0]

    assert first_entity_id != second_entity_id
    assert hass.states.get(first_entity_id) is None
    assert hass.states.get(second_entity_id) is not None

    assert "Unable to remove unknown dispatcher" not in caplog.text
