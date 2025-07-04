"""Support for climate devices through the SmartThings cloud API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pysmartthings import Attribute, Capability, Command, SmartThings

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    SWING_BOTH,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_VERTICAL,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FullDevice, SmartThingsConfigEntry
from .const import DOMAIN, MAIN, UNIT_MAP
from .entity import SmartThingsEntity

# ... (všetky konštanty zostávajú rovnaké) ...
MODE_TO_STATE = {
    "auto": HVACMode.HEAT_COOL,
    "cool": HVACMode.COOL,
    "eco": HVACMode.AUTO,
    "rush hour": HVACMode.AUTO,
    "emergency heat": HVACMode.HEAT,
    "heat": HVACMode.HEAT,
    "off": HVACMode.OFF,
}
STATE_TO_MODE = {
    HVACMode.HEAT_COOL: "auto",
    HVACMode.COOL: "cool",
    HVACMode.HEAT: "heat",
    HVACMode.OFF: "off",
}
OPERATING_STATE_TO_ACTION = {
    "cooling": HVACAction.COOLING,
    "fan only": HVACAction.FAN,
    "heating": HVACAction.HEATING,
    "idle": HVACAction.IDLE,
    "pending cool": HVACAction.COOLING,
    "pending heat": HVACAction.HEATING,
    "vent economizer": HVACAction.FAN,
    "wind": HVACAction.FAN,
}
AC_MODE_TO_STATE = {
    "auto": HVACMode.AUTO,
    "cool": HVACMode.COOL,
    "dry": HVACMode.DRY,
    "coolClean": HVACMode.COOL,
    "dryClean": HVACMode.DRY,
    "heat": HVACMode.HEAT,
    "heatClean": HVACMode.HEAT,
    "fanOnly": HVACMode.FAN_ONLY,
    "fan": HVACMode.FAN_ONLY,
    "wind": HVACMode.FAN_ONLY,
}
STATE_TO_AC_MODE = {
    HVACMode.AUTO: "auto",
    HVACMode.COOL: "cool",
    HVACMode.DRY: "dry",
    HVACMode.HEAT: "heat",
    HVACMode.FAN_ONLY: "fanOnly",
}
SWING_TO_FAN_OSCILLATION = {
    SWING_BOTH: "all",
    SWING_HORIZONTAL: "horizontal",
    SWING_VERTICAL: "vertical",
    SWING_OFF: "fixed",
}
FAN_OSCILLATION_TO_SWING = {
    value: key for key, value in SWING_TO_FAN_OSCILLATION.items()
}
HEAT_PUMP_AC_MODE_TO_HA = {
    "auto": HVACMode.AUTO,
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
}
HA_MODE_TO_HEAT_PUMP_AC_MODE = {v: k for k, v in HEAT_PUMP_AC_MODE_TO_HA.items()}
WIND = "wind"
FAN = "fan"
WINDFREE = "windFree"
_LOGGER = logging.getLogger(__name__)
AC_CAPABILITIES = [
    Capability.AIR_CONDITIONER_MODE,
    Capability.AIR_CONDITIONER_FAN_MODE,
    Capability.SWITCH,
    Capability.TEMPERATURE_MEASUREMENT,
    Capability.THERMOSTAT_COOLING_SETPOINT,
]
THERMOSTAT_CAPABILITIES = [
    Capability.TEMPERATURE_MEASUREMENT,
    Capability.THERMOSTAT_HEATING_SETPOINT,
    Capability.THERMOSTAT_MODE,
]
HEAT_PUMP_CAPABILITIES = [
    Capability.TEMPERATURE_MEASUREMENT,
    Capability.CUSTOM_THERMOSTAT_SETPOINT_CONTROL,
    Capability.AIR_CONDITIONER_MODE,
    Capability.THERMOSTAT_COOLING_SETPOINT,
    Capability.SWITCH,
]

async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartThingsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add climate entities for a config entry."""
    entry_data = entry.runtime_data
    entities: list[ClimateEntity] = [
        SmartThingsAirConditioner(entry_data.client, device)
        for device in entry_data.devices.values()
        if all(capability in device.status[MAIN] for capability in AC_CAPABILITIES)
    ]
    entities.extend(
        SmartThingsThermostat(entry_data.client, device)
        for device in entry_data.devices.values()
        if all(
            capability in device.status[MAIN] for capability in THERMOSTAT_CAPABILITIES
        )
    )
    entities.extend(
        SmartThingsHeatPumpZone(entry_data.client, device, component)
        for device in entry_data.devices.values()
        for component in device.status
        if component in {"INDOOR", "INDOOR1", "INDOOR2"}
        and all(
            capability in device.status[component]
            for capability in HEAT_PUMP_CAPABILITIES
        )
    )
    async_add_entities(entities)


class SmartThingsThermostat(SmartThingsEntity, ClimateEntity):
    """Define a SmartThings climate entities."""

    _attr_name = None

    def __init__(self, client: SmartThings, device: FullDevice) -> None:
        """Init the class."""
        super().__init__(
            client,
            device,
            {
                Capability.THERMOSTAT_FAN_MODE,
                Capability.THERMOSTAT_MODE,
                Capability.TEMPERATURE_MEASUREMENT,
                Capability.THERMOSTAT_HEATING_SETPOINT,
                Capability.THERMOSTAT_OPERATING_STATE,
                Capability.THERMOSTAT_COOLING_SETPOINT,
                Capability.RELATIVE_HUMIDITY_MEASUREMENT,
            },
        )
        self._attr_supported_features = self._determine_features()

    def _determine_features(self) -> ClimateEntityFeature:
        flags = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        if self.supports_capability(Capability.THERMOSTAT_FAN_MODE):
            flags |= ClimateEntityFeature.FAN_MODE
        return flags

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        await self.execute_device_command(
            Capability.THERMOSTAT_FAN_MODE,
            Command.SET_THERMOSTAT_FAN_MODE,
            argument=fan_mode,
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target operation mode."""
        await self.execute_device_command(
            Capability.THERMOSTAT_MODE,
            Command.SET_THERMOSTAT_MODE,
            argument=STATE_TO_MODE[hvac_mode],
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new operation mode and target temperatures."""
        hvac_mode = self.hvac_mode
        if operation_state := kwargs.get(ATTR_HVAC_MODE):
            await self.async_set_hvac_mode(operation_state)
            hvac_mode = operation_state

        heating_setpoint = None
        cooling_setpoint = None
        if hvac_mode == HVACMode.HEAT:
            heating_setpoint = kwargs.get(ATTR_TEMPERATURE)
        elif hvac_mode == HVACMode.COOL:
            cooling_setpoint = kwargs.get(ATTR_TEMPERATURE)
        else:
            heating_setpoint = kwargs.get(ATTR_TARGET_TEMP_LOW)
            cooling_setpoint = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        tasks = []
        if heating_setpoint is not None:
            tasks.append(
                self.execute_device_command(
                    Capability.THERMOSTAT_HEATING_SETPOINT,
                    Command.SET_HEATING_SETPOINT,
                    argument=round(heating_setpoint, 3),
                )
            )
        if cooling_setpoint is not None:
            tasks.append(
                self.execute_device_command(
                    Capability.THERMOSTAT_COOLING_SETPOINT,
                    Command.SET_COOLING_SETPOINT,
                    argument=round(cooling_setpoint, 3),
                )
            )
        await asyncio.gather(*tasks)

    @property
    def current_humidity(self) -> float | None:
        """Return the current humidity."""
        if self.supports_capability(Capability.RELATIVE_HUMIDITY_MEASUREMENT):
            return self.get_attribute_value(
                Capability.RELATIVE_HUMIDITY_MEASUREMENT, Attribute.HUMIDITY
            )
        return None

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.get_attribute_value(
            Capability.TEMPERATURE_MEASUREMENT, Attribute.TEMPERATURE
        )

    @property
    def fan_mode(self) -> str | None:
        """Return the fan setting."""
        return self.get_attribute_value(
            Capability.THERMOSTAT_FAN_MODE, Attribute.THERMOSTAT_FAN_MODE
        )

    @property
    def fan_modes(self) -> list[str]:
        """Return the list of available fan modes."""
        return self.get_attribute_value(
            Capability.THERMOSTAT_FAN_MODE, Attribute.SUPPORTED_THERMOSTAT_FAN_MODES
        )

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running hvac operation if supported."""
        if not self.supports_capability(Capability.THERMOSTAT_OPERATING_STATE):
            return None
        return OPERATING_STATE_TO_ACTION.get(
            self.get_attribute_value(
                Capability.THERMOSTAT_OPERATING_STATE,
                Attribute.THERMOSTAT_OPERATING_STATE,
            )
        )

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return current operation ie. heat, cool, idle."""
        return MODE_TO_STATE.get(
            self.get_attribute_value(
                Capability.THERMOSTAT_MODE, Attribute.THERMOSTAT_MODE
            )
        )

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available operation modes."""
        if (
            supported_thermostat_modes := self.get_attribute_value(
                Capability.THERMOSTAT_MODE, Attribute.SUPPORTED_THERMOSTAT_MODES
            )
        ) is None:
            return []
        return [
            state
            for mode in supported_thermostat_modes
            if (state := MODE_TO_STATE.get(mode)) is not None
        ]

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        if self.hvac_mode == HVACMode.COOL:
            return self.get_attribute_value(
                Capability.THERMOSTAT_COOLING_SETPOINT, Attribute.COOLING_SETPOINT
            )
        if self.hvac_mode == HVACMode.HEAT:
            return self.get_attribute_value(
                Capability.THERMOSTAT_HEATING_SETPOINT, Attribute.HEATING_SETPOINT
            )
        return None

    @property
    def target_temperature_high(self) -> float | None:
        """Return the highbound target temperature we try to reach."""
        if self.hvac_mode == HVACMode.HEAT_COOL:
            return self.get_attribute_value(
                Capability.THERMOSTAT_COOLING_SETPOINT, Attribute.COOLING_SETPOINT
            )
        return None

    @property
    def target_temperature_low(self) -> float | None:
        """Return the lowbound target temperature we try to reach."""
        if self.hvac_mode == HVACMode.HEAT_COOL:
            return self.get_attribute_value(
                Capability.THERMOSTAT_HEATING_SETPOINT, Attribute.HEATING_SETPOINT
            )
        return None

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement."""
        if (
            unit := self._internal_state[Capability.TEMPERATURE_MEASUREMENT][
                Attribute.TEMPERATURE
            ].unit
        ) is None:
            return UnitOfTemperature.CELSIUS
        return UNIT_MAP[unit]


class SmartThingsAirConditioner(SmartThingsEntity, ClimateEntity):
    """Define a SmartThings Air Conditioner."""

    _attr_name = None

    def __init__(self, client: SmartThings, device: FullDevice) -> None:
        """Init the class."""
        super().__init__(
            client,
            device,
            {
                Capability.AIR_CONDITIONER_MODE,
                Capability.SWITCH,
                Capability.FAN_OSCILLATION_MODE,
                Capability.AIR_CONDITIONER_FAN_MODE,
                Capability.THERMOSTAT_COOLING_SETPOINT,
                Capability.TEMPERATURE_MEASUREMENT,
                Capability.CUSTOM_AIR_CONDITIONER_OPTIONAL_MODE,
                Capability.DEMAND_RESPONSE_LOAD_CONTROL,
                Capability.EXECUTE,
            },
        )
        self._attr_hvac_modes = self._determine_hvac_modes()
        if self.supports_capability(Capability.FAN_OSCILLATION_MODE):
            self._attr_swing_modes = self._determine_swing_modes()
        self._attr_supported_features = self._determine_supported_features()

    @property
    def swing_mode(self) -> str:
        """Return the swing setting."""
        return FAN_OSCILLATION_TO_SWING.get(
            self.get_attribute_value(
                Capability.FAN_OSCILLATION_MODE, Attribute.FAN_OSCILLATION_MODE
            ),
            SWING_OFF,
        )

    @property
    def swing_modes(self) -> list[str] | None:
        """Return the list of available swing modes."""
        supported = self.get_attribute_value(
            Capability.FAN_OSCILLATION_MODE,
            Attribute.SUPPORTED_FAN_OSCILLATION_MODES,
        )
        if supported:
            return [
            ha_mode
            for mode in supported
            if (ha_mode := FAN_OSCILLATION_TO_SWING.get(mode)) is not None
            ]
        fallback = self.get_attribute_value(
            Capability.FAN_OSCILLATION_MODE, Attribute.FAN_OSCILLATION_MODE
        )
        if fallback:
            return [SWING_OFF, SWING_BOTH, SWING_VERTICAL, SWING_HORIZONTAL]
        return None

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set new target swing mode."""
        result = await self.execute_device_command(
            Capability.FAN_OSCILLATION_MODE,
            Command.SET_FAN_OSCILLATION_MODE,
            argument=[SWING_TO_FAN_OSCILLATION[swing_mode]],
        )
        if result is not None:
            self._internal_state[Capability.FAN_OSCILLATION_MODE][
                Attribute.FAN_OSCILLATION_MODE
            ].value = SWING_TO_FAN_OSCILLATION[swing_mode]
        self.async_write_ha_state()

    def _determine_supported_features(self) -> ClimateEntityFeature:
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        if self.supports_capability(Capability.FAN_OSCILLATION_MODE):
            features |= ClimateEntityFeature.SWING_MODE
        if self.preset_modes:
            features |= ClimateEntityFeature.PRESET_MODE
        return features

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        await self.execute_device_command(
            Capability.AIR_CONDITIONER_FAN_MODE,
            Command.SET_FAN_MODE,
            argument=fan_mode,
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target operation mode."""
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return
        tasks = []
        if self.get_attribute_value(Capability.SWITCH, Attribute.SWITCH) == "off":
            tasks.append(self.async_turn_on())

        mode = STATE_TO_AC_MODE.get(hvac_mode)
        if hvac_mode == HVACMode.FAN_ONLY:
            ac_modes = self.get_attribute_value(
                Capability.AIR_CONDITIONER_MODE, Attribute.SUPPORTED_AC_MODES
            )
            if ac_modes:
                for fan_mode in (WIND, FAN):
                    if fan_mode in ac_modes:
                        mode = fan_mode
                        break
        
        if mode:
            tasks.append(
                self.execute_device_command(
                    Capability.AIR_CONDITIONER_MODE,
                    Command.SET_AIR_CONDITIONER_MODE,
                    argument=mode,
                )
            )
        await asyncio.gather(*tasks)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        tasks = []
        if operation_mode := kwargs.get(ATTR_HVAC_MODE):
            if operation_mode == HVACMode.OFF:
                tasks.append(self.async_turn_off())
            else:
                if (
                    self.get_attribute_value(Capability.SWITCH, Attribute.SWITCH)
                    == "off"
                ):
                    tasks.append(self.async_turn_on())
                tasks.append(self.async_set_hvac_mode(operation_mode))
        tasks.append(
            self.execute_device_command(
                Capability.THERMOSTAT_COOLING_SETPOINT,
                Command.SET_COOLING_SETPOINT,
                argument=kwargs[ATTR_TEMPERATURE],
            )
        )
        await asyncio.gather(*tasks)

    async def async_turn_on(self) -> None:
        """Turn device on."""
        await self.execute_device_command(
            Capability.SWITCH,
            Command.ON,
        )

    async def async_turn_off(self) -> None:
        """Turn device off."""
        await self.execute_device_command(
            Capability.SWITCH,
            Command.OFF,
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.get_attribute_value(
            Capability.TEMPERATURE_MEASUREMENT, Attribute.TEMPERATURE
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return device specific state attributes."""
        if not self.supports_capability(Capability.DEMAND_RESPONSE_LOAD_CONTROL):
            return None

        drlc_status = self.get_attribute_value(
            Capability.DEMAND_RESPONSE_LOAD_CONTROL,
            Attribute.DEMAND_RESPONSE_LOAD_CONTROL_STATUS,
        )
        res = {}
        for key in ("duration", "start", "override", "drlcLevel"):
            if key in drlc_status:
                dict_key = {"drlcLevel": "drlc_status_level"}.get(
                    key, f"drlc_status_{key}"
                )
                res[dict_key] = drlc_status[key]
        return res

    @property
    def fan_mode(self) -> str:
        """Return the fan setting."""
        return self.get_attribute_value(
            Capability.AIR_CONDITIONER_FAN_MODE, Attribute.FAN_MODE
        )

    @property
    def fan_modes(self) -> list[str]:
        """Return the list of available fan modes."""
        return self.get_attribute_value(
            Capability.AIR_CONDITIONER_FAN_MODE, Attribute.SUPPORTED_AC_FAN_MODES
        )

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return current operation ie. heat, cool, idle."""
        if self.get_attribute_value(Capability.SWITCH, Attribute.SWITCH) == "off":
            return HVACMode.OFF
        return AC_MODE_TO_STATE.get(
            self.get_attribute_value(
                Capability.AIR_CONDITIONER_MODE, Attribute.AIR_CONDITIONER_MODE
            )
        )

    @property
    def target_temperature(self) -> float:
        """Return the temperature we try to reach."""
        return self.get_attribute_value(
            Capability.THERMOSTAT_COOLING_SETPOINT, Attribute.COOLING_SETPOINT
        )

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement."""
        unit = self._internal_state[Capability.TEMPERATURE_MEASUREMENT][
            Attribute.TEMPERATURE
        ].unit
        assert unit
        return UNIT_MAP[unit]

    def _determine_swing_modes(self) -> list[str] | None:
        """Return the list of available swing modes."""
        if (
            supported_modes := self.get_attribute_value(
                Capability.FAN_OSCILLATION_MODE,
                Attribute.SUPPORTED_FAN_OSCILLATION_MODES,
            )
        ) is None:
            return None
        return [FAN_OSCILLATION_TO_SWING.get(m, SWING_OFF) for m in supported_modes]

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set swing mode."""
        await self.execute_device_command(
            Capability.FAN_OSCILLATION_MODE,
            Command.SET_FAN_OSCILLATION_MODE,
            argument=SWING_TO_FAN_OSCILLATION[swing_mode],
        )

    @property
    def swing_mode(self) -> str:
        """Return the swing setting."""
        return FAN_OSCILLATION_TO_SWING.get(
            self.get_attribute_value(
                Capability.FAN_OSCILLATION_MODE, Attribute.FAN_OSCILLATION_MODE
            ),
            SWING_OFF,
        )

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        if self.supports_capability(Capability.CUSTOM_AIR_CONDITIONER_OPTIONAL_MODE):
            mode = self.get_attribute_value(
                Capability.CUSTOM_AIR_CONDITIONER_OPTIONAL_MODE,
                Attribute.AC_OPTIONAL_MODE,
            )
            if mode == WINDFREE:
                return WINDFREE
        return None

    @property
    def preset_modes(self) -> list[str] | None:
        """Return a list of available preset modes, including custom ones."""
        modes = []
        if self.supports_capability(Capability.CUSTOM_AIR_CONDITIONER_OPTIONAL_MODE):
            supported_modes = self.get_attribute_value(
                Capability.CUSTOM_AIR_CONDITIONER_OPTIONAL_MODE,
                Attribute.SUPPORTED_AC_OPTIONAL_MODE,
            )
            if supported_modes and WINDFREE in supported_modes:
                modes.append(WINDFREE)
        
        # Použijeme self.device namiesto self._device
        model = self.device.device.ocf.model_number if self.device.device.ocf else None
        if model and "ARTIK051_KRAC_18K" in model:
            custom_modes = ["2-Step", "Fast Turbo", "Comfort", "Quiet", "off"]
            for mode in custom_modes:
                if mode not in modes:
                    modes.append(mode)

        return modes if modes else None

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new target preset mode."""
        preset_mode_lower = preset_mode.lower()
        command_option = None

        if preset_mode_lower == "fast turbo":
            command_option = "Comode_Speed"
        elif preset_mode_lower == "comfort":
            command_option = "Comode_Comfort"
        elif preset_mode_lower == "quiet":
            command_option = "Comode_Quiet"
        elif preset_mode_lower == "2-step":
            command_option = "Comode_2Step"
        elif preset_mode_lower == "off":
            command_option = "Comode_Off"			

        if command_option:
            _LOGGER.debug(
                "Sending custom execute command for preset '%s' with option: %s",
                preset_mode,
                command_option,
            )
            # --- FINÁLNA ZMENA ---
            # Použijeme 'x.com.samsung.da.options' a hodnotu pošleme ako pole.
            payload = {"x.com.samsung.da.options": [command_option]}
            await self.execute_device_command(
                "execute", "execute", argument=["/mode/vs/0", payload]
            )
        else:
            _LOGGER.debug("Sending standard command for preset '%s'", preset_mode)
            await self.execute_device_command(
                Capability.CUSTOM_AIR_CONDITIONER_OPTIONAL_MODE,
                Command.SET_AC_OPTIONAL_MODE,
                argument=preset_mode,
            )
        self.async_write_ha_state()

    def _determine_hvac_modes(self) -> list[HVACMode]:
        """Determine the supported HVAC modes."""
        modes = [HVACMode.OFF]
        ac_modes = self.get_attribute_value(
            Capability.AIR_CONDITIONER_MODE, Attribute.SUPPORTED_AC_MODES
        )
        if ac_modes is not None:
            modes.extend(
                state
                for mode in ac_modes
                if (state := AC_MODE_TO_STATE.get(mode)) is not None
                and state not in modes
            )
        return modes


class SmartThingsHeatPumpZone(SmartThingsEntity, ClimateEntity):
    """Define a SmartThings heat pump zone."""

    _attr_name = None

    def __init__(self, client: SmartThings, device: FullDevice, component: str) -> None:
        """Init the class."""
        super().__init__(
            client,
            device,
            {
                Capability.AIR_CONDITIONER_MODE,
                Capability.SWITCH,
                Capability.CUSTOM_THERMOSTAT_SETPOINT_CONTROL,
                Capability.THERMOSTAT_COOLING_SETPOINT,
                Capability.TEMPERATURE_MEASUREMENT,
            },
            component=component,
        )
        self._attr_hvac_modes = self._determine_hvac_modes()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{device.device.device_id}_{component}")},
            via_device=(DOMAIN, device.device.device_id),
            name=f"{device.device.label} {component}",
        )

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the list of supported features."""
        features = ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
        if (
            self.get_attribute_value(
                Capability.AIR_CONDITIONER_MODE, Attribute.AIR_CONDITIONER_MODE
            )
            != "auto"
        ):
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        return features

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        min_setpoint = self.get_attribute_value(
            Capability.CUSTOM_THERMOSTAT_SETPOINT_CONTROL, Attribute.MINIMUM_SETPOINT
        )
        if min_setpoint == -1000:
            return DEFAULT_MIN_TEMP
        return min_setpoint

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        max_setpoint = self.get_attribute_value(
            Capability.CUSTOM_THERMOSTAT_SETPOINT_CONTROL, Attribute.MAXIMUM_SETPOINT
        )
        if max_setpoint == -1000:
            return DEFAULT_MAX_TEMP
        return max_setpoint

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target operation mode."""
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return
        if self.get_attribute_value(Capability.SWITCH, Attribute.SWITCH) == "off":
            await self.async_turn_on()

        await self.execute_device_command(
            Capability.AIR_CONDITIONER_MODE,
            Command.SET_AIR_CONDITIONER_MODE,
            argument=HA_MODE_TO_HEAT_PUMP_AC_MODE[hvac_mode],
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        await self.execute_device_command(
            Capability.THERMOSTAT_COOLING_SETPOINT,
            Command.SET_COOLING_SETPOINT,
            argument=kwargs[ATTR_TEMPERATURE],
        )

    async def async_turn_on(self) -> None:
        """Turn device on."""
        await self.execute_device_command(
            Capability.SWITCH,
            Command.ON,
        )

    async def async_turn_off(self) -> None:
        """Turn device off."""
        await self.execute_device_command(
            Capability.SWITCH,
            Command.OFF,
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.get_attribute_value(
            Capability.TEMPERATURE_MEASUREMENT, Attribute.TEMPERATURE
        )

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return current operation ie. heat, cool, idle."""
        if self.get_attribute_value(Capability.SWITCH, Attribute.SWITCH) == "off":
            return HVACMode.OFF
        return HEAT_PUMP_AC_MODE_TO_HA.get(
            self.get_attribute_value(
                Capability.AIR_CONDITIONER_MODE, Attribute.AIR_CONDITIONER_MODE
            )
        )

    @property
    def target_temperature(self) -> float:
        """Return the temperature we try to reach."""
        return self.get_attribute_value(
            Capability.THERMOSTAT_COOLING_SETPOINT, Attribute.COOLING_SETPOINT
        )

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement."""
        unit = self._internal_state[Capability.TEMPERATURE_MEASUREMENT][
            Attribute.TEMPERATURE
        ].unit
        assert unit
        return UNIT_MAP[unit]

    def _determine_hvac_modes(self) -> list[HVACMode]:
        """Determine the supported HVAC modes."""
        modes = [HVACMode.OFF]
        ac_modes = self.get_attribute_value(
            Capability.AIR_CONDITIONER_MODE, Attribute.SUPPORTED_AC_MODES
        )
        if ac_modes is not None:
            modes.extend(
                state
                for mode in ac_modes
                if (state := HEAT_PUMP_AC_MODE_TO_HA.get(mode)) is not None
            )
        return modes