from __future__ import annotations

import asyncio
import argparse
import sys
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from .client import (
    ProxmoxClient,
    TESTED_PROXMOX_VE_SERIES_LABEL,
    TESTED_PROXMOX_VE_VERSION,
)
from .runtime_env import load_runtime_env
from .utils import read_env, is_multi_cluster_mode
from .cluster_manager import get_cluster_registry
from .registrars.clusters import register_cluster_tools
from .registrars.core_admin import register_core_admin_tools
from .registrars.core_compute import register_core_compute_tools
from .registrars.notes import register_notes_tools
from .registrars.provisioning import register_provisioning_tools


server = FastMCP("proxmox-mcp")
_WARNED_PROXMOX_TARGETS: set[tuple[str, str]] = set()


def _warn_if_proxmox_version_mismatch(
    client: ProxmoxClient, cluster_name: Optional[str] = None
) -> None:
    compatibility = client.get_version_compatibility()
    if compatibility.compatible is not False or not compatibility.detected_version:
        return

    target_label = cluster_name or client.base_url
    cache_key = (client.base_url, target_label)
    if cache_key in _WARNED_PROXMOX_TARGETS:
        return

    if cluster_name:
        target = f"cluster '{cluster_name}' ({client.base_url})"
    else:
        target = client.base_url

    print(
        f"[proxmox-mcp] Warning: {target} reports Proxmox VE "
        f"{compatibility.detected_version}; this MCP server is tested against "
        f"{TESTED_PROXMOX_VE_VERSION}. Patch releases within "
        f"{TESTED_PROXMOX_VE_SERIES_LABEL} are expected to be compatible, but "
        "other major/minor versions are unverified.",
        file=sys.stderr,
    )
    _WARNED_PROXMOX_TARGETS.add(cache_key)


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
        client = registry.get_client(cluster_name)
        _warn_if_proxmox_version_mismatch(client, cluster_name)
        return client
    else:
        # Single-cluster mode: use environment variables
        read_env()
        client = ProxmoxClient.from_env()
        _warn_if_proxmox_version_mismatch(client)
        return client


# ---------- Multi-Cluster Helper Tools ----------


register_cluster_tools(server, get_client, is_multi_cluster_mode, get_cluster_registry)


# ---------- Core discovery ----------


register_core_compute_tools(server, get_client)


# ---------- Metrics ----------
register_core_admin_tools(server, get_client)


# -------- CloudInit and Advanced OS Installation --------


register_provisioning_tools(server, get_client)


# ---------- VM/LXC Notes Management ----------


register_notes_tools(server, get_client)


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
        "--list-tools",
        action="store_true",
        help="Print available tool names and exit",
    )
    args = parser.parse_args(argv)

    if args.env_file:
        load_runtime_env(args.env_file)

    if args.list_tools:
        tool_names = sorted(tool.name for tool in asyncio.run(server.list_tools()))
        for tool_name in tool_names:
            print(tool_name)
        return

    print("Starting proxmox-mcp", file=sys.stderr)
    server.run("stdio")


if __name__ == "__main__":
    main()
