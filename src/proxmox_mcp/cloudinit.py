"""CloudInit configuration and VM provisioning module."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import os
import tempfile
import yaml
from typing import Any, Dict, List, Optional, Union

from jsonschema import validate, ValidationError

from .utils import command_failure_message


DEFAULT_CLOUDINIT_CONFIG: Dict[str, Any] = {
    "package_update": True,
    "package_upgrade": False,
    "ssh_pwauth": True,
    "disable_root": True,
}


@dataclass(frozen=True)
class ProxmoxCloudInitPayload:
    native_params: Dict[str, str]
    custom_user_data: Optional[str] = None


class CloudInitConfig:
    """CloudInit configuration builder and validator."""

    # Common OS templates with their specific configurations
    OS_TEMPLATES = {
        "ubuntu-22.04": {
            "name": "Ubuntu 22.04 LTS",
            "image_url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
            "default_user": "ubuntu",
            "package_manager": "apt",
            "default_packages": [
                "curl",
                "wget",
                "git",
                "htop",
                "vim",
                "openssh-server",
            ],
        },
        "ubuntu-24.04": {
            "name": "Ubuntu 24.04 LTS",
            "image_url": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
            "default_user": "ubuntu",
            "package_manager": "apt",
            "default_packages": [
                "curl",
                "wget",
                "git",
                "htop",
                "vim",
                "openssh-server",
            ],
        },
        "fedora-39": {
            "name": "Fedora 39",
            "image_url": "https://download.fedoraproject.org/pub/fedora/linux/releases/39/Cloud/x86_64/images/Fedora-Cloud-Base-39-1.5.x86_64.qcow2",
            "default_user": "fedora",
            "package_manager": "dnf",
            "default_packages": [
                "curl",
                "wget",
                "git",
                "htop",
                "vim",
                "openssh-server",
            ],
        },
        "fedora-40": {
            "name": "Fedora 40",
            "image_url": "https://download.fedoraproject.org/pub/fedora/linux/releases/40/Cloud/x86_64/images/Fedora-Cloud-Base-40-1.14.x86_64.qcow2",
            "default_user": "fedora",
            "package_manager": "dnf",
            "default_packages": [
                "curl",
                "wget",
                "git",
                "htop",
                "vim",
                "openssh-server",
            ],
        },
        "rocky-9": {
            "name": "Rocky Linux 9",
            "image_url": "https://download.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud-Base.latest.x86_64.qcow2",
            "default_user": "rocky",
            "package_manager": "dnf",
            "default_packages": [
                "curl",
                "wget",
                "git",
                "htop",
                "vim",
                "openssh-server",
            ],
        },
        "almalinux-9": {
            "name": "AlmaLinux 9",
            "image_url": "https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/AlmaLinux-9-GenericCloud-latest.x86_64.qcow2",
            "default_user": "almalinux",
            "package_manager": "dnf",
            "default_packages": [
                "curl",
                "wget",
                "git",
                "htop",
                "vim",
                "openssh-server",
            ],
        },
    }

    # CloudInit schema for validation
    CLOUDINIT_SCHEMA = {
        "type": "object",
        "properties": {
            "users": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "sudo": {"type": ["string", "array"]},
                        "shell": {"type": "string"},
                        "ssh_authorized_keys": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "passwd": {"type": "string"},
                        "lock_passwd": {"type": "boolean"},
                    },
                    "required": ["name"],
                },
            },
            "packages": {"type": "array", "items": {"type": "string"}},
            "package_update": {"type": "boolean"},
            "package_upgrade": {"type": "boolean"},
            "runcmd": {"type": "array", "items": {"type": ["string", "array"]}},
            "write_files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "permissions": {"type": "string"},
                        "owner": {"type": "string"},
                        "encoding": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            "network": {
                "type": "object",
                "properties": {
                    "version": {"type": "integer"},
                    "ethernets": {"type": "object"},
                },
            },
            "hostname": {"type": "string"},
            "fqdn": {"type": "string"},
            "timezone": {"type": "string"},
            "ssh_pwauth": {"type": "boolean"},
            "disable_root": {"type": "boolean"},
        },
    }

    def __init__(self, template: str = "ubuntu-22.04"):
        """Initialize CloudInit configuration with OS template."""
        if template not in self.OS_TEMPLATES:
            raise ValueError(
                f"Unsupported template: {template}. Supported: {list(self.OS_TEMPLATES.keys())}"
            )

        self.template = template
        self.template_info = self.OS_TEMPLATES[template]
        self.config: Dict[str, Any] = dict(DEFAULT_CLOUDINIT_CONFIG)

    def add_user(
        self,
        name: str,
        ssh_keys: List[str],
        sudo: Union[str, List[str]] = "ALL=(ALL) NOPASSWD:ALL",
        shell: str = "/bin/bash",
        passwd: Optional[str] = None,
    ) -> None:
        """Add user to CloudInit configuration."""
        if "users" not in self.config:
            self.config["users"] = []

        user_config = {
            "name": name,
            "sudo": sudo,
            "shell": shell,
            "ssh_authorized_keys": ssh_keys,
            "lock_passwd": passwd is None,
        }

        if passwd:
            user_config["passwd"] = passwd

        self.config["users"].append(user_config)

    def add_packages(self, packages: List[str]) -> None:
        """Add packages to install."""
        if "packages" not in self.config:
            self.config["packages"] = []

        # Add default packages for the OS
        all_packages = list(set(self.template_info["default_packages"] + packages))
        self.config["packages"] = all_packages

    def add_commands(self, commands: List[Union[str, List[str]]]) -> None:
        """Add commands to run on first boot."""
        if "runcmd" not in self.config:
            self.config["runcmd"] = []

        self.config["runcmd"].extend(commands)

    def add_file(
        self,
        path: str,
        content: str,
        permissions: str = "0644",
        owner: str = "root:root",
        encoding: str = "text/plain",
    ) -> None:
        """Add file to write during cloud-init."""
        if "write_files" not in self.config:
            self.config["write_files"] = []

        self.config["write_files"].append(
            {
                "path": path,
                "content": content,
                "permissions": permissions,
                "owner": owner,
                "encoding": encoding,
            }
        )

    def set_network_config(
        self,
        interface: str = "ens18",
        dhcp: bool = True,
        ip: Optional[str] = None,
        gateway: Optional[str] = None,
        nameservers: Optional[List[str]] = None,
    ) -> None:
        """Configure network settings."""
        network_config = {"version": 2, "ethernets": {interface: {}}}

        if dhcp:
            network_config["ethernets"][interface]["dhcp4"] = True
        else:
            if not ip:
                raise ValueError("IP address required when DHCP is disabled")

            network_config["ethernets"][interface]["addresses"] = [ip]
            if gateway:
                network_config["ethernets"][interface]["gateway4"] = gateway
            if nameservers:
                network_config["ethernets"][interface]["nameservers"] = {
                    "addresses": nameservers
                }

        self.config["network"] = network_config

    def set_hostname(self, hostname: str, fqdn: Optional[str] = None) -> None:
        """Set hostname and FQDN."""
        self.config["hostname"] = hostname
        if fqdn:
            self.config["fqdn"] = fqdn

    def set_timezone(self, timezone: str = "UTC") -> None:
        """Set system timezone."""
        self.config["timezone"] = timezone

    def validate_config(self) -> bool:
        """Validate CloudInit configuration against schema."""
        try:
            validate(instance=self.config, schema=self.CLOUDINIT_SCHEMA)
            return True
        except ValidationError as e:
            raise ValueError(f"CloudInit configuration validation error: {e.message}")

    def to_yaml(self) -> str:
        """Convert configuration to CloudInit YAML format."""
        self.validate_config()

        # Add cloud-config header
        yaml_content = "#cloud-config\n"
        yaml_content += yaml.dump(
            self.config, default_flow_style=False, allow_unicode=True
        )

        return yaml_content

    def to_user_data(self) -> str:
        """Generate user-data for CloudInit."""
        return self.to_yaml()

    def _user_can_use_native_params(self, user: Dict[str, Any]) -> bool:
        supported_keys = {
            "name",
            "ssh_authorized_keys",
            "passwd",
            "lock_passwd",
            "sudo",
            "shell",
        }
        if set(user) - supported_keys:
            return False
        if user.get("sudo", "ALL=(ALL) NOPASSWD:ALL") != "ALL=(ALL) NOPASSWD:ALL":
            return False
        if user.get("shell", "/bin/bash") != "/bin/bash":
            return False
        if user.get("lock_passwd") is False and not user.get("passwd"):
            return False
        return True

    def _build_native_network_params(self, network: Dict[str, Any]) -> Dict[str, str]:
        ethernets = network.get("ethernets") or {}
        if not ethernets:
            return {}
        if len(ethernets) != 1:
            raise ValueError(
                "Native Proxmox Cloud-Init currently supports one network interface"
            )

        interface_config = next(iter(ethernets.values()))
        params: Dict[str, str] = {}
        if interface_config.get("dhcp4", False):
            params["ipconfig0"] = "ip=dhcp"
        else:
            addresses = interface_config.get("addresses") or []
            if len(addresses) > 1:
                raise ValueError(
                    "Native Proxmox Cloud-Init currently supports one IPv4 address on net0"
                )
            if addresses:
                params["ipconfig0"] = f"ip={addresses[0]}"
                gateway = interface_config.get("gateway4")
                if gateway:
                    params["ipconfig0"] += f",gw={gateway}"
            else:
                params["ipconfig0"] = "ip=dhcp"

        nameservers = interface_config.get("nameservers") or {}
        resolver_addresses = nameservers.get("addresses") or []
        if resolver_addresses:
            params["nameserver"] = " ".join(str(value) for value in resolver_addresses)

        search = nameservers.get("search")
        if search:
            if isinstance(search, list):
                params["searchdomain"] = " ".join(str(value) for value in search)
            else:
                params["searchdomain"] = str(search)

        return params

    def to_proxmox_payload(self) -> ProxmoxCloudInitPayload:
        """Render config into Proxmox-native settings plus optional user-data."""
        self.validate_config()

        native_params: Dict[str, str] = {}
        custom_config = deepcopy(self.config)

        users = custom_config.get("users") or []
        if len(users) == 1 and self._user_can_use_native_params(users[0]):
            user = users[0]
            native_params["ciuser"] = str(user["name"])
            ssh_keys = user.get("ssh_authorized_keys") or []
            if ssh_keys:
                native_params["sshkeys"] = "\n".join(str(key) for key in ssh_keys)
            if user.get("passwd"):
                native_params["cipassword"] = str(user["passwd"])
            custom_config.pop("users", None)

        network = custom_config.get("network")
        if network:
            native_params.update(self._build_native_network_params(network))
            custom_config.pop("network", None)

        needs_custom_user_data = any(
            key not in DEFAULT_CLOUDINIT_CONFIG
            or value != DEFAULT_CLOUDINIT_CONFIG[key]
            for key, value in custom_config.items()
        )
        if not needs_custom_user_data:
            return ProxmoxCloudInitPayload(native_params=native_params)

        user_data = "#cloud-config\n" + yaml.dump(
            custom_config, default_flow_style=False, allow_unicode=True
        )
        return ProxmoxCloudInitPayload(
            native_params=native_params,
            custom_user_data=user_data,
        )

    def create_iso(
        self,
        output_path: str,
        instance_id: str = "vm-instance",
        local_hostname: Optional[str] = None,
    ) -> str:
        """Create CloudInit NoCloud ISO with user-data and meta-data."""
        import subprocess

        # Create temporary directory for ISO content
        with tempfile.TemporaryDirectory() as temp_dir:
            # Write user-data
            user_data_path = os.path.join(temp_dir, "user-data")
            with open(user_data_path, "w") as f:
                f.write(self.to_user_data())

            # Create meta-data
            meta_data = {
                "instance-id": instance_id,
                "local-hostname": local_hostname or instance_id,
            }
            meta_data_path = os.path.join(temp_dir, "meta-data")
            with open(meta_data_path, "w") as f:
                yaml.dump(meta_data, f)

            # Create network-config if specified
            if "network" in self.config:
                network_config_path = os.path.join(temp_dir, "network-config")
                with open(network_config_path, "w") as f:
                    yaml.dump(self.config["network"], f)

            # Create ISO using genisoimage or mkisofs
            iso_cmd = [
                "genisoimage",
                "-output",
                output_path,
                "-volid",
                "cidata",
                "-joliet",
                "-rock",
                temp_dir,
            ]

            try:
                subprocess.run(iso_cmd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as first_error:
                iso_cmd[0] = "mkisofs"
                try:
                    subprocess.run(iso_cmd, check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as second_error:
                    raise RuntimeError(
                        command_failure_message(
                            iso_cmd,
                            action="creating a cloud-init ISO",
                            likely_cause="both ISO creation commands exited with errors",
                            try_next="install `genisoimage` or `mkisofs` on the MCP host and retry",
                            stderr=second_error.stderr or first_error.stderr,
                        )
                    ) from second_error
                except FileNotFoundError as error:
                    raise RuntimeError(
                        command_failure_message(
                            iso_cmd,
                            action="creating a cloud-init ISO",
                            likely_cause="`mkisofs` is not installed and `genisoimage` already failed",
                            try_next="install `genisoimage` or `mkisofs` on the MCP host and retry",
                            stderr=str(error),
                        )
                    ) from error
            except FileNotFoundError as first_missing:
                iso_cmd[0] = "mkisofs"
                try:
                    subprocess.run(iso_cmd, check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as error:
                    raise RuntimeError(
                        command_failure_message(
                            iso_cmd,
                            action="creating a cloud-init ISO",
                            likely_cause="`genisoimage` is not installed and `mkisofs` returned an error",
                            try_next="install `genisoimage` or `mkisofs` on the MCP host and retry",
                            stderr=error.stderr,
                        )
                    ) from error
                except FileNotFoundError as second_missing:
                    raise RuntimeError(
                        command_failure_message(
                            iso_cmd,
                            action="creating a cloud-init ISO",
                            likely_cause="neither `genisoimage` nor `mkisofs` is installed",
                            try_next="install `genisoimage` or `mkisofs` on the MCP host and retry",
                            stderr=f"{first_missing}; {second_missing}",
                        )
                    ) from second_missing

        return output_path


class CloudInitProvisioner:
    """Provisions VMs with CloudInit configuration."""

    def __init__(self, proxmox_client):
        """Initialize with Proxmox client."""
        self.client = proxmox_client

    def create_vm_with_cloudinit(
        self,
        *,
        node: str,
        vmid: int,
        name: str,
        source_template: str,
        cloudinit_config: CloudInitConfig,
        hardware: Dict[str, Any],
        storage: Optional[str] = None,
        bridge: Optional[str] = None,
        snippet_storage: Optional[str] = None,
        timeout: int = 900,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """Clone a Proxmox template and configure native Cloud-Init."""
        cores = hardware.get("cores", 2)
        memory_mb = hardware.get("memory_mb", 2048)
        disk_gb = hardware.get("disk_gb", 20)
        payload = cloudinit_config.to_proxmox_payload()

        return self.client.create_cloudinit_vm(
            node=node,
            vmid=vmid,
            name=name,
            template=source_template,
            cores=cores,
            memory_mb=memory_mb,
            disk_gb=disk_gb,
            storage=storage,
            bridge=bridge,
            cloudinit_params=payload.native_params,
            user_data=payload.custom_user_data,
            snippet_storage=snippet_storage,
            timeout=timeout,
            poll_interval=poll_interval,
        )

    def prompt_for_config(self, template: str) -> CloudInitConfig:
        """Interactive prompt for CloudInit configuration."""
        config = CloudInitConfig(template)

        print(f"Configuring {config.template_info['name']} CloudInit setup...")

        # Hostname
        hostname = input("Enter hostname: ").strip()
        if hostname:
            fqdn = input("Enter FQDN (optional): ").strip() or None
            config.set_hostname(hostname, fqdn)

        # User configuration
        print("\n--- User Configuration ---")
        username = input(
            f"Username (default: {config.template_info['default_user']}): "
        ).strip()
        username = username or config.template_info["default_user"]

        ssh_keys = []
        print("Enter SSH public keys (press Enter twice when done):")
        while True:
            key = input("SSH key: ").strip()
            if not key:
                break
            ssh_keys.append(key)

        if ssh_keys:
            config.add_user(username, ssh_keys)

        # Package configuration
        print("\n--- Package Configuration ---")
        additional_packages = input("Additional packages (comma-separated): ").strip()
        if additional_packages:
            packages = [pkg.strip() for pkg in additional_packages.split(",")]
            config.add_packages(packages)
        else:
            config.add_packages([])  # Just default packages

        # Network configuration
        print("\n--- Network Configuration ---")
        use_dhcp = input("Use DHCP? (y/N): ").strip().lower()
        if use_dhcp != "y":
            ip = input("IP address (CIDR notation, e.g., 192.168.1.100/24): ").strip()
            gateway = input("Gateway: ").strip()
            nameservers = input("DNS servers (comma-separated): ").strip()

            if ip:
                ns_list = (
                    [ns.strip() for ns in nameservers.split(",")]
                    if nameservers
                    else None
                )
                config.set_network_config(
                    dhcp=False, ip=ip, gateway=gateway, nameservers=ns_list
                )

        # Timezone
        timezone = input("Timezone (default: UTC): ").strip() or "UTC"
        config.set_timezone(timezone)

        # Custom commands
        print("\n--- Custom Commands (optional) ---")
        commands = []
        print("Enter commands to run on first boot (press Enter twice when done):")
        while True:
            cmd = input("Command: ").strip()
            if not cmd:
                break
            commands.append(cmd)

        if commands:
            config.add_commands(commands)

        return config


# Template configurations for quick deployment
def get_ubuntu_web_server_config(
    hostname: str, ssh_keys: List[str], admin_user: str = "ubuntu"
) -> CloudInitConfig:
    """Pre-configured Ubuntu web server setup."""
    config = CloudInitConfig("ubuntu-22.04")
    config.set_hostname(hostname)
    config.add_user(admin_user, ssh_keys)
    config.add_packages(["nginx", "ufw", "certbot", "python3-certbot-nginx"])
    config.add_commands(
        [
            "systemctl enable nginx",
            "systemctl start nginx",
            "ufw allow 'Nginx Full'",
            "ufw allow ssh",
            "ufw --force enable",
        ]
    )
    return config


def get_docker_host_config(
    hostname: str, ssh_keys: List[str], admin_user: str = "ubuntu"
) -> CloudInitConfig:
    """Pre-configured Docker host setup."""
    config = CloudInitConfig("ubuntu-22.04")
    config.set_hostname(hostname)
    config.add_user(admin_user, ssh_keys)
    config.add_packages(["docker.io", "docker-compose", "curl"])
    config.add_commands(
        [
            f"usermod -aG docker {admin_user}",
            "systemctl enable docker",
            "systemctl start docker",
        ]
    )
    return config


def get_development_config(
    hostname: str, ssh_keys: List[str], admin_user: str = "fedora"
) -> CloudInitConfig:
    """Pre-configured development environment."""
    config = CloudInitConfig("fedora-40")
    config.set_hostname(hostname)
    config.add_user(admin_user, ssh_keys)
    config.add_packages(
        [
            "git",
            "vim",
            "tmux",
            "nodejs",
            "npm",
            "python3",
            "python3-pip",
            "gcc",
            "make",
            "golang",
            "docker",
            "podman",
        ]
    )
    config.add_commands(
        [
            f"usermod -aG docker {admin_user}",
            "systemctl enable docker",
            "systemctl start docker",
        ]
    )
    return config
