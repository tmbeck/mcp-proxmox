"""
Cluster Manager for Multi-Cluster Proxmox Support

Manages multiple Proxmox cluster configurations, intelligent cluster selection,
and caching of ProxmoxClient instances.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple

from .utils import (
    ClusterConfig,
    ClusterRegistryConfig,
    load_cluster_registry_config,
    is_multi_cluster_mode,
)
from .client import ProxmoxClient

logger = logging.getLogger(__name__)


class ClusterError(Exception):
    """Base exception for cluster-related errors."""

    pass


class ClusterNotFoundError(ClusterError):
    """Raised when a cluster is not found in the registry."""

    def __init__(self, cluster_name: str):
        super().__init__(f"Cluster not found: {cluster_name}")


class ClusterConnectionError(ClusterError):
    """Raised when unable to connect to a cluster."""

    def __init__(self, cluster_name: str, reason: str):
        super().__init__(f"Cannot connect to cluster '{cluster_name}': {reason}")


class AmbiguousClusterSelectionError(ClusterError):
    """Raised when cluster selection is ambiguous."""

    def __init__(self, resource_name: str, candidates: List[str]):
        super().__init__(
            f"Ambiguous cluster selection for '{resource_name}'. "
            f"Candidates: {', '.join(candidates)}. Please specify cluster explicitly."
        )


class ClusterRegistry:
    """
    Central registry for managing multiple Proxmox clusters.

    Features:
    - Load cluster configurations from environment
    - Cache ProxmoxClient instances
    - Intelligent cluster selection based on patterns
    - Cluster validation and health checks
    """

    def __init__(self, config: Optional[ClusterRegistryConfig] = None):
        """
        Initialize cluster registry.

        Args:
            config: ClusterRegistryConfig instance. If None, loads from environment.
        """
        self._config = config or load_cluster_registry_config()
        self._clients: Dict[str, ProxmoxClient] = {}  # Cache of ProxmoxClient instances
        self._client_timestamps: Dict[str, float] = {}  # Timestamp of client creation
        self._is_multi_cluster = is_multi_cluster_mode()

        logger.info(
            f"Initialized ClusterRegistry with {len(self._config.clusters)} cluster(s). "
            f"Default: {self._config.default_cluster}. "
            f"Multi-cluster mode: {self._is_multi_cluster}"
        )

    def get_config(self) -> ClusterRegistryConfig:
        """Get the registry configuration."""
        return self._config

    def list_clusters(self) -> List[str]:
        """List all available cluster names."""
        return list(self._config.clusters.keys())

    def get_cluster_config(self, cluster_name: str) -> ClusterConfig:
        """
        Get configuration for a specific cluster.

        Args:
            cluster_name: Name of the cluster

        Returns:
            ClusterConfig instance

        Raises:
            ClusterNotFoundError: If cluster not found
        """
        if cluster_name not in self._config.clusters:
            raise ClusterNotFoundError(cluster_name)
        return self._config.clusters[cluster_name]

    def get_client(self, cluster_name: Optional[str] = None) -> ProxmoxClient:
        """
        Get or create a ProxmoxClient for a cluster.

        Args:
            cluster_name: Name of the cluster. If None, uses default.

        Returns:
            ProxmoxClient instance

        Raises:
            ClusterNotFoundError: If cluster not found
        """
        target_cluster = cluster_name or self._config.default_cluster

        if target_cluster not in self._config.clusters:
            raise ClusterNotFoundError(target_cluster)

        # Check cache and TTL
        if target_cluster in self._clients:
            age = time.time() - self._client_timestamps.get(target_cluster, 0)
            if age < self._config.cache_ttl:
                logger.debug(f"Using cached client for cluster '{target_cluster}'")
                return self._clients[target_cluster]
            else:
                logger.debug(f"Client cache expired for cluster '{target_cluster}'")
                del self._clients[target_cluster]
                del self._client_timestamps[target_cluster]

        # Create new client
        cluster_config = self._config.clusters[target_cluster]
        try:
            client = ProxmoxClient(
                base_url=cluster_config.base_url,
                token_id=cluster_config.token_id,
                token_secret=cluster_config.token_secret,
                verify=cluster_config.verify,
                default_node=cluster_config.default_node,
                default_storage=cluster_config.default_storage,
                default_bridge=cluster_config.default_bridge,
            )

            self._clients[target_cluster] = client
            self._client_timestamps[target_cluster] = time.time()

            logger.info(f"Created new ProxmoxClient for cluster '{target_cluster}'")
            return client

        except Exception as e:
            logger.error(f"Failed to create client for cluster '{target_cluster}': {e}")
            raise ClusterConnectionError(target_cluster, str(e))

    def select_cluster(
        self,
        cluster_name: Optional[str] = None,
        resource_name: Optional[str] = None,
        vmid: Optional[int] = None,
    ) -> str:
        """
        Intelligently select a cluster based on priority order.

        Priority:
        1. Explicit cluster_name parameter
        2. Pattern matching on resource_name
        3. VMId mapping (if available)
        4. Default cluster

        Args:
            cluster_name: Explicit cluster name
            resource_name: Name of resource (VM/container)
            vmid: VM/Container ID

        Returns:
            Selected cluster name

        Raises:
            ClusterNotFoundError: If no cluster can be selected
            AmbiguousClusterSelectionError: If selection is ambiguous
        """
        # Priority 1: Explicit cluster name
        if cluster_name:
            if cluster_name not in self._config.clusters:
                raise ClusterNotFoundError(cluster_name)
            logger.debug(f"Cluster selected explicitly: {cluster_name}")
            return cluster_name

        # Priority 2: Pattern matching on resource name
        if resource_name:
            matched_clusters = self._match_resource_to_clusters(resource_name)

            if len(matched_clusters) == 1:
                logger.debug(
                    f"Cluster selected by resource name pattern: {matched_clusters[0]}"
                )
                return matched_clusters[0]
            elif len(matched_clusters) > 1:
                raise AmbiguousClusterSelectionError(resource_name, matched_clusters)

        # Priority 4: Default cluster
        logger.debug(f"Using default cluster: {self._config.default_cluster}")
        return self._config.default_cluster

    def _match_resource_to_clusters(self, resource_name: str) -> List[str]:
        """
        Match resource name to clusters using configured patterns.

        Args:
            resource_name: Name of the resource

        Returns:
            List of matching cluster names
        """
        matched = []

        # Try configured patterns first
        for pattern, cluster_name in self._config.cluster_patterns.items():
            if resource_name.startswith(pattern):
                matched.append(cluster_name)

        if matched:
            return list(set(matched))  # Remove duplicates

        # Try naming convention: {cluster_name}-{resource_type}-{identifier}
        # Example: prod-vm-web01 -> prod -> cluster named 'prod'
        parts = resource_name.split("-")
        if parts:
            potential_cluster = parts[0]
            if potential_cluster in self._config.clusters:
                matched.append(potential_cluster)

        return matched

    def validate_all_clusters(self) -> Dict[str, Tuple[bool, str]]:
        """
        Validate connectivity to all clusters.

        Returns:
            Dict mapping cluster names to (is_valid, message) tuples
        """
        results = {}

        for cluster_name in self._config.clusters:
            try:
                client = self.get_client(cluster_name)
                # Try a simple API call
                nodes = client.list_nodes()
                results[cluster_name] = (True, f"OK ({len(nodes)} nodes)")
                logger.info(f"Cluster '{cluster_name}' is healthy")
            except Exception as e:
                results[cluster_name] = (False, str(e))
                logger.warning(f"Cluster '{cluster_name}' validation failed: {e}")

        return results

    def get_cluster_info(self, cluster_name: Optional[str] = None) -> Dict:
        """
        Get detailed information about a cluster.

        Args:
            cluster_name: Cluster name. If None, uses default.

        Returns:
            Dict with cluster information
        """
        target_cluster = cluster_name or self._config.default_cluster
        config = self.get_cluster_config(target_cluster)

        try:
            client = self.get_client(target_cluster)
            nodes = client.list_nodes()
            vms = client.list_vms()
            lxcs = client.list_lxc()
            storages = client.list_storage()

            return {
                "cluster_name": target_cluster,
                "api_url": config.base_url,
                "region": config.region,
                "tier": config.tier,
                "nodes_count": len(nodes),
                "vms_count": len(vms),
                "lxc_count": len(lxcs),
                "storage_count": len(storages),
                "nodes": [
                    {"name": n.get("node"), "status": n.get("status")} for n in nodes
                ],
                "status": "online",
            }
        except Exception as e:
            logger.error(f"Failed to get cluster info for '{target_cluster}': {e}")
            return {
                "cluster_name": target_cluster,
                "api_url": config.base_url,
                "region": config.region,
                "tier": config.tier,
                "status": "offline",
                "error": str(e),
            }

    def list_all_clusters_info(self) -> List[Dict]:
        """
        Get information about all clusters.

        Returns:
            List of cluster information dicts
        """
        results = []
        for cluster_name in self.list_clusters():
            info = self.get_cluster_info(cluster_name)
            results.append(info)
        return results

    def clear_cache(self, cluster_name: Optional[str] = None) -> None:
        """
        Clear cached client(s).

        Args:
            cluster_name: Specific cluster to clear. If None, clears all.
        """
        if cluster_name:
            if cluster_name in self._clients:
                del self._clients[cluster_name]
                del self._client_timestamps[cluster_name]
                logger.info(f"Cleared cache for cluster '{cluster_name}'")
        else:
            self._clients.clear()
            self._client_timestamps.clear()
            logger.info("Cleared cache for all clusters")

    def __repr__(self) -> str:
        clusters_info = ", ".join(
            [
                f"{name}({'default' if name == self._config.default_cluster else 'secondary'})"
                for name in self.list_clusters()
            ]
        )
        return f"ClusterRegistry({clusters_info})"


# Global registry instance
_global_registry: Optional[ClusterRegistry] = None


def get_cluster_registry() -> ClusterRegistry:
    """Get or create the global cluster registry."""
    global _global_registry

    if _global_registry is None:
        _global_registry = ClusterRegistry()

    return _global_registry


def reset_cluster_registry() -> None:
    """Reset the global cluster registry (for testing)."""
    global _global_registry
    _global_registry = None
