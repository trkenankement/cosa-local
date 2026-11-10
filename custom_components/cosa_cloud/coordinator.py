"""Poll only the selected Cosa device."""
from datetime import timedelta
import logging

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CosaAPI, CosaAuthError, CosaError
from .const import CONF_ENDPOINT_ID, DOMAIN

LOGGER = logging.getLogger(__name__)


class CosaCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, session):
        super().__init__(hass, LOGGER, name=DOMAIN, config_entry=entry,
                         update_interval=timedelta(seconds=60), always_update=False)
        self.endpoint_id = entry.data[CONF_ENDPOINT_ID]
        self.api = CosaAPI(session, entry.data["email"], entry.data["password"])

    async def _async_update_data(self):
        try:
            return await self.api.device(self.endpoint_id)
        except CosaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from None
        except CosaError as err:
            raise UpdateFailed(str(err)) from None

    async def async_control(self, operation, *args):
        try:
            return await getattr(self.api, operation)(self.endpoint_id, *args)
        except CosaAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from None
        except CosaError as err:
            raise HomeAssistantError(str(err)) from None
        finally:
            # State is always read back, never set optimistically.
            await self.async_request_refresh()

    async def async_get_schedule(self):
        try:
            return await self.api.get_schedule(self.endpoint_id)
        except CosaAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from None
        except CosaError as err:
            raise HomeAssistantError(str(err)) from None
