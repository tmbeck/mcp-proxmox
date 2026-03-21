from __future__ import annotations

import os
from pathlib import Path


STATE_DIR_ENV_VAR = "PROXMOX_MCP_STATE_DIR"
DEFAULT_STATE_DIRNAME = ".proxmox_mcp"


def get_state_root(*, create: bool = True) -> Path:
    custom_root = os.getenv(STATE_DIR_ENV_VAR, "").strip()
    root = (
        Path(custom_root).expanduser()
        if custom_root
        else Path.home() / DEFAULT_STATE_DIRNAME
    )
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def get_state_subdir(*parts: str, create: bool = True) -> Path:
    path = get_state_root(create=create)
    for part in parts:
        path /= part
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def get_state_file(*parts: str, create_parent: bool = False) -> Path:
    if not parts:
        raise ValueError("at least one path component is required")
    path = get_state_root(create=create_parent)
    for part in parts:
        path /= part
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path
