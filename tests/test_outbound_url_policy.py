"""Regression tests for outbound URL policy enforcement."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "proxmox_mcp"


ALLOWLISTED_FILES = {
    "client.py",
    "windows.py",
    "rhcos.py",
}


class _HttpCallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.http_calls: list[int] = []
        self.http_client_vars: set[str] = set()

    def _mark_http_client_target(self, target: ast.expr | None) -> None:
        if isinstance(target, ast.Name):
            self.http_client_vars.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._mark_http_client_target(elt)

    def _is_httpx_client_constructor(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "httpx"
            and node.func.attr in {"AsyncClient", "Client"}
        )

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._is_httpx_client_constructor(node.value):
            for target in node.targets:
                self._mark_http_client_target(target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value and self._is_httpx_client_constructor(node.value):
            self._mark_http_client_target(node.target)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if self._is_httpx_client_constructor(item.context_expr):
                self._mark_http_client_target(item.optional_vars)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            if self._is_httpx_client_constructor(item.context_expr):
                self._mark_http_client_target(item.optional_vars)
        self.generic_visit(node)

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
            if (
                isinstance(func.value, ast.Name)
                and func.value.id in self.http_client_vars
            ):
                self.http_calls.append(node.lineno)
        self.generic_visit(node)


def _collect_http_call_lines(source: str) -> list[int]:
    tree = ast.parse(source)
    visitor = _HttpCallVisitor()
    visitor.visit(tree)
    return visitor.http_calls


def _count_policy_gate_calls(source: str) -> int:
    return source.count("require_allowed_url(")


def test_http_call_visitor_detects_httpx_client_instance_calls() -> None:
    source = """
import httpx

async def send_events():
    async with httpx.AsyncClient() as client:
        await client.post("https://example.com")
        await client.get("https://example.com/health")
"""

    assert _collect_http_call_lines(source) == [6, 7]


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
