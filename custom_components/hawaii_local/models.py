"""Device model shared by the cloud import, local connections and entities."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any

from .const import GATEWAY_CATEGORIES

# Codes never exposed as switches: one tap would wipe or reboot the device.
DANGEROUS_CODES = ("factory_reset", "reset", "reboot", "restore_factory")

# Codes that are settings rather than loads; shown as configuration switches.
CONFIG_CODES = (
    "child_lock", "switch_backlight", "backlight", "light_mode", "relay_status",
    "switch_inching", "switch_buzzer", "led", "indicator",
)


@dataclass
class DpSpec:
    """One data point (DP) of a device."""

    dp: str
    code: str | None = None
    type: str = "Boolean"      # Boolean / Integer / Enum / String / Json / Raw
    writable: bool = True
    from_device: bool = False  # found on the device itself, not in Tuya's profile
    values: dict[str, Any] = field(default_factory=dict)  # min/max/scale/step or range

    def scaled(self, raw: Any) -> float | None:
        """Device value -> real number (Integer DPs carry a decimal scale)."""
        if raw is None:
            return None
        try:
            return float(raw) / (10 ** int(self.values.get("scale", 0)))
        except (TypeError, ValueError):
            return None


@dataclass
class DeviceInfo:
    """A Tuya device as Hawaii Local knows it.

    `stable` identifies the hardware and survives re-pairing (the Tuya device id
    and local key may change after a reset, the hardware uuid / Zigbee node do not).
    """

    id: str
    stable: str
    name: str
    key: str
    category: str
    product_id: str = ""
    product_name: str = ""
    sub: bool = False
    node_candidates: list[str] = field(default_factory=list)
    cloud_online: bool = False
    dps: dict[str, DpSpec] = field(default_factory=dict)
    cloud_status: dict[str, Any] = field(default_factory=dict)  # code -> value

    def __post_init__(self) -> None:
        # Some multi-mode gateways are listed by Tuya as sub-devices (of their own
        # BLE/Zigbee radio). A gateway always has its own IP, so treat it as one.
        if self.category in GATEWAY_CATEGORIES:
            self.sub = False

    @property
    def is_gateway(self) -> bool:
        return self.category in GATEWAY_CATEGORIES

    @property
    def code_to_dp(self) -> dict[str, str]:
        return {s.code: s.dp for s in self.dps.values() if s.code}

    def switch_dps(self) -> list[DpSpec]:
        return sorted(
            (
                s for s in self.dps.values()
                if s.type == "Boolean" and s.writable and (s.code or "") not in DANGEROUS_CODES
            ),
            key=lambda s: int(s.dp) if s.dp.isdigit() else 0,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["dps"] = {k: asdict(v) for k, v in self.dps.items()}
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceInfo:
        data = dict(data)
        data["dps"] = {k: DpSpec(**v) for k, v in data.get("dps", {}).items()}
        return cls(**data)


def _norm_node(value: Any) -> str | None:
    if not value or not isinstance(value, str):
        return None
    value = value.replace(":", "").replace("-", "").strip().lower()
    return value or None


def from_cloud(dev: Any) -> DeviceInfo:
    """Build a DeviceInfo from a tuya_sharing CustomerDevice (all raw fields kept)."""
    get = lambda name, default=None: getattr(dev, name, default)  # noqa: E731
    uuid = get("uuid") or ""
    sub = bool(get("sub", False))
    nodes: list[str] = []
    for raw in (get("node_id"), get("cid"), uuid if sub else None, get("mac")):
        node = _norm_node(raw)
        if node and node not in nodes:
            nodes.append(node)

    dps: dict[str, DpSpec] = {}
    functions = get("function") or {}
    for dp_id, strat in (get("local_strategy") or {}).items():
        code = (strat or {}).get("status_code")
        item = (strat or {}).get("config_item") or {}
        vtype = item.get("valueType") or _type_of(get, code)
        dps[str(dp_id)] = DpSpec(
            dp=str(dp_id), code=code, type=vtype or "Raw", writable=code in functions,
            values=_values_of(get, code, item),
        )
    status = get("status") or {}
    return DeviceInfo(
        id=get("id"),
        stable=(uuid or get("id")),
        name=get("name") or get("id"),
        key=get("local_key") or "",
        category=get("category") or "",
        product_id=get("product_id") or "",
        product_name=get("product_name") or "",
        sub=sub,
        node_candidates=nodes,
        cloud_online=bool(get("online", False)),
        dps=dps,
        cloud_status=dict(status) if isinstance(status, dict) else {},
    )


def _parse_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            data = json.loads(raw)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _values_of(get, code: str | None, item: dict[str, Any]) -> dict[str, Any]:
    """Ranges from the Tuya profile: {'min','max','scale','step'} or {'range': [...]}."""
    values = _parse_json(item.get("valueDesc"))
    for source in (get("function") or {}, get("status_range") or {}):
        spec = source.get(code) if code else None
        if spec is None:
            continue
        raw = getattr(spec, "values", None) if not isinstance(spec, dict) else spec.get("values")
        for key, val in _parse_json(raw).items():
            values.setdefault(key, val)
    keep = ("min", "max", "scale", "step", "range", "unit")
    return {k: v for k, v in values.items() if k in keep}


def _type_of(get, code: str | None) -> str | None:
    for source in (get("function") or {}, get("status_range") or {}):
        spec = source.get(code) if code else None
        if spec is not None:
            return getattr(spec, "type", None) or (spec.get("type") if isinstance(spec, dict) else None)
    return None


_LIGHT = re.compile(r"^switch_led(_\d+)?$")
_COVER = re.compile(r"^control(_\d+)?$")


def light_channels(dev: DeviceInfo) -> list[dict[str, DpSpec | None]]:
    """Dimmable lights: switch_led[_N] with its bright_value[_N] (if any)."""
    by_code = {s.code: s for s in dev.dps.values() if s.code}
    out = []
    for code, spec in sorted(by_code.items()):
        m = _LIGHT.match(code)
        if not m or spec.type != "Boolean":
            continue
        suffix = m.group(1) or ""
        bright = by_code.get(f"bright_value{suffix}") or (by_code.get("bright_value_v2") if not suffix else None)
        out.append({"switch": spec, "bright": bright})
    return out


def cover_channels(dev: DeviceInfo) -> list[dict[str, DpSpec | None]]:
    """Curtains: control[_N] (open/stop/close) with percent_control / percent_state."""
    by_code = {s.code: s for s in dev.dps.values() if s.code}
    out = []
    for code, spec in sorted(by_code.items()):
        m = _COVER.match(code)
        if not m or spec.type != "Enum" or not spec.writable:
            continue
        suffix = m.group(1) or ""
        out.append({
            "control": spec,
            "set": by_code.get(f"percent_control{suffix}"),
            "state": by_code.get(f"percent_state{suffix}"),
        })
    return out


def dp_name(spec: DpSpec, total_switches: int) -> str:
    """Friendly entity name for a data point."""
    code = spec.code or ""
    if code in ("switch", "switch_1") and total_switches == 1:
        return "Power"
    if code == "switch_led":
        return "Light"
    if code.startswith("switch_") and code[7:].isdigit():
        return f"Switch {code[7:]}"
    if code:
        return code.replace("_", " ").capitalize()
    return f"Channel {spec.dp}"


def value_type_of(value: Any) -> str:
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, int):
        return "Integer"
    if isinstance(value, (dict, list)):
        return "Json"
    try:
        json.loads(value)
    except (TypeError, ValueError):
        return "String"
    return "String"
