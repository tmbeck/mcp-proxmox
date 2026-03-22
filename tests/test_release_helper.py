from __future__ import annotations

from pathlib import Path

from proxmox_mcp.release import (
    bump_patch_version,
    read_current_version,
    update_version_files,
)


def test_bump_patch_version_increments_patch_component() -> None:
    assert bump_patch_version("0.2.1") == "0.2.2"


def test_read_current_version_requires_matching_files(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.2.1"\n',
        encoding="utf-8",
    )
    package_dir = tmp_path / "src" / "proxmox_mcp"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        '__version__ = "0.2.1"\n',
        encoding="utf-8",
    )

    assert read_current_version(tmp_path) == "0.2.1"


def test_update_version_files_updates_pyproject_and_package_init(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.2.1"\n',
        encoding="utf-8",
    )
    package_dir = tmp_path / "src" / "proxmox_mcp"
    package_dir.mkdir(parents=True)
    init_path = package_dir / "__init__.py"
    init_path.write_text(
        '__version__ = "0.2.1"\n',
        encoding="utf-8",
    )

    update_version_files(tmp_path, "0.2.1", "0.2.2")

    assert 'version = "0.2.2"' in (tmp_path / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert '__version__ = "0.2.2"' in init_path.read_text(encoding="utf-8")
