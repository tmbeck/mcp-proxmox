from __future__ import annotations

from pathlib import Path

import pytest

from proxmox_mcp.state import get_state_file, get_state_root, get_state_subdir


def test_state_root_defaults_under_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PROXMOX_MCP_STATE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    root = get_state_root()

    assert root == tmp_path / ".proxmox_mcp"
    assert root.exists()


def test_state_root_honors_explicit_override(monkeypatch, tmp_path: Path) -> None:
    custom_root = tmp_path / "custom-state"
    monkeypatch.setenv("PROXMOX_MCP_STATE_DIR", str(custom_root))

    subdir = get_state_subdir("integrations")
    secret_file = get_state_file("secrets", "token.enc", create_parent=True)

    assert subdir == custom_root / "integrations"
    assert secret_file == custom_root / "secrets" / "token.enc"
    assert subdir.exists()
    assert secret_file.parent.exists()


def test_state_subdir_rejects_parent_directory_escape(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PROXMOX_MCP_STATE_DIR", str(tmp_path / "state"))

    with pytest.raises(ValueError, match="state path"):
        get_state_subdir("..", "escape", create=False)


def test_state_file_rejects_absolute_path_component(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PROXMOX_MCP_STATE_DIR", str(tmp_path / "state"))

    with pytest.raises(ValueError, match="state path"):
        get_state_file("/tmp", "escape.txt")
