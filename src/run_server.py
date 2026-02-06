#!/usr/bin/env python3
"""
Wrapper script to run MCP-PowerBi-Finvision server with correct PYTHONPATH.
This ensures bundled dependencies in venv/Lib/site-packages are found.
"""
import sys
import site
import importlib.util
from pathlib import Path

# Get the repository root (parent of src/ where this script is located)
script_dir = Path(__file__).parent.parent.absolute()

# Add bundled dependencies to Python path using site.addsitedir
# This properly handles .pth files and native extensions (.pyd files)
# Support both Windows and Unix venv layouts
site_packages_win = script_dir / "venv" / "Lib" / "site-packages"
site_packages_unix = script_dir / "venv" / "lib"

if site_packages_win.exists():
    site.addsitedir(str(site_packages_win))
elif site_packages_unix.exists():
    for child in site_packages_unix.iterdir():
        sp = child / "site-packages"
        if sp.exists():
            site.addsitedir(str(sp))
            break

# Add parent directory to path so imports work
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

# Import and run the server module using importlib (safe alternative to exec())
server_module_path = script_dir / "src" / "pbixray_server_enhanced.py"

if not server_module_path.exists():
    print(f"ERROR: Server module not found: {server_module_path}", file=sys.stderr)
    sys.exit(1)

spec = importlib.util.spec_from_file_location("pbixray_server_enhanced", str(server_module_path))
module = importlib.util.module_from_spec(spec)
sys.modules["pbixray_server_enhanced"] = module
spec.loader.exec_module(module)
