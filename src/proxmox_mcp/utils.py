from __future__ import annotations

import os
import time
import subprocess
import asyncio
import ipaddress
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List
from urllib.parse import urlparse


@dataclass
class ProxmoxEnv:
    base_url: str
    token_id: str
    token_secret: str
    verify: bool
    default_node: Optional[str] = None
    default_storage: Optional[str] = None
    default_bridge: Optional[str] = None


@dataclass
class ClusterConfig:
    """Configuration for a single Proxmox cluster."""

    name: str
    base_url: str
    token_id: str
    token_secret: str
    verify: bool
    default_node: Optional[str] = None
    default_storage: Optional[str] = None
    default_bridge: Optional[str] = None
    region: Optional[str] = None
    tier: Optional[str] = None

    def to_proxmox_env(self) -> ProxmoxEnv:
        """Convert ClusterConfig to ProxmoxEnv format."""
        return ProxmoxEnv(
            base_url=self.base_url,
            token_id=self.token_id,
            token_secret=self.token_secret,
            verify=self.verify,
            default_node=self.default_node,
            default_storage=self.default_storage,
            default_bridge=self.default_bridge,
        )


@dataclass
class ClusterRegistryConfig:
    """Configuration for the cluster registry."""

    clusters: Dict[str, ClusterConfig] = field(default_factory=dict)
    default_cluster: str = ""
    enable_cluster_validation: bool = True
    cache_ttl: int = 3600
    cluster_patterns: Dict[str, str] = field(
        default_factory=dict
    )  # Pattern -> cluster_name mapping


def strtobool(value: Optional[str], default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def is_multi_cluster_mode() -> bool:
    """Detect if multi-cluster mode is enabled."""
    return "PROXMOX_CLUSTERS" in os.environ


def read_env() -> ProxmoxEnv:
    """Read single cluster configuration (backward compatible)."""
    base_url = os.environ.get("PROXMOX_API_URL", "").strip()
    token_id = os.environ.get("PROXMOX_TOKEN_ID", "").strip()
    token_secret = os.environ.get("PROXMOX_TOKEN_SECRET", "").strip()
    verify = strtobool(os.environ.get("PROXMOX_VERIFY"), True)

    default_node = os.environ.get("PROXMOX_DEFAULT_NODE") or None
    default_storage = os.environ.get("PROXMOX_DEFAULT_STORAGE") or None
    default_bridge = os.environ.get("PROXMOX_DEFAULT_BRIDGE") or None

    if not base_url:
        raise ValueError("Missing PROXMOX_API_URL")
    if not token_id:
        raise ValueError("Missing PROXMOX_TOKEN_ID (format: user@realm!tokenname)")
    if not token_secret:
        raise ValueError("Missing PROXMOX_TOKEN_SECRET")

    return ProxmoxEnv(
        base_url=base_url,
        token_id=token_id,
        token_secret=token_secret,
        verify=verify,
        default_node=default_node,
        default_storage=default_storage,
        default_bridge=default_bridge,
    )


def read_multi_cluster_env() -> Dict[str, ClusterConfig]:
    """
    Read multiple cluster configurations from environment variables.

    Expects format:
        PROXMOX_CLUSTERS=cluster1,cluster2,cluster3
        PROXMOX_CLUSTER_cluster1_API_URL=...
        PROXMOX_CLUSTER_cluster1_TOKEN_ID=...
        PROXMOX_CLUSTER_cluster1_TOKEN_SECRET=...
        etc.
    """
    clusters_str = os.environ.get("PROXMOX_CLUSTERS", "").strip()

    if not clusters_str:
        raise ValueError("PROXMOX_CLUSTERS environment variable not set")

    cluster_names = [name.strip() for name in clusters_str.split(",") if name.strip()]

    if not cluster_names:
        raise ValueError("PROXMOX_CLUSTERS is empty")

    clusters: Dict[str, ClusterConfig] = {}

    for cluster_name in cluster_names:
        prefix = f"PROXMOX_CLUSTER_{cluster_name}_"

        base_url = os.environ.get(f"{prefix}API_URL", "").strip()
        token_id = os.environ.get(f"{prefix}TOKEN_ID", "").strip()
        token_secret = os.environ.get(f"{prefix}TOKEN_SECRET", "").strip()
        verify_str = os.environ.get(f"{prefix}VERIFY", "true").strip()

        if not base_url:
            raise ValueError(f"Missing {prefix}API_URL for cluster '{cluster_name}'")
        if not token_id:
            raise ValueError(
                f"Missing {prefix}TOKEN_ID for cluster '{cluster_name}' (format: user@realm!tokenname)"
            )
        if not token_secret:
            raise ValueError(
                f"Missing {prefix}TOKEN_SECRET for cluster '{cluster_name}'"
            )

        verify = strtobool(verify_str, True)

        default_node = os.environ.get(f"{prefix}DEFAULT_NODE") or None
        default_storage = os.environ.get(f"{prefix}DEFAULT_STORAGE") or None
        default_bridge = os.environ.get(f"{prefix}DEFAULT_BRIDGE") or None
        region = os.environ.get(f"{prefix}REGION") or None
        tier = os.environ.get(f"{prefix}TIER") or None

        config = ClusterConfig(
            name=cluster_name,
            base_url=base_url,
            token_id=token_id,
            token_secret=token_secret,
            verify=verify,
            default_node=default_node,
            default_storage=default_storage,
            default_bridge=default_bridge,
            region=region,
            tier=tier,
        )

        clusters[cluster_name] = config

    return clusters


def load_cluster_registry_config() -> ClusterRegistryConfig:
    """Load cluster registry configuration from environment."""
    clusters_str = os.environ.get("PROXMOX_CLUSTERS", "").strip()

    if clusters_str:
        # Multi-cluster mode
        clusters = read_multi_cluster_env()
        cluster_names = [
            name.strip() for name in clusters_str.split(",") if name.strip()
        ]
        default_cluster = cluster_names[0]  # First cluster is default

        # Load cluster patterns if defined
        patterns_str = os.environ.get("PROXMOX_CLUSTER_PATTERNS", "").strip()
        cluster_patterns: Dict[str, str] = {}
        if patterns_str:
            # Format: "prod-:cluster1,staging-:cluster2"
            for pattern_pair in patterns_str.split(","):
                if ":" in pattern_pair:
                    pattern, cluster = pattern_pair.split(":", 1)
                    cluster_patterns[pattern.strip()] = cluster.strip()

        return ClusterRegistryConfig(
            clusters=clusters,
            default_cluster=default_cluster,
            enable_cluster_validation=strtobool(
                os.environ.get("PROXMOX_CLUSTER_VALIDATION"), True
            ),
            cache_ttl=int(os.environ.get("PROXMOX_CLUSTER_CACHE_TTL", "3600")),
            cluster_patterns=cluster_patterns,
        )
    else:
        # Single cluster mode (backward compatible)
        env = read_env()
        single_cluster = ClusterConfig(
            name="default",
            base_url=env.base_url,
            token_id=env.token_id,
            token_secret=env.token_secret,
            verify=env.verify,
            default_node=env.default_node,
            default_storage=env.default_storage,
            default_bridge=env.default_bridge,
        )

        return ClusterRegistryConfig(
            clusters={"default": single_cluster},
            default_cluster="default",
            enable_cluster_validation=True,
        )


def parse_api_url(base_url: str) -> Dict[str, Any]:
    """Parse API URL into components suitable for proxmoxer.ProxmoxAPI.

    Accepts forms like:
      - https://host:8006
      - https://host:8006/api2/json
      - https://host
    """
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Invalid PROXMOX_API_URL: {base_url}")
    port = parsed.port or 8006
    return {
        "host": parsed.hostname,
        "port": port,
        "scheme": parsed.scheme,
    }


def split_token_id(token_id: str) -> Dict[str, str]:
    """Split token_id of the form 'user@realm!tokenname' into components."""
    if "!" not in token_id:
        raise ValueError(
            "PROXMOX_TOKEN_ID must include '!' separating user and token name, e.g. root@pam!mcp"
        )
    user, token_name = token_id.split("!", 1)
    if "@" not in user:
        raise ValueError(
            "PROXMOX_TOKEN_ID user part must include '@realm', e.g. root@pam!mcp"
        )
    return {"user": user, "token_name": token_name}


def _normalize_allowed_entry(entry: str) -> str:
    value = entry.strip()
    if not value:
        return ""
    if "://" in value:
        parsed = urlparse(value)
        return (parsed.hostname or "").lower()
    return value.lower()


def get_allowed_url_hosts() -> set[str]:
    """Read explicit outbound URL allowlist from environment.

    Format:
      PROXMOX_ALLOWED_URLS=example.com,https://api.example.com,10.0.0.15
    """
    raw = os.environ.get("PROXMOX_ALLOWED_URLS", "")
    allowed: set[str] = set()
    for item in raw.split(","):
        stripped = item.strip().lower()
        if not stripped:
            continue
        allowed.add(stripped)
        host = _normalize_allowed_entry(stripped)
        if host:
            allowed.add(host)
    return allowed


def is_private_host(host: str) -> bool:
    """Return True when host is clearly private/local without DNS lookups."""
    normalized = host.strip().lower()
    if normalized in {"localhost", "::1"}:
        return True
    if "." not in normalized:
        return True
    if normalized.endswith(".local") or normalized.endswith(".internal"):
        return True

    try:
        ip = ipaddress.ip_address(normalized)
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return False


def require_allowed_url(url: str, *, purpose: str, user_provided: bool = False) -> None:
    """Enforce outbound egress policy for all HTTP targets.

    Policy (strict by default):
      - private/local hosts are allowed
      - public hosts require explicit allowlist via PROXMOX_ALLOWED_URLS
      - non-user-provided public URLs are rejected unless allowlisted
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError(f"Invalid URL for {purpose}: {url}")

    if is_private_host(host):
        return

    allowed_hosts = get_allowed_url_hosts()
    if host in allowed_hosts or url.lower() in allowed_hosts:
        return

    source_hint = "user-provided" if user_provided else "built-in"
    raise ValueError(
        f"Blocked outbound request to public host '{host}' for {purpose}. "
        f"Source={source_hint}. Add host/url to PROXMOX_ALLOWED_URLS to allow it."
    )


def now_ms() -> int:
    return int(time.time() * 1000)


def format_size(size_bytes: int) -> str:
    """Format byte size into human readable format."""
    if size_bytes == 0:
        return "0 B"

    size_value = float(size_bytes)
    size_names = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while size_value >= 1024 and i < len(size_names) - 1:
        size_value /= 1024.0
        i += 1

    if i == 0:
        return f"{int(size_value)} {size_names[i]}"
    else:
        return f"{size_value:.1f} {size_names[i]}"


async def run_command(
    cmd: list[str] | str,
    input_data: Optional[str] = None,
    shell: bool = False,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run a command asynchronously and return the result."""
    try:
        if shell:
            if not isinstance(cmd, str):
                raise ValueError("When shell=True, cmd must be a single string")
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdin=subprocess.PIPE if input_data else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
        else:
            if not isinstance(cmd, list):
                raise ValueError("When shell=False, cmd must be a list of arguments")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=subprocess.PIPE if input_data else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

        stdout, stderr = await process.communicate(
            input=input_data.encode() if input_data else None
        )

        return {
            "return_code": process.returncode,
            "stdout": stdout.decode() if stdout else "",
            "stderr": stderr.decode() if stderr else "",
            "command": cmd,
        }

    except Exception as e:
        return {
            "return_code": -1,
            "stdout": "",
            "stderr": str(e),
            "command": cmd,
            "error": str(e),
        }


def format_error(
    message: str, context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Format an error response with context."""
    error_response = {"error": True, "message": message, "timestamp": time.time()}

    if context:
        error_response["context"] = context

    return error_response
