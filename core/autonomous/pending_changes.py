"""
Pending Changes Detector

Decides which save path the lifecycle manager should take:

- "live_tom_changes": there are uncommitted in-memory model changes that
  PBIDesktop has not yet written to disk. We need either UI Ctrl+S or a
  TOM SaveChanges() before close.
- "file_only_changes": the underlying PBIP files were modified externally
  (e.g. by 07_Visual_Operations write_through). PBIDesktop's view is stale;
  no save needed but we DO need to reopen for the UI to see new content.
- "no_changes": nothing pending. Close is safe.

Detection sources:
- TOM Model.HasLocalChanges (when AMO is available and connected).
- File mtimes on the .pbix or PBIP folder, compared to the connection's
  recorded "last seen" timestamp.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PendingChangesResult:
    """Structured result of a pending-changes check."""

    has_live_tom_changes: bool = False
    has_file_changes: bool = False
    file_type: Optional[str] = None  # 'pbix' | 'pbip' | None
    file_full_path: Optional[str] = None
    pbip_folder_path: Optional[str] = None
    newest_file_mtime: float = 0.0
    seen_at: float = 0.0
    changed_files: List[str] = field(default_factory=list)
    detection_errors: List[str] = field(default_factory=list)

    @property
    def category(self) -> str:
        if self.has_live_tom_changes:
            return "live_tom_changes"
        if self.has_file_changes:
            return "file_only_changes"
        return "no_changes"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "has_live_tom_changes": self.has_live_tom_changes,
            "has_file_changes": self.has_file_changes,
            "file_type": self.file_type,
            "file_full_path": self.file_full_path,
            "pbip_folder_path": self.pbip_folder_path,
            "newest_file_mtime": self.newest_file_mtime,
            "seen_at": self.seen_at,
            "changed_files": self.changed_files[:50],
            "detection_errors": self.detection_errors,
        }


class PendingChangesDetector:
    """
    Inspect TOM and the file system to figure out what needs saving / reloading.

    Stateful: remembers the newest file mtime it has seen so subsequent calls
    can detect newly-modified files. Call mark_seen() after a successful
    save/reload to reset the baseline.
    """

    # Files inside a PBIP folder that meaningfully signal user changes.
    PBIP_FILE_PATTERNS = (
        ".tmdl",
        ".bim",
        ".json",
        ".pbir",
        ".tmd",
    )

    def __init__(self, connection_state) -> None:  # type: ignore[no-untyped-def]
        self._connection_state = connection_state
        self._baseline_mtime: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def detect(self) -> PendingChangesResult:
        """Run all available checks and return a structured result."""
        info = self._pbip_info()
        result = PendingChangesResult(
            file_type=info.get("file_type"),
            file_full_path=info.get("file_full_path"),
            pbip_folder_path=info.get("pbip_folder_path"),
            seen_at=time.time(),
        )

        # 1. TOM live-changes check (best-effort)
        try:
            result.has_live_tom_changes = self._check_tom_local_changes(result)
        except Exception as e:  # noqa: BLE001
            result.detection_errors.append(f"tom_check_failed: {e}")

        # 2. File mtime check
        try:
            self._check_file_changes(result)
        except Exception as e:  # noqa: BLE001
            result.detection_errors.append(f"file_check_failed: {e}")

        return result

    def mark_seen(self) -> None:
        """
        Reset the file baseline to "now". Call after a successful save or
        reopen so subsequent detect() calls only flag *future* changes.
        """
        info = self._pbip_info()
        path = info.get("pbip_folder_path") or info.get("file_full_path")
        if not path:
            return
        try:
            self._baseline_mtime[path] = self._max_mtime(path)
        except Exception as e:  # noqa: BLE001
            logger.debug("mark_seen failed for %s: %s", path, e)

    # ------------------------------------------------------------------
    # Internal: TOM
    # ------------------------------------------------------------------
    def _check_tom_local_changes(self, result: PendingChangesResult) -> bool:
        """
        Query the TOM Model for HasLocalChanges. Returns False if we can't
        introspect (not connected, AMO not loaded) — we assume "no live
        changes" in that case to avoid blocking on a check we can't perform.
        """
        cs = self._connection_state
        cm = getattr(cs, "connection_manager", None)
        if not cm or not cm.is_connected():
            return False

        # Try the lazy AMO Server.Databases path used elsewhere in the codebase.
        try:
            from core.infrastructure.dll_paths import load_amo_assemblies

            if not load_amo_assemblies():
                return False
            from Microsoft.AnalysisServices.Tabular import Server  # type: ignore
        except Exception as e:  # noqa: BLE001
            result.detection_errors.append(f"amo_load_failed: {e}")
            return False

        server = None
        try:
            conn_str = cm.connection_string
            if not conn_str:
                return False
            server = Server()
            server.Connect(conn_str)
            if server.Databases.Count == 0:
                return False
            db = server.Databases[0]
            model = db.Model
            if model is None:
                return False
            # Property may be unavailable on older AS versions
            return bool(getattr(model, "HasLocalChanges", False))
        except Exception as e:  # noqa: BLE001
            result.detection_errors.append(f"tom_query_failed: {e}")
            return False
        finally:
            try:
                if server is not None:
                    server.Disconnect()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal: filesystem
    # ------------------------------------------------------------------
    def _check_file_changes(self, result: PendingChangesResult) -> None:
        path = result.pbip_folder_path or result.file_full_path
        if not path:
            return

        newest, changed = self._collect_mtimes(path)
        result.newest_file_mtime = newest
        baseline = self._baseline_mtime.get(path)

        # First-ever observation: record but don't flag
        if baseline is None:
            self._baseline_mtime[path] = newest
            return

        if newest > baseline:
            result.has_file_changes = True
            result.changed_files = [f for f, mt in changed if mt > baseline][:50]

    def _max_mtime(self, path: str) -> float:
        newest, _ = self._collect_mtimes(path)
        return newest

    def _collect_mtimes(self, path: str) -> tuple[float, list[tuple[str, float]]]:
        """
        For a PBIP folder: walk the tree, look at files matching PBIP_FILE_PATTERNS.
        For a single .pbix file: just that file's mtime.
        """
        if not os.path.exists(path):
            return 0.0, []

        if os.path.isfile(path):
            try:
                mt = os.path.getmtime(path)
                return mt, [(path, mt)]
            except OSError:
                return 0.0, []

        newest = 0.0
        per_file: List[tuple[str, float]] = []
        for root, _dirs, files in os.walk(path):
            # Skip git internals, caches, virtualenvs
            base = os.path.basename(root).lower()
            if base in {".git", "__pycache__", ".venv", "node_modules"}:
                continue
            for name in files:
                lname = name.lower()
                if not any(lname.endswith(ext) for ext in self.PBIP_FILE_PATTERNS):
                    continue
                fp = os.path.join(root, name)
                try:
                    mt = os.path.getmtime(fp)
                except OSError:
                    continue
                per_file.append((fp, mt))
                if mt > newest:
                    newest = mt
        return newest, per_file

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _pbip_info(self) -> Dict[str, Any]:
        """Return whatever PBIP/PBIX info connection_state currently knows."""
        cs = self._connection_state
        # connection_state has both pbip_info and connection_manager.active_instance
        try:
            info = cs.get_pbip_info() or {}
        except Exception:
            info = {}

        if not info.get("file_full_path"):
            try:
                cm = getattr(cs, "connection_manager", None)
                inst = cm.get_instance_info() if cm else None
                if inst:
                    info.setdefault("file_full_path", inst.get("file_full_path"))
                    info.setdefault("pbip_folder_path", inst.get("pbip_folder_path"))
                    info.setdefault("file_type", inst.get("file_type"))
            except Exception:
                pass
        return info
