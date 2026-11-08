"""Cosa Cloud, maintained in the owner's repository."""
from homeassistant.const import Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .coordinator import CosaCoordinator

PLATFORMS = [Platform.CLIMATE, Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass, entry):
    coordinator = CosaCoordinator(hass, entry, async_get_clientsession(hass))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
