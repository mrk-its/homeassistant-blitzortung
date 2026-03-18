"""Config flow for blitzortung integration."""

from typing import TYPE_CHECKING, Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.device_tracker import DOMAIN as DEVICE_TRACKER_DOMAIN
from homeassistant.components.person import DOMAIN as PERSON_DOMAIN
from homeassistant.components.zone import DOMAIN as ZONE_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_CONFIG_TYPE,
    CONF_LOCATION_ENTITY,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    CONFIG_TYPE_COORDINATES,
    CONFIG_TYPE_ENTITY,
    DEFAULT_MAX_TRACKED_LIGHTNINGS,
    DEFAULT_RADIUS,
    DEFAULT_TIME_WINDOW,
    DOMAIN,
    ZONE_HOME,
)
from .utils import get_coordinates_from_entity

# Only allow location entities
LOCATION_ENTITY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(
        domain=[DEVICE_TRACKER_DOMAIN, PERSON_DOMAIN, ZONE_DOMAIN]
    )
)

CONFIG_TYPE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[
            CONFIG_TYPE_ENTITY,
            CONFIG_TYPE_COORDINATES,
        ],
        mode=selector.SelectSelectorMode.LIST,
        translation_key=CONF_CONFIG_TYPE,
    )
)


def _validate_input_entity(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> tuple[str, str]:
    """Validate user input for location entity."""
    location_entity = user_input[CONF_LOCATION_ENTITY]

    # Special handling for zone.home, which doesn't have a unique ID but its entity ID
    # is unique and stable.
    if location_entity == ZONE_HOME:
        if get_coordinates_from_entity(hass, location_entity) is None:
            raise BlitzortungNoCoordinatesError

        return location_entity, hass.states.get(location_entity).name

    entity_registry = er.async_get(hass)

    if TYPE_CHECKING:
        assert entity_registry is not None

    registry_entry = entity_registry.async_get(location_entity)

    if registry_entry is None or registry_entry.unique_id is None:
        raise BlitzortungNoUniqueIdError

    if get_coordinates_from_entity(hass, location_entity) is None:
        raise BlitzortungNoCoordinatesError

    return (
        f"{registry_entry.platform}_{registry_entry.unique_id}",
        registry_entry.original_name or registry_entry.name or location_entity,
    )


class BlitzortungConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Blitzortung."""

    VERSION = 6

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select how the user wants to configure the entry."""
        if user_input is not None:
            if user_input[CONF_CONFIG_TYPE] == CONFIG_TYPE_ENTITY:
                return await self.async_step_entity()
            return await self.async_step_coordinates()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONFIG_TYPE, default=CONFIG_TYPE_ENTITY
                    ): CONFIG_TYPE_SELECTOR,
                }
            ),
        )

    async def async_step_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the entry using a location entity."""
        errors = {}

        if user_input is not None:
            try:
                unique_id, title = _validate_input_entity(self.hass, user_input)
            except BlitzortungNoUniqueIdError:
                errors["base"] = "entity_without_unique_id"
            except BlitzortungNoCoordinatesError:
                errors["base"] = "entity_without_coordinates"
            else:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                data = {
                    CONF_NAME: title,
                    CONF_CONFIG_TYPE: CONFIG_TYPE_ENTITY,
                    CONF_LOCATION_ENTITY: user_input[CONF_LOCATION_ENTITY],
                }

                return self.async_create_entry(
                    title=title,
                    data=data,
                    options={
                        CONF_RADIUS: DEFAULT_RADIUS,
                        CONF_MAX_TRACKED_LIGHTNINGS: DEFAULT_MAX_TRACKED_LIGHTNINGS,
                        CONF_TIME_WINDOW: DEFAULT_TIME_WINDOW,
                    },
                )

        return self.async_show_form(
            step_id="entity",
            data_schema=vol.Schema(
                {vol.Required(CONF_LOCATION_ENTITY): LOCATION_ENTITY_SELECTOR}
            ),
            errors=errors,
        )

    async def async_step_coordinates(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the entry using fixed coordinates."""
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_LATITUDE]}-{user_input[CONF_LONGITUDE]}"
            )
            self._abort_if_unique_id_configured()

            data = {
                CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
                **user_input,
            }

            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data=data,
                options={
                    CONF_RADIUS: DEFAULT_RADIUS,
                    CONF_MAX_TRACKED_LIGHTNINGS: DEFAULT_MAX_TRACKED_LIGHTNINGS,
                    CONF_TIME_WINDOW: DEFAULT_TIME_WINDOW,
                },
            )

        return self.async_show_form(
            step_id="coordinates",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME,
                        default=self.hass.config.location_name,
                    ): str,
                    vol.Required(
                        CONF_LATITUDE,
                        default=self.hass.config.latitude,
                    ): cv.latitude,
                    vol.Required(
                        CONF_LONGITUDE,
                        default=self.hass.config.longitude,
                    ): cv.longitude,
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry (coordinates only)."""
        entry = self._get_reconfigure_entry()

        # Only coordinate entries can be reconfigured this way.
        # Entity entries show a read-only notice and abort immediately.
        config_type = entry.data[CONF_CONFIG_TYPE]
        if config_type == CONFIG_TYPE_ENTITY:
            return self.async_abort(reason="reconfigure_not_supported")

        if user_input is not None:
            unique_id = f"{user_input[CONF_LATITUDE]}-{user_input[CONF_LONGITUDE]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_update_reload_and_abort(
                entry,
                unique_id=unique_id,
                data_updates=user_input,
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_LATITUDE,
                            default=self.hass.config.latitude,
                        ): cv.latitude,
                        vol.Required(
                            CONF_LONGITUDE,
                            default=self.hass.config.longitude,
                        ): cv.longitude,
                    }
                ),
                suggested_values=entry.data | (user_input or {}),
            ),
            description_placeholders={"name": entry.title},
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


class BlitzortungNoUniqueIdError(HomeAssistantError):
    """Raised when the selected entity does not have a unique ID."""


class BlitzortungNoCoordinatesError(HomeAssistantError):
    """Raised when the selected entity does not have coordinates."""
