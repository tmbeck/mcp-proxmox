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
from .cloudinit import (
    CloudInitConfig,
    CloudInitProvisioner,
    get_ubuntu_web_server_config,
    get_docker_host_config,
    get_development_config,
)
from .rhcos import IgnitionConfig, RHCOSProvisioner
from .windows import (
    WindowsConfig,
    WindowsProvisioner,
    get_windows_web_server_config,
    get_windows_domain_controller_config,
)
from .notes_manager import NotesManager
from .registrars.ai import register_ai_tools
from .registrars.automation import register_automation_tools
from .registrars.control_plane import register_control_plane_tools
from .registrars.observability import register_observability_tools
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


@server.tool("proxmox-list-os-templates")
async def proxmox_list_os_templates(
    node: Optional[str] = None, storage: Optional[str] = None
) -> Dict[str, Any]:
    """List available OS templates and their configurations."""
    client = get_client()
    node_id = node or client.default_node
    storage_id = storage or client.default_storage
    if not node_id or not storage_id:
        raise ValueError("node and storage are required (or set defaults)")

    # Get available templates from storage
    storage_templates = client.list_os_templates(node_id, storage_id)

    # Get built-in CloudInit templates
    builtin_templates = []
    for template_key, template_info in CloudInitConfig.OS_TEMPLATES.items():
        builtin_templates.append(
            {
                "name": template_key,
                "display_name": template_info["name"],
                "type": "cloudinit",
                "default_user": template_info["default_user"],
                "package_manager": template_info["package_manager"],
                "image_url": template_info["image_url"],
            }
        )

    return {
        "storage_templates": storage_templates,
        "builtin_templates": builtin_templates,
        "total_templates": len(storage_templates) + len(builtin_templates),
    }


@server.tool("proxmox-download-os-template")
async def proxmox_download_os_template(
    template_name: str,
    node: Optional[str] = None,
    storage: Optional[str] = None,
    verify_checksum: bool = True,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Download OS template from official sources."""
    client = get_client()
    node_id = node or client.default_node
    storage_id = storage or client.default_storage
    if not node_id or not storage_id:
        raise ValueError("node and storage are required (or set defaults)")

    if template_name not in CloudInitConfig.OS_TEMPLATES:
        raise ValueError(
            f"Unsupported template: {template_name}. Supported: {list(CloudInitConfig.OS_TEMPLATES.keys())}"
        )

    require_confirm(confirm)
    template_info = CloudInitConfig.OS_TEMPLATES[template_name]

    if dry_run:
        return {
            "dry_run": True,
            "action": "download-template",
            "params": {
                "template_name": template_name,
                "node": node_id,
                "storage": storage_id,
                "url": template_info["image_url"],
                "verify_checksum": verify_checksum,
            },
        }

    upid = client.download_os_template(
        node_id, storage_id, template_name, template_info["image_url"]
    )
    return {
        "upid": upid,
        "template_name": template_name,
        "template_info": template_info,
    }


@server.tool("proxmox-create-vm-cloudinit")
async def proxmox_create_vm_cloudinit(
    node: Optional[str] = None,
    vmid: int = 0,
    name: str = "",
    template: str = "ubuntu-22.04",
    cloudinit_config: Optional[Dict[str, Any]] = None,
    hardware: Optional[Dict[str, Any]] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = False,
    timeout: int = 900,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    """Create VM with advanced CloudInit configuration."""
    client = get_client()
    node_id = node or client.default_node
    if not node_id:
        raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
    if vmid <= 0 or not name:
        raise ValueError("vmid > 0 and non-empty name are required")

    require_confirm(confirm)

    # Default hardware configuration
    hw_config = hardware or {}
    cores = hw_config.get("cores", 2)
    memory_mb = hw_config.get("memory_mb", 2048)
    disk_gb = hw_config.get("disk_gb", 20)

    if dry_run:
        return {
            "dry_run": True,
            "action": "create-vm-cloudinit",
            "params": {
                "node": node_id,
                "vmid": vmid,
                "name": name,
                "template": template,
                "hardware": {
                    "cores": cores,
                    "memory_mb": memory_mb,
                    "disk_gb": disk_gb,
                },
                "cloudinit_config": cloudinit_config,
            },
        }

    # Create CloudInit configuration
    config = CloudInitConfig(template)

    # Apply user-provided CloudInit configuration
    if cloudinit_config:
        if "hostname" in cloudinit_config:
            config.set_hostname(
                cloudinit_config["hostname"], cloudinit_config.get("fqdn")
            )

        if "users" in cloudinit_config:
            for user in cloudinit_config["users"]:
                config.add_user(
                    user["name"],
                    user.get("ssh_keys", []),
                    user.get("sudo", "ALL=(ALL) NOPASSWD:ALL"),
                    user.get("shell", "/bin/bash"),
                    user.get("passwd"),
                )

        if "packages" in cloudinit_config:
            config.add_packages(cloudinit_config["packages"])

        if "commands" in cloudinit_config:
            config.add_commands(cloudinit_config["commands"])

        if "network" in cloudinit_config:
            net = cloudinit_config["network"]
            config.set_network_config(
                interface=net.get("interface", "ens18"),
                dhcp=net.get("dhcp", True),
                ip=net.get("ip"),
                gateway=net.get("gateway"),
                nameservers=net.get("nameservers"),
            )

        if "timezone" in cloudinit_config:
            config.set_timezone(cloudinit_config["timezone"])

    # Create VM with CloudInit
    provisioner = CloudInitProvisioner(client)
    upid = provisioner.create_vm_with_cloudinit(
        node=node_id,
        vmid=vmid,
        name=name,
        template=template,
        cloudinit_config=config,
        hardware={"cores": cores, "memory_mb": memory_mb, "disk_gb": disk_gb},
    )

    result: Dict[str, Any] = {"upid": upid, "template": template}
    if wait:
        status = client.wait_task(
            upid, node=node_id, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status

    return result


@server.tool("proxmox-configure-cloudinit-advanced")
async def proxmox_configure_cloudinit_advanced(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    users: Optional[List[Dict[str, Any]]] = None,
    packages: Optional[List[str]] = None,
    commands: Optional[List[str]] = None,
    network_config: Optional[Dict[str, Any]] = None,
    files: Optional[List[Dict[str, Any]]] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Configure advanced CloudInit settings for VM."""
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
    require_confirm(confirm)

    if dry_run:
        return {
            "dry_run": True,
            "action": "configure-cloudinit-advanced",
            "params": {
                "node": vm_node,
                "vmid": vm_vmid,
                "users": users or [],
                "packages": packages or [],
                "commands": commands or [],
                "network_config": network_config,
                "files": files or [],
            },
        }

    # Create CloudInit configuration
    config = CloudInitConfig()

    # Configure users
    if users:
        for user in users:
            config.add_user(
                user["name"],
                user.get("ssh_keys", []),
                user.get("sudo", "ALL=(ALL) NOPASSWD:ALL"),
                user.get("shell", "/bin/bash"),
                user.get("passwd"),
            )

    # Add packages
    if packages:
        config.add_packages(packages)

    # Add commands
    if commands:
        config.add_commands(commands)

    # Configure network
    if network_config:
        config.set_network_config(
            interface=network_config.get("interface", "ens18"),
            dhcp=network_config.get("dhcp", True),
            ip=network_config.get("ip"),
            gateway=network_config.get("gateway"),
            nameservers=network_config.get("nameservers"),
        )

    # Add files
    if files:
        for file_config in files:
            config.add_file(
                file_config["path"],
                file_config["content"],
                file_config.get("permissions", "0644"),
                file_config.get("owner", "root:root"),
                file_config.get("encoding", "text/plain"),
            )

    # Create and attach CloudInit ISO
    user_data = config.to_user_data()
    iso_path = f"/tmp/cloudinit-{vm_vmid}.iso"
    client.create_cloudinit_iso(user_data, output_path=iso_path)

    # Upload and attach ISO
    result = client.attach_cloudinit_iso(vm_node, vm_vmid, iso_path)

    # Clean up temporary file
    os.unlink(iso_path)

    return result


@server.tool("proxmox-create-preset-vm")
async def proxmox_create_preset_vm(
    preset: str,
    node: Optional[str] = None,
    vmid: int = 0,
    name: str = "",
    hostname: str = "",
    ssh_keys: List[str] = [],
    admin_user: str = "",
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = False,
    timeout: int = 900,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    """Create VM with preset configurations (web-server, docker-host, development)."""
    client = get_client()
    node_id = node or client.default_node
    if not node_id:
        raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
    if vmid <= 0 or not name:
        raise ValueError("vmid > 0 and non-empty name are required")
    if not ssh_keys:
        raise ValueError("ssh_keys are required for preset configurations")

    require_confirm(confirm)

    # Get preset configuration
    preset_configs = {
        "web-server": get_ubuntu_web_server_config,
        "docker-host": get_docker_host_config,
        "development": get_development_config,
    }

    if preset not in preset_configs:
        raise ValueError(
            f"Unsupported preset: {preset}. Supported: {list(preset_configs.keys())}"
        )

    if dry_run:
        return {
            "dry_run": True,
            "action": "create-preset-vm",
            "params": {
                "preset": preset,
                "node": node_id,
                "vmid": vmid,
                "name": name,
                "hostname": hostname or name,
                "admin_user": admin_user,
                "ssh_keys_count": len(ssh_keys),
            },
        }

    # Create preset configuration
    if preset == "development":
        default_user = "fedora"
    else:
        default_user = "ubuntu"

    config = preset_configs[preset](
        hostname or name, ssh_keys, admin_user or default_user
    )

    # Create VM with preset CloudInit
    provisioner = CloudInitProvisioner(client)
    upid = provisioner.create_vm_with_cloudinit(
        node=node_id,
        vmid=vmid,
        name=name,
        template=config.template,
        cloudinit_config=config,
        hardware={"cores": 2, "memory_mb": 2048, "disk_gb": 20},
    )

    result: Dict[str, Any] = {
        "upid": upid,
        "preset": preset,
        "template": config.template,
    }
    if wait:
        status = client.wait_task(
            upid, node=node_id, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status

    return result


# -------- RHCOS and OpenShift Deployment --------


@server.tool("proxmox-list-rhcos-streams")
async def proxmox_list_rhcos_streams() -> Dict[str, Any]:
    """List available RHCOS release streams and versions."""
    return {
        "streams": IgnitionConfig.RHCOS_STREAMS,
        "supported_versions": list(IgnitionConfig.RHCOS_STREAMS.keys()),
        "default_version": "4.14",
    }


@server.tool("proxmox-download-rhcos")
async def proxmox_download_rhcos(
    version: str,
    node: Optional[str] = None,
    storage: Optional[str] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Download RHCOS image from official Red Hat sources."""
    client = get_client()
    node_id = node or client.default_node
    storage_id = storage or client.default_storage
    if not node_id or not storage_id:
        raise ValueError("node and storage are required (or set defaults)")

    if version not in IgnitionConfig.RHCOS_STREAMS:
        raise ValueError(
            f"Unsupported RHCOS version: {version}. Supported: {list(IgnitionConfig.RHCOS_STREAMS.keys())}"
        )

    require_confirm(confirm)
    stream_info = IgnitionConfig.RHCOS_STREAMS[version]

    if dry_run:
        return {
            "dry_run": True,
            "action": "download-rhcos",
            "params": {
                "version": version,
                "node": node_id,
                "storage": storage_id,
                "stream_info": stream_info,
            },
        }

    provisioner = RHCOSProvisioner(client)
    upid = provisioner.download_rhcos_image(version, node_id, storage_id)

    return {
        "upid": upid,
        "version": version,
        "stream_info": stream_info,
        "status": "downloading",
    }


@server.tool("proxmox-create-rhcos-vm")
async def proxmox_create_rhcos_vm(
    node: Optional[str] = None,
    vmid: int = 0,
    name: str = "",
    rhcos_version: str = "4.14",
    ignition_config: Optional[Dict[str, Any]] = None,
    hardware: Optional[Dict[str, Any]] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = False,
    timeout: int = 900,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    """Create RHCOS VM with Ignition configuration."""
    client = get_client()
    node_id = node or client.default_node
    if not node_id:
        raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
    if vmid <= 0 or not name:
        raise ValueError("vmid > 0 and non-empty name are required")

    require_confirm(confirm)

    # Default hardware configuration for RHCOS
    hw_config = hardware or {}
    cores = hw_config.get("cores", 4)
    memory_mb = hw_config.get("memory_mb", 8192)
    disk_gb = hw_config.get("disk_gb", 50)

    if dry_run:
        return {
            "dry_run": True,
            "action": "create-rhcos-vm",
            "params": {
                "node": node_id,
                "vmid": vmid,
                "name": name,
                "rhcos_version": rhcos_version,
                "hardware": {
                    "cores": cores,
                    "memory_mb": memory_mb,
                    "disk_gb": disk_gb,
                },
                "ignition_config": ignition_config,
            },
        }

    # Create Ignition configuration
    config = IgnitionConfig()

    # Apply user-provided Ignition configuration
    if ignition_config:
        if "users" in ignition_config:
            for user in ignition_config["users"]:
                config.add_user(
                    user["name"],
                    user.get("ssh_keys", []),
                    user.get("groups", ["sudo", "docker"]),
                    user.get("shell", "/bin/bash"),
                    user.get("home_dir"),
                )

        if "hostname" in ignition_config:
            config.set_hostname(ignition_config["hostname"])

        if "files" in ignition_config:
            for file_config in ignition_config["files"]:
                config.add_file(
                    file_config["path"],
                    file_config["content"],
                    file_config.get("mode", 0o644),
                    file_config.get("user_id", 0),
                    file_config.get("group_id", 0),
                )

        if "systemd_units" in ignition_config:
            for unit in ignition_config["systemd_units"]:
                config.add_systemd_unit(
                    unit["name"],
                    unit.get("content", ""),
                    unit.get("enabled", True),
                    unit.get("mask", False),
                )

    # Create RHCOS VM
    provisioner = RHCOSProvisioner(client)
    upid = provisioner.create_rhcos_vm(
        node=node_id,
        vmid=vmid,
        name=name,
        rhcos_version=rhcos_version,
        ignition_config=config,
        hardware={"cores": cores, "memory_mb": memory_mb, "disk_gb": disk_gb},
    )

    result: Dict[str, Any] = {"upid": upid, "rhcos_version": rhcos_version}
    if wait:
        status = client.wait_task(
            upid, node=node_id, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status

    return result


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


@server.tool("proxmox-create-ignition-config")
async def proxmox_create_ignition_config(
    users: List[Dict[str, Any]],
    hostname: Optional[str] = None,
    files: Optional[List[Dict[str, Any]]] = None,
    systemd_units: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create and validate Ignition configuration for RHCOS."""
    config = IgnitionConfig()

    # Add users
    for user in users:
        config.add_user(
            user["name"],
            user.get("ssh_keys", []),
            user.get("groups", ["sudo", "docker"]),
            user.get("shell", "/bin/bash"),
            user.get("home_dir"),
        )

    # Set hostname
    if hostname:
        config.set_hostname(hostname)

    # Add files
    if files:
        for file_config in files:
            config.add_file(
                file_config["path"],
                file_config["content"],
                file_config.get("mode", 0o644),
                file_config.get("user_id", 0),
                file_config.get("group_id", 0),
            )

    # Add systemd units
    if systemd_units:
        for unit in systemd_units:
            config.add_systemd_unit(
                unit["name"],
                unit.get("content", ""),
                unit.get("enabled", True),
                unit.get("mask", False),
            )

    # Validate and return
    config.validate_config()

    return {
        "ignition_config": config.config,
        "ignition_json": config.to_json(),
        "ignition_compact": config.to_compact_json(),
        "validation": "passed",
    }


# -------- Windows VM Management --------


@server.tool("proxmox-list-windows-versions")
async def proxmox_list_windows_versions() -> Dict[str, Any]:
    """List available Windows Server versions and configurations."""
    return {
        "versions": WindowsConfig.WINDOWS_VERSIONS,
        "supported_versions": list(WindowsConfig.WINDOWS_VERSIONS.keys()),
        "default_version": "server-2022",
        "virtio_drivers": WindowsConfig.VIRTIO_DRIVERS,
    }


@server.tool("proxmox-create-windows-vm")
async def proxmox_create_windows_vm(
    node: Optional[str] = None,
    vmid: int = 0,
    name: str = "",
    windows_version: str = "server-2022",
    admin_password: str = "",
    computer_name: str = "",
    hardware: Optional[Dict[str, Any]] = None,
    domain_config: Optional[Dict[str, Any]] = None,
    applications: Optional[List[Dict[str, Any]]] = None,
    license_key: Optional[str] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = False,
    timeout: int = 1800,
    poll_interval: float = 5.0,
) -> Dict[str, Any]:
    """Create Windows Server VM with automated installation and configuration."""
    client = get_client()
    node_id = node or client.default_node
    if not node_id:
        raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
    if vmid <= 0 or not name:
        raise ValueError("vmid > 0 and non-empty name are required")
    if not admin_password:
        raise ValueError("admin_password is required")

    require_confirm(confirm)

    # Default hardware configuration for Windows
    hw_config = hardware or {}
    cores = hw_config.get("cores", 4)
    memory_mb = hw_config.get("memory_mb", 4096)
    disk_gb = hw_config.get("disk_gb", 60)

    if dry_run:
        return {
            "dry_run": True,
            "action": "create-windows-vm",
            "params": {
                "node": node_id,
                "vmid": vmid,
                "name": name,
                "windows_version": windows_version,
                "computer_name": computer_name or name,
                "hardware": {
                    "cores": cores,
                    "memory_mb": memory_mb,
                    "disk_gb": disk_gb,
                },
                "domain_config": domain_config,
                "applications": applications or [],
                "has_license_key": bool(license_key),
            },
        }

    # Create Windows configuration
    config = WindowsConfig(windows_version)
    config.set_admin_password(admin_password)
    config.set_computer_name(computer_name or name)

    # Configure domain joining
    if domain_config:
        config.set_domain_config(
            domain_config["domain"],
            domain_config["username"],
            domain_config["password"],
            domain_config.get("ou_path"),
        )

    # Add applications
    if applications:
        for app in applications:
            config.add_application(
                app["name"], app["installer_url"], app.get("silent_args", "/S")
            )

    # Create Windows VM
    provisioner = WindowsProvisioner(client)
    upid = provisioner.create_windows_vm(
        node=node_id,
        vmid=vmid,
        name=name,
        windows_version=windows_version,
        windows_config=config,
        hardware={"cores": cores, "memory_mb": memory_mb, "disk_gb": disk_gb},
        license_key=license_key,
    )

    result: Dict[str, Any] = {
        "upid": upid,
        "windows_version": windows_version,
        "computer_name": computer_name or name,
        "rdp_port": 3389,
    }

    if wait:
        status = client.wait_task(
            upid, node=node_id, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status

    return result


@server.tool("proxmox-create-windows-preset")
async def proxmox_create_windows_preset(
    preset: str,
    node: Optional[str] = None,
    vmid: int = 0,
    name: str = "",
    computer_name: str = "",
    admin_password: str = "",
    domain: Optional[str] = None,
    license_key: Optional[str] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
    wait: bool = False,
    timeout: int = 1800,
    poll_interval: float = 5.0,
) -> Dict[str, Any]:
    """Create Windows VM with preset configurations (web-server, domain-controller)."""
    client = get_client()
    node_id = node or client.default_node
    if not node_id:
        raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
    if vmid <= 0 or not name:
        raise ValueError("vmid > 0 and non-empty name are required")
    if not admin_password:
        raise ValueError("admin_password is required")

    require_confirm(confirm)

    # Get preset configuration
    preset_configs = {
        "web-server": get_windows_web_server_config,
        "domain-controller": get_windows_domain_controller_config,
    }

    if preset not in preset_configs:
        raise ValueError(
            f"Unsupported preset: {preset}. Supported: {list(preset_configs.keys())}"
        )

    if dry_run:
        return {
            "dry_run": True,
            "action": "create-windows-preset",
            "params": {
                "preset": preset,
                "node": node_id,
                "vmid": vmid,
                "name": name,
                "computer_name": computer_name or name,
                "domain": domain,
                "has_license_key": bool(license_key),
            },
        }

    # Create preset configuration
    if preset == "web-server":
        config = preset_configs[preset](computer_name or name, admin_password, domain)
    elif preset == "domain-controller":
        if not domain:
            raise ValueError("domain is required for domain-controller preset")
        config = preset_configs[preset](computer_name or name, admin_password, domain)

    # Create Windows VM
    provisioner = WindowsProvisioner(client)
    upid = provisioner.create_windows_vm(
        node=node_id,
        vmid=vmid,
        name=name,
        windows_version="server-2022",
        windows_config=config,
        hardware={"cores": 4, "memory_mb": 4096, "disk_gb": 60},
        license_key=license_key,
    )

    result: Dict[str, Any] = {
        "upid": upid,
        "preset": preset,
        "windows_version": "server-2022",
        "computer_name": computer_name or name,
        "rdp_port": 3389,
    }

    if wait:
        status = client.wait_task(
            upid, node=node_id, timeout=timeout, poll_interval=poll_interval
        )
        result["status"] = status

    return result


@server.tool("proxmox-windows-domain-join")
async def proxmox_windows_domain_join(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    domain: str = "",
    username: str = "",
    password: str = "",
    ou_path: Optional[str] = None,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Join Windows VM to Active Directory domain."""
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)

    if not domain or not username or not password:
        raise ValueError("domain, username, and password are required")

    require_confirm(confirm)

    if dry_run:
        return {
            "dry_run": True,
            "action": "windows-domain-join",
            "params": {
                "node": vm_node,
                "vmid": vm_vmid,
                "domain": domain,
                "username": username,
                "ou_path": ou_path,
            },
        }

    # Join domain
    provisioner = WindowsProvisioner(client)
    result = provisioner.join_domain(
        vm_node, vm_vmid, domain, username, password, ou_path
    )

    return result


@server.tool("proxmox-windows-install-apps")
async def proxmox_windows_install_apps(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    applications: List[Dict[str, Any]] = [],
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Install applications on Windows VM."""
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)

    if not applications:
        raise ValueError("applications list is required")

    require_confirm(confirm)

    if dry_run:
        return {
            "dry_run": True,
            "action": "windows-install-apps",
            "params": {
                "node": vm_node,
                "vmid": vm_vmid,
                "applications": [app["name"] for app in applications],
            },
        }

    # Install applications
    provisioner = WindowsProvisioner(client)
    result = provisioner.install_applications(vm_node, vm_vmid, applications)

    return result


@server.tool("proxmox-windows-configure-rdp")
async def proxmox_windows_configure_rdp(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    enable: bool = True,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Configure Windows Remote Desktop Protocol."""
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)

    require_confirm(confirm)

    if dry_run:
        return {
            "dry_run": True,
            "action": "windows-configure-rdp",
            "params": {"node": vm_node, "vmid": vm_vmid, "enable": enable},
        }

    # Configure RDP
    result = client.configure_windows_rdp(vm_node, vm_vmid, enable)

    return result


@server.tool("proxmox-windows-vm-info")
async def proxmox_windows_vm_info(
    vmid: Optional[int] = None, name: Optional[str] = None, node: Optional[str] = None
) -> Dict[str, Any]:
    """Get detailed Windows VM information including RDP access."""
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)

    # Get Windows-specific VM info
    vm_info = client.get_windows_vm_info(vm_node, vm_vmid)

    return vm_info


@server.tool("proxmox-windows-execute-command")
async def proxmox_windows_execute_command(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    command: str = "",
    shell: str = "powershell",
    confirm: Optional[bool] = None,
) -> Dict[str, Any]:
    """Execute command on Windows VM via QEMU guest agent."""
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)

    if not command:
        raise ValueError("command is required")

    require_confirm(confirm)

    # Execute command
    result = client.execute_windows_command(vm_node, vm_vmid, command, shell)

    return result


@server.tool("proxmox-windows-services")
async def proxmox_windows_services(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    action: str = "list",
    service_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Manage Windows services (list, restart)."""
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)

    if action == "list":
        result = client.get_windows_services(vm_node, vm_vmid)
    elif action == "restart":
        if not service_name:
            raise ValueError("service_name is required for restart action")
        result = client.restart_windows_service(vm_node, vm_vmid, service_name)
    else:
        raise ValueError(f"Unsupported action: {action}. Supported: list, restart")

    return result


@server.tool("proxmox-windows-updates")
async def proxmox_windows_updates(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    confirm: Optional[bool] = None,
) -> Dict[str, Any]:
    """Install Windows updates via PowerShell."""
    client = get_client()
    vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)

    require_confirm(confirm)

    # Install updates
    result = client.install_windows_updates(vm_node, vm_vmid)

    return result


# ---------- Security & Authentication Features ----------


register_security_tools(server, get_client, get_security_manager)


# ---------- Monitoring & Observability Features ----------


register_observability_tools(server, get_client, get_monitoring_manager)


# ---------- AI/ML Optimization Features ----------


register_ai_tools(server, get_client, get_ai_manager)


# ---------- Integration & API Features ----------


register_control_plane_tools(server, get_client, get_integration_manager)


# ---------- VM/LXC Notes Management ----------


@server.tool("proxmox-vm-notes-read")
async def proxmox_vm_notes_read(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    format: str = "auto",
    parse_secrets: bool = True,
) -> Dict[str, Any]:
    """Read VM description/notes with format detection and secret reference parsing"""
    client = get_client()
    notes_manager = NotesManager(client)

    # Resolve VM
    vm_vmid, vm_node, vm_info = client.resolve_vm(vmid=vmid, name=name, node=node)

    # Get notes
    notes_content = client.get_vm_notes(vm_node, vm_vmid)

    # Format output
    formatted = notes_manager.format_notes_output(notes_content, format, parse_secrets)

    return {
        "vm": {"vmid": vm_vmid, "name": vm_info.get("name"), "node": vm_node},
        "notes": formatted,
    }


@server.tool("proxmox-vm-notes-update")
async def proxmox_vm_notes_update(
    content: str,
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    format: str = "auto",
    validate: bool = True,
    backup: bool = True,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Update VM description/notes with validation and backup"""
    client = get_client()
    notes_manager = NotesManager(client)

    # Resolve VM
    vm_vmid, vm_node, vm_info = client.resolve_vm(vmid=vmid, name=name, node=node)

    # Validate content if requested
    warnings = []
    if validate:
        is_valid, validation_warnings = notes_manager.validate_content(content)
        warnings.extend(validation_warnings)

        if not is_valid:
            return {
                "success": False,
                "error": "Content validation failed",
                "warnings": warnings,
            }

    # Get backup of existing notes if requested
    previous_notes = None
    if backup:
        previous_notes = client.get_vm_notes(vm_node, vm_vmid)

    if dry_run:
        return {
            "dry_run": True,
            "action": "update-vm-notes",
            "vm": {"vmid": vm_vmid, "name": vm_info.get("name"), "node": vm_node},
            "content_length": len(content),
            "format": notes_manager.detect_format(content),
            "warnings": warnings,
            "previous_notes_length": len(previous_notes) if previous_notes else 0,
        }

    require_confirm(confirm)

    # Update notes
    result = client.set_vm_notes(vm_node, vm_vmid, content)

    return {
        "success": True,
        "vm": {"vmid": vm_vmid, "name": vm_info.get("name"), "node": vm_node},
        "previous_notes": previous_notes if backup else None,
        "warnings": warnings,
        "result": result,
    }


@server.tool("proxmox-vm-notes-remove")
async def proxmox_vm_notes_remove(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    backup: bool = True,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Remove VM description/notes with backup option"""
    client = get_client()

    # Resolve VM
    vm_vmid, vm_node, vm_info = client.resolve_vm(vmid=vmid, name=name, node=node)

    # Get backup of existing notes if requested
    backup_notes = None
    if backup:
        backup_notes = client.get_vm_notes(vm_node, vm_vmid)

    if dry_run:
        return {
            "dry_run": True,
            "action": "remove-vm-notes",
            "vm": {"vmid": vm_vmid, "name": vm_info.get("name"), "node": vm_node},
            "backup_notes_length": len(backup_notes) if backup_notes else 0,
        }

    require_confirm(confirm)

    # Remove notes by setting empty string
    result = client.set_vm_notes(vm_node, vm_vmid, "")

    return {
        "success": True,
        "vm": {"vmid": vm_vmid, "name": vm_info.get("name"), "node": vm_node},
        "backup_notes": backup_notes if backup else None,
        "result": result,
    }


@server.tool("proxmox-lxc-notes-read")
async def proxmox_lxc_notes_read(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    format: str = "auto",
    parse_secrets: bool = True,
) -> Dict[str, Any]:
    """Read LXC description/notes with format detection and secret reference parsing"""
    client = get_client()
    notes_manager = NotesManager(client)

    # Resolve LXC
    ct_vmid, ct_node, ct_info = client.resolve_lxc(vmid=vmid, name=name, node=node)

    # Get notes
    notes_content = client.get_lxc_notes(ct_node, ct_vmid)

    # Format output
    formatted = notes_manager.format_notes_output(notes_content, format, parse_secrets)

    return {
        "lxc": {"vmid": ct_vmid, "name": ct_info.get("name"), "node": ct_node},
        "notes": formatted,
    }


@server.tool("proxmox-lxc-notes-update")
async def proxmox_lxc_notes_update(
    content: str,
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    format: str = "auto",
    validate: bool = True,
    backup: bool = True,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Update LXC description/notes with validation and backup"""
    client = get_client()
    notes_manager = NotesManager(client)

    # Resolve LXC
    ct_vmid, ct_node, ct_info = client.resolve_lxc(vmid=vmid, name=name, node=node)

    # Validate content if requested
    warnings = []
    if validate:
        is_valid, validation_warnings = notes_manager.validate_content(content)
        warnings.extend(validation_warnings)

        if not is_valid:
            return {
                "success": False,
                "error": "Content validation failed",
                "warnings": warnings,
            }

    # Get backup of existing notes if requested
    previous_notes = None
    if backup:
        previous_notes = client.get_lxc_notes(ct_node, ct_vmid)

    if dry_run:
        return {
            "dry_run": True,
            "action": "update-lxc-notes",
            "lxc": {"vmid": ct_vmid, "name": ct_info.get("name"), "node": ct_node},
            "content_length": len(content),
            "format": notes_manager.detect_format(content),
            "warnings": warnings,
            "previous_notes_length": len(previous_notes) if previous_notes else 0,
        }

    require_confirm(confirm)

    # Update notes
    result = client.set_lxc_notes(ct_node, ct_vmid, content)

    return {
        "success": True,
        "lxc": {"vmid": ct_vmid, "name": ct_info.get("name"), "node": ct_node},
        "previous_notes": previous_notes if backup else None,
        "warnings": warnings,
        "result": result,
    }


@server.tool("proxmox-lxc-notes-remove")
async def proxmox_lxc_notes_remove(
    vmid: Optional[int] = None,
    name: Optional[str] = None,
    node: Optional[str] = None,
    backup: bool = True,
    confirm: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Remove LXC description/notes with backup option"""
    client = get_client()

    # Resolve LXC
    ct_vmid, ct_node, ct_info = client.resolve_lxc(vmid=vmid, name=name, node=node)

    # Get backup of existing notes if requested
    backup_notes = None
    if backup:
        backup_notes = client.get_lxc_notes(ct_node, ct_vmid)

    if dry_run:
        return {
            "dry_run": True,
            "action": "remove-lxc-notes",
            "lxc": {"vmid": ct_vmid, "name": ct_info.get("name"), "node": ct_node},
            "backup_notes_length": len(backup_notes) if backup_notes else 0,
        }

    require_confirm(confirm)

    # Remove notes by setting empty string
    result = client.set_lxc_notes(ct_node, ct_vmid, "")

    return {
        "success": True,
        "lxc": {"vmid": ct_vmid, "name": ct_info.get("name"), "node": ct_node},
        "backup_notes": backup_notes if backup else None,
        "result": result,
    }


@server.tool("proxmox-notes-template")
async def proxmox_notes_template(
    template_type: str, format: str = "html", variables: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Generate notes template with optional variable substitution"""
    client = get_client()
    notes_manager = NotesManager(client)

    # Generate template
    template_content = notes_manager.generate_template(template_type, format, variables)

    # Extract variables used
    import re

    variables_used = re.findall(r"\{([A-Z_]+)\}", template_content)

    return {
        "template": template_content,
        "template_type": template_type,
        "format": format,
        "variables_used": list(set(variables_used)),
        "length": len(template_content),
    }


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
