from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP


def register_control_plane_tools(
    server: FastMCP,
    get_client: Callable[[], Any],
    get_integration_manager: Callable[[Any], Any],
) -> None:
    @server.tool("proxmox-setup-webhooks")
    async def proxmox_setup_webhooks(
        webhook_url: str,
        events: Optional[List[str]] = None,
        secret_token: Optional[str] = None,
        retry_policy: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Setup webhooks for event-driven automation"""
        client = get_client()
        integration_manager = get_integration_manager(client)
        if events is None:
            events = ["vm_start", "vm_stop", "backup_complete"]
        return await integration_manager.setup_webhooks(
            webhook_url, events, secret_token, retry_policy, dry_run
        )

    @server.tool("proxmox-api-gateway")
    async def proxmox_api_gateway(
        enable_rate_limiting: bool = True,
        auth_providers: Optional[List[str]] = None,
        cors_enabled: bool = True,
        api_versioning: bool = True,
        port: int = 8000,
        bind_host: Optional[str] = None,
        cors_origins: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Deploy API gateway for enhanced API management"""
        client = get_client()
        integration_manager = get_integration_manager(client)
        if auth_providers is None:
            auth_providers = ["jwt"]
        return await integration_manager.api_gateway(
            enable_rate_limiting,
            auth_providers,
            cors_enabled,
            api_versioning,
            port,
            bind_host,
            cors_origins,
            dry_run,
        )

    @server.tool("proxmox-integrate-service")
    async def proxmox_integrate_service(
        service_type: str,
        credentials: Dict[str, str],
        notification_types: Optional[List[str]] = None,
        webhook_url: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Integrate with external services for notifications and automation"""
        client = get_client()
        integration_manager = get_integration_manager(client)
        if notification_types is None:
            notification_types = ["alerts", "deployments"]
        return await integration_manager.integrate_service(
            service_type, credentials, notification_types, webhook_url, dry_run
        )
