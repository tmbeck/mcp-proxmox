from __future__ import annotations

from proxmox_mcp.control_plane import build_control_plane_argv


def test_control_plane_entrypoint_adds_default_profiles(monkeypatch) -> None:
    monkeypatch.delenv("PROXMOX_MCP_PROFILES", raising=False)
    argv = build_control_plane_argv([])

    assert argv == [
        "--profile",
        "control-plane",
        "--profile",
        "observability",
        "--profile",
        "automation",
        "--profile",
        "security",
    ]


def test_control_plane_entrypoint_respects_explicit_profile(monkeypatch) -> None:
    monkeypatch.delenv("PROXMOX_MCP_PROFILES", raising=False)
    argv = build_control_plane_argv(["--profile", "core"])
    assert argv == ["--profile", "core"]


def test_control_plane_entrypoint_respects_profile_env(monkeypatch) -> None:
    monkeypatch.setenv("PROXMOX_MCP_PROFILES", "full")
    argv = build_control_plane_argv([])
    assert argv == []
