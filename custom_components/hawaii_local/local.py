"""Local (LAN) connections to Tuya devices and gateways.

One background thread per connection keeps a persistent socket open, so state
changes made in the Tuya app or at the wall switch arrive instantly. A gateway
connection carries all of its Zigbee/BLE sub-devices (addressed by node id).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import queue
import threading
import time
from typing import Any

import tinytuya

from .const import HEARTBEAT, PROTOCOLS, RECEIVE_TIMEOUT, RECONNECT_MAX, RECONNECT_MIN

_LOGGER = logging.getLogger(__name__)

OFFLINE_ERRORS = {"901", "905"}
NO_DATA_ERRORS = {"902"}
WRONG_KEY_ERRORS = {"914", "904", "900"}  # wrong key or wrong protocol version


@dataclass
class Child:
    stable: str
    dev_id: str
    node: str


@dataclass
class Endpoint:
    """Something with its own IP: a Wi-Fi device or a gateway."""

    stable: str
    dev_id: str
    ip: str
    keys: list[str]
    version: str | None = None            # None = try PROTOCOLS
    direct: bool = True                   # False = gateway (data comes from children)
    children: list[Child] = field(default_factory=list)


@dataclass
class Callbacks:
    """Called from the connection thread; the hub hops onto the event loop."""

    connected: Callable[[str, str, str], None]           # endpoint stable, version, key
    disconnected: Callable[[str, str], None]              # endpoint stable, reason: offline|key
    status: Callable[[str, dict[str, Any]], None]        # device stable, dps
    subdevices: Callable[[str, set[str], set[str]], None]  # endpoint stable, online, all nodes


def _err(result: Any) -> str | None:
    if isinstance(result, dict) and "Err" in result:
        return str(result["Err"])
    return None


def _nodes(result: Any) -> tuple[set[str], set[str]]:
    """online, all node ids from a subdev_online_stat reply."""
    online: set[str] = set()
    every: set[str] = set()
    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, dict):
        for state, nodes in data.items():
            if isinstance(nodes, list):
                lowered = {str(n).lower() for n in nodes}
                every |= lowered
                if state == "online":
                    online |= lowered
    return online, every


class LocalConnection(threading.Thread):
    """Persistent connection to one endpoint (and its children)."""

    def __init__(self, endpoint: Endpoint, callbacks: Callbacks) -> None:
        super().__init__(name=f"hawaii_local {endpoint.dev_id}", daemon=True)
        self.endpoint = endpoint
        self._cb = callbacks
        self._stop = threading.Event()
        self._commands: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self._parent: Any = None
        self._targets: dict[str, Any] = {}   # device stable -> tinytuya device
        self._by_node: dict[str, str] = {}   # node -> device stable
        self.connected = False

    # ---- called from the event loop -------------------------------------------------
    def send(self, stable: str, dps: dict[str, Any]) -> bool:
        if not self.connected:
            return False
        self._commands.put((stable, dps))
        return True

    def stop(self) -> None:
        self._stop.set()

    # ---- thread ---------------------------------------------------------------------
    def run(self) -> None:
        delay = RECONNECT_MIN
        while not self._stop.is_set():
            outcome = self._connect()
            if outcome == "ok":
                delay = RECONNECT_MIN
                self.connected = True
                self._loop()
                self.connected = False
                self._close()
                if self._stop.is_set():
                    break
                self._cb.disconnected(self.endpoint.stable, "offline")
            else:
                self._close()
                self._cb.disconnected(self.endpoint.stable, outcome)
            self._stop.wait(delay)
            delay = min(delay * 2, RECONNECT_MAX)

    def _make(self, key: str, version: str) -> Any:
        dev = tinytuya.Device(
            self.endpoint.dev_id, self.endpoint.ip, key, version=float(version), persist=True,
            connection_timeout=4, connection_retry_limit=1, connection_retry_delay=1,
        )
        return dev

    def _connect(self) -> str:
        ep = self.endpoint
        versions = [ep.version] if ep.version else PROTOCOLS
        saw_wrong_key = False
        for version in versions:
            for key in dict.fromkeys(k for k in ep.keys if k):
                if self._stop.is_set():
                    return "offline"
                try:
                    dev = self._make(key, version)
                    probe = dev.status() if ep.direct else dev.subdev_query()
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("%s: connect error %s", ep.dev_id, err)
                    return "offline"
                code = _err(probe)
                _LOGGER.debug("%s at %s v%s: %s", ep.dev_id, ep.ip, version, code or "ok")
                if code in OFFLINE_ERRORS:
                    _close_quietly(dev)
                    return "offline"
                if code in WRONG_KEY_ERRORS or (probe is None and ep.direct):
                    saw_wrong_key = True
                    _close_quietly(dev)
                    continue
                self._parent = dev
                ep.version = version
                self._cb.connected(ep.stable, version, key)
                self._setup_targets(probe)
                return "ok"
        return "key" if saw_wrong_key else "offline"

    def _setup_targets(self, probe: Any) -> None:
        ep, parent = self.endpoint, self._parent
        parent.set_socketTimeout(RECEIVE_TIMEOUT)
        if ep.direct:
            self._targets = {ep.stable: parent}
            if isinstance(probe, dict) and isinstance(probe.get("dps"), dict):
                self._cb.status(ep.stable, probe["dps"])
            return
        online, every = _nodes(probe)
        self._cb.subdevices(ep.stable, online, every)
        self._targets, self._by_node = {}, {}
        for child in ep.children:
            dev = tinytuya.Device(child.dev_id, cid=child.node, parent=parent)
            self._targets[child.stable] = dev
            self._by_node[child.node.lower()] = child.stable
            try:
                result = dev.status()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("%s: child %s status failed: %s", ep.dev_id, child.node, err)
                continue
            if isinstance(result, dict) and isinstance(result.get("dps"), dict):
                self._cb.status(child.stable, result["dps"])

    def _loop(self) -> None:
        parent = self._parent
        last_beat = time.monotonic()
        while not self._stop.is_set():
            try:
                while True:
                    stable, dps = self._commands.get_nowait()
                    target = self._targets.get(stable)
                    if target is not None:
                        target.set_multiple_values(dps, nowait=True)
            except queue.Empty:
                pass
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("%s: send failed: %s", self.endpoint.dev_id, err)
                return
            try:
                data = parent.receive()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("%s: receive failed: %s", self.endpoint.dev_id, err)
                return
            code = _err(data)
            if code in OFFLINE_ERRORS:
                return
            if data and code is None:
                self._route(data)
            if time.monotonic() - last_beat > HEARTBEAT:
                last_beat = time.monotonic()
                try:
                    parent.heartbeat(nowait=True)
                except Exception:  # noqa: BLE001
                    return

    def _route(self, data: dict[str, Any]) -> None:
        if data.get("reqType", "").startswith("subdev_online_stat"):
            online, every = _nodes(data)
            self._cb.subdevices(self.endpoint.stable, online, every)
            return
        dps = data.get("dps")
        if not isinstance(dps, dict):
            return
        if self.endpoint.direct:
            self._cb.status(self.endpoint.stable, dps)
            return
        cid = data.get("cid") or (data.get("data") or {}).get("cid")
        stable = self._by_node.get(str(cid).lower()) if cid else None
        if stable:
            self._cb.status(stable, dps)

    def _close(self) -> None:
        if self._parent is not None:
            _close_quietly(self._parent)
        self._parent, self._targets, self._by_node = None, {}, {}


def _close_quietly(dev: Any) -> None:
    try:
        dev.close()
    except Exception:  # noqa: BLE001
        pass


def probe_endpoint(ip: str, dev_id: str, keys: list[str], direct: bool, version: str | None) -> tuple[str, str] | None:
    """Blocking: return (version, key) if the device at ip accepts dev_id/key."""
    for ver in [version] if version else PROTOCOLS:
        for key in dict.fromkeys(k for k in keys if k):
            dev = tinytuya.Device(
                dev_id, ip, key, version=float(ver), connection_timeout=2,
                connection_retry_limit=1, connection_retry_delay=0,
            )
            try:
                result = dev.status() if direct else dev.subdev_query()
            except Exception:  # noqa: BLE001
                result = {"Err": "901"}
            finally:
                _close_quietly(dev)
            code = _err(result)
            _LOGGER.debug(
                "Probe %s as %s v%s key …%s: %s", ip, dev_id, ver, key[-3:],
                code or ("no reply" if result is None else "ok"),
            )
            if code in OFFLINE_ERRORS:
                return None
            if code is None and (result is not None or not direct):
                return ver, key
    return None
