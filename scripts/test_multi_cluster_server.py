#!/usr/bin/env python3
"""
Test multi-cluster MCP server functionality
"""

import sys
import os
from pathlib import Path

# Add src to path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

# Load environment
from dotenv import load_dotenv

load_dotenv()

from proxmox_mcp.utils import is_multi_cluster_mode, load_cluster_registry_config
from proxmox_mcp.cluster_manager import get_cluster_registry
from proxmox_mcp.server import get_client


def test_multi_cluster_detection():
    """Test if multi-cluster mode is detected"""
    print("\n=== Testing Multi-Cluster Detection ===")

    is_multi = is_multi_cluster_mode()
    print(f"Multi-cluster mode: {is_multi}")

    if is_multi:
        print("✅ Multi-cluster mode is ENABLED")
        clusters_env = os.getenv("PROXMOX_CLUSTERS", "")
        print(f"   Configured clusters: {clusters_env}")
    else:
        print("❌ Multi-cluster mode is NOT enabled")
        print("   Using single-cluster mode")

    return is_multi


def test_cluster_registry():
    """Test cluster registry"""
    print("\n=== Testing Cluster Registry ===")

    if not is_multi_cluster_mode():
        print("⏭️  Skipping (single-cluster mode)")
        return

    try:
        config = load_cluster_registry_config()
        print(f"Loaded registry config:")
        print(f"  - Clusters: {list(config.clusters.keys())}")
        print(f"  - Default cluster: {config.default_cluster}")

        registry = get_cluster_registry()
        clusters = registry.list_clusters()
        print(f"\nRegistry clusters: {clusters}")

        for cluster_name in clusters:
            cluster_config = registry.get_cluster_config(cluster_name)
            print(f"\n{cluster_name}:")
            print(f"  - URL: {cluster_config.base_url}")
            print(f"  - Token ID: {cluster_config.token_id}")
            print(f"  - Default Node: {cluster_config.default_node}")
            print(f"  - Tier: {cluster_config.tier}")
            print(f"  - Region: {cluster_config.region}")

        print("\n✅ Cluster registry working correctly")
        return True
    except Exception as e:
        print(f"\n❌ Error with cluster registry: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_get_client():
    """Test getting clients"""
    print("\n=== Testing get_client() ===")

    try:
        # Test default client
        print("\n1. Getting default client...")
        client = get_client()
        print(f"   ✅ Got client: {client}")
        print(
            f"      Base URL: {client._api._base_url if hasattr(client._api, '_base_url') else 'N/A'}"
        )
        print(f"      Default node: {client.default_node}")

        # Test cluster-specific clients (if multi-cluster)
        if is_multi_cluster_mode():
            registry = get_cluster_registry()
            clusters = registry.list_clusters()

            for cluster_name in clusters:
                print(f"\n2. Getting client for '{cluster_name}'...")
                client = get_client(cluster_name)
                print(f"   ✅ Got client for {cluster_name}")
                print(f"      Default node: {client.default_node}")

        print("\n✅ get_client() working correctly")
        return True
    except Exception as e:
        print(f"\n❌ Error with get_client(): {e}")
        import traceback

        traceback.print_exc()
        return False


def test_cluster_connectivity():
    """Test actual connectivity to clusters"""
    print("\n=== Testing Cluster Connectivity ===")

    if not is_multi_cluster_mode():
        print("⏭️  Skipping (single-cluster mode)")
        try:
            client = get_client()
            nodes = client.list_nodes()
            print(f"✅ Single cluster: {len(nodes)} node(s) found")
            for node in nodes:
                print(
                    f"   - {node.get('node', 'unknown')}: {node.get('status', 'unknown')}"
                )
            return True
        except Exception as e:
            print(f"❌ Error connecting to single cluster: {e}")
            return False

    try:
        registry = get_cluster_registry()
        results = registry.validate_all_clusters()

        print("\nCluster connectivity:")
        all_ok = True
        for cluster_name, (is_valid, message) in results.items():
            status = "✅" if is_valid else "❌"
            print(f"  {status} {cluster_name}: {message}")
            if not is_valid:
                all_ok = False

        if all_ok:
            print("\n✅ All clusters are accessible")
        else:
            print("\n⚠️  Some clusters are not accessible")

        # Try to list nodes from each cluster
        print("\n Listing nodes from each cluster:")
        for cluster_name in registry.list_clusters():
            try:
                client = get_client(cluster_name)
                nodes = client.list_nodes()
                print(f"\n  {cluster_name}: {len(nodes)} node(s)")
                for node in nodes:
                    print(
                        f"    - {node.get('node', 'unknown')}: {node.get('status', 'unknown')}"
                    )
            except Exception as e:
                print(f"\n  ❌ {cluster_name}: Error - {e}")

        return all_ok
    except Exception as e:
        print(f"\n❌ Error testing connectivity: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    print("=" * 80)
    print("Multi-Cluster Proxmox MCP Server Test")
    print("=" * 80)

    # Run tests
    tests_passed = 0
    tests_total = 4

    if test_multi_cluster_detection():
        tests_passed += 1

    if test_cluster_registry():
        tests_passed += 1

    if test_get_client():
        tests_passed += 1

    if test_cluster_connectivity():
        tests_passed += 1

    # Summary
    print("\n" + "=" * 80)
    print(f"Test Summary: {tests_passed}/{tests_total} passed")
    print("=" * 80)

    if tests_passed == tests_total:
        print("\n🎉 All tests passed! Multi-cluster support is working correctly.")
        return 0
    else:
        print(f"\n⚠️  {tests_total - tests_passed} test(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
