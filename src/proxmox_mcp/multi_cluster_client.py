"""
Multi-Cluster Client Wrapper

Provides intelligent routing of operations to the appropriate ProxmoxClient
based on cluster selection strategy while maintaining transparent API compatibility.
"""

from __future__ import annotations

import logging
from typing import Optional, Any, Dict, List

from .client import ProxmoxClient
from .cluster_manager import ClusterRegistry, get_cluster_registry

logger = logging.getLogger(__name__)


class MultiClusterProxmoxClient:
    """
    Wrapper that routes operations to the appropriate cluster's ProxmoxClient.

    Provides transparent API compatibility - can be used as a drop-in replacement
    for single ProxmoxClient while supporting multi-cluster operations.

    Cluster selection priority:
    1. Explicit cluster parameter
    2. Resource name pattern matching
    3. Default cluster
    """

    def __init__(self, registry: Optional[ClusterRegistry] = None):
        """
        Initialize multi-cluster client.

        Args:
            registry: ClusterRegistry instance. If None, uses global registry.
        """
        self._registry = registry or get_cluster_registry()
        logger.info(
            f"Initialized MultiClusterProxmoxClient with {len(self._registry.list_clusters())} cluster(s)"
        )

    def _get_client(
        self,
        cluster: Optional[str] = None,
        resource_name: Optional[str] = None,
    ) -> ProxmoxClient:
        """
        Get the appropriate ProxmoxClient for the operation.

        Args:
            cluster: Explicit cluster name
            resource_name: Name of resource for pattern matching

        Returns:
            ProxmoxClient instance
        """
        selected_cluster = self._registry.select_cluster(
            cluster_name=cluster,
            resource_name=resource_name,
        )
        return self._registry.get_client(selected_cluster)

    # -------- Discovery Methods --------

    def list_nodes(self, cluster: Optional[str] = None) -> List[Dict[str, Any]]:
        """List nodes from cluster."""
        client = self._get_client(cluster=cluster)
        return client.list_nodes()

    def get_node_status(
        self, node: str, cluster: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get node status."""
        client = self._get_client(cluster=cluster)
        return client.get_node_status(node)

    def list_vms(
        self,
        node: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        cluster: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List VMs from cluster."""
        client = self._get_client(cluster=cluster)
        return client.list_vms(node=node, status=status, search=search)

    def list_lxc(
        self,
        node: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        cluster: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List LXC containers from cluster."""
        client = self._get_client(cluster=cluster)
        return client.list_lxc(node=node, status=status, search=search)

    def resolve_vm(
        self,
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        cluster: Optional[str] = None,
    ) -> tuple:
        """Resolve VM to (vmid, node, resource)."""
        client = self._get_client(cluster=cluster, resource_name=name)
        return client.resolve_vm(vmid=vmid, name=name, node=node)

    def resolve_lxc(
        self,
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        cluster: Optional[str] = None,
    ) -> tuple:
        """Resolve LXC container to (vmid, node, resource)."""
        client = self._get_client(cluster=cluster, resource_name=name)
        return client.resolve_lxc(vmid=vmid, name=name, node=node)

    def vm_config(
        self,
        node: str,
        vmid: int,
        cluster: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get VM configuration."""
        client = self._get_client(cluster=cluster)
        return client.vm_config(node, vmid)

    def lxc_config(
        self,
        node: str,
        vmid: int,
        cluster: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get LXC configuration."""
        client = self._get_client(cluster=cluster)
        return client.lxc_config(node, vmid)

    def list_storage(self, cluster: Optional[str] = None) -> List[Dict[str, Any]]:
        """List storage from cluster."""
        client = self._get_client(cluster=cluster)
        return client.list_storage()

    def storage_status(
        self,
        node: str,
        storage: str,
        cluster: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get storage status."""
        client = self._get_client(cluster=cluster)
        return client.storage_status(node, storage)

    def storage_content(
        self,
        node: str,
        storage: str,
        cluster: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get storage content."""
        client = self._get_client(cluster=cluster)
        return client.storage_content(node, storage)

    def list_bridges(
        self,
        node: str,
        cluster: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List bridges from node."""
        client = self._get_client(cluster=cluster)
        return client.list_bridges(node)

    def list_tasks(
        self,
        node: Optional[str] = None,
        user: Optional[str] = None,
        limit: int = 50,
        cluster: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List tasks from cluster."""
        client = self._get_client(cluster=cluster)
        return client.list_tasks(node=node, user=user, limit=limit)

    def task_status(
        self,
        upid: str,
        node: Optional[str] = None,
        cluster: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get task status."""
        client = self._get_client(cluster=cluster)
        return client.task_status(upid, node=node)

    # -------- VM Lifecycle Methods --------

    def clone_vm(
        self,
        source_node: str,
        source_vmid: int,
        target_node: Optional[str],
        new_vmid: int,
        name: Optional[str] = None,
        full: bool = True,
        storage: Optional[str] = None,
        cluster: Optional[str] = None,
    ) -> str:
        """Clone VM."""
        client = self._get_client(cluster=cluster)
        return client.clone_vm(
            source_node=source_node,
            source_vmid=source_vmid,
            target_node=target_node,
            new_vmid=new_vmid,
            name=name,
            full=full,
            storage=storage,
        )

    def create_vm(
        self,
        node: str,
        vmid: int,
        name: str,
        cores: int = 2,
        memory_mb: int = 2048,
        disk_gb: int = 20,
        storage: Optional[str] = None,
        bridge: Optional[str] = None,
        iso: Optional[str] = None,
        scsihw: str = "virtio-scsi-pci",
        agent: bool = True,
        ostype: str = "l26",
        cluster: Optional[str] = None,
    ) -> str:
        """Create VM."""
        client = self._get_client(cluster=cluster, resource_name=name)
        return client.create_vm(
            node=node,
            vmid=vmid,
            name=name,
            cores=cores,
            memory_mb=memory_mb,
            disk_gb=disk_gb,
            storage=storage,
            bridge=bridge,
            iso=iso,
            scsihw=scsihw,
            agent=agent,
            ostype=ostype,
        )

    def delete_vm(
        self,
        node: str,
        vmid: int,
        purge: bool = True,
        cluster: Optional[str] = None,
    ) -> str:
        """Delete VM."""
        client = self._get_client(cluster=cluster)
        return client.delete_vm(node, vmid, purge=purge)

    def start_vm(
        self,
        node: str,
        vmid: int,
        cluster: Optional[str] = None,
    ) -> str:
        """Start VM."""
        client = self._get_client(cluster=cluster)
        return client.start_vm(node, vmid)

    def stop_vm(
        self,
        node: str,
        vmid: int,
        overrule_shutdown: bool = False,
        timeout: Optional[int] = None,
        cluster: Optional[str] = None,
        force: Optional[bool] = None,
    ) -> str:
        """Stop VM."""
        client = self._get_client(cluster=cluster)
        return client.stop_vm(
            node,
            vmid,
            overrule_shutdown=overrule_shutdown,
            timeout=timeout,
            force=force,
        )

    def reboot_vm(
        self,
        node: str,
        vmid: int,
        cluster: Optional[str] = None,
    ) -> str:
        """Reboot VM."""
        client = self._get_client(cluster=cluster)
        return client.reboot_vm(node, vmid)

    def shutdown_vm(
        self,
        node: str,
        vmid: int,
        timeout: Optional[int] = None,
        cluster: Optional[str] = None,
    ) -> str:
        """Shutdown VM."""
        client = self._get_client(cluster=cluster)
        return client.shutdown_vm(node, vmid, timeout=timeout)

    def migrate_vm(
        self,
        node: str,
        vmid: int,
        target_node: str,
        online: bool = True,
        cluster: Optional[str] = None,
    ) -> str:
        """Migrate VM."""
        client = self._get_client(cluster=cluster)
        return client.migrate_vm(node, vmid, target_node, online=online)

    def resize_vm_disk(
        self,
        node: str,
        vmid: int,
        disk: str,
        size_gb: int,
        cluster: Optional[str] = None,
    ) -> str:
        """Resize VM disk."""
        client = self._get_client(cluster=cluster)
        return client.resize_vm_disk(node, vmid, disk, size_gb)

    def configure_vm(
        self,
        node: str,
        vmid: int,
        params: Dict[str, Any],
        cluster: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Configure VM."""
        client = self._get_client(cluster=cluster)
        return client.configure_vm(node, vmid, params)

    # -------- LXC Lifecycle Methods --------

    def create_lxc(
        self,
        node: str,
        vmid: int,
        hostname: str,
        ostemplate: str,
        cores: int = 2,
        memory_mb: int = 1024,
        rootfs_gb: int = 8,
        storage: Optional[str] = None,
        bridge: Optional[str] = None,
        net_ip: Optional[str] = None,
        cluster: Optional[str] = None,
    ) -> str:
        """Create LXC container."""
        client = self._get_client(cluster=cluster, resource_name=hostname)
        return client.create_lxc(
            node=node,
            vmid=vmid,
            hostname=hostname,
            ostemplate=ostemplate,
            cores=cores,
            memory_mb=memory_mb,
            rootfs_gb=rootfs_gb,
            storage=storage,
            bridge=bridge,
            net_ip=net_ip,
        )

    def delete_lxc(
        self,
        node: str,
        vmid: int,
        purge: bool = True,
        cluster: Optional[str] = None,
    ) -> str:
        """Delete LXC container."""
        client = self._get_client(cluster=cluster)
        return client.delete_lxc(node, vmid, purge=purge)

    def start_lxc(
        self,
        node: str,
        vmid: int,
        cluster: Optional[str] = None,
    ) -> str:
        """Start LXC container."""
        client = self._get_client(cluster=cluster)
        return client.start_lxc(node, vmid)

    def stop_lxc(
        self,
        node: str,
        vmid: int,
        timeout: Optional[int] = None,
        cluster: Optional[str] = None,
    ) -> str:
        """Stop LXC container."""
        client = self._get_client(cluster=cluster)
        return client.stop_lxc(node, vmid, timeout=timeout)

    def configure_lxc(
        self,
        node: str,
        vmid: int,
        params: Dict[str, Any],
        cluster: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Configure LXC container."""
        client = self._get_client(cluster=cluster)
        return client.configure_lxc(node, vmid, params)

    # -------- Cluster-Specific Methods --------

    def get_registry(self) -> ClusterRegistry:
        """Get the cluster registry."""
        return self._registry

    def list_all_clusters(self) -> List[str]:
        """List all available clusters."""
        return self._registry.list_clusters()

    def get_cluster_info(self, cluster_name: Optional[str] = None) -> Dict:
        """Get information about a cluster."""
        return self._registry.get_cluster_info(cluster_name)

    def list_all_clusters_info(self) -> List[Dict]:
        """Get information about all clusters."""
        return self._registry.list_all_clusters_info()

    def validate_all_clusters(self) -> Dict[str, tuple]:
        """Validate connectivity to all clusters."""
        return self._registry.validate_all_clusters()

    def __repr__(self) -> str:
        return f"MultiClusterProxmoxClient({self._registry})"
