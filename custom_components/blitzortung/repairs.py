"""Repairs platform for Blitzortung integration."""

from typing import TYPE_CHECKING

import probatio
from homeassistant.components.repairs import (
    ConfirmRepairFlow,
    RepairsFlow,
    RepairsFlowResult,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util.unit_system import IMPERIAL_SYSTEM

from .const import (
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    DOMAIN,
    MAX_TRACKED_LIGHTNINGS_WARNING,
    TIME_WINDOW_MAX,
    radius_max,
)


class BlitzortungRepairFlow(RepairsFlow):
    """Base handler for Blitzortung issue fix flows."""

    @property
    def _option_update(self) -> dict[str, int]:
        """Return the option key-value pairs to update on confirm."""
        raise NotImplementedError

    def _description_placeholders(self) -> dict[str, str] | None:
        """Return the translation placeholders of the issue being fixed."""
        issue = ir.async_get(self.hass).async_get_issue(DOMAIN, self.issue_id)
        return issue.translation_placeholders if issue else None

    async def async_step_confirm(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002
    ) -> RepairsFlowResult:
        """Handle the confirm step of a fix flow."""
        if TYPE_CHECKING:
            assert self.data

        entry_id = self.data["entry_id"]

        if TYPE_CHECKING:
            assert isinstance(entry_id, str)

        entry = self.hass.config_entries.async_get_entry(entry_id)

        if not entry:
            return self.async_abort(reason="entry_not_found")

        new_options = {
            **entry.options,
            **self._option_update,
        }
        self.hass.config_entries.async_update_entry(entry, options=new_options)

        return self.async_create_entry(title="", data={})


class IgnorableRepairFlow(BlitzortungRepairFlow):
    """Base handler for fix flows offering to either apply the fix or ignore."""

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002
    ) -> RepairsFlowResult:
        """Handle the first step of a fix flow."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["confirm", "ignore"],
            description_placeholders=self._description_placeholders(),
        )

    async def async_step_ignore(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002
    ) -> RepairsFlowResult:
        """Handle the ignore step of a fix flow."""
        ir.async_ignore_issue(self.hass, DOMAIN, self.issue_id, True)
        return self.async_abort(reason="issue_ignored")


class MaxTrackedLightningsRepairFlow(IgnorableRepairFlow):
    """Handler for the max tracked lightnings issue fix flow."""

    @property
    def _option_update(self) -> dict[str, int]:
        return {CONF_MAX_TRACKED_LIGHTNINGS: MAX_TRACKED_LIGHTNINGS_WARNING}


class RadiusMaxRepairFlow(BlitzortungRepairFlow):
    """Handler for the radius max issue fix flow."""

    @property
    def _option_update(self) -> dict[str, int]:
        return {CONF_RADIUS: radius_max(self.hass.config.units == IMPERIAL_SYSTEM)}

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002
    ) -> RepairsFlowResult:
        """Handle the first step of a fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Show a confirm-only form, then apply the fix on submit."""
        if user_input is None:
            # No ignore option: a large radius raises the server costs, so the
            # limit must not be dismissable.
            return self.async_show_form(
                step_id="confirm",
                data_schema=probatio.Schema({}),
                description_placeholders=self._description_placeholders(),
            )

        return await super().async_step_confirm(user_input)


class TimeWindowMaxRepairFlow(IgnorableRepairFlow):
    """Handler for the time window max issue fix flow."""

    @property
    def _option_update(self) -> dict[str, int]:
        return {CONF_TIME_WINDOW: TIME_WINDOW_MAX}


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001
    issue_id: str,
    data: dict[str, str | int | float | None] | None,  # noqa: ARG001
) -> RepairsFlow:
    """Create flow."""
    if issue_id.startswith("max_tracked_lightnings_warning"):
        return MaxTrackedLightningsRepairFlow()

    if issue_id.startswith("radius_max_warning"):
        return RadiusMaxRepairFlow()

    if issue_id.startswith("time_window_max_warning"):
        return TimeWindowMaxRepairFlow()

    return ConfirmRepairFlow()
