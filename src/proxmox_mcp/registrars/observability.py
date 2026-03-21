from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP


def register_observability_tools(
    server: FastMCP,
    get_client: Callable[[], Any],
    get_monitoring_manager: Callable[[Any], Any],
) -> None:
    @server.tool("proxmox-setup-monitoring")
    async def proxmox_setup_monitoring(
        stack_type: str = "prometheus",
        retention_days: int = 30,
        alert_rules: Optional[List[str]] = None,
        webhook_url: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Deploy comprehensive monitoring stack"""
        client = get_client()
        monitoring_manager = get_monitoring_manager(client)
        return await monitoring_manager.setup_monitoring(
            stack_type, retention_days, alert_rules, webhook_url, dry_run
        )

    @server.tool("proxmox-setup-logging")
    async def proxmox_setup_logging(
        log_stack: str = "elk",
        centralized: bool = True,
        retention_policy: str = "30d",
        indices: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Setup centralized logging for all VMs"""
        client = get_client()
        monitoring_manager = get_monitoring_manager(client)
        return await monitoring_manager.setup_logging(
            log_stack, centralized, retention_policy, indices, dry_run
        )

    @server.tool("proxmox-performance-analysis")
    async def proxmox_performance_analysis(
        time_range: str = "24h",
        metrics: Optional[List[str]] = None,
        generate_report: bool = True,
        optimization_suggestions: bool = True,
    ) -> Dict[str, Any]:
        """Analyze VM and host performance with optimization suggestions"""
        client = get_client()
        monitoring_manager = get_monitoring_manager(client)
        if metrics is None:
            metrics = ["cpu", "memory", "disk", "network"]
        return await monitoring_manager.performance_analysis(
            time_range, metrics, generate_report, optimization_suggestions
        )
