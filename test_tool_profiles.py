from __future__ import annotations

from proxmox_mcp.tool_profiles import (
    CORE_PROFILE,
    disabled_tools_for_profiles,
    resolve_profiles,
    validate_profile_dependencies,
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
    assert "proxmox-create-windows-vm" not in disabled
    assert "proxmox-create-rhcos-vm" not in disabled


def test_disabled_tools_for_composed_profiles_keeps_requested_extensions() -> None:
    disabled = disabled_tools_for_profiles(
        (CORE_PROFILE, "control-plane", "observability")
    )
    assert "proxmox-api-gateway" not in disabled
    assert "proxmox-setup-monitoring" not in disabled
    assert "proxmox-terraform-plan" in disabled
    assert "proxmox-ai-scaling" in disabled


def test_validate_profile_dependencies_allows_core_only() -> None:
    validate_profile_dependencies((CORE_PROFILE,))


def test_validate_profile_dependencies_reports_missing_modules(monkeypatch) -> None:
    import proxmox_mcp.tool_profiles as tool_profiles

    real_find_spec = tool_profiles.importlib.util.find_spec

    def fake_find_spec(name: str):
        if name in {"fastapi", "httpx"}:
            return None
        return real_find_spec(name)

    monkeypatch.setattr(tool_profiles.importlib.util, "find_spec", fake_find_spec)

    try:
        validate_profile_dependencies((CORE_PROFILE, "control-plane"))
    except ValueError as exc:
        message = str(exc)
        assert "control-plane" in message
        assert "fastapi" in message
        assert "httpx" in message
    else:
        raise AssertionError(
            "Expected missing optional dependencies to raise ValueError"
        )
