from __future__ import annotations

from pathlib import Path

import proxmox_mcp.runtime_env as runtime_env


def test_load_runtime_env_from_explicit_path(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / "proxmox.env"
    env_file.write_text(
        'PROXMOX_API_URL="https://pve.example:8006"\n', encoding="utf-8"
    )
    monkeypatch.delenv("PROXMOX_API_URL", raising=False)

    loaded = runtime_env.load_runtime_env(str(env_file), force=True)

    assert loaded == str(env_file)
    assert runtime_env.os.environ["PROXMOX_API_URL"] == "https://pve.example:8006"


def test_load_runtime_env_from_env_var(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / "tool.env"
    env_file.write_text('PROXMOX_DEFAULT_NODE="pve1"\n', encoding="utf-8")
    monkeypatch.delenv("PROXMOX_DEFAULT_NODE", raising=False)
    monkeypatch.setenv(runtime_env.ENV_FILE_ENV_VAR, str(env_file))

    loaded = runtime_env.load_runtime_env(force=True)

    assert loaded == str(env_file)
    assert runtime_env.os.environ["PROXMOX_DEFAULT_NODE"] == "pve1"
