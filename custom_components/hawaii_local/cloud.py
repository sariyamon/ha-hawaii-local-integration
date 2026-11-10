"""Tuya account access: QR sign-in, device import and cloud fallback commands.

Only used to learn device ids / local keys / data points, to recover after a
device is reset, and as a fallback when a device can't be reached locally.
"""
from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from tuya_sharing import LoginControl, Manager, SharingTokenListener

from .const import TUYA_CLIENT_ID, TUYA_SCHEMA
from .models import DeviceInfo, from_cloud

_LOGGER = logging.getLogger(__name__)

AUTH_ERROR_CODES = {1010, 1011, 1012, 1013, 2406}  # token invalid / expired / revoked


class CloudAuthError(Exception):
    """The saved Tuya sign-in is no longer valid."""


class CloudError(Exception):
    """Tuya cloud unreachable or returned an error."""


def qr_login_start(user_code: str) -> str:
    """Return the QR token for the Smart Life / Tuya Smart app to scan (blocking)."""
    response = LoginControl().qr_code(TUYA_CLIENT_ID, TUYA_SCHEMA, user_code)
    if not response.get("success"):
        raise CloudError(response.get("msg") or str(response.get("code")))
    return response["result"]["qrcode"]


def qr_login_result(token: str, user_code: str) -> dict[str, Any] | None:
    """Return the sign-in info once the QR code was scanned, else None (blocking)."""
    ok, info = LoginControl().login_result(token, TUYA_CLIENT_ID, user_code)
    return info if ok else None


class _TokenListener(SharingTokenListener):
    def __init__(self, on_token: Callable[[dict[str, Any]], None]) -> None:
        self._on_token = on_token

    def update_token(self, token_info: dict[str, Any]) -> None:
        self._on_token(token_info)


class TuyaCloud:
    """Thin, blocking wrapper around tuya_sharing (call from the executor)."""

    def __init__(
        self,
        user_code: str,
        terminal_id: str,
        endpoint: str,
        token_info: dict[str, Any],
        on_token: Callable[[dict[str, Any]], None],
    ) -> None:
        self._manager = Manager(
            TUYA_CLIENT_ID, user_code, terminal_id, endpoint, token_info, _TokenListener(on_token)
        )

    def fetch_devices(self) -> list[DeviceInfo]:
        try:
            self._manager.update_device_cache()
        except Exception as err:  # noqa: BLE001 - sdk raises plain exceptions
            if _is_auth_error(err):
                raise CloudAuthError(str(err)) from err
            raise CloudError(str(err)) from err
        return [from_cloud(dev) for dev in self._manager.device_map.values()]

    def send(self, device_id: str, code: str, value: Any) -> None:
        try:
            result = self._manager.send_commands(device_id, [{"code": code, "value": value}])
        except Exception as err:  # noqa: BLE001
            raise CloudError(str(err)) from err
        if isinstance(result, dict) and not result.get("success", True):
            raise CloudError(result.get("msg") or str(result.get("code")))


def _is_auth_error(err: Exception) -> bool:
    code = getattr(err, "error_code", None)
    try:
        return int(code) in AUTH_ERROR_CODES
    except (TypeError, ValueError):
        return False
