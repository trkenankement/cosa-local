"""Explicit, on-demand actions for the Cosa device's own weekly program."""

import voluptuous as vol

from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import DOMAIN

TARGET = vol.Schema({vol.Required("entity_id"): cv.entity_id})
SET_SCHEDULE = TARGET.extend({vol.Required("schedule"): dict})


def _coordinator(hass, entity_id):
    entity = er.async_get(hass).async_get(entity_id)
    if entity is None or entity.domain != "climate" or entity.platform != DOMAIN:
        raise HomeAssistantError("Select a Cosa Cloud thermostat")
    coordinator = hass.data.get(DOMAIN, {}).get(entity.config_entry_id)
    if coordinator is None:
        raise HomeAssistantError("Cosa Cloud thermostat is not loaded")
    return coordinator


def register(hass):
    if hass.services.has_service(DOMAIN, "get_schedule"):
        return

    async def get_schedule(call):
        coordinator = _coordinator(hass, call.data["entity_id"])
        return {"schedule": await coordinator.async_get_schedule()}

    async def set_schedule(call):
        coordinator = _coordinator(hass, call.data["entity_id"])
        schedule = await coordinator.async_control("set_schedule", call.data["schedule"])
        return {"verified": True, "schedule": schedule}

    hass.services.async_register(
        DOMAIN, "get_schedule", get_schedule, schema=TARGET,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "set_schedule", set_schedule, schema=SET_SCHEDULE,
        supports_response=SupportsResponse.OPTIONAL,
    )


def unregister(hass):
    hass.services.async_remove(DOMAIN, "get_schedule")
    hass.services.async_remove(DOMAIN, "set_schedule")
