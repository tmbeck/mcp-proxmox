from __future__ import annotations

import asyncio
from typing import Any, cast

import jwt
from fastapi.testclient import TestClient

from proxmox_mcp.integrations import IntegrationManager


class _DummyClient:
    pass


TEST_JWT_SECRET = "test-secret-with-at-least-32-bytes"


def test_api_gateway_requires_jwt_secret(monkeypatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("PROXMOX_API_GATEWAY_ALLOW_REMOTE", raising=False)

    manager = IntegrationManager(cast(Any, _DummyClient()))
    result = asyncio.run(
        manager.api_gateway(
            enable_rate_limiting=False,
            auth_providers=["jwt"],
            cors_enabled=False,
        )
    )

    assert result["error"] is True
    assert "JWT_SECRET must be set" in result["message"]


def test_api_gateway_defaults_to_local_and_protects_management_routes(
    monkeypatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.delenv("PROXMOX_API_GATEWAY_ALLOW_REMOTE", raising=False)

    manager = IntegrationManager(cast(Any, _DummyClient()))
    manager.webhooks = {
        "wh-1": {
            "id": "wh-1",
            "url": "http://127.0.0.1:9999/hook",
            "events": ["vm_start"],
            "secret_token": "super-secret",
            "retry_policy": {"max_retries": 1},
            "created_at": "2026-03-21T00:00:00",
            "enabled": True,
            "stats": {"total_sent": 0, "successful": 0, "failed": 0, "last_sent": None},
        }
    }

    result = asyncio.run(
        manager.api_gateway(
            enable_rate_limiting=False,
            auth_providers=["jwt"],
            cors_enabled=False,
        )
    )

    assert result["status"] == "configured"
    assert result["bind_host"] == "127.0.0.1"
    assert result["remote_exposure"] is False

    assert manager.api_app is not None
    client = TestClient(manager.api_app)

    assert client.get("/health").status_code == 200
    assert client.get("/webhooks").status_code == 401

    token = jwt.encode({"sub": "tester"}, TEST_JWT_SECRET, algorithm="HS256")
    response = client.get("/webhooks", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["webhooks"][0]["secret_token"] == "***"


def test_api_gateway_remote_bind_requires_explicit_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.delenv("PROXMOX_API_GATEWAY_ALLOW_REMOTE", raising=False)

    manager = IntegrationManager(cast(Any, _DummyClient()))
    result = asyncio.run(
        manager.api_gateway(
            enable_rate_limiting=False,
            auth_providers=["jwt"],
            cors_enabled=False,
            bind_host="0.0.0.0",
        )
    )

    assert result["error"] is True
    assert "PROXMOX_API_GATEWAY_ALLOW_REMOTE=true" in result["message"]
