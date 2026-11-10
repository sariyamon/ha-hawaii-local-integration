"""Diagnostics with keys and tokens removed."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN_INFO, CONF_USER_CODE

REDACT = {"key", "local_key", CONF_TOKEN_INFO, CONF_USER_CODE, "access_token", "refresh_token", "uid"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry) -> dict[str, Any]:
    hub = entry.runtime_data
    return async_redact_data(
        {
            "entry": dict(entry.data),
            "devices": [d.to_dict() for d in hub.devices.values()],
            "endpoints": hub.endpoints,
            "subs": hub.subs,
            "local_online": sorted(hub.local_online),
            "connections": {
                s: {"connected": c.connected, "ip": c.endpoint.ip, "version": c.endpoint.version}
                for s, c in hub.connections.items()
            },
            "state": hub.state,
        },
        REDACT,
    )
