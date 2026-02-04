from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional


@dataclass
class ErrorResponse:
    """
    Structured error response with optional compaction for token optimization.

    Compact mode reduces token usage by:
    - Using shorter keys (ok, err, err_type, hints)
    - Omitting context and verbose suggestions
    - Including only a single actionable hint
    """
    success: bool = False
    error: str = ""
    error_type: str = "unexpected_error"
    suggestions: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    fix: Optional[str] = None  # Short actionable fix for compact mode

    def to_dict(self, compact: bool = False) -> dict:
        """
        Convert to dictionary.

        Args:
            compact: If True, return minimal error response

        Returns:
            Error dictionary
        """
        if compact:
            result = {'ok': False, 'err': self.error}
            if self.error_type and self.error_type != 'unexpected_error':
                result['err_type'] = self.error_type
            # Include fix hint if available, otherwise first suggestion
            if self.fix:
                result['fix'] = self.fix
            elif self.suggestions:
                result['fix'] = self.suggestions[0]
            return result
        else:
            # Full response - only include keys with truthy values
            data = asdict(self)
            # Remove fix from full response (it's for compact mode)
            data.pop('fix', None)
            out = {k: v for k, v in data.items() if (k == 'success' or v)}
            return out


def quick_error(error: str, fix: str = None, error_type: str = "error") -> dict:
    """
    Create a quick compact error response.

    Args:
        error: Error message
        fix: Short actionable fix instruction
        error_type: Error type identifier

    Returns:
        Compact error dictionary
    """
    result = {'ok': False, 'err': error}
    if error_type and error_type != 'error':
        result['err_type'] = error_type
    if fix:
        result['fix'] = fix
    return result


def not_connected_error() -> dict:
    """Standard 'not connected' error response."""
    return quick_error(
        "Not connected to Power BI",
        fix="Run 01_Connect_To_Instance",
        error_type="not_connected"
    )


def invalid_input_error(message: str) -> dict:
    """Standard invalid input error response."""
    return quick_error(message, error_type="invalid_input")


def operation_error(operation: str, message: str) -> dict:
    """Standard operation error response."""
    return quick_error(f"{operation}: {message}", error_type="operation_error")
