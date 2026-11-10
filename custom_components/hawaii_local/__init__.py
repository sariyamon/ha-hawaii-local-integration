"""Hawaii Local: sign in with the Tuya app once, control every switch locally."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .hub import HawaiiHub

PLATFORMS = [Platform.SWITCH]

type HawaiiConfigEntry = ConfigEntry[HawaiiHub]


async def async_setup_entry(hass: HomeAssistant, entry: HawaiiConfigEntry) -> bool:
    hub = HawaiiHub(hass, entry)
    await hub.async_start()
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HawaiiConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_stop()
    return ok


async def _options_updated(hass: HomeAssistant, entry: HawaiiConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
