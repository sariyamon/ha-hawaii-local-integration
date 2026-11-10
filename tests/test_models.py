"""Import from the Tuya sharing SDK device objects."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.hawaii_local.models import DeviceInfo, dp_name, from_cloud


def test_from_cloud_sub_device() -> None:
    dev = SimpleNamespace(
        id="d7f73e4d873095d5adwsdj", name="office", local_key="k", category="cjkg",
        product_id="x98awb3y", product_name="6&8 Module Super Switch", sub=True,
        uuid="D8:78:F0:FF:FE:92:0E:8D", online=False, status={"switch_7": False},
        function={"switch_7": SimpleNamespace(type="Boolean")},
        status_range={"switch_7": SimpleNamespace(type="Boolean")},
        local_strategy={107: {"status_code": "switch_7", "config_item": {"valueType": "Boolean"}},
                        2: {"status_code": "scene_2", "config_item": {"valueType": "Enum"}}},
    )
    info = from_cloud(dev)
    assert info.stable == "D8:78:F0:FF:FE:92:0E:8D"
    assert info.node_candidates == ["d878f0fffe920e8d"]
    assert info.dps["107"].writable and info.dps["107"].code == "switch_7"
    assert not info.dps["2"].writable
    assert [s.dp for s in info.switch_dps()] == ["107"]
    assert dp_name(info.dps["107"], 1) == "Switch 7"
    assert DeviceInfo.from_dict(info.to_dict()) == info
