from __future__ import annotations

import os
import sys
from typing import Optional, Sequence

from .server import main as server_main
from .tool_profiles import PROFILE_ENV_VAR


DEFAULT_CONTROL_PLANE_PROFILES = (
    "control-plane",
    "observability",
    "automation",
    "security",
)


def build_control_plane_argv(argv: Sequence[str]) -> list[str]:
    args = list(argv)
    if os.getenv(PROFILE_ENV_VAR, "").strip():
        return args
    if any(arg == "--profile" or arg.startswith("--profile=") for arg in args):
        return args

    profile_args: list[str] = []
    for profile in DEFAULT_CONTROL_PLANE_PROFILES:
        profile_args.extend(["--profile", profile])
    return profile_args + args


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = list(argv) if argv is not None else sys.argv[1:]
    server_main(build_control_plane_argv(args))
