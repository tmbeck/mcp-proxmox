from __future__ import annotations

from typing import Any, cast

from proxmox_mcp.client import ProxmoxClient


class _FakeDeleteCall:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "UPID:delete"


class _FakeSnapshot:
    def __init__(self, delete_call: _FakeDeleteCall) -> None:
        self.delete = delete_call


class _FakeSnapshotCollection:
    def __init__(self, delete_call: _FakeDeleteCall) -> None:
        self._snapshot = _FakeSnapshot(delete_call)

    def __call__(self, name: str) -> _FakeSnapshot:
        return self._snapshot


class _FakeQemuVm:
    def __init__(self) -> None:
        self.delete = _FakeDeleteCall()
        self.snapshot = _FakeSnapshotCollection(_FakeDeleteCall())


class _FakeLxcVm:
    def __init__(self) -> None:
        self.delete = _FakeDeleteCall()


class _FakeQemuCollection:
    def __init__(self) -> None:
        self.vm = _FakeQemuVm()

    def __call__(self, vmid: int) -> _FakeQemuVm:
        return self.vm


class _FakeLxcCollection:
    def __init__(self) -> None:
        self.vm = _FakeLxcVm()

    def __call__(self, vmid: int) -> _FakeLxcVm:
        return self.vm


class _FakeNode:
    def __init__(self) -> None:
        self.qemu = _FakeQemuCollection()
        self.lxc = _FakeLxcCollection()


class _FakeNodes:
    def __init__(self) -> None:
        self.node = _FakeNode()

    def __call__(self, node: str) -> _FakeNode:
        return self.node


class _FakeApi:
    def __init__(self) -> None:
        self.nodes = _FakeNodes()


def _build_client() -> ProxmoxClient:
    client = ProxmoxClient.__new__(ProxmoxClient)
    client._api = cast(Any, _FakeApi())
    return client


def test_delete_vm_uses_delete_call() -> None:
    client = _build_client()

    result = client.delete_vm("pve1", 123, purge=True)

    delete_call = client._api.nodes("pve1").qemu(123).delete
    assert result == "UPID:delete"
    assert delete_call.calls == [{"purge": 1}]


def test_delete_snapshot_uses_delete_call() -> None:
    client = _build_client()

    result = client.delete_snapshot("pve1", 123, "snap1")

    delete_call = client._api.nodes("pve1").qemu(123).snapshot("snap1").delete
    assert result == "UPID:delete"
    assert delete_call.calls == [{}]


def test_delete_lxc_uses_delete_call() -> None:
    client = _build_client()

    result = client.delete_lxc("pve1", 456, purge=True)

    delete_call = client._api.nodes("pve1").lxc(456).delete
    assert result == "UPID:delete"
    assert delete_call.calls == [{"purge": 1}]
