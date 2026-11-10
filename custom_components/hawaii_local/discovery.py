"""Finding devices on the home network.

1. Listen for the broadcasts Tuya devices send every few seconds (device id,
   IP, protocol version). An IP change is picked up within seconds.
2. When broadcasts don't arrive (e.g. Home Assistant in Docker without host
   networking), scan the local subnet for Tuya's port and let the hub test the
   open hosts with each missing device's key; only the right device accepts it.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import ipaddress
import json
import logging
import socket
from typing import Any

from tinytuya import decrypt_udp

from .const import LOCAL_PORT, UDP_PORTS

_LOGGER = logging.getLogger(__name__)


def parse_broadcast(data: bytes) -> dict[str, Any] | None:
    """Decode one Tuya UDP broadcast into {'id', 'ip', 'version'}."""
    try:
        text = decrypt_udp(data)
        if isinstance(text, bytes):
            text = text.decode(errors="ignore")
        msg = json.loads(text)
    except Exception:  # noqa: BLE001 - foreign or garbled packets are normal
        return None
    dev_id, ip = msg.get("gwId"), msg.get("ip")
    if not dev_id or not ip:
        return None
    return {"id": dev_id, "ip": ip, "version": str(msg.get("version") or "")}


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, on_found: Callable[[dict[str, Any]], None]) -> None:
        self._on_found = on_found

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if (found := parse_broadcast(data)) is not None:
            self._on_found(found)


class BroadcastListener:
    """Listens on Tuya's UDP ports for device announcements."""

    def __init__(self, on_found: Callable[[dict[str, Any]], None]) -> None:
        self._on_found = on_found
        self._transports: list[asyncio.DatagramTransport] = []

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        for port in UDP_PORTS:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket, "SO_REUSEPORT"):
                    try:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                    except OSError:
                        pass
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind(("", port))
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: _Protocol(self._on_found), sock=sock
                )
                self._transports.append(transport)
            except OSError as err:
                _LOGGER.debug("Can't listen on UDP %s: %s", port, err)

    def stop(self) -> None:
        for transport in self._transports:
            transport.close()
        self._transports.clear()


def scan_networks(addresses: list[tuple[str, int]]) -> list[ipaddress.IPv4Network]:
    """The /24 (or smaller) networks to scan for the given local addresses."""
    nets: list[ipaddress.IPv4Network] = []
    for addr, prefix in addresses:
        try:
            net = ipaddress.ip_network(f"{addr}/{max(prefix, 24)}", strict=False)
        except ValueError:
            continue
        if net.version == 4 and not net.is_loopback and not net.is_link_local and net not in nets:
            nets.append(net)
    return nets


def parse_networks(values: list[str] | str | None) -> list[ipaddress.IPv4Network]:
    """'192.168.0.0/24, 10.0.0.5' -> networks (a bare IP means its /24)."""
    if isinstance(values, str):
        values = values.replace(";", ",").replace(" ", ",").split(",")
    nets: list[ipaddress.IPv4Network] = []
    for raw in values or []:
        raw = raw.strip()
        if not raw:
            continue
        if "/" not in raw:
            raw = f"{raw}/24"
        try:
            net = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            continue
        if net.version == 4 and net.prefixlen >= 16 and net not in nets:
            nets.append(net)
    return nets


def in_container(addresses: list[tuple[str, int]], container_net: str) -> bool:
    """True when every local address is on a Docker-style private bridge network."""
    inside = ipaddress.ip_network(container_net)
    private = [
        ipaddress.ip_address(a) for a, _ in addresses
        if not ipaddress.ip_address(a).is_loopback
    ]
    return bool(private) and all(a in inside for a in private)


async def find_open_hosts(
    networks: list[ipaddress.IPv4Network], timeout: float = 0.6, limit: int = 256
) -> list[str]:
    """Hosts in the networks that accept connections on Tuya's local port."""
    sem = asyncio.Semaphore(limit)

    async def probe(ip: str) -> str | None:
        async with sem:
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(ip, LOCAL_PORT), timeout)
            except (OSError, asyncio.TimeoutError):
                return None
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            return ip

    hosts = [str(h) for net in networks for h in net.hosts()]
    results = await asyncio.gather(*(probe(ip) for ip in hosts))
    return [ip for ip in results if ip]
