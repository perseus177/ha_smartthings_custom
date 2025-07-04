"""Support for SmartThings Cloud."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING # ZMENA: Pridaný import TYPE_CHECKING

from pysmartthings import (
    Attribute,
    Capability,
    Command,
    ComponentStatus,
    DeviceEvent,
    DeviceHealthEvent,
    SmartThings,
)
from pysmartthings.models import HealthStatus

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

# ZMENA: Import FullDevice je teraz v bloku TYPE_CHECKING, aby sa predišlo cyklickému importu
if TYPE_CHECKING:
    from . import FullDevice

from .const import DOMAIN, MAIN


class SmartThingsEntity(Entity):
    """Defines a SmartThings entity."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        client: SmartThings,
        device: "FullDevice", # Všimnite si úvodzovky, pomáha to s cyklickým importom
        capabilities: set[Capability],
        *,
        component: str = MAIN,
    ) -> None:
        """Initialize the instance."""
        self.client = client
        self.capabilities = capabilities
        self.component = component
        self._internal_state: ComponentStatus = {
            capability: device.status[component][capability]
            for capability in capabilities
            if capability in device.status[component]
        }
        self.device = device
        self._attr_unique_id = f"{device.device.device_id}_{component}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device.device_id)},
        )
        self._attr_available = device.online

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates."""
        await super().async_added_to_hass()
        for capability in self._internal_state:
            self.async_on_remove(
                self.client.add_device_capability_event_listener(
                    self.device.device.device_id,
                    self.component,
                    capability,
                    self._update_handler,
                )
            )
        self.async_on_remove(
            self.client.add_device_availability_event_listener(
                self.device.device.device_id, self._availability_handler
            )
        )
        self._update_attr()

    def _availability_handler(self, event: DeviceHealthEvent) -> None:
        self._attr_available = event.status != HealthStatus.OFFLINE
        self.async_write_ha_state()

    def _update_handler(self, event: DeviceEvent) -> None:
        self._internal_state[event.capability][event.attribute].value = event.value
        self._internal_state[event.capability][event.attribute].data = event.data
        self._handle_update()

    def supports_capability(self, capability: Capability) -> bool:
        """Test if device supports a capability."""
        return capability in self.device.status[self.component]

    def get_attribute_value(self, capability: Capability, attribute: Attribute) -> Any:
        """Get the value of a device attribute."""
        return self._internal_state[capability][attribute].value

    def _update_attr(self) -> None:
        """Update the attributes."""

    def _handle_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attr()
        self.async_write_ha_state()

    async def execute_device_command(
        self,
        capability: Capability,
        command: Command,
        argument: int | str | list[Any] | dict[str, Any] | None = None,
    ) -> None:
        """Execute a command on the device."""
        kwargs = {}
        if argument is not None:
            kwargs["argument"] = argument
        await self.client.execute_device_command(
            self.device.device.device_id, capability, command, self.component, **kwargs
        )