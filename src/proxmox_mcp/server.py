from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

from .client import ProxmoxClient
from .utils import read_env, require_confirm, format_size, is_multi_cluster_mode
from .cluster_manager import get_cluster_registry
from .registrars.ai import register_ai_tools
from .registrars.automation import register_automation_tools
from .registrars.control_plane import register_control_plane_tools
from .registrars.notes import register_notes_tools
from .registrars.observability import register_observability_tools
from .registrars.provisioning import register_provisioning_tools
from .registrars.security import register_security_tools
from .tool_profiles import (
    PROFILE_DESCRIPTIONS,
    apply_profiles_to_server,
    resolve_profiles,
)


server = FastMCP("proxmox-mcp")


# Load .env early
load_dotenv()


# ---------- Helpers ----------


def get_client(cluster_name: Optional[str] = None) -> ProxmoxClient:
    """
    Get Proxmox client. Supports both single-cluster and multi-cluster mode.

    In multi-cluster mode (when PROXMOX_CLUSTERS environment variable is set),
    this will return a client for the specified cluster or the default cluster.

    In single-cluster mode, cluster_name is ignored and the default client is returned.

    Args:
        cluster_name: Optional cluster name. Only used in multi-cluster mode.

    Returns:
        ProxmoxClient instance configured for the specified (or default) cluster.
    """
    if is_multi_cluster_mode():
        # Multi-cluster mode: use cluster registry
        registry = get_cluster_registry()
        return registry.get_client(cluster_name)
    else:
        # Single-cluster mode: use environment variables
        read_env()
        return ProxmoxClient.from_env()


def get_openshift_installer(client: ProxmoxClient):
    from .rhcos import OpenShiftInstaller

    return OpenShiftInstaller(client)


def get_docker_swarm_symbols():
    from .docker_swarm import (
        DockerSwarmConfig,
        DockerSwarmProvisioner,
        get_web_cluster_config,
        get_development_cluster_config,
        get_production_cluster_config,
    )

    return {
        "DockerSwarmConfig": DockerSwarmConfig,
        "DockerSwarmProvisioner": DockerSwarmProvisioner,
        "get_web_cluster_config": get_web_cluster_config,
        "get_development_cluster_config": get_development_cluster_config,
        "get_production_cluster_config": get_production_cluster_config,
    }


def get_security_manager(client: ProxmoxClient):
    from .security import SecurityManager

    return SecurityManager(client)


def get_infrastructure_manager(client: ProxmoxClient):
    from .infrastructure import InfrastructureManager

    return InfrastructureManager(client)


def get_network_manager(client: ProxmoxClient):
    from .network import NetworkManager

    return NetworkManager(client)


def get_monitoring_manager(client: ProxmoxClient):
    from .monitoring import MonitoringManager

    return MonitoringManager(client)


def get_storage_manager(client: ProxmoxClient):
    from .storage_advanced import AdvancedStorageManager

    return AdvancedStorageManager(client)


def get_ai_manager(client: ProxmoxClient):
    from .ai_optimization import AIOptimizationManager

    return AIOptimizationManager(client)


def get_integration_manager(client: ProxmoxClient):
    from .integrations import IntegrationManager

    return IntegrationManager(client)


# ---------- Multi-Cluster Helper Tools ----------


@server.tool("proxmox-list-all-clusters")
async def proxmox_list_all_clusters() -> List[str]:
    """
    List all configured Proxmox clusters.

    Returns empty list in single-cluster mode.
    """
    if not is_multi_cluster_mode():
        return []

    registry = get_cluster_registry()
    return registry.list_clusters()


@server.tool("proxmox-list-all-nodes-from-all-clusters")
async def proxmox_list_all_nodes_from_all_clusters() -> Dict[str, Any]:
    """
    List ALL nodes from ALL configured clusters.

    This is a convenience tool that aggregates nodes from all clusters.
    In single-cluster mode, returns nodes from the single cluster.

    Returns:
        Dict with cluster names as keys and node lists as values
    """
    if not is_multi_cluster_mode():
        # Single cluster mode
        client = get_client()
        nodes = client.list_nodes()
        return {"default": nodes}

    # Multi-cluster mode
    registry = get_cluster_registry()
    result = {}

    for cluster_name in registry.list_clusters():
        try:
            client = get_client(cluster_name)
            nodes = client.list_nodes()
            result[cluster_name] = nodes
        except Exception as e:
            result[cluster_name] = {"error": str(e)}

    return result


@server.tool("proxmox-list-all-vms-from-all-clusters")
async def proxmox_list_all_vms_from_all_clusters() -> Dict[str, Any]:
    """
    List ALL VMs from ALL configured clusters.

    This is a convenience tool that aggregates VMs from all clusters.
    In single-cluster mode, returns VMs from the single cluster.

    Returns:
        Dict with cluster names as keys and VM lists as values
    """
    if not is_multi_cluster_mode():
        # Single cluster mode
        client = get_client()
        vms = client.list_vms()
        return {"default": vms}

    # Multi-cluster mode
    registry = get_cluster_registry()
    result = {}

    for cluster_name in registry.list_clusters():
        try:
            client = get_client(cluster_name)
            vms = client.list_vms()
            result[cluster_name] = vms
        except Exception as e:
            result[cluster_name] = {"error": str(e)}

    return result


@server.tool("proxmox-get-all-cluster-status")
async def proxmox_get_all_cluster_status() -> Dict[str, Any]:
    """
    Get comprehensive status of ALL configured clusters.

    Returns detailed information including:
    - Cluster connectivity
    - Node status
    - Resource counts (VMs, containers, storage)
    - Health metrics

    Returns:
        Dict with cluster names as keys and status info as values
    """
    if not is_multi_cluster_mode():
        # Single cluster mode
        client = get_client()
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
        except Exception as e:
            return {"default": {"status": "error", "message": str(e)}}

    # Multi-cluster mode
    registry = get_cluster_registry()
    result = {}

    for cluster_name in registry.list_clusters():
        try:
            client = get_client(cluster_name)

            # Get basic info
            nodes = client.list_nodes()
            vms = client.list_vms()
            storage = client.list_storage()

            # Count running/stopped VMs
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
        except Exception as e:
            result[cluster_name] = {"status": "error", "message": str(e)}

    return result


# ---------- Core discovery ----------


@server.tool("proxmox-list-nodes")
async def proxmox_list_nodes() -> List[Dict[str, Any]]:
    client = get_client()
    return client.list_nodes()


@server.tool("proxmox-node-status")
async def proxmox_node_status(node: Optional[str] = None) -> Dict[str, Any]:
    client = get_client()
    node_id = node or client.default_node
    if not node_id:
        raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
    return client.get_node_status(node_id)


@server.tool("proxmox-list-vms")
async def proxmox_list_vms(
    node: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    client = get_client()
    return client.list_vms(node=node, status=status, search=search)


@server.tool("proxmox-vm-info")
async def proxmox_vm_info(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, res = client.resolve_vm(vmid=vmid, name=name, node=node)
    config = client.vm_config(vm_node, vm_vmid)
    return {"selector": res, "config": config}


@server.tool("proxmox-list-lxc")
async def proxmox_list_lxc(
    node: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    client = get_client()
    return client.list_lxc(node=node, status=status, search=search)


@server.tool("proxmox-lxc-info")
async def proxmox_lxc_info(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
) -> Dict[str, Any]:
    client = get_client()
    ct_vmid, ct_node, res = client.resolve_lxc(vmid=vmid, name=name, node=node)
    config = client.lxc_config(ct_node, ct_vmid)
    return {"selector": res, "config": config}


@server.tool("proxmox-list-storage")
async def proxmox_list_storage() -> List[Dict[str, Any]]:
    client = get_client()
    return client.list_storage()


@server.tool("proxmox-storage-content")
async def proxmox_storage_content(
    node: Optional[str] = None, storage: Optional[str] = None
) -> List[Dict[str, Any]]:
    client = get_client()
    node_id = node or client.default_node
    storage_id = storage or client.default_storage
    if not node_id:
        raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
    if not storage_id:
        raise ValueError("storage is required (or set PROXMOX_DEFAULT_STORAGE)")
    return client.storage_content(node_id, storage_id)


@server.tool("proxmox-list-bridges")
async def proxmox_list_bridges(node: Optional[str] = None) -> List[Dict[str, Any]]:
    client = get_client()
    node_id = node or client.default_node
    if not node_id:
        raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
    return client.list_bridges(node_id)


@server.tool("proxmox-list-tasks")
async def proxmox_list_tasks(
    node: Optional[str] = None, user: Optional[str] = None, limit: int = 50
) -> List[Dict[str, Any]]:
    client = get_client()
    return client.list_tasks(node=node, user=user, limit=limit)


@server.tool("proxmox-task-status")
async def proxmox_task_status(upid: str, node: Optional[str] = None) -> Dict[str, Any]:
    client = get_client()
    return client.task_status(upid, node=node)


# ---------- VM lifecycle ----------


@server.tool("proxmox-clone-vm")
async def proxmox_clone_vm(
    source_vmid: int,
    new_vmid: int,
    source_node: Optional[str] = None,
    target_node: Optional[str] = None,
    name: Optional[str] = None,
    storage: Optional[str] = None,
    full: bool = True,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = False,
    timeout: int = 900,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    node = source_node or client.default_node
    if not node:
        raise ValueError("source_node is required (or set PROXMOX_DEFAULT_NODE)")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "clone",
            "params": {
                "source_node": node,
                "source_vmid": source_vmid,
                "new_vmid": new_vmid,
                "target_node": target_node,
                "name": name,
                "storage": storage,
                "full": full,
            },
        }
    upid = client.clone_vm(
        source_node=node,
        source_vmid=source_vmid,
        target_node=target_node,
        new_vmid=new_vmid,
        name=name,
        full=full,
        storage=storage or client.default_storage,
    )
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=node, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-create-vm")
async def proxmox_create_vm(
    node: Optional[str] = None,
    vmid: int = 0,
    name: str = "",
    cores: int = 2,
    memory_mb: int = 2048,
    disk_gb: int = 20,
    storage: Optional[str] = None,
    bridge: Optional[str] = None,
    iso: Optional[str] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = False,
    timeout: int = 900,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    node_id = node or client.default_node
    if not node_id:
        raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
    if vmid <= 0 or not name:
        raise ValueError("vmid > 0 and non-empty name are required")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "create-vm",
            "params": {
                "node": node_id,
                "vmid": vmid,
                "name": name,
                "cores": cores,
                "memory_mb": memory_mb,
                "disk_gb": disk_gb,
                "storage": storage or client.default_storage,
                "bridge": bridge or client.default_bridge,
                "iso": iso,
            },
        }
    upid = client.create_vm(
        node=node_id,
        vmid=vmid,
        name=name,
        cores=cores,
        memory_mb=memory_mb,
        disk_gb=disk_gb,
        storage=storage or client.default_storage,
        bridge=bridge or client.default_bridge,
        iso=iso,
    )
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=node_id, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-delete-vm")
async def proxmox_delete_vm(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    purge: bool = True,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = False,
    timeout: int = 600,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "delete-vm",
            "params": {"node": vm_node, "vmid": vm_vmid, "purge": purge},
        }
    upid = client.delete_vm(vm_node, vm_vmid, purge=purge)
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=vm_node, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-start-vm")
async def proxmox_start_vm(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    wait: bool = False,
    timeout: int = 300,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    upid = client.start_vm(vm_node, vm_vmid)
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=vm_node, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-stop-vm")
async def proxmox_stop_vm(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    hard: bool = False,
    timeout: Optional[int] = None,
    wait: bool = False,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    upid = client.stop_vm(vm_node, vm_vmid, force=hard, timeout=timeout)
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=vm_node, timeout=timeout or 600, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-reboot-vm")
async def proxmox_reboot_vm(
    vmid: Optional[int] = None, name: Optional[str] = None, node: Optional[str] = None
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    upid = client.reboot_vm(vm_node, vm_vmid)
    return {"upid": upid}


@server.tool("proxmox-shutdown-vm")
async def proxmox_shutdown_vm(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    timeout: Optional[int] = None,
    wait: bool = False,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    upid = client.shutdown_vm(vm_node, vm_vmid, timeout=timeout)
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=vm_node, timeout=timeout or 600, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-migrate-vm")
async def proxmox_migrate_vm(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    target_node: str = "",
    live: bool = True,
    wait: bool = True,
    timeout: int = 1800,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    if not target_node:
        raise ValueError("target_node is required")
    upid = client.migrate_vm(vm_node, vm_vmid, target_node=target_node, online=live)
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=vm_node, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-resize-vm-disk")
async def proxmox_resize_vm_disk(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    disk: str = "scsi0",
    grow_gb: int = 0,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = True,
    timeout: int = 900,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    require_confirm(confirm)
    if grow_gb <= 0:
        raise ValueError("grow_gb must be > 0")
    if dry_run:
        return {
            "dry_run": True,
            "action": "resize",
            "params": {"node": vm_node, "vmid": vm_vmid, "disk": disk, "grow": grow_gb},
        }
    upid = client.resize_vm_disk(vm_node, vm_vmid, disk=disk, size_gb=grow_gb)
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=vm_node, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-configure-vm")
async def proxmox_configure_vm(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = False,
    timeout: int = 600,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    if not params:
        raise ValueError("params is required and must contain whitelisted config keys")
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "configure",
            "params": {"node": vm_node, "vmid": vm_vmid, "config": params},
        }
    result = client.configure_vm(vm_node, vm_vmid, params)
    if wait and "upid" in result:
        status = client.wait_task(
            result["upid"], node=vm_node, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


# ---------- LXC lifecycle ----------


@server.tool("proxmox-create-lxc")
async def proxmox_create_lxc(
    node: Optional[str] = None,
    vmid: int = 0,
    hostname: str = "",
    ostemplate: str = "",
    cores: int = 2,
    memory_mb: int = 1024,
    rootfs_gb: int = 8,
    storage: Optional[str] = None,
    bridge: Optional[str] = None,
    net_ip: Optional[str] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = True,
    timeout: int = 900,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    node_id = node or client.default_node
    if not node_id:
        raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
    if vmid <= 0 or not hostname or not ostemplate:
        raise ValueError("vmid, hostname, ostemplate are required")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "create-lxc",
            "params": {
                "node": node_id,
                "vmid": vmid,
                "hostname": hostname,
                "ostemplate": ostemplate,
                "cores": cores,
                "memory_mb": memory_mb,
                "rootfs_gb": rootfs_gb,
                "storage": storage or client.default_storage,
                "bridge": bridge or client.default_bridge,
                "net_ip": net_ip or "dhcp",
            },
        }
    upid = client.create_lxc(
        node=node_id,
        vmid=vmid,
        hostname=hostname,
        ostemplate=ostemplate,
        cores=cores,
        memory_mb=memory_mb,
        rootfs_gb=rootfs_gb,
        storage=storage or client.default_storage,
        bridge=bridge or client.default_bridge,
        net_ip=net_ip,
    )
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=node_id, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-delete-lxc")
async def proxmox_delete_lxc(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    purge: bool = True,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = False,
    timeout: int = 600,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    ct_vmid, ct_node, _ = client.resolve_lxc(vmid=vmid, name=name, node=node)
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "delete-lxc",
            "params": {"node": ct_node, "vmid": ct_vmid, "purge": purge},
        }
    upid = client.delete_lxc(ct_node, ct_vmid, purge=purge)
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=ct_node, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-start-lxc")
async def proxmox_start_lxc(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    wait: bool = False,
    timeout: int = 300,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    ct_vmid, ct_node, _ = client.resolve_lxc(vmid=vmid, name=name, node=node)
    upid = client.start_lxc(ct_node, ct_vmid)
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=ct_node, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-stop-lxc")
async def proxmox_stop_lxc(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    timeout: Optional[int] = None,
    wait: bool = False,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    ct_vmid, ct_node, _ = client.resolve_lxc(vmid=vmid, name=name, node=node)
    upid = client.stop_lxc(ct_node, ct_vmid, timeout=timeout)
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=ct_node, timeout=timeout or 600, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-configure-lxc")
async def proxmox_configure_lxc(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = False,
    timeout: int = 600,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    if not params:
        raise ValueError("params is required and must contain allowed LXC config keys")
    ct_vmid, ct_node, _ = client.resolve_lxc(vmid=vmid, name=name, node=node)
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "configure-lxc",
            "params": {"node": ct_node, "vmid": ct_vmid, "config": params},
        }
    result = client.configure_lxc(ct_node, ct_vmid, params)
    if wait and "upid" in result:
        status = client.wait_task(
            result["upid"], node=ct_node, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


# ---------- Cloud-init & networking ----------


@server.tool("proxmox-cloudinit-set")
async def proxmox_cloudinit_set(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    ipconfig0: Optional[str] = None,
    sshkeys: Optional[str] = None,
    ciuser: Optional[str] = None,
    cipassword: Optional[str] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    params: Dict[str, Any] = {}
    if ipconfig0 is not None:
        params["ipconfig0"] = ipconfig0
    if sshkeys is not None:
        params["sshkeys"] = sshkeys
    if ciuser is not None:
        params["ciuser"] = ciuser
    if cipassword is not None:
        params["cipassword"] = cipassword
    if not params:
        raise ValueError(
            "Provide at least one of: ipconfig0, sshkeys, ciuser, cipassword"
        )
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "cloudinit-set",
            "params": {"node": vm_node, "vmid": vm_vmid, **params},
        }
    return client.cloudinit_set(vm_node, vm_vmid, params)


@server.tool("proxmox-vm-nic-add")
async def proxmox_vm_nic_add(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    bridge: Optional[str] = None,
    model: str = "virtio",
    vlan: Optional[int] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    bridge_id = bridge or client.default_bridge
    if not bridge_id:
        raise ValueError("bridge is required (or set PROXMOX_DEFAULT_BRIDGE)")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "vm-nic-add",
            "params": {
                "node": vm_node,
                "vmid": vm_vmid,
                "bridge": bridge_id,
                "model": model,
                "vlan": vlan,
            },
        }
    return client.vm_nic_add(vm_node, vm_vmid, bridge=bridge_id, model=model, vlan=vlan)


@server.tool("proxmox-vm-nic-remove")
async def proxmox_vm_nic_remove(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    slot: int = 0,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "vm-nic-remove",
            "params": {"node": vm_node, "vmid": vm_vmid, "slot": slot},
        }
    return client.vm_nic_remove(vm_node, vm_vmid, slot=slot)


@server.tool("proxmox-vm-firewall-get")
async def proxmox_vm_firewall_get(
    vmid: Optional[int] = None, name: Optional[str] = None, node: Optional[str] = None
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    return client.vm_firewall_get(vm_node, vm_vmid)


@server.tool("proxmox-vm-firewall-set")
async def proxmox_vm_firewall_set(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    enable: Optional[bool] = None,
    rules: Optional[List[Dict[str, Any]]] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    if enable is None and not rules:
        raise ValueError("Provide enable and/or rules")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "vm-firewall-set",
            "params": {
                "node": vm_node,
                "vmid": vm_vmid,
                "enable": enable,
                "rules": rules or [],
            },
        }
    return client.vm_firewall_set(vm_node, vm_vmid, enable=enable, rules=rules)


# ---------- Images, templates, snapshots, backups ----------


@server.tool("proxmox-upload-iso")
async def proxmox_upload_iso(
    node: Optional[str] = None,
    storage: Optional[str] = None,
    file_path: str = "",
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    node_id = node or client.default_node
    storage_id = storage or client.default_storage
    if not node_id or not storage_id:
        raise ValueError("node and storage are required (or set defaults)")
    if not os.path.isfile(file_path):
        raise ValueError(f"file not found: {file_path}")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "upload-iso",
            "params": {"node": node_id, "storage": storage_id, "file_path": file_path},
        }
    upid = client.upload_iso(node_id, storage_id, file_path)
    return {"upid": upid}


@server.tool("proxmox-upload-template")
async def proxmox_upload_template(
    node: Optional[str] = None,
    storage: Optional[str] = None,
    file_path: str = "",
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    node_id = node or client.default_node
    storage_id = storage or client.default_storage
    if not node_id or not storage_id:
        raise ValueError("node and storage are required (or set defaults)")
    if not os.path.isfile(file_path):
        raise ValueError(f"file not found: {file_path}")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "upload-template",
            "params": {"node": node_id, "storage": storage_id, "file_path": file_path},
        }
    upid = client.upload_template(node_id, storage_id, file_path)
    return {"upid": upid}


@server.tool("proxmox-template-vm")
async def proxmox_template_vm(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "template-vm",
            "params": {"node": vm_node, "vmid": vm_vmid},
        }
    upid = client.template_vm(vm_node, vm_vmid)
    return {"upid": upid}


@server.tool("proxmox-list-snapshots")
async def proxmox_list_snapshots(
    vmid: Optional[int] = None, name: Optional[str] = None, node: Optional[str] = None
) -> List[Dict[str, Any]]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    return client.list_snapshots(vm_node, vm_vmid)


@server.tool("proxmox-create-snapshot")
async def proxmox_create_snapshot(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    snapname: str = "",
    description: Optional[str] = None,
    vmstate: bool = False,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    if not snapname:
        raise ValueError("snapname is required")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "create-snapshot",
            "params": {
                "node": vm_node,
                "vmid": vm_vmid,
                "snapname": snapname,
                "description": description,
                "vmstate": vmstate,
            },
        }
    upid = client.create_snapshot(
        vm_node, vm_vmid, name=snapname, description=description, vmstate=vmstate
    )
    return {"upid": upid}


@server.tool("proxmox-delete-snapshot")
async def proxmox_delete_snapshot(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    snapname: str = "",
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    if not snapname:
        raise ValueError("snapname is required")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "delete-snapshot",
            "params": {"node": vm_node, "vmid": vm_vmid, "snapname": snapname},
        }
    upid = client.delete_snapshot(vm_node, vm_vmid, name=snapname)
    return {"upid": upid}


@server.tool("proxmox-rollback-snapshot")
async def proxmox_rollback_snapshot(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    snapname: str = "",
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = True,
    timeout: int = 900,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    if not snapname:
        raise ValueError("snapname is required")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "rollback-snapshot",
            "params": {"node": vm_node, "vmid": vm_vmid, "snapname": snapname},
        }
    upid = client.rollback_snapshot(vm_node, vm_vmid, name=snapname)
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=vm_node, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-backup-vm")
async def proxmox_backup_vm(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    mode: str = "snapshot",
    compress: str = "zstd",
    storage: Optional[str] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = True,
    timeout: int = 3600,
    poll_interval: float = 5.0,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "backup-vm",
            "params": {
                "node": vm_node,
                "vmid": vm_vmid,
                "mode": mode,
                "compress": compress,
                "storage": storage,
            },
        }
    upid = client.backup_vm(
        vm_node,
        vm_vmid,
        mode=mode,
        compress=compress,
        storage=storage or client.default_storage,
    )
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=vm_node, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


@server.tool("proxmox-restore-vm")
async def proxmox_restore_vm(
    node: Optional[str] = None,
    vmid: int = 0,
    archive: str = "",
    storage: Optional[str] = None,
    force: bool = False,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = True,
    timeout: int = 3600,
    poll_interval: float = 5.0,
) -> Dict[str, Any]:
    client = get_client()
    node_id = node or client.default_node
    if not node_id:
        raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
    if vmid <= 0 or not archive:
        raise ValueError("vmid and archive are required")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "restore-vm",
            "params": {
                "node": node_id,
                "vmid": vmid,
                "archive": archive,
                "storage": storage,
                "force": force,
            },
        }
    upid = client.restore_vm(
        node_id,
        vmid,
        archive=archive,
        storage=storage or client.default_storage,
        force=force,
    )
    result: Dict[str, Any] = {"upid": upid}
    if wait:
        status = client.wait_task(
            upid, node=node_id, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status
    return result


# ---------- Metrics ----------


@server.tool("proxmox-vm-metrics")
async def proxmox_vm_metrics(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    timeframe: str = "hour",
    cf: str = "AVERAGE",
) -> List[Dict[str, Any]]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    return client.vm_metrics(vm_node, vm_vmid, timeframe=timeframe, cf=cf)


@server.tool("proxmox-node-metrics")
async def proxmox_node_metrics(
    node: Optional[str] = None, timeframe: str = "hour", cf: str = "AVERAGE"
) -> List[Dict[str, Any]]:
    client = get_client()
    node_id = node or client.default_node
    if not node_id:
        raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
    return client.node_metrics(node_id, timeframe=timeframe, cf=cf)


# ---------- Pools / permissions ----------


@server.tool("proxmox-list-pools")
async def proxmox_list_pools() -> List[Dict[str, Any]]:
    client = get_client()
    return client.list_pools()


@server.tool("proxmox-create-pool")
async def proxmox_create_pool(
    poolid: str,
    comment: Optional[str] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    if not poolid:
        raise ValueError("poolid is required")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "create-pool",
            "params": {"poolid": poolid, "comment": comment},
        }
    res = client.create_pool(poolid, comment=comment)
    return {"result": res}


@server.tool("proxmox-delete-pool")
async def proxmox_delete_pool(
    poolid: str, confirm: Optional[bool] = None, dry_run: bool = False
) -> Dict[str, Any]:
    client = get_client()
    if not poolid:
        raise ValueError("poolid is required")
    require_confirm(confirm)
    if dry_run:
        return {"dry_run": True, "action": "delete-pool", "params": {"poolid": poolid}}
    res = client.delete_pool(poolid)
    return {"result": res}


@server.tool("proxmox-pool-add")
async def proxmox_pool_add(
    poolid: str,
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    type_: str = "qemu",
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    if type_ not in ("qemu", "lxc"):
        raise ValueError("type_ must be 'qemu' or 'lxc'")
    if type_ == "qemu":
        rid, rnode, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    else:
        rid, rnode, _ = client.resolve_lxc(vmid=vmid, name=name, node=node)
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "pool-add",
            "params": {"poolid": poolid, "vmid": rid, "node": rnode, "type_": type_},
        }
    res = client.pool_add(poolid, vmid=rid, node=rnode, type_=type_)
    return {"result": res}


@server.tool("proxmox-pool-remove")
async def proxmox_pool_remove(
    poolid: str,
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    type_: str = "qemu",
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    if type_ not in ("qemu", "lxc"):
        raise ValueError("type_ must be 'qemu' or 'lxc'")
    if type_ == "qemu":
        rid, rnode, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    else:
        rid, rnode, _ = client.resolve_lxc(vmid=vmid, name=name, node=node)
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "pool-remove",
            "params": {"poolid": poolid, "vmid": rid, "node": rnode, "type_": type_},
        }
    res = client.pool_remove(poolid, vmid=rid, node=rnode, type_=type_)
    return {"result": res}


@server.tool("proxmox-list-users")
async def proxmox_list_users() -> List[Dict[str, Any]]:
    client = get_client()
    return client.list_users()


@server.tool("proxmox-list-roles")
async def proxmox_list_roles() -> List[Dict[str, Any]]:
    client = get_client()
    return client.list_roles()


@server.tool("proxmox-assign-permission")
async def proxmox_assign_permission(
    path: str,
    roles: str,
    users: Optional[str] = None,
    groups: Optional[str] = None,
    propagate: bool = True,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_client()
    if not path or not roles:
        raise ValueError("path and roles are required")
    require_confirm(confirm)
    if dry_run:
        return {
            "dry_run": True,
            "action": "assign-permission",
            "params": {
                "path": path,
                "roles": roles,
                "users": users,
                "groups": groups,
                "propagate": propagate,
            },
        }
    res = client.assign_permission(
        path, roles, users=users, groups=groups, propagate=propagate
    )
    return {"result": res}


# ---------- Orchestration helpers ----------


@server.tool("proxmox-wait-task")
async def proxmox_wait_task(
    upid: str,
    node: Optional[str] = None,
    timeout: int = 900,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    client = get_client()
    status = client.wait_task(
        upid, node=node, timeout=timeout, poll_interval=poll_interval
    )
    return status


@server.tool("proxmox-register-vm-as-host")
async def proxmox_register_vm_as_host(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    ssh_user: str = "root",
    ssh_private_key_path: Optional[str] = None,
    prefer_interface: Optional[str] = None,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, vm = client.resolve_vm(vmid=vmid, name=name, node=node)
    # Try to fetch IPs via QGA
    interfaces = {}
    try:
        qga = client.qga_network_get_interfaces(vm_node, vm_vmid)
        interfaces = qga.get("result", {})
    except Exception as e:
        interfaces = {"error": str(e)}
    # Simplify: pick first private IPv4 found
    chosen_ip: Optional[str] = None
    if isinstance(interfaces, list):
        for itf in interfaces:
            if prefer_interface and itf.get("name") != prefer_interface:
                continue
            for addr in itf.get("ip-addresses", []) or []:
                if (
                    addr.get("ip-address-type") == "ipv4"
                    and not addr.get("prefix") == 32
                ):
                    chosen_ip = addr.get("ip-address")
                    break
            if chosen_ip:
                break
    # Emit JSON and INI snippets
    hostname = vm.get("name") or f"vm{vm_vmid}"
    ini = f"[{hostname}]\n{hostname} ansible_host={chosen_ip or '<IP>'} ansible_user={ssh_user}"
    if ssh_private_key_path:
        ini += f" ansible_ssh_private_key_file={ssh_private_key_path}"
    return {
        "hostname": hostname,
        "ip": chosen_ip,
        "json": {
            hostname: {
                "ansible_host": chosen_ip or "<IP>",
                "ansible_user": ssh_user,
                **(
                    {"ansible_ssh_private_key_file": ssh_private_key_path}
                    if ssh_private_key_path
                    else {}
                ),
            }
        },
        "ini": ini,
        "interfaces": interfaces,
    }


# Optional helpers (stubs for future expansion)
@server.tool("proxmox-guest-exec")
async def proxmox_guest_exec(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    command: str = "",
    args: Optional[List[str]] = None,
    input_data: Optional[str] = None,
) -> Dict[str, Any]:
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    if not command:
        raise ValueError("command is required")
    return client.qga_exec(
        vm_node, vm_vmid, command=command, args=args, input_data=input_data
    )


# -------- CloudInit and Advanced OS Installation --------


register_provisioning_tools(server, get_client, require_confirm)


# ---------- Automation Features ----------


register_automation_tools(
    server,
    get_client,
    require_confirm,
    get_openshift_installer,
    get_docker_swarm_symbols,
    get_infrastructure_manager,
    get_network_manager,
    get_storage_manager,
)


# ---------- Security & Authentication Features ----------


register_security_tools(server, get_client, get_security_manager)


# ---------- Monitoring & Observability Features ----------


register_observability_tools(server, get_client, get_monitoring_manager)


# ---------- AI/ML Optimization Features ----------


register_ai_tools(server, get_client, get_ai_manager)


# ---------- Integration & API Features ----------


register_control_plane_tools(server, get_client, get_integration_manager)


# ---------- VM/LXC Notes Management ----------


register_notes_tools(server, get_client, require_confirm)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Proxmox MCP server")
    parser.add_argument(
        "--profile",
        action="append",
        default=None,
        help=(
            "Enable one or more optional tool profiles. "
            "Repeat the flag or pass a comma-separated list. "
            "Default is core."
        ),
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="Print available profiles and exit",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print enabled tool names for the selected profiles and exit",
    )
    args = parser.parse_args(argv)

    if args.list_profiles:
        for profile_name in sorted(PROFILE_DESCRIPTIONS):
            print(f"{profile_name}: {PROFILE_DESCRIPTIONS[profile_name]}")
        return

    try:
        active_profiles = resolve_profiles(args.profile)
    except ValueError as exc:
        parser.error(str(exc))

    enabled_tool_names = apply_profiles_to_server(server, active_profiles)

    if args.list_tools:
        for tool_name in sorted(enabled_tool_names):
            print(tool_name)
        return

    print(
        f"Starting proxmox-mcp with profiles: {', '.join(active_profiles)}",
        file=sys.stderr,
    )
    server.run("stdio")


if __name__ == "__main__":
    main()
