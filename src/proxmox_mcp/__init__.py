"""MCP Proxmox package exports."""

from __future__ import annotations

from importlib import import_module


__version__ = "0.2.1"

_EXPORTS = {
    "ProxmoxClient": ("client", "ProxmoxClient"),
    "server": ("server", "server"),
    "format_size": ("utils", "format_size"),
    "ClusterConfig": ("utils", "ClusterConfig"),
    "ClusterRegistryConfig": ("utils", "ClusterRegistryConfig"),
    "read_multi_cluster_env": ("utils", "read_multi_cluster_env"),
    "load_cluster_registry_config": ("utils", "load_cluster_registry_config"),
    "is_multi_cluster_mode": ("utils", "is_multi_cluster_mode"),
    "CloudInitConfig": ("cloudinit", "CloudInitConfig"),
    "CloudInitProvisioner": ("cloudinit", "CloudInitProvisioner"),
    "IgnitionConfig": ("rhcos", "IgnitionConfig"),
    "RHCOSProvisioner": ("rhcos", "RHCOSProvisioner"),
    "OpenShiftInstaller": ("rhcos", "OpenShiftInstaller"),
    "WindowsConfig": ("windows", "WindowsConfig"),
    "WindowsProvisioner": ("windows", "WindowsProvisioner"),
    "DockerSwarmConfig": ("docker_swarm", "DockerSwarmConfig"),
    "DockerSwarmProvisioner": ("docker_swarm", "DockerSwarmProvisioner"),
    "ClusterRegistry": ("cluster_manager", "ClusterRegistry"),
    "get_cluster_registry": ("cluster_manager", "get_cluster_registry"),
    "reset_cluster_registry": ("cluster_manager", "reset_cluster_registry"),
    "ClusterError": ("cluster_manager", "ClusterError"),
    "ClusterNotFoundError": ("cluster_manager", "ClusterNotFoundError"),
    "ClusterConnectionError": ("cluster_manager", "ClusterConnectionError"),
    "AmbiguousClusterSelectionError": (
        "cluster_manager",
        "AmbiguousClusterSelectionError",
    ),
    "MultiClusterProxmoxClient": ("multi_cluster_client", "MultiClusterProxmoxClient"),
}

__all__ = ["__version__", *_EXPORTS.keys()]


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(f".{module_name}", __name__), attr_name)
    globals()[name] = value
    return value
