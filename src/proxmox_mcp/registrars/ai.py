from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from mcp.server.fastmcp import FastMCP


def register_ai_tools(
    server: FastMCP,
    get_client: Callable[[], Any],
    get_ai_manager: Callable[[Any], Any],
) -> None:
    @server.tool("proxmox-ai-scaling")
    async def proxmox_ai_scaling(
        vmid: int,
        enable_prediction: bool = True,
        metrics_window: str = "7d",
        scaling_policy: Optional[Dict[str, Any]] = None,
        node: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """AI-powered predictive scaling based on usage patterns"""
        client = get_client()
        ai_manager = get_ai_manager(client)
        return await ai_manager.ai_scaling(
            vmid, enable_prediction, metrics_window, scaling_policy, node, dry_run
        )

    @server.tool("proxmox-anomaly-detection")
    async def proxmox_anomaly_detection(
        detection_type: str = "performance",
        sensitivity: str = "medium",
        alert_threshold: float = 0.85,
        auto_remediation: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """AI-powered anomaly detection for proactive issue resolution"""
        client = get_client()
        ai_manager = get_ai_manager(client)
        return await ai_manager.anomaly_detection(
            detection_type, sensitivity, alert_threshold, auto_remediation, dry_run
        )

    @server.tool("proxmox-auto-optimize")
    async def proxmox_auto_optimize(
        optimization_scope: str = "all",
        learning_period: int = 7,
        apply_recommendations: bool = False,
        rollback_enabled: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Automatically optimize VM configurations based on usage patterns"""
        client = get_client()
        ai_manager = get_ai_manager(client)
        return await ai_manager.auto_optimize(
            optimization_scope,
            learning_period,
            apply_recommendations,
            rollback_enabled,
            dry_run,
        )
