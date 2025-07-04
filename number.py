"""Support for numbers through the SmartThings cloud API."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pysmartthings import Attribute, Capability, Command

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FullDevice, SmartThingsConfigEntry
from .const import DOMAIN, MAIN, UNIT_MAP
from .entity import SmartThingsEntity

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any


@dataclass(frozen=True, kw_only=True)
class SmartThingsNumberEntityDescription(NumberEntityDescription):
    """Class describing SmartThings number entities."""

    component: str = MAIN
    command: Command | None = None
    status_attribute: Attribute | str | None = None
    value_attribute: Attribute | str | None = None


CAPABILITY_TO_NUMBER: dict[
    Capability | str, list[SmartThingsNumberEntityDescription]
] = {
    Capability.AUDIO_VOLUME: [
        SmartThingsNumberEntityDescription(
            key=Capability.AUDIO_VOLUME,  # Opravené: Používa sa Capability, nie Attribute
            name="Audio Volume",
            icon="mdi:volume-high",
            native_min_value=0,
            native_max_value=100,
            native_step=1,
            mode=NumberMode.SLIDER,
            command=Command.SET_VOLUME,
            status_attribute=Attribute.VOLUME,
            native_unit_of_measurement=PERCENTAGE,
        )
    ],
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartThingsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add numbers for a config entry."""
    entry_data = entry.runtime_data
    entities: list[SmartThingsEntity] = []

    # Generic numbers
    for device in entry_data.devices.values():
        for capability_name, descriptions in CAPABILITY_TO_NUMBER.items():
            if capability_name in device.status[MAIN]:
                for description in descriptions:
                    entities.append(SmartThingsNumber(entry_data.client, device, description))

        # Specialized numbers
        if Capability.CUSTOM_WASHER_RINSE_CYCLES in device.status[MAIN]:
            entities.append(
                SmartThingsWasherRinseCyclesNumberEntity(entry_data.client, device)
            )
        if "hood" in device.status and (
            Capability.SAMSUNG_CE_HOOD_FAN_SPEED in device.status["hood"]
            and Capability.SAMSUNG_CE_CONNECTION_STATE
            not in device.status["hood"]
        ):
            entities.append(SmartThingsHoodNumberEntity(entry_data.client, device))
        for component in ("cooler", "freezer"):
            if component in device.status and (
                Capability.THERMOSTAT_COOLING_SETPOINT in device.status[component]
            ):
                entities.append(
                    SmartThingsRefrigeratorTemperatureNumberEntity(
                        entry_data.client, device, component
                    )
                )
    async_add_entities(entities)


class SmartThingsNumber(SmartThingsEntity, NumberEntity):
    """Define a generic SmartThings number."""

    entity_description: SmartThingsNumberEntityDescription

    def __init__(
        self,
        client: Coroutine[Any, Any, Any],
        device: FullDevice,
        description: SmartThingsNumberEntityDescription,
    ) -> None:
        """Init the class."""
        super().__init__(client, device, {description.key})
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{device.device.device_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if not self.entity_description.status_attribute:
            return None
        return self.get_attribute_value(
            self.entity_description.key, self.entity_description.status_attribute
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        if self.entity_description.command:
            await self.execute_device_command(
                self.entity_description.key,
                self.entity_description.command,
                argument=int(value),
            )


class SmartThingsWasherRinseCyclesNumberEntity(SmartThingsEntity, NumberEntity):
    """Define a washer rinse cycles number."""

    _attr_mode = NumberMode.BOX
    _attr_name = "Rinse Cycles"
    _attr_entity_category = "config"

    def __init__(self, client: Coroutine[Any, Any, Any], device: FullDevice) -> None:
        """Init the class."""
        super().__init__(client, device, {Capability.CUSTOM_WASHER_RINSE_CYCLES})
        self._attr_unique_id = (
            f"{device.device.device_id}_{Capability.CUSTOM_WASHER_RINSE_CYCLES}"
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.get_attribute_value(
            Capability.CUSTOM_WASHER_RINSE_CYCLES, Attribute.WASHER_RINSE_CYCLES
        )

    @property
    def native_min_value(self) -> float:
        """Return the minimum value."""
        return min(self.supported_values)

    @property
    def native_max_value(self) -> float:
        """Return the maximum value."""
        return max(self.supported_values)

    @property
    def supported_values(self) -> list[int]:
        """Get the list of supported values."""
        if (
            values := self.get_attribute_value(
                Capability.CUSTOM_WASHER_RINSE_CYCLES,
                Attribute.SUPPORTED_WASHER_RINSE_CYCLES,
            )
        ) is None:
            return []
        return values

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.execute_device_command(
            Capability.CUSTOM_WASHER_RINSE_CYCLES,
            Command.SET_WASHER_RINSE_CYCLES,
            argument=int(value),
        )


class SmartThingsHoodNumberEntity(SmartThingsEntity, NumberEntity):
    """Define a hood number."""

    _attr_mode = NumberMode.SLIDER
    _attr_name = "Fan Speed"
    _attr_entity_category = "config"

    def __init__(self, client: Coroutine[Any, Any, Any], device: FullDevice) -> None:
        """Init the class."""
        super().__init__(client, device, {Capability.SAMSUNG_CE_HOOD_FAN_SPEED}, component="hood")
        self._attr_unique_id = f"{device.device.device_id}_hood_{Capability.SAMSUNG_CE_HOOD_FAN_SPEED}"

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.get_attribute_value(
            Capability.SAMSUNG_CE_HOOD_FAN_SPEED, Attribute.HOOD_FAN_SPEED
        )

    @property
    def native_min_value(self) -> float:
        """Return the minimum value."""
        if (
            min_value := self.get_attribute_value(
                Capability.SAMSUNG_CE_HOOD_FAN_SPEED, Attribute.SETTABLE_MIN_FAN_SPEED
            )
        ) is None:
            return 0
        return min_value

    @property
    def native_max_value(self) -> float:
        """Return the maximum value."""
        if (
            max_value := self.get_attribute_value(
                Capability.SAMSUNG_CE_HOOD_FAN_SPEED, Attribute.SETTABLE_MAX_FAN_SPEED
            )
        ) is None:
            return 0
        return max_value

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.execute_device_command(
            Capability.SAMSUNG_CE_HOOD_FAN_SPEED,
            Command.SET_HOOD_FAN_SPEED,
            argument=int(value),
        )


class SmartThingsRefrigeratorTemperatureNumberEntity(SmartThingsEntity, NumberEntity):
    """Define a refrigerator temperature number."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_entity_category = "config"

    def __init__(
        self, client: Coroutine[Any, Any, Any], device: FullDevice, component: str
    ) -> None:
        """Init the class."""
        super().__init__(client, device, {Capability.THERMOSTAT_COOLING_SETPOINT}, component=component)
        self._attr_name = f"{component.capitalize()} Temperature"
        self._attr_unique_id = f"{device.device.device_id}_{component}_{Capability.THERMOSTAT_COOLING_SETPOINT}"

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.get_attribute_value(
            Capability.THERMOSTAT_COOLING_SETPOINT, Attribute.COOLING_SETPOINT
        )

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""
        if (
            unit := self._internal_state[Capability.THERMOSTAT_COOLING_SETPOINT][
                Attribute.COOLING_SETPOINT
            ].unit
        ) is None:
            return UnitOfTemperature.CELSIUS
        return UNIT_MAP[unit]

    @property
    def native_min_value(self) -> float:
        """Return the minimum value."""
        if (
            rng := self.get_attribute_value(
                Capability.THERMOSTAT_COOLING_SETPOINT,
                Attribute.COOLING_SETPOINT_RANGE,
            )
        ) is None:
            return 0
        return rng[0]

    @property
    def native_max_value(self) -> float:
        """Return the maximum value."""
        if (
            rng := self.get_attribute_value(
                Capability.THERMOSTAT_COOLING_SETPOINT,
                Attribute.COOLING_SETPOINT_RANGE,
            )
        ) is None:
            return 0
        return rng[1]

    @property
    def native_step(self) -> float:
        """Return the step size."""
        if (
            rng := self.get_attribute_value(
                Capability.THERMOSTAT_COOLING_SETPOINT,
                Attribute.COOLING_SETPOINT_RANGE,
            )
        ) is None:
            return 1
        return rng[2]

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.execute_device_command(
            Capability.THERMOSTAT_COOLING_SETPOINT,
            Command.SET_COOLING_SETPOINT,
            argument=value,
        )