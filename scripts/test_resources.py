#!/usr/bin/env python3
# ruff: noqa: E402

"""Test script to list resources from both Production and Staging clusters."""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from proxmox_mcp.cluster_manager import get_cluster_registry
from proxmox_mcp.utils import is_multi_cluster_mode


async def main():
    """List resources from both clusters."""

    print("=" * 80)
    print("PROXMOX MCP - MULTI-CLUSTER RESOURCES")
    print("=" * 80)

    # Check if multi-cluster mode is enabled
    multi_cluster_enabled = is_multi_cluster_mode()
    print(f"\n✓ Multi-Cluster Mode Enabled: {multi_cluster_enabled}\n")

    # Get cluster registry
    registry = get_cluster_registry()

    # List all clusters
    print("Configured Clusters:")
    print("-" * 80)
    cluster_names = registry.list_clusters()
    for cluster_name in cluster_names:
        cluster_config = registry.get_cluster_config(cluster_name)
        print(f"  • {cluster_name.upper()}")
        print(f"    - API URL: {cluster_config.base_url}")
        print(f"    - Token ID: {cluster_config.token_id}")
        print(f"    - Tier: {cluster_config.tier or 'N/A'}")
        print(f"    - Region: {cluster_config.region or 'N/A'}")
        print()

    # Get resources from each cluster
    print("\n" + "=" * 80)
    print("CLUSTER RESOURCES")
    print("=" * 80)

    for cluster_name in cluster_names:
        cluster_display_name = cluster_name.upper()
        print(f"\n{cluster_display_name} CLUSTER RESOURCES")
        print("-" * 80)

        try:
            client = registry.get_client(cluster_name)

            # List nodes
            print(f"\n📍 Nodes in {cluster_display_name}:")
            nodes = client.list_nodes()
            for node in nodes:
                node_name = node.get("node", "N/A")
                node_status = node.get("status", "N/A")
                uptime = node.get("uptime", 0)
                cpu_usage = node.get("cpu", 0) * 100
                memory_max_gb = node.get("maxmem", 0) / (1024**3)
                memory_used_gb = node.get("mem", 0) / (1024**3)
                print(f"  ✓ {node_name}")
                print(f"    - Status: {node_status}")
                print(f"    - CPU Usage: {cpu_usage:.2f}%")
                print(f"    - Memory: {memory_used_gb:.2f} GB / {memory_max_gb:.2f} GB")
                print(f"    - Uptime: {uptime} seconds")

            # List VMs
            print(f"\n🖥️  Virtual Machines in {cluster_display_name}:")
            vms = client.list_vms()
            if vms:
                for vm in vms:
                    vm_name = vm.get("name", "N/A")
                    vm_status = vm.get("status", "N/A")
                    vmid = vm.get("vmid", "N/A")
                    cpu_cores = vm.get("cpus", 0)
                    memory_mb = vm.get("maxmem", 0) / (1024**2)
                    print(f"  ✓ {vm_name} (ID: {vmid})")
                    print(f"    - Status: {vm_status}")
                    print(f"    - CPU Cores: {cpu_cores}")
                    print(f"    - Memory: {memory_mb:.2f} MB")
            else:
                print("  (No VMs found)")

            # List LXC Containers
            print(f"\n📦 LXC Containers in {cluster_display_name}:")
            containers = client.list_lxc()
            if containers:
                for container in containers:
                    ct_name = container.get("name", "N/A")
                    ct_status = container.get("status", "N/A")
                    vmid = container.get("vmid", "N/A")
                    cpu_cores = container.get("cpus", 0)
                    memory_mb = container.get("maxmem", 0) / (1024**2)
                    print(f"  ✓ {ct_name} (ID: {vmid})")
                    print(f"    - Status: {ct_status}")
                    print(f"    - CPU Cores: {cpu_cores}")
                    print(f"    - Memory: {memory_mb:.2f} MB")
            else:
                print("  (No containers found)")

            # List Storage
            print(f"\n💾 Storage in {cluster_display_name}:")
            storage = client.list_storage()
            if storage:
                for store in storage:
                    store_id = store.get("storage", "N/A")
                    store_type = store.get("type", "N/A")
                    content_types = store.get("content", "N/A")
                    enabled = store.get("enabled", 1)
                    print(f"  ✓ {store_id} ({store_type})")
                    print(f"    - Content Types: {content_types}")
                    print(f"    - Enabled: {'Yes' if enabled else 'No'}")
            else:
                print("  (No storage found)")

        except Exception as e:
            print(f"  ❌ Error accessing {cluster_display_name}: {e}")

    print("\n" + "=" * 80)
    print("✓ Resource listing completed")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
