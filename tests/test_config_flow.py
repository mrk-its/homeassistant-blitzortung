"""Tests for the Blitzortung config flow."""

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blitzortung.config_flow import (
    CONF_CONFIG_TYPE,
    CONFIG_TYPE_COORDINATES,
    CONFIG_TYPE_TRACKER,
)
from custom_components.blitzortung.const import (
    CONF_LOCATION_ENTITY,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    DOMAIN,
)


@pytest.mark.asyncio
async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test successful user flow (coordinates)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    # Step 1: choose config type
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "coordinates"

    # Step 2: provide coords + name
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Location"
    assert result["data"] == {
        CONF_NAME: "Test Location",
        CONF_LATITUDE: 50.0,
        CONF_LONGITUDE: 10.0,
        CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
    }
    assert result["options"] == {
        CONF_RADIUS: 100,
        CONF_MAX_TRACKED_LIGHTNINGS: 100,
        CONF_TIME_WINDOW: 120,
    }
    assert result["result"].unique_id == "50.0-10.0"


@pytest.mark.asyncio
async def test_user_flow_already_configured(hass: HomeAssistant) -> None:
    """Test user flow when already configured (coordinates)."""
    mock_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Existing Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
        },
        unique_id="50.0-10.0",
    )
    mock_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    # Step 1: choose config type
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "coordinates"

    # Step 2: same coords -> should abort
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_user_flow_success_tracker(hass: HomeAssistant) -> None:
    """Test successful user flow (tracker)."""
    # Make HA defaults deterministic for _ensure_lat_lon()
    hass.config.latitude = 52.0
    hass.config.longitude = 4.0

    # Provide a tracker entity id (selector validates domain, not state)
    tracker_entity_id = "device_tracker.test_phone"
    hass.states.async_set(tracker_entity_id, "home")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    # Step 1: choose tracker config type
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CONFIG_TYPE: CONFIG_TYPE_TRACKER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "tracker"

    # Step 2: provide name + entity
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "Tracked Location",
            CONF_LOCATION_ENTITY: tracker_entity_id,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Tracked Location"
    assert result["data"] == {
        CONF_NAME: "Tracked Location",
        CONF_LOCATION_ENTITY: tracker_entity_id,
        CONF_CONFIG_TYPE: CONFIG_TYPE_TRACKER,
    }
    assert result["options"] == {
        CONF_RADIUS: 100,
        CONF_MAX_TRACKED_LIGHTNINGS: 100,
        CONF_TIME_WINDOW: 120,
    }
    assert result["result"].unique_id == f"tracker-{tracker_entity_id.lower()}"


@pytest.mark.asyncio
async def test_reconfigure_flow_success(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test successful reconfigure flow."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_LATITUDE: 51.0,
            CONF_LONGITUDE: 11.0,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_LATITUDE] == 51.0
    assert mock_config_entry.data[CONF_LONGITUDE] == 11.0


@pytest.mark.asyncio
async def test_reconfigure_flow_success_tracker(hass: HomeAssistant) -> None:
    """Test successful reconfigure flow (tracker preserves entity)."""
    tracker_entity_id = "device_tracker.original_tracker"
    new_tracker_entity_id = "device_tracker.new_tracker"

    hass.states.async_set(tracker_entity_id, "home")
    hass.states.async_set(new_tracker_entity_id, "home")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Tracked Location",
            CONF_CONFIG_TYPE: CONFIG_TYPE_TRACKER,
            CONF_LOCATION_ENTITY: tracker_entity_id,
        },
        unique_id=f"tracker-{tracker_entity_id.lower()}",
        version=6,
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            # Attempt to switch to a different tracker and add coordinates.
            CONF_LOCATION_ENTITY: new_tracker_entity_id,
            CONF_LATITUDE: 51.0,
            CONF_LONGITUDE: 11.0,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_CONFIG_TYPE] == CONFIG_TYPE_TRACKER
    assert entry.data[CONF_LOCATION_ENTITY] == tracker_entity_id
    assert CONF_LATITUDE not in entry.data
    assert CONF_LONGITUDE not in entry.data


@pytest.mark.asyncio
async def test_options_flow_success(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test successful options flow."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(
        mock_config_entry.entry_id, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_RADIUS: 200,
            CONF_TIME_WINDOW: 300,
            CONF_MAX_TRACKED_LIGHTNINGS: 150,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_RADIUS: 200,
        CONF_TIME_WINDOW: 300,
        CONF_MAX_TRACKED_LIGHTNINGS: 150,
    }
