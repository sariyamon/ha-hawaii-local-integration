"""Hawaii Local end to end against a simulated home network."""
from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.hawaii_local.const import DOMAIN

from .conftest import (
    GW_ID, OFFICE_NODE, WIFI_ID, FakeCloud, cloud_devices, wait_for,
)

DATA = {
    "user_code": "abc", "terminal_id": "t1", "endpoint": "https://apigw.tuyain.com",
    "token_info": {"t": 1, "uid": "u1", "expire_time": 0, "access_token": "a", "refresh_token": "r"},
}


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="u1", title="me")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _broadcast_all(hass, hub, lan):
    for ip, hw in list(lan.hosts.items()):
        hub._on_broadcast({"id": hw.dev_id, "ip": ip, "version": str(hw.version)})
    await hass.async_block_till_done()


async def test_wifi_and_gateway_subdevices_local(hass: HomeAssistant, lan) -> None:
    entry = await _setup(hass)
    hub = entry.runtime_data
    await _broadcast_all(hass, hub, lan)

    # Wi-Fi device: profile switches, live state from the device.
    await wait_for(hass, lambda: hass.states.get("switch.living_room_switch_switch_2") is not None
                   and hass.states.get("switch.living_room_switch_switch_2").state == "on")
    st = hass.states.get("switch.living_room_switch_switch_2")
    assert st.attributes["connection"] == "local"

    # Sub-device behind the gateway, with a broken cloud profile: extra channels learnt locally.
    await wait_for(hass, lambda: hass.states.get("switch.office_channel_102") is not None)
    assert hass.states.get("switch.office_channel_102").state == "on"
    assert hass.states.get("switch.office_switch_7").state == "off"
    assert hub.subs[OFFICE_NODE] == {"gateway": "gwuuid", "node": OFFICE_NODE}
    assert hass.states.get("switch.plug_power").state == "off"   # local beats stale cloud "on"

    # Commands go over the LAN; changes made elsewhere arrive by push.
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.office_channel_101"}, blocking=True)
    await wait_for(hass, lambda: (OFFICE_NODE, {"101": True}) in lan.hosts["192.168.0.87"].received)
    lan.hosts["192.168.0.50"].outbox.append({"dps": {"1": True}})
    await wait_for(hass, lambda: hass.states.get("switch.living_room_switch_switch_1").state == "on")
    assert FakeCloud.sent == []

    # Devices hang off the gateway in the device registry.
    reg = er.async_get(hass)
    assert reg.async_get("switch.office_channel_101").unique_id == f"{OFFICE_NODE}_101"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_ip_change_followed_from_broadcast(hass: HomeAssistant, lan) -> None:
    entry = await _setup(hass)
    hub = entry.runtime_data
    await _broadcast_all(hass, hub, lan)
    await wait_for(hass, lambda: "wifiuuid" in hub.local_online)

    lan.move("192.168.0.50", "192.168.0.77")
    await wait_for(hass, lambda: "wifiuuid" not in hub.local_online)
    hub._on_broadcast({"id": WIFI_ID, "ip": "192.168.0.77", "version": "3.3"})
    await wait_for(hass, lambda: "wifiuuid" in hub.local_online)
    assert hub.endpoints["wifiuuid"]["ip"] == "192.168.0.77"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_scan_finds_devices_without_broadcasts(hass: HomeAssistant, lan) -> None:
    """Docker without host networking: no broadcasts, the scan finds devices by key."""
    with patch("custom_components.hawaii_local.hub.find_open_hosts",
               return_value=["192.168.0.20", "192.168.0.50", "192.168.0.87"]):
        entry = await _setup(hass)
        hub = entry.runtime_data
        found = await hub.async_scan(force=True)
    assert found == 2
    assert hub.endpoints["wifiuuid"]["ip"] == "192.168.0.50"
    assert hub.endpoints["gwuuid"]["ip"] == "192.168.0.87"
    await wait_for(hass, lambda: {"wifiuuid", OFFICE_NODE} <= hub.local_online)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reset_device_recovers_new_key_and_id(hass: HomeAssistant, lan) -> None:
    entry = await _setup(hass)
    hub = entry.runtime_data
    await _broadcast_all(hass, hub, lan)
    await wait_for(hass, lambda: "wifiuuid" in hub.local_online and OFFICE_NODE in hub.local_online)
    reg = er.async_get(hass)
    before = reg.async_get("switch.office_channel_101").unique_id

    # Re-paired in the Tuya app: new keys; the office module also gets a new id + uuid.
    lan.hosts["192.168.0.50"].key = "wifikey2"
    lan.hosts["192.168.0.87"].key = "subkey2"
    FakeCloud.devices = cloud_devices(office_key="subkey2", wifi_key="wifikey2",
                                      office_id="office0002", office_uuid="newuuid")
    hub._last_refresh = 0  # allow an immediate refresh in the test

    await wait_for(hass, lambda: "wifiuuid" in hub.local_online and FakeCloud.fetches >= 2
                   and hub.devices["wifiuuid"].key == "wifikey2", timeout=8)
    await wait_for(hass, lambda: OFFICE_NODE in hub.local_online, timeout=8)
    assert hub.devices[OFFICE_NODE].id == "office0002"      # same device, new Tuya id
    assert reg.async_get("switch.office_channel_101").unique_id == before
    assert "newuuid" not in hub.devices
    await hass.config_entries.async_unload(entry.entry_id)


async def test_cloud_fallback_when_not_local(hass: HomeAssistant, lan) -> None:
    lan.hosts.clear()  # nothing reachable locally
    entry = await _setup(hass)
    assert hass.states.get("switch.plug_power").state == "on"           # cloud state
    assert hass.states.get("switch.plug_power").attributes["connection"] == "cloud"
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.plug_power"}, blocking=True)
    assert FakeCloud.sent == [("plug0001", "switch_1", False)]
    assert hass.states.get("switch.office_switch_7").state == "unavailable"  # cloud says offline
    await hass.config_entries.async_unload(entry.entry_id)


async def test_works_offline_from_cache(hass: HomeAssistant, lan) -> None:
    entry = await _setup(hass)
    await hass.config_entries.async_unload(entry.entry_id)  # saves the cache

    from custom_components.hawaii_local.cloud import CloudError

    with patch.object(FakeCloud, "fetch_devices", side_effect=CloudError("no internet")):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("switch.living_room_switch_switch_1") is not None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_gateway_id_constant(hass: HomeAssistant, lan) -> None:
    assert GW_ID == lan.hosts["192.168.0.87"].dev_id
