"""
DAX Utilities - Shared helper functions for DAX parsing and analysis

Provides common utilities used across context_analyzer, call_tree_builder,
and other DAX analysis modules. This is a leaf dependency with no imports
from other core.dax modules.

Functions:
- normalize_dax: Remove comments and normalize whitespace
- extract_function_body: Extract function body with string-literal-aware
  parenthesis matching
- find_matching_paren: Find matching closing parenthesis with string
  literal awareness
- extract_variables: Extract VAR variable definitions from DAX
- get_line_column: Convert character position to line/column
- validate_dax_identifier: Validate DAX identifier names
"""

import re
from typing import Dict, Tuple

# --- Pre-compiled regex patterns ---

# Single-line comment: // to end of line
_SINGLE_LINE_COMMENT_RE = re.compile(r"//.*?$", re.MULTILINE)

# Multi-line comment: /* ... */
_MULTI_LINE_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

# VAR declaration: VAR VarName =
_VAR_PATTERN_RE = re.compile(
    r"\bVAR\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*", re.IGNORECASE
)

# Next VAR keyword (for variable boundary detection)
_NEXT_VAR_RE = re.compile(r"\bVAR\s+", re.IGNORECASE)

# RETURN keyword (for variable boundary detection)
_RETURN_RE = re.compile(r"\bRETURN\b", re.IGNORECASE)

# DAX identifier validation
_DAX_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def normalize_dax(dax: str) -> str:
    """
    Normalize DAX expression by removing comments and extra whitespace.

    Removes single-line (//) and multi-line (/* */) comments.

    Args:
        dax: Raw DAX expression

    Returns:
        DAX expression with comments removed
    """
    # Remove single-line comments
    dax = _SINGLE_LINE_COMMENT_RE.sub("", dax)
    # Remove multi-line comments
    dax = _MULTI_LINE_COMMENT_RE.sub("", dax)
    return dax


def extract_function_body(dax: str, start: int) -> str:
    """
    Extract function body from opening paren position using
    string-literal-aware parenthesis matching.

    The caller should pass `start` as the position immediately AFTER the
    opening parenthesis (i.e., the first character inside the function
    body). The function returns the body text excluding the closing
    parenthesis.

    Handles DAX string literals correctly:
    - Double-quoted strings: "hello ""world"" "
    - Single-quoted table names: 'My Table'
    - Escaped quotes: "" inside double-quoted, '' inside single-quoted

    Args:
        dax: Full DAX expression
        start: Position right after the opening parenthesis

    Returns:
        Function body text (without the closing paren)
    """
    depth = 1
    pos = start
    in_double_quote = False
    in_single_quote = False
    length = len(dax)

    while pos < length and depth > 0:
        ch = dax[pos]

        if in_double_quote:
            if ch == '"':
                # Check for escaped double-quote ("")
                if pos + 1 < length and dax[pos + 1] == '"':
                    pos += 2
                    continue
                # End of double-quoted string
                in_double_quote = False
        elif in_single_quote:
            if ch == "'":
                # Check for escaped single-quote ('')
                if pos + 1 < length and dax[pos + 1] == "'":
                    pos += 2
                    continue
                # End of single-quoted string
                in_single_quote = False
        else:
            if ch == '"':
                in_double_quote = True
            elif ch == "'":
                in_single_quote = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return dax[start:pos]

        pos += 1

    # Fallback: return everything from start to end if unmatched
    return dax[start:pos]


def find_matching_paren(expr: str, open_pos: int) -> int:
    """
    Find matching closing parenthesis with string literal awareness.

    Args:
        expr: Expression string
        open_pos: Position of the opening parenthesis

    Returns:
        Position of matching closing parenthesis, or -1 if not found
    """
    depth = 1
    pos = open_pos + 1
    in_double_quote = False
    in_single_quote = False
    length = len(expr)

    while pos < length and depth > 0:
        ch = expr[pos]

        if in_double_quote:
            if ch == '"':
                if pos + 1 < length and expr[pos + 1] == '"':
                    pos += 2
                    continue
                in_double_quote = False
        elif in_single_quote:
            if ch == "'":
                if pos + 1 < length and expr[pos + 1] == "'":
                    pos += 2
                    continue
                in_single_quote = False
        else:
            if ch == '"':
                in_double_quote = True
            elif ch == "'":
                in_single_quote = True
            elif ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1

        pos += 1

    return pos - 1 if depth == 0 else -1


def extract_variables(dax: str) -> Dict[str, str]:
    """
    Extract VAR variable definitions from a DAX expression.

    Args:
        dax: DAX expression (should be normalized first)

    Returns:
        Dict mapping variable names to their definitions (truncated
        to 100 chars)
    """
    variables: Dict[str, str] = {}

    # Pattern to match VAR declarations: VAR VariableName = expression
    for match in _VAR_PATTERN_RE.finditer(dax):
        var_name = match.group(1)
        start_pos = match.end()

        # Extract the variable definition (until next VAR or RETURN)
        remaining = dax[start_pos:]
        next_var = _NEXT_VAR_RE.search(remaining)
        next_return = _RETURN_RE.search(remaining)

        end_pos = len(remaining)
        if next_var and next_return:
            end_pos = min(next_var.start(), next_return.start())
        elif next_var:
            end_pos = next_var.start()
        elif next_return:
            end_pos = next_return.start()

        definition = remaining[:end_pos].strip()

        # Truncate long definitions
        if len(definition) > 100:
            definition = definition[:100] + "..."

        variables[var_name] = definition

    return variables


def get_line_column(text: str, position: int) -> Tuple[int, int]:
    """
    Convert a character position to a 1-based (line, column) tuple.

    Args:
        text: Full text
        position: Character offset (0-based)

    Returns:
        Tuple of (line_number, column_number), both 1-based
    """
    lines = text[:position].split("\n")
    line = len(lines)
    column = len(lines[-1]) + 1
    return line, column


def validate_dax_identifier(name: str) -> bool:
    """Validate DAX identifier against strict naming pattern (letters, digits, underscores).

    NOTE: For loose safety-only validation (length/null checks),
    see dax_validator.validate_identifier() instead.
    """
    if not name:
        return False
    return bool(_DAX_IDENTIFIER_RE.fullmatch(name))
