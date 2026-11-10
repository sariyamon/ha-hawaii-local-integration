"""Broadcast decoding and scan ranges."""
from __future__ import annotations

import ipaddress
import json

from tinytuya.core.crypto_helper import AESCipher
from tinytuya.core.udp_helper import udpkey

from custom_components.hawaii_local.discovery import parse_broadcast, scan_networks


def test_parse_encrypted_broadcast() -> None:
    msg = {"ip": "192.168.0.87", "gwId": "gw0001", "active": 2, "version": "3.4", "productKey": "x"}
    packet = AESCipher(udpkey).encrypt(json.dumps(msg).encode(), False)
    assert parse_broadcast(packet) == {"id": "gw0001", "ip": "192.168.0.87", "version": "3.4"}
    assert parse_broadcast(b"garbage") is None


def test_scan_networks() -> None:
    nets = scan_networks([("192.168.0.10", 16), ("127.0.0.1", 8), ("192.168.0.20", 24)])
    assert nets == [ipaddress.ip_network("192.168.0.0/24")]
