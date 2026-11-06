"""Tests for the Blitzortung repairs platform."""

from unittest.mock import MagicMock, patch

from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

from custom_components.blitzortung.const import (
    CONF_CONFIG_TYPE,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    DOMAIN,
    DONATE_URL,
    MAX_TRACKED_LIGHTNINGS_WARNING,
    RADIUS_MAX,
    TIME_WINDOW_MAX,
)
from custom_components.blitzortung.repairs import (
    IgnorableRepairFlow,
    MaxTrackedLightningsRepairFlow,
    RadiusMaxRepairFlow,
    TimeWindowMaxRepairFlow,
    async_create_fix_flow,
)


async def _setup_flow(
    hass: HomeAssistant, entry: MockConfigEntry
) -> MaxTrackedLightningsRepairFlow:
    """Set up a config entry and return a flow instance."""
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    issue_id = f"max_tracked_lightnings_warning_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    flow = MaxTrackedLightningsRepairFlow()
    flow.hass = hass
    flow.data = {"entry_id": entry.entry_id}
    flow.handler = issue_id
    flow.issue_id = issue_id
    return flow


async def _setup_radius_flow(
    hass: HomeAssistant, entry: MockConfigEntry
) -> RadiusMaxRepairFlow:
    """Set up a config entry with radius issue and return a flow instance."""
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    issue_id = f"radius_max_warning_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    flow = RadiusMaxRepairFlow()
    flow.hass = hass
    flow.data = {"entry_id": entry.entry_id}
    flow.handler = issue_id
    flow.issue_id = issue_id
    return flow


async def test_init_shows_menu(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
    mock_config_entry_coordinates: MockConfigEntry,
) -> None:
    """Test the init step shows a menu with confirm and ignore options."""
    entry = mock_config_entry_coordinates
    flow = await _setup_flow(hass, entry)

    result = await flow.async_step_init()
    assert result["type"] == "menu"
    assert result["menu_options"] == ["confirm", "ignore"]


async def test_confirm_step_reduces_value_and_reloads(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
    mock_config_entry_coordinates: MockConfigEntry,
) -> None:
    """Test confirm step sets max_tracked_lightnings to 400 and reloads."""
    entry = mock_config_entry_coordinates
    flow = await _setup_flow(hass, entry)
    issue_id = flow.issue_id

    result = await flow.async_step_confirm(user_input={})
    assert result["type"] == "create_entry"
    assert result["data"] == {}

    assert entry.options[CONF_MAX_TRACKED_LIGHTNINGS] == MAX_TRACKED_LIGHTNINGS_WARNING
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_confirm_step_unknown_entry(
    hass: HomeAssistant,
) -> None:
    """Test the confirm step handles a missing entry gracefully."""
    flow = MaxTrackedLightningsRepairFlow()
    flow.hass = hass
    flow.data = {"entry_id": "nonexistent_entry_id"}
    flow.handler = "max_tracked_lightnings_warning_nonexistent"
    flow.issue_id = "max_tracked_lightnings_warning_nonexistent"

    result = await flow.async_step_confirm(user_input={})
    assert result["type"] == "abort"
    assert result["reason"] == "entry_not_found"


async def test_ignore_step(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
    mock_config_entry_coordinates: MockConfigEntry,
) -> None:
    """Test the ignore step calls async_ignore_issue and aborts."""
    entry = mock_config_entry_coordinates
    flow = await _setup_flow(hass, entry)

    with patch(
        "custom_components.blitzortung.repairs.ir.async_ignore_issue"
    ) as mock_ignore:
        result = await flow.async_step_ignore(user_input={})

    mock_ignore.assert_called_once_with(hass, DOMAIN, flow.issue_id, True)
    assert result["type"] == "abort"
    assert result["reason"] == "issue_ignored"


async def test_async_create_fix_flow_matches_warning_issue(
    hass: HomeAssistant,
) -> None:
    """Test async_create_fix_flow returns the correct flow for warning issues."""
    flow = await async_create_fix_flow(
        hass,
        "max_tracked_lightnings_warning_abc123",
        {"entry_id": "abc123"},
    )
    assert isinstance(flow, MaxTrackedLightningsRepairFlow)


async def test_radius_fix_flow_shows_form_then_reduces_value(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test the radius fix flow run by HA shows a confirm form, then reduces."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: "coordinates",
        },
        unique_id="50.0-10.0-radius-flow",
        version=6,
        options={
            CONF_RADIUS: RADIUS_MAX + 1000,
            CONF_MAX_TRACKED_LIGHTNINGS: 100,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, "repairs", {})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"radius_max_warning_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    # HA hands {"issue_id": ...} to the first step, so the flow must not treat
    # that as the user's submit and reduce the radius without showing the form.
    manager = repairs_flow_manager(hass)
    assert manager is not None
    result = await manager.async_init(
        DOMAIN, context={"source": "user"}, data={"issue_id": issue_id}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "confirm"
    assert not result["data_schema"].schema
    assert result["description_placeholders"] == {
        "name": "Test Location",
        "radius": str(RADIUS_MAX + 1000),
        "radius_max": str(RADIUS_MAX),
        "donate_url": DONATE_URL,
    }
    assert entry.options[CONF_RADIUS] == RADIUS_MAX + 1000

    result = await manager.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options[CONF_RADIUS] == RADIUS_MAX
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_radius_confirm_step_unknown_entry(
    hass: HomeAssistant,
) -> None:
    """Test the radius confirm step handles a missing entry gracefully."""
    flow = RadiusMaxRepairFlow()
    flow.hass = hass
    flow.data = {"entry_id": "nonexistent_entry_id"}
    flow.handler = "radius_max_warning_nonexistent"
    flow.issue_id = "radius_max_warning_nonexistent"

    result = await flow.async_step_confirm(user_input={})
    assert result["type"] == "abort"
    assert result["reason"] == "entry_not_found"


async def test_radius_flow_not_ignorable() -> None:
    """Test the radius flow offers no way to ignore the issue."""
    assert not hasattr(RadiusMaxRepairFlow, "async_step_ignore")
    assert not issubclass(RadiusMaxRepairFlow, IgnorableRepairFlow)


async def test_async_create_fix_flow_matches_radius_issue(
    hass: HomeAssistant,
) -> None:
    """Test async_create_fix_flow returns RadiusMaxRepairFlow for radius issues."""
    flow = await async_create_fix_flow(
        hass,
        "radius_max_warning_abc123",
        {"entry_id": "abc123"},
    )
    assert isinstance(flow, RadiusMaxRepairFlow)


async def _setup_time_window_flow(
    hass: HomeAssistant, entry: MockConfigEntry
) -> TimeWindowMaxRepairFlow:
    """Set up a config entry with time_window issue and return a flow instance."""
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    issue_id = f"time_window_max_warning_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    flow = TimeWindowMaxRepairFlow()
    flow.hass = hass
    flow.data = {"entry_id": entry.entry_id}
    flow.handler = issue_id
    flow.issue_id = issue_id
    return flow


async def test_time_window_init_shows_menu(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test the time_window init step shows a menu with confirm and ignore options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: "coordinates",
        },
        unique_id="50.0-10.0-time-window-menu",
        version=6,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: 100,
            CONF_TIME_WINDOW: TIME_WINDOW_MAX + 100,
        },
    )
    entry.add_to_hass(hass)
    flow = await _setup_time_window_flow(hass, entry)

    result = await flow.async_step_init()
    assert result["type"] == "menu"
    assert result["menu_options"] == ["confirm", "ignore"]


async def test_time_window_confirm_step_reduces_value(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test time_window confirm step sets time_window to TIME_WINDOW_MAX."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: "coordinates",
        },
        unique_id="50.0-10.0-time-window-confirm",
        version=6,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: 100,
            CONF_TIME_WINDOW: TIME_WINDOW_MAX + 100,
        },
    )
    entry.add_to_hass(hass)
    flow = await _setup_time_window_flow(hass, entry)
    issue_id = flow.issue_id

    result = await flow.async_step_confirm(user_input={})
    assert result["type"] == "create_entry"
    assert result["data"] == {}

    assert entry.options[CONF_TIME_WINDOW] == TIME_WINDOW_MAX
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_time_window_confirm_step_unknown_entry(
    hass: HomeAssistant,
) -> None:
    """Test the time_window confirm step handles a missing entry gracefully."""
    flow = TimeWindowMaxRepairFlow()
    flow.hass = hass
    flow.data = {"entry_id": "nonexistent_entry_id"}
    flow.handler = "time_window_max_warning_nonexistent"
    flow.issue_id = "time_window_max_warning_nonexistent"

    result = await flow.async_step_confirm(user_input={})
    assert result["type"] == "abort"
    assert result["reason"] == "entry_not_found"


async def test_time_window_ignore_step(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test the time_window ignore step calls async_ignore_issue and aborts."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Location",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: "coordinates",
        },
        unique_id="50.0-10.0-time-window-ignore",
        version=6,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: 100,
            CONF_TIME_WINDOW: TIME_WINDOW_MAX + 100,
        },
    )
    entry.add_to_hass(hass)
    flow = await _setup_time_window_flow(hass, entry)

    with patch(
        "custom_components.blitzortung.repairs.ir.async_ignore_issue"
    ) as mock_ignore:
        result = await flow.async_step_ignore(user_input={})

    mock_ignore.assert_called_once_with(hass, DOMAIN, flow.issue_id, True)
    assert result["type"] == "abort"
    assert result["reason"] == "issue_ignored"


async def test_async_create_fix_flow_matches_time_window_issue(
    hass: HomeAssistant,
) -> None:
    """Test async_create_fix_flow returns TimeWindowMaxRepairFlow for time_window."""
    flow = await async_create_fix_flow(
        hass,
        "time_window_max_warning_abc123",
        {"entry_id": "abc123"},
    )
    assert isinstance(flow, TimeWindowMaxRepairFlow)
