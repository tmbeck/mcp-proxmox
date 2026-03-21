from __future__ import annotations

import tomllib
from pathlib import Path

import proxmox_mcp


def test_package_version_matches_pyproject() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == proxmox_mcp.__version__
