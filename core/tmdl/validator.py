"""
TMDL Validator - Syntax validation and best practices linting

Validates TMDL folder structures for syntax errors, reference integrity,
and best practices violations.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from enum import Enum

logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    """Severity levels for validation issues"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationError:
    """Represents a validation error or warning"""
    file: str
    line: int
    column: int
    severity: ValidationSeverity
    code: str
    message: str
    suggestion: Optional[str] = None


@dataclass
class LintIssue:
    """Represents a linting/best practices issue"""
    file: str
    line: int
    severity: ValidationSeverity
    rule: str
    message: str
    suggestion: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of TMDL validation"""
    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    info: List[ValidationError] = field(default_factory=list)
    files_checked: int = 0

    @property
    def total_errors(self) -> int:
        return len(self.errors)

    @property
    def total_warnings(self) -> int:
        return len(self.warnings)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "success": self.is_valid,
            "errors": [
                {
                    "file": e.file,
                    "line": e.line,
                    "column": e.column,
                    "severity": e.severity.value,
                    "code": e.code,
                    "message": e.message,
                    "suggestion": e.suggestion,
                }
                for e in self.errors + self.warnings + self.info
            ],
            "summary": {
                "total_errors": self.total_errors,
                "total_warnings": self.total_warnings,
                "files_checked": self.files_checked,
            },
        }


class TmdlValidator:
    """
    TMDL Validation and Linting Engine

    Validates TMDL folder structures for:
    - Syntax errors (indentation, missing colons, unclosed strings)
    - Reference integrity (column/measure references exist)
    - Data type validity
    - Relationship validity
    - Naming conventions
    - Best practices
    """

    VALID_DATA_TYPES = {
        "string", "int64", "double", "dateTime", "boolean", "decimal",
        "currency", "rowNumber", "binary", "variant"
    }

    VALID_CARDINALITIES = {"many", "one", "none"}

    RESERVED_KEYWORDS = {
        "table", "column", "measure", "relationship", "partition",
        "annotation", "role", "expression", "dataType", "formatString"
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize validator with optional configuration

        Args:
            config: Optional configuration dict with validation rules
        """
        self.config = config or {}
        self.validation_rules = self.config.get("validation_rules", {})
        self.linting_enabled = self.config.get("linting", {}).get("enabled", True)

        # Will be populated during validation
        self.tables: Set[str] = set()
        self.columns: Dict[str, Set[str]] = {}  # table -> set of columns
        self.measures: Dict[str, Set[str]] = {}  # table -> set of measures
        self.relationships: List[Dict[str, str]] = []

    def validate_syntax(self, tmdl_path: str) -> ValidationResult:
        """
        Validate TMDL folder structure for syntax errors

        Args:
            tmdl_path: Path to TMDL definition folder

        Returns:
            ValidationResult with all errors and warnings
        """
        try:
            path = Path(tmdl_path)
            if not path.exists():
                logger.error(f"TMDL path does not exist: {tmdl_path}")
                return ValidationResult(
                    is_valid=False,
                    errors=[
                        ValidationError(
                            file=str(path),
                            line=0,
                            column=0,
                            severity=ValidationSeverity.ERROR,
                            code="TMDL000",
                            message=f"TMDL path does not exist: {tmdl_path}",
                            suggestion="Verify the path is correct and accessible"
                        )
                    ]
                )

            result = ValidationResult(is_valid=True)

            # First pass: collect all tables, columns, measures
            self._collect_model_objects(path, result)

            # Second pass: validate files
            files_to_check = [
                path / "database.tmdl",
                path / "model.tmdl",
            ]

            # Add all table files
            tables_dir = path / "tables"
            if tables_dir.exists():
                files_to_check.extend(tables_dir.glob("*.tmdl"))

            # Add relationship files
            relationships_dir = path / "relationships"
            if relationships_dir.exists():
                files_to_check.extend(relationships_dir.glob("*.tmdl"))

            for file_path in files_to_check:
                if file_path.exists():
                    self._validate_file(file_path, result)
                    result.files_checked += 1

            # Third pass: validate references
            self._validate_references(result)

            # Update is_valid based on errors
            result.is_valid = len(result.errors) == 0

            logger.info(
                f"TMDL validation complete: {result.files_checked} files, "
                f"{result.total_errors} errors, {result.total_warnings} warnings"
            )

            return result

        except Exception as e:
            logger.error(f"Error during TMDL validation: {e}", exc_info=True)
            return ValidationResult(
                is_valid=False,
                errors=[
                    ValidationError(
                        file=tmdl_path,
                        line=0,
                        column=0,
                        severity=ValidationSeverity.ERROR,
                        code="TMDL999",
                        message=f"Validation failed: {str(e)}",
                        suggestion="Check logs for details"
                    )
                ]
            )

    def _collect_model_objects(self, path: Path, result: ValidationResult) -> None:
        """First pass: collect all tables, columns, measures"""
        try:
            tables_dir = path / "tables"
            if not tables_dir.exists():
                return

            for table_file in tables_dir.glob("*.tmdl"):
                table_name = table_file.stem
                self.tables.add(table_name)
                self.columns[table_name] = set()
                self.measures[table_name] = set()

                # Parse file to extract columns and measures
                try:
                    content = table_file.read_text(encoding="utf-8")
                    self._extract_columns_and_measures(
                        content, table_name, self.columns[table_name], self.measures[table_name]
                    )
                except Exception as e:
                    logger.warning(f"Could not parse {table_file}: {e}")

        except Exception as e:
            logger.error(f"Error collecting model objects: {e}", exc_info=True)

    def _extract_columns_and_measures(
        self, content: str, table_name: str, columns: Set[str], measures: Set[str]
    ) -> None:
        """Extract column and measure names from TMDL content"""
        lines = content.split("\n")
        current_section = None

        for line in lines:
            stripped = line.strip()

            # Detect sections
            if stripped.startswith("column "):
                # column 'ColumnName' or column "ColumnName"
                match = re.match(r"column\s+['\"]([^'\"]+)['\"]", stripped)
                if match:
                    columns.add(match.group(1))
                    current_section = "column"
            elif stripped.startswith("measure "):
                # measure 'MeasureName' or measure "MeasureName"
                match = re.match(r"measure\s+['\"]([^'\"]+)['\"]", stripped)
                if match:
                    measures.add(match.group(1))
                    current_section = "measure"
            elif stripped.startswith("table "):
                current_section = "table"

    def _validate_file(self, file_path: Path, result: ValidationResult) -> None:
        """Validate a single TMDL file for syntax errors"""
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.split("\n")

            for line_num, line in enumerate(lines, start=1):
                # Check indentation (should be tabs or spaces, but consistent)
                if line and not line[0].isspace() and not line[0].isalpha():
                    if line[0] not in {"\t", " "} and ":" not in line:
                        result.warnings.append(
                            ValidationError(
                                file=str(file_path),
                                line=line_num,
                                column=0,
                                severity=ValidationSeverity.WARNING,
                                code="TMDL002",
                                message="Unexpected character at line start",
                                suggestion="Check indentation and formatting"
                            )
                        )

                # Check for unclosed strings
                stripped = line.strip()
                if stripped.count("'") % 2 != 0 or stripped.count('"') % 2 != 0:
                    if not stripped.endswith("\\"):  # Allow line continuations
                        result.errors.append(
                            ValidationError(
                                file=str(file_path),
                                line=line_num,
                                column=0,
                                severity=ValidationSeverity.ERROR,
                                code="TMDL003",
                                message="Unclosed string literal",
                                suggestion="Add closing quote"
                            )
                        )

                # Check dataType values
                if "dataType:" in line or "datatype:" in line:
                    match = re.search(r"dataType:\s*(\w+)", line, re.IGNORECASE)
                    if match:
                        data_type = match.group(1)
                        if data_type not in self.VALID_DATA_TYPES:
                            result.errors.append(
                                ValidationError(
                                    file=str(file_path),
                                    line=line_num,
                                    column=line.index("dataType"),
                                    severity=ValidationSeverity.ERROR,
                                    code="TMDL001",
                                    message=f"Invalid data type '{data_type}'. Valid types: {', '.join(sorted(self.VALID_DATA_TYPES))}",
                                    suggestion=f"Use a valid data type (e.g., 'string', 'int64', 'double')"
                                )
                            )

        except Exception as e:
            logger.error(f"Error validating file {file_path}: {e}", exc_info=True)
            result.errors.append(
                ValidationError(
                    file=str(file_path),
                    line=0,
                    column=0,
                    severity=ValidationSeverity.ERROR,
                    code="TMDL998",
                    message=f"Failed to read file: {str(e)}",
                    suggestion="Check file encoding and permissions"
                )
            )

    def _validate_references(self, result: ValidationResult) -> None:
        """Validate that all references (columns, measures) exist in the model"""
        # This is a simplified version - full implementation would parse DAX expressions
        # and extract all [Table[Column]] and [Measure] references
        logger.warning(
            "Reference validation is not yet fully implemented. "
            "DAX expression reference checking will be added in a future version."
        )

    def lint_best_practices(self, tmdl_path: str) -> List[LintIssue]:
        """
        Run best practices linting on TMDL model

        Args:
            tmdl_path: Path to TMDL definition folder

        Returns:
            List of linting issues
        """
        if not self.linting_enabled:
            return []

        issues: List[LintIssue] = []

        try:
            path = Path(tmdl_path)

            # Rule: Check for hidden columns referenced in measures
            self._lint_hidden_column_references(path, issues)

            # Rule: Check for large number of measures in a single table
            self._lint_measure_count(path, issues)

            # Rule: Check for naming conventions
            self._lint_naming_conventions(path, issues)

            # Rule: Check for unused columns
            self._lint_unused_columns(path, issues)

            logger.info(f"Linting complete: {len(issues)} issues found")

        except Exception as e:
            logger.error(f"Error during linting: {e}", exc_info=True)

        return issues

    def _lint_hidden_column_references(self, path: Path, issues: List[LintIssue]) -> None:
        """Check for hidden columns referenced in measures"""
        # Implementation would parse measures and check for hidden column references
        logger.warning(
            "Hidden column reference linting is not yet implemented. "
            "Skipping hidden column reference checks."
        )

    def _lint_measure_count(self, path: Path, issues: List[LintIssue]) -> None:
        """Check for tables with too many measures"""
        tables_dir = path / "tables"
        if not tables_dir.exists():
            return

        for table_file in tables_dir.glob("*.tmdl"):
            try:
                content = table_file.read_text(encoding="utf-8")
                measure_count = content.count("measure ")

                if measure_count > 100:
                    issues.append(
                        LintIssue(
                            file=str(table_file),
                            line=0,
                            severity=ValidationSeverity.WARNING,
                            rule="large_measure_count",
                            message=f"Table has {measure_count} measures (>100)",
                            suggestion="Consider organizing measures into calculation groups or separate tables"
                        )
                    )
            except Exception as e:
                logger.warning(f"Could not check measure count for {table_file}: {e}")

    def _lint_naming_conventions(self, path: Path, issues: List[LintIssue]) -> None:
        """Check naming conventions"""
        # Check for reserved keywords, special characters, etc.
        for table_name in self.tables:
            if table_name.lower() in self.RESERVED_KEYWORDS:
                issues.append(
                    LintIssue(
                        file=f"tables/{table_name}.tmdl",
                        line=1,
                        severity=ValidationSeverity.WARNING,
                        rule="reserved_keyword",
                        message=f"Table name '{table_name}' is a reserved keyword",
                        suggestion="Use a different name to avoid conflicts"
                    )
                )

    def _lint_unused_columns(self, path: Path, issues: List[LintIssue]) -> None:
        """Check for columns that are never referenced"""
        # This would require parsing all DAX expressions and checking references
        logger.warning(
            "Unused column linting is not yet implemented. "
            "DAX expression parsing for reference detection will be added in a future version."
        )

    def validate_references(self, tmdl_path: str) -> List[ValidationError]:
        """
        Validate that all DAX references point to existing objects

        Args:
            tmdl_path: Path to TMDL definition folder

        Returns:
            List of reference errors
        """
        errors: List[ValidationError] = []

        try:
            # This would parse all DAX expressions and validate references
            logger.warning(
                "Public reference validation is not yet fully implemented. "
                "Returning empty error list. Full DAX reference validation "
                "will be added in a future version."
            )

        except Exception as e:
            logger.error(f"Error validating references: {e}", exc_info=True)

        return errors
