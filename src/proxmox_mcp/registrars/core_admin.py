from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP


def register_core_admin_tools(
    server: FastMCP,
    get_client: Callable[[], Any],
    require_confirm: Callable[[Optional[bool]], None],
) -> None:
    @server.tool("proxmox-vm-metrics")
    async def proxmox_vm_metrics(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        timeframe: str = "hour",
        cf: str = "AVERAGE",
    ) -> List[Dict[str, Any]]:
        client = get_client()
        vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
        return client.vm_metrics(vm_node, vm_vmid, timeframe=timeframe, cf=cf)

    @server.tool("proxmox-node-metrics")
    async def proxmox_node_metrics(
        node: Optional[str] = None,
        timeframe: str = "hour",
        cf: str = "AVERAGE",
    ) -> List[Dict[str, Any]]:
        client = get_client()
        node_id = node or client.default_node
        if not node_id:
            raise ValueError("node is required (or set PROXMOX_DEFAULT_NODE)")
        return client.node_metrics(node_id, timeframe=timeframe, cf=cf)

    @server.tool("proxmox-list-pools")
    async def proxmox_list_pools() -> List[Dict[str, Any]]:
        client = get_client()
        return client.list_pools()

    @server.tool("proxmox-create-pool")
    async def proxmox_create_pool(
        poolid: str,
        comment: Optional[str] = None,
        confirm: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        client = get_client()
        if not poolid:
            raise ValueError("poolid is required")
        require_confirm(confirm)
        if dry_run:
            return {
                "dry_run": True,
                "action": "create-pool",
                "params": {"poolid": poolid, "comment": comment},
            }
        return {"result": client.create_pool(poolid, comment=comment)}

    @server.tool("proxmox-delete-pool")
    async def proxmox_delete_pool(
        poolid: str,
        confirm: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        client = get_client()
        if not poolid:
            raise ValueError("poolid is required")
        require_confirm(confirm)
        if dry_run:
            return {
                "dry_run": True,
                "action": "delete-pool",
                "params": {"poolid": poolid},
            }
        return {"result": client.delete_pool(poolid)}

    @server.tool("proxmox-pool-add")
    async def proxmox_pool_add(
        poolid: str,
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        type_: str = "qemu",
        confirm: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        client = get_client()
        if type_ not in ("qemu", "lxc"):
            raise ValueError("type_ must be 'qemu' or 'lxc'")
        if type_ == "qemu":
            rid, rnode, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
        else:
            rid, rnode, _ = client.resolve_lxc(vmid=vmid, name=name, node=node)
        require_confirm(confirm)
        if dry_run:
            return {
                "dry_run": True,
                "action": "pool-add",
                "params": {
                    "poolid": poolid,
                    "vmid": rid,
                    "node": rnode,
                    "type_": type_,
                },
            }
        return {"result": client.pool_add(poolid, vmid=rid, node=rnode, type_=type_)}

    @server.tool("proxmox-pool-remove")
    async def proxmox_pool_remove(
        poolid: str,
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        type_: str = "qemu",
        confirm: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        client = get_client()
        if type_ not in ("qemu", "lxc"):
            raise ValueError("type_ must be 'qemu' or 'lxc'")
        if type_ == "qemu":
            rid, rnode, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
        else:
            rid, rnode, _ = client.resolve_lxc(vmid=vmid, name=name, node=node)
        require_confirm(confirm)
        if dry_run:
            return {
                "dry_run": True,
                "action": "pool-remove",
                "params": {
                    "poolid": poolid,
                    "vmid": rid,
                    "node": rnode,
                    "type_": type_,
                },
            }
        return {"result": client.pool_remove(poolid, vmid=rid, node=rnode, type_=type_)}

    @server.tool("proxmox-list-users")
    async def proxmox_list_users() -> List[Dict[str, Any]]:
        client = get_client()
        return client.list_users()

    @server.tool("proxmox-list-roles")
    async def proxmox_list_roles() -> List[Dict[str, Any]]:
        client = get_client()
        return client.list_roles()

    @server.tool("proxmox-assign-permission")
    async def proxmox_assign_permission(
        path: str,
        roles: str,
        users: Optional[str] = None,
        groups: Optional[str] = None,
        propagate: bool = True,
        confirm: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        client = get_client()
        if not path or not roles:
            raise ValueError("path and roles are required")
        require_confirm(confirm)
        if dry_run:
            return {
                "dry_run": True,
                "action": "assign-permission",
                "params": {
                    "path": path,
                    "roles": roles,
                    "users": users,
                    "groups": groups,
                    "propagate": propagate,
                },
            }
        return {
            "result": client.assign_permission(
                path, roles, users=users, groups=groups, propagate=propagate
            )
        }

    @server.tool("proxmox-wait-task")
    async def proxmox_wait_task(
        upid: str,
        node: Optional[str] = None,
        timeout: int = 900,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        client = get_client()
        return client.wait_task(
            upid, node=node, timeout=timeout, poll_interval=poll_interval
        )

    @server.tool("proxmox-register-vm-as-host")
    async def proxmox_register_vm_as_host(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        ssh_user: str = "root",
        ssh_private_key_path: Optional[str] = None,
        prefer_interface: Optional[str] = None,
    ) -> Dict[str, Any]:
        client = get_client()
        vm_vmid, vm_node, vm = client.resolve_vm(vmid=vmid, name=name, node=node)
        interfaces: Any = {}
        try:
            qga = client.qga_network_get_interfaces(vm_node, vm_vmid)
            interfaces = qga.get("result", {})
        except Exception as exc:
            interfaces = {"error": str(exc)}

        chosen_ip: Optional[str] = None
        if isinstance(interfaces, list):
            for itf in interfaces:
                if prefer_interface and itf.get("name") != prefer_interface:
                    continue
                for addr in itf.get("ip-addresses", []) or []:
                    if (
                        addr.get("ip-address-type") == "ipv4"
                        and addr.get("prefix") != 32
                    ):
                        chosen_ip = addr.get("ip-address")
                        break
                if chosen_ip:
                    break

        hostname = vm.get("name") or f"vm{vm_vmid}"
        ini = f"[{hostname}]\n{hostname} ansible_host={chosen_ip or '<IP>'} ansible_user={ssh_user}"
        if ssh_private_key_path:
            ini += f" ansible_ssh_private_key_file={ssh_private_key_path}"
        return {
            "hostname": hostname,
            "ip": chosen_ip,
            "json": {
                hostname: {
                    "ansible_host": chosen_ip or "<IP>",
                    "ansible_user": ssh_user,
                    **(
                        {"ansible_ssh_private_key_file": ssh_private_key_path}
                        if ssh_private_key_path
                        else {}
                    ),
                }
            },
            "ini": ini,
            "interfaces": interfaces,
        }

    @server.tool("proxmox-guest-exec")
    async def proxmox_guest_exec(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        command: str = "",
        args: Optional[List[str]] = None,
        input_data: Optional[str] = None,
        wait: bool = False,
        timeout: int = 300,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        client = get_client()
        vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
        if not command:
            raise ValueError("command is required")
        result = client.qga_exec(
            vm_node, vm_vmid, command=command, args=args, input_data=input_data
        )
        if wait and isinstance(result, dict) and "pid" in result:
            result["status"] = client.qga_exec_wait(
                vm_node,
                vm_vmid,
                pid=int(result["pid"]),
                timeout=timeout,
                poll_interval=poll_interval,
            )
        return result

    @server.tool("proxmox-guest-shell")
    async def proxmox_guest_shell(
        script: str,
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        shell: str = "bash",
        wait: bool = True,
        timeout: int = 300,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        client = get_client()
        vm_vmid, vm_node, _ = client.resolve_vm(vmid=vmid, name=name, node=node)
        if not script:
            raise ValueError("script is required")
        if shell not in {"bash", "sh"}:
            raise ValueError("shell must be 'bash' or 'sh'")

        result = client.qga_exec(vm_node, vm_vmid, command=shell, args=["-lc", script])
        if wait and isinstance(result, dict) and "pid" in result:
            result["status"] = client.qga_exec_wait(
                vm_node,
                vm_vmid,
                pid=int(result["pid"]),
                timeout=timeout,
                poll_interval=poll_interval,
            )
        return result
