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
        return "UPID:pci-op"


class _FakeQemuVm:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = _FakeConfig(config)


class _FakeQemuCollection:
    def __init__(self, config: dict[str, Any]) -> None:
        self._vm = _FakeQemuVm(config)

    def __call__(self, vmid: int) -> _FakeQemuVm:
        return self._vm


class _FakeHardwarePci:
    def __init__(self, devices: list[dict[str, Any]]) -> None:
        self._devices = devices

    def get(self) -> list[dict[str, Any]]:
        return list(self._devices)


class _FakeHardware:
    def __init__(self, pci_devices: list[dict[str, Any]]) -> None:
        self.pci = _FakeHardwarePci(pci_devices)


class _FakeNode:
    def __init__(
        self,
        config: dict[str, Any],
        pci_devices: list[dict[str, Any]] | None = None,
    ) -> None:
        self.qemu = _FakeQemuCollection(config)
        self.hardware = _FakeHardware(pci_devices or [])


class _FakeNodes:
    def __init__(
        self,
        config: dict[str, Any],
        pci_devices: list[dict[str, Any]] | None = None,
    ) -> None:
        self._node = _FakeNode(config, pci_devices)

    def __call__(self, node: str) -> _FakeNode:
        return self._node


class _FakeClusterMappingPci:
    def __init__(self, mappings: list[dict[str, Any]]) -> None:
        self._mappings = mappings

    def get(self) -> list[dict[str, Any]]:
        return list(self._mappings)


class _FakeClusterMapping:
    def __init__(self, pci_mappings: list[dict[str, Any]]) -> None:
        self.pci = _FakeClusterMappingPci(pci_mappings)


class _FakeCluster:
    def __init__(self, pci_mappings: list[dict[str, Any]]) -> None:
        self.mapping = _FakeClusterMapping(pci_mappings)


class _FakeApi:
    def __init__(
        self,
        config: dict[str, Any],
        pci_devices: list[dict[str, Any]] | None = None,
        pci_mappings: list[dict[str, Any]] | None = None,
    ) -> None:
        self.nodes = _FakeNodes(config, pci_devices)
        self.cluster = _FakeCluster(pci_mappings or [])


def _build_client(
    config: dict[str, Any],
    *,
    pci_devices: list[dict[str, Any]] | None = None,
    pci_mappings: list[dict[str, Any]] | None = None,
) -> tuple[ProxmoxClient, _FakeConfig]:
    client = ProxmoxClient.__new__(ProxmoxClient)
    client._api = cast(Any, _FakeApi(config, pci_devices, pci_mappings))
    client.default_storage = "local-lvm"
    fake_config = cast(_FakeConfig, client._api.nodes("pve").qemu(101).config)
    return client, fake_config


def test_list_vm_pci_parses_host_mapping_and_options() -> None:
    client, _ = _build_client(
        {
            "name": "vm-101",
            "hostpci0": "host=0000:01:00.0,pcie=1,x-vga=1",
            "hostpci1": "mapping=gpu-pool,mdev=nvidia-256",
            "hostpci3": "01:00.0,rombar=0",
            "scsi0": "local-lvm:vm-101-disk-0,size=20G",
        }
    )

    devices = client.list_vm_pci("pve", 101)

    assert [d["device"] for d in devices] == ["hostpci0", "hostpci1", "hostpci3"]
    assert devices[0]["host"] == "0000:01:00.0"
    assert devices[0]["pcie"] is True
    assert devices[0]["x_vga"] is True
    assert devices[1]["mapping"] == "gpu-pool"
    assert devices[1]["mdev"] == "nvidia-256"
    assert devices[2]["host"] == "01:00.0"
    assert devices[2]["rombar"] is False


def test_vm_pci_add_picks_lowest_free_slot() -> None:
    client, fake = _build_client(
        {"hostpci0": "host=0000:01:00.0", "hostpci2": "mapping=x"}
    )

    result = client.vm_pci_add("pve", 101, host="0000:02:00.0")

    assert result["added"] == "hostpci1"
    assert result["config"] == "host=0000:02:00.0"
    assert fake.put_calls[-1] == {"hostpci1": "host=0000:02:00.0"}


def test_vm_pci_add_serializes_options_in_proxmox_format() -> None:
    client, fake = _build_client({})

    result = client.vm_pci_add(
        "pve",
        101,
        host="0000:01:00.0",
        pcie=True,
        rombar=False,
        x_vga=True,
        mdev="nvidia-256",
        slot=4,
    )

    assert result["added"] == "hostpci4"
    assert fake.put_calls[-1] == {
        "hostpci4": "host=0000:01:00.0,pcie=1,rombar=0,x-vga=1,mdev=nvidia-256"
    }


def test_vm_pci_add_accepts_short_pci_address() -> None:
    client, fake = _build_client({})

    client.vm_pci_add("pve", 101, host="01:00.0")

    assert fake.put_calls[-1] == {"hostpci0": "host=01:00.0"}


def test_vm_pci_add_requires_exactly_one_source() -> None:
    client, _ = _build_client({})

    with pytest.raises(ValueError, match="exactly one"):
        client.vm_pci_add("pve", 101)
    with pytest.raises(ValueError, match="exactly one"):
        client.vm_pci_add("pve", 101, host="0000:01:00.0", mapping="m")


def test_vm_pci_add_rejects_malformed_address() -> None:
    client, _ = _build_client({})

    with pytest.raises(ValueError, match="Invalid PCI address"):
        client.vm_pci_add("pve", 101, host="not-a-pci-addr")
    with pytest.raises(ValueError, match="Invalid PCI address"):
        client.vm_pci_add("pve", 101, host="01:00")  # missing function


def test_vm_pci_add_rejects_taken_slot() -> None:
    client, _ = _build_client({"hostpci5": "host=0000:01:00.0"})

    with pytest.raises(ValueError, match="hostpci5 is already in use"):
        client.vm_pci_add("pve", 101, host="0000:02:00.0", slot=5)


def test_vm_pci_remove_issues_delete() -> None:
    client, fake = _build_client({"hostpci0": "host=0000:01:00.0"})

    result = client.vm_pci_remove("pve", 101, slot=0)

    assert result == {"upid": "UPID:pci-op", "removed": "hostpci0"}
    assert fake.put_calls[-1] == {"delete": "hostpci0"}


def test_list_host_pci_proxies_to_hardware_endpoint() -> None:
    devices = [{"id": "0000:01:00.0", "vendor": "0x10de", "device": "0x2204"}]
    client, _ = _build_client({}, pci_devices=devices)

    assert client.list_host_pci("pve") == devices


def test_list_cluster_pci_mappings_proxies_to_cluster_endpoint() -> None:
    mappings = [{"id": "gpu-pool", "map": [{"node": "pve", "path": "0000:01:00.0"}]}]
    client, _ = _build_client({}, pci_mappings=mappings)

    assert client.list_cluster_pci_mappings() == mappings
