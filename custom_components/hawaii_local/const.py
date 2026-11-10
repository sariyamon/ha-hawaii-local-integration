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

PROTOCOLS = ["3.4", "3.5", "3.3", "3.1", "3.2"]  # order tried when unknown
VERSION_AUTO = "auto"

# Device categories that are gateways (Zigbee/BLE hubs) rather than end devices.
GATEWAY_CATEGORIES = {"wg2", "wfcon", "wg", "wgsxj", "zigbee_gateway"}

# Local network
LOCAL_PORT = 6668
UDP_PORTS = (6666, 6667, 7000)

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
