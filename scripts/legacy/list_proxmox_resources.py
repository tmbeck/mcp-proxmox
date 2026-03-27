#!/usr/bin/env python3
"""
List Proxmox Resources from Multiple Clusters

This script uses the proxmox-mcp client to list:
- All nodes
- All VMs
- All LXC containers
- All storage
- Network information
From both staging and production Proxmox clusters.
"""

import sys
import os
import json
from pathlib import Path
from typing import Any, Dict, Optional
import logging

# Add project src to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root / "src"))
os.environ["PYTHONPATH"] = str(project_root / "src")

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def list_all_resources_from_cluster(
    cluster_registry, cluster_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    List all resources from a specific cluster.

    Args:
        cluster_registry: ClusterRegistry instance
        cluster_name: Name of the cluster (optional, uses default if not provided)

    Returns:
        Dictionary containing all resources
    """
    resources = {}

    try:
        logger.info(f"Fetching resources from cluster: {cluster_name or 'default'}")

        # Get client for cluster
        client = cluster_registry.get_client(cluster_name)

        # List nodes
        logger.info("Fetching nodes...")
        try:
            nodes = client.list_nodes()
            resources["nodes"] = nodes
            logger.info(f"  Found {len(nodes)} nodes")
        except Exception as e:
            logger.warning(f"  Error fetching nodes: {e}")
            resources["nodes"] = []

        # List VMs
        logger.info("Fetching VMs...")
        try:
            vms = client.list_vms()
            resources["vms"] = vms
            logger.info(f"  Found {len(vms)} VMs")
        except Exception as e:
            logger.warning(f"  Error fetching VMs: {e}")
            resources["vms"] = []

        # List LXC containers
        logger.info("Fetching LXC containers...")
        try:
            lxc_containers = client.list_lxc()
            resources["lxc"] = lxc_containers
            logger.info(f"  Found {len(lxc_containers)} LXC containers")
        except Exception as e:
            logger.warning(f"  Error fetching LXC containers: {e}")
            resources["lxc"] = []

        # List storage
        logger.info("Fetching storage...")
        try:
            storage = client.list_storage()
            resources["storage"] = storage
            logger.info(f"  Found {len(storage)} storage devices")
        except Exception as e:
            logger.warning(f"  Error fetching storage: {e}")
            resources["storage"] = []

        # Get node status for each node
        if resources.get("nodes"):
            logger.info("Fetching node status...")
            resources["node_status"] = {}
            for node in resources["nodes"]:
                try:
                    node_name = node.get("node")
                    if node_name:
                        status = client.get_node_status(node_name)
                        resources["node_status"][node_name] = status
                except Exception as e:
                    logger.warning(f"  Error getting status for node {node_name}: {e}")

        return resources

    except Exception as e:
        logger.error(f"Error fetching resources: {e}")
        import traceback

        traceback.print_exc()
        raise


def format_resources_report(resources: Dict[str, Any], cluster_name: str) -> str:
    """
    Format resources into a readable report.

    Args:
        resources: Dictionary of resources
        cluster_name: Name of the cluster

    Returns:
        Formatted report string
    """
    report = []
    report.append("=" * 80)
    report.append(f"PROXMOX CLUSTER RESOURCES - {cluster_name.upper()}")
    report.append("=" * 80)
    report.append("")

    # Nodes
    report.append("📍 NODES:")
    report.append("-" * 80)
    nodes = resources.get("nodes", [])
    if nodes:
        for node in nodes:
            report.append(f"  • {node.get('node', 'N/A')}")
            report.append(f"    - Status: {node.get('status', 'N/A')}")
            report.append(f"    - Uptime: {node.get('uptime', 'N/A')} seconds")
    else:
        report.append("  No nodes found")
    report.append("")

    # VMs
    report.append("🖥️  VIRTUAL MACHINES:")
    report.append("-" * 80)
    vms = resources.get("vms", [])
    if vms:
        report.append(f"  Total VMs: {len(vms)}")
        report.append("")
        for vm in vms[:10]:  # Show first 10
            vm_name = vm.get("name", f"VM {vm.get('vmid', 'N/A')}")
            vm_id = vm.get("vmid", "N/A")
            report.append(f"  • {vm_name} (ID: {vm_id})")
            report.append(f"    - Status: {vm.get('status', 'N/A')}")
            report.append(f"    - Node: {vm.get('node', 'N/A')}")
            mem_bytes = vm.get("mem", 0)
            if mem_bytes:
                report.append(f"    - Memory: {mem_bytes / 1024 / 1024:.2f} MB")
            report.append(f"    - CPU cores: {vm.get('cpus', 'N/A')}")
        if len(vms) > 10:
            report.append(f"  ... and {len(vms) - 10} more VMs")
    else:
        report.append("  No VMs found")
    report.append("")

    # LXC Containers
    report.append("📦 LXC CONTAINERS:")
    report.append("-" * 80)
    lxc = resources.get("lxc", [])
    if lxc:
        report.append(f"  Total Containers: {len(lxc)}")
        report.append("")
        for ct in lxc[:10]:  # Show first 10
            ct_name = ct.get("name", f"Container {ct.get('vmid', 'N/A')}")
            ct_id = ct.get("vmid", "N/A")
            report.append(f"  • {ct_name} (ID: {ct_id})")
            report.append(f"    - Status: {ct.get('status', 'N/A')}")
            report.append(f"    - Node: {ct.get('node', 'N/A')}")
            mem_bytes = ct.get("mem", 0)
            if mem_bytes:
                report.append(f"    - Memory: {mem_bytes / 1024 / 1024:.2f} MB")
            report.append(f"    - CPU cores: {ct.get('cpus', 'N/A')}")
        if len(lxc) > 10:
            report.append(f"  ... and {len(lxc) - 10} more containers")
    else:
        report.append("  No LXC containers found")
    report.append("")

    # Storage
    report.append("💾 STORAGE:")
    report.append("-" * 80)
    storage = resources.get("storage", [])
    if storage:
        report.append(f"  Total Storage: {len(storage)}")
        report.append("")
        for stg in storage:
            report.append(f"  • {stg.get('storage', 'N/A')} ({stg.get('type', 'N/A')})")
            report.append(f"    - Content: {stg.get('content', 'N/A')}")
            report.append(f"    - Enabled: {stg.get('enabled', 'N/A')}")
            report.append(f"    - Node: {stg.get('node', 'N/A')}")
    else:
        report.append("  No storage found")
    report.append("")

    # Node Status
    node_status = resources.get("node_status", {})
    if node_status:
        report.append("📊 NODE STATUS DETAILS:")
        report.append("-" * 80)
        for node_name, status in node_status.items():
            report.append(f"  {node_name}:")
            report.append(f"    - Status: {status.get('status', 'N/A')}")
            report.append(f"    - Uptime: {status.get('uptime', 'N/A')} seconds")
            report.append(f"    - CPU: {status.get('cpu', 'N/A')}")
            mem_info = status.get("memory", {})
            if isinstance(mem_info, dict):
                report.append(
                    f"    - Memory: {mem_info.get('used', 'N/A')} / {mem_info.get('total', 'N/A')} bytes"
                )
        report.append("")

    report.append("=" * 80)

    return "\n".join(report)


def main():
    """Main function."""
    from dotenv import load_dotenv
    from proxmox_mcp.cluster_manager import get_cluster_registry

    logger.info("Starting Proxmox Resource Listing")
    logger.info("Using: proxmox-mcp-server MCP Server")
    logger.info("")

    # Load environment
    load_dotenv()

    # Get cluster registry
    registry = get_cluster_registry()

    all_results = {}
    clusters = registry.list_clusters()

    logger.info(f"Available clusters: {clusters}")
    logger.info(f"Default cluster: {registry._config.default_cluster}")

    for cluster in clusters:
        cluster_display = cluster
        try:
            logger.info(f"\n{'=' * 80}")
            logger.info(f"Querying Cluster: {cluster_display}")
            logger.info(f"{'=' * 80}")

            resources = list_all_resources_from_cluster(registry, cluster_name=cluster)
            all_results[cluster_display] = resources

            # Print formatted report
            report = format_resources_report(resources, cluster_display)
            print(report)

        except Exception as e:
            logger.error(
                f"Failed to fetch resources from cluster '{cluster_display}': {e}"
            )
            import traceback

            traceback.print_exc()
            continue

    # Save results to JSON
    output_file = Path(__file__).parent / "proxmox_resources_output.json"
    try:
        with open(output_file, "w") as f:
            json.dump(all_results, f, indent=2, default=str)
        logger.info(f"\nResults saved to: {output_file}")
    except Exception as e:
        logger.error(f"Failed to save results: {e}")

    logger.info("\n✅ Proxmox Resource Listing Complete")


if __name__ == "__main__":
    main()
