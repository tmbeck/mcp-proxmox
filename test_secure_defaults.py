from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import yaml

import proxmox_mcp.storage_advanced as storage_advanced_module
from proxmox_mcp.client import get_default_lxc_password
from proxmox_mcp.infrastructure import InfrastructureManager
from proxmox_mcp.monitoring import MonitoringManager
from proxmox_mcp.storage_advanced import AdvancedStorageManager


class _DummyClient:
    host = "proxmox.example.com"
    base_url = "https://proxmox.example.com:8006"
    verify = True


def test_get_default_lxc_password_requires_env(monkeypatch) -> None:
    monkeypatch.delenv("PROXMOX_DEFAULT_LXC_PASSWORD", raising=False)

    try:
        get_default_lxc_password()
    except ValueError as exc:
        assert "PROXMOX_DEFAULT_LXC_PASSWORD" in str(exc)
    else:
        raise AssertionError("Expected missing LXC password to raise ValueError")


def test_monitoring_configs_use_local_bind_and_secret_placeholders(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    manager = MonitoringManager(cast(Any, _DummyClient()))

    grafana_result = asyncio.run(manager._setup_grafana())
    grafana_compose = yaml.safe_load(
        Path(grafana_result["grafana_compose"]).read_text()
    )
    assert grafana_compose["services"]["grafana"]["ports"] == ["127.0.0.1:3000:3000"]
    assert (
        grafana_compose["services"]["grafana"]["environment"][
            "GF_SECURITY_ADMIN_PASSWORD"
        ]
        == "${PROXMOX_GRAFANA_ADMIN_PASSWORD:?set PROXMOX_GRAFANA_ADMIN_PASSWORD}"
    )
    assert grafana_result["admin_password_env"] == "PROXMOX_GRAFANA_ADMIN_PASSWORD"

    elk_result = asyncio.run(manager._setup_elk_stack())
    elk_compose = yaml.safe_load(Path(elk_result["elk_compose"]).read_text())
    assert elk_compose["services"]["elasticsearch"]["ports"] == ["127.0.0.1:9200:9200"]
    assert elk_compose["services"]["kibana"]["ports"] == ["127.0.0.1:5601:5601"]
    assert (
        elk_compose["services"]["elasticsearch"]["environment"][
            "xpack.security.enabled"
        ]
        == "true"
    )
    assert (
        elk_compose["services"]["elasticsearch"]["environment"]["ELASTIC_PASSWORD"]
        == "${PROXMOX_ELASTIC_PASSWORD:?set PROXMOX_ELASTIC_PASSWORD}"
    )
    logstash_config = Path(elk_result["logstash_config"]).read_text()
    assert 'password => "${PROXMOX_ELASTIC_PASSWORD}"' in logstash_config


def test_terraform_provider_follows_client_tls_verification(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    secure_client = cast(Any, _DummyClient())
    secure_manager = InfrastructureManager(secure_client)
    secure_provider = secure_manager._generate_terraform_provider()
    assert (
        'pm_api_url = "https://proxmox.example.com:8006/api2/json"' in secure_provider
    )
    assert "pm_tls_insecure = false" in secure_provider

    insecure_client = cast(
        Any,
        type(
            "_InsecureClient",
            (),
            {
                "base_url": "https://proxmox.example.com:8006",
                "verify": False,
            },
        )(),
    )
    insecure_manager = InfrastructureManager(insecure_client)
    insecure_provider = insecure_manager._generate_terraform_provider()
    assert "pm_tls_insecure = true" in insecure_provider


def test_storage_optimization_uses_safe_mount_command(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    calls: dict[str, Any] = {}

    async def fake_run_command(cmd: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return {
            "return_code": 0,
            "stdout": "store1 on /mnt/store1 type ext4 (rw,relatime)",
            "stderr": "",
        }

    monkeypatch.setattr(storage_advanced_module, "run_command", fake_run_command)
    manager = AdvancedStorageManager(cast(Any, _DummyClient()))

    result = asyncio.run(manager._optimize_directory("store1", "pve"))

    assert calls["cmd"] == ["mount"]
    assert calls["kwargs"] == {}
    assert result["optimizations"][0]["optimization"] == "noatime_mount_option"
