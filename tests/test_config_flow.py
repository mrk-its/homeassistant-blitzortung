"""Tests for the Blitzortung config flow."""

import pytest
from homeassistant.components.device_tracker import DOMAIN as DEVICE_TRACKER_DOMAIN
from homeassistant.components.person import DOMAIN as PERSON_DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
    STATE_HOME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blitzortung.const import (
    CONF_CONFIG_TYPE,
    CONF_LOCATION_ENTITY,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    CONFIG_TYPE_COORDINATES,
    CONFIG_TYPE_ENTITY,
    DOMAIN,
)


@pytest.mark.asyncio
async def test_user_flow_success_coordinates(hass: HomeAssistant) -> None:
    """Test successful user flow for coordinates."""
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
async def test_user_flow_already_configured_coordinates(hass: HomeAssistant) -> None:
    """Test user flow when already configured for coordinates."""
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
async def test_reconfigure_flow_success(
    hass: HomeAssistant, mock_config_entry_coordinates: MockConfigEntry
) -> None:
    """Test successful reconfigure flow."""
    result = await mock_config_entry_coordinates.start_reconfigure_flow(hass)
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
    assert mock_config_entry_coordinates.data[CONF_LATITUDE] == 51.0
    assert mock_config_entry_coordinates.data[CONF_LONGITUDE] == 11.0


@pytest.mark.asyncio
async def test_options_flow_success(
    hass: HomeAssistant, mock_config_entry_coordinates: MockConfigEntry
) -> None:
    """Test successful options flow."""
    result = await hass.config_entries.options.async_init(
        mock_config_entry_coordinates.entry_id, context={"source": "user"}
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


@pytest.mark.parametrize("platform", [DEVICE_TRACKER_DOMAIN, PERSON_DOMAIN])
@pytest.mark.asyncio
async def test_user_flow_success_entity(hass: HomeAssistant, platform: str) -> None:
    """Test successful user flow for location entity."""
    entity_id = f"{platform}.test_phone"
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        platform,
        platform,
        "unique_1234",
        suggested_object_id="test_phone",
        original_name="Test phone",
    )
    attrs = {ATTR_LATITUDE: 50.0, ATTR_LONGITUDE: 10.0}
    hass.states.async_set(entity_id, STATE_HOME, attrs)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    # Step 1: choose entity config type
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CONFIG_TYPE: CONFIG_TYPE_ENTITY},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "entity"

    # Step 2: provide entity
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LOCATION_ENTITY: entity_id},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test phone"
    assert result["data"] == {
        CONF_NAME: "Test phone",
        CONF_LOCATION_ENTITY: entity_id,
        CONF_CONFIG_TYPE: CONFIG_TYPE_ENTITY,
    }
    assert result["options"] == {
        CONF_RADIUS: 100,
        CONF_MAX_TRACKED_LIGHTNINGS: 100,
        CONF_TIME_WINDOW: 120,
    }
    assert result["result"].unique_id == f"{platform}_unique_1234"


@pytest.mark.asyncio
async def test_location_entity_without_unique_id(hass: HomeAssistant) -> None:
    """Test the flow for location entity without unique ID."""
    entity_id = "device_tracker.test_phone"
    attrs = {ATTR_LATITUDE: 50.0, ATTR_LONGITUDE: 10.0}
    hass.states.async_set(entity_id, STATE_HOME, attrs)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    # Step 1: choose entity config type
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CONFIG_TYPE: CONFIG_TYPE_ENTITY},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "entity"

    # Step 2: provide entity
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LOCATION_ENTITY: entity_id},
    )

    assert result["errors"] == {"base": "entity_without_unique_id"}


@pytest.mark.asyncio
async def test_location_entity_without_coordinates(hass: HomeAssistant) -> None:
    """Test the flow for location entity without coordinates."""
    entity_id = "device_tracker.test_phone"
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "device_tracker",
        "device_tracker",
        "unique_1234",
        suggested_object_id="test_phone",
        original_name="Test phone",
    )
    hass.states.async_set(entity_id, STATE_HOME)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    # Step 1: choose entity config type
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CONFIG_TYPE: CONFIG_TYPE_ENTITY},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "entity"

    # Step 2: provide entity
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LOCATION_ENTITY: entity_id},
    )

    assert result["errors"] == {"base": "entity_without_coordinates"}


@pytest.mark.asyncio
async def test_reconfigure_flow_not_supported(
    hass: HomeAssistant, mock_config_entry_location_entity: MockConfigEntry
) -> None:
    """Test that reconfigure for a location entity entry aborts immediately."""
    entity_id = "device_tracker.original_tracker"
    hass.states.async_set(entity_id, STATE_HOME)

    result = await mock_config_entry_location_entity.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_not_supported"
