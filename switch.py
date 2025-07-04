"""Support for switches through the SmartThings cloud API."""

from __future__ import annotations

from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

from pysmartthings import Attribute, Capability, Command

from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue

from . import FullDevice, SmartThingsConfigEntry
from .const import DOMAIN, INVALID_SWITCH_CATEGORIES, MAIN
from .entity import SmartThingsEntity

# Capabilities that are better represented by other domains
DEPRECATED_CAPABILITIES = {
    "mediaPlayback",
    "mediaTrackControl",
    "playbackShuffle",
    "playbackRepeat",
}
# Capabilities that are better represented by other domains
MEDIA_PLAYER_CAPABILITIES = {
    Capability.AUDIO_MUTE,
    Capability.MEDIA_INPUT_SOURCE,
    Capability.MEDIA_PLAYBACK_SHUFFLE,
    Capability.MEDIA_PLAYBACK,
    Capability.MEDIA_TRACK_CONTROL,
    Capability.SPEECH_SYNTHESIS,
    Capability.AUDIO_VOLUME,
}


@dataclass(frozen=True, kw_only=True)
class SmartThingsSwitchEntityDescription(SwitchEntityDescription):
    """Class describing SmartThings switch entities."""

    status_attribute: Attribute | str
    on_key: str
    on_command: Command
    off_command: Command
    component: str = MAIN
    deprecated_in_favor_of_other_platform: str | None = None


@dataclass(frozen=True, kw_only=True)
class SmartThingsCommandSwitchEntityDescription(SwitchEntityDescription):
    """Class describing SmartThings switch entities."""

    status_attribute: Attribute | str
    on_key: str
    command: Command
    component: str = MAIN
    deprecated_in_favor_of_other_platform: str | None = None


@dataclass(frozen=True, kw_only=True)
class SmartThingsExecuteSwitchEntityDescription(SwitchEntityDescription):
    """Class describing SmartThings execute switch entities."""
    on_argument: list[Any]
    off_argument: list[Any]
    default_is_on: bool = False


CAPABILITY_TO_SWITCHES: dict[
    Capability | str, list[SmartThingsSwitchEntityDescription]
] = {
    "samsungce.powerCool": [
        SmartThingsSwitchEntityDescription(
            key="samsungce.powerCool",
            name="Power Cool",
            status_attribute="powerCool",
            on_key="on",
            on_command=Command.ACTIVATE,
            off_command=Command.DEACTIVATE,
        )
    ],
    "samsungce.powerFreeze": [
        SmartThingsSwitchEntityDescription(
            key="samsungce.powerFreeze",
            name="Power Freeze",
            status_attribute="powerFreeze",
            on_key="on",
            on_command=Command.ACTIVATE,
            off_command=Command.DEACTIVATE,
        )
    ],
    "samsungce.icemaker": [
        SmartThingsSwitchEntityDescription(
            key="samsungce.icemaker",
            name="Ice Maker",
            status_attribute="icemaker",
            on_key="on",
            on_command=Command.ON,
            off_command=Command.OFF,
            component="icemaker",
        )
    ],
}
CAPABILITY_TO_COMMAND_SWITCHES: dict[
    Capability | str, list[SmartThingsCommandSwitchEntityDescription]
] = {
    Capability.CUSTOM_DRYER_WRINKLE_PREVENT: [
        SmartThingsCommandSwitchEntityDescription(
            key=Capability.CUSTOM_DRYER_WRINKLE_PREVENT,
            name="Wrinkle Prevent",
            status_attribute="dryerWrinklePrevent",
            on_key="on",
            command=Command.SET_DRYER_WRINKLE_PREVENT,
        )
    ],
    "custom.spiMode": [
        SmartThingsCommandSwitchEntityDescription(
            key="custom.spiMode",
            name="SPI Mode",
            status_attribute="spiMode",
            on_key="on",
            command=Command.SET_SPI_MODE,
        )
    ],
    "custom.autoCleaningMode": [
        SmartThingsCommandSwitchEntityDescription(
            key="custom.autoCleaningMode",
            name="Auto Cleaning Mode",
            icon="mdi:shimmer",
            status_attribute="autoCleaningMode",
            on_key="on",
            command=Command.SET_AUTO_CLEANING_MODE,
        )
    ],
}

# Special switches for climate devices that use the 'execute' command
CLIMATE_EXECUTE_SWITCHES: list[SmartThingsExecuteSwitchEntityDescription] = [
    SmartThingsExecuteSwitchEntityDescription(
        key="light",
        name="Light",
        default_is_on=True,  # Nastaví predvolený stav na ZAPNUTÝ
        # Arguments are swapped to match the device's inverse logic
        on_argument=["/mode/vs/0", {"x.com.samsung.da.options": ["Light_Off"]}],
        off_argument=["/mode/vs/0", {"x.com.samsung.da.options": ["Light_On"]}],
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartThingsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add switches for a config entry."""
    entry_data = entry.runtime_data
    entities: list[
        SmartThingsSwitch
        | SmartThingsCommandSwitch
        | SmartThingsExecuteSwitch
        | SmartThingsGenericSwitch
    ] = []
    for device in entry_data.devices.values():
        # Standard and Command switches
        for capability, descriptions in CAPABILITY_TO_SWITCHES.items():
            if capability in device.status[MAIN]:
                for description in descriptions:
                    entities.append(SmartThingsSwitch(entry_data.client, device, description))
        for capability, descriptions in CAPABILITY_TO_COMMAND_SWITCHES.items():
            if capability in device.status[MAIN]:
                for description in descriptions:
                    entities.append(
                        SmartThingsCommandSwitch(entry_data.client, device, description)
                    )

        # Special Execute switches for climate devices
        if (
            Capability.AIR_CONDITIONER_MODE in device.status[MAIN]
            and Capability.EXECUTE in device.status[MAIN]
        ):
            for description in CLIMATE_EXECUTE_SWITCHES:
                entities.append(
                    SmartThingsExecuteSwitch(entry_data.client, device, description)
                )

        # Generic fallback switch
        if (
            Capability.SWITCH in device.status[MAIN]
            and not any(
                capability in device.status[MAIN]
                for capability in MEDIA_PLAYER_CAPABILITIES
            )
            and (
                (main_component := device.device.components.get(MAIN)) is not None
                and (
                    main_component.user_category not in INVALID_SWITCH_CATEGORIES
                    or main_component.manufacturer_category
                    not in INVALID_SWITCH_CATEGORIES
                )
            )
            and "samsungce.ehsFsvSettings" not in device.status[MAIN]
        ):
            entities.append(
                SmartThingsGenericSwitch(
                    entry_data.client,
                    device,
                    SmartThingsSwitchEntityDescription(
                        key=Attribute.SWITCH,
                        status_attribute=Attribute.SWITCH,
                        on_key="on",
                        on_command=Command.ON,
                        off_command=Command.OFF,
                        device_class=SwitchDeviceClass.SWITCH,
                    ),
                )
            )
        # Deprecation warnings
        if any(
            capability in device.status[MAIN] for capability in MEDIA_PLAYER_CAPABILITIES
        ):
            async_create_issue(
                hass,
                DOMAIN,
                f"deprecated_media_player_switch_{device.device.device_id}",
                breaks_in_ha_version="2025.10.0",
                is_fixable=False,
                is_persistent=True,
                severity=IssueSeverity.WARNING,
                translation_key="deprecated_media_player_switch",
                translation_placeholders={
                    "device_name": device.device.label,
                },
            )
        if (main_component := device.device.components.get(MAIN)) is not None and (
            main_component.user_category in INVALID_SWITCH_CATEGORIES
            or main_component.manufacturer_category in INVALID_SWITCH_CATEGORIES
        ):
            async_create_issue(
                hass,
                DOMAIN,
                f"deprecated_appliance_switch_{device.device.device_id}",
                breaks_in_ha_version="2025.10.0",
                is_fixable=False,
                is_persistent=True,
                severity=IssueSeverity.WARNING,
                translation_key="deprecated_appliance_switch",
                translation_placeholders={
                    "device_name": device.device.label,
                },
            )
        if "samsungce.ehsFsvSettings" in device.status[MAIN]:
            async_create_issue(
                hass,
                DOMAIN,
                f"deprecated_water_heater_switch_{device.device.device_id}",
                breaks_in_ha_version="2025.12.0",
                is_fixable=False,
                is_persistent=True,
                severity=IssueSeverity.WARNING,
                translation_key="deprecated_water_heater_switch",
                translation_placeholders={
                    "device_name": device.device.label,
                },
            )

    async_add_entities(entities)


class SmartThingsSwitch(SmartThingsEntity, SwitchEntity):
    """Define a SmartThings switch."""

    _attr_has_entity_name = False
    entity_description: SmartThingsSwitchEntityDescription

    def __init__(
        self,
        client: Coroutine[Any, Any, Any],
        device: FullDevice,
        description: SmartThingsSwitchEntityDescription,
    ) -> None:
        """Init the class."""
        super().__init__(client, device, {description.key}, component=description.component)
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{device.device.device_id}_{description.component}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return (
            self.get_attribute_value(
                self.entity_description.key, self.entity_description.status_attribute
            )
            == self.entity_description.on_key
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.execute_device_command(
            self.entity_description.key, self.entity_description.off_command
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.execute_device_command(
            self.entity_description.key, self.entity_description.on_command
        )


class SmartThingsCommandSwitch(SmartThingsEntity, SwitchEntity):
    """Define a SmartThings switch that uses a command with arguments."""

    _attr_has_entity_name = False
    entity_description: SmartThingsCommandSwitchEntityDescription

    def __init__(
        self,
        client: Coroutine[Any, Any, Any],
        device: FullDevice,
        description: SmartThingsCommandSwitchEntityDescription,
    ) -> None:
        """Init the class."""
        super().__init__(client, device, {description.key}, component=description.component)
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{device.device.device_id}_{description.component}_{description.key}"

    @property
    def icon(self) -> str | None:
        """Return the icon to use in the frontend, depending on the state."""
        if self.entity_description.key == "custom.spiMode":
            return "mdi:air-purifier" if self.is_on else "mdi:air-purifier-off"
        return self.entity_description.icon

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return (
            self.get_attribute_value(
                self.entity_description.key, self.entity_description.status_attribute
            )
            == self.entity_description.on_key
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.execute_device_command(
            self.entity_description.key, self.entity_description.command, argument="off"
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.execute_device_command(
            self.entity_description.key, self.entity_description.command, argument="on"
        )


class SmartThingsExecuteSwitch(SmartThingsEntity, SwitchEntity):
    """Define a SmartThings switch that uses the execute command."""

    _attr_has_entity_name = False

    entity_description: SmartThingsExecuteSwitchEntityDescription

    def __init__(
        self,
        client: Coroutine[Any, Any, Any],
        device: FullDevice,
        description: SmartThingsExecuteSwitchEntityDescription,
    ) -> None:
        """Init the class."""
        # This entity doesn't listen to a specific capability for state
        super().__init__(client, device, set())
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{device.device.device_id}_{description.key}"
        # Set the initial optimistic state from the description
        self._attr_is_on = description.default_is_on

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend, depending on the state."""
        return "mdi:led-on" if self.is_on else "mdi:led-off"

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.execute_device_command(
            Capability.EXECUTE,
            Command.EXECUTE,
            argument=self.entity_description.off_argument,
        )
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.execute_device_command(
            Capability.EXECUTE,
            Command.EXECUTE,
            argument=self.entity_description.on_argument,
        )
        self._attr_is_on = True
        self.async_write_ha_state()


class SmartThingsGenericSwitch(SmartThingsSwitch):
    """Define a generic SmartThings switch."""

    _attr_has_entity_name = True  # Generic switch will keep the default behavior

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return (
            self.get_attribute_value(Capability.SWITCH, self.entity_description.key)
            == self.entity_description.on_key
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.execute_device_command(
            Capability.SWITCH, self.entity_description.off_command
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.execute_device_command(
            Capability.SWITCH, self.entity_description.on_command
        )