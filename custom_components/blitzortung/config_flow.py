"""Config flow for blitzortung integration."""

import voluptuous as vol
from typing import Any
import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.helpers import selector

from .const import (
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    CONF_ENABLE_GEOCODING,
    DEFAULT_MAX_TRACKED_LIGHTNINGS,
    DEFAULT_RADIUS,
    DEFAULT_TIME_WINDOW,
    DEFAULT_ENABLE_GEOCODING,
    CONF_DEVICE_TRACKER,
    CONF_TRACKING_MODE,
    DEFAULT_MAX_TRACKED_LIGHTNINGS,
    DEFAULT_RADIUS,
    DEFAULT_TIME_WINDOW,
    DEFAULT_TRACKING_MODE,
    DOMAIN,
)

RECONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TRACKING_MODE, default=DEFAULT_TRACKING_MODE): vol.In(
            ["Static", "Device Tracker"]
        ),
        vol.Optional(CONF_LATITUDE): cv.latitude,
        vol.Optional(CONF_LONGITUDE): cv.longitude,
        vol.Optional(CONF_DEVICE_TRACKER): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="device_tracker")
        ),
    }
)


class BlitortungConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for blitzortung."""

    VERSION = 5

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:            # Validate input based on tracking mode
            if user_input[CONF_TRACKING_MODE] == "Static":
                if not user_input.get(CONF_LATITUDE) or not user_input.get(CONF_LONGITUDE):
                    errors["base"] = "static_location_required"
                else:
                    await self.async_set_unique_id(
                        f"{user_input[CONF_LATITUDE]}-{user_input[CONF_LONGITUDE]}"
                    )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data={
                            CONF_NAME: user_input[CONF_NAME],
                            CONF_TRACKING_MODE: user_input[CONF_TRACKING_MODE],
                            CONF_LATITUDE: user_input[CONF_LATITUDE],
                            CONF_LONGITUDE: user_input[CONF_LONGITUDE],
                        },
                        options={
                            CONF_RADIUS: DEFAULT_RADIUS,
                            CONF_MAX_TRACKED_LIGHTNINGS: DEFAULT_MAX_TRACKED_LIGHTNINGS,
                            CONF_TIME_WINDOW: DEFAULT_TIME_WINDOW,
                            CONF_ENABLE_GEOCODING: DEFAULT_ENABLE_GEOCODING,
                        },
                    )
            else:  # device_tracker mode
                if not user_input.get(CONF_DEVICE_TRACKER):
                    errors["base"] = "device_tracker_required"
                else:
                    await self.async_set_unique_id(
                        f"device_tracker-{user_input[CONF_DEVICE_TRACKER]}"
                    )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data={
                            CONF_NAME: user_input[CONF_NAME],
                            CONF_TRACKING_MODE: user_input[CONF_TRACKING_MODE],
                            CONF_DEVICE_TRACKER: user_input[CONF_DEVICE_TRACKER],
                            # Set default coordinates for initial setup
                            CONF_LATITUDE: self.hass.config.latitude,
                            CONF_LONGITUDE: self.hass.config.longitude,
                        },
                        options={
                            CONF_RADIUS: DEFAULT_RADIUS,
                            CONF_MAX_TRACKED_LIGHTNINGS: DEFAULT_MAX_TRACKED_LIGHTNINGS,
                            CONF_TIME_WINDOW: DEFAULT_TIME_WINDOW,
                            CONF_ENABLE_GEOCODING: DEFAULT_ENABLE_GEOCODING,
                        },
                    )


        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=self.hass.config.location_name
                    ): str,
                    vol.Required(
                        CONF_TRACKING_MODE, default=DEFAULT_TRACKING_MODE
                    ): vol.In(["Static", "Device Tracker"]),
                    vol.Optional(
                        CONF_LATITUDE,
                        default=self.hass.config.latitude,
                    ): cv.latitude,
                    vol.Optional(
                        CONF_LONGITUDE,
                        default=self.hass.config.longitude,
                    ): cv.longitude,
                    vol.Optional(CONF_DEVICE_TRACKER): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="device_tracker")
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a reconfiguration flow initialized by the user."""
        errors = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            # Validate input based on tracking mode
            if user_input[CONF_TRACKING_MODE] == "Static":
                if not user_input.get(CONF_LATITUDE) or not user_input.get(CONF_LONGITUDE):
                    errors["base"] = "static_location_required"
                else:
                    return self.async_update_reload_and_abort(
                        reconfigure_entry,
                        data_updates=user_input,
                    )
            else:  # device_tracker mode
                if not user_input.get(CONF_DEVICE_TRACKER):
                    errors["base"] = "device_tracker_required"
                else:
                    # Keep existing coordinates for fallback
                    update_data = user_input.copy()
                    if not update_data.get(CONF_LATITUDE):
                        update_data[CONF_LATITUDE] = reconfigure_entry.data.get(CONF_LATITUDE, self.hass.config.latitude)
                    if not update_data.get(CONF_LONGITUDE):
                        update_data[CONF_LONGITUDE] = reconfigure_entry.data.get(CONF_LONGITUDE, self.hass.config.longitude)
                    
                    return self.async_update_reload_and_abort(
                        reconfigure_entry,
                        data_updates=update_data,
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                data_schema=RECONFIGURE_SCHEMA,
                suggested_values=reconfigure_entry.data | (user_input or {}),
            ),
            description_placeholders={"name": reconfigure_entry.title},
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BlitzortungOptionsFlowHandler()


class BlitzortungOptionsFlowHandler(OptionsFlow):
    """Handle an options flow for Blitzortung."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_RADIUS,
                    default=self.config_entry.options.get(CONF_RADIUS, DEFAULT_RADIUS),
                ): int,
                vol.Optional(
                    CONF_ENABLE_GEOCODING,
                    default=self.config_entry.options.get(
                        CONF_ENABLE_GEOCODING,
                        DEFAULT_ENABLE_GEOCODING,
                    ),
                ): bool,
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
