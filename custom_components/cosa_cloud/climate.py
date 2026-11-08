"""Thermostat controls reflecting only observed Cosa state."""
from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError

from .api import number
from .const import MAX_TEMP, MIN_TEMP, PRESETS
from .entity import CosaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CosaClimate(entry.runtime_data)])


class CosaClimate(CosaEntity, ClimateEntity):
    _attr_name = None
    _attr_translation_key = "thermostat"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [*PRESETS, "automatic", "schedule"]
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = 0.1
    _attr_supported_features = (ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
                                | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF)
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator):
        super().__init__(coordinator, "thermostat")

    @property
    def native_current_temperature(self):
        return number(self.coordinator.data.get("temperature"), -40, 80)

    @property
    def current_humidity(self):
        value = number(self.coordinator.data.get("humidity"), 0, 100)
        return round(value) if value is not None else None

    @property
    def native_target_temperature(self):
        data = self.coordinator.data
        option = data.get("option")
        value = data.get(option + "Temperature") if option in PRESETS.values() else data.get("targetTemperature")
        return number(value, MIN_TEMP, MAX_TEMP)

    @property
    def hvac_mode(self):
        data = self.coordinator.data
        if data.get("mode") == "manual" and data.get("option") == "frozen":
            return HVACMode.OFF
        if data.get("mode") in ("manual", "auto", "schedule", "turbo", "ventilation"):
            return HVACMode.HEAT
        return None

    @property
    def hvac_action(self):
        state = self.coordinator.data.get("combiState")
        if state == "on":
            return HVACAction.HEATING
        if state == "off":
            return HVACAction.OFF if self.hvac_mode == HVACMode.OFF else HVACAction.IDLE
        return None

    @property
    def preset_mode(self):
        data = self.coordinator.data
        if data.get("mode") == "auto":
            return "automatic"
        if data.get("mode") == "schedule":
            return "schedule"
        if data.get("mode") == "manual":
            return next((k for k, v in PRESETS.items() if v == data.get("option")), None)
        return None

    async def async_set_temperature(self, **kwargs):
        await self.coordinator.async_control("set_temperature", kwargs.get(ATTR_TEMPERATURE))

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode not in self.hvac_modes:
            raise HomeAssistantError("Unsupported HVAC mode")
        await self.coordinator.async_control("set_mode", "manual", "frozen" if hvac_mode == HVACMode.OFF else "home")

    async def async_set_preset_mode(self, preset_mode):
        if preset_mode in PRESETS:
            await self.coordinator.async_control("set_mode", "manual", PRESETS[preset_mode])
        elif preset_mode in ("automatic", "schedule"):
            await self.coordinator.async_control("set_mode", "auto" if preset_mode == "automatic" else "schedule")
        else:
            raise HomeAssistantError("Unsupported preset")

    async def async_turn_on(self):
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self):
        await self.async_set_hvac_mode(HVACMode.OFF)
