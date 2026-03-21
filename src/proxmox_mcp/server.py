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
from .registrars.clusters import register_cluster_tools
from .registrars.control_plane import register_control_plane_tools
from .registrars.core_compute import register_core_compute_tools
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


register_cluster_tools(server, get_client, is_multi_cluster_mode, get_cluster_registry)


# ---------- Core discovery ----------


register_core_compute_tools(server, get_client, require_confirm)


# ---------- VM lifecycle ----------


# ---------- LXC lifecycle ----------


# ---------- Cloud-init & networking ----------


# ---------- Images, templates, snapshots, backups ----------


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
