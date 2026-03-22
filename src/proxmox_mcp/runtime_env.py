from __future__ import annotations

import os
from typing import Optional

from dotenv import find_dotenv, load_dotenv


ENV_FILE_ENV_VAR = "PROXMOX_ENV_FILE"

_loaded_path: Optional[str] = None
_loaded = False


def load_runtime_env(
    env_file: Optional[str] = None, *, force: bool = False
) -> Optional[str]:
    """Load runtime environment for CLI/MCP entrypoints.

    Precedence:
    1. explicit ``env_file`` argument
    2. ``PROXMOX_ENV_FILE`` environment variable
    3. ``.env`` discovered from the current working directory upward

    This is more predictable for installed CLI tools than relying on
    python-dotenv's default frame-based search, which follows the installed
    package path instead of the user's project/config location.
    """

    global _loaded, _loaded_path

    if _loaded and not force and env_file is None:
        return _loaded_path

    candidate = env_file or os.getenv(ENV_FILE_ENV_VAR, "").strip() or None
    if candidate is None:
        found = find_dotenv(usecwd=True)
        candidate = found or None

    if candidate:
        load_dotenv(candidate, override=False)
        _loaded_path = candidate
    else:
        _loaded_path = None

    _loaded = True
    return _loaded_path
