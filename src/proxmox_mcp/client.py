from __future__ import annotations

import os
import re
import ssl
import time
import tempfile
import ipaddress
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from proxmoxer import ProxmoxAPI

from .utils import parse_api_url, read_env, split_token_id, require_allowed_url


VM_DISK_PREFIXES = ("ide", "sata", "scsi", "virtio")
VM_UNUSED_DISK_PREFIX = "unused"

VM_USB_PREFIX = "usb"
VM_USB_MAX_SLOTS = 14  # Proxmox 8+ supports usb0..usb14 with xhci

VM_PCI_PREFIX = "hostpci"
VM_PCI_MAX_SLOTS = 16  # Proxmox 8+ supports hostpci0..hostpci15

# host=VID:PID  (lowercase hex, 4-digit each)
_USB_VIDPID_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")
# host=<bus>-<port>[.<port>...]  e.g. 1-2 or 1-2.4
_USB_BUSPORT_RE = re.compile(r"^\d+-\d+(?:\.\d+)*$")
# PCI address: [DDDD:]BB:DD.F  domain optional
_PCI_ADDR_RE = re.compile(r"^(?:[0-9a-f]{4}:)?[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")
# Cluster mapping names: letters, digits, dash, underscore
_MAPPING_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
TESTED_PROXMOX_VE_VERSION = "9.1.6"
TESTED_PROXMOX_VE_SERIES = (9, 1)
TESTED_PROXMOX_VE_SERIES_LABEL = "9.1.x"
_PROXMOX_VERSION_PATTERN = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)(?:\.\d+)?$")
_DISK_SIZE_PATTERN = re.compile(
    r"(?:^|,)size=(?P<size>\d+(?:\.\d+)?)(?P<unit>[KMGT])(?:i?B|B)?(?:,|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProxmoxVersionCompatibility:
    detected_version: Optional[str]
    compatible: Optional[bool]


_VERSION_COMPATIBILITY_CACHE: Dict[Tuple[str, str], ProxmoxVersionCompatibility] = {}


def _parse_proxmox_version_series(version: Optional[str]) -> Optional[Tuple[int, int]]:
    if not version:
        return None

    match = _PROXMOX_VERSION_PATTERN.match(version.strip())
    if not match:
        return None

    return int(match.group("major")), int(match.group("minor"))


def _parse_disk_size_gb(config_value: str) -> Optional[int]:
    match = _DISK_SIZE_PATTERN.search(config_value)
    if not match:
        return None

    size = float(match.group("size"))
    unit = match.group("unit").upper()
    multipliers = {"K": 1 / (1024 * 1024), "M": 1 / 1024, "G": 1, "T": 1024}
    size_gb = size * multipliers[unit]
    return max(1, int(size_gb) if size_gb.is_integer() else int(size_gb) + 1)


def _encode_sshkeys(value: str) -> str:
    """URL-encode SSH keys for the Proxmox `sshkeys` config field.

    Proxmox stores the value as URL-encoded text with a trailing %0A.
    If the input already round-trips through urllib.parse.unquote to a
    different string, it's already encoded and is returned unchanged.
    """
    if not value:
        return value
    if "%" in value and urllib.parse.unquote(value) != value:
        return value
    text = value if value.endswith("\n") else value + "\n"
    return urllib.parse.quote(text, safe="")


class _TLSHttpAdapter(HTTPAdapter):
    def __init__(self, ssl_context: ssl.SSLContext, *args: Any, **kwargs: Any) -> None:
        self.ssl_context = ssl_context
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args: Any, **kwargs: Any):
        kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(*args, **kwargs)


def configure_proxmox_https_session(session: requests.Session) -> requests.Session:
    """Mount a stable HTTPS adapter for Proxmox API traffic.

    Some environments negotiate TLS to Proxmox successfully with curl but hit
    intermittent EOF/handshake issues through the default Python requests stack.
    Mounting an explicit SSL context on the session makes the behavior reliable.
    """
    session.mount("https://", _TLSHttpAdapter(ssl.create_default_context()))
    return session


def get_default_lxc_password() -> str:
    """Return the configured default LXC password or fail closed."""
    password = os.environ.get("PROXMOX_DEFAULT_LXC_PASSWORD", "").strip()
    if not password:
        raise ValueError(
            "PROXMOX_DEFAULT_LXC_PASSWORD must be set before creating an LXC container"
        )
    return password


class ProxmoxClient:
    """Wrapper around proxmoxer.ProxmoxAPI with helper methods and sane defaults."""

    def __init__(
        self,
        *,
        base_url: str,
        token_id: str,
        token_secret: str,
        verify: bool,
        default_node: Optional[str] = None,
        default_storage: Optional[str] = None,
        default_bridge: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url
        self.token_id = token_id
        self.token_secret = token_secret
        self.verify = verify
        self.default_node = default_node
        self.default_storage = default_storage
        self.default_bridge = default_bridge
        self.timeout = timeout

        url = parse_api_url(base_url)
        self.host = url["host"]
        self.port = url["port"]
        self.scheme = url["scheme"]
        token_parts = split_token_id(token_id)
        self._api = ProxmoxAPI(
            self.host,
            port=self.port,
            user=token_parts["user"],
            token_name=token_parts["token_name"],
            token_value=token_secret,
            verify_ssl=verify,
            timeout=timeout,
        )
        configure_proxmox_https_session(self._api._store["session"])

    @classmethod
    def from_env(cls) -> "ProxmoxClient":
        env = read_env()
        return cls(
            base_url=env.base_url,
            token_id=env.token_id,
            token_secret=env.token_secret,
            verify=env.verify,
            default_node=env.default_node,
            default_storage=env.default_storage,
            default_bridge=env.default_bridge,
        )

    # Low-level accessor
    @property
    def api(self) -> ProxmoxAPI:
        return self._api

    # -------- Core discovery --------
    def get_version_info(self) -> Dict[str, Any]:
        return self._api.version.get()

    def get_version_compatibility(self) -> ProxmoxVersionCompatibility:
        cache_key = (self.base_url, self.token_id)
        cached = _VERSION_COMPATIBILITY_CACHE.get(cache_key)
        if cached is not None:
            return cached

        try:
            version_info = self.get_version_info()
        except Exception:
            compatibility = ProxmoxVersionCompatibility(
                detected_version=None,
                compatible=None,
            )
            _VERSION_COMPATIBILITY_CACHE[cache_key] = compatibility
            return compatibility

        detected_version = str(version_info.get("version") or "").strip() or None
        detected_series = _parse_proxmox_version_series(detected_version)

        if detected_series is None:
            compatibility = ProxmoxVersionCompatibility(
                detected_version=detected_version,
                compatible=None,
            )
        else:
            compatibility = ProxmoxVersionCompatibility(
                detected_version=detected_version,
                compatible=detected_series == TESTED_PROXMOX_VE_SERIES,
            )

        _VERSION_COMPATIBILITY_CACHE[cache_key] = compatibility
        return compatibility

    def get_version_compatibility_payload(self) -> Dict[str, Any]:
        compatibility = self.get_version_compatibility()
        return {
            "detected_version": compatibility.detected_version,
            "tested_version": TESTED_PROXMOX_VE_VERSION,
            "tested_series": TESTED_PROXMOX_VE_SERIES_LABEL,
            "compatible": compatibility.compatible,
        }

    def list_nodes(self) -> List[Dict[str, Any]]:
        return self._api.nodes.get()

    def get_node_status(self, node: str) -> Dict[str, Any]:
        return self._api.nodes(node).status.get()

    def list_vms(
        self,
        node: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        vms = self._api.cluster.resources.get(type="vm")
        if node:
            vms = [v for v in vms if v.get("node") == node]
        if status:
            vms = [v for v in vms if v.get("status") == status]
        if search:
            s = search.lower()
            vms = [v for v in vms if s in str(v.get("name", "")).lower()]
        return vms

    def list_lxc(
        self,
        node: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        lxcs = self._api.cluster.resources.get(type="lxc")
        if node:
            lxcs = [c for c in lxcs if c.get("node") == node]
        if status:
            lxcs = [c for c in lxcs if c.get("status") == status]
        if search:
            s = search.lower()
            lxcs = [c for c in lxcs if s in str(c.get("name", "")).lower()]
        return lxcs

    def list_vm_templates(
        self,
        node: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        templates = [
            vm
            for vm in self._api.cluster.resources.get(type="vm")
            if vm.get("template")
        ]
        if node:
            templates = [vm for vm in templates if vm.get("node") == node]
        if search:
            needle = search.lower()
            templates = [
                vm for vm in templates if needle in str(vm.get("name", "")).lower()
            ]
        return templates

    def resolve_vm(
        self,
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
    ) -> Tuple[int, str, Dict[str, Any]]:
        resources = self._api.cluster.resources.get(type="vm")
        candidates: List[Dict[str, Any]] = []
        if vmid is not None:
            candidates = [r for r in resources if r.get("vmid") == vmid]
        elif name is not None:
            candidates = [r for r in resources if r.get("name") == name]
        else:
            raise ValueError("Provide either vmid or name")

        if node:
            candidates = [r for r in candidates if r.get("node") == node]

        if not candidates:
            raise ValueError("VM not found with given selector")
        if len(candidates) > 1 and not node:
            raise ValueError("Multiple VMs match name; specify node")

        vm = candidates[0]
        return int(vm["vmid"]), str(vm["node"]), vm

    def resolve_vm_template(
        self,
        template: str | int,
        node: Optional[str] = None,
    ) -> Tuple[int, str, Dict[str, Any]]:
        if isinstance(template, int) or (
            isinstance(template, str) and template.strip().isdigit()
        ):
            vm_vmid, vm_node, vm = self.resolve_vm(vmid=int(template), node=node)
        else:
            vm_vmid, vm_node, vm = self.resolve_vm(name=str(template), node=node)

        if not vm.get("template"):
            raise ValueError(
                f"VM '{template}' exists but is not marked as a Proxmox template"
            )
        return vm_vmid, vm_node, vm

    def resolve_lxc(
        self,
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
    ) -> Tuple[int, str, Dict[str, Any]]:
        resources = self._api.cluster.resources.get(type="lxc")
        candidates: List[Dict[str, Any]] = []
        if vmid is not None:
            candidates = [r for r in resources if r.get("vmid") == vmid]
        elif name is not None:
            candidates = [r for r in resources if r.get("name") == name]
        else:
            raise ValueError("Provide either vmid or name")

        if node:
            candidates = [r for r in candidates if r.get("node") == node]

        if not candidates:
            raise ValueError("LXC not found with given selector")
        if len(candidates) > 1 and not node:
            raise ValueError("Multiple LXCs match name; specify node")

        ct = candidates[0]
        return int(ct["vmid"]), str(ct["node"]), ct

    def vm_config(self, node: str, vmid: int) -> Dict[str, Any]:
        return self._api.nodes(node).qemu(vmid).config.get()

    def list_vm_disks(self, node: str, vmid: int) -> Dict[str, Dict[str, Any]]:
        config = self.vm_config(node, vmid)
        disks: Dict[str, Dict[str, Any]] = {}
        for key, value in config.items():
            if not key.startswith(VM_DISK_PREFIXES):
                continue
            disks[key] = {
                "device": key,
                "config": value,
                "interface": "".join(ch for ch in key if not ch.isdigit()),
                "slot": int("".join(ch for ch in key if ch.isdigit()) or "0"),
            }
        return dict(sorted(disks.items(), key=lambda item: item[0]))

    def list_vm_unused_disks(self, node: str, vmid: int) -> Dict[str, Dict[str, Any]]:
        config = self.vm_config(node, vmid)
        disks: Dict[str, Dict[str, Any]] = {}
        for key, value in config.items():
            if not key.startswith(VM_UNUSED_DISK_PREFIX):
                continue
            disks[key] = {
                "device": key,
                "config": value,
                "slot": int("".join(ch for ch in key if ch.isdigit()) or "0"),
            }
        return dict(sorted(disks.items(), key=lambda item: item[0]))

    def _next_unused_disk_key(self, config: Dict[str, Any]) -> str:
        used_slots = {
            int(key.removeprefix(VM_UNUSED_DISK_PREFIX))
            for key in config
            if key.startswith(VM_UNUSED_DISK_PREFIX)
            and key.removeprefix(VM_UNUSED_DISK_PREFIX).isdigit()
        }
        slot = 0
        while slot in used_slots:
            slot += 1
        return f"{VM_UNUSED_DISK_PREFIX}{slot}"

    def add_vm_disk(
        self,
        node: str,
        vmid: int,
        *,
        interface: str = "scsi",
        slot: Optional[int] = None,
        storage: Optional[str] = None,
        size_gb: Optional[int] = None,
        volume: Optional[str] = None,
        format: Optional[str] = None,
        ssd: bool = False,
        cache: Optional[str] = None,
    ) -> Dict[str, Any]:
        if interface not in VM_DISK_PREFIXES:
            supported = ", ".join(VM_DISK_PREFIXES)
            raise ValueError(
                f"Unsupported disk interface '{interface}'. Supported: {supported}"
            )
        if not volume and (size_gb is None or size_gb <= 0):
            raise ValueError("Provide either volume or size_gb > 0")

        config = self.vm_config(node, vmid)
        if slot is None:
            used_slots = {
                int(key.removeprefix(interface))
                for key in config
                if key.startswith(interface) and key.removeprefix(interface).isdigit()
            }
            slot = 0
            while slot in used_slots:
                slot += 1
        elif f"{interface}{slot}" in config:
            raise ValueError(f"Disk slot already in use: {interface}{slot}")

        storage_id = storage or self.default_storage or "local-lvm"
        disk_value = volume or f"{storage_id}:{size_gb}"
        disk_options: List[str] = []
        if format:
            disk_options.append(f"format={format}")
        if ssd:
            disk_options.append("ssd=1")
        if cache:
            disk_options.append(f"cache={cache}")
        if disk_options:
            disk_value = f"{disk_value},{','.join(disk_options)}"

        device = f"{interface}{slot}"
        upid = self._api.nodes(node).qemu(vmid).config.put(**{device: disk_value})
        return {"upid": upid, "device": device, "config": disk_value}

    def detach_vm_disk(
        self,
        node: str,
        vmid: int,
        *,
        device: str,
    ) -> Dict[str, Any]:
        config = self.vm_config(node, vmid)
        if device not in config:
            raise ValueError(f"Disk device not attached: {device}")
        upid = self._api.nodes(node).qemu(vmid).config.put(delete=device)
        predicted_unused_device = self._next_unused_disk_key(config)
        return {
            "upid": upid,
            "removed": device,
            "previous_config": config[device],
            "retained_as": predicted_unused_device,
            "mode": "detach",
        }

    def delete_vm_disk_volume(
        self,
        node: str,
        vmid: int,
        *,
        device: str,
        timeout: int = 600,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        config = self.vm_config(node, vmid)
        if device not in config:
            raise ValueError(f"Disk device not attached: {device}")

        previous_config = config[device]
        if device.startswith(VM_UNUSED_DISK_PREFIX):
            delete_upid = self._api.nodes(node).qemu(vmid).config.put(delete=device)
            return {
                "delete_upid": delete_upid,
                "removed": device,
                "previous_config": previous_config,
                "mode": "delete-volume",
            }

        detach_result = self.detach_vm_disk(node, vmid, device=device)
        self.wait_task(
            detach_result["upid"],
            node=node,
            timeout=timeout,
            poll_interval=poll_interval,
        )

        refreshed_config = self.vm_config(node, vmid)
        unused_device = next(
            (
                key
                for key, value in refreshed_config.items()
                if key.startswith(VM_UNUSED_DISK_PREFIX) and value == previous_config
            ),
            None,
        )
        if unused_device is None:
            raise RuntimeError(
                f"Detached disk {device} did not appear as an unused disk; refusing destructive delete"
            )

        delete_upid = self._api.nodes(node).qemu(vmid).config.put(delete=unused_device)
        return {
            "detach_upid": detach_result["upid"],
            "delete_upid": delete_upid,
            "removed": device,
            "deleted_unused_device": unused_device,
            "previous_config": previous_config,
            "mode": "delete-volume",
        }

    def remove_vm_disk(
        self,
        node: str,
        vmid: int,
        *,
        device: str,
    ) -> Dict[str, Any]:
        return self.detach_vm_disk(node, vmid, device=device)

    def lxc_config(self, node: str, vmid: int) -> Dict[str, Any]:
        return self._api.nodes(node).lxc(vmid).config.get()

    def list_storage(self) -> List[Dict[str, Any]]:
        return self._api.storage.get()

    def storage_status(self, node: str, storage: str) -> Dict[str, Any]:
        return self._api.nodes(node).storage(storage).status.get()

    def storage_content(self, node: str, storage: str) -> List[Dict[str, Any]]:
        return self._api.nodes(node).storage(storage).content.get()

    def list_bridges(self, node: str) -> List[Dict[str, Any]]:
        nets = self._api.nodes(node).network.get()
        return [
            n
            for n in nets
            if n.get("type") == "bridge" or str(n.get("iface", "")).startswith("vmbr")
        ]

    def list_tasks(
        self, node: Optional[str] = None, user: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        tasks = self._api.cluster.tasks.get()
        if node:
            tasks = [t for t in tasks if t.get("node") == node]
        if user:
            tasks = [t for t in tasks if t.get("user") == user]
        return tasks[:limit]

    def task_status(self, upid: str, node: Optional[str] = None) -> Dict[str, Any]:
        # If node is unknown, try cluster lookup then fall back to nodes
        try:
            status = self._api.cluster.tasks(upid).status.get()
            if isinstance(status, dict) and status.get("status") is not None:
                return status
        except Exception:
            pass

        if not node:
            raise ValueError(
                "node is required when cluster task status lookup is unavailable"
            )

        try:
            status = self._api.nodes(node).tasks(upid).status.get()
            if isinstance(status, dict) and status.get("status") is not None:
                return status
        except Exception:
            pass

        tasks = self._api.nodes(node).tasks.get(source="all", limit=100)
        if isinstance(tasks, list):
            for task in tasks:
                if isinstance(task, dict) and task.get("upid") == upid:
                    return task

        raise RuntimeError(f"Unable to resolve task status for {upid}")

    # -------- VM lifecycle --------
    def clone_vm(
        self,
        *,
        source_node: str,
        source_vmid: int,
        target_node: Optional[str],
        new_vmid: int,
        name: Optional[str] = None,
        full: bool = True,
        storage: Optional[str] = None,
    ) -> str:
        params: Dict[str, Any] = {"newid": new_vmid, "full": int(full)}
        if name:
            params["name"] = name
        if target_node:
            params["target"] = target_node
        if storage:
            params["storage"] = storage
        return (
            self._api.nodes(source_node).qemu(source_vmid).clone.post(**params)
        )  # returns upid

    def create_vm(
        self,
        *,
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
        boot_order: Optional[str] = None,
    ) -> str:
        storage_id = storage or self.default_storage or "local-lvm"
        bridge_id = bridge or self.default_bridge or "vmbr0"
        params: Dict[str, Any] = {
            "vmid": vmid,
            "name": name,
            "cores": cores,
            "memory": memory_mb,
            "scsihw": scsihw,
            "agent": int(agent),
            "ostype": ostype,
            "net0": f"virtio,bridge={bridge_id}",
        }
        if disk_gb > 0:
            params["scsi0"] = f"{storage_id}:{disk_gb}"
        if iso:
            # ide2 expects format storage:iso/filename.iso,media=cdrom
            params["ide2"] = iso if ":" in iso else f"{storage_id}:iso/{iso}"
            params["boot"] = "order=scsi0;ide2;net0"
        if boot_order is not None:
            params["boot"] = (
                boot_order if "=" in boot_order else f"order={boot_order}"
            )
        return self._api.nodes(node).qemu.post(**params)

    def delete_vm(self, node: str, vmid: int, purge: bool = True) -> str:
        return self._api.nodes(node).qemu(vmid).delete(purge=int(purge))

    def start_vm(self, node: str, vmid: int) -> str:
        return self._api.nodes(node).qemu(vmid).status.start.post()

    def stop_vm(
        self,
        node: str,
        vmid: int,
        overrule_shutdown: bool = False,
        timeout: Optional[int] = None,
        force: Optional[bool] = None,
    ) -> str:
        params: Dict[str, Any] = {}
        if force is not None:
            overrule_shutdown = overrule_shutdown or force
        if overrule_shutdown:
            params["overrule-shutdown"] = 1
        if timeout is not None:
            params["timeout"] = int(timeout)
        return self._api.nodes(node).qemu(vmid).status.stop.post(**params)

    def reboot_vm(self, node: str, vmid: int) -> str:
        return self._api.nodes(node).qemu(vmid).status.reboot.post()

    def shutdown_vm(self, node: str, vmid: int, timeout: Optional[int] = None) -> str:
        params: Dict[str, Any] = {}
        if timeout is not None:
            params["timeout"] = int(timeout)
        return self._api.nodes(node).qemu(vmid).status.shutdown.post(**params)

    def migrate_vm(
        self, node: str, vmid: int, target_node: str, online: bool = True
    ) -> str:
        return (
            self._api.nodes(node)
            .qemu(vmid)
            .migrate.post(target=target_node, online=int(online))
        )

    def resize_vm_disk(self, node: str, vmid: int, disk: str, size_gb: int) -> str:
        # size format like +10G to grow
        return (
            self._api.nodes(node).qemu(vmid).resize.put(disk=disk, size=f"+{size_gb}G")
        )

    def configure_vm(
        self, node: str, vmid: int, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        # Returns a task upid for most changes; some return nothing. Normalize to dict
        upid = self._api.nodes(node).qemu(vmid).config.put(**params)
        return {"upid": upid} if isinstance(upid, str) else {"result": upid}

    # -------- LXC lifecycle --------
    def create_lxc(
        self,
        *,
        node: str,
        vmid: int,
        hostname: str,
        ostemplate: str,
        cores: int = 2,
        memory_mb: int = 1024,
        rootfs_gb: int = 8,
        storage: Optional[str] = None,
        bridge: Optional[str] = None,
        net_ip: Optional[str] = None,  # e.g. "dhcp" or "192.168.1.50/24,gw=192.168.1.1"
    ) -> str:
        storage_id = storage or self.default_storage or "local-lvm"
        bridge_id = bridge or self.default_bridge or "vmbr0"
        rootfs = f"{storage_id}:{max(rootfs_gb, 1)}"
        net0 = f"name=eth0,bridge={bridge_id},ip={net_ip or 'dhcp'}"
        params: Dict[str, Any] = {
            "vmid": vmid,
            "hostname": hostname,
            "cores": cores,
            "memory": memory_mb,
            "ostemplate": ostemplate
            if ":" in ostemplate
            else f"{storage_id}:vztmpl/{ostemplate}",
            "rootfs": rootfs,
            "net0": net0,
            "password": get_default_lxc_password(),
        }
        return self._api.nodes(node).lxc.post(**params)

    def delete_lxc(self, node: str, vmid: int, purge: bool = True) -> str:
        return self._api.nodes(node).lxc(vmid).delete(purge=int(purge))

    def start_lxc(self, node: str, vmid: int) -> str:
        return self._api.nodes(node).lxc(vmid).status.start.post()

    def stop_lxc(self, node: str, vmid: int, timeout: Optional[int] = None) -> str:
        params: Dict[str, Any] = {}
        if timeout is not None:
            params["timeout"] = int(timeout)
        return self._api.nodes(node).lxc(vmid).status.stop.post(**params)

    def configure_lxc(
        self, node: str, vmid: int, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        upid = self._api.nodes(node).lxc(vmid).config.put(**params)
        return {"upid": upid} if isinstance(upid, str) else {"result": upid}

    # -------- Cloud-init & networking --------
    def cloudinit_set(
        self, node: str, vmid: int, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        params = dict(params)
        if "sshkeys" in params and params["sshkeys"] is not None:
            params["sshkeys"] = _encode_sshkeys(params["sshkeys"])
        upid = self._api.nodes(node).qemu(vmid).config.put(**params)
        return {"upid": upid} if isinstance(upid, str) else {"result": upid}

    def ensure_cloudinit_drive(
        self,
        node: str,
        vmid: int,
        storage: Optional[str] = None,
    ) -> Dict[str, Any]:
        config = self.vm_config(node, vmid)
        for device, value in config.items():
            if isinstance(value, str) and ":cloudinit" in value:
                return {"present": True, "device": device, "config": value}

        if "ide2" in config:
            raise ValueError(
                "VM uses ide2 for non-cloud-init media; free ide2 or attach a cloud-init drive manually"
            )

        storage_id = storage or self.default_storage or "local-lvm"
        config_value = f"{storage_id}:cloudinit"
        upid = self._api.nodes(node).qemu(vmid).config.put(ide2=config_value)
        return {
            "added": True,
            "device": "ide2",
            "config": config_value,
            "storage": storage_id,
            "upid": upid,
        }

    def upload_snippet(self, node: str, storage: str, file_path: str) -> str:
        with open(file_path, "rb") as f:
            return (
                self._api.nodes(node)
                .storage(storage)
                .upload.post(
                    content="snippets", filename=os.path.basename(file_path), file=f
                )
            )

    def apply_cloudinit_config(
        self,
        node: str,
        vmid: int,
        *,
        cloudinit_params: Optional[Dict[str, Any]] = None,
        user_data: Optional[str] = None,
        storage: Optional[str] = None,
        snippet_storage: Optional[str] = None,
        timeout: int = 900,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        drive = self.ensure_cloudinit_drive(node, vmid, storage=storage)
        result["cloudinit_drive"] = drive
        if "upid" in drive:
            result["cloudinit_drive_status"] = self.wait_task(
                drive["upid"],
                node=node,
                timeout=timeout,
                poll_interval=poll_interval,
            )

        params = dict(cloudinit_params or {})
        if user_data:
            snippet_storage_id = snippet_storage or "local"
            temp_path = ""
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", delete=False, suffix=".yaml", encoding="utf-8"
                ) as temp_file:
                    temp_file.write(user_data)
                    temp_path = temp_file.name
                upload_upid = self.upload_snippet(node, snippet_storage_id, temp_path)
                result["snippet_upload_upid"] = upload_upid
                result["snippet_upload_status"] = self.wait_task(
                    upload_upid,
                    node=node,
                    timeout=timeout,
                    poll_interval=poll_interval,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Unable to upload Cloud-Init snippet to storage '{snippet_storage_id}'. "
                    "Use a storage that supports snippets, such as 'local'."
                ) from exc
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)

            snippet_name = os.path.basename(temp_path)
            params["cicustom"] = f"user={snippet_storage_id}:snippets/{snippet_name}"
            result["cicustom"] = params["cicustom"]

        if not params:
            return result

        result["config"] = params
        config_result = self.configure_vm(node, vmid, params)
        result.update(config_result)
        return result

    def _get_primary_disk(
        self, node: str, vmid: int
    ) -> Tuple[Optional[str], Optional[int]]:
        config = self.vm_config(node, vmid)
        for device in sorted(config):
            if not device.startswith(VM_DISK_PREFIXES):
                continue
            value = str(config[device])
            if "media=cdrom" in value or ":cloudinit" in value:
                continue
            return device, _parse_disk_size_gb(value)
        return None, None

    def vm_nic_add(
        self,
        node: str,
        vmid: int,
        bridge: str,
        model: str = "virtio",
        vlan: Optional[int] = None,
    ) -> Dict[str, Any]:
        cfg = self.vm_config(node, vmid)
        used = sorted(
            int(k.replace("net", "")) for k in cfg.keys() if k.startswith("net")
        )
        idx = 0
        while idx in used:
            idx += 1
        parts = [model]
        parts.append(f"bridge={bridge}")
        if vlan is not None:
            parts.append(f"tag={vlan}")
        net_val = ",".join(parts)
        upid = self._api.nodes(node).qemu(vmid).config.put(**{f"net{idx}": net_val})
        return {"upid": upid, "added": f"net{idx}"}

    def vm_nic_remove(self, node: str, vmid: int, slot: int) -> Dict[str, Any]:
        upid = self._api.nodes(node).qemu(vmid).config.put(delete=f"net{slot}")
        return {"upid": upid, "removed": f"net{slot}"}

    # -------- USB passthrough (hot-pluggable) --------
    def list_host_usb(self, node: str) -> List[Dict[str, Any]]:
        return self._api.nodes(node).hardware.usb.get()

    def list_cluster_usb_mappings(self) -> List[Dict[str, Any]]:
        return self._api.cluster.mapping.usb.get()

    @staticmethod
    def _parse_usb_value(value: str) -> Dict[str, Any]:
        parts = [p.strip() for p in str(value).split(",") if p.strip()]
        parsed: Dict[str, Any] = {"raw": value}
        for part in parts:
            if "=" not in part:
                continue
            key, val = part.split("=", 1)
            if key == "host":
                if val == "spice":
                    parsed["spice"] = True
                elif _USB_VIDPID_RE.match(val):
                    parsed["host_vendor_product"] = val
                elif _USB_BUSPORT_RE.match(val):
                    parsed["host_bus_port"] = val
                else:
                    parsed["host"] = val
            elif key == "mapping":
                parsed["mapping"] = val
            elif key == "usb3":
                parsed["usb3"] = val in ("1", "true", "yes")
        return parsed

    def list_vm_usb(self, node: str, vmid: int) -> List[Dict[str, Any]]:
        config = self.vm_config(node, vmid)
        out: List[Dict[str, Any]] = []
        for key, value in config.items():
            if not (key.startswith(VM_USB_PREFIX) and key[len(VM_USB_PREFIX):].isdigit()):
                continue
            entry = {
                "device": key,
                "slot": int(key[len(VM_USB_PREFIX):]),
                "config": value,
                **self._parse_usb_value(value),
            }
            out.append(entry)
        return sorted(out, key=lambda e: e["slot"])

    @staticmethod
    def _build_usb_value(
        host: Optional[str],
        mapping: Optional[str],
        spice: bool,
        usb3: bool,
    ) -> str:
        sources = sum(1 for v in (host, mapping, spice) if v)
        if sources != 1:
            raise ValueError(
                "Provide exactly one of host, mapping, or spice=True"
            )
        if host is not None:
            if not (_USB_VIDPID_RE.match(host) or _USB_BUSPORT_RE.match(host)):
                raise ValueError(
                    f"Invalid USB host '{host}'. Expected VID:PID (4-hex:4-hex) "
                    "or bus-port (e.g. 1-2 or 1-2.4)"
                )
            parts = [f"host={host}"]
        elif mapping is not None:
            if not _MAPPING_NAME_RE.match(mapping):
                raise ValueError(
                    f"Invalid mapping name '{mapping}'"
                )
            parts = [f"mapping={mapping}"]
        else:
            parts = ["host=spice"]
        if usb3:
            parts.append("usb3=1")
        return ",".join(parts)

    def vm_usb_add(
        self,
        node: str,
        vmid: int,
        *,
        host: Optional[str] = None,
        mapping: Optional[str] = None,
        spice: bool = False,
        usb3: bool = False,
        slot: Optional[int] = None,
    ) -> Dict[str, Any]:
        value = self._build_usb_value(host, mapping, spice, usb3)
        config = self.vm_config(node, vmid)
        used = {
            int(k[len(VM_USB_PREFIX):])
            for k in config
            if k.startswith(VM_USB_PREFIX) and k[len(VM_USB_PREFIX):].isdigit()
        }
        if slot is not None:
            if slot < 0 or slot >= VM_USB_MAX_SLOTS:
                raise ValueError(
                    f"slot must be in [0, {VM_USB_MAX_SLOTS - 1}]"
                )
            if slot in used:
                raise ValueError(f"usb{slot} is already in use")
            chosen = slot
        else:
            chosen = 0
            while chosen in used:
                chosen += 1
            if chosen >= VM_USB_MAX_SLOTS:
                raise ValueError(
                    f"No free USB slots (0..{VM_USB_MAX_SLOTS - 1} all in use)"
                )
        device = f"{VM_USB_PREFIX}{chosen}"
        upid = self._api.nodes(node).qemu(vmid).config.put(**{device: value})
        return {"upid": upid, "added": device, "config": value}

    def vm_usb_remove(self, node: str, vmid: int, slot: int) -> Dict[str, Any]:
        device = f"{VM_USB_PREFIX}{slot}"
        upid = self._api.nodes(node).qemu(vmid).config.put(delete=device)
        return {"upid": upid, "removed": device}

    # -------- PCI passthrough (NOT hot-pluggable; change applies on next start) --------
    def list_host_pci(self, node: str) -> List[Dict[str, Any]]:
        return self._api.nodes(node).hardware.pci.get()

    def list_cluster_pci_mappings(self) -> List[Dict[str, Any]]:
        return self._api.cluster.mapping.pci.get()

    @staticmethod
    def _parse_pci_value(value: str) -> Dict[str, Any]:
        parts = [p.strip() for p in str(value).split(",") if p.strip()]
        parsed: Dict[str, Any] = {"raw": value}
        # First bare token (no =) is the host address shorthand
        for part in parts:
            if "=" not in part:
                if _PCI_ADDR_RE.match(part):
                    parsed["host"] = part
                continue
            key, val = part.split("=", 1)
            if key == "host":
                parsed["host"] = val
            elif key == "mapping":
                parsed["mapping"] = val
            elif key == "mdev":
                parsed["mdev"] = val
            elif key == "pcie":
                parsed["pcie"] = val in ("1", "true", "yes")
            elif key == "rombar":
                parsed["rombar"] = val in ("1", "true", "yes")
            elif key == "x-vga":
                parsed["x_vga"] = val in ("1", "true", "yes")
            elif key == "romfile":
                parsed["romfile"] = val
        return parsed

    def list_vm_pci(self, node: str, vmid: int) -> List[Dict[str, Any]]:
        config = self.vm_config(node, vmid)
        out: List[Dict[str, Any]] = []
        for key, value in config.items():
            if not (key.startswith(VM_PCI_PREFIX) and key[len(VM_PCI_PREFIX):].isdigit()):
                continue
            entry = {
                "device": key,
                "slot": int(key[len(VM_PCI_PREFIX):]),
                "config": value,
                **self._parse_pci_value(value),
            }
            out.append(entry)
        return sorted(out, key=lambda e: e["slot"])

    @staticmethod
    def _build_pci_value(
        host: Optional[str],
        mapping: Optional[str],
        pcie: bool,
        rombar: Optional[bool],
        x_vga: bool,
        mdev: Optional[str],
        romfile: Optional[str],
    ) -> str:
        if (host is None) == (mapping is None):
            raise ValueError("Provide exactly one of host or mapping")
        if host is not None:
            if not _PCI_ADDR_RE.match(host):
                raise ValueError(
                    f"Invalid PCI address '{host}'. Expected [DDDD:]BB:DD.F "
                    "(e.g. 0000:01:00.0 or 01:00.0)"
                )
            parts = [f"host={host}"]
        else:
            assert mapping is not None
            if not _MAPPING_NAME_RE.match(mapping):
                raise ValueError(f"Invalid mapping name '{mapping}'")
            parts = [f"mapping={mapping}"]
        if pcie:
            parts.append("pcie=1")
        if rombar is False:
            parts.append("rombar=0")
        if x_vga:
            parts.append("x-vga=1")
        if mdev:
            parts.append(f"mdev={mdev}")
        if romfile:
            parts.append(f"romfile={romfile}")
        return ",".join(parts)

    def vm_pci_add(
        self,
        node: str,
        vmid: int,
        *,
        host: Optional[str] = None,
        mapping: Optional[str] = None,
        pcie: bool = False,
        rombar: Optional[bool] = None,
        x_vga: bool = False,
        mdev: Optional[str] = None,
        romfile: Optional[str] = None,
        slot: Optional[int] = None,
    ) -> Dict[str, Any]:
        value = self._build_pci_value(
            host, mapping, pcie, rombar, x_vga, mdev, romfile
        )
        config = self.vm_config(node, vmid)
        used = {
            int(k[len(VM_PCI_PREFIX):])
            for k in config
            if k.startswith(VM_PCI_PREFIX) and k[len(VM_PCI_PREFIX):].isdigit()
        }
        if slot is not None:
            if slot < 0 or slot >= VM_PCI_MAX_SLOTS:
                raise ValueError(
                    f"slot must be in [0, {VM_PCI_MAX_SLOTS - 1}]"
                )
            if slot in used:
                raise ValueError(f"hostpci{slot} is already in use")
            chosen = slot
        else:
            chosen = 0
            while chosen in used:
                chosen += 1
            if chosen >= VM_PCI_MAX_SLOTS:
                raise ValueError(
                    f"No free PCI slots (0..{VM_PCI_MAX_SLOTS - 1} all in use)"
                )
        device = f"{VM_PCI_PREFIX}{chosen}"
        upid = self._api.nodes(node).qemu(vmid).config.put(**{device: value})
        return {"upid": upid, "added": device, "config": value}

    def vm_pci_remove(self, node: str, vmid: int, slot: int) -> Dict[str, Any]:
        device = f"{VM_PCI_PREFIX}{slot}"
        upid = self._api.nodes(node).qemu(vmid).config.put(delete=device)
        return {"upid": upid, "removed": device}

    def vm_firewall_get(self, node: str, vmid: int) -> Dict[str, Any]:
        opts = self._api.nodes(node).qemu(vmid).firewall.options.get()
        rules = self._api.nodes(node).qemu(vmid).firewall.rules.get()
        return {"options": opts, "rules": rules}

    def vm_firewall_set(
        self,
        node: str,
        vmid: int,
        enable: Optional[bool] = None,
        rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if enable is not None:
            upid = (
                self._api.nodes(node)
                .qemu(vmid)
                .firewall.options.put(enable=int(enable))
            )
            result["options_upid"] = upid
        if rules:
            # Very simple approach: append new rules at the end
            for rule in rules:
                self._api.nodes(node).qemu(vmid).firewall.rules.post(**rule)
            result["rules_added"] = len(rules)
        return result

    # -------- Images, templates, snapshots, backups --------
    def upload_iso(self, node: str, storage: str, file_path: str) -> str:
        with open(file_path, "rb") as f:
            return (
                self._api.nodes(node)
                .storage(storage)
                .upload.post(
                    content="iso", filename=os.path.basename(file_path), file=f
                )
            )

    def upload_template(self, node: str, storage: str, file_path: str) -> str:
        with open(file_path, "rb") as f:
            return (
                self._api.nodes(node)
                .storage(storage)
                .upload.post(
                    content="vztmpl", filename=os.path.basename(file_path), file=f
                )
            )

    def template_vm(self, node: str, vmid: int) -> str:
        return self._api.nodes(node).qemu(vmid).template.post()

    def list_snapshots(self, node: str, vmid: int) -> List[Dict[str, Any]]:
        return self._api.nodes(node).qemu(vmid).snapshot.get()

    def create_snapshot(
        self,
        node: str,
        vmid: int,
        name: str,
        description: Optional[str] = None,
        vmstate: bool = False,
    ) -> str:
        params: Dict[str, Any] = {"snapname": name, "vmstate": int(vmstate)}
        if description:
            params["description"] = description
        return self._api.nodes(node).qemu(vmid).snapshot.post(**params)

    def delete_snapshot(self, node: str, vmid: int, name: str) -> str:
        return self._api.nodes(node).qemu(vmid).snapshot(name).delete()

    def rollback_snapshot(self, node: str, vmid: int, name: str) -> str:
        return self._api.nodes(node).qemu(vmid).snapshot(name).rollback.post()

    def backup_vm(
        self,
        node: str,
        vmid: int,
        mode: str = "snapshot",
        compress: str = "zstd",
        storage: Optional[str] = None,
    ) -> str:
        params: Dict[str, Any] = {"vmid": vmid, "mode": mode, "compress": compress}
        if storage:
            params["storage"] = storage
        return self._api.nodes(node).vzdump.post(**params)

    def restore_vm(
        self,
        node: str,
        vmid: int,
        archive: str,
        storage: Optional[str] = None,
        force: bool = False,
    ) -> str:
        params: Dict[str, Any] = {"vmid": vmid, "archive": archive, "force": int(force)}
        if storage:
            params["storage"] = storage
        return self._api.nodes(node).qemu.restore.post(**params)

    # -------- Metrics --------
    def vm_metrics(
        self, node: str, vmid: int, timeframe: str = "hour", cf: str = "AVERAGE"
    ) -> List[Dict[str, Any]]:
        return self._api.nodes(node).qemu(vmid).rrddata.get(timeframe=timeframe, cf=cf)

    def node_metrics(
        self, node: str, timeframe: str = "hour", cf: str = "AVERAGE"
    ) -> List[Dict[str, Any]]:
        return self._api.nodes(node).rrddata.get(timeframe=timeframe, cf=cf)

    # -------- Pools / permissions --------
    def list_pools(self) -> List[Dict[str, Any]]:
        return self._api.pools.get()

    def create_pool(self, poolid: str, comment: Optional[str] = None) -> Any:
        params: Dict[str, Any] = {"poolid": poolid}
        if comment:
            params["comment"] = comment
        return self._api.pools.post(**params)

    def delete_pool(self, poolid: str) -> Any:
        return self._api.pools(poolid).delete()

    def pool_add(self, poolid: str, vmid: int, node: str, type_: str = "qemu") -> Any:
        # Using set on the resource is more reliable
        if type_ == "qemu":
            return self._api.nodes(node).qemu(vmid).config.put(pool=poolid)
        else:
            return self._api.nodes(node).lxc(vmid).config.put(pool=poolid)

    def pool_remove(
        self, poolid: str, vmid: int, node: str, type_: str = "qemu"
    ) -> Any:
        if type_ == "qemu":
            return self._api.nodes(node).qemu(vmid).config.put(pool="")
        else:
            return self._api.nodes(node).lxc(vmid).config.put(pool="")

    def list_users(self) -> List[Dict[str, Any]]:
        return self._api.access.users.get()

    def list_roles(self) -> List[Dict[str, Any]]:
        return self._api.access.roles.get()

    def assign_permission(
        self,
        path: str,
        roles: str,
        users: Optional[str] = None,
        groups: Optional[str] = None,
        propagate: bool = True,
    ) -> Any:
        params: Dict[str, Any] = {
            "path": path,
            "roles": roles,
            "propagate": int(propagate),
        }
        if users:
            params["users"] = users
        if groups:
            params["groups"] = groups
        return self._api.access.acl.put(**params)

    # -------- Tasks/wait helpers --------
    def wait_task(
        self,
        upid: str,
        node: Optional[str] = None,
        timeout: int = 600,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        start = time.time()
        while True:
            status = self.task_status(upid, node=node)
            if status.get("status") == "stopped":
                return status
            if (time.time() - start) > timeout:
                raise TimeoutError(f"Task {upid} did not complete within {timeout}s")
            time.sleep(poll_interval)

    def qga_exec(
        self,
        node: str,
        vmid: int,
        command: str,
        args: Optional[List[str]] = None,
        input_data: Optional[str] = None,
    ) -> Dict[str, Any]:
        command_parts = [command, *(args or [])]
        payload: Dict[str, Any] = {"command": command_parts}
        if input_data is not None:
            payload["input-data"] = input_data
        return self._api.nodes(node).qemu(vmid).agent.exec.post(**payload)

    def qga_exec_status(self, node: str, vmid: int, pid: int) -> Dict[str, Any]:
        return self._api.nodes(node).qemu(vmid).agent("exec-status").get(pid=pid)

    def qga_get_info(self, node: str, vmid: int) -> Dict[str, Any]:
        return self._api.nodes(node).qemu(vmid).agent("info").get()

    def qga_exec_wait(
        self,
        node: str,
        vmid: int,
        pid: int,
        timeout: int = 300,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        start = time.time()
        while True:
            status = self.qga_exec_status(node, vmid, pid)
            if status.get("exited"):
                return status
            if (time.time() - start) > timeout:
                raise TimeoutError(
                    f"Guest exec pid {pid} did not finish within {timeout}s"
                )
            time.sleep(poll_interval)

    def qga_network_get_interfaces(self, node: str, vmid: int) -> Dict[str, Any]:
        return self._api.nodes(node).qemu(vmid).agent("network-get-interfaces").get()

    def get_vm_ipv4_addresses(self, node: str, vmid: int) -> List[str]:
        interfaces = self.qga_network_get_interfaces(node, vmid)
        interface_list: Any
        if isinstance(interfaces, dict) and isinstance(interfaces.get("result"), list):
            interface_list = interfaces.get("result")
        elif isinstance(interfaces, list):
            interface_list = interfaces
        else:
            interface_list = []

        addresses: List[str] = []
        for interface in interface_list:
            for addr in interface.get("ip-addresses", []) or []:
                if addr.get("ip-address-type") != "ipv4":
                    continue
                ip = addr.get("ip-address")
                if not ip:
                    continue
                try:
                    parsed = ipaddress.ip_address(ip)
                except ValueError:
                    continue
                if parsed.is_loopback or parsed.is_link_local:
                    continue
                addresses.append(ip)

        # Preserve order but de-duplicate
        return list(dict.fromkeys(addresses))

    def wait_for_vm_ip(
        self, node: str, vmid: int, timeout: int = 300, poll_interval: float = 5.0
    ) -> str:
        start = time.time()
        last_error: Optional[str] = None
        while True:
            try:
                addresses = self.get_vm_ipv4_addresses(node, vmid)
                if addresses:
                    return addresses[0]
            except Exception as exc:
                last_error = str(exc)

            if (time.time() - start) > timeout:
                error_suffix = f" Last error: {last_error}" if last_error else ""
                raise TimeoutError(
                    f"VM {vmid} on node {node} did not report an IPv4 address within {timeout}s.{error_suffix}"
                )
            time.sleep(poll_interval)

    # -------- CloudInit and template management --------
    def create_cloudinit_vm(
        self,
        *,
        node: str,
        vmid: int,
        name: str,
        template: str,
        cores: int = 2,
        memory_mb: int = 2048,
        disk_gb: int = 20,
        storage: Optional[str] = None,
        bridge: Optional[str] = None,
        cloudinit_params: Optional[Dict[str, Any]] = None,
        user_data: Optional[str] = None,
        snippet_storage: Optional[str] = None,
        timeout: int = 900,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """Clone a prepared Proxmox VM template and apply native Cloud-Init."""
        template_vmid, template_node, template_vm = self.resolve_vm_template(
            template, node=node
        )
        result: Dict[str, Any] = {
            "source_template": {
                "vmid": template_vmid,
                "node": template_node,
                "name": template_vm.get("name"),
            }
        }

        clone_upid = self.clone_vm(
            source_node=template_node,
            source_vmid=template_vmid,
            target_node=node,
            new_vmid=vmid,
            name=name,
            full=True,
            storage=storage,
        )
        result["clone_upid"] = clone_upid
        result["clone_status"] = self.wait_task(
            clone_upid,
            node=template_node,
            timeout=timeout,
            poll_interval=poll_interval,
        )

        effective_cloudinit_params = dict(cloudinit_params or {})
        effective_cloudinit_params.update({"cores": cores, "memory": memory_mb})
        if bridge:
            effective_cloudinit_params["net0"] = f"virtio,bridge={bridge}"

        apply_result = self.apply_cloudinit_config(
            node,
            vmid,
            cloudinit_params=effective_cloudinit_params,
            user_data=user_data,
            storage=storage,
            snippet_storage=snippet_storage,
            timeout=timeout,
            poll_interval=poll_interval,
        )
        result.update(apply_result)

        final_upid = apply_result.get("upid")
        disk_device, current_disk_gb = self._get_primary_disk(node, vmid)
        if (
            disk_device is not None
            and current_disk_gb is not None
            and disk_gb > current_disk_gb
        ):
            if isinstance(final_upid, str):
                result["config_status"] = self.wait_task(
                    final_upid,
                    node=node,
                    timeout=timeout,
                    poll_interval=poll_interval,
                )
            growth_gb = disk_gb - current_disk_gb
            resize_upid = self.resize_vm_disk(node, vmid, disk_device, growth_gb)
            result["resize_upid"] = resize_upid
            result["resized_disk"] = disk_device
            result["target_disk_gb"] = disk_gb
            final_upid = resize_upid
        elif disk_device is None or current_disk_gb is None:
            result.setdefault("warnings", []).append(
                "Unable to determine the cloned VM disk size; skipped disk resize"
            )

        result["upid"] = final_upid or clone_upid
        return result

    def build_cloud_image_template(
        self,
        *,
        node: str,
        vmid: int,
        name: str,
        image_url: str,
        image_filename: Optional[str] = None,
        image_storage: str = "local",
        storage: Optional[str] = None,
        bridge: Optional[str] = None,
        cores: int = 2,
        memory_mb: int = 2048,
        disk_gb: int = 32,
        machine: str = "q35",
        bios: str = "ovmf",
        cpu: str = "host",
        scsihw: str = "virtio-scsi-pci",
        ostype: str = "l26",
        serial_console: bool = True,
        agent: bool = True,
        ciuser: Optional[str] = None,
        sshkeys: Optional[str] = None,
        ipconfig0: Optional[str] = "ip=dhcp",
        cipassword: Optional[str] = None,
        cicustom: Optional[str] = None,
        tags: Optional[str] = None,
        boot_disk: str = "virtio0",
        cloudinit_disk: str = "scsi1",
        convert_to_template: bool = True,
        timeout: int = 1800,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """Build a cloud-init-ready template from a cloud image URL.

        Uses Proxmox REST `download-url` (PVE 7.2+) + disk `import-from`
        (PVE 8+). No SSH to the node required.
        """
        require_allowed_url(
            image_url,
            purpose=f"cloud image fetch for VM {vmid}",
            user_provided=False,
        )
        storage_id = storage or self.default_storage or "local-lvm"
        bridge_id = bridge or self.default_bridge or "vmbr0"
        filename = image_filename or os.path.basename(
            urllib.parse.urlparse(image_url).path
        )
        if not filename:
            raise ValueError(
                "Could not derive image_filename from image_url; pass image_filename explicitly"
            )

        result: Dict[str, Any] = {
            "node": node,
            "vmid": vmid,
            "name": name,
            "image_url": image_url,
            "image_filename": filename,
            "image_storage": image_storage,
            "disk_storage": storage_id,
            "steps": [],
        }

        def _wait(upid: Any, label: str) -> None:
            if isinstance(upid, str):
                status = self.wait_task(
                    upid, node=node, timeout=timeout, poll_interval=poll_interval
                )
                result["steps"].append({"step": label, "upid": upid, "status": status})
            else:
                result["steps"].append({"step": label, "result": upid})

        # 1. Download cloud image (skip if already on storage)
        target_volid = f"{image_storage}:iso/{filename}"
        existing = self.storage_content(node, image_storage)
        if any(item.get("volid") == target_volid for item in existing):
            result["steps"].append({"step": "download-image", "skipped": True})
        else:
            upid = (
                self._api.nodes(node)
                .storage(image_storage)("download-url")
                .post(url=image_url, content="iso", filename=filename)
            )
            _wait(upid, "download-image")

        # 2. Create shell VM (no disk yet)
        create_params: Dict[str, Any] = {
            "vmid": vmid,
            "name": name,
            "ostype": ostype,
            "cores": cores,
            "sockets": 1,
            "memory": memory_mb,
            "machine": machine,
            "bios": bios,
            "cpu": cpu,
            "scsihw": scsihw,
            "agent": int(agent),
            "net0": f"virtio,bridge={bridge_id}",
        }
        if serial_console:
            create_params["serial0"] = "socket"
            create_params["vga"] = "serial0"
        if tags:
            create_params["tags"] = tags
        _wait(self._api.nodes(node).qemu.post(**create_params), "create-vm")

        # 3. EFI disk for UEFI builds
        if bios == "ovmf":
            _wait(
                self._api.nodes(node)
                .qemu(vmid)
                .config.put(efidisk0=f"{storage_id}:0,pre-enrolled-keys=0"),
                "efidisk",
            )

        # 4. Import main disk from cloud image via import-from
        import_spec = (
            f"{storage_id}:0,import-from={target_volid},discard=on"
        )
        _wait(
            self._api.nodes(node)
            .qemu(vmid)
            .config.put(**{boot_disk: import_spec}),
            "import-disk",
        )

        # 5. Resize imported disk up to target size (image is ~3-5 GiB raw)
        config = self.vm_config(node, vmid)
        current_gb = _parse_disk_size_gb(config.get(boot_disk, "")) or 0
        if disk_gb > current_gb > 0:
            _wait(
                self.resize_vm_disk(node, vmid, boot_disk, disk_gb - current_gb),
                "resize-disk",
            )

        # 6. Cloud-init drive
        _wait(
            self._api.nodes(node)
            .qemu(vmid)
            .config.put(**{cloudinit_disk: f"{storage_id}:cloudinit"}),
            "cloudinit-drive",
        )

        # 7. Cloud-init params + boot order in one PUT
        ci_params: Dict[str, Any] = {"boot": f"order={boot_disk}"}
        if ciuser is not None:
            ci_params["ciuser"] = ciuser
        if sshkeys is not None:
            ci_params["sshkeys"] = _encode_sshkeys(sshkeys)
        if ipconfig0 is not None:
            ci_params["ipconfig0"] = ipconfig0
        if cipassword is not None:
            ci_params["cipassword"] = cipassword
        if cicustom is not None:
            ci_params["cicustom"] = cicustom
        _wait(
            self._api.nodes(node).qemu(vmid).config.put(**ci_params),
            "cloudinit-config",
        )

        # 8. Convert to template
        if convert_to_template:
            result["template_upid"] = self.template_vm(node, vmid)

        return result

    def download_os_template(
        self, node: str, storage: str, template_name: str, template_url: str
    ) -> str:
        """Download OS template from URL."""
        import requests
        import tempfile

        require_allowed_url(
            template_url,
            purpose=f"os template download ({template_name})",
            user_provided=False,
        )

        # Download template to temporary file
        response = requests.get(template_url, stream=True, timeout=60)
        response.raise_for_status()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".img") as temp_file:
            for chunk in response.iter_content(chunk_size=8192):
                temp_file.write(chunk)
            temp_path = temp_file.name

        try:
            # Upload to Proxmox storage
            upid = self.upload_template(node, storage, temp_path)
            return upid
        finally:
            # Clean up temporary file
            os.unlink(temp_path)

    def list_os_templates(self, node: str, storage: str) -> List[Dict[str, Any]]:
        """List available OS templates in storage."""
        content = self.storage_content(node, storage)
        templates = [
            item
            for item in content
            if item.get("content") in ("iso", "vztmpl")
            and any(
                keyword in item.get("volid", "").lower()
                for keyword in ["ubuntu", "fedora", "rocky", "alma", "centos", "debian"]
            )
        ]
        return templates

    def attach_cloudinit_iso(
        self, node: str, vmid: int, iso_path: str
    ) -> Dict[str, Any]:
        """Attach CloudInit ISO to VM."""
        # First upload the ISO if it's a local path
        if os.path.isfile(iso_path):
            storage_id = self.default_storage or "local"
            upid = self.upload_iso(node, storage_id, iso_path)
            iso_volid = f"{storage_id}:iso/{os.path.basename(iso_path)}"
        else:
            iso_volid = iso_path

        # Attach to IDE2 as CloudInit drive
        upid = (
            self._api.nodes(node).qemu(vmid).config.put(ide2=f"{iso_volid},media=cdrom")
        )
        return {"upid": upid, "iso_attached": iso_volid}

    def create_cloudinit_iso(
        self,
        user_data: str,
        meta_data: Optional[str] = None,
        network_config: Optional[str] = None,
        output_path: str = "/tmp/cloudinit.iso",
    ) -> str:
        """Create CloudInit NoCloud ISO."""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            # Write user-data
            with open(os.path.join(temp_dir, "user-data"), "w") as f:
                f.write(user_data)

            # Write meta-data
            if meta_data:
                with open(os.path.join(temp_dir, "meta-data"), "w") as f:
                    f.write(meta_data)
            else:
                # Create minimal meta-data
                with open(os.path.join(temp_dir, "meta-data"), "w") as f:
                    f.write("instance-id: cloud-vm\nlocal-hostname: cloud-vm\n")

            # Write network-config if provided
            if network_config:
                with open(os.path.join(temp_dir, "network-config"), "w") as f:
                    f.write(network_config)

            # Create ISO
            cmd = [
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
                subprocess.run(cmd, check=True, capture_output=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Fallback to mkisofs
                cmd[0] = "mkisofs"
                try:
                    subprocess.run(cmd, check=True, capture_output=True)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    raise RuntimeError(
                        "Neither genisoimage nor mkisofs available for ISO creation"
                    )

        return output_path

    def get_vm_cloudinit_config(self, node: str, vmid: int) -> Dict[str, Any]:
        """Get current CloudInit configuration of VM."""
        config = self.vm_config(node, vmid)
        cloudinit_config = {}

        # Extract CloudInit related configurations
        for key, value in config.items():
            if key.startswith(
                (
                    "ciuser",
                    "cipassword",
                    "searchdomain",
                    "nameserver",
                    "sshkeys",
                    "ipconfig",
                    "cicustom",
                    "citype",
                    "ciupgrade",
                )
            ):
                cloudinit_config[key] = value

        return cloudinit_config

    def set_cloudinit_config(self, node: str, vmid: int, config: Dict[str, Any]) -> str:
        """Set CloudInit configuration for VM."""
        return self._api.nodes(node).qemu(vmid).config.put(**config)

    # -------- RHCOS and OpenShift support --------
    def create_rhcos_vm(
        self,
        *,
        node: str,
        vmid: int,
        name: str,
        cores: int = 4,
        memory_mb: int = 8192,
        disk_gb: int = 50,
        storage: Optional[str] = None,
        bridge: Optional[str] = None,
        machine_type: str = "q35",
        cpu_type: str = "host",
    ) -> str:
        """Create RHCOS VM with enterprise-grade configuration."""
        storage_id = storage or self.default_storage or "local-lvm"
        bridge_id = bridge or self.default_bridge or "vmbr0"

        params: Dict[str, Any] = {
            "vmid": vmid,
            "name": name,
            "cores": cores,
            "memory": memory_mb,
            "machine": machine_type,
            "cpu": cpu_type,
            "scsihw": "virtio-scsi-pci",
            "agent": 0,  # QEMU guest agent not used in RHCOS typically
            "ostype": "l26",
            "boot": "order=scsi0;ide2;net0",
            "serial0": "socket",
            "vga": "serial0",
            "scsi0": f"{storage_id}:{max(disk_gb, 1)},format=qcow2",
            "net0": f"virtio,bridge={bridge_id}",
            # Enable nested virtualization for OpenShift
            "args": "-cpu host,+vmx",
        }

        return self._api.nodes(node).qemu.post(**params)

    def attach_ignition_iso(
        self, node: str, vmid: int, iso_path: str
    ) -> Dict[str, Any]:
        """Attach Ignition ISO to RHCOS VM."""
        # Upload ISO if it's a local path
        if os.path.isfile(iso_path):
            storage_id = self.default_storage or "local"
            upid = self.upload_iso(node, storage_id, iso_path)
            iso_volid = f"{storage_id}:iso/{os.path.basename(iso_path)}"
        else:
            iso_volid = iso_path

        # Attach to IDE2 as Ignition drive
        upid = (
            self._api.nodes(node).qemu(vmid).config.put(ide2=f"{iso_volid},media=cdrom")
        )
        return {"upid": upid, "ignition_iso": iso_volid}

    def create_ignition_iso(
        self, ignition_json: str, output_path: str = "/tmp/ignition.iso"
    ) -> str:
        """Create Ignition ISO for RHCOS boot."""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            # Write ignition.json
            with open(os.path.join(temp_dir, "ignition.json"), "w") as f:
                f.write(ignition_json)

            # Create ISO
            cmd = [
                "genisoimage",
                "-output",
                output_path,
                "-volid",
                "ignition",
                "-joliet",
                "-rock",
                temp_dir,
            ]

            try:
                subprocess.run(cmd, check=True, capture_output=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Fallback to mkisofs
                cmd[0] = "mkisofs"
                try:
                    subprocess.run(cmd, check=True, capture_output=True)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    raise RuntimeError(
                        "Neither genisoimage nor mkisofs available for ISO creation"
                    )

        return output_path

    def get_vm_console_url(self, node: str, vmid: int) -> str:
        """Get VNC console URL for VM."""
        # Get VM configuration to determine console type
        config = self.vm_config(node, vmid)
        console_type = 4 if "serial0" in config else 0

        # For RHCOS VMs, we typically use serial console
        return f"{self.scheme}://{self.host}:{self.port}/#v1:0:18:{node}:{console_type}:{vmid}::"

    def wait_for_vm_ssh(self, node: str, vmid: int, timeout: int = 300) -> bool:
        """Wait for VM to be accessible via SSH."""
        import socket
        import time

        # Get VM IP from QEMU guest agent if available
        try:
            interfaces = self.qga_network_get_interfaces(node, vmid)
            vm_ip = None

            if isinstance(interfaces.get("result"), list):
                for interface in interfaces["result"]:
                    for addr in interface.get("ip-addresses", []):
                        if (
                            addr.get("ip-address-type") == "ipv4"
                            and not addr.get("prefix") == 32
                        ):
                            vm_ip = addr.get("ip-address")
                            break
                    if vm_ip:
                        break

            if not vm_ip:
                return False

            # Try to connect to SSH port
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    result = sock.connect_ex((vm_ip, 22))
                    sock.close()

                    if result == 0:
                        return True
                except Exception:
                    pass

                time.sleep(10)

            return False

        except Exception:
            # If we can't get the IP or check SSH, assume it's not ready
            return False

    def set_vm_description(self, node: str, vmid: int, description: str) -> str:
        """Set VM description/notes."""
        return self._api.nodes(node).qemu(vmid).config.put(description=description)

    def get_vm_notes(self, node: str, vmid: int) -> str:
        """Get VM description/notes."""
        config = self._api.nodes(node).qemu(vmid).config.get()
        return config.get("description", "")

    def set_vm_notes(self, node: str, vmid: int, notes: str) -> str:
        """Set VM description/notes."""
        return self.set_vm_description(node, vmid, notes)

    def get_lxc_notes(self, node: str, ctid: int) -> str:
        """Get LXC description/notes."""
        config = self._api.nodes(node).lxc(ctid).config.get()
        return config.get("description", "")

    def set_lxc_notes(self, node: str, ctid: int, notes: str) -> str:
        """Set LXC description/notes."""
        return self._api.nodes(node).lxc(ctid).config.put(description=notes)

    # -------- Windows VM support --------
    def create_windows_vm(
        self,
        *,
        node: str,
        vmid: int,
        name: str,
        cores: int = 4,
        memory_mb: int = 4096,
        disk_gb: int = 60,
        storage: Optional[str] = None,
        bridge: Optional[str] = None,
        windows_iso: Optional[str] = None,
        virtio_iso: Optional[str] = None,
    ) -> str:
        """Create Windows VM with optimized configuration."""
        storage_id = storage or self.default_storage or "local-lvm"
        bridge_id = bridge or self.default_bridge or "vmbr0"

        params: Dict[str, Any] = {
            "vmid": vmid,
            "name": name,
            "cores": cores,
            "memory": memory_mb,
            "scsihw": "virtio-scsi-pci",
            "agent": 1,
            "ostype": "win10",
            "machine": "pc-q35-6.2",
            "cpu": "host",
            "bios": "ovmf",  # UEFI BIOS for modern Windows
            "boot": "order=scsi0;ide2;net0",
            "scsi0": f"{storage_id}:{max(disk_gb, 1)},format=qcow2,cache=writeback",
            "net0": f"virtio,bridge={bridge_id}",
            "vga": "qxl",
            "tablet": 1,
            "usb": "nec-xhci,u2=1,u3=1",
            # Add EFI disk for UEFI boot
            "efidisk0": f"{storage_id}:1,format=qcow2,efitype=4m,pre-enrolled-keys=1",
            # Add TPM for Windows 11 compatibility
            "tpmstate0": f"{storage_id}:1,version=v2.0",
        }

        # Attach Windows ISO if provided
        if windows_iso:
            params["ide2"] = f"{windows_iso},media=cdrom"

        # Attach VirtIO drivers ISO if provided
        if virtio_iso:
            params["ide3"] = f"{virtio_iso},media=cdrom"

        return self._api.nodes(node).qemu.post(**params)

    def attach_windows_iso(self, node: str, vmid: int, iso_path: str) -> Dict[str, Any]:
        """Attach Windows installation ISO to VM."""
        # Upload ISO if it's a local path
        if os.path.isfile(iso_path):
            storage_id = self.default_storage or "local"
            upid = self.upload_iso(node, storage_id, iso_path)
            iso_volid = f"{storage_id}:iso/{os.path.basename(iso_path)}"
        else:
            iso_volid = iso_path

        # Attach to IDE2 as bootable drive
        upid = (
            self._api.nodes(node).qemu(vmid).config.put(ide2=f"{iso_volid},media=cdrom")
        )
        return {"upid": upid, "windows_iso": iso_volid}

    def configure_windows_rdp(
        self, node: str, vmid: int, enable: bool = True
    ) -> Dict[str, Any]:
        """Configure Windows Remote Desktop Protocol."""
        if enable:
            script = """
# Enable RDP
Set-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server" -Name "fDenyTSConnections" -Value 0
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"
Write-Host "RDP enabled successfully"
"""
        else:
            script = """
# Disable RDP
Set-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server" -Name "fDenyTSConnections" -Value 1
Disable-NetFirewallRule -DisplayGroup "Remote Desktop"
Write-Host "RDP disabled successfully"
"""

        try:
            result = self.qga_exec(
                node,
                vmid,
                command="powershell.exe",
                args=["-ExecutionPolicy", "Bypass", "-Command", script],
            )
            return {"rdp_configured": True, "enabled": enable, "result": result}
        except Exception as e:
            return {"rdp_configured": False, "error": str(e)}

    def get_windows_vm_info(self, node: str, vmid: int) -> Dict[str, Any]:
        """Get Windows-specific VM information."""
        try:
            # Get VM configuration
            config = self.vm_config(node, vmid)

            # Get guest info if QEMU agent is available
            guest_info = {}
            try:
                guest_info = self.qga_get_info(node, vmid)
            except Exception:
                pass  # QEMU agent not available or VM not running

            # Check if it's a Windows VM
            is_windows = config.get("ostype", "").startswith("win")

            # Get network interfaces
            interfaces = {}
            try:
                interfaces = self.qga_network_get_interfaces(node, vmid)
            except Exception:
                pass

            return {
                "vmid": vmid,
                "name": config.get("name", ""),
                "is_windows": is_windows,
                "ostype": config.get("ostype", ""),
                "bios": config.get("bios", ""),
                "machine": config.get("machine", ""),
                "cores": config.get("cores", 0),
                "memory": config.get("memory", 0),
                "agent": config.get("agent", 0),
                "guest_info": guest_info,
                "interfaces": interfaces,
                "rdp_port": 3389,  # Default RDP port
                "console_url": self.get_vm_console_url(node, vmid),
            }
        except Exception as e:
            return {"error": str(e)}

    def execute_windows_command(
        self, node: str, vmid: int, command: str, shell: str = "powershell"
    ) -> Dict[str, Any]:
        """Execute command on Windows VM via QEMU guest agent."""
        if shell.lower() == "powershell":
            cmd = "powershell.exe"
            args = ["-ExecutionPolicy", "Bypass", "-Command", command]
        elif shell.lower() == "cmd":
            cmd = "cmd.exe"
            args = ["/c", command]
        else:
            raise ValueError("Supported shells: powershell, cmd")

        try:
            result = self.qga_exec(node, vmid, command=cmd, args=args)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_windows_services(self, node: str, vmid: int) -> Dict[str, Any]:
        """Get Windows services status."""
        script = "Get-Service | Select-Object Name, Status, StartType | ConvertTo-Json"

        try:
            result = self.execute_windows_command(node, vmid, script, "powershell")
            return {"success": True, "services": result.get("result", {})}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def restart_windows_service(
        self, node: str, vmid: int, service_name: str
    ) -> Dict[str, Any]:
        """Restart Windows service."""
        script = f"Restart-Service -Name '{service_name}' -Force"

        try:
            result = self.execute_windows_command(node, vmid, script, "powershell")
            return {"success": True, "service": service_name, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def install_windows_updates(self, node: str, vmid: int) -> Dict[str, Any]:
        """Install Windows updates via PowerShell."""
        script = """
# Install PSWindowsUpdate module if not available
if (!(Get-Module -ListAvailable -Name PSWindowsUpdate)) {
    Install-PackageProvider -Name NuGet -Force -Scope CurrentUser
    Install-Module PSWindowsUpdate -Force -Scope CurrentUser
}

# Import module and install updates
Import-Module PSWindowsUpdate
Get-WindowsUpdate -Install -AcceptAll -AutoReboot
"""

        try:
            result = self.execute_windows_command(node, vmid, script, "powershell")
            return {"success": True, "updates_installed": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
