"""Device connection and observed heater activity."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory

from .entity import CosaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CosaConnection(entry.runtime_data), CosaHeating(entry.runtime_data)])


class CosaConnection(CosaEntity, BinarySensorEntity):
    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "connection")

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def is_on(self):
        value = self.coordinator.data.get("device", {}).get("isConnected")
        return value if isinstance(value, bool) else None


class CosaHeating(CosaEntity, BinarySensorEntity):
    _attr_translation_key = "heating"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator):
        super().__init__(coordinator, "heating")

    @property
    def is_on(self):
        value = self.coordinator.data.get("combiState")
        return value == "on" if value in ("on", "off") else None
