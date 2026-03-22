from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from ..cloudinit import (
    CloudInitConfig,
    CloudInitProvisioner,
    get_development_config,
    get_docker_host_config,
    get_ubuntu_web_server_config,
)
from ..rhcos import IgnitionConfig, RHCOSProvisioner
from ..windows import (
    WindowsConfig,
    WindowsProvisioner,
    get_windows_domain_controller_config,
    get_windows_web_server_config,
)


def register_provisioning_tools(
    server: FastMCP,
    get_client: Callable[[], Any],
) -> None:
    @server.tool("proxmox-list-os-templates")
    async def proxmox_list_os_templates(
        node: Optional[str] = None, storage: Optional[str] = None
    ) -> Dict[str, Any]:
        """List available OS templates and their configurations."""
        client = get_client()
        node_id = node or client.default_node
        storage_id = storage or client.default_storage
        if not node_id or not storage_id:
            raise ValueError("node and storage are required (or set defaults)")

        storage_templates = client.list_os_templates(node_id, storage_id)
        builtin_templates = [
            {
                "name": template_key,
                "display_name": template_info["name"],
                "type": "cloudinit",
                "default_user": template_info["default_user"],
                "package_manager": template_info["package_manager"],
                "image_url": template_info["image_url"],
            }
            for template_key, template_info in CloudInitConfig.OS_TEMPLATES.items()
        ]

        return {
            "storage_templates": storage_templates,
            "builtin_templates": builtin_templates,
            "total_templates": len(storage_templates) + len(builtin_templates),
        }

    @server.tool("proxmox-download-os-template")
    async def proxmox_download_os_template(
        template_name: str,
        node: Optional[str] = None,
        storage: Optional[str] = None,
        verify_checksum: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Download OS template from official sources."""
        client = get_client()
        node_id = node or client.default_node
        storage_id = storage or client.default_storage
        if not node_id or not storage_id:
            raise ValueError("node and storage are required (or set defaults)")

        if template_name not in CloudInitConfig.OS_TEMPLATES:
            raise ValueError(
                f"Unsupported template: {template_name}. Supported: {list(CloudInitConfig.OS_TEMPLATES.keys())}"
            )

        template_info = CloudInitConfig.OS_TEMPLATES[template_name]
        if dry_run:
            return {
                "dry_run": True,
                "action": "download-template",
                "params": {
                    "template_name": template_name,
                    "node": node_id,
                    "storage": storage_id,
                    "url": template_info["image_url"],
                    "verify_checksum": verify_checksum,
                },
            }

        upid = client.download_os_template(
            node_id, storage_id, template_name, template_info["image_url"]
        )
        return {
            "upid": upid,
            "template_name": template_name,
            "template_info": template_info,
        }

    @server.tool("proxmox-create-vm-cloudinit")
    async def proxmox_create_vm_cloudinit(
        node: Optional[str] = None,
        vmid: int = 0,
        name: str = "",
        template: str = "ubuntu-22.04",
        cloudinit_config: Optional[Dict[str, Any]] = None,
        hardware: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        wait: bool = False,
        timeout: int = 900,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """Create VM with advanced CloudInit configuration."""
        client = get_client()
        node_id = node or client.default_node
        if not node_id:
            raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
        if vmid <= 0 or not name:
            raise ValueError("vmid > 0 and non-empty name are required")

        hw_config = hardware or {}
        cores = hw_config.get("cores", 2)
        memory_mb = hw_config.get("memory_mb", 2048)
        disk_gb = hw_config.get("disk_gb", 20)

        if dry_run:
            return {
                "dry_run": True,
                "action": "create-vm-cloudinit",
                "params": {
                    "node": node_id,
                    "vmid": vmid,
                    "name": name,
                    "template": template,
                    "hardware": {
                        "cores": cores,
                        "memory_mb": memory_mb,
                        "disk_gb": disk_gb,
                    },
                    "cloudinit_config": cloudinit_config,
                },
            }

        config = CloudInitConfig(template)
        if cloudinit_config:
            if "hostname" in cloudinit_config:
                config.set_hostname(
                    cloudinit_config["hostname"], cloudinit_config.get("fqdn")
                )
            if "users" in cloudinit_config:
                for user in cloudinit_config["users"]:
                    config.add_user(
                        user["name"],
                        user.get("ssh_keys", []),
                        user.get("sudo", "ALL=(ALL) NOPASSWD:ALL"),
                        user.get("shell", "/bin/bash"),
                        user.get("passwd"),
                    )
            if "packages" in cloudinit_config:
                config.add_packages(cloudinit_config["packages"])
            if "commands" in cloudinit_config:
                config.add_commands(cloudinit_config["commands"])
            if "network" in cloudinit_config:
                net = cloudinit_config["network"]
                config.set_network_config(
                    interface=net.get("interface", "ens18"),
                    dhcp=net.get("dhcp", True),
                    ip=net.get("ip"),
                    gateway=net.get("gateway"),
                    nameservers=net.get("nameservers"),
                )
            if "timezone" in cloudinit_config:
                config.set_timezone(cloudinit_config["timezone"])

        provisioner = CloudInitProvisioner(client)
        upid = provisioner.create_vm_with_cloudinit(
            node=node_id,
            vmid=vmid,
            name=name,
            template=template,
            cloudinit_config=config,
            hardware={"cores": cores, "memory_mb": memory_mb, "disk_gb": disk_gb},
        )
        result: Dict[str, Any] = {"upid": upid, "template": template}
        if wait:
            result["status"] = client.wait_task(
                upid, node=node_id, timeout=timeout, poll_interval=poll_interval
            )
        return result

    @server.tool("proxmox-configure-cloudinit-advanced")
    async def proxmox_configure_cloudinit_advanced(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        users: Optional[List[Dict[str, Any]]] = None,
        packages: Optional[List[str]] = None,
        commands: Optional[List[str | List[str]]] = None,
        network_config: Optional[Dict[str, Any]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Configure advanced CloudInit settings for VM."""
        client = get_client()
        vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)

        if dry_run:
            return {
                "dry_run": True,
                "action": "configure-cloudinit-advanced",
                "params": {
                    "node": vm_node,
                    "vmid": vm_vmid,
                    "users": users or [],
                    "packages": packages or [],
                    "commands": commands or [],
                    "network_config": network_config,
                    "files": files or [],
                },
            }

        config = CloudInitConfig()
        if users:
            for user in users:
                config.add_user(
                    user["name"],
                    user.get("ssh_keys", []),
                    user.get("sudo", "ALL=(ALL) NOPASSWD:ALL"),
                    user.get("shell", "/bin/bash"),
                    user.get("passwd"),
                )
        if packages:
            config.add_packages(packages)
        if commands:
            config.add_commands(commands)
        if network_config:
            config.set_network_config(
                interface=network_config.get("interface", "ens18"),
                dhcp=network_config.get("dhcp", True),
                ip=network_config.get("ip"),
                gateway=network_config.get("gateway"),
                nameservers=network_config.get("nameservers"),
            )
        if files:
            for file_config in files:
                config.add_file(
                    file_config["path"],
                    file_config["content"],
                    file_config.get("permissions", "0644"),
                    file_config.get("owner", "root:root"),
                    file_config.get("encoding", "text/plain"),
                )

        user_data = config.to_user_data()
        iso_path = f"/tmp/cloudinit-{vm_vmid}.iso"
        client.create_cloudinit_iso(user_data, output_path=iso_path)
        result = client.attach_cloudinit_iso(vm_node, vm_vmid, iso_path)
        os.unlink(iso_path)
        return result

    @server.tool("proxmox-create-preset-vm")
    async def proxmox_create_preset_vm(
        preset: str,
        node: Optional[str] = None,
        vmid: int = 0,
        name: str = "",
        hostname: str = "",
        ssh_keys: Optional[List[str]] = None,
        admin_user: str = "",
        dry_run: bool = False,
        wait: bool = False,
        timeout: int = 900,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """Create VM with preset configurations."""
        client = get_client()
        node_id = node or client.default_node
        if not node_id:
            raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
        if vmid <= 0 or not name:
            raise ValueError("vmid > 0 and non-empty name are required")
        ssh_keys = ssh_keys or []
        if not ssh_keys:
            raise ValueError("ssh_keys are required for preset configurations")

        preset_configs = {
            "web-server": get_ubuntu_web_server_config,
            "docker-host": get_docker_host_config,
            "development": get_development_config,
        }
        if preset not in preset_configs:
            raise ValueError(
                f"Unsupported preset: {preset}. Supported: {list(preset_configs.keys())}"
            )

        if dry_run:
            return {
                "dry_run": True,
                "action": "create-preset-vm",
                "params": {
                    "preset": preset,
                    "node": node_id,
                    "vmid": vmid,
                    "name": name,
                    "hostname": hostname or name,
                    "admin_user": admin_user,
                    "ssh_keys_count": len(ssh_keys),
                },
            }

        default_user = "fedora" if preset == "development" else "ubuntu"
        config = preset_configs[preset](
            hostname or name, ssh_keys, admin_user or default_user
        )
        provisioner = CloudInitProvisioner(client)
        upid = provisioner.create_vm_with_cloudinit(
            node=node_id,
            vmid=vmid,
            name=name,
            template=config.template,
            cloudinit_config=config,
            hardware={"cores": 2, "memory_mb": 2048, "disk_gb": 20},
        )
        result: Dict[str, Any] = {
            "upid": upid,
            "preset": preset,
            "template": config.template,
        }
        if wait:
            result["status"] = client.wait_task(
                upid, node=node_id, timeout=timeout, poll_interval=poll_interval
            )
        return result

    @server.tool("proxmox-list-rhcos-streams")
    async def proxmox_list_rhcos_streams() -> Dict[str, Any]:
        """List available RHCOS release streams and versions."""
        return {
            "streams": IgnitionConfig.RHCOS_STREAMS,
            "supported_versions": list(IgnitionConfig.RHCOS_STREAMS.keys()),
            "default_version": "4.14",
        }

    @server.tool("proxmox-download-rhcos")
    async def proxmox_download_rhcos(
        version: str,
        node: Optional[str] = None,
        storage: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Download RHCOS image from official Red Hat sources."""
        client = get_client()
        node_id = node or client.default_node
        storage_id = storage or client.default_storage
        if not node_id or not storage_id:
            raise ValueError("node and storage are required (or set defaults)")
        if version not in IgnitionConfig.RHCOS_STREAMS:
            raise ValueError(
                f"Unsupported RHCOS version: {version}. Supported: {list(IgnitionConfig.RHCOS_STREAMS.keys())}"
            )

        stream_info = IgnitionConfig.RHCOS_STREAMS[version]
        if dry_run:
            return {
                "dry_run": True,
                "action": "download-rhcos",
                "params": {
                    "version": version,
                    "node": node_id,
                    "storage": storage_id,
                    "stream_info": stream_info,
                },
            }

        provisioner = RHCOSProvisioner(client)
        upid = provisioner.download_rhcos_image(version, node_id, storage_id)
        return {
            "upid": upid,
            "version": version,
            "stream_info": stream_info,
            "status": "downloading",
        }

    @server.tool("proxmox-create-rhcos-vm")
    async def proxmox_create_rhcos_vm(
        node: Optional[str] = None,
        vmid: int = 0,
        name: str = "",
        rhcos_version: str = "4.14",
        ignition_config: Optional[Dict[str, Any]] = None,
        hardware: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        wait: bool = False,
        timeout: int = 900,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """Create RHCOS VM with Ignition configuration."""
        client = get_client()
        node_id = node or client.default_node
        if not node_id:
            raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
        if vmid <= 0 or not name:
            raise ValueError("vmid > 0 and non-empty name are required")

        hw_config = hardware or {}
        cores = hw_config.get("cores", 4)
        memory_mb = hw_config.get("memory_mb", 8192)
        disk_gb = hw_config.get("disk_gb", 50)

        if dry_run:
            return {
                "dry_run": True,
                "action": "create-rhcos-vm",
                "params": {
                    "node": node_id,
                    "vmid": vmid,
                    "name": name,
                    "rhcos_version": rhcos_version,
                    "hardware": {
                        "cores": cores,
                        "memory_mb": memory_mb,
                        "disk_gb": disk_gb,
                    },
                    "ignition_config": ignition_config,
                },
            }

        config = IgnitionConfig()
        if ignition_config:
            if "users" in ignition_config:
                for user in ignition_config["users"]:
                    config.add_user(
                        user["name"],
                        user.get("ssh_keys", []),
                        user.get("groups", ["sudo", "docker"]),
                        user.get("shell", "/bin/bash"),
                        user.get("home_dir"),
                    )
            if "hostname" in ignition_config:
                config.set_hostname(ignition_config["hostname"])
            if "files" in ignition_config:
                for file_config in ignition_config["files"]:
                    config.add_file(
                        file_config["path"],
                        file_config["content"],
                        file_config.get("mode", 0o644),
                        file_config.get("user_id", 0),
                        file_config.get("group_id", 0),
                    )
            if "systemd_units" in ignition_config:
                for unit in ignition_config["systemd_units"]:
                    config.add_systemd_unit(
                        unit["name"],
                        unit.get("content", ""),
                        unit.get("enabled", True),
                        unit.get("mask", False),
                    )

        provisioner = RHCOSProvisioner(client)
        upid = provisioner.create_rhcos_vm(
            node=node_id,
            vmid=vmid,
            name=name,
            rhcos_version=rhcos_version,
            ignition_config=config,
            hardware={"cores": cores, "memory_mb": memory_mb, "disk_gb": disk_gb},
        )
        result: Dict[str, Any] = {"upid": upid, "rhcos_version": rhcos_version}
        if wait:
            result["status"] = client.wait_task(
                upid, node=node_id, timeout=timeout, poll_interval=poll_interval
            )
        return result

    @server.tool("proxmox-create-ignition-config")
    async def proxmox_create_ignition_config(
        users: List[Dict[str, Any]],
        hostname: Optional[str] = None,
        files: Optional[List[Dict[str, Any]]] = None,
        systemd_units: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Create and validate Ignition configuration for RHCOS."""
        config = IgnitionConfig()
        for user in users:
            config.add_user(
                user["name"],
                user.get("ssh_keys", []),
                user.get("groups", ["sudo", "docker"]),
                user.get("shell", "/bin/bash"),
                user.get("home_dir"),
            )
        if hostname:
            config.set_hostname(hostname)
        if files:
            for file_config in files:
                config.add_file(
                    file_config["path"],
                    file_config["content"],
                    file_config.get("mode", 0o644),
                    file_config.get("user_id", 0),
                    file_config.get("group_id", 0),
                )
        if systemd_units:
            for unit in systemd_units:
                config.add_systemd_unit(
                    unit["name"],
                    unit.get("content", ""),
                    unit.get("enabled", True),
                    unit.get("mask", False),
                )
        config.validate_config()
        return {
            "ignition_config": config.config,
            "ignition_json": config.to_json(),
            "ignition_compact": config.to_compact_json(),
            "validation": "passed",
        }

    @server.tool("proxmox-list-windows-versions")
    async def proxmox_list_windows_versions() -> Dict[str, Any]:
        """List available Windows Server versions and configurations."""
        return {
            "versions": WindowsConfig.WINDOWS_VERSIONS,
            "supported_versions": list(WindowsConfig.WINDOWS_VERSIONS.keys()),
            "default_version": "server-2022",
            "virtio_drivers": WindowsConfig.VIRTIO_DRIVERS,
        }

    @server.tool("proxmox-create-windows-vm")
    async def proxmox_create_windows_vm(
        node: Optional[str] = None,
        vmid: int = 0,
        name: str = "",
        windows_version: str = "server-2022",
        admin_password: str = "",
        computer_name: str = "",
        hardware: Optional[Dict[str, Any]] = None,
        domain_config: Optional[Dict[str, Any]] = None,
        applications: Optional[List[Dict[str, Any]]] = None,
        license_key: Optional[str] = None,
        dry_run: bool = False,
        wait: bool = False,
        timeout: int = 1800,
        poll_interval: float = 5.0,
    ) -> Dict[str, Any]:
        """Create Windows Server VM with automated installation and configuration."""
        client = get_client()
        node_id = node or client.default_node
        if not node_id:
            raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
        if vmid <= 0 or not name:
            raise ValueError("vmid > 0 and non-empty name are required")
        if not admin_password:
            raise ValueError("admin_password is required")

        hw_config = hardware or {}
        cores = hw_config.get("cores", 4)
        memory_mb = hw_config.get("memory_mb", 4096)
        disk_gb = hw_config.get("disk_gb", 60)

        if dry_run:
            return {
                "dry_run": True,
                "action": "create-windows-vm",
                "params": {
                    "node": node_id,
                    "vmid": vmid,
                    "name": name,
                    "windows_version": windows_version,
                    "computer_name": computer_name or name,
                    "hardware": {
                        "cores": cores,
                        "memory_mb": memory_mb,
                        "disk_gb": disk_gb,
                    },
                    "domain_config": domain_config,
                    "applications": applications or [],
                    "has_license_key": bool(license_key),
                },
            }

        config = WindowsConfig(windows_version)
        config.set_admin_password(admin_password)
        config.set_computer_name(computer_name or name)
        if domain_config:
            config.set_domain_config(
                domain_config["domain"],
                domain_config["username"],
                domain_config["password"],
                domain_config.get("ou_path"),
            )
        if applications:
            for app in applications:
                config.add_application(
                    app["name"], app["installer_url"], app.get("silent_args", "/S")
                )

        provisioner = WindowsProvisioner(client)
        upid = provisioner.create_windows_vm(
            node=node_id,
            vmid=vmid,
            name=name,
            windows_version=windows_version,
            windows_config=config,
            hardware={"cores": cores, "memory_mb": memory_mb, "disk_gb": disk_gb},
            license_key=license_key,
        )
        result: Dict[str, Any] = {
            "upid": upid,
            "windows_version": windows_version,
            "computer_name": computer_name or name,
            "rdp_port": 3389,
        }
        if wait:
            result["status"] = client.wait_task(
                upid, node=node_id, timeout=timeout, poll_interval=poll_interval
            )
        return result

    @server.tool("proxmox-create-windows-preset")
    async def proxmox_create_windows_preset(
        preset: str,
        node: Optional[str] = None,
        vmid: int = 0,
        name: str = "",
        computer_name: str = "",
        admin_password: str = "",
        domain: Optional[str] = None,
        license_key: Optional[str] = None,
        dry_run: bool = False,
        wait: bool = False,
        timeout: int = 1800,
        poll_interval: float = 5.0,
    ) -> Dict[str, Any]:
        """Create Windows VM with preset configurations."""
        client = get_client()
        node_id = node or client.default_node
        if not node_id:
            raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
        if vmid <= 0 or not name:
            raise ValueError("vmid > 0 and non-empty name are required")
        if not admin_password:
            raise ValueError("admin_password is required")

        preset_configs = {
            "web-server": get_windows_web_server_config,
            "domain-controller": get_windows_domain_controller_config,
        }
        if preset not in preset_configs:
            raise ValueError(
                f"Unsupported preset: {preset}. Supported: {list(preset_configs.keys())}"
            )

        if dry_run:
            return {
                "dry_run": True,
                "action": "create-windows-preset",
                "params": {
                    "preset": preset,
                    "node": node_id,
                    "vmid": vmid,
                    "name": name,
                    "computer_name": computer_name or name,
                    "domain": domain,
                    "has_license_key": bool(license_key),
                },
            }

        if preset == "domain-controller":
            if not domain:
                raise ValueError("domain is required for domain-controller preset")
            config = get_windows_domain_controller_config(
                computer_name or name, admin_password, domain
            )
        else:
            config = get_windows_web_server_config(
                computer_name or name, admin_password, domain
            )

        provisioner = WindowsProvisioner(client)
        upid = provisioner.create_windows_vm(
            node=node_id,
            vmid=vmid,
            name=name,
            windows_version="server-2022",
            windows_config=config,
            hardware={"cores": 4, "memory_mb": 4096, "disk_gb": 60},
            license_key=license_key,
        )
        result: Dict[str, Any] = {
            "upid": upid,
            "preset": preset,
            "windows_version": "server-2022",
            "computer_name": computer_name or name,
            "rdp_port": 3389,
        }
        if wait:
            result["status"] = client.wait_task(
                upid, node=node_id, timeout=timeout, poll_interval=poll_interval
            )
        return result

    @server.tool("proxmox-windows-domain-join")
    async def proxmox_windows_domain_join(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        domain: str = "",
        username: str = "",
        password: str = "",
        ou_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Join Windows VM to Active Directory domain."""
        client = get_client()
        vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
        if not domain or not username or not password:
            raise ValueError("domain, username, and password are required")

        if dry_run:
            return {
                "dry_run": True,
                "action": "windows-domain-join",
                "params": {
                    "node": vm_node,
                    "vmid": vm_vmid,
                    "domain": domain,
                    "username": username,
                    "ou_path": ou_path,
                },
            }

        provisioner = WindowsProvisioner(client)
        return provisioner.join_domain(
            vm_node, vm_vmid, domain, username, password, ou_path
        )

    @server.tool("proxmox-windows-install-apps")
    async def proxmox_windows_install_apps(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        applications: Optional[List[Dict[str, Any]]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Install applications on Windows VM."""
        client = get_client()
        vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
        applications = applications or []
        if not applications:
            raise ValueError("applications list is required")

        if dry_run:
            return {
                "dry_run": True,
                "action": "windows-install-apps",
                "params": {
                    "node": vm_node,
                    "vmid": vm_vmid,
                    "applications": [app["name"] for app in applications],
                },
            }

        provisioner = WindowsProvisioner(client)
        return provisioner.install_applications(vm_node, vm_vmid, applications)

    @server.tool("proxmox-windows-configure-rdp")
    async def proxmox_windows_configure_rdp(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        enable: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Configure Windows Remote Desktop Protocol."""
        client = get_client()
        vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
        if dry_run:
            return {
                "dry_run": True,
                "action": "windows-configure-rdp",
                "params": {"node": vm_node, "vmid": vm_vmid, "enable": enable},
            }
        return client.configure_windows_rdp(vm_node, vm_vmid, enable)

    @server.tool("proxmox-windows-vm-info")
    async def proxmox_windows_vm_info(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get detailed Windows VM information including RDP access."""
        client = get_client()
        vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
        return client.get_windows_vm_info(vm_node, vm_vmid)

    @server.tool("proxmox-windows-execute-command")
    async def proxmox_windows_execute_command(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        command: str = "",
        shell: str = "powershell",
    ) -> Dict[str, Any]:
        """Execute command on Windows VM via QEMU guest agent."""
        client = get_client()
        vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
        if not command:
            raise ValueError("command is required")
        return client.execute_windows_command(vm_node, vm_vmid, command, shell)

    @server.tool("proxmox-windows-services")
    async def proxmox_windows_services(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        action: str = "list",
        service_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Manage Windows services (list, restart)."""
        client = get_client()
        vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
        if action == "list":
            return client.get_windows_services(vm_node, vm_vmid)
        if action == "restart":
            if not service_name:
                raise ValueError("service_name is required for restart action")
            return client.restart_windows_service(vm_node, vm_vmid, service_name)
        raise ValueError(f"Unsupported action: {action}. Supported: list, restart")

    @server.tool("proxmox-windows-updates")
    async def proxmox_windows_updates(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Install Windows updates via PowerShell."""
        client = get_client()
        vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
        return client.install_windows_updates(vm_node, vm_vmid)
