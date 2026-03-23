"""Notes management module for Proxmox VM/LXC description fields."""

from __future__ import annotations

import re
import html
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from .client import ProxmoxClient


class NotesManager:
    """Manager for VM/LXC notes with format support and validation."""

    # Regex patterns
    SECRET_REFERENCE_PATTERN = r"secret://([a-zA-Z0-9_\-/]+)"
    PASSWORD_PATTERNS = [
        r'password\s*[=:]\s*["\']?([^"\'\s]+)',
        r'passwd\s*[=:]\s*["\']?([^"\'\s]+)',
        r'pwd\s*[=:]\s*["\']?([^"\'\s]+)',
        r'api[_-]?key\s*[=:]\s*["\']?([^"\'\s]+)',
        r'token\s*[=:]\s*["\']?([^"\'\s]+)',
        r'secret\s*[=:]\s*["\']?([^"\'\s]+)(?!://)',  # Exclude secret:// references
    ]

    # Note templates
    TEMPLATES = {
        "web-server-html": """<div style="font-family: monospace; padding: 10px;">
  <h3>🌐 {VM_NAME}</h3>
  <p><strong>Type:</strong> Web Server</p>
  <p><strong>Owner:</strong> {OWNER}</p>
  <p><strong>Purpose:</strong> {PURPOSE}</p>
  <p><strong>OS:</strong> {OS}</p>
  <p><strong>IP Address:</strong> {IP_ADDRESS}</p>
  <p><strong>Credentials:</strong> <code>secret://{SECRET_ID}</code></p>
  <p><strong>Last Updated:</strong> {DATE}</p>
  <hr>
  <h4>Services</h4>
  <ul>
    <li>Nginx - Port 80/443</li>
    <li>PHP-FPM - Port 9000</li>
  </ul>
  <h4>Maintenance</h4>
  <ul>
    <li>Updates: Weekly on Sunday 2 AM UTC</li>
    <li>Backup: Daily at midnight</li>
  </ul>
</div>""",
        "database-html": """<div style="font-family: monospace; padding: 10px;">
  <h3>🗄️ {VM_NAME}</h3>
  <p><strong>Type:</strong> Database Server</p>
  <p><strong>Owner:</strong> {OWNER}</p>
  <p><strong>Purpose:</strong> {PURPOSE}</p>
  <p><strong>Database:</strong> {DATABASE_TYPE}</p>
  <p><strong>IP Address:</strong> {IP_ADDRESS}</p>
  <p><strong>Port:</strong> {PORT}</p>
  <p><strong>Credentials:</strong> <code>secret://{SECRET_ID}</code></p>
  <p><strong>Last Updated:</strong> {DATE}</p>
  <hr>
  <h4>Configuration</h4>
  <ul>
    <li>Max Connections: 100</li>
    <li>Buffer Pool: 2GB</li>
  </ul>
  <h4>Backup Schedule</h4>
  <ul>
    <li>Full Backup: Daily at 1 AM UTC</li>
    <li>Incremental: Every 6 hours</li>
  </ul>
</div>""",
        "development-markdown": """# 💻 {VM_NAME}

**Type:** Development Environment  
**Owner:** {OWNER}  
**Purpose:** {PURPOSE}  
**OS:** {OS}  
**IP Address:** {IP_ADDRESS}  
**Credentials:** `secret://{SECRET_ID}`  
**Last Updated:** {DATE}

## Installed Tools
- Git
- Docker
- Node.js v18
- Python 3.11
- VS Code Server

## Access
```bash
ssh developer@{IP_ADDRESS}
```

## Notes
{NOTES}

## Maintenance
- Updates: As needed
- Backup: Weekly on Friday
""",
        "generic-markdown": """# {VM_NAME}

**Owner:** {OWNER}  
**Purpose:** {PURPOSE}  
**OS:** {OS}  
**IP Address:** {IP_ADDRESS}  
**Credentials:** `secret://{SECRET_ID}`  
**Created:** {DATE}

## Description
{DESCRIPTION}

## Configuration
{CONFIGURATION}

## Notes
{NOTES}
""",
        "minimal-plain": """{VM_NAME}
Owner: {OWNER}
Purpose: {PURPOSE}
IP: {IP_ADDRESS}
Credentials: secret://{SECRET_ID}
Updated: {DATE}
""",
    }

    def __init__(self, proxmox_client: ProxmoxClient):
        """Initialize NotesManager with Proxmox client."""
        self.client = proxmox_client

    def detect_format(self, content: str) -> str:
        """
        Detect notes format (html, markdown, plain).

        Args:
            content: Notes content to analyze

        Returns:
            Format type: 'html', 'markdown', or 'plain'
        """
        if not content or not content.strip():
            return "plain"

        # Check for HTML tags
        html_pattern = r"<[a-z][\s\S]*>"
        if re.search(html_pattern, content, re.IGNORECASE):
            return "html"

        # Check for Markdown syntax
        markdown_patterns = [
            r"^#{1,6}\s",  # Headers
            r"\*\*[^*]+\*\*",  # Bold
            r"\*[^*]+\*",  # Italic
            r"^\s*[-*+]\s",  # Lists
            r"^\s*\d+\.\s",  # Numbered lists
            r"\[.+\]\(.+\)",  # Links
            r"`[^`]+`",  # Code
        ]

        for pattern in markdown_patterns:
            if re.search(pattern, content, re.MULTILINE):
                return "markdown"

        return "plain"

    def validate_content(self, content: str) -> Tuple[bool, List[str]]:
        """
        Validate content and return warnings.

        Args:
            content: Notes content to validate

        Returns:
            Tuple of (is_valid, warnings_list)
        """
        warnings = []

        if not content:
            return True, warnings

        # Check for potential secrets in plain text
        for pattern in self.PASSWORD_PATTERNS:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                # Skip if it's a secret reference
                if "secret://" in match.group(0):
                    continue
                warnings.append(
                    f"⚠️  Potential secret detected: '{match.group(0)[:20]}...'. "
                    "Consider using an external secret manager and storing only a reference."
                )

        # Check size (Proxmox typically limits to 64KB)
        max_size = 64 * 1024  # 64KB
        if len(content.encode("utf-8")) > max_size:
            warnings.append(
                f"⚠️  Content size ({len(content.encode('utf-8'))} bytes) exceeds "
                f"recommended limit ({max_size} bytes). May be truncated by Proxmox."
            )

        # Validate HTML if detected
        if self.detect_format(content) == "html":
            # Basic HTML validation - check for unclosed tags
            open_tags = re.findall(r"<([a-z][a-z0-9]*)[^>]*>", content, re.IGNORECASE)
            close_tags = re.findall(r"</([a-z][a-z0-9]*)>", content, re.IGNORECASE)

            # Simple check - not comprehensive but catches obvious issues
            if len(open_tags) != len(close_tags):
                warnings.append("⚠️  HTML may have unclosed tags. Please verify syntax.")

        is_valid = len([w for w in warnings if "secret detected" in w]) == 0

        return is_valid, warnings

    def extract_secret_references(self, content: str) -> List[str]:
        """
        Extract secret:// references from content.

        Args:
            content: Notes content to parse

        Returns:
            List of secret reference IDs
        """
        if not content:
            return []

        matches = re.findall(self.SECRET_REFERENCE_PATTERN, content)
        return list(set(matches))  # Remove duplicates

    def generate_template(
        self,
        template_type: str,
        format_type: str,
        variables: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Generate notes template.

        Args:
            template_type: Type of template (web-server, database, development, generic, minimal)
            format_type: Output format (html, markdown, plain)
            variables: Dictionary of variables to replace in template

        Returns:
            Generated template content
        """
        # Map template type and format to template key
        template_key = f"{template_type}-{format_type}"

        # Fallback to generic if specific template not found
        if template_key not in self.TEMPLATES:
            if format_type == "html":
                template_key = "generic-markdown"  # Will convert
            elif format_type == "markdown":
                template_key = "generic-markdown"
            else:
                template_key = "minimal-plain"

        template = self.TEMPLATES.get(template_key, self.TEMPLATES["minimal-plain"])

        # Default variables
        default_vars = {
            "VM_NAME": "My VM",
            "OWNER": "Admin",
            "PURPOSE": "General Purpose",
            "OS": "Ubuntu 22.04",
            "IP_ADDRESS": "192.168.1.100",
            "SECRET_ID": "vm-secret-key",
            "DATE": datetime.now().strftime("%Y-%m-%d"),
            "DATABASE_TYPE": "PostgreSQL 15",
            "PORT": "5432",
            "DESCRIPTION": "Add description here",
            "CONFIGURATION": "Add configuration details here",
            "NOTES": "Add additional notes here",
        }

        # Merge with provided variables
        if variables:
            default_vars.update(variables)

        # Replace variables in template
        result = template
        for key, value in default_vars.items():
            result = result.replace(f"{{{key}}}", str(value))

        return result

    def render_markdown(self, content: str) -> str:
        """
        Render markdown to formatted text (simple conversion).

        Args:
            content: Markdown content

        Returns:
            Formatted text representation
        """
        # Simple markdown to text conversion
        # Headers
        result = re.sub(
            r"^#{1,6}\s+(.+)$", r"\n\1\n" + "=" * 50, content, flags=re.MULTILINE
        )

        # Bold
        result = re.sub(r"\*\*(.+?)\*\*", r"\1", result)

        # Italic
        result = re.sub(r"\*(.+?)\*", r"\1", result)

        # Code
        result = re.sub(r"`(.+?)`", r"[\1]", result)

        # Links
        result = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1 (\2)", result)

        return result

    def format_notes_output(
        self, content: str, format_type: str = "auto", parse_secrets: bool = True
    ) -> Dict[str, Any]:
        """
        Format notes for output with metadata.

        Args:
            content: Notes content
            format_type: Desired output format
            parse_secrets: Whether to extract secret references

        Returns:
            Dictionary with formatted content and metadata
        """
        detected_format = self.detect_format(content)

        if format_type == "auto":
            format_type = detected_format

        result = {
            "content": content,
            "format": detected_format,
            "length": len(content),
            "lines": content.count("\n") + 1 if content else 0,
        }

        if parse_secrets:
            secret_refs = self.extract_secret_references(content)
            result["secret_references"] = secret_refs
            result["has_secrets"] = len(secret_refs) > 0

        # Add rendered version if markdown
        if detected_format == "markdown" and format_type != "plain":
            result["rendered"] = self.render_markdown(content)

        return result
