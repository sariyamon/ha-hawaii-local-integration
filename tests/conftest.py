"""Test fixtures: a simulated home network of Tuya devices and a fake Tuya account."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from custom_components.hawaii_local.models import DeviceInfo, DpSpec

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


# ---------------------------------------------------------------- simulated LAN
@dataclass
class Hardware:
    dev_id: str
    key: str
    version: float
    gateway: bool = False
    dps: dict[str, Any] = field(default_factory=dict)
    children: dict[str, dict[str, Any]] = field(default_factory=dict)  # node -> dps
    outbox: deque = field(default_factory=deque)
    received: list = field(default_factory=list)


class Network:
    def __init__(self) -> None:
        self.hosts: dict[str, Hardware] = {}
        self.lock = threading.Lock()

    def at(self, ip: str) -> Hardware | None:
        with self.lock:
            return self.hosts.get(ip)

    def move(self, old: str, new: str) -> None:
        with self.lock:
            self.hosts[new] = self.hosts.pop(old)


NET = Network()


class FakeDevice:
    """Stands in for tinytuya.Device."""

    def __init__(self, dev_id, address=None, local_key="", version=3.1, persist=False,
                 cid=None, node_id=None, parent=None, **_: Any) -> None:
        self.id, self.address, self.key, self.version = dev_id, address, local_key, float(version)
        self.cid = cid or node_id
        self.parent = parent

    def _hw(self) -> Hardware | None:
        return NET.at(self.parent.address if self.parent else self.address)

    def _auth(self) -> dict | None:
        root = self.parent or self
        hw = NET.at(root.address)
        if hw is None:
            return {"Err": "901"}
        if hw.dev_id != root.id or hw.key != root.key or hw.version != root.version:
            return {"Err": "914"}
        return None

    def status(self, nowait=False):
        if err := self._auth():
            return err
        hw = self._hw()
        if self.parent:
            if self.cid not in hw.children:
                return None
            return {"dps": dict(hw.children[self.cid]), "cid": self.cid}
        return {"dps": dict(hw.dps)}

    def subdev_query(self, nowait=False):
        if err := self._auth():
            return err
        return {"reqType": "subdev_online_stat_query",
                "data": {"online": list(self._hw().children), "offline": []}}

    def set_socketTimeout(self, s):
        pass

    def receive(self):
        hw = self._hw()
        if hw is None or self._auth():
            time.sleep(0.02)
            return {"Err": "905"}
        if hw.outbox:
            return hw.outbox.popleft()
        time.sleep(0.02)
        return None

    def heartbeat(self, nowait=True):
        return None

    def set_multiple_values(self, data, nowait=False):
        hw = self._hw()
        hw.received.append((self.cid, dict(data)))
        if self.parent:
            hw.children[self.cid].update(data)
            hw.outbox.append({"dps": dict(data), "cid": self.cid})
        else:
            hw.dps.update(data)
            hw.outbox.append({"dps": dict(data)})

    def close(self):
        pass


# ---------------------------------------------------------------- fake Tuya account
GW_ID, WIFI_ID, OFFICE_ID, PLUG_ID = "gw0001", "wifi0001", "office0001", "plug0001"
OFFICE_NODE, PLUG_NODE = "d878f0fffe920e8d", "a4c1380000000001"


def cloud_devices(office_key="subkey", wifi_key="wifikey", office_id=OFFICE_ID, office_uuid=OFFICE_NODE):
    return [
        DeviceInfo(id=GW_ID, stable="gwuuid", name="Gateway", key="", category="wg2", cloud_online=True),
        DeviceInfo(id=WIFI_ID, stable="wifiuuid", name="Living room switch", key=wifi_key, category="kg",
                   cloud_online=True,
                   dps={"1": DpSpec("1", "switch_1"), "2": DpSpec("2", "switch_2")},
                   cloud_status={"switch_1": False, "switch_2": False}),
        # Broken cloud profile: only switch_7 known; the module really has 101..103.
        DeviceInfo(id=office_id, stable=office_uuid, name="office", key=office_key, category="cjkg",
                   sub=True, node_candidates=[office_uuid, OFFICE_NODE], cloud_online=False,
                   dps={"107": DpSpec("107", "switch_7")}),
        DeviceInfo(id=PLUG_ID, stable=PLUG_NODE, name="Plug", key=office_key, category="cz", sub=True,
                   node_candidates=[PLUG_NODE], cloud_online=True,
                   dps={"1": DpSpec("1", "switch_1")}, cloud_status={"switch_1": True}),
    ]


class FakeCloud:
    devices: list[DeviceInfo] = []
    sent: list = []
    fetches = 0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def fetch_devices(self):
        FakeCloud.fetches += 1
        return [DeviceInfo.from_dict(d.to_dict()) for d in FakeCloud.devices]

    def send(self, device_id, code, value):
        FakeCloud.sent.append((device_id, code, value))


@pytest.fixture
def lan():
    NET.hosts.clear()
    NET.hosts["192.168.0.87"] = Hardware(
        GW_ID, "subkey", 3.4, gateway=True,
        children={OFFICE_NODE: {"101": False, "102": True, "103": False, "107": False},
                  PLUG_NODE: {"1": False}},
    )
    NET.hosts["192.168.0.50"] = Hardware(WIFI_ID, "wifikey", 3.3, dps={"1": False, "2": True})
    FakeCloud.devices = cloud_devices()
    FakeCloud.sent = []
    FakeCloud.fetches = 0
    with (
        patch("custom_components.hawaii_local.local.tinytuya.Device", FakeDevice),
        patch("custom_components.hawaii_local.hub.TuyaCloud", FakeCloud),
        patch("custom_components.hawaii_local.hub.BroadcastListener.start", return_value=None),
        patch("custom_components.hawaii_local.local.RECONNECT_MIN", 0.05),
        patch("custom_components.hawaii_local.local.RECONNECT_MAX", 0.2),
        patch("custom_components.hawaii_local.hub.network.async_get_adapters",
              return_value=[{"enabled": True, "ipv4": [{"address": "192.168.0.10", "network_prefix": 24}]}]),
    ):
        yield NET


async def wait_for(hass, check, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        await hass.async_block_till_done()
        if check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")
