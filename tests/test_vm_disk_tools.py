from __future__ import annotations

from typing import Any

from proxmox_mcp.client import ProxmoxClient


class _FakeConfig:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self.put_calls: list[dict[str, Any]] = []

    def get(self) -> dict[str, Any]:
        return dict(self._config)

    def put(self, **kwargs: Any) -> str:
        self.put_calls.append(kwargs)
        return "UPID:disk-op"


class _FakeQemuVm:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = _FakeConfig(config)


class _FakeQemuCollection:
    def __init__(self, config: dict[str, Any]) -> None:
        self._vm = _FakeQemuVm(config)

    def __call__(self, vmid: int) -> _FakeQemuVm:
        return self._vm


class _FakeNode:
    def __init__(self, config: dict[str, Any]) -> None:
        self.qemu = _FakeQemuCollection(config)


class _FakeNodes:
    def __init__(self, config: dict[str, Any]) -> None:
        self._node = _FakeNode(config)

    def __call__(self, node: str) -> _FakeNode:
        return self._node


class _FakeApi:
    def __init__(self, config: dict[str, Any]) -> None:
        self.nodes = _FakeNodes(config)


def _build_client(config: dict[str, Any]) -> tuple[ProxmoxClient, _FakeConfig]:
    client = ProxmoxClient.__new__(ProxmoxClient)
    client._api = _FakeApi(config)
    client.default_storage = "local-lvm"
    fake_config = client._api.nodes("pve").qemu(101).config
    return client, fake_config


def test_list_vm_disks_filters_qemu_disk_devices() -> None:
    client, _ = _build_client(
        {
            "name": "vm-101",
            "scsi0": "local-lvm:vm-101-disk-0,size=20G",
            "scsi2": "local-lvm:vm-101-disk-2,size=50G",
            "ide2": "local:iso/debian.iso,media=cdrom",
            "net0": "virtio,bridge=vmbr0",
        }
    )

    disks = client.list_vm_disks("pve", 101)

    assert list(disks) == ["ide2", "scsi0", "scsi2"]
    assert disks["scsi2"]["slot"] == 2
    assert disks["scsi2"]["interface"] == "scsi"


def test_add_vm_disk_uses_next_free_slot_and_formats_config() -> None:
    client, fake_config = _build_client(
        {
            "scsi0": "local-lvm:vm-101-disk-0,size=20G",
            "scsi1": "local-lvm:vm-101-disk-1,size=40G",
        }
    )

    result = client.add_vm_disk(
        "pve",
        101,
        size_gb=100,
        interface="scsi",
        format="qcow2",
        ssd=True,
        cache="writeback",
    )

    assert result["device"] == "scsi2"
    assert fake_config.put_calls[-1] == {
        "scsi2": "local-lvm:100,format=qcow2,ssd=1,cache=writeback"
    }


def test_remove_vm_disk_uses_delete_semantics() -> None:
    client, fake_config = _build_client(
        {
            "scsi0": "local-lvm:vm-101-disk-0,size=20G",
            "scsi1": "local-lvm:vm-101-disk-1,size=10G",
        }
    )

    result = client.remove_vm_disk("pve", 101, device="scsi1")

    assert result["removed"] == "scsi1"
    assert result["previous_config"] == "local-lvm:vm-101-disk-1,size=10G"
    assert fake_config.put_calls[-1] == {"delete": "scsi1"}
