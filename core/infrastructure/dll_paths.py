"""
Shared DLL path resolution for .NET assemblies.

Centralizes the repeated root_dir/dll_folder/dll_path logic
that was duplicated across 13+ files.
"""

import os
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)

# Project root: go up from core/infrastructure/ to project root
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.dirname(_THIS_DIR)
PROJECT_ROOT = os.path.dirname(_CORE_DIR)
DLL_FOLDER = os.path.join(PROJECT_ROOT, "lib", "dotnet")


class DllPaths(NamedTuple):
    """Paths to all .NET assemblies used by the server."""
    dll_folder: str
    core_dll: str
    amo_dll: str
    tabular_dll: str
    adomd_dll: str


def get_dll_paths() -> DllPaths:
    """Get resolved paths to all .NET DLLs."""
    return DllPaths(
        dll_folder=DLL_FOLDER,
        core_dll=os.path.join(DLL_FOLDER, "Microsoft.AnalysisServices.Core.dll"),
        amo_dll=os.path.join(DLL_FOLDER, "Microsoft.AnalysisServices.dll"),
        tabular_dll=os.path.join(DLL_FOLDER, "Microsoft.AnalysisServices.Tabular.dll"),
        adomd_dll=os.path.join(DLL_FOLDER, "Microsoft.AnalysisServices.AdomdClient.dll"),
    )


def load_amo_assemblies():
    """Load AMO/TOM assemblies into CLR. Returns True if successful."""
    try:
        import clr
        paths = get_dll_paths()
        if os.path.exists(paths.core_dll):
            clr.AddReference(paths.core_dll)
        if os.path.exists(paths.amo_dll):
            clr.AddReference(paths.amo_dll)
        if os.path.exists(paths.tabular_dll):
            clr.AddReference(paths.tabular_dll)
        return True
    except Exception as e:
        logger.warning(f"AMO/TOM assemblies not available: {e}")
        return False


def load_adomd_assembly():
    """Load ADOMD.NET assembly into CLR. Returns True if successful."""
    try:
        import clr
        paths = get_dll_paths()
        if os.path.exists(paths.adomd_dll):
            clr.AddReference(paths.adomd_dll)
            return True
        return False
    except Exception as e:
        logger.warning(f"ADOMD.NET assembly not available: {e}")
        return False
