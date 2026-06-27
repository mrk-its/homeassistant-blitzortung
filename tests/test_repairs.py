"""Tests for the Blitzortung repairs platform."""

from unittest.mock import MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blitzortung.const import (
    CONF_CONFIG_TYPE,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    CONFIG_TYPE_COORDINATES,
    DOMAIN,
)
from custom_components.blitzortung.repairs import (
    MaxTrackedLightningsRepairFlow,
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


def _make_entry(
    hass: HomeAssistant, unique_id: str, max_val: int = 600
) -> MockConfigEntry:
    """Create a coordinates-based MockConfigEntry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test Location",
            "latitude": 50.0,
            "longitude": 10.0,
            CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        },
        unique_id=unique_id,
        version=6,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: max_val,
            CONF_TIME_WINDOW: 10,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_init_shows_menu(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test the init step shows a menu with confirm and ignore options."""
    entry = _make_entry(hass, "50.0-10.0-menu")
    flow = await _setup_flow(hass, entry)

    result = await flow.async_step_init()
    assert result["type"] == "menu"
    assert result["menu_options"] == ["confirm", "ignore"]


async def test_confirm_step_reduces_value_and_reloads(
    hass: HomeAssistant,
    mock_mqtt: MagicMock,
) -> None:
    """Test confirm step sets max_tracked_lightnings to 400 and reloads."""
    entry = _make_entry(hass, "50.0-10.0-confirm")
    flow = await _setup_flow(hass, entry)
    issue_id = flow.issue_id

    result = await flow.async_step_confirm(user_input={})
    assert result["type"] == "create_entry"
    assert result["data"] == {}

    assert entry.options[CONF_MAX_TRACKED_LIGHTNINGS] == 400
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
) -> None:
    """Test the ignore step calls async_ignore_issue and aborts."""
    entry = _make_entry(hass, "50.0-10.0-ignore")
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
