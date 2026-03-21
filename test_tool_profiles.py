from __future__ import annotations

from proxmox_mcp.tool_profiles import (
    CORE_PROFILE,
    disabled_tools_for_profiles,
    resolve_profiles,
)


def test_resolve_profiles_defaults_to_core(monkeypatch) -> None:
    monkeypatch.delenv("PROXMOX_MCP_PROFILES", raising=False)
    assert resolve_profiles() == (CORE_PROFILE,)


def test_resolve_profiles_supports_composition_and_full() -> None:
    assert resolve_profiles(["control-plane,observability"]) == (
        CORE_PROFILE,
        "control-plane",
        "observability",
    )
    assert resolve_profiles(["full"]) == (
        CORE_PROFILE,
        "ai",
        "automation",
        "control-plane",
        "observability",
        "security",
    )


def test_disabled_tools_for_core_excludes_optional_surfaces() -> None:
    disabled = disabled_tools_for_profiles((CORE_PROFILE,))
    assert "proxmox-api-gateway" in disabled
    assert "proxmox-setup-monitoring" in disabled
    assert "proxmox-terraform-plan" in disabled
    assert "proxmox-setup-mfa" in disabled
    assert "proxmox-ai-scaling" in disabled
    assert "proxmox-create-vm" not in disabled
    assert "proxmox-download-os-template" not in disabled


def test_disabled_tools_for_composed_profiles_keeps_requested_extensions() -> None:
    disabled = disabled_tools_for_profiles(
        (CORE_PROFILE, "control-plane", "observability")
    )
    assert "proxmox-api-gateway" not in disabled
    assert "proxmox-setup-monitoring" not in disabled
    assert "proxmox-terraform-plan" in disabled
    assert "proxmox-ai-scaling" in disabled
