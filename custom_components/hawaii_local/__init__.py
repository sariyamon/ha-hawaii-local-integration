"""Hawaii Local: sign in with the Tuya app once, control every switch locally."""
from __future__ import annotations

import json
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .hub import HawaiiHub

CARDS_URL = "/hawaii_local/hawaii-local-cards.js"
CARDS_FILE = Path(__file__).parent / "frontend" / "hawaii-local-cards.js"
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.COVER, Platform.LIGHT, Platform.SWITCH]

type HawaiiConfigEntry = ConfigEntry[HawaiiHub]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await _async_register_cards(hass)
    return True


async def _async_register_cards(hass: HomeAssistant) -> None:
    """Serve the switch cards and load them in every dashboard (no resource to add)."""
    if (
        hass.data.get(f"{DOMAIN}_cards")
        or "frontend" not in hass.config.components
        or not getattr(hass, "http", None)
    ):
        return
    hass.data[f"{DOMAIN}_cards"] = True
    version = await hass.async_add_executor_job(_manifest_version)
    await hass.http.async_register_static_paths([StaticPathConfig(CARDS_URL, str(CARDS_FILE), True)])
    add_extra_js_url(hass, f"{CARDS_URL}?v={version}")


def _manifest_version() -> str:
    return json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]


async def async_setup_entry(hass: HomeAssistant, entry: HawaiiConfigEntry) -> bool:
    await _async_register_cards(hass)
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
