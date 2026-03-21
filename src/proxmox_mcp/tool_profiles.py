from __future__ import annotations

import asyncio
import importlib.util
import os
from typing import Iterable, Sequence

from mcp.server.fastmcp import FastMCP


CORE_PROFILE = "core"
FULL_PROFILE = "full"
PROFILE_ENV_VAR = "PROXMOX_MCP_PROFILES"

PROFILE_DESCRIPTIONS: dict[str, str] = {
    CORE_PROFILE: "Direct Proxmox operations, provisioning, and guest lifecycle",
    "control-plane": "Shared-service features such as webhooks, integrations, and the optional API gateway",
    "observability": "Monitoring, logging, and performance-analysis helpers",
    "automation": "Higher-level orchestration helpers such as Docker Swarm, OpenShift, GitOps, and advanced storage/network automation",
    "security": "Security-adjacent helpers such as MFA, certificate management, and secret storage",
    "ai": "AI/optimization helpers",
    FULL_PROFILE: "Enable every optional profile in addition to core",
}

OPTIONAL_PROFILE_TOOL_NAMES: dict[str, set[str]] = {
    "control-plane": {
        "proxmox-setup-webhooks",
        "proxmox-api-gateway",
        "proxmox-integrate-service",
    },
    "observability": {
        "proxmox-setup-monitoring",
        "proxmox-setup-logging",
        "proxmox-performance-analysis",
    },
    "automation": {
        "proxmox-setup-replication",
        "proxmox-snapshot-policy",
        "proxmox-migrate-storage",
        "proxmox-terraform-plan",
        "proxmox-ansible-playbook",
        "proxmox-gitops-sync",
        "proxmox-create-vlan",
        "proxmox-configure-firewall",
        "proxmox-deploy-vpn-server",
        "proxmox-create-docker-swarm",
        "proxmox-create-docker-swarm-preset",
        "proxmox-docker-swarm-init",
        "proxmox-docker-swarm-join",
        "proxmox-docker-swarm-status",
        "proxmox-docker-service-create",
        "proxmox-docker-service-scale",
        "proxmox-docker-service-remove",
        "proxmox-docker-network-create",
        "proxmox-docker-service-logs",
        "proxmox-docker-execute-command",
        "proxmox-deploy-openshift-cluster",
        "proxmox-deploy-openshift-sno",
        "proxmox-openshift-cluster-status",
    },
    "security": {
        "proxmox-setup-mfa",
        "proxmox-manage-certificates",
        "proxmox-secret-store",
    },
    "ai": {
        "proxmox-ai-scaling",
        "proxmox-anomaly-detection",
        "proxmox-auto-optimize",
    },
}

PROFILE_REQUIRED_MODULES: dict[str, tuple[str, ...]] = {
    "control-plane": ("fastapi", "httpx", "uvicorn", "jwt"),
    "observability": (
        "prometheus_client",
        "grafana_api",
        "elasticsearch",
        "pandas",
        "numpy",
    ),
    "automation": ("git", "ansible_runner", "netaddr", "croniter", "schedule"),
    "security": ("pyotp", "qrcode", "hvac", "OpenSSL", "cryptography"),
    "ai": ("sklearn", "joblib", "pandas", "numpy"),
}


def _split_profile_values(values: Sequence[str]) -> list[str]:
    tokens: list[str] = []
    for value in values:
        for token in value.split(","):
            normalized = token.strip().lower()
            if normalized:
                tokens.append(normalized)
    return tokens


def resolve_profiles(requested: Sequence[str] | None = None) -> tuple[str, ...]:
    raw_values = list(requested or [])
    if not raw_values:
        env_value = os.getenv(PROFILE_ENV_VAR, "")
        if env_value.strip():
            raw_values = [env_value]

    tokens = _split_profile_values(raw_values)
    if not tokens:
        return (CORE_PROFILE,)

    active_profiles = {CORE_PROFILE}
    for token in tokens:
        if token == FULL_PROFILE:
            active_profiles.update(OPTIONAL_PROFILE_TOOL_NAMES.keys())
            continue
        if token == CORE_PROFILE:
            continue
        if token not in OPTIONAL_PROFILE_TOOL_NAMES:
            valid = ", ".join(sorted(PROFILE_DESCRIPTIONS.keys()))
            raise ValueError(f"Unknown profile '{token}'. Valid profiles: {valid}")
        active_profiles.add(token)

    return (CORE_PROFILE, *sorted(active_profiles - {CORE_PROFILE}))


def disabled_tools_for_profiles(active_profiles: Iterable[str]) -> set[str]:
    active = set(active_profiles)
    disabled: set[str] = set()
    for profile_name, tool_names in OPTIONAL_PROFILE_TOOL_NAMES.items():
        if profile_name not in active:
            disabled.update(tool_names)
    return disabled


def validate_profile_dependencies(active_profiles: Iterable[str]) -> None:
    active = set(active_profiles)
    missing_by_profile: dict[str, list[str]] = {}

    for profile_name in sorted(active - {CORE_PROFILE}):
        required_modules = PROFILE_REQUIRED_MODULES.get(profile_name, ())
        missing = [
            module_name
            for module_name in required_modules
            if importlib.util.find_spec(module_name) is None
        ]
        if missing:
            missing_by_profile[profile_name] = missing

    if not missing_by_profile:
        return

    requested_profiles = ",".join(sorted(missing_by_profile))
    details = "; ".join(
        f"{profile}: missing {', '.join(modules)}"
        for profile, modules in missing_by_profile.items()
    )
    raise ValueError(
        f"Selected profile dependencies are not installed ({details}). "
        f"Install the matching extras, e.g. `uv tool install '.[{requested_profiles}]'`, "
        "or use `uv sync --dev` in the repository."
    )


async def get_registered_tool_names(server: FastMCP) -> set[str]:
    return {tool.name for tool in await server.list_tools()}


def apply_profiles_to_server(
    server: FastMCP, active_profiles: Sequence[str]
) -> set[str]:
    registered_tool_names = asyncio.run(get_registered_tool_names(server))
    for tool_name in sorted(
        disabled_tools_for_profiles(active_profiles) & registered_tool_names
    ):
        server.remove_tool(tool_name)
    return registered_tool_names - disabled_tools_for_profiles(active_profiles)
