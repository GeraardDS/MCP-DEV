"""
Input validation and sanitization for Power BI MCP Server.
Prevents injection attacks, path traversal, and malicious inputs.
"""

import re
import os
from pathlib import Path
from typing import Optional, List, Tuple
import logging

logger = logging.getLogger("mcp_powerbi_finvision.input_validator")


class InputValidator:
    """Centralized input validation and sanitization."""
    
    # DAX identifier rules
    MAX_IDENTIFIER_LENGTH = 128
    MAX_DAX_QUERY_LENGTH = 500_000
    MAX_M_EXPRESSION_LENGTH = 1_000_000
    
    # Path rules
    ALLOWED_EXPORT_EXTENSIONS = {'.json', '.csv', '.txt', '.xlsx', '.xml', '.graphml', '.yaml', '.yml'}
    MAX_PATH_LENGTH = 260  # Windows MAX_PATH
    
    # Dangerous patterns
    DANGEROUS_DAX_PATTERNS = [
        r';\s*DROP\s+TABLE',
        r';\s*DELETE\s+FROM',
        r';\s*TRUNCATE\s+TABLE',
        r'xp_cmdshell',
        r'sp_executesql',
        r'OPENROWSET',
        r'OPENDATASOURCE',
    ]
    
    DANGEROUS_M_PATTERNS = [
        r'File\.Contents\s*\(',
        r'Web\.Contents\s*\(',
        r'Sql\.Database\s*\(',
        r'#shared',
    ]
    
    @classmethod
    def validate_table_name(cls, name: str) -> Tuple[bool, Optional[str]]:
        """
        Validate table name for DAX safety.
        
        Returns:
            (is_valid, error_message)
        """
        if not name or not isinstance(name, str):
            return False, "Table name must be a non-empty string"
        
        name = name.strip()
        
        if len(name) > cls.MAX_IDENTIFIER_LENGTH:
            return False, f"Table name exceeds {cls.MAX_IDENTIFIER_LENGTH} characters"
        
        # Check for null bytes
        if '\x00' in name:
            return False, "Table name contains null bytes"
        
        # Check for control characters
        if any(ord(c) < 32 for c in name):
            return False, "Table name contains control characters"
        
        # Warn on suspicious patterns (but allow - some Desktop models have weird names)
        suspicious = ['--', '/*', '*/', 'xp_', 'sp_', 'DROP', 'DELETE']
        if any(pattern in name.upper() for pattern in suspicious):
            logger.warning(f"Suspicious table name detected: {name}")
        
        return True, None
    
    @classmethod
    def validate_column_name(cls, name: str) -> Tuple[bool, Optional[str]]:
        """Validate column name (same rules as table)."""
        return cls.validate_table_name(name)
    
    @classmethod
    def validate_measure_name(cls, name: str) -> Tuple[bool, Optional[str]]:
        """Validate measure name."""
        return cls.validate_table_name(name)
    
    @classmethod
    def sanitize_dax_identifier(cls, name: str) -> str:
        """
        Sanitize a DAX identifier (table/column/measure name).
        Removes null bytes and control characters.
        """
        if not name:
            return ""
        
        # Remove null bytes and control characters
        cleaned = ''.join(c for c in name if ord(c) >= 32 and c != '\x00')
        return cleaned.strip()
    
    @classmethod
    def validate_dax_query(cls, query: str) -> Tuple[bool, Optional[str]]:
        """
        Validate DAX query for safety.
        
        Returns:
            (is_valid, error_message)
        """
        if not query or not isinstance(query, str):
            return False, "Query must be a non-empty string"
        
        if len(query) > cls.MAX_DAX_QUERY_LENGTH:
            return False, f"Query exceeds {cls.MAX_DAX_QUERY_LENGTH} characters"
        
        # Check for null bytes
        if '\x00' in query:
            return False, "Query contains null bytes"
        
        # Check for dangerous patterns
        query_upper = query.upper()
        for pattern in cls.DANGEROUS_DAX_PATTERNS:
            if re.search(pattern, query_upper, re.IGNORECASE):
                return False, f"Query contains potentially dangerous pattern: {pattern}"
        
        return True, None
    
    @classmethod
    def validate_m_expression(cls, expression: str, strict: bool = False) -> Tuple[bool, Optional[str]]:
        """
        Validate M expression for safety.
        
        Args:
            expression: The M expression to validate
            strict: If True, reject any file/web access patterns
        
        Returns:
            (is_valid, error_message)
        """
        if not expression or not isinstance(expression, str):
            return False, "Expression must be a non-empty string"
        
        if len(expression) > cls.MAX_M_EXPRESSION_LENGTH:
            return False, f"Expression exceeds {cls.MAX_M_EXPRESSION_LENGTH} characters"
        
        # Check for null bytes
        if '\x00' in expression:
            return False, "Expression contains null bytes"
        
        if strict:
            # In strict mode, reject external data access
            for pattern in cls.DANGEROUS_M_PATTERNS:
                if re.search(pattern, expression, re.IGNORECASE):
                    logger.warning(f"M expression contains external access pattern: {pattern}")
                    return False, f"Expression contains restricted pattern: {pattern}"
        
        return True, None
    
    @classmethod
    def validate_export_path(cls, path: str, base_dir: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Validate export path for safety.
        Prevents path traversal and enforces allowed locations.
        
        Args:
            path: The path to validate
            base_dir: Optional base directory to restrict paths to
        
        Returns:
            (is_valid, error_message)
        """
        if not path or not isinstance(path, str):
            return False, "Path must be a non-empty string"
        
        if len(path) > cls.MAX_PATH_LENGTH:
            return False, f"Path exceeds {cls.MAX_PATH_LENGTH} characters"
        
        # Check for null bytes
        if '\x00' in path:
            return False, "Path contains null bytes"

        # Check for path traversal in raw input (before normpath resolves it away)
        if '..' in path:
            return False, "Path contains traversal sequences (..)"

        # Normalize path
        try:
            normalized = os.path.normpath(path)
            resolved = Path(normalized).resolve()
        except (ValueError, OSError) as e:
            return False, f"Invalid path: {e}"
        
        # Check extension if it's a file
        if '.' in os.path.basename(path):
            ext = Path(path).suffix.lower()
            if ext and ext not in cls.ALLOWED_EXPORT_EXTENSIONS:
                return False, f"File extension {ext} not allowed. Allowed: {cls.ALLOWED_EXPORT_EXTENSIONS}"
        
        # If base_dir specified, ensure path is within it
        if base_dir:
            try:
                base_resolved = Path(base_dir).resolve()
                if not str(resolved).startswith(str(base_resolved)):
                    return False, f"Path must be within {base_dir}"
            except (ValueError, OSError) as e:
                return False, f"Invalid base directory: {e}"
        
        return True, None
    
    @classmethod
    def sanitize_export_path(cls, path: str, base_dir: str) -> str:
        """
        Sanitize and make safe an export path.
        
        Args:
            path: The path to sanitize
            base_dir: Base directory to confine path to
        
        Returns:
            Sanitized absolute path within base_dir
        """
        if not path:
            path = "export"
        
        # Remove dangerous characters
        safe_name = re.sub(r'[^\w\s\-.]', '_', os.path.basename(path))
        
        # Ensure base_dir exists
        base_path = Path(base_dir).resolve()
        base_path.mkdir(parents=True, exist_ok=True)
        
        # Construct safe path
        safe_path = base_path / safe_name
        
        return str(safe_path)
    
    @classmethod
    def validate_integer_param(cls, value: any, min_val: int = None, max_val: int = None, 
                               param_name: str = "parameter") -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Validate and coerce integer parameters.
        
        Returns:
            (is_valid, error_message, coerced_value)
        """
        try:
            int_val = int(value)
        except (ValueError, TypeError):
            return False, f"{param_name} must be an integer", None
        
        if min_val is not None and int_val < min_val:
            return False, f"{param_name} must be >= {min_val}", None
        
        if max_val is not None and int_val > max_val:
            return False, f"{param_name} must be <= {max_val}", None
        
        return True, None, int_val
    
    @classmethod
    def validate_page_size(cls, page_size: any) -> Tuple[bool, Optional[str], Optional[int]]:
        """Validate pagination page_size parameter."""
        if page_size is None:
            return True, None, None
        
        return cls.validate_integer_param(page_size, min_val=1, max_val=10000, param_name="page_size")
    
    @classmethod
    def validate_runs(cls, runs: any) -> Tuple[bool, Optional[str], Optional[int]]:
        """Validate performance test runs parameter."""
        if runs is None:
            return True, None, None
        
        return cls.validate_integer_param(runs, min_val=1, max_val=50, param_name="runs")


# Convenience wrapper functions for common validations

def validate_and_sanitize_identifier(name: str, identifier_type: str = "identifier") -> str:
    """
    Validate and sanitize a DAX identifier, raising on failure.
    
    Args:
        name: The identifier to validate
        identifier_type: Type name for error messages (table/column/measure)
    
    Returns:
        Sanitized identifier
    
    Raises:
        ValueError: If validation fails
    """
    is_valid, error = InputValidator.validate_table_name(name)
    if not is_valid:
        raise ValueError(f"Invalid {identifier_type} name: {error}")
    
    return InputValidator.sanitize_dax_identifier(name)


def validate_export_directory(path: str, base_dir: str) -> str:
    """
    Validate export directory, creating if needed.
    
    Returns:
        Absolute path to validated directory
    
    Raises:
        ValueError: If validation fails
    """
    is_valid, error = InputValidator.validate_export_path(path, base_dir)
    if not is_valid:
        raise ValueError(f"Invalid export path: {error}")
    
    # Create directory if it doesn't exist
    abs_path = Path(path).resolve()
    abs_path.mkdir(parents=True, exist_ok=True)
    
    return str(abs_path)
