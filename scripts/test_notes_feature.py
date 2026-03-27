#!/usr/bin/env python3
"""Test script for VM/LXC Notes Management feature"""

import sys
import os
import asyncio

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


async def test_notes_feature():
    """Test all notes management functionality"""

    print("🧪 Testing VM/LXC Notes Management Feature")
    print("=" * 70)

    try:
        # Test 1: Import NotesManager
        print("\n1️⃣ Testing NotesManager Import...")
        from proxmox_mcp.notes_manager import NotesManager

        print("✅ NotesManager imported successfully")

        # Test 2: Import MCP tools
        print("\n2️⃣ Testing MCP Tools Import...")
        from proxmox_mcp.server import (
            proxmox_vm_notes_read,
            proxmox_vm_notes_update,
            proxmox_vm_notes_remove,
            proxmox_lxc_notes_read,
            proxmox_lxc_notes_update,
            proxmox_lxc_notes_remove,
            proxmox_notes_template,
        )

        imported_tools = (
            proxmox_vm_notes_read,
            proxmox_vm_notes_update,
            proxmox_vm_notes_remove,
            proxmox_lxc_notes_read,
            proxmox_lxc_notes_update,
            proxmox_lxc_notes_remove,
            proxmox_notes_template,
        )
        assert len(imported_tools) == 7

        print("✅ All 7 MCP tools imported successfully")

        # Test 3: Test format detection
        print("\n3️⃣ Testing Format Detection...")

        # Create a mock client for testing (without actual Proxmox connection)
        class MockClient:
            pass

        mock_client = MockClient()
        notes_mgr = NotesManager(mock_client)

        # Test HTML detection
        html_content = "<div><h3>Test</h3><p>Content</p></div>"
        format_html = notes_mgr.detect_format(html_content)
        assert format_html == "html", f"Expected 'html', got '{format_html}'"
        print(f"✅ HTML detection: {format_html}")

        # Test Markdown detection
        md_content = "# Header\n**Bold** text\n- List item"
        format_md = notes_mgr.detect_format(md_content)
        assert format_md == "markdown", f"Expected 'markdown', got '{format_md}'"
        print(f"✅ Markdown detection: {format_md}")

        # Test Plain text detection
        plain_content = "Just plain text"
        format_plain = notes_mgr.detect_format(plain_content)
        assert format_plain == "plain", f"Expected 'plain', got '{format_plain}'"
        print(f"✅ Plain text detection: {format_plain}")

        # Test 4: Test secret reference extraction
        print("\n4️⃣ Testing Secret Reference Extraction...")
        content_with_secrets = """
        VM: Production Server
        Credentials: secret://vm-341-ssh-key
        API Key: secret://api/production-key
        """
        secrets = notes_mgr.extract_secret_references(content_with_secrets)
        assert len(secrets) == 2, f"Expected 2 secrets, got {len(secrets)}"
        assert "vm-341-ssh-key" in secrets
        assert "api/production-key" in secrets
        print(f"✅ Extracted {len(secrets)} secret references: {secrets}")

        # Test 5: Test content validation
        print("\n5️⃣ Testing Content Validation...")

        # Safe content
        safe_content = "VM: web-server\nCredentials: secret://vm-key"
        is_valid, warnings = notes_mgr.validate_content(safe_content)
        assert is_valid, "Safe content should be valid"
        print(f"✅ Safe content validated: {len(warnings)} warnings")

        # Unsafe content
        unsafe_content = "password=mySecretPass123"
        is_valid, warnings = notes_mgr.validate_content(unsafe_content)
        assert not is_valid, "Unsafe content should be invalid"
        assert len(warnings) > 0, "Should have warnings"
        print(f"✅ Unsafe content detected: {len(warnings)} warnings")
        print(f"   Warning: {warnings[0][:50]}...")

        # Test 6: Test template generation
        print("\n6️⃣ Testing Template Generation...")

        templates_to_test = [
            ("web-server", "html"),
            ("database", "html"),
            ("development", "markdown"),
            ("generic", "markdown"),
            ("minimal", "plain"),
        ]

        for template_type, format_type in templates_to_test:
            template = notes_mgr.generate_template(
                template_type,
                format_type,
                {"VM_NAME": "test-vm", "IP_ADDRESS": "192.168.1.100"},
            )
            assert len(template) > 0, f"Template {template_type} should not be empty"
            assert "test-vm" in template, "Template should contain VM_NAME"
            print(f"✅ Template '{template_type}-{format_type}': {len(template)} chars")

        # Test 7: Test markdown rendering
        print("\n7️⃣ Testing Markdown Rendering...")
        md_input = "# Header\n**Bold** text\n`code`"
        rendered = notes_mgr.render_markdown(md_input)
        assert len(rendered) > 0, "Rendered markdown should not be empty"
        print(f"✅ Markdown rendered: {len(rendered)} chars")

        # Test 8: Test format_notes_output
        print("\n8️⃣ Testing Notes Output Formatting...")
        test_content = "# Test VM\nCredentials: secret://test-key"
        output = notes_mgr.format_notes_output(test_content, "auto", True)

        assert "content" in output
        assert "format" in output
        assert "secret_references" in output
        assert output["format"] == "markdown"
        assert len(output["secret_references"]) == 1
        print("✅ Output formatted correctly")
        print(f"   Format: {output['format']}")
        print(f"   Secrets: {output['secret_references']}")
        print(f"   Length: {output['length']} chars")

        # Summary
        print("\n" + "=" * 70)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 70)
        print("\n📊 Test Summary:")
        print("   ✅ Module imports: PASS")
        print("   ✅ Format detection: PASS (HTML, Markdown, Plain)")
        print("   ✅ Secret extraction: PASS")
        print("   ✅ Content validation: PASS")
        print("   ✅ Template generation: PASS (5 templates)")
        print("   ✅ Markdown rendering: PASS")
        print("   ✅ Output formatting: PASS")
        print("\n🎯 Feature Status: FULLY FUNCTIONAL ✅")

        return 0

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(test_notes_feature())
    sys.exit(exit_code)
