from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional

from mcp.server.fastmcp import FastMCP

from ..notes_manager import NotesManager


def register_notes_tools(
    server: FastMCP,
    get_client: Callable[[], Any],
    require_confirm: Callable[[Optional[bool]], None],
) -> None:
    @server.tool("proxmox-vm-notes-read")
    async def proxmox_vm_notes_read(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        format: str = "auto",
        parse_secrets: bool = True,
    ) -> Dict[str, Any]:
        client = get_client()
        notes_manager = NotesManager(client)
        vm_vmid, vm_node, vm_info = client.resolve_vm(vmid=vmid, name=name, node=node)
        notes_content = client.get_vm_notes(vm_node, vm_vmid)
        formatted = notes_manager.format_notes_output(
            notes_content, format, parse_secrets
        )
        return {
            "vm": {"vmid": vm_vmid, "name": vm_info.get("name"), "node": vm_node},
            "notes": formatted,
        }

    @server.tool("proxmox-vm-notes-update")
    async def proxmox_vm_notes_update(
        content: str,
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        format: str = "auto",
        validate: bool = True,
        backup: bool = True,
        confirm: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        client = get_client()
        notes_manager = NotesManager(client)
        vm_vmid, vm_node, vm_info = client.resolve_vm(vmid=vmid, name=name, node=node)

        warnings: list[str] = []
        if validate:
            is_valid, validation_warnings = notes_manager.validate_content(content)
            warnings.extend(validation_warnings)
            if not is_valid:
                return {
                    "success": False,
                    "error": "Content validation failed",
                    "warnings": warnings,
                }

        previous_notes = client.get_vm_notes(vm_node, vm_vmid) if backup else None
        if dry_run:
            return {
                "dry_run": True,
                "action": "update-vm-notes",
                "vm": {"vmid": vm_vmid, "name": vm_info.get("name"), "node": vm_node},
                "content_length": len(content),
                "format": notes_manager.detect_format(content),
                "warnings": warnings,
                "previous_notes_length": len(previous_notes) if previous_notes else 0,
            }

        require_confirm(confirm)
        result = client.set_vm_notes(vm_node, vm_vmid, content)
        return {
            "success": True,
            "vm": {"vmid": vm_vmid, "name": vm_info.get("name"), "node": vm_node},
            "previous_notes": previous_notes if backup else None,
            "warnings": warnings,
            "result": result,
        }

    @server.tool("proxmox-vm-notes-remove")
    async def proxmox_vm_notes_remove(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        backup: bool = True,
        confirm: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        client = get_client()
        vm_vmid, vm_node, vm_info = client.resolve_vm(vmid=vmid, name=name, node=node)
        backup_notes = client.get_vm_notes(vm_node, vm_vmid) if backup else None

        if dry_run:
            return {
                "dry_run": True,
                "action": "remove-vm-notes",
                "vm": {"vmid": vm_vmid, "name": vm_info.get("name"), "node": vm_node},
                "backup_notes_length": len(backup_notes) if backup_notes else 0,
            }

        require_confirm(confirm)
        result = client.set_vm_notes(vm_node, vm_vmid, "")
        return {
            "success": True,
            "vm": {"vmid": vm_vmid, "name": vm_info.get("name"), "node": vm_node},
            "backup_notes": backup_notes if backup else None,
            "result": result,
        }

    @server.tool("proxmox-lxc-notes-read")
    async def proxmox_lxc_notes_read(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        format: str = "auto",
        parse_secrets: bool = True,
    ) -> Dict[str, Any]:
        client = get_client()
        notes_manager = NotesManager(client)
        ct_vmid, ct_node, ct_info = client.resolve_lxc(vmid=vmid, name=name, node=node)
        notes_content = client.get_lxc_notes(ct_node, ct_vmid)
        formatted = notes_manager.format_notes_output(
            notes_content, format, parse_secrets
        )
        return {
            "lxc": {"vmid": ct_vmid, "name": ct_info.get("name"), "node": ct_node},
            "notes": formatted,
        }

    @server.tool("proxmox-lxc-notes-update")
    async def proxmox_lxc_notes_update(
        content: str,
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        format: str = "auto",
        validate: bool = True,
        backup: bool = True,
        confirm: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        client = get_client()
        notes_manager = NotesManager(client)
        ct_vmid, ct_node, ct_info = client.resolve_lxc(vmid=vmid, name=name, node=node)

        warnings: list[str] = []
        if validate:
            is_valid, validation_warnings = notes_manager.validate_content(content)
            warnings.extend(validation_warnings)
            if not is_valid:
                return {
                    "success": False,
                    "error": "Content validation failed",
                    "warnings": warnings,
                }

        previous_notes = client.get_lxc_notes(ct_node, ct_vmid) if backup else None
        if dry_run:
            return {
                "dry_run": True,
                "action": "update-lxc-notes",
                "lxc": {"vmid": ct_vmid, "name": ct_info.get("name"), "node": ct_node},
                "content_length": len(content),
                "format": notes_manager.detect_format(content),
                "warnings": warnings,
                "previous_notes_length": len(previous_notes) if previous_notes else 0,
            }

        require_confirm(confirm)
        result = client.set_lxc_notes(ct_node, ct_vmid, content)
        return {
            "success": True,
            "lxc": {"vmid": ct_vmid, "name": ct_info.get("name"), "node": ct_node},
            "previous_notes": previous_notes if backup else None,
            "warnings": warnings,
            "result": result,
        }

    @server.tool("proxmox-lxc-notes-remove")
    async def proxmox_lxc_notes_remove(
        vmid: Optional[int] = None,
        name: Optional[str] = None,
        node: Optional[str] = None,
        backup: bool = True,
        confirm: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        client = get_client()
        ct_vmid, ct_node, ct_info = client.resolve_lxc(vmid=vmid, name=name, node=node)
        backup_notes = client.get_lxc_notes(ct_node, ct_vmid) if backup else None

        if dry_run:
            return {
                "dry_run": True,
                "action": "remove-lxc-notes",
                "lxc": {"vmid": ct_vmid, "name": ct_info.get("name"), "node": ct_node},
                "backup_notes_length": len(backup_notes) if backup_notes else 0,
            }

        require_confirm(confirm)
        result = client.set_lxc_notes(ct_node, ct_vmid, "")
        return {
            "success": True,
            "lxc": {"vmid": ct_vmid, "name": ct_info.get("name"), "node": ct_node},
            "backup_notes": backup_notes if backup else None,
            "result": result,
        }

    @server.tool("proxmox-notes-template")
    async def proxmox_notes_template(
        template_type: str,
        format: str = "html",
        variables: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        client = get_client()
        notes_manager = NotesManager(client)
        template_content = notes_manager.generate_template(
            template_type, format, variables
        )
        variables_used = re.findall(r"\{([A-Z_]+)\}", template_content)
        return {
            "template": template_content,
            "template_type": template_type,
            "format": format,
            "variables_used": list(set(variables_used)),
            "length": len(template_content),
        }
