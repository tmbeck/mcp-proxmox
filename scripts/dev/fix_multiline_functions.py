#!/usr/bin/env python3
"""
Fix multi-line function signatures to add cluster parameter.
"""

import re


def fix_file(content: str) -> str:
    """Fix all multi-line function signatures."""

    # Find all function signatures that span multiple lines
    # Pattern: async def proxmox_xxx(\n    params...\n) -> ReturnType:

    pattern = r"(@server\.tool\([^)]+\)\n)(async def (proxmox_[a-z_]+)\(([^)]*(?:\n[^)]*)*)\) -> ([^\n]+):\n)"

    def replace_func(match):
        decorator = match.group(1)
        full_sig = match.group(0)
        func_name = match.group(3)
        params = match.group(4)
        return_type = match.group(5)

        # Skip if already has cluster parameter
        if "cluster:" in params or "cluster =" in params:
            return full_sig

        # Add cluster parameter before the closing paren
        # Find last parameter
        if params.strip():
            # Add cluster parameter
            new_params = params + ",\n    cluster: Optional[str] = None"
        else:
            new_params = "cluster: Optional[str] = None"

        return f"{decorator}async def {func_name}({new_params}) -> {return_type}:\n"

    content = re.sub(pattern, replace_func, content, flags=re.MULTILINE)

    return content


def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: python scripts/dev/fix_multiline_functions.py <server.py>")
        sys.exit(1)

    file_path = sys.argv[1]

    # Read file
    with open(file_path, "r") as f:
        content = f.read()

    # Process
    new_content = fix_file(content)

    # Write back
    with open(file_path, "w") as f:
        f.write(new_content)

    print(f"✅ Fixed {file_path}")


if __name__ == "__main__":
    main()
