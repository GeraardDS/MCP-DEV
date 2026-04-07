"""
Shared PBIP model cache.
Thread-safe LRU cache for parsed PBIP models and dependencies.
Used by pbip_operations_handler and hybrid_analysis_handler.
"""

import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

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
            # Double-check: another thread may have parsed while we were outside the lock
            if cache_key in self._cache:
                return self._cache[cache_key]
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
        """Get the most recent modification time across TMDL and report JSON files."""
        p = Path(path)
        max_t = 0.0
        for pattern in ("*.tmdl", "*.json"):
            for f in p.rglob(pattern):
                try:
                    t = f.stat().st_mtime
                    if t > max_t:
                        max_t = t
                except OSError:
                    pass
        return max_t

    @staticmethod
    def _parse_pbip(resolved_path: str) -> PbipProject:
        """Parse a PBIP project into a PbipProject.

        Parses ALL reports in the project and merges them into a single
        combined report_data and dependencies result. Pages from each
        report are prefixed with the report name for disambiguation.
        Unused columns/measures are intersected across all reports.
        """
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

        # Parse ALL reports
        reports = project_info.get("reports", [])
        parsed_reports: List[Dict[str, Any]] = []
        for report_info in reports:
            report_folder = report_info.get("report_folder")
            if report_folder:
                try:
                    from core.pbip.pbip_report_analyzer import PbirReportAnalyzer
                    rd = PbirReportAnalyzer().analyze_report(report_folder)
                    rd["_report_name"] = os.path.basename(report_folder)
                    parsed_reports.append(rd)
                except Exception as e:
                    logger.warning(f"Failed to parse report {report_folder}: {e}")

        # Merge reports and build dependencies
        if not parsed_reports:
            # No reports — model-only analysis
            dep_engine = PbipDependencyEngine(model_data, None)
            dependencies = dep_engine.analyze_all_dependencies()
            return PbipProject(
                project_info=project_info,
                model_data=model_data,
                typed_model=typed_model,
                report_data=None,
                dependencies=dependencies,
            )

        if len(parsed_reports) == 1:
            # Single report — original behavior, no prefixing needed
            report_data = parsed_reports[0]
            dep_engine = PbipDependencyEngine(model_data, report_data)
            dependencies = dep_engine.analyze_all_dependencies()
        else:
            # Multi-report: run per-report analysis, then merge
            report_data, dependencies = _merge_multi_report(
                model_data, parsed_reports
            )

        return PbipProject(
            project_info=project_info,
            model_data=model_data,
            typed_model=typed_model,
            report_data=report_data,
            dependencies=dependencies,
        )


def _merge_multi_report(
    model_data: Dict[str, Any],
    parsed_reports: List[Dict[str, Any]],
) -> tuple:
    """
    Merge multiple parsed reports into combined report_data and dependencies.

    Strategy:
    - Pages from each report are prefixed with report name for disambiguation
    - Report-level filters are merged from all reports
    - PbipDependencyEngine runs per-report; unused lists are intersected
    - Visual/page dependencies are merged from all per-report runs

    Args:
        model_data: Shared semantic model data
        parsed_reports: List of parsed report dicts (each from PbirReportAnalyzer)

    Returns:
        Tuple of (merged_report_data, merged_dependencies)
    """
    from core.pbip.pbip_dependency_engine import PbipDependencyEngine

    # Build merged report_data with pages from all reports
    merged_pages: List[Dict[str, Any]] = []
    merged_report_filters: List[Dict[str, Any]] = []
    report_names: List[str] = []

    for rd in parsed_reports:
        report_name = rd.get("_report_name", "")
        report_names.append(report_name)

        # Prefix each page's display_name with report name
        for page in rd.get("pages", []):
            prefixed_page = dict(page)
            original_name = page.get("display_name", page.get("id", ""))
            prefixed_page["display_name"] = f"[{report_name}] {original_name}"
            merged_pages.append(prefixed_page)

        # Collect report-level filters
        report_info = rd.get("report", {})
        for filt in report_info.get("filters", []):
            merged_report_filters.append(filt)

    merged_report_data: Dict[str, Any] = {
        "report": {
            "name": ", ".join(report_names),
            "filters": merged_report_filters,
        },
        "pages": merged_pages,
        "bookmarks": [],
        "_report_names": report_names,
    }

    # Run dependency engine per report and collect results
    all_unused_cols: List[set] = []
    all_unused_measures: List[set] = []
    merged_deps: Dict[str, Any] = {}

    for rd in parsed_reports:
        engine = PbipDependencyEngine(model_data, rd)
        deps = engine.analyze_all_dependencies()

        all_unused_cols.append(set(deps.get("unused_columns", [])))
        all_unused_measures.append(set(deps.get("unused_measures", [])))

        # Merge additive dependency maps
        if not merged_deps:
            merged_deps = deps
        else:
            report_name = rd.get("_report_name", "")

            # Merge visual_dependencies (prefix keys with report name)
            for vk, vv in deps.get("visual_dependencies", {}).items():
                merged_deps.setdefault("visual_dependencies", {})[
                    f"[{report_name}] {vk}"
                ] = vv

            # Merge page_dependencies (prefix keys with report name)
            for pk, pv in deps.get("page_dependencies", {}).items():
                merged_deps.setdefault("page_dependencies", {})[
                    f"[{report_name}] {pk}"
                ] = pv

            # Merge filter_pane_data
            _merge_filter_pane(
                merged_deps.setdefault("filter_pane_data", {}),
                deps.get("filter_pane_data", {}),
                report_name,
            )

            # Merge column_to_measure (union of measure lists per column)
            for ck, measures in deps.get("column_to_measure", {}).items():
                existing = merged_deps.setdefault("column_to_measure", {})
                if ck not in existing:
                    existing[ck] = []
                for m in measures:
                    if m not in existing[ck]:
                        existing[ck].append(m)

    # Intersect unused: only unused if unused in ALL report analyses
    if all_unused_cols:
        merged_deps["unused_columns"] = sorted(
            all_unused_cols[0].intersection(*all_unused_cols[1:])
        )
    if all_unused_measures:
        merged_deps["unused_measures"] = sorted(
            all_unused_measures[0].intersection(*all_unused_measures[1:])
        )

    # Update summary counts
    summary = merged_deps.get("summary", {})
    summary["unused_columns"] = len(merged_deps.get("unused_columns", []))
    summary["unused_measures"] = len(merged_deps.get("unused_measures", []))
    summary["total_pages"] = len(merged_pages)
    summary["total_visuals"] = sum(
        len(p.get("visuals", [])) for p in merged_pages
    )
    summary["reports_analyzed"] = report_names
    merged_deps["summary"] = summary

    return merged_report_data, merged_deps


def _merge_filter_pane(
    target: Dict[str, Any],
    source: Dict[str, Any],
    report_name: str,
) -> None:
    """Merge filter pane data from a source report into target, prefixing keys."""
    # Report filters — append
    target.setdefault("report_filters", []).extend(
        source.get("report_filters", [])
    )

    # Page filters — prefix page keys
    for pk, pv in source.get("page_filters", {}).items():
        target.setdefault("page_filters", {})[f"[{report_name}] {pk}"] = pv

    # Visual filters — prefix visual keys
    for vk, vv in source.get("visual_filters", {}).items():
        target.setdefault("visual_filters", {})[f"[{report_name}] {vk}"] = vv

    # Summary — add counts
    src_summary = source.get("summary", {})
    tgt_summary = target.setdefault("summary", {
        "total_report_filters": 0,
        "total_page_filters": 0,
        "total_visual_filters": 0,
        "pages_with_filters": 0,
        "visuals_with_filters": 0,
    })
    for key in tgt_summary:
        tgt_summary[key] = tgt_summary.get(key, 0) + src_summary.get(key, 0)


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
