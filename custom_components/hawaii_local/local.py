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

OFFLINE_ERRORS = {"901", "905"}      # while connected: the link dropped
UNREACHABLE_ERRORS = {"901"}         # while connecting: nothing answers at this IP
NO_REPLY_ERRORS = {"905", "902"}     # while connecting: some gateways just hang up on a wrong key
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
    alt_ids: list[str] = field(default_factory=list)  # other ids a gateway may answer to

    def ids(self) -> list[str]:
        return list(dict.fromkeys(i for i in [self.dev_id, *self.alt_ids] if i))


@dataclass
class Callbacks:
    """Called from the connection thread; the hub hops onto the event loop."""

    connected: Callable[[str, str, str, str], None]      # endpoint stable, version, key, id used
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
        if not self.connected or not self.is_alive():
            return False
        self._commands.put((stable, dps))
        return True

    def stop(self) -> None:
        self._stop.set()

    # ---- thread ---------------------------------------------------------------------
    def run(self) -> None:
        delay = RECONNECT_MIN
        while not self._stop.is_set():
            try:
                outcome = self._connect()
            except Exception:  # noqa: BLE001 - never let the worker die
                _LOGGER.exception("%s: unexpected error while connecting", self.endpoint.dev_id)
                outcome = "offline"
            if outcome == "ok":
                delay = RECONNECT_MIN
                self.connected = True
                try:
                    self._loop()
                except Exception:  # noqa: BLE001 - reconnect instead of dying
                    _LOGGER.exception("%s: unexpected error, reconnecting", self.endpoint.dev_id)
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

    def _make(self, dev_id: str, key: str, version: str) -> Any:
        return tinytuya.Device(
            dev_id, self.endpoint.ip, key, version=float(version), persist=True,
            connection_timeout=4, connection_retry_limit=1, connection_retry_delay=1,
        )

    def _connect(self) -> str:
        ep = self.endpoint
        versions = [ep.version] if ep.version else PROTOCOLS
        saw_wrong_key = False
        for version, key, dev_id in _attempts(versions, ep.keys, ep.ids()):
            if self._stop.is_set():
                return "offline"
            try:
                dev = self._make(dev_id, key, version)
                probe = dev.status() if ep.direct else dev.subdev_query()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("%s: connect error %s", ep.dev_id, err)
                return "offline"
            code = _err(probe)
            _LOGGER.debug("%s at %s v%s as %s: %s", ep.dev_id, ep.ip, version, dev_id, code or "ok")
            if code in UNREACHABLE_ERRORS:
                _close_quietly(dev)
                return "offline"
            if code in NO_REPLY_ERRORS:
                _close_quietly(dev)
                continue
            if code in WRONG_KEY_ERRORS or (probe is None and ep.direct):
                saw_wrong_key = True
                _close_quietly(dev)
                continue
            self._parent = dev
            ep.version, ep.dev_id = version, dev_id
            self.connected = True  # accept commands before states are reported as local
            self._cb.connected(ep.stable, version, key, dev_id)
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
                for message in _messages(data):
                    self._route(message)
            if time.monotonic() - last_beat > HEARTBEAT:
                last_beat = time.monotonic()
                try:
                    parent.heartbeat(nowait=True)
                except Exception:  # noqa: BLE001
                    return

    def _route(self, data: dict[str, Any]) -> None:
        if str(data.get("reqType") or "").startswith("subdev_online_stat"):
            online, every = _nodes(data)
            self._cb.subdevices(self.endpoint.stable, online, every)
            return
        dps = data.get("dps")
        if not isinstance(dps, dict):
            return
        if self.endpoint.direct:
            self._cb.status(self.endpoint.stable, dps)
            return
        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        cid = data.get("cid") or inner.get("cid")
        stable = self._by_node.get(str(cid).lower()) if cid else None
        if stable:
            self._cb.status(stable, dps)

    def _close(self) -> None:
        if self._parent is not None:
            _close_quietly(self._parent)
        self._parent, self._targets, self._by_node = None, {}, {}


def _messages(data: Any) -> list[dict[str, Any]]:
    """tinytuya usually returns one dict, but can return several messages at once."""
    if isinstance(data, dict):
        return [data]
    if isinstance(data, (list, tuple)):
        return [m for item in data for m in _messages(item)]
    return []


def _close_quietly(dev: Any) -> None:
    try:
        dev.close()
    except Exception:  # noqa: BLE001
        pass


def _attempts(versions: list[str], keys: list[str], ids: list[str]):
    """(version, key, id) combinations, most likely first."""
    keys = list(dict.fromkeys(k for k in keys if k))
    for version in versions:
        for key in keys:
            for dev_id in ids:
                yield version, key, dev_id


def probe_endpoint(
    ip: str, dev_ids: list[str] | str, keys: list[str], direct: bool, version: str | None
) -> tuple[str, str, str] | None:
    """Blocking: return (version, key, id) if the device at ip accepts one of them.

    A gateway that accepts the key but not the id hangs up (905), so other ids
    (its sub-devices') are tried with that key; a wrong key (914) skips them.
    """
    ids = [dev_ids] if isinstance(dev_ids, str) else list(dict.fromkeys(i for i in dev_ids if i))
    bad_keys: set[tuple[str, str]] = set()
    for ver, key, dev_id in _attempts([version] if version else PROTOCOLS, keys, ids):
        if (ver, key) in bad_keys:
            continue
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
        if code in UNREACHABLE_ERRORS:
            return None
        if code in WRONG_KEY_ERRORS:
            bad_keys.add((ver, key))
            continue
        if code is None and (result is not None or not direct):
            return ver, key, dev_id
    return None
