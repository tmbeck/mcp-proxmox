from __future__ import annotations

from typing import Any, cast

from proxmox_mcp.client import ProxmoxClient


class _FakeConfigEndpoint:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    def get(self) -> dict[str, Any]:
        return dict(self._config)


class _FakeInfoEndpoint:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.get_calls = 0

    def get(self) -> dict[str, Any]:
        self.get_calls += 1
        return self.result


class _FakeNetworkEndpoint:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    def get(self) -> dict[str, Any]:
        return self.result


class _FakeAgent:
    def __init__(
        self, info_result: dict[str, Any], network_result: dict[str, Any]
    ) -> None:
        self._info = _FakeInfoEndpoint(info_result)
        self._network = _FakeNetworkEndpoint(network_result)

    def __call__(self, endpoint: str) -> Any:
        if endpoint == "info":
            return self._info
        if endpoint == "network-get-interfaces":
            return self._network
        raise AssertionError(f"unexpected agent endpoint: {endpoint}")


class _FakeQemuVm:
    def __init__(
        self,
        config: dict[str, Any],
        info_result: dict[str, Any],
        network_result: dict[str, Any],
    ) -> None:
        self.config = _FakeConfigEndpoint(config)
        self.agent = _FakeAgent(info_result, network_result)


class _FakeQemuCollection:
    def __init__(
        self,
        config: dict[str, Any],
        info_result: dict[str, Any],
        network_result: dict[str, Any],
    ) -> None:
        self.vm = _FakeQemuVm(config, info_result, network_result)

    def __call__(self, vmid: int) -> _FakeQemuVm:
        return self.vm


class _FakeNode:
    def __init__(
        self,
        config: dict[str, Any],
        info_result: dict[str, Any],
        network_result: dict[str, Any],
    ) -> None:
        self.qemu = _FakeQemuCollection(config, info_result, network_result)


class _FakeNodes:
    def __init__(
        self,
        config: dict[str, Any],
        info_result: dict[str, Any],
        network_result: dict[str, Any],
    ) -> None:
        self.node = _FakeNode(config, info_result, network_result)

    def __call__(self, node: str) -> _FakeNode:
        return self.node


class _FakeApi:
    def __init__(
        self,
        config: dict[str, Any],
        info_result: dict[str, Any],
        network_result: dict[str, Any],
    ) -> None:
        self.nodes = _FakeNodes(config, info_result, network_result)


def _build_client(
    config: dict[str, Any],
    info_result: dict[str, Any],
    network_result: dict[str, Any],
) -> tuple[ProxmoxClient, _FakeInfoEndpoint]:
    client = ProxmoxClient.__new__(ProxmoxClient)
    client._api = cast(Any, _FakeApi(config, info_result, network_result))
    client.scheme = "https"
    client.host = "pve.example"
    client.port = 8006
    info_endpoint = cast(
        _FakeInfoEndpoint, client._api.nodes("pve").qemu(101).agent("info")
    )
    return client, info_endpoint


def test_get_vm_console_url_uses_parsed_host_and_port() -> None:
    client, _ = _build_client({}, {}, {"result": []})

    result = client.get_vm_console_url("pve1", 101)

    assert result == "https://pve.example:8006/#v1:0:18:pve1:0:101::"


def test_get_vm_console_url_uses_serial_console_when_present() -> None:
    client, _ = _build_client({"serial0": "socket"}, {}, {"result": []})

    result = client.get_vm_console_url("pve1", 101)

    assert result == "https://pve.example:8006/#v1:0:18:pve1:4:101::"


def test_get_windows_vm_info_uses_qga_info_endpoint() -> None:
    info_result = {"version": "8.1.0"}
    network_result = {"result": [{"name": "Ethernet0", "ip-addresses": []}]}
    client, info_endpoint = _build_client(
        {"name": "win-vm", "ostype": "win11", "agent": 1},
        info_result,
        network_result,
    )

    result = client.get_windows_vm_info("pve1", 101)

    assert info_endpoint.get_calls == 1
    assert result["guest_info"] == info_result
    assert result["console_url"] == "https://pve.example:8006/#v1:0:18:pve1:0:101::"
