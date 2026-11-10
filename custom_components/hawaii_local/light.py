"""Lights: Tuya dimmer switches (on/off with brightness)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_NEW_DPS
from .entity import HawaiiEntity
from .hub import HawaiiHub
from .models import DpSpec, light_channels


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
            channels = light_channels(dev)
            for i, ch in enumerate(channels, 1):
                uid = f"{stable}_{ch['switch'].dp}"
                if uid in added:
                    continue
                added.add(uid)
                name = "Light" if len(channels) == 1 else f"Light {i}"
                new.append(HawaiiLight(hub, stable, ch["switch"], name, ch["bright"]))
        if new:
            async_add_entities(new)

    @callback
    def on_new_dps(stable: str) -> None:
        add([stable])

    add(list(hub.devices))
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_NEW_DPS, on_new_dps))


class HawaiiLight(HawaiiEntity, LightEntity):
    """Dimmer channel."""

    def __init__(self, hub: HawaiiHub, stable: str, switch: DpSpec, name: str,
                 bright: DpSpec | None) -> None:
        super().__init__(hub, stable, switch, name)
        self._bright = bright if bright and bright.writable else None
        mode = ColorMode.BRIGHTNESS if self._bright else ColorMode.ONOFF
        self._attr_color_mode = mode
        self._attr_supported_color_modes = {mode}

    def _range(self) -> tuple[int, int]:
        values = self._bright.values if self._bright else {}
        return int(values.get("min", 10)), int(values.get("max", 1000))

    @property
    def is_on(self) -> bool | None:
        value = self.hub.value(self.stable, self.spec.dp)
        return None if value is None else bool(value)

    @property
    def brightness(self) -> int | None:
        if self._bright is None:
            return None
        raw = self.hub.value(self.stable, self._bright.dp)
        if raw is None:
            return None
        _, hi = self._range()
        try:
            return max(1, min(255, round(float(raw) * 255 / hi)))
        except (TypeError, ValueError):
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        values: dict[str, Any] = {self.spec.dp: True}
        if self._bright is not None and ATTR_BRIGHTNESS in kwargs:
            lo, hi = self._range()
            values[self._bright.dp] = max(lo, min(hi, round(kwargs[ATTR_BRIGHTNESS] * hi / 255)))
        await self.hub.async_set_many(self.stable, values)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hub.async_set(self.stable, self.spec.dp, False)
