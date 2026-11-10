"""Curtains: Tuya curtain switches / motors (open, stop, close and position)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_NEW_DPS
from .entity import HawaiiEntity
from .hub import HawaiiHub
from .models import DpSpec, cover_channels

OPEN_WORDS = ("open", "on", "fz")
CLOSE_WORDS = ("close", "off", "zz")
STOP_WORDS = ("stop", "pause")


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
            channels = cover_channels(dev)
            for i, ch in enumerate(channels, 1):
                uid = f"{stable}_{ch['control'].dp}"
                if uid in added:
                    continue
                added.add(uid)
                name = "Curtain" if len(channels) == 1 else f"Curtain {i}"
                new.append(HawaiiCover(hub, stable, ch["control"], name, ch["set"], ch["state"]))
        if new:
            async_add_entities(new)

    @callback
    def on_new_dps(stable: str) -> None:
        add([stable])

    add(list(hub.devices))
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_NEW_DPS, on_new_dps))


def _pick(spec: DpSpec, words: tuple[str, ...]) -> str | None:
    options = [str(o) for o in spec.values.get("range") or []]
    for word in words:
        for option in options:
            if option.lower() == word:
                return option
    return None if options else words[0]


class HawaiiCover(HawaiiEntity, CoverEntity):
    """Curtain."""

    _attr_device_class = CoverDeviceClass.CURTAIN

    def __init__(self, hub: HawaiiHub, stable: str, control: DpSpec, name: str,
                 set_spec: DpSpec | None, state_spec: DpSpec | None) -> None:
        super().__init__(hub, stable, control, name)
        self._set = set_spec if set_spec and set_spec.writable else None
        self._state = state_spec or set_spec
        features = CoverEntityFeature(0)
        for flag, words in (
            (CoverEntityFeature.OPEN, OPEN_WORDS),
            (CoverEntityFeature.CLOSE, CLOSE_WORDS),
            (CoverEntityFeature.STOP, STOP_WORDS),
        ):
            if _pick(control, words):
                features |= flag
        if self._set:
            features |= CoverEntityFeature.SET_POSITION
        self._attr_supported_features = features

    def _percent(self, spec: DpSpec | None) -> int | None:
        if spec is None:
            return None
        raw = self.hub.value(self.stable, spec.dp)
        if raw is None:
            return None
        lo, hi = spec.values.get("min", 0), spec.values.get("max", 100)
        try:
            return max(0, min(100, round((float(raw) - lo) * 100 / ((hi - lo) or 100))))
        except (TypeError, ValueError):
            return None

    @property
    def current_cover_position(self) -> int | None:
        return self._percent(self._state)

    @property
    def is_closed(self) -> bool | None:
        pos = self.current_cover_position
        return None if pos is None else pos == 0

    async def _control(self, words: tuple[str, ...]) -> None:
        if value := _pick(self.spec, words):
            await self.hub.async_set(self.stable, self.spec.dp, value)

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._control(OPEN_WORDS)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._control(CLOSE_WORDS)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._control(STOP_WORDS)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        if self._set is None:
            return
        lo, hi = self._set.values.get("min", 0), self._set.values.get("max", 100)
        raw = round(lo + kwargs[ATTR_POSITION] * (hi - lo) / 100)
        await self.hub.async_set(self.stable, self._set.dp, raw)
