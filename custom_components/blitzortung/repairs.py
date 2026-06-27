"""Repairs platform for Blitzortung integration."""

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import CONF_MAX_TRACKED_LIGHTNINGS, DOMAIN


class MaxTrackedLightningsRepairFlow(RepairsFlow):
    """Handler for the max tracked lightnings issue fix flow."""

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002
    ) -> RepairsFlowResult:
        """Handle the first step of a fix flow."""
        issue_registry = ir.async_get(self.hass)
        description_placeholders = None
        if issue := issue_registry.async_get_issue(DOMAIN, self.issue_id):
            description_placeholders = issue.translation_placeholders
        return self.async_show_menu(
            menu_options=["confirm", "ignore"],
            description_placeholders=description_placeholders,
        )

    async def async_step_confirm(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002
    ) -> RepairsFlowResult:
        """Handle the confirm step of a fix flow."""
        entry_id = self.data.get("entry_id")
        if entry_id:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry:
                new_options = {
                    **entry.options,
                    CONF_MAX_TRACKED_LIGHTNINGS: 400,
                }
                self.hass.config_entries.async_update_entry(entry, options=new_options)
                await self.hass.config_entries.async_reload(entry_id)
        return self.async_create_entry(title="", data={})

    async def async_step_ignore(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002
    ) -> RepairsFlowResult:
        """Handle the ignore step of a fix flow."""
        ir.async_ignore_issue(self.hass, DOMAIN, self.issue_id, True)
        return self.async_abort(reason="issue_ignored")


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001
    issue_id: str,
    data: dict[str, str | int | float | None] | None,  # noqa: ARG001
) -> RepairsFlow:
    """Create flow."""
    if issue_id.startswith("max_tracked_lightnings_warning"):
        return MaxTrackedLightningsRepairFlow()
    return None  # type: ignore[return-value]
