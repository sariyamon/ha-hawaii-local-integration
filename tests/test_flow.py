"""Sign-in flow: user code → QR scan → entry; options."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.hawaii_local.cloud import CloudError
from custom_components.hawaii_local.const import DOMAIN

INFO = {"t": 1, "uid": "u1", "expire_time": 9, "access_token": "a", "refresh_token": "r",
        "terminal_id": "t1", "endpoint": "https://apigw.tuyain.com", "username": "riya"}
P = "custom_components.hawaii_local.config_flow."


async def test_sign_in(hass: HomeAssistant) -> None:
    with patch(P + "qr_login_start", side_effect=CloudError("bad")):
        r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"user_code": "nope"})
    assert r["errors"] == {"base": "invalid_user_code"}

    with patch(P + "qr_login_start", return_value="tok"), patch(P + "qr_login_result", side_effect=[None, INFO]):
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"user_code": " AbC "})
        assert r["step_id"] == "scan"
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
        assert r["errors"] == {"base": "not_scanned"}
        with patch("custom_components.hawaii_local.async_setup_entry", return_value=True):
            r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["title"] == "riya"
    assert r["data"]["user_code"] == "AbC"
    assert r["data"]["token_info"]["refresh_token"] == "r"
    assert r["result"].unique_id == "u1"
