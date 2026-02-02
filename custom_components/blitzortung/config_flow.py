"""Config flow for blitzortung integration."""

from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.helpers import selector

from .const import (
    CONF_LOCATION_ENTITY,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    DEFAULT_MAX_TRACKED_LIGHTNINGS,
    DEFAULT_RADIUS,
    DEFAULT_TIME_WINDOW,
    DOMAIN,
)

# Only allow tracker-like entities
TRACKER_ENTITY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["device_tracker", "person"])
)

TRACKER_ENTITY_SELECTOR_OR_NONE = vol.Any(None, TRACKER_ENTITY_SELECTOR)

RECONFIGURE_SCHEMA = vol.Schema(
    {
        # Keep lat/lon visible but not required (can be empty when using a tracker)
        vol.Optional(CONF_LATITUDE): cv.latitude,
        vol.Optional(CONF_LONGITUDE): cv.longitude,
        vol.Optional(CONF_LOCATION_ENTITY): TRACKER_ENTITY_SELECTOR_OR_NONE,
    }
)

CONF_CONFIG_TYPE = "config_type"
CONFIG_TYPE_COORDINATES = "coordinates"
CONFIG_TYPE_TRACKER = "tracker"

CONFIG_TYPE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[
            {"value": CONFIG_TYPE_COORDINATES, "label": "Coordinates"},
            {"value": CONFIG_TYPE_TRACKER, "label": "Tracking entity"},
        ],
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)


class BlitortungConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for blitzortung."""

    VERSION = 6

    def _ensure_lat_lon(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ensure config entry always stores lat/lon (fallback to HA defaults)."""
        out = dict(data)
        if CONF_LATITUDE not in out:
            out[CONF_LATITUDE] = self.hass.config.latitude
        if CONF_LONGITUDE not in out:
            out[CONF_LONGITUDE] = self.hass.config.longitude
        return out

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select how the user wants to configure the entry."""
        if user_input is not None:
            self.context[CONF_CONFIG_TYPE] = user_input[CONF_CONFIG_TYPE]
            if user_input[CONF_CONFIG_TYPE] == CONFIG_TYPE_TRACKER:
                return await self.async_step_tracker()
            return await self.async_step_coordinates()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONFIG_TYPE, default=CONFIG_TYPE_TRACKER
                    ): CONFIG_TYPE_SELECTOR,
                }
            ),
        )

    async def async_step_tracker(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the entry using a tracking entity."""
        if user_input is not None:
            user_input = self._ensure_lat_lon(user_input)
            location_entity = user_input[CONF_LOCATION_ENTITY]

            unique_id = f"tracker-{location_entity.lower()}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data=user_input,
                options={
                    CONF_RADIUS: DEFAULT_RADIUS,
                    CONF_MAX_TRACKED_LIGHTNINGS: DEFAULT_MAX_TRACKED_LIGHTNINGS,
                    CONF_TIME_WINDOW: DEFAULT_TIME_WINDOW,
                },
            )

        defaults = user_input or {}
        return self.async_show_form(
            step_id="tracker",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME,
                        default=defaults.get(CONF_NAME, self.hass.config.location_name),
                    ): str,
                    vol.Required(
                        CONF_LOCATION_ENTITY,
                        default=defaults.get(CONF_LOCATION_ENTITY),
                    ): TRACKER_ENTITY_SELECTOR,
                }
            )
        )

    async def async_step_coordinates(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the entry using fixed coordinates."""
        if user_input is not None:
            user_input = self._ensure_lat_lon(user_input)

            # Coordinates-based entries do not store a tracker entity
            user_input.pop(CONF_LOCATION_ENTITY, None)

            lat = user_input[CONF_LATITUDE]
            lon = user_input[CONF_LONGITUDE]

            unique_id = f"{lat}-{lon}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data=user_input,
                options={
                    CONF_RADIUS: DEFAULT_RADIUS,
                    CONF_MAX_TRACKED_LIGHTNINGS: DEFAULT_MAX_TRACKED_LIGHTNINGS,
                    CONF_TIME_WINDOW: DEFAULT_TIME_WINDOW,
                },
            )

        defaults = user_input or {}
        return self.async_show_form(
            step_id="coordinates",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME,
                        default=defaults.get(
                            CONF_NAME,
                            self.hass.config.location_name
                        ),
                    ): str,
                    vol.Required(
                        CONF_LATITUDE,
                        default=defaults.get(
                            CONF_LATITUDE,
                            self.hass.config.latitude
                        ),
                    ): cv.latitude,
                    vol.Required(
                        CONF_LONGITUDE,
                        default=defaults.get(
                            CONF_LONGITUDE,
                            self.hass.config.longitude
                        ),
                    ): cv.longitude,
                }
            )
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a reconfiguration flow initialized by the user."""
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            # If the user is reconfiguring and leaves lat/lon blank, keep existing ones.
            merged = dict(reconfigure_entry.data)
            merged.update(user_input)
            merged = self._ensure_lat_lon(merged)

            # Only update the fields the user changed + ensure lat/lon exist
            # (We pass full merged to keep entry.data consistent)
            return self.async_update_reload_and_abort(
                reconfigure_entry,
                data_updates=merged,
            )

        # Suggested values should include existing entry data, with HA fallback
        suggested = dict(reconfigure_entry.data)
        suggested = self._ensure_lat_lon(suggested)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                data_schema=RECONFIGURE_SCHEMA,
                suggested_values=suggested | (user_input or {}),
            ),
            description_placeholders={"name": reconfigure_entry.title}
        )

    @staticmethod
    def async_get_options_flow(_config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return BlitzortungOptionsFlowHandler()


class BlitzortungOptionsFlowHandler(OptionsFlow):
    """Handle an options flow for Blitzortung."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            if user_input.get(CONF_LOCATION_ENTITY) is None:
                user_input.pop(CONF_LOCATION_ENTITY, None)
            return self.async_create_entry(data=user_input)

        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_RADIUS,
                    default=self.config_entry.options.get(CONF_RADIUS, DEFAULT_RADIUS),
                ): int,
                vol.Optional(
                    CONF_TIME_WINDOW,
                    default=self.config_entry.options.get(
                    CONF_TIME_WINDOW,
                        DEFAULT_TIME_WINDOW,
                    ),
                ): int,
                vol.Optional(
                    CONF_MAX_TRACKED_LIGHTNINGS,
                    default=self.config_entry.options.get(
                    CONF_MAX_TRACKED_LIGHTNINGS,
                        DEFAULT_MAX_TRACKED_LIGHTNINGS,
                    ),
                ): int,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                options_schema, self.config_entry.options
            ),
        )
