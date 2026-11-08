"""Cosa login, device selection and reauthentication."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .api import CosaAPI, CosaAuthError, CosaError
from .const import CONF_ENDPOINT_ID, DOMAIN

SCHEMA = vol.Schema({
    vol.Required(CONF_EMAIL): str,
    vol.Required(CONF_PASSWORD): selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
})


class CosaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._credentials = {}
        self._devices = []

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                api = CosaAPI(async_get_clientsession(self.hass), user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
                self._devices = await api.devices()
            except CosaAuthError:
                errors["base"] = "invalid_auth"
            except CosaError:
                errors["base"] = "cannot_connect"
            else:
                if not self._devices:
                    errors["base"] = "no_devices"
                else:
                    self._credentials = {k: user_input[k] for k in (CONF_EMAIL, CONF_PASSWORD)}
                    if len(self._devices) == 1:
                        return await self.async_step_device({CONF_ENDPOINT_ID: self._devices[0]["id"]})
                    return await self.async_step_device()
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_device(self, user_input=None):
        if user_input is not None:
            endpoint_id = user_input[CONF_ENDPOINT_ID]
            selected = next((d for d in self._devices if d["id"] == endpoint_id), None)
            if selected is None:
                return self.async_abort(reason="no_devices")
            await self.async_set_unique_id(endpoint_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=selected.get("name") or "Cosa",
                                           data=self._credentials | {CONF_ENDPOINT_ID: endpoint_id})
        choices = {d["id"]: d.get("name") or f"Cosa {i+1}" for i, d in enumerate(self._devices)}
        return self.async_show_form(step_id="device", data_schema=vol.Schema({
            vol.Required(CONF_ENDPOINT_ID): vol.In(choices)}))

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            entry = self._get_reauth_entry()
            try:
                api = CosaAPI(async_get_clientsession(self.hass), user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
                devices = await api.devices()
                if entry.data[CONF_ENDPOINT_ID] not in [d["id"] for d in devices]:
                    errors["base"] = "wrong_account"
                else:
                    return self.async_update_reload_and_abort(entry, data_updates=user_input)
            except CosaAuthError:
                errors["base"] = "invalid_auth"
            except CosaError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="reauth_confirm", data_schema=SCHEMA, errors=errors)
