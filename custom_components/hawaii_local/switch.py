"""Switches: every on/off data point of every device."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_NEW_DPS
from .entity import HawaiiEntity
from .hub import HawaiiHub
from .models import CONFIG_CODES, dp_name


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    hub: HawaiiHub = entry.runtime_data
    added: set[str] = set()

    @callback
    def add(stables: list[str]) -> None:
        new = []
        for stable in stables:
            dev = hub.devices.get(stable)
            if dev is None or dev.is_gateway:
                continue
            specs = dev.switch_dps()
            for spec in specs:
                uid = f"{stable}_{spec.dp}"
                if uid not in added:
                    added.add(uid)
                    new.append(HawaiiSwitch(hub, stable, spec, dp_name(spec, len(specs))))
        if new:
            async_add_entities(new)

    @callback
    def on_new_dps(stable: str) -> None:
        add([stable])

    add(list(hub.devices))
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_NEW_DPS, on_new_dps))


class HawaiiSwitch(HawaiiEntity, SwitchEntity):
    """On/off data point."""

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        if self.spec.code and self.spec.code.startswith(CONFIG_CODES):
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool | None:
        value = self.hub.value(self.stable, self.spec.dp)
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hub.async_set(self.stable, self.spec.dp, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hub.async_set(self.stable, self.spec.dp, False)
