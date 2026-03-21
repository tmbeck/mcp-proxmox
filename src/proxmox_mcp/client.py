from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

from proxmoxer import ProxmoxAPI

from .utils import parse_api_url, read_env, split_token_id, require_allowed_url


VM_DISK_PREFIXES = ("ide", "sata", "scsi", "virtio")
VM_UNUSED_DISK_PREFIX = "unused"


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
            return self._api.cluster.tasks(upid).status.get()
        except Exception:
            if not node:
                raise
            return self._api.nodes(node).tasks(upid).status.get()

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
    ) -> str:
        storage_id = storage or self.default_storage or "local-lvm"
        bridge_id = bridge or self.default_bridge or "vmbr0"
        scsi0 = f"{storage_id}:{max(disk_gb, 1)}"
        params: Dict[str, Any] = {
            "vmid": vmid,
            "name": name,
            "cores": cores,
            "memory": memory_mb,
            "scsihw": scsihw,
            "agent": int(agent),
            "ostype": ostype,
            "scsi0": scsi0,
            "net0": f"virtio,bridge={bridge_id}",
        }
        if iso:
            # ide2 expects format storage:iso/filename.iso,media=cdrom
            params["ide2"] = iso if ":" in iso else f"{storage_id}:iso/{iso}"
            params["boot"] = "order=scsi0;ide2;net0"
        return self._api.nodes(node).qemu.post(**params)

    def delete_vm(self, node: str, vmid: int, purge: bool = True) -> str:
        return self._api.nodes(node).qemu(vmid).delete.post(purge=int(purge))

    def start_vm(self, node: str, vmid: int) -> str:
        return self._api.nodes(node).qemu(vmid).status.start.post()

    def stop_vm(
        self, node: str, vmid: int, force: bool = False, timeout: Optional[int] = None
    ) -> str:
        params: Dict[str, Any] = {}
        if force:
            params["forceStop"] = 1
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
        return self._api.nodes(node).lxc(vmid).delete.post(purge=int(purge))

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
        upid = self._api.nodes(node).qemu(vmid).config.put(**params)
        return {"upid": upid} if isinstance(upid, str) else {"result": upid}

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
        return self._api.nodes(node).qemu(vmid).snapshot(name).delete.post()

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
        payload: Dict[str, Any] = {"command": command}
        if args:
            payload["args"] = args
        if input_data is not None:
            payload["input-data"] = input_data
        return self._api.nodes(node).qemu(vmid).agent.exec.post(**payload)

    def qga_exec_status(self, node: str, vmid: int, pid: int) -> Dict[str, Any]:
        return self._api.nodes(node).qemu(vmid).agent("exec-status").get(pid=pid)

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
        return self._api.nodes(node).qemu(vmid).agent["network-get-interfaces"].get()

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
        user_data: Optional[str] = None,
    ) -> str:
        """Create VM with CloudInit support."""
        storage_id = storage or self.default_storage or "local-lvm"
        bridge_id = bridge or self.default_bridge or "vmbr0"

        params: Dict[str, Any] = {
            "vmid": vmid,
            "name": name,
            "cores": cores,
            "memory": memory_mb,
            "scsihw": "virtio-scsi-pci",
            "agent": 1,
            "ostype": "l26",
            "boot": "order=scsi0;ide2;net0",
            "serial0": "socket",
            "vga": "serial0",
            "scsi0": f"{storage_id}:{max(disk_gb, 1)}",
            "net0": f"virtio,bridge={bridge_id}",
            "ide2": f"{storage_id}:cloudinit",  # CloudInit drive
        }

        return self._api.nodes(node).qemu.post(**params)

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

        # For RHCOS VMs, we typically use serial console
        if "serial0" in config:
            return f"https://{self.base_url}:8006/#v1:0:18:{node}:4:{vmid}::"
        else:
            return f"https://{self.base_url}:8006/#v1:0:18:{node}:0:{vmid}::"

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

    def get_cluster_vms(self, cluster_name: str) -> List[Dict[str, Any]]:
        """Get all VMs belonging to a cluster."""
        all_vms = self.list_vms()
        cluster_vms = [
            vm for vm in all_vms if vm.get("name", "").startswith(f"{cluster_name}-")
        ]
        return cluster_vms

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
                guest_info = self.qga_exec(node, vmid, command="guest-info")
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

    # -------- Docker Swarm support --------
    def execute_docker_command(
        self, node: str, vmid: int, command: str
    ) -> Dict[str, Any]:
        """Execute Docker command on VM."""
        try:
            result = self.qga_exec(node, vmid, command="bash", args=["-c", command])
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_docker_info(self, node: str, vmid: int) -> Dict[str, Any]:
        """Get Docker daemon information."""
        return self.execute_docker_command(node, vmid, "docker info --format json")

    def get_docker_swarm_status(self, node: str, vmid: int) -> Dict[str, Any]:
        """Get Docker Swarm status."""
        return self.execute_docker_command(
            node, vmid, "docker info --format '{{.Swarm.LocalNodeState}}'"
        )

    def initialize_docker_swarm(
        self, node: str, vmid: int, advertise_addr: str
    ) -> Dict[str, Any]:
        """Initialize Docker Swarm on node."""
        command = f"docker swarm init --advertise-addr {advertise_addr}"
        return self.execute_docker_command(node, vmid, command)

    def join_docker_swarm(
        self, node: str, vmid: int, manager_ip: str, token: str
    ) -> Dict[str, Any]:
        """Join node to Docker Swarm."""
        command = f"docker swarm join --token {token} {manager_ip}:2377"
        return self.execute_docker_command(node, vmid, command)

    def get_swarm_join_tokens(self, node: str, vmid: int) -> Dict[str, Any]:
        """Get Docker Swarm join tokens."""
        try:
            manager_token_result = self.execute_docker_command(
                node, vmid, "docker swarm join-token manager -q"
            )
            worker_token_result = self.execute_docker_command(
                node, vmid, "docker swarm join-token worker -q"
            )

            if manager_token_result["success"] and worker_token_result["success"]:
                return {
                    "success": True,
                    "manager_token": manager_token_result["result"],
                    "worker_token": worker_token_result["result"],
                }
            else:
                return {"success": False, "error": "Failed to retrieve tokens"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_swarm_nodes(self, node: str, vmid: int) -> Dict[str, Any]:
        """List Docker Swarm nodes."""
        command = "docker node ls --format 'table {{.ID}}\\t{{.Hostname}}\\t{{.Status}}\\t{{.Availability}}\\t{{.ManagerStatus}}'"
        return self.execute_docker_command(node, vmid, command)

    def list_swarm_services(self, node: str, vmid: int) -> Dict[str, Any]:
        """List Docker Swarm services."""
        command = "docker service ls --format 'table {{.Name}}\\t{{.Mode}}\\t{{.Replicas}}\\t{{.Image}}'"
        return self.execute_docker_command(node, vmid, command)

    def create_docker_service(
        self,
        node: str,
        vmid: int,
        service_name: str,
        image: str,
        replicas: int = 1,
        ports: Optional[List[str]] = None,
        environment: Optional[Dict[str, str]] = None,
        networks: Optional[List[str]] = None,
        constraints: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create Docker Swarm service."""
        command = f"docker service create --name {service_name} --replicas {replicas}"

        # Add port mappings
        if ports:
            for port in ports:
                command += f" --publish {port}"

        # Add environment variables
        if environment:
            for key, value in environment.items():
                command += f" --env {key}='{value}'"

        # Add network attachments
        if networks:
            for network in networks:
                command += f" --network {network}"

        # Add constraints
        if constraints:
            for constraint in constraints:
                command += f" --constraint '{constraint}'"

        command += f" {image}"

        return self.execute_docker_command(node, vmid, command)

    def scale_docker_service(
        self, node: str, vmid: int, service_name: str, replicas: int
    ) -> Dict[str, Any]:
        """Scale Docker Swarm service."""
        command = f"docker service scale {service_name}={replicas}"
        return self.execute_docker_command(node, vmid, command)

    def remove_docker_service(
        self, node: str, vmid: int, service_name: str
    ) -> Dict[str, Any]:
        """Remove Docker Swarm service."""
        command = f"docker service rm {service_name}"
        return self.execute_docker_command(node, vmid, command)

    def create_docker_network(
        self,
        node: str,
        vmid: int,
        network_name: str,
        driver: str = "overlay",
        subnet: Optional[str] = None,
        attachable: bool = False,
        encrypted: bool = False,
    ) -> Dict[str, Any]:
        """Create Docker network."""
        command = f"docker network create --driver {driver}"

        if subnet:
            command += f" --subnet {subnet}"
        if attachable:
            command += " --attachable"
        if encrypted:
            command += " --opt encrypted"

        command += f" {network_name}"

        return self.execute_docker_command(node, vmid, command)

    def get_docker_service_logs(
        self, node: str, vmid: int, service_name: str, lines: int = 100
    ) -> Dict[str, Any]:
        """Get Docker service logs."""
        command = f"docker service logs --tail {lines} {service_name}"
        return self.execute_docker_command(node, vmid, command)

    def get_swarm_cluster_info(self, cluster_name: str) -> Dict[str, Any]:
        """Get comprehensive Docker Swarm cluster information."""
        cluster_vms = self.get_cluster_vms(cluster_name)

        if not cluster_vms:
            return {"error": f"No VMs found for cluster: {cluster_name}"}

        # Find manager nodes (assuming naming convention)
        manager_vms = [
            vm for vm in cluster_vms if "manager" in vm.get("name", "").lower()
        ]
        worker_vms = [
            vm for vm in cluster_vms if "worker" in vm.get("name", "").lower()
        ]

        cluster_info = {
            "cluster_name": cluster_name,
            "total_nodes": len(cluster_vms),
            "manager_nodes": len(manager_vms),
            "worker_nodes": len(worker_vms),
            "nodes": [],
        }

        # Get detailed info from primary manager if available
        if manager_vms:
            primary_manager = manager_vms[0]
            try:
                swarm_status = self.get_docker_swarm_status(
                    primary_manager["node"], primary_manager["vmid"]
                )
                cluster_info["swarm_status"] = swarm_status

                if swarm_status.get("success"):
                    # Get nodes and services info
                    nodes_info = self.list_swarm_nodes(
                        primary_manager["node"], primary_manager["vmid"]
                    )
                    services_info = self.list_swarm_services(
                        primary_manager["node"], primary_manager["vmid"]
                    )

                    cluster_info["nodes_info"] = nodes_info
                    cluster_info["services_info"] = services_info
            except Exception as e:
                cluster_info["error"] = f"Failed to get cluster details: {str(e)}"

        # Add VM details
        for vm in cluster_vms:
            vm_info = {
                "vmid": vm["vmid"],
                "name": vm["name"],
                "status": vm.get("status", "unknown"),
                "node": vm.get("node", "unknown"),
                "role": "manager"
                if "manager" in vm.get("name", "").lower()
                else "worker",
            }
            cluster_info["nodes"].append(vm_info)

        return cluster_info
