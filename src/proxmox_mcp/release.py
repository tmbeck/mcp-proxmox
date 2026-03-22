from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = Path("pyproject.toml")
PACKAGE_INIT_PATH = Path("src/proxmox_mcp/__init__.py")
LOCKFILE_PATH = Path("uv.lock")
EXPECTED_RELEASE_PATHS = {PYPROJECT_PATH, PACKAGE_INIT_PATH, LOCKFILE_PATH}
_SEMVER_PATTERN = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
_INIT_VERSION_PATTERN = re.compile(
    r'^(?P<prefix>__version__ = ")(?P<version>\d+\.\d+\.\d+)(?P<suffix>")$',
    re.MULTILINE,
)


def bump_patch_version(version: str) -> str:
    match = _SEMVER_PATTERN.match(version.strip())
    if match is None:
        raise ValueError(f"Unsupported version format: {version!r}")

    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))
    return f"{major}.{minor}.{patch + 1}"


def _read_pyproject_version(repo_root: Path) -> str:
    pyproject_path = repo_root / PYPROJECT_PATH
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def _read_package_init_version(repo_root: Path) -> str:
    init_path = repo_root / PACKAGE_INIT_PATH
    init_text = init_path.read_text(encoding="utf-8")
    match = _INIT_VERSION_PATTERN.search(init_text)
    if match is None:
        raise ValueError(f"Could not find __version__ in {init_path}")
    return match.group("version")


def read_current_version(repo_root: Path) -> str:
    pyproject_version = _read_pyproject_version(repo_root)
    init_version = _read_package_init_version(repo_root)
    if pyproject_version != init_version:
        raise ValueError(
            "Version mismatch between pyproject.toml "
            f"({pyproject_version}) and src/proxmox_mcp/__init__.py ({init_version})"
        )
    return pyproject_version


def update_version_files(
    repo_root: Path, current_version: str, new_version: str
) -> None:
    pyproject_path = repo_root / PYPROJECT_PATH
    pyproject_text = pyproject_path.read_text(encoding="utf-8")
    current_pyproject_line = f'version = "{current_version}"'
    new_pyproject_line = f'version = "{new_version}"'
    if current_pyproject_line not in pyproject_text:
        raise ValueError(
            f"Could not find {current_pyproject_line!r} in {pyproject_path}"
        )
    pyproject_path.write_text(
        pyproject_text.replace(current_pyproject_line, new_pyproject_line, 1),
        encoding="utf-8",
    )

    init_path = repo_root / PACKAGE_INIT_PATH
    init_text = init_path.read_text(encoding="utf-8")
    new_init_text, count = _INIT_VERSION_PATTERN.subn(
        rf"\g<prefix>{new_version}\g<suffix>",
        init_text,
        count=1,
    )
    if count != 1:
        raise ValueError(f"Could not update __version__ in {init_path}")
    init_path.write_text(new_init_text, encoding="utf-8")


def _run(repo_root: Path, *args: str) -> None:
    subprocess.run(args, cwd=repo_root, check=True)


def _capture(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        args,
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def _parse_status_paths(status_output: str) -> set[Path]:
    paths: set[Path] = set()
    for raw_line in status_output.splitlines():
        if not raw_line:
            continue
        path_text = raw_line[3:]
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1]
        paths.add(Path(path_text))
    return paths


def _require_clean_worktree(repo_root: Path) -> None:
    status_output = _capture(repo_root, "git", "status", "--porcelain")
    if status_output.strip():
        raise RuntimeError("Release helper requires a clean git worktree")


def _require_missing_tag(repo_root: Path, tag_name: str) -> None:
    existing = _capture(repo_root, "git", "tag", "--list", tag_name)
    if existing.strip():
        raise RuntimeError(f"Tag already exists: {tag_name}")


def _require_only_expected_release_changes(repo_root: Path) -> None:
    status_output = _capture(repo_root, "git", "status", "--porcelain")
    changed_paths = _parse_status_paths(status_output)
    unexpected_paths = changed_paths - EXPECTED_RELEASE_PATHS
    if unexpected_paths:
        rendered_paths = ", ".join(sorted(str(path) for path in unexpected_paths))
        raise RuntimeError(
            f"Release helper found unexpected modified paths: {rendered_paths}"
        )


def create_patch_release(repo_root: Path) -> str:
    _require_clean_worktree(repo_root)

    current_version = read_current_version(repo_root)
    new_version = bump_patch_version(current_version)
    tag_name = f"v{new_version}"

    _require_missing_tag(repo_root, tag_name)
    print(f"Bumping version {current_version} -> {new_version}")

    update_version_files(repo_root, current_version, new_version)

    _run(repo_root, "uv", "lock")
    _run(repo_root, "uv", "run", "pytest")
    _require_only_expected_release_changes(repo_root)

    _run(
        repo_root,
        "git",
        "add",
        str(PYPROJECT_PATH),
        str(PACKAGE_INIT_PATH),
        str(LOCKFILE_PATH),
    )
    _run(
        repo_root,
        "git",
        "commit",
        "-m",
        f"chore: release v{new_version}",
        "-m",
        (
            f"Bump the package version to {new_version}, refresh the uv lockfile, "
            "and verify the release with the automated test suite."
        ),
    )
    _run(repo_root, "git", "tag", "-a", tag_name, "-m", tag_name)
    return new_version


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bump the patch version, refresh the lockfile, run tests, commit, and tag a release.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    try:
        new_version = create_patch_release(repo_root)
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        print(f"release helper failed: {exc}", file=sys.stderr)
        return 1

    print(f"Released v{new_version}. Next: git push origin main --tags")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
