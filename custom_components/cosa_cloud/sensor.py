"""Measured room temperature and humidity; missing values stay unknown."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfTemperature

from .api import number
from .entity import CosaEntity

DESCRIPTIONS = (
    SensorEntityDescription(key="temperature", translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT),
    SensorEntityDescription(key="humidity", translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY, native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CosaSensor(entry.runtime_data, d) for d in DESCRIPTIONS])


class CosaSensor(CosaEntity, SensorEntity):
    def __init__(self, coordinator, description):
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        key = self.entity_description.key
        return number(self.coordinator.data.get(key), 0 if key == "humidity" else -40,
                      100 if key == "humidity" else 80)
