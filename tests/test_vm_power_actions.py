from __future__ import annotations

from typing import Any, cast

from proxmox_mcp.client import ProxmoxClient


class _FakePostCall:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "UPID:task"


class _FakeStopEndpoint:
    def __init__(self) -> None:
        self.post = _FakePostCall()


class _FakeStatusEndpoint:
    def __init__(self) -> None:
        self.stop = _FakeStopEndpoint()


class _FakeQemuVm:
    def __init__(self) -> None:
        self.status = _FakeStatusEndpoint()


class _FakeQemuCollection:
    def __init__(self) -> None:
        self.vm = _FakeQemuVm()

    def __call__(self, vmid: int) -> _FakeQemuVm:
        return self.vm


class _FakeNode:
    def __init__(self) -> None:
        self.qemu = _FakeQemuCollection()


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


def test_stop_vm_without_hard_uses_plain_stop() -> None:
    client = _build_client()

    result = client.stop_vm("pve1", 123)

    stop_call = client._api.nodes("pve1").qemu(123).status.stop.post
    assert result == "UPID:task"
    assert stop_call.calls == [{}]


def test_stop_vm_with_hard_overrules_existing_shutdown() -> None:
    client = _build_client()

    result = client.stop_vm("pve1", 123, force=True, timeout=45)

    stop_call = client._api.nodes("pve1").qemu(123).status.stop.post
    assert result == "UPID:task"
    assert stop_call.calls == [{"overrule-shutdown": 1, "timeout": 45}]
