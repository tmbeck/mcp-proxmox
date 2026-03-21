from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP


def _primary_manager_vm(client: Any, cluster_name: str) -> Dict[str, Any]:
    cluster_vms = client.get_cluster_vms(cluster_name)
    manager_vms = [vm for vm in cluster_vms if "manager" in vm.get("name", "").lower()]
    if not manager_vms:
        raise ValueError(f"No manager nodes found in cluster: {cluster_name}")
    return manager_vms[0]


def register_automation_tools(
    server: FastMCP,
    get_client: Callable[[], Any],
    require_confirm: Callable[[Optional[bool]], None],
    get_openshift_installer: Callable[[Any], Any],
    get_docker_swarm_symbols: Callable[[], Dict[str, Any]],
    get_infrastructure_manager: Callable[[Any], Any],
    get_network_manager: Callable[[Any], Any],
    get_storage_manager: Callable[[Any], Any],
) -> None:
    @server.tool("proxmox-deploy-openshift-cluster")
    async def proxmox_deploy_openshift_cluster(
        cluster_name: str,
        base_domain: str,
        ssh_key: str,
        pull_secret: Dict[str, Any],
        topology: str = "three-master",
        node: Optional[str] = None,
        storage: Optional[str] = None,
        bridge: Optional[str] = None,
        rhcos_version: str = "4.14",
        base_vmid: int = 500,
        confirm: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Deploy complete OpenShift cluster (bootstrap + masters + workers)."""
        client = get_client()
        node_id = node or client.default_node
        storage_id = storage or client.default_storage
        bridge_id = bridge or client.default_bridge

        if not node_id or not storage_id or not bridge_id:
            raise ValueError("node, storage, and bridge are required (or set defaults)")

        require_confirm(confirm)

        if topology not in ["three-master", "production"]:
            raise ValueError(
                f"Unsupported topology: {topology}. Supported: three-master, production"
            )

        if topology == "three-master":
            master_count = 3
            worker_count = 0
        else:
            master_count = 3
            worker_count = 3

        cluster_config = {
            "cluster_name": cluster_name,
            "base_domain": base_domain,
            "ssh_key": ssh_key,
            "pull_secret": pull_secret,
            "rhcos_version": rhcos_version,
            "master_count": master_count,
            "worker_count": worker_count,
        }

        if dry_run:
            return {
                "dry_run": True,
                "action": "deploy-openshift-cluster",
                "params": {
                    "cluster_config": cluster_config,
                    "node": node_id,
                    "storage": storage_id,
                    "bridge": bridge_id,
                    "base_vmid": base_vmid,
                    "topology": topology,
                },
            }

        installer = get_openshift_installer(client)
        deployment_result = installer.deploy_cluster(
            cluster_config, node_id, storage_id, bridge_id, base_vmid
        )
        deployment_result.update(
            {
                "topology": topology,
                "console_url": f"https://console-openshift-console.apps.{cluster_name}.{base_domain}",
                "api_url": f"https://api.{cluster_name}.{base_domain}:6443",
                "kubeconfig_note": "Run 'oc get kubeconfig' after cluster bootstrap completes",
            }
        )
        return deployment_result

    @server.tool("proxmox-deploy-openshift-sno")
    async def proxmox_deploy_openshift_sno(
        cluster_name: str,
        base_domain: str,
        ssh_key: str,
        pull_secret: Dict[str, Any],
        node: Optional[str] = None,
        storage: Optional[str] = None,
        bridge: Optional[str] = None,
        rhcos_version: str = "4.14",
        vmid: int = 600,
        confirm: Optional[bool] = None,
        dry_run: bool = False,
        wait: bool = False,
        timeout: int = 1800,
        poll_interval: float = 5.0,
    ) -> Dict[str, Any]:
        """Deploy OpenShift Single Node Openshift (SNO) cluster."""
        client = get_client()
        node_id = node or client.default_node
        storage_id = storage or client.default_storage
        bridge_id = bridge or client.default_bridge

        if not node_id or not storage_id or not bridge_id:
            raise ValueError("node, storage, and bridge are required (or set defaults)")

        require_confirm(confirm)

        cluster_config = {
            "cluster_name": cluster_name,
            "base_domain": base_domain,
            "ssh_key": ssh_key,
            "pull_secret": pull_secret,
            "rhcos_version": rhcos_version,
        }

        if dry_run:
            return {
                "dry_run": True,
                "action": "deploy-openshift-sno",
                "params": {
                    "cluster_config": cluster_config,
                    "node": node_id,
                    "storage": storage_id,
                    "bridge": bridge_id,
                    "vmid": vmid,
                },
            }

        installer = get_openshift_installer(client)
        deployment_result = installer.deploy_single_node_cluster(
            cluster_config, node_id, storage_id, bridge_id, vmid
        )

        result: Dict[str, Any] = deployment_result
        if wait:
            status = client.wait_task(
                deployment_result["upid"],
                node=node_id,
                timeout=timeout,
                poll_interval=poll_interval,
            )
            result["status"] = status

        return result

    @server.tool("proxmox-openshift-cluster-status")
    async def proxmox_openshift_cluster_status(cluster_name: str) -> Dict[str, Any]:
        """Get OpenShift cluster status and health information."""
        client = get_client()
        cluster_vms = client.get_cluster_vms(cluster_name)
        if not cluster_vms:
            raise ValueError(f"No VMs found for cluster: {cluster_name}")

        bootstrap_vms = [vm for vm in cluster_vms if "bootstrap" in vm.get("name", "")]
        master_vms = [vm for vm in cluster_vms if "master" in vm.get("name", "")]
        worker_vms = [vm for vm in cluster_vms if "worker" in vm.get("name", "")]
        sno_vms = [vm for vm in cluster_vms if "sno" in vm.get("name", "")]

        if sno_vms:
            cluster_type = "single-node"
            total_nodes = 1
        else:
            cluster_type = "multi-node"
            total_nodes = len(master_vms) + len(worker_vms)

        running_vms = [vm for vm in cluster_vms if vm.get("status") == "running"]
        stopped_vms = [vm for vm in cluster_vms if vm.get("status") == "stopped"]

        if len(running_vms) == len(cluster_vms):
            overall_status = "healthy"
        elif len(running_vms) > len(cluster_vms) / 2:
            overall_status = "degraded"
        else:
            overall_status = "critical"

        return {
            "cluster_name": cluster_name,
            "cluster_type": cluster_type,
            "overall_status": overall_status,
            "total_nodes": total_nodes,
            "running_nodes": len(running_vms),
            "stopped_nodes": len(stopped_vms),
            "node_details": {
                "bootstrap": [
                    {"vmid": vm["vmid"], "name": vm["name"], "status": vm["status"]}
                    for vm in bootstrap_vms
                ],
                "masters": [
                    {"vmid": vm["vmid"], "name": vm["name"], "status": vm["status"]}
                    for vm in master_vms
                ],
                "workers": [
                    {"vmid": vm["vmid"], "name": vm["name"], "status": vm["status"]}
                    for vm in worker_vms
                ],
                "sno": [
                    {"vmid": vm["vmid"], "name": vm["name"], "status": vm["status"]}
                    for vm in sno_vms
                ],
            },
            "console_url": f"https://console-openshift-console.apps.{cluster_name}.example.com",
            "api_url": f"https://api.{cluster_name}.example.com:6443",
        }

    @server.tool("proxmox-create-docker-swarm")
    async def proxmox_create_docker_swarm(
        cluster_name: str,
        manager_count: int = 1,
        worker_count: int = 2,
        base_os: str = "ubuntu-22.04",
        ssh_keys: Optional[List[str]] = None,
        node: Optional[str] = None,
        storage: Optional[str] = None,
        bridge: Optional[str] = None,
        base_vmid: int = 800,
        confirm: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Create Docker Swarm cluster with manager and worker nodes."""
        client = get_client()
        node_id = node or client.default_node
        storage_id = storage or client.default_storage
        bridge_id = bridge or client.default_bridge

        if not node_id or not storage_id or not bridge_id:
            raise ValueError("node, storage, and bridge are required (or set defaults)")
        ssh_keys = ssh_keys or []
        if not ssh_keys:
            raise ValueError("ssh_keys are required for Docker Swarm nodes")

        require_confirm(confirm)

        if dry_run:
            return {
                "dry_run": True,
                "action": "create-docker-swarm",
                "params": {
                    "cluster_name": cluster_name,
                    "manager_count": manager_count,
                    "worker_count": worker_count,
                    "base_os": base_os,
                    "node": node_id,
                    "storage": storage_id,
                    "bridge": bridge_id,
                    "base_vmid": base_vmid,
                    "ssh_keys_count": len(ssh_keys),
                },
            }

        docker_swarm = get_docker_swarm_symbols()
        swarm_config = docker_swarm["DockerSwarmConfig"](cluster_name, base_os)
        for i in range(manager_count):
            swarm_config.add_node(
                f"manager-{i}",
                "manager",
                base_vmid + i,
                cores=2,
                memory_mb=2048,
                disk_gb=30,
            )
        for i in range(worker_count):
            swarm_config.add_node(
                f"worker-{i}",
                "worker",
                base_vmid + manager_count + i,
                cores=2,
                memory_mb=4096,
                disk_gb=30,
            )

        provisioner = docker_swarm["DockerSwarmProvisioner"](client)
        return provisioner.create_swarm_cluster(
            swarm_config, node_id, storage_id, bridge_id, ssh_keys, base_vmid
        )

    @server.tool("proxmox-create-docker-swarm-preset")
    async def proxmox_create_docker_swarm_preset(
        preset: str,
        cluster_name: str,
        ssh_keys: Optional[List[str]] = None,
        node: Optional[str] = None,
        storage: Optional[str] = None,
        bridge: Optional[str] = None,
        base_vmid: int = 800,
        confirm: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Create Docker Swarm cluster with preset configurations."""
        client = get_client()
        node_id = node or client.default_node
        storage_id = storage or client.default_storage
        bridge_id = bridge or client.default_bridge

        if not node_id or not storage_id or not bridge_id:
            raise ValueError("node, storage, and bridge are required (or set defaults)")
        ssh_keys = ssh_keys or []
        if not ssh_keys:
            raise ValueError("ssh_keys are required for Docker Swarm nodes")

        require_confirm(confirm)

        docker_swarm = get_docker_swarm_symbols()
        preset_configs = {
            "web": docker_swarm["get_web_cluster_config"],
            "development": docker_swarm["get_development_cluster_config"],
            "production": docker_swarm["get_production_cluster_config"],
        }
        if preset not in preset_configs:
            raise ValueError(
                f"Unsupported preset: {preset}. Supported: {list(preset_configs.keys())}"
            )

        if dry_run:
            return {
                "dry_run": True,
                "action": "create-docker-swarm-preset",
                "params": {
                    "preset": preset,
                    "cluster_name": cluster_name,
                    "node": node_id,
                    "storage": storage_id,
                    "bridge": bridge_id,
                    "base_vmid": base_vmid,
                    "ssh_keys_count": len(ssh_keys),
                },
            }

        config_factory = preset_configs[preset]
        if preset == "web":
            swarm_config = config_factory(cluster_name, 1, 2)
        else:
            swarm_config = config_factory(cluster_name)

        provisioner = docker_swarm["DockerSwarmProvisioner"](client)
        deployment_result = provisioner.create_swarm_cluster(
            swarm_config, node_id, storage_id, bridge_id, ssh_keys, base_vmid
        )
        deployment_result.update(
            {
                "preset": preset,
                "services": [
                    service["name"] for service in swarm_config.config["services"]
                ],
                "networks": [
                    network["name"] for network in swarm_config.config["networks"]
                ],
            }
        )
        return deployment_result

    @server.tool("proxmox-docker-swarm-init")
    async def proxmox_docker_swarm_init(
        cluster_name: str,
        manager_vmid: Optional[int] = None,
        manager_name: Optional[str] = None,
        manager_node: Optional[str] = None,
        advertise_ip: str = "",
        confirm: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Initialize Docker Swarm on primary manager node."""
        client = get_client()
        if manager_vmid or manager_name:
            vm_vmid, vm_node, _ = client.resolve_vm(
                vmid=manager_vmid, name=manager_name, node=manager_node
            )
        else:
            manager_vm = _primary_manager_vm(client, cluster_name)
            vm_vmid = manager_vm["vmid"]
            vm_node = manager_vm["node"]

        if not advertise_ip:
            raise ValueError("advertise_ip is required for swarm initialization")

        require_confirm(confirm)
        result = client.initialize_docker_swarm(vm_node, vm_vmid, advertise_ip)
        if result.get("success"):
            result.update(client.get_swarm_join_tokens(vm_node, vm_vmid))
        return result

    @server.tool("proxmox-docker-swarm-join")
    async def proxmox_docker_swarm_join(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        role: str = "worker",
        manager_ip: str = "",
        token: str = "",
        confirm: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Join node to existing Docker Swarm cluster."""
        client = get_client()
        vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)

        if not manager_ip or not token:
            raise ValueError("manager_ip and token are required")
        if role not in ["manager", "worker"]:
            raise ValueError("role must be 'manager' or 'worker'")

        require_confirm(confirm)
        result = client.join_docker_swarm(vm_node, vm_vmid, manager_ip, token)
        result.update({"role": role, "manager_ip": manager_ip})
        return result

    @server.tool("proxmox-docker-swarm-status")
    async def proxmox_docker_swarm_status(cluster_name: str) -> Dict[str, Any]:
        """Get Docker Swarm cluster status and information."""
        client = get_client()
        return client.get_swarm_cluster_info(cluster_name)

    @server.tool("proxmox-docker-service-create")
    async def proxmox_docker_service_create(
        cluster_name: str,
        service_name: str,
        image: str,
        replicas: int = 1,
        ports: Optional[List[str]] = None,
        environment: Optional[Dict[str, str]] = None,
        networks: Optional[List[str]] = None,
        constraints: Optional[List[str]] = None,
        confirm: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Create Docker Swarm service."""
        client = get_client()
        manager_vm = _primary_manager_vm(client, cluster_name)
        require_confirm(confirm)
        result = client.create_docker_service(
            manager_vm["node"],
            manager_vm["vmid"],
            service_name,
            image,
            replicas,
            ports,
            environment,
            networks,
            constraints,
        )
        result.update(
            {
                "cluster_name": cluster_name,
                "service_name": service_name,
                "image": image,
                "replicas": replicas,
            }
        )
        return result

    @server.tool("proxmox-docker-service-scale")
    async def proxmox_docker_service_scale(
        cluster_name: str,
        service_name: str,
        replicas: int,
        confirm: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Scale Docker Swarm service."""
        client = get_client()
        manager_vm = _primary_manager_vm(client, cluster_name)
        require_confirm(confirm)
        result = client.scale_docker_service(
            manager_vm["node"], manager_vm["vmid"], service_name, replicas
        )
        result.update(
            {
                "cluster_name": cluster_name,
                "service_name": service_name,
                "replicas": replicas,
            }
        )
        return result

    @server.tool("proxmox-docker-service-remove")
    async def proxmox_docker_service_remove(
        cluster_name: str, service_name: str, confirm: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Remove Docker Swarm service."""
        client = get_client()
        manager_vm = _primary_manager_vm(client, cluster_name)
        require_confirm(confirm)
        result = client.remove_docker_service(
            manager_vm["node"], manager_vm["vmid"], service_name
        )
        result.update({"cluster_name": cluster_name, "service_name": service_name})
        return result

    @server.tool("proxmox-docker-network-create")
    async def proxmox_docker_network_create(
        cluster_name: str,
        network_name: str,
        driver: str = "overlay",
        subnet: Optional[str] = None,
        attachable: bool = False,
        encrypted: bool = False,
        confirm: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Create Docker network in Swarm cluster."""
        client = get_client()
        manager_vm = _primary_manager_vm(client, cluster_name)
        require_confirm(confirm)
        result = client.create_docker_network(
            manager_vm["node"],
            manager_vm["vmid"],
            network_name,
            driver,
            subnet,
            attachable,
            encrypted,
        )
        result.update(
            {
                "cluster_name": cluster_name,
                "network_name": network_name,
                "driver": driver,
            }
        )
        return result

    @server.tool("proxmox-docker-service-logs")
    async def proxmox_docker_service_logs(
        cluster_name: str, service_name: str, lines: int = 100
    ) -> Dict[str, Any]:
        """Get Docker Swarm service logs."""
        client = get_client()
        manager_vm = _primary_manager_vm(client, cluster_name)
        result = client.get_docker_service_logs(
            manager_vm["node"], manager_vm["vmid"], service_name, lines
        )
        result.update(
            {"cluster_name": cluster_name, "service_name": service_name, "lines": lines}
        )
        return result

    @server.tool("proxmox-docker-execute-command")
    async def proxmox_docker_execute_command(
        cluster_name: str,
        command: str,
        target: str = "manager",
        confirm: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Execute Docker command on cluster node."""
        client = get_client()
        cluster_vms = client.get_cluster_vms(cluster_name)
        if target == "manager":
            target_vms = [
                vm for vm in cluster_vms if "manager" in vm.get("name", "").lower()
            ]
        else:
            target_vms = [
                vm for vm in cluster_vms if target in vm.get("name", "").lower()
            ]
        if not target_vms:
            raise ValueError(f"No {target} nodes found in cluster: {cluster_name}")

        target_vm = target_vms[0]
        require_confirm(confirm)
        result = client.execute_docker_command(
            target_vm["node"], target_vm["vmid"], command
        )
        result.update(
            {
                "cluster_name": cluster_name,
                "target_node": target_vm["name"],
                "command": command,
            }
        )
        return result

    @server.tool("proxmox-terraform-plan")
    async def proxmox_terraform_plan(
        config_path: str,
        workspace: Optional[str] = None,
        auto_approve: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Execute Terraform plans for infrastructure as code."""
        client = get_client()
        infra_manager = get_infrastructure_manager(client)
        return await infra_manager.terraform_plan(
            config_path, workspace, auto_approve, dry_run
        )

    @server.tool("proxmox-ansible-playbook")
    async def proxmox_ansible_playbook(
        playbook_path: str,
        inventory: Optional[str] = None,
        extra_vars: Optional[Dict[str, Any]] = None,
        limit: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Execute Ansible playbooks against Proxmox VMs."""
        client = get_client()
        infra_manager = get_infrastructure_manager(client)
        return await infra_manager.ansible_playbook(
            playbook_path, inventory, extra_vars, limit, dry_run
        )

    @server.tool("proxmox-gitops-sync")
    async def proxmox_gitops_sync(
        repo_url: str,
        branch: str = "main",
        config_path: str = "./infrastructure",
        auto_deploy: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Sync infrastructure state with Git repository."""
        client = get_client()
        infra_manager = get_infrastructure_manager(client)
        return await infra_manager.gitops_sync(
            repo_url, branch, config_path, auto_deploy, dry_run
        )

    @server.tool("proxmox-create-vlan")
    async def proxmox_create_vlan(
        vlan_id: int,
        vlan_name: str,
        bridge: str = "vmbr0",
        gateway: Optional[str] = None,
        dhcp_range: Optional[str] = None,
        node: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Create and configure VLANs for network segmentation."""
        client = get_client()
        network_manager = get_network_manager(client)
        return await network_manager.create_vlan(
            vlan_id, vlan_name, bridge, gateway, dhcp_range, node, dry_run
        )

    @server.tool("proxmox-configure-firewall")
    async def proxmox_configure_firewall(
        vmid: int,
        rules: List[Dict[str, Any]],
        policy: str = "ACCEPT",
        log_level: str = "info",
        node: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Configure VM-level firewall rules."""
        client = get_client()
        network_manager = get_network_manager(client)
        return await network_manager.configure_firewall(
            vmid, rules, policy, log_level, node, dry_run
        )

    @server.tool("proxmox-deploy-vpn-server")
    async def proxmox_deploy_vpn_server(
        vpn_type: str = "wireguard",
        client_count: int = 10,
        subnet: str = "10.0.100.0/24",
        node: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Deploy VPN server for secure remote access."""
        client = get_client()
        network_manager = get_network_manager(client)
        return await network_manager.deploy_vpn_server(
            vpn_type, client_count, subnet, node, dry_run
        )

    @server.tool("proxmox-setup-replication")
    async def proxmox_setup_replication(
        source_storage: str,
        target_node: str,
        target_storage: str,
        schedule: str = "*/15 * * * *",
        compression: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Setup storage replication between nodes."""
        client = get_client()
        storage_manager = get_storage_manager(client)
        return await storage_manager.setup_replication(
            source_storage, target_node, target_storage, schedule, compression, dry_run
        )

    @server.tool("proxmox-snapshot-policy")
    async def proxmox_snapshot_policy(
        vmid: int,
        policy: Dict[str, Any],
        auto_cleanup: bool = True,
        compression: bool = True,
        node: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Create automated snapshot policies with lifecycle management."""
        client = get_client()
        storage_manager = get_storage_manager(client)
        return await storage_manager.snapshot_policy(
            vmid, policy, auto_cleanup, compression, node, dry_run
        )

    @server.tool("proxmox-migrate-storage")
    async def proxmox_migrate_storage(
        vmid: int,
        source_storage: str,
        target_storage: str,
        online: bool = True,
        preserve_source: bool = False,
        node: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Migrate VM storage between different storage backends."""
        client = get_client()
        storage_manager = get_storage_manager(client)
        return await storage_manager.migrate_storage(
            vmid, source_storage, target_storage, online, preserve_source, node, dry_run
        )
