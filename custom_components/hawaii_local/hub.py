"""Hawaii Local hub: keeps every device reachable locally, by itself.

* Imports devices (ids, local keys, data points) from the Tuya account.
* Finds each device's IP from its broadcasts, or by scanning the network, and
  follows IP changes automatically.
* Finds which gateway each Zigbee/BLE sub-device sits behind.
* When a device is reset or re-paired (new key / new id), notices the key
  failure, re-imports from the Tuya account and reconnects; entities keep
  their ids because devices are tracked by hardware, not by Tuya id.
* Works without internet from a local cache; uses the cloud only as a fallback.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from functools import partial
import ipaddress
import logging
import time
from typing import Any

from homeassistant.components import network
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store

from .cloud import CloudAuthError, CloudError, TuyaCloud
from .const import (
    CLOUD_REFRESH_COOLDOWN,
    CLOUD_REFRESH_INTERVAL,
    COMMON_HOME_NETWORKS,
    CONF_ENDPOINT,
    CONF_NETWORKS,
    CONF_OVERRIDES,
    CONF_TERMINAL_ID,
    CONF_TOKEN_INFO,
    CONF_USER_CODE,
    CONTAINER_NETWORK,
    DISCOVERY_GRACE,
    DOMAIN,
    FAILURES_BEFORE_RESCAN,
    SCAN_COOLDOWN,
    SIGNAL_DEVICE_UPDATE,
    SIGNAL_NEW_DPS,
    STORAGE_VERSION,
    VERSION_AUTO,
)
from .discovery import (
    BroadcastListener,
    find_open_hosts,
    in_container,
    parse_networks,
    scan_networks,
)
from .local import Callbacks, Child, Endpoint, LocalConnection, probe_endpoint
from .models import DeviceInfo, DpSpec, value_type_of

_LOGGER = logging.getLogger(__name__)


class HawaiiHub:
    """Runtime state for one Tuya account."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.devices: dict[str, DeviceInfo] = {}
        self.state: dict[str, dict[str, Any]] = {}
        self.local_online: set[str] = set()
        self.endpoints: dict[str, dict[str, Any]] = {}  # stable -> {ip, version, key, source}
        self.subs: dict[str, dict[str, str]] = {}       # sub stable -> {gateway, node}
        self.connections: dict[str, LocalConnection] = {}
        self._failures: dict[str, int] = {}
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._cloud: TuyaCloud | None = None
        self._listener = BroadcastListener(self._thread_safe(self._on_broadcast))
        self._last_scan: float | None = None     # None = never
        self._last_refresh: float | None = None
        self._unsubs: list[Callable[[], None]] = []
        self.last_scan_found: int | None = None
        self._stopping: list[LocalConnection] = []

    # ------------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        cached = await self._store.async_load() or {}
        for raw in cached.get("devices", []):
            dev = DeviceInfo.from_dict(raw)
            self.devices[dev.stable] = dev
        self.endpoints = cached.get("endpoints", {})
        self.subs = cached.get("subs", {})

        data = self.entry.data
        self._cloud = TuyaCloud(
            data[CONF_USER_CODE], data[CONF_TERMINAL_ID], data[CONF_ENDPOINT],
            data[CONF_TOKEN_INFO], self._thread_safe(self._on_token),
        )
        try:
            await self._refresh_cloud(force=True)
        except CloudAuthError as err:
            if not self.devices:
                raise ConfigEntryAuthFailed(str(err)) from err
            self.entry.async_start_reauth(self.hass)
        except CloudError as err:
            if not self.devices:
                raise ConfigEntryNotReady(f"Tuya account unreachable: {err}") from err
            _LOGGER.warning("Tuya cloud unreachable, using saved devices: %s", err)

        self._apply_overrides()
        await self._listener.start()
        self._reconcile_connections()
        self._unsubs.append(async_call_later(self.hass, DISCOVERY_GRACE, self._scan_later))
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._periodic_refresh, timedelta(seconds=CLOUD_REFRESH_INTERVAL)
            )
        )

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._listener.stop()
        conns = list(self.connections.values()) + self._stopping
        for conn in conns:
            conn.stop()
        self.connections.clear()
        self._stopping.clear()
        await self.hass.async_add_executor_job(_join, conns)
        await self._store.async_save(self._snapshot())

    # ------------------------------------------------------------------ helpers
    def _thread_safe(self, func: Callable[..., None]) -> Callable[..., None]:
        def wrapper(*args: Any) -> None:
            self.hass.loop.call_soon_threadsafe(partial(func, *args))
        return wrapper

    def _snapshot(self) -> dict[str, Any]:
        return {
            "devices": [d.to_dict() for d in self.devices.values()],
            "endpoints": self.endpoints,
            "subs": self.subs,
        }

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self._snapshot, 5)

    def stable_of(self, dev_id: str) -> str | None:
        for dev in self.devices.values():
            if dev.id == dev_id:
                return dev.stable
        return None

    def gateways(self) -> list[DeviceInfo]:
        return [d for d in self.devices.values() if d.is_gateway]

    def endpoint_of(self, stable: str) -> str | None:
        """The endpoint (own IP) that reaches this device."""
        dev = self.devices.get(stable)
        if dev is None:
            return None
        if dev.sub:
            return (self.subs.get(stable) or {}).get("gateway")
        return stable

    def gateway_of(self, stable: str) -> str | None:
        """The gateway a sub-device sits behind (known, or the only gateway)."""
        dev = self.devices.get(stable)
        if dev is None or not dev.sub:
            return None
        if link := self.subs.get(stable):
            return link.get("gateway")
        gateways = self.gateways()
        return gateways[0].stable if len(gateways) == 1 else None

    @callback
    def link_to_gateway(self, stable: str) -> None:
        """Show a sub-device as connected via its gateway in the device registry."""
        gw = self.gateway_of(stable)
        if gw is None:
            return
        reg = dr.async_get(self.hass)
        child, parent = self._registry_device(reg, stable), self._registry_device(reg, gw)
        if child is None:
            return
        if parent is None:
            gw_dev = self.devices[gw]
            parent = reg.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                identifiers={(DOMAIN, gw)},
                name=gw_dev.name,
                manufacturer="Tuya",
                model=gw_dev.product_name or gw_dev.category,
            )
        if child.via_device_id != parent.id:
            reg.async_update_device(child.id, via_device_id=parent.id)

    def _registry_device(self, reg: dr.DeviceRegistry, stable: str) -> dr.DeviceEntry | None:
        for device in dr.async_entries_for_config_entry(reg, self.entry.entry_id):
            if (DOMAIN, stable) in device.identifiers:
                return device
        return None

    def _overrides(self) -> dict[str, dict[str, str]]:
        return self.entry.options.get(CONF_OVERRIDES, {})

    @callback
    def _apply_overrides(self) -> None:
        for stable, ov in self._overrides().items():
            ep = self.endpoints.setdefault(stable, {})
            if ov.get("ip"):
                ep.update(ip=ov["ip"], source="manual")
            if ov.get("version") and ov["version"] != VERSION_AUTO:
                ep["version"] = ov["version"]

    # ------------------------------------------------------------------ cloud
    async def _refresh_cloud(self, force: bool = False) -> bool:
        """Re-import devices from the Tuya account. Returns True if anything changed."""
        if (
            not force and self._last_refresh is not None
            and time.monotonic() - self._last_refresh < CLOUD_REFRESH_COOLDOWN
        ):
            return False
        self._last_refresh = time.monotonic()
        assert self._cloud is not None
        fresh = await self.hass.async_add_executor_job(self._cloud.fetch_devices)
        if not fresh and self.devices:
            _LOGGER.warning("Tuya account returned no devices; keeping saved list")
            return False
        changed = self._merge(fresh)
        self._save()
        return changed

    def _merge(self, fresh: list[DeviceInfo]) -> bool:
        changed = False
        for new in fresh:
            old = self.devices.get(new.stable) or self._match_reset_device(new)
            if old is None:
                self.devices[new.stable] = new
                changed = True
                continue
            if (old.id, old.key) != (new.id, new.key):
                _LOGGER.info("%s: new Tuya id/key after reset, reconnecting", old.name)
                changed = True
            # keep the old stable id so entity ids don't change; keep locally found DPs
            new.stable = old.stable
            for dp, spec in old.dps.items():
                if spec.from_device and dp not in new.dps:
                    new.dps[dp] = spec
            self.devices[old.stable] = new
        if changed:
            self._reconcile_connections(restart_changed=True)
        return changed

    def _match_reset_device(self, new: DeviceInfo) -> DeviceInfo | None:
        """A re-paired device can come back with a new uuid; match by Zigbee node / MAC."""
        nodes = set(new.node_candidates)
        if not nodes:
            return None
        if new.stable in self.devices:
            return None
        for old in self.devices.values():
            if old.id != new.id and nodes & set(old.node_candidates):
                return old
        return None

    @callback
    def _on_token(self, token_info: dict[str, Any]) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_TOKEN_INFO: token_info}
        )

    async def _periodic_refresh(self, _now: Any = None) -> None:
        try:
            await self._refresh_cloud(force=True)
        except CloudAuthError:
            self.entry.async_start_reauth(self.hass)
        except CloudError as err:
            _LOGGER.debug("Periodic Tuya refresh failed: %s", err)

    async def async_refresh(self) -> None:
        """Options-flow / service: re-import now."""
        await self._refresh_cloud(force=True)

    # ------------------------------------------------------------------ connections
    def _endpoint_for(self, stable: str) -> Endpoint | None:
        dev = self.devices.get(stable)
        info = self.endpoints.get(stable, {})
        if dev is None or not info.get("ip"):
            return None
        if dev.is_gateway:
            children = self._children_of(stable)
            keys = [info.get("key", ""), dev.key] + [
                self.devices[c.stable].key for c in children
            ] + [d.key for d in self.devices.values() if d.sub]
            return Endpoint(
                stable, info.get("dev_id") or dev.id, info["ip"], keys, info.get("version"),
                False, children, alt_ids=self._gateway_ids(dev),
            )
        return Endpoint(stable, dev.id, info["ip"], [dev.key, info.get("key", "")], info.get("version"))

    def _children_of(self, gw_stable: str) -> list[Child]:
        gateways = self.gateways()
        children = []
        for dev in self.devices.values():
            if not dev.sub:
                continue
            link = self.subs.get(dev.stable)
            if link and link.get("gateway") == gw_stable:
                children.append(Child(dev.stable, dev.id, link["node"]))
            elif not link and len(gateways) == 1 and dev.node_candidates:
                children.append(Child(dev.stable, dev.id, dev.node_candidates[0]))
        return children

    @callback
    def _reconcile_connections(self, restart_changed: bool = False) -> None:
        """Start, restart or stop connections so they match what we know."""
        wanted: dict[str, Endpoint] = {}
        for dev in self.devices.values():
            if dev.sub:
                continue
            if not dev.is_gateway and not dev.dps:
                continue
            ep = self._endpoint_for(dev.stable)
            if ep is not None:
                wanted[dev.stable] = ep
        for stable, conn in list(self.connections.items()):
            new = wanted.get(stable)
            if new is None or (restart_changed and _differs(conn.endpoint, new)) or not conn.is_alive():
                conn.stop()
                self._stopping.append(conn)
                del self.connections[stable]
        for stable, ep in wanted.items():
            if stable not in self.connections:
                conn = LocalConnection(ep, self._callbacks)
                self.connections[stable] = conn
                conn.start()

    @property
    def _callbacks(self) -> Callbacks:
        return Callbacks(
            connected=self._thread_safe(self._on_connected),
            disconnected=self._thread_safe(self._on_disconnected),
            status=self._thread_safe(self._on_status),
            subdevices=self._thread_safe(self._on_subdevices),
        )

    @callback
    def _restart(self, stable: str) -> None:
        if (conn := self.connections.pop(stable, None)) is not None:
            conn.stop()
            self._stopping.append(conn)
        self._stopping = [c for c in self._stopping if c.is_alive()]
        self._reconcile_connections()

    # ------------------------------------------------------------------ callbacks
    @callback
    def _on_connected(self, ep_stable: str, version: str, key: str, dev_id: str) -> None:
        self._failures[ep_stable] = 0
        info = self.endpoints.setdefault(ep_stable, {})
        info.update(version=version, key=key, dev_id=dev_id)
        dev = self.devices.get(ep_stable)
        if dev is not None and not dev.is_gateway:
            self._set_online(ep_stable, True)
        self._save()

    @callback
    def _on_disconnected(self, ep_stable: str, reason: str) -> None:
        self._failures[ep_stable] = self._failures.get(ep_stable, 0) + 1
        self._set_online(ep_stable, False)
        for child in self._children_of(ep_stable):
            self._set_online(child.stable, False)
        if reason == "key":
            # Reset / re-paired: new local key. Fetch it from the Tuya account.
            self.hass.async_create_task(self._recover_keys())
        elif (
            self._failures[ep_stable] >= FAILURES_BEFORE_RESCAN
            and self.endpoints.get(ep_stable, {}).get("source") != "manual"
        ):
            # Probably a new IP that the broadcasts didn't tell us about.
            self.hass.async_create_task(self.async_scan())

    async def _recover_keys(self) -> None:
        try:
            await self._refresh_cloud()
        except CloudAuthError:
            self.entry.async_start_reauth(self.hass)
        except CloudError as err:
            _LOGGER.debug("Key recovery: Tuya cloud unreachable: %s", err)

    @callback
    def _on_status(self, stable: str, dps: dict[str, Any]) -> None:
        dev = self.devices.get(stable)
        if dev is None:
            return
        values = self.state.setdefault(stable, {})
        new_specs = False
        for dp, value in dps.items():
            dp = str(dp)
            values[dp] = value
            if dp not in dev.dps:
                # Not in Tuya's profile (broken/old profile): learn it from the device.
                dev.dps[dp] = DpSpec(dp=dp, type=value_type_of(value), writable=True, from_device=True)
                new_specs = True
        self._set_online(stable, True, notify=False)
        if new_specs:
            self._save()
            async_dispatcher_send(self.hass, SIGNAL_NEW_DPS, stable)
        async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATE.format(stable))

    @callback
    def _on_subdevices(self, gw_stable: str, online: set[str], every: set[str]) -> None:
        before = {(c.stable, c.node) for c in self._children_of(gw_stable)}
        reassigned = False
        for dev in self.devices.values():
            if not dev.sub:
                continue
            match = next((n for n in dev.node_candidates if n in every), None)
            link = self.subs.get(dev.stable)
            if match and (not link or link != {"gateway": gw_stable, "node": match}):
                self.subs[dev.stable] = {"gateway": gw_stable, "node": match}
                reassigned = True
            link = self.subs.get(dev.stable)
            if link and link.get("gateway") == gw_stable and every:
                self._set_online(dev.stable, link["node"] in online)
        if reassigned:
            self._save()
            for sub, link in self.subs.items():
                if link.get("gateway") == gw_stable:
                    self.link_to_gateway(sub)
            if {(c.stable, c.node) for c in self._children_of(gw_stable)} != before:
                self._restart(gw_stable)

    @callback
    def _on_broadcast(self, found: dict[str, Any]) -> None:
        stable = self.stable_of(found["id"])
        if stable is None:
            return
        info = self.endpoints.setdefault(stable, {})
        if info.get("source") == "manual":
            return
        version = found.get("version") or info.get("version")
        if info.get("ip") != found["ip"]:
            _LOGGER.info("%s: found at %s", self.devices[stable].name, found["ip"])
            info.update(ip=found["ip"], version=version, source="broadcast")
            self._save()
            self._restart(stable)

    @callback
    def _set_online(self, stable: str, online: bool, notify: bool = True) -> None:
        was = stable in self.local_online
        if online:
            self.local_online.add(stable)
        else:
            self.local_online.discard(stable)
        if notify and was != online:
            async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATE.format(stable))

    # ------------------------------------------------------------------ scanning
    async def _scan_later(self, _now: Any = None) -> None:
        await self.async_scan()

    def _missing_endpoints(self) -> list[str]:
        missing = []
        for dev in self.devices.values():
            if dev.sub or (not dev.is_gateway and not dev.dps):
                continue
            conn = self.connections.get(dev.stable)
            info = self.endpoints.get(dev.stable, {})
            if info.get("source") == "manual":
                continue
            if not info.get("ip") or (conn is not None and not conn.connected and self._failures.get(dev.stable, 0)):
                missing.append(dev.stable)
        return missing

    async def _networks_to_scan(self) -> list[ipaddress.IPv4Network]:
        adapters = await network.async_get_adapters(self.hass)
        addresses = [
            (ip["address"], ip["network_prefix"])
            for adapter in adapters if adapter.get("enabled")
            for ip in adapter.get("ipv4", [])
        ]
        nets = scan_networks(addresses)
        extra = parse_networks(self.entry.options.get(CONF_NETWORKS))
        # networks where devices were seen before (a device that moved usually stays on its LAN)
        extra += parse_networks([i["ip"] for i in self.endpoints.values() if i.get("ip")])
        if in_container(addresses, CONTAINER_NETWORK):
            extra += parse_networks(list(COMMON_HOME_NETWORKS))
        for net in extra:
            if net not in nets:
                nets.append(net)
        return nets

    async def async_scan(self, force: bool = False) -> int:
        """Look for missing devices on the local network. Returns how many were found."""
        if (
            not force and self._last_scan is not None
            and time.monotonic() - self._last_scan < SCAN_COOLDOWN
        ):
            return 0
        missing = self._missing_endpoints()
        if not missing:
            return 0
        self._last_scan = time.monotonic()
        nets = await self._networks_to_scan()
        hosts = await find_open_hosts(nets)
        _LOGGER.debug("Scan of %s: Tuya port open on %s", [str(n) for n in nets], hosts)
        busy = {
            self.endpoints[s]["ip"] for s, c in self.connections.items()
            if c.connected and s in self.endpoints
        }
        hosts = [h for h in hosts if h not in busy]
        # Gateways first (they carry many devices), then Wi-Fi devices.
        missing.sort(key=lambda s: not self.devices[s].is_gateway)
        claimed: dict[str, str] = {}  # stable -> host

        async def try_host(host: str) -> None:
            # One host at a time per device; hosts in parallel.
            for stable in missing:
                if stable in claimed:
                    continue
                dev = self.devices[stable]
                ep = self._endpoint_for(stable)
                keys = ep.keys if ep else self._candidate_keys(dev)
                ids = self._gateway_ids(dev) if dev.is_gateway else [dev.id]
                hit = await self.hass.async_add_executor_job(
                    probe_endpoint, host, ids, keys, not dev.is_gateway,
                    self.endpoints.get(stable, {}).get("version"),
                )
                if hit and stable not in claimed:
                    version, key, dev_id = hit
                    claimed[stable] = host
                    self.endpoints[stable] = {
                        "ip": host, "version": version, "key": key, "dev_id": dev_id, "source": "scan",
                    }
                    _LOGGER.info("%s: found at %s by network scan", dev.name, host)
                    return

        await asyncio.gather(*(try_host(h) for h in hosts))
        for stable in claimed:
            self._restart(stable)
        self.last_scan_found = len(claimed)
        self._save()
        return len(claimed)

    def _gateway_ids(self, dev: DeviceInfo) -> list[str]:
        """Ids a gateway may answer to: its own, then its sub-devices'."""
        return [dev.id] + [d.id for d in self.devices.values() if d.sub]

    def _candidate_keys(self, dev: DeviceInfo) -> list[str]:
        if dev.is_gateway:
            return [dev.key] + [d.key for d in self.devices.values() if d.sub]
        return [dev.key]

    # ------------------------------------------------------------------ entities
    def value(self, stable: str, dp: str) -> Any:
        if dp in self.state.get(stable, {}):
            return self.state[stable][dp]
        dev = self.devices.get(stable)
        spec = dev.dps.get(dp) if dev else None
        if spec and spec.code and dev:
            return dev.cloud_status.get(spec.code)
        return None

    def available(self, stable: str) -> bool:
        dev = self.devices.get(stable)
        return stable in self.local_online or bool(dev and dev.cloud_online)

    async def async_set(self, stable: str, dp: str, value: Any) -> None:
        await self.async_set_many(stable, {dp: value})

    async def async_set_many(self, stable: str, values: dict[str, Any]) -> None:
        """Send one or more data points together (locally, else via the Tuya cloud)."""
        dev = self.devices[stable]
        ep = self.endpoint_of(stable)
        conn = self.connections.get(ep) if ep else None
        if conn is not None and not conn.is_alive():
            self._restart(ep)  # worker stopped unexpectedly: start a fresh one
            conn = None
        sent = conn is not None and stable in self.local_online and conn.send(stable, dict(values))
        if not sent:
            if not dev.cloud_online or self._cloud is None:
                raise HomeAssistantError(f"{dev.name} is not reachable right now")
            for dp, value in values.items():
                spec = dev.dps.get(dp)
                if not spec or not spec.code:
                    raise HomeAssistantError(f"{dev.name} is not reachable right now")
                try:
                    await self.hass.async_add_executor_job(self._cloud.send, dev.id, spec.code, value)
                except CloudError as err:
                    raise HomeAssistantError(f"{dev.name}: {err}") from err
                dev.cloud_status[spec.code] = value
        self.state.setdefault(stable, {}).update(values)
        async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATE.format(stable))


def _differs(a: Endpoint, b: Endpoint) -> bool:
    return (
        a.ip != b.ip or a.dev_id != b.dev_id
        or {k for k in a.keys if k} != {k for k in b.keys if k}
        or [(c.dev_id, c.node) for c in a.children] != [(c.dev_id, c.node) for c in b.children]
    )


def _join(conns: list[LocalConnection]) -> None:
    for conn in conns:
        conn.join(timeout=5)
