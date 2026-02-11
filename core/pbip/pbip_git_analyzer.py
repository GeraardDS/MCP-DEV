"""
PBIP Git Analyzer - Semantic diff and change analysis for PBIP projects.

Analyzes git changes to TMDL files and produces business-readable
summaries of what changed (measures added/modified/removed, relationships
changed, etc.) rather than raw text diffs.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PbipGitAnalyzer:
    """Analyzes git changes to PBIP projects with semantic understanding."""

    def __init__(self, repo_path: str):
        """
        Initialize with a path inside a git repository.

        Args:
            repo_path: Path to PBIP project (must be inside a git repo)
        """
        self.repo_path = Path(repo_path).resolve()
        self.git_root = self._find_git_root()

    def _find_git_root(self) -> Path:
        """Find the git repository root."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, cwd=str(self.repo_path),
                timeout=10,
            )
            if result.returncode == 0:
                return Path(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        raise ValueError(f"Not a git repository: {self.repo_path}")

    def _run_git(self, args: List[str], **kwargs) -> str:
        """Run a git command and return stdout."""
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True,
            cwd=str(self.git_root),
            timeout=30,
            **kwargs,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
        return result.stdout

    def analyze_working_changes(self) -> Dict[str, Any]:
        """
        Analyze what TMDL objects changed since the last commit.

        Returns:
            Dictionary with categorized changes
        """
        # Get list of changed TMDL files (staged + unstaged)
        staged = self._run_git(["diff", "--cached", "--name-status"])
        unstaged = self._run_git(["diff", "--name-status"])
        untracked = self._run_git(["ls-files", "--others", "--exclude-standard"])

        changes = self._parse_name_status(staged + "\n" + unstaged)

        # Add untracked files as additions
        for line in untracked.strip().split("\n"):
            line = line.strip()
            if line and line.endswith(".tmdl"):
                changes.append(("A", line))

        return self._categorize_changes(changes)

    def analyze_commit_diff(
        self,
        from_ref: str = "HEAD~1",
        to_ref: str = "HEAD",
    ) -> Dict[str, Any]:
        """
        Analyze TMDL changes between two git refs.

        Args:
            from_ref: Starting reference (commit, branch, tag)
            to_ref: Ending reference

        Returns:
            Dictionary with categorized changes
        """
        output = self._run_git(["diff", "--name-status", from_ref, to_ref])
        changes = self._parse_name_status(output)
        result = self._categorize_changes(changes)
        result["from_ref"] = from_ref
        result["to_ref"] = to_ref
        return result

    def summarize_pr_changes(
        self,
        base_branch: str = "main",
    ) -> Dict[str, Any]:
        """
        Summarize changes for a PR against a base branch.

        Args:
            base_branch: Base branch to compare against

        Returns:
            Dictionary with PR summary and categorized changes
        """
        # Find merge base
        try:
            merge_base = self._run_git(
                ["merge-base", base_branch, "HEAD"]
            ).strip()
        except RuntimeError:
            merge_base = base_branch

        output = self._run_git(["diff", "--name-status", merge_base, "HEAD"])
        changes = self._parse_name_status(output)
        result = self._categorize_changes(changes)

        # Add commit log
        try:
            log = self._run_git([
                "log", "--oneline", f"{merge_base}..HEAD"
            ]).strip()
            result["commits"] = log.split("\n") if log else []
        except RuntimeError:
            result["commits"] = []

        result["base_branch"] = base_branch
        result["merge_base"] = merge_base

        # Generate summary text
        result["summary"] = self._generate_summary_text(result)

        return result

    def _parse_name_status(self, output: str) -> List[tuple]:
        """Parse git diff --name-status output into (status, path) tuples."""
        changes = []
        for line in output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                status = parts[0][0]  # A, M, D, R
                filepath = parts[1]
                if filepath.endswith(".tmdl") or filepath.endswith(".json") or filepath.endswith(".pbir"):
                    changes.append((status, filepath))
        return changes

    def _categorize_changes(self, changes: List[tuple]) -> Dict[str, Any]:
        """Categorize file changes into semantic categories."""
        result: Dict[str, Any] = {
            "tables": {"added": [], "modified": [], "deleted": []},
            "relationships": {"modified": False},
            "expressions": {"modified": False},
            "roles": {"added": [], "modified": [], "deleted": []},
            "perspectives": {"added": [], "modified": [], "deleted": []},
            "cultures": {"added": [], "modified": [], "deleted": []},
            "report": {"modified": False, "pages_changed": []},
            "model_config": {"modified": False},
            "total_tmdl_changes": 0,
            "total_report_changes": 0,
            "files": [],
        }

        for status, filepath in changes:
            fp = Path(filepath)
            parts = fp.parts
            name = fp.stem
            action = {"A": "added", "M": "modified", "D": "deleted"}.get(status, "modified")

            result["files"].append({"status": status, "path": filepath})

            if filepath.endswith(".tmdl"):
                result["total_tmdl_changes"] += 1

                if "tables" in parts:
                    result["tables"][action].append(name)
                elif fp.name == "relationships.tmdl":
                    result["relationships"]["modified"] = True
                elif fp.name == "expressions.tmdl":
                    result["expressions"]["modified"] = True
                elif fp.name == "model.tmdl" or fp.name == "database.tmdl":
                    result["model_config"]["modified"] = True
                elif "roles" in parts:
                    result["roles"][action].append(name)
                elif "perspectives" in parts:
                    result["perspectives"][action].append(name)
                elif "cultures" in parts:
                    result["cultures"][action].append(name)

            elif filepath.endswith(".json") or filepath.endswith(".pbir"):
                result["total_report_changes"] += 1
                result["report"]["modified"] = True
                if "pages" in parts:
                    # Try to extract page name from path
                    try:
                        pages_idx = list(parts).index("pages")
                        if pages_idx + 1 < len(parts):
                            page_name = parts[pages_idx + 1]
                            if page_name not in result["report"]["pages_changed"]:
                                result["report"]["pages_changed"].append(page_name)
                    except (ValueError, IndexError):
                        pass

        return result

    def _generate_summary_text(self, categorized: Dict[str, Any]) -> str:
        """Generate a business-readable summary of changes."""
        lines = []

        tables = categorized.get("tables", {})
        if tables.get("added"):
            lines.append(f"Added tables: {', '.join(tables['added'])}")
        if tables.get("modified"):
            lines.append(f"Modified tables: {', '.join(tables['modified'])}")
        if tables.get("deleted"):
            lines.append(f"Deleted tables: {', '.join(tables['deleted'])}")

        if categorized.get("relationships", {}).get("modified"):
            lines.append("Relationships modified")

        if categorized.get("expressions", {}).get("modified"):
            lines.append("Shared expressions/parameters modified")

        roles = categorized.get("roles", {})
        if any(roles.get(k) for k in ("added", "modified", "deleted")):
            lines.append(f"Security roles changed: +{len(roles.get('added', []))} ~{len(roles.get('modified', []))} -{len(roles.get('deleted', []))}")

        if categorized.get("model_config", {}).get("modified"):
            lines.append("Model configuration changed")

        report = categorized.get("report", {})
        if report.get("modified"):
            pages = report.get("pages_changed", [])
            if pages:
                lines.append(f"Report pages changed: {', '.join(pages)}")
            else:
                lines.append("Report definition changed")

        if not lines:
            lines.append("No semantic model or report changes detected")

        return "; ".join(lines)
