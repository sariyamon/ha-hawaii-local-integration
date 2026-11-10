"""Base entity for Hawaii Local."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo as HADeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_DEVICE_UPDATE
from .hub import HawaiiHub
from .models import DpSpec


class HawaiiEntity(Entity):
    """One data point of one device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: HawaiiHub, stable: str, spec: DpSpec, name: str) -> None:
        self.hub = hub
        self.stable = stable
        self.spec = spec
        dev = hub.devices[stable]
        # Unique id is based on the hardware, so it survives a reset / re-pair.
        self._attr_unique_id = f"{stable}_{spec.dp}"
        self._attr_name = name
        self._attr_device_info = HADeviceInfo(
            identifiers={(DOMAIN, stable)},
            name=dev.name,
            manufacturer="Tuya",
            model=dev.product_name or dev.category,
            model_id=dev.product_id or None,
        )

    async def async_added_to_hass(self) -> None:
        self.hub.link_to_gateway(self.stable)
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DEVICE_UPDATE.format(self.stable), self.async_write_ha_state
            )
        )

    @property
    def available(self) -> bool:
        return self.hub.available(self.stable)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "dp": self.spec.dp,
            "code": self.spec.code,
            "connection": "local" if self.stable in self.hub.local_online else "cloud",
        }
