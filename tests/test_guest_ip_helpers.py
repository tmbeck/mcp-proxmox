from __future__ import annotations

from typing import Any, cast

from proxmox_mcp.client import ProxmoxClient


class _FakeNetworkEndpoint:
    def __init__(self, result: Any) -> None:
        self.result = result

    def get(self) -> Any:
        return self.result


class _FakeAgent:
    def __init__(self, network_result: Any) -> None:
        self._network = _FakeNetworkEndpoint(network_result)

    def __call__(self, key: str) -> _FakeNetworkEndpoint:
        if key != "network-get-interfaces":
            raise AssertionError(f"unexpected key: {key}")
        return self._network


class _FakeQemuVm:
    def __init__(self, network_result: Any) -> None:
        self.agent = _FakeAgent(network_result)


class _FakeQemuCollection:
    def __init__(self, network_result: Any) -> None:
        self.vm = _FakeQemuVm(network_result)

    def __call__(self, vmid: int) -> _FakeQemuVm:
        return self.vm


class _FakeNode:
    def __init__(self, network_result: Any) -> None:
        self.qemu = _FakeQemuCollection(network_result)


class _FakeNodes:
    def __init__(self, network_result: Any) -> None:
        self.node = _FakeNode(network_result)

    def __call__(self, node: str) -> _FakeNode:
        return self.node


class _FakeApi:
    def __init__(self, network_result: Any) -> None:
        self.nodes = _FakeNodes(network_result)


def _build_client(network_result: Any) -> ProxmoxClient:
    client = ProxmoxClient.__new__(ProxmoxClient)
    client._api = cast(Any, _FakeApi(network_result))
    return client


def test_get_vm_ipv4_addresses_filters_loopback_and_link_local() -> None:
    client = _build_client(
        {
            "result": [
                {
                    "name": "lo",
                    "ip-addresses": [
                        {"ip-address-type": "ipv4", "ip-address": "127.0.0.1"}
                    ],
                },
                {
                    "name": "ens18",
                    "ip-addresses": [
                        {"ip-address-type": "ipv4", "ip-address": "169.254.1.10"},
                        {"ip-address-type": "ipv4", "ip-address": "192.168.0.55"},
                        {"ip-address-type": "ipv6", "ip-address": "fe80::1"},
                    ],
                },
            ]
        }
    )

    result = client.get_vm_ipv4_addresses("pve1", 9001)

    assert result == ["192.168.0.55"]


def test_get_vm_ipv4_addresses_accepts_list_shape() -> None:
    client = _build_client(
        [
            {
                "name": "ens18",
                "ip-addresses": [
                    {"ip-address-type": "ipv4", "ip-address": "10.0.0.22"}
                ],
            }
        ]
    )

    result = client.get_vm_ipv4_addresses("pve1", 9001)

    assert result == ["10.0.0.22"]
