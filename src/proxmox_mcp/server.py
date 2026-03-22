from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from .client import ProxmoxClient
from .runtime_env import load_runtime_env
from .utils import read_env, require_confirm, is_multi_cluster_mode
from .cluster_manager import get_cluster_registry
from .registrars.ai import register_ai_tools
from .registrars.automation import register_automation_tools
from .registrars.clusters import register_cluster_tools
from .registrars.core_admin import register_core_admin_tools
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
    validate_profile_dependencies,
)


server = FastMCP("proxmox-mcp")


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
    load_runtime_env()

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


# ---------- Metrics ----------
register_core_admin_tools(server, get_client, require_confirm)


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
        "--env-file",
        help=(
            "Path to an env file containing Proxmox configuration. "
            "Overrides implicit .env discovery."
        ),
    )
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

    load_runtime_env(args.env_file)

    try:
        active_profiles = resolve_profiles(args.profile)
        validate_profile_dependencies(active_profiles)
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
