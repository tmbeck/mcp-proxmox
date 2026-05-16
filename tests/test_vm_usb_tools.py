from __future__ import annotations

from typing import Any, cast

import pytest

from proxmox_mcp.client import ProxmoxClient


class _FakeConfig:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self.put_calls: list[dict[str, Any]] = []

    def get(self) -> dict[str, Any]:
        return dict(self._config)

    def put(self, **kwargs: Any) -> str:
        self.put_calls.append(kwargs)
        if "delete" in kwargs:
            self._config.pop(kwargs["delete"], None)
        else:
            for k, v in kwargs.items():
                self._config[k] = v
        return "UPID:usb-op"


class _FakeQemuVm:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = _FakeConfig(config)


class _FakeQemuCollection:
    def __init__(self, config: dict[str, Any]) -> None:
        self._vm = _FakeQemuVm(config)

    def __call__(self, vmid: int) -> _FakeQemuVm:
        return self._vm


class _FakeHardware:
    def __init__(self, usb_devices: list[dict[str, Any]]) -> None:
        self.usb = _FakeHardwareUsb(usb_devices)


class _FakeHardwareUsb:
    def __init__(self, devices: list[dict[str, Any]]) -> None:
        self._devices = devices

    def get(self) -> list[dict[str, Any]]:
        return list(self._devices)


class _FakeNode:
    def __init__(
        self,
        config: dict[str, Any],
        usb_devices: list[dict[str, Any]] | None = None,
    ) -> None:
        self.qemu = _FakeQemuCollection(config)
        self.hardware = _FakeHardware(usb_devices or [])


class _FakeNodes:
    def __init__(
        self,
        config: dict[str, Any],
        usb_devices: list[dict[str, Any]] | None = None,
    ) -> None:
        self._node = _FakeNode(config, usb_devices)

    def __call__(self, node: str) -> _FakeNode:
        return self._node


class _FakeClusterMappingUsb:
    def __init__(self, mappings: list[dict[str, Any]]) -> None:
        self._mappings = mappings

    def get(self) -> list[dict[str, Any]]:
        return list(self._mappings)


class _FakeClusterMapping:
    def __init__(self, usb_mappings: list[dict[str, Any]]) -> None:
        self.usb = _FakeClusterMappingUsb(usb_mappings)


class _FakeCluster:
    def __init__(self, usb_mappings: list[dict[str, Any]]) -> None:
        self.mapping = _FakeClusterMapping(usb_mappings)


class _FakeApi:
    def __init__(
        self,
        config: dict[str, Any],
        usb_devices: list[dict[str, Any]] | None = None,
        usb_mappings: list[dict[str, Any]] | None = None,
    ) -> None:
        self.nodes = _FakeNodes(config, usb_devices)
        self.cluster = _FakeCluster(usb_mappings or [])


def _build_client(
    config: dict[str, Any],
    *,
    usb_devices: list[dict[str, Any]] | None = None,
    usb_mappings: list[dict[str, Any]] | None = None,
) -> tuple[ProxmoxClient, _FakeConfig]:
    client = ProxmoxClient.__new__(ProxmoxClient)
    client._api = cast(Any, _FakeApi(config, usb_devices, usb_mappings))
    client.default_storage = "local-lvm"
    fake_config = cast(_FakeConfig, client._api.nodes("pve").qemu(101).config)
    return client, fake_config


def test_list_vm_usb_parses_vid_pid_and_mapping_and_spice() -> None:
    client, _ = _build_client(
        {
            "name": "vm-101",
            "usb0": "host=0951:1666,usb3=1",
            "usb1": "mapping=yubikey",
            "usb3": "host=spice",
            "usb10": "host=1-2.4",
            "scsi0": "local-lvm:vm-101-disk-0,size=20G",
        }
    )

    devices = client.list_vm_usb("pve", 101)

    assert [d["device"] for d in devices] == ["usb0", "usb1", "usb3", "usb10"]
    assert devices[0]["host_vendor_product"] == "0951:1666"
    assert devices[0]["usb3"] is True
    assert devices[1]["mapping"] == "yubikey"
    assert devices[2]["spice"] is True
    assert devices[3]["host_bus_port"] == "1-2.4"


def test_vm_usb_add_picks_lowest_free_slot() -> None:
    client, fake = _build_client({"usb0": "host=0951:1666", "usb2": "mapping=m"})

    result = client.vm_usb_add("pve", 101, host="1a2b:3c4d")

    assert result["added"] == "usb1"
    assert result["config"] == "host=1a2b:3c4d"
    assert fake.put_calls[-1] == {"usb1": "host=1a2b:3c4d"}


def test_vm_usb_add_respects_explicit_slot() -> None:
    client, fake = _build_client({})

    result = client.vm_usb_add("pve", 101, host="0951:1666", usb3=True, slot=5)

    assert result["added"] == "usb5"
    assert fake.put_calls[-1] == {"usb5": "host=0951:1666,usb3=1"}


def test_vm_usb_add_rejects_taken_slot() -> None:
    client, _ = _build_client({"usb4": "host=spice"})

    with pytest.raises(ValueError, match="usb4 is already in use"):
        client.vm_usb_add("pve", 101, host="0951:1666", slot=4)


def test_vm_usb_add_requires_exactly_one_source() -> None:
    client, _ = _build_client({})

    with pytest.raises(ValueError, match="exactly one"):
        client.vm_usb_add("pve", 101)
    with pytest.raises(ValueError, match="exactly one"):
        client.vm_usb_add("pve", 101, host="0951:1666", mapping="m")


def test_vm_usb_add_rejects_malformed_host() -> None:
    client, _ = _build_client({})

    with pytest.raises(ValueError, match="Invalid USB host"):
        client.vm_usb_add("pve", 101, host="not-a-device")
    with pytest.raises(ValueError, match="Invalid USB host"):
        client.vm_usb_add("pve", 101, host="0951:166")  # too short


def test_vm_usb_add_accepts_mapping_and_spice() -> None:
    client, fake = _build_client({})

    r1 = client.vm_usb_add("pve", 101, mapping="yubikey")
    assert fake.put_calls[-1] == {"usb0": "mapping=yubikey"}
    assert r1["added"] == "usb0"

    r2 = client.vm_usb_add("pve", 101, spice=True)
    assert fake.put_calls[-1] == {"usb1": "host=spice"}
    assert r2["added"] == "usb1"


def test_vm_usb_remove_issues_delete() -> None:
    client, fake = _build_client({"usb0": "host=0951:1666"})

    result = client.vm_usb_remove("pve", 101, slot=0)

    assert result == {"upid": "UPID:usb-op", "removed": "usb0"}
    assert fake.put_calls[-1] == {"delete": "usb0"}


def test_list_host_usb_proxies_to_hardware_endpoint() -> None:
    devices = [{"vendid": "0x0951", "prodid": "0x1666", "busnum": 1, "devnum": 4}]
    client, _ = _build_client({}, usb_devices=devices)

    assert client.list_host_usb("pve") == devices


def test_list_cluster_usb_mappings_proxies_to_cluster_endpoint() -> None:
    mappings = [{"id": "yubikey", "map": [{"node": "pve", "path": "1-2"}]}]
    client, _ = _build_client({}, usb_mappings=mappings)

    assert client.list_cluster_usb_mappings() == mappings
