from __future__ import annotations

from typing import Any, cast

import proxmox_mcp.client as client_module
import proxmox_mcp.server as server_module
from proxmox_mcp.client import ProxmoxClient, ProxmoxVersionCompatibility


class _FakeVersionEndpoint:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def get(self) -> dict[str, Any]:
        self.calls += 1
        return self.payload


class _FakeApi:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.version = _FakeVersionEndpoint(payload)


def _build_client(payload: dict[str, Any]) -> ProxmoxClient:
    client = ProxmoxClient.__new__(ProxmoxClient)
    client.base_url = "https://pve.example:8006"
    client.token_id = "root@pam!mcp"
    client._api = cast(Any, _FakeApi(payload))
    return client


def test_version_compatibility_accepts_patch_releases() -> None:
    client_module._VERSION_COMPATIBILITY_CACHE.clear()
    client = _build_client({"version": "9.1.9"})

    compatibility = client.get_version_compatibility()

    assert compatibility == ProxmoxVersionCompatibility(
        detected_version="9.1.9",
        compatible=True,
    )


def test_version_compatibility_warns_for_different_minor_series() -> None:
    client_module._VERSION_COMPATIBILITY_CACHE.clear()
    client = _build_client({"version": "9.2.0"})

    compatibility = client.get_version_compatibility()

    assert compatibility == ProxmoxVersionCompatibility(
        detected_version="9.2.0",
        compatible=False,
    )


def test_version_compatibility_caches_lookup_result() -> None:
    client_module._VERSION_COMPATIBILITY_CACHE.clear()
    client = _build_client({"version": "9.2.0"})

    first = client.get_version_compatibility()
    second = client.get_version_compatibility()

    assert first == second
    assert client._api.version.calls == 1


def test_version_mismatch_warning_is_emitted_once(capsys: Any) -> None:
    server_module._WARNED_PROXMOX_TARGETS.clear()

    class _FakeClient:
        base_url = "https://pve.example:8006"

        def get_version_compatibility(self) -> ProxmoxVersionCompatibility:
            return ProxmoxVersionCompatibility(
                detected_version="9.2.0",
                compatible=False,
            )

    client = cast(Any, _FakeClient())

    server_module._warn_if_proxmox_version_mismatch(client, "lab")
    server_module._warn_if_proxmox_version_mismatch(client, "lab")

    stderr_lines = [line for line in capsys.readouterr().err.splitlines() if line]
    assert len(stderr_lines) == 1
    assert "cluster 'lab'" in stderr_lines[0]
    assert "9.2.0" in stderr_lines[0]
    assert "9.1.6" in stderr_lines[0]
