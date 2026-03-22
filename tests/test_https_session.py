from __future__ import annotations

import requests

from proxmox_mcp.client import _TLSHttpAdapter, configure_proxmox_https_session


def test_configure_proxmox_https_session_mounts_custom_adapter() -> None:
    session = requests.Session()

    configure_proxmox_https_session(session)

    assert isinstance(session.adapters["https://"], _TLSHttpAdapter)
