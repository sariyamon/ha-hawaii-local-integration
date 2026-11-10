"""Setup: Tuya user code → scan the QR code with the Tuya app → done."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .cloud import CloudError, qr_login_result, qr_login_start
from .discovery import parse_networks
from .const import (
    CONF_ENDPOINT,
    CONF_NETWORKS,
    CONF_OVERRIDES,
    CONF_TERMINAL_ID,
    CONF_TOKEN_INFO,
    CONF_USER_CODE,
    DOMAIN,
    PROTOCOLS,
    VERSION_AUTO,
)


def _qr_schema(token: str) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional("qr"): selector.QrCodeSelector(
                selector.QrCodeSelectorConfig(
                    data=f"tuyaSmart--qrLogin?token={token}",
                    scale=5,
                    error_correction_level=selector.QrErrorCorrectionLevel.QUARTILE,
                )
            )
        }
    )


class HawaiiLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in with the Smart Life / Tuya Smart app."""

    VERSION = 1

    def __init__(self) -> None:
        self._user_code = ""
        self._qr = ""

    async def _start_qr(self, user_code: str) -> str | None:
        try:
            self._qr = await self.hass.async_add_executor_job(qr_login_start, user_code)
        except (CloudError, OSError, KeyError):
            return "invalid_user_code"
        self._user_code = user_code
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if (err := await self._start_qr(user_input[CONF_USER_CODE].strip())) is None:
                return await self.async_step_scan()
            errors["base"] = err
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_USER_CODE, default=self._user_code): str}),
            errors=errors,
        )

    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="scan", data_schema=_qr_schema(self._qr))
        info = await self.hass.async_add_executor_job(qr_login_result, self._qr, self._user_code)
        if not info:
            await self._start_qr(self._user_code)  # QR codes expire; show a fresh one
            return self.async_show_form(
                step_id="scan", data_schema=_qr_schema(self._qr), errors={"base": "not_scanned"}
            )
        data = {
            CONF_USER_CODE: self._user_code,
            CONF_TERMINAL_ID: info[CONF_TERMINAL_ID],
            CONF_ENDPOINT: info[CONF_ENDPOINT],
            CONF_TOKEN_INFO: {
                k: info[k] for k in ("t", "uid", "expire_time", "access_token", "refresh_token")
            },
        }
        await self.async_set_unique_id(info["uid"])
        if self.source == "reauth":
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=info.get("username") or "Tuya account", data=data)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._user_code = entry_data.get(CONF_USER_CODE, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if (err := await self._start_qr(user_input[CONF_USER_CODE].strip())) is None:
                return await self.async_step_scan()
            errors["base"] = err
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_USER_CODE, default=self._user_code): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HawaiiLocalOptionsFlow()


class HawaiiLocalOptionsFlow(OptionsFlow):
    """Refresh devices, scan the network, or fix one device's IP / protocol."""

    def __init__(self) -> None:
        self._stable: str | None = None
        self._result = ""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        hub = self.config_entry.runtime_data
        total = len([d for d in hub.devices.values() if not d.is_gateway])
        local = len([s for s in hub.local_online if not hub.devices[s].is_gateway])
        return self.async_show_menu(
            step_id="init",
            menu_options=["refresh", "scan", "networks", "device"],
            description_placeholders={"local": str(local), "total": str(total), "result": self._result},
        )

    async def async_step_refresh(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        hub = self.config_entry.runtime_data
        try:
            await hub.async_refresh()
            self._result = "Devices re-imported from your Tuya account."
        except CloudError as err:
            self._result = f"Couldn't reach your Tuya account: {err}"
        return await self.async_step_init()

    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        found = await self.config_entry.runtime_data.async_scan(force=True)
        self._result = f"Network scan finished: {found} device(s) found at a new address."
        return await self.async_step_init()

    async def async_step_networks(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = ", ".join(self.config_entry.options.get(CONF_NETWORKS, []))
        if user_input is not None:
            text = user_input.get(CONF_NETWORKS, "").strip()
            nets = parse_networks(text)
            if text and not nets:
                errors[CONF_NETWORKS] = "invalid_networks"
            else:
                return self.async_create_entry(
                    data={**self.config_entry.options, CONF_NETWORKS: [str(n) for n in nets]}
                )
        return self.async_show_form(
            step_id="networks",
            data_schema=vol.Schema(
                {vol.Optional(CONF_NETWORKS, description={"suggested_value": current}): str}
            ),
            errors=errors,
        )

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        hub = self.config_entry.runtime_data
        if user_input is not None:
            self._stable = user_input["device"]
            return await self.async_step_device_settings()
        options = [
            selector.SelectOptionDict(
                value=d.stable,
                label=f"{d.name} ({hub.endpoints.get(d.stable, {}).get('ip') or 'address not found yet'})",
            )
            for d in sorted(hub.devices.values(), key=lambda d: d.name.lower())
            if not d.sub and (d.is_gateway or d.dps)
        ]
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {vol.Required("device"): selector.SelectSelector(selector.SelectSelectorConfig(options=options))}
            ),
        )

    async def async_step_device_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        overrides = dict(self.config_entry.options.get(CONF_OVERRIDES, {}))
        current = overrides.get(self._stable, {})
        if user_input is not None:
            ip = (user_input.get("ip") or "").strip()
            version = user_input.get("version", VERSION_AUTO)
            if ip or version != VERSION_AUTO:
                overrides[self._stable] = {"ip": ip, "version": version}
            else:
                overrides.pop(self._stable, None)
            return self.async_create_entry(data={**self.config_entry.options, CONF_OVERRIDES: overrides})
        dev = self.config_entry.runtime_data.devices[self._stable]
        return self.async_show_form(
            step_id="device_settings",
            data_schema=vol.Schema(
                {
                    vol.Optional("ip", description={"suggested_value": current.get("ip", "")}): str,
                    vol.Required("version", default=current.get("version", VERSION_AUTO)): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=[VERSION_AUTO, *sorted(PROTOCOLS)])
                    ),
                }
            ),
            description_placeholders={"name": dev.name},
        )
