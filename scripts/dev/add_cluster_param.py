#!/usr/bin/env python3
"""
Script to add 'cluster' parameter to all proxmox-* tool functions in server.py
"""

import re


def add_cluster_param_to_tools(content: str) -> str:
    """Add cluster parameter to all proxmox tool functions."""

    # Pattern to match tool function definitions
    # Matches: async def proxmox_xxx(...) -> ...
    pattern = r"(async def (proxmox_[a-z_]+)\((.*?)\) -> ([^\n]+):\n)"

    def replace_func(match):
        full_match = match.group(0)
        func_name = match.group(2)
        params = match.group(3)
        return_type = match.group(4)

        # Skip if already has cluster parameter
        if "cluster:" in params or "cluster =" in params:
            return full_match

        # Add cluster parameter
        if params.strip():
            # Has other parameters
            new_params = params + ", cluster: Optional[str] = None"
        else:
            # No parameters
            new_params = "cluster: Optional[str] = None"

        return f"async def {func_name}({new_params}) -> {return_type}:\n"

    # Apply replacements
    content = re.sub(pattern, replace_func, content, flags=re.MULTILINE)

    # Now update get_client() calls to pass cluster parameter
    # Pattern: client = get_client()
    content = re.sub(
        r"(\s+)client = get_client\(\)", r"\1client = get_client(cluster)", content
    )

    return content


def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: python scripts/dev/add_cluster_param.py <server.py>")
        sys.exit(1)

    file_path = sys.argv[1]

    # Read file
    with open(file_path, "r") as f:
        content = f.read()

    # Process
    new_content = add_cluster_param_to_tools(content)

    # Write back
    with open(file_path, "w") as f:
        f.write(new_content)

    print(f"✅ Updated {file_path}")
    print("   - Added 'cluster' parameter to all proxmox-* tools")
    print("   - Updated get_client() calls to pass cluster")


if __name__ == "__main__":
    main()
