from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP


def register_security_tools(
    server: FastMCP,
    get_client: Callable[[], Any],
    get_security_manager: Callable[[Any], Any],
) -> None:
    @server.tool("proxmox-setup-mfa")
    async def proxmox_setup_mfa(
        username: str,
        mfa_type: str = "totp",
        qr_code_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Setup multi-factor authentication for Proxmox users"""
        client = get_client()
        security_manager = get_security_manager(client)
        return await security_manager.setup_mfa(
            username, mfa_type, qr_code_path, dry_run
        )

    @server.tool("proxmox-manage-certificates")
    async def proxmox_manage_certificates(
        action: str,
        cert_type: str = "lets_encrypt",
        domains: Optional[List[str]] = None,
        auto_renew: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Manage SSL certificates for Proxmox and VMs"""
        client = get_client()
        security_manager = get_security_manager(client)
        return await security_manager.manage_certificates(
            action, cert_type, domains or [], auto_renew, dry_run
        )

    @server.tool("proxmox-secret-store")
    async def proxmox_secret_store(
        action: str,
        secret_name: str,
        secret_value: Optional[str] = None,
        encryption_type: str = "aes256",
    ) -> Dict[str, Any]:
        """Secure secret storage for VM credentials and API keys"""
        client = get_client()
        security_manager = get_security_manager(client)

        if action == "store":
            if not secret_value:
                raise ValueError("secret_value is required for store action")
            return await security_manager.store_secret(
                secret_name, secret_value, encryption_type
            )
        if action == "retrieve":
            return await security_manager.retrieve_secret(secret_name, encryption_type)
        if action == "delete":
            return await security_manager.delete_secret(secret_name)
        if action == "rotate":
            if not secret_value:
                raise ValueError("secret_value is required for rotate action")
            return await security_manager.rotate_secret(
                secret_name, secret_value, encryption_type
            )
        raise ValueError(f"Unknown action: {action}")
