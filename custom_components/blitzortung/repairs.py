"""Repairs platform for Blitzortung integration."""

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .const import CONF_MAX_TRACKED_LIGHTNINGS


class MaxTrackedLightningsRepairFlow(RepairsFlow):
    """Handler for the max tracked lightnings issue fix flow."""

    async def async_step_init(
        self, _user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirm/fix step."""
        if user_input is not None:
            entry_id = self.data.get("entry_id")
            if entry_id:
                entry = self.hass.config_entries.async_get_entry(entry_id)
                if entry:
                    new_options = {
                        **entry.options,
                        CONF_MAX_TRACKED_LIGHTNINGS: 400,
                    }
                    self.hass.config_entries.async_update_entry(
                        entry, options=new_options
                    )
                    await self.hass.config_entries.async_reload(entry_id)
            return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
        )


async def async_create_fix_flow(
    _hass: HomeAssistant,
    issue_id: str,
    _data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create flow."""
    if issue_id.startswith("max_tracked_lightnings_warning"):
        return MaxTrackedLightningsRepairFlow()
    return None  # type: ignore[return-value]
