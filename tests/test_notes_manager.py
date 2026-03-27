from __future__ import annotations

import html

from proxmox_mcp.notes_manager import NotesManager


class _DummyClient:
    pass


def test_generate_html_template_escapes_user_variables() -> None:
    manager = NotesManager(_DummyClient())
    vm_name = '<script>alert("xss")</script>'
    owner = "Alice & Bob"

    result = manager.generate_template(
        "web-server",
        "html",
        {"VM_NAME": vm_name, "OWNER": owner},
    )

    assert html.escape(vm_name, quote=True) in result
    assert html.escape(owner, quote=True) in result
    assert vm_name not in result


def test_generate_markdown_template_preserves_literal_values() -> None:
    manager = NotesManager(_DummyClient())

    result = manager.generate_template(
        "generic",
        "markdown",
        {"DESCRIPTION": "<b>literal</b>"},
    )

    assert "<b>literal</b>" in result
