#!/usr/bin/env python3
# ruff: noqa: E402

"""
Test the new multi-cluster aggregation tools
"""

import sys
import asyncio
from pathlib import Path

# Add src to path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

# Load environment
from dotenv import load_dotenv

load_dotenv()

# Import the new tools
from proxmox_mcp.server import (
    proxmox_list_all_clusters,
    proxmox_list_all_nodes_from_all_clusters,
    proxmox_list_all_vms_from_all_clusters,
    proxmox_get_all_cluster_status,
)


async def test_list_clusters():
    """Test listing all clusters"""
    print("\n=== Test: proxmox-list-all-clusters ===")
    try:
        clusters = await proxmox_list_all_clusters()
        print(f"✅ Found {len(clusters)} cluster(s): {clusters}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


async def test_list_all_nodes():
    """Test listing nodes from all clusters"""
    print("\n=== Test: proxmox-list-all-nodes-from-all-clusters ===")
    try:
        result = await proxmox_list_all_nodes_from_all_clusters()
        print(f"✅ Got nodes from {len(result)} cluster(s):\n")

        for cluster_name, nodes in result.items():
            if isinstance(nodes, dict) and "error" in nodes:
                print(f"  ❌ {cluster_name}: {nodes['error']}")
            else:
                print(f"  ✅ {cluster_name}: {len(nodes)} node(s)")
                for node in nodes:
                    print(
                        f"     - {node.get('node', 'unknown')}: {node.get('status', 'unknown')}"
                    )

        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_list_all_vms():
    """Test listing VMs from all clusters"""
    print("\n=== Test: proxmox-list-all-vms-from-all-clusters ===")
    try:
        result = await proxmox_list_all_vms_from_all_clusters()
        print(f"✅ Got VMs from {len(result)} cluster(s):\n")

        for cluster_name, vms in result.items():
            if isinstance(vms, dict) and "error" in vms:
                print(f"  ❌ {cluster_name}: {vms['error']}")
            else:
                running = len([vm for vm in vms if vm.get("status") == "running"])
                stopped = len([vm for vm in vms if vm.get("status") == "stopped"])
                print(
                    f"  ✅ {cluster_name}: {len(vms)} VMs ({running} running, {stopped} stopped)"
                )

        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_get_all_status():
    """Test getting comprehensive status"""
    print("\n=== Test: proxmox-get-all-cluster-status ===")
    try:
        result = await proxmox_get_all_cluster_status()
        print(f"✅ Got status from {len(result)} cluster(s):\n")

        for cluster_name, status in result.items():
            if status.get("status") == "error":
                print(f"  ❌ {cluster_name}: {status.get('message', 'Unknown error')}")
            else:
                print(f"  ✅ {cluster_name}:")
                print(f"     - Status: {status.get('status', 'unknown')}")
                print(f"     - Nodes: {status.get('nodes_count', 0)}")
                print(
                    f"     - VMs: {status.get('vms_total', 0)} ({status.get('vms_running', 0)} running)"
                )
                print(f"     - Storage: {status.get('storage_count', 0)}")

                if "cluster_info" in status:
                    info = status["cluster_info"]
                    print(f"     - URL: {info.get('api_url', 'N/A')}")
                    print(f"     - Tier: {info.get('tier', 'N/A')}")

        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    print("=" * 80)
    print("Testing New Multi-Cluster Aggregation Tools")
    print("=" * 80)

    tests_passed = 0
    tests_total = 4

    if await test_list_clusters():
        tests_passed += 1

    if await test_list_all_nodes():
        tests_passed += 1

    if await test_list_all_vms():
        tests_passed += 1

    if await test_get_all_status():
        tests_passed += 1

    print("\n" + "=" * 80)
    print(f"Test Summary: {tests_passed}/{tests_total} passed")
    print("=" * 80)

    if tests_passed == tests_total:
        print("\n🎉 All new tools work perfectly!")
        print("\nYou can now use these tools in Claude/Cursor:")
        print("  - proxmox-list-all-clusters")
        print("  - proxmox-list-all-nodes-from-all-clusters")
        print("  - proxmox-list-all-vms-from-all-clusters")
        print("  - proxmox-get-all-cluster-status")
        return 0
    else:
        print(f"\n⚠️  {tests_total - tests_passed} test(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
