from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from proxmox_mcp.registrars.clusters import register_cluster_tools
from proxmox_mcp.server import server


class _FakeClient:
    def __init__(self, compatibility: dict[str, Any]) -> None:
        self.compatibility = compatibility

    def list_nodes(self) -> list[dict[str, Any]]:
        return [{"node": "pve1"}]

    def list_vms(self) -> list[dict[str, Any]]:
        return [
            {"vmid": 100, "status": "running"},
            {"vmid": 101, "status": "stopped"},
        ]

    def list_storage(self) -> list[dict[str, Any]]:
        return [{"storage": "local-lvm"}]

    def get_version_compatibility_payload(self) -> dict[str, Any]:
        return dict(self.compatibility)


class _FakeRegistry:
    def __init__(self) -> None:
        self.clients = {
            "lab-a": _FakeClient(
                {
                    "detected_version": "9.1.9",
                    "tested_version": "9.1.6",
                    "tested_series": "9.1.x",
                    "compatible": True,
                }
            ),
            "lab-b": _FakeClient(
                {
                    "detected_version": "9.2.0",
                    "tested_version": "9.1.6",
                    "tested_series": "9.1.x",
                    "compatible": False,
                }
            ),
        }

    def list_clusters(self) -> list[str]:
        return list(self.clients)

    def get_client(self, cluster_name: str) -> _FakeClient:
        return self.clients[cluster_name]

    def get_cluster_info(self, cluster_name: str) -> dict[str, Any]:
        return {
            "name": cluster_name,
            "base_url": f"https://{cluster_name}.example:8006",
        }


def test_cluster_status_includes_version_compatibility() -> None:
    fake_client = _FakeClient(
        {
            "detected_version": "9.1.9",
            "tested_version": "9.1.6",
            "tested_series": "9.1.x",
            "compatible": True,
        }
    )
    app = FastMCP("test")
    register_cluster_tools(
        app,
        lambda cluster_name: fake_client,
        lambda: False,
        lambda: None,
    )

    tool = app._tool_manager.get_tool("proxmox-get-all-cluster-status")
    assert tool is not None

    result = asyncio.run(tool.fn())

    assert result["default"]["status"] == "online"
    assert result["default"]["vms_count"] == 2
    assert result["default"]["version_compatibility"] == {
        "detected_version": "9.1.9",
        "tested_version": "9.1.6",
        "tested_series": "9.1.x",
        "compatible": True,
    }


def test_cluster_version_tool_supports_multi_cluster_results() -> None:
    registry = _FakeRegistry()
    app = FastMCP("test")
    register_cluster_tools(
        app,
        lambda cluster_name: registry.get_client(cluster_name or "lab-a"),
        lambda: True,
        lambda: registry,
    )

    tool = app._tool_manager.get_tool("proxmox-get-cluster-version-compatibility")
    assert tool is not None

    result = asyncio.run(tool.fn())

    assert result["lab-a"]["compatible"] is True
    assert result["lab-b"]["compatible"] is False
    assert result["lab-b"]["cluster_info"]["name"] == "lab-b"


def test_tool_metadata_marks_destructive_and_conditional_actions() -> None:
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    assert (
        tools["proxmox-get-cluster-version-compatibility"].annotations.readOnlyHint
        is True
    )
    assert tools["proxmox-delete-vm"].annotations.destructiveHint is True
    assert tools["proxmox-rollback-snapshot"].annotations.destructiveHint is True
    assert tools["proxmox-vm-disk-remove"].meta["proxmox"]["destructive_when"] == {
        "parameter": "mode",
        "values": ["delete-volume"],
    }
    assert tools["proxmox-restore-vm"].meta["proxmox"]["destructive_when"] == {
        "parameter": "force",
        "values": [True],
    }
