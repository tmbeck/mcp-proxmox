from __future__ import annotations

from typing import Any, Callable, Dict, List

from mcp.server.fastmcp import FastMCP


def register_cluster_tools(
    server: FastMCP,
    get_client: Callable[[str | None], Any],
    is_multi_cluster_mode: Callable[[], bool],
    get_cluster_registry: Callable[[], Any],
) -> None:
    @server.tool("proxmox-list-all-clusters")
    async def proxmox_list_all_clusters() -> List[str]:
        if not is_multi_cluster_mode():
            return []
        registry = get_cluster_registry()
        return registry.list_clusters()

    @server.tool("proxmox-list-all-nodes-from-all-clusters")
    async def proxmox_list_all_nodes_from_all_clusters() -> Dict[str, Any]:
        if not is_multi_cluster_mode():
            client = get_client(None)
            return {"default": client.list_nodes()}

        registry = get_cluster_registry()
        result: Dict[str, Any] = {}
        for cluster_name in registry.list_clusters():
            try:
                client = get_client(cluster_name)
                result[cluster_name] = client.list_nodes()
            except Exception as exc:
                result[cluster_name] = {"error": str(exc)}
        return result

    @server.tool("proxmox-list-all-vms-from-all-clusters")
    async def proxmox_list_all_vms_from_all_clusters() -> Dict[str, Any]:
        if not is_multi_cluster_mode():
            client = get_client(None)
            return {"default": client.list_vms()}

        registry = get_cluster_registry()
        result: Dict[str, Any] = {}
        for cluster_name in registry.list_clusters():
            try:
                client = get_client(cluster_name)
                result[cluster_name] = client.list_vms()
            except Exception as exc:
                result[cluster_name] = {"error": str(exc)}
        return result

    @server.tool("proxmox-get-all-cluster-status")
    async def proxmox_get_all_cluster_status() -> Dict[str, Any]:
        if not is_multi_cluster_mode():
            client = get_client(None)
            try:
                nodes = client.list_nodes()
                vms = client.list_vms()
                storage = client.list_storage()
                return {
                    "default": {
                        "status": "online",
                        "nodes": nodes,
                        "nodes_count": len(nodes),
                        "vms_count": len(vms),
                        "storage_count": len(storage),
                    }
                }
            except Exception as exc:
                return {"default": {"status": "error", "message": str(exc)}}

        registry = get_cluster_registry()
        result: Dict[str, Any] = {}
        for cluster_name in registry.list_clusters():
            try:
                client = get_client(cluster_name)
                nodes = client.list_nodes()
                vms = client.list_vms()
                storage = client.list_storage()
                running_vms = [vm for vm in vms if vm.get("status") == "running"]
                stopped_vms = [vm for vm in vms if vm.get("status") == "stopped"]
                result[cluster_name] = {
                    "status": "online",
                    "nodes": nodes,
                    "nodes_count": len(nodes),
                    "vms_total": len(vms),
                    "vms_running": len(running_vms),
                    "vms_stopped": len(stopped_vms),
                    "storage_count": len(storage),
                    "cluster_info": registry.get_cluster_info(cluster_name),
                }
            except Exception as exc:
                result[cluster_name] = {"status": "error", "message": str(exc)}
        return result
