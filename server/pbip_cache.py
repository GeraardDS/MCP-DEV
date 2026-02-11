"""
Shared PBIP model cache.
Thread-safe LRU cache for parsed PBIP models and dependencies.
Used by pbip_operations_handler and hybrid_analysis_handler.
"""

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PbipProject:
    """Typed wrapper for a parsed PBIP project.

    Provides attribute access instead of dict bracket notation.
    Returned by PbipModelCache.get_or_parse().
    """
    project_info: Dict[str, Any]
    model_data: Dict[str, Any]
    typed_model: Any  # TmdlModel from core.tmdl.models
    report_data: Optional[Dict[str, Any]]
    dependencies: Dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        """Dict-style access for backward compatibility."""
        return getattr(self, key)


class PbipModelCache:
    """Thread-safe cache for parsed PBIP models and dependencies."""

    def __init__(self, max_entries: int = 3):
        self._lock = threading.RLock()
        self._cache: Dict[str, PbipProject] = {}
        self._max_entries = max_entries

    def get_or_parse(self, pbip_path: str) -> PbipProject:
        """Get cached project or parse fresh."""
        resolved = str(Path(pbip_path).resolve())
        max_mtime = self._get_max_mtime(resolved)
        cache_key = f"{resolved}|{max_mtime}"

        with self._lock:
            if cache_key in self._cache:
                logger.debug(f"Cache hit for {resolved}")
                return self._cache[cache_key]

        # Parse outside the lock
        result = self._parse_pbip(resolved)

        with self._lock:
            # Evict old entries if at capacity
            if len(self._cache) >= self._max_entries:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[cache_key] = result

        return result

    def invalidate(self, pbip_path: str) -> None:
        """Remove a model from cache."""
        resolved = str(Path(pbip_path).resolve())
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(resolved)]
            for k in keys_to_remove:
                del self._cache[k]

    @staticmethod
    def _get_max_mtime(path: str) -> float:
        """Get the most recent modification time across all TMDL files."""
        p = Path(path)
        max_t = 0.0
        for f in p.rglob("*.tmdl"):
            try:
                t = f.stat().st_mtime
                if t > max_t:
                    max_t = t
            except OSError:
                pass
        return max_t

    @staticmethod
    def _parse_pbip(resolved_path: str) -> PbipProject:
        """Parse a PBIP project into a PbipProject."""
        from core.pbip.pbip_project_scanner import PbipProjectScanner
        from core.pbip.pbip_model_analyzer import TmdlModelAnalyzer
        from core.pbip.pbip_dependency_engine import PbipDependencyEngine

        scanner = PbipProjectScanner()
        project_info = scanner.scan_repository(resolved_path)

        if not project_info or not project_info.get("semantic_models"):
            raise ValueError(f"No PBIP semantic models found in: {resolved_path}")

        model_folder = project_info["semantic_models"][0].get("model_folder")
        if not model_folder:
            raise ValueError("Semantic model folder path not found")

        analyzer = TmdlModelAnalyzer()
        typed_model = analyzer.analyze_model_typed(model_folder)
        model_data = typed_model.to_dict()
        model_data["model_folder"] = model_folder

        # Parse report if available
        report_data = None
        reports = project_info.get("reports", [])
        if reports:
            report_folder = reports[0].get("report_folder")
            if report_folder:
                try:
                    from core.pbip.pbip_report_analyzer import PbirReportAnalyzer
                    report_data = PbirReportAnalyzer().analyze_report(report_folder)
                except Exception as e:
                    logger.warning(f"Failed to parse report: {e}")

        # Build dependencies
        dep_engine = PbipDependencyEngine(model_data, report_data)
        dependencies = dep_engine.analyze_all_dependencies()

        return PbipProject(
            project_info=project_info,
            model_data=model_data,
            typed_model=typed_model,
            report_data=report_data,
            dependencies=dependencies,
        )


def normalize_pbip_path(raw_path: str) -> str:
    """Normalize PBIP path (handle WSL/Unix paths on Windows)."""
    normalized = raw_path
    wsl_match = re.match(r"^/mnt/([a-z])/(.*)", raw_path, re.IGNORECASE)
    if wsl_match:
        drive = wsl_match.group(1).upper()
        rest = wsl_match.group(2).replace("/", "\\")
        normalized = f"{drive}:\\{rest}"
    elif raw_path.startswith("/"):
        normalized = raw_path.replace("/", "\\")

    p = Path(normalized)
    if p.is_file() and p.suffix == ".pbip":
        return str(p.parent.resolve())

    # Auto-fix: if path points to a .Report folder, resolve to .SemanticModel or parent
    resolved = p.resolve()
    if resolved.is_dir() and resolved.name.endswith('.Report'):
        sm_sibling = resolved.parent / resolved.name.replace('.Report', '.SemanticModel')
        if sm_sibling.is_dir():
            return str(sm_sibling)
        return str(resolved.parent)

    return str(resolved)


# Global shared cache instance
pbip_cache = PbipModelCache()
