from __future__ import annotations

import pytest
import requests

from proxmox_mcp.client import (
    ProxmoxClient,
    _TLSHttpAdapter,
    configure_proxmox_https_session,
)


def test_configure_proxmox_https_session_mounts_custom_adapter() -> None:
    session = requests.Session()

    configure_proxmox_https_session(session)

    assert isinstance(session.adapters["https://"], _TLSHttpAdapter)


def _client() -> ProxmoxClient:
    return ProxmoxClient(
        base_url="https://pve.invalid:8006",
        token_id="root@pam!t",
        token_secret="x",
        verify=True,
    )


@pytest.mark.parametrize(
    "bad", ["../access/users", "pve/../../access", "pve?x=1", "pve#f", "pve%2e", "a b", ".."]
)
def test_api_path_segments_reject_traversal(bad: str) -> None:
    with pytest.raises(ValueError):
        _client().api.nodes(bad)


def test_api_path_segments_allow_normal_ids() -> None:
    api = _client().api
    url = api.nodes("pve-1").qemu(100).snapshot("snap_1")._store["base_url"]
    assert url.endswith("/nodes/pve-1/qemu/100/snapshot/snap_1")
    assert api.cluster.tasks("UPID:pve:0001:abc:qmstart:100:root@pam:")
