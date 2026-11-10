"""Constants for Hawaii Local."""
from __future__ import annotations

DOMAIN = "hawaii_local"

# Tuya "Smart Life" app sign-in (same public client the Home Assistant Tuya
# integration uses for QR login; no Tuya developer account needed).
TUYA_CLIENT_ID = "HA_3y9q4ak7g4ephrvke"
TUYA_SCHEMA = "haauthorize"

CONF_USER_CODE = "user_code"
CONF_TERMINAL_ID = "terminal_id"
CONF_ENDPOINT = "endpoint"
CONF_TOKEN_INFO = "token_info"
CONF_OVERRIDES = "overrides"  # options: {stable_id: {"ip": str, "version": str}}
CONF_NETWORKS = "networks"    # options: extra networks to scan, e.g. ["192.168.0.0/24"]

PROTOCOLS = ["3.4", "3.5", "3.3", "3.1", "3.2"]  # order tried when unknown
VERSION_AUTO = "auto"

# Device categories that are gateways (Zigbee/BLE hubs) rather than end devices.
GATEWAY_CATEGORIES = {"wg2", "wfcon", "wg", "wgsxj", "zigbee_gateway"}

# Local network
LOCAL_PORT = 6668
UDP_PORTS = (6666, 6667, 7000)

# Home Assistant in Docker (bridge networking) only sees its own private network,
# not the home LAN. Then these usual home-router subnets are scanned as well.
COMMON_HOME_NETWORKS = (
    "192.168.0.0/24", "192.168.1.0/24", "192.168.29.0/24", "192.168.31.0/24",
    "192.168.2.0/24", "192.168.68.0/24", "192.168.86.0/24", "192.168.100.0/24",
    "192.168.10.0/24", "192.168.18.0/24", "10.0.0.0/24", "10.0.1.0/24",
)
CONTAINER_NETWORK = "172.16.0.0/12"  # Docker's default bridge networks

# Timing (seconds)
HEARTBEAT = 10
RECEIVE_TIMEOUT = 1.0
RECONNECT_MIN = 5
RECONNECT_MAX = 120
DISCOVERY_GRACE = 20          # wait for broadcasts before scanning the network
SCAN_COOLDOWN = 300           # at most one network scan per 5 minutes
CLOUD_REFRESH_COOLDOWN = 300  # at most one "keys changed?" cloud refresh per 5 minutes
CLOUD_REFRESH_INTERVAL = 6 * 3600  # routine refresh to pick up renamed/added devices
FAILURES_BEFORE_RESCAN = 3

SIGNAL_DEVICE_UPDATE = f"{DOMAIN}_device_update_{{}}"  # format with stable id
SIGNAL_NEW_DPS = f"{DOMAIN}_new_dps"

STORAGE_VERSION = 1
