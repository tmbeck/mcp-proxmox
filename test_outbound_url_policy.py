"""Regression tests for outbound URL policy enforcement."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src" / "proxmox_mcp"


ALLOWLISTED_FILES = {
    "client.py",
    "windows.py",
    "rhcos.py",
    "integrations.py",
}


class _HttpCallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.http_calls: list[int] = []

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {
            "get",
            "post",
            "put",
            "delete",
            "patch",
        }:
            if isinstance(func.value, ast.Name) and func.value.id == "requests":
                self.http_calls.append(node.lineno)
            if isinstance(func.value, ast.Name) and func.value.id == "httpx":
                self.http_calls.append(node.lineno)
        self.generic_visit(node)


def _collect_http_call_lines(source: str) -> list[int]:
    tree = ast.parse(source)
    visitor = _HttpCallVisitor()
    visitor.visit(tree)
    return visitor.http_calls


def _count_policy_gate_calls(source: str) -> int:
    return source.count("require_allowed_url(")


def test_outbound_http_calls_are_restricted_to_allowlisted_files() -> None:
    offenders: list[str] = []
    for path in SRC.glob("*.py"):
        if path.name in {"utils.py", "__init__.py"}:
            continue
        source = path.read_text(encoding="utf-8")
        calls = _collect_http_call_lines(source)
        if calls and path.name not in ALLOWLISTED_FILES:
            offenders.append(f"{path.name}: HTTP calls at lines {calls}")

    assert not offenders, "Unexpected outbound HTTP call sites found:\n" + "\n".join(
        offenders
    )


def test_allowlisted_http_files_use_policy_gate() -> None:
    failures: list[str] = []
    for name in sorted(ALLOWLISTED_FILES):
        path = SRC / name
        source = path.read_text(encoding="utf-8")
        http_call_lines = _collect_http_call_lines(source)
        if not http_call_lines:
            continue
        policy_calls = _count_policy_gate_calls(source)
        if policy_calls < len(http_call_lines):
            failures.append(
                f"{name}: {len(http_call_lines)} HTTP calls but only {policy_calls} require_allowed_url() checks"
            )

    assert not failures, "Outbound policy gate coverage is incomplete:\n" + "\n".join(
        failures
    )
