"""Shared device identity and availability."""
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class CosaEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.endpoint_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.endpoint_id)},
            name=coordinator.data.get("name") or "Cosa",
            manufacturer="Cosa / Nuvia", model="Smart Thermostat",
        )

    @property
    def available(self):
        return super().available and self.coordinator.data.get("device", {}).get("isConnected") is True
