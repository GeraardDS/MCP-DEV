"""
Server Middleware Utilities
Pagination, truncation, formatting helpers
"""
from typing import Any, Dict, List, Optional, Tuple
import json

# Pagination and truncation limits
MAX_PAGE_SIZE = 10000
MAX_PAGINATION_OFFSET = 1000000
DEFAULT_MAX_TOKENS = 100000
TRUNCATION_ITEM_LIMIT = 100
TRUNCATION_STRING_LIMIT = 50000
SUMMARY_THRESHOLD_TOKENS = 50000

def paginate(result: Any, page_size: Optional[int], next_token: Optional[str], list_keys: List[str]) -> Any:
    """
    Paginate result arrays with continuation tokens

    Args:
        result: Result dict containing arrays to paginate
        page_size: Items per page (must be between 1 and 10000)
        next_token: Continuation token
        list_keys: Keys in result dict that contain lists to paginate

    Returns:
        Result with paginated data and next_token if more data available
    """
    if not isinstance(result, dict) or not result.get('success'):
        return result

    if page_size is None or page_size <= 0:
        return result

    # Validate page_size bounds
    if page_size > MAX_PAGE_SIZE:
        return {
            'success': False,
            'error': f'page_size exceeds maximum allowed value of {MAX_PAGE_SIZE}',
            'error_type': 'ValidationError'
        }

    # Parse token (format: "key:offset")
    start_offset = 0
    target_key = None
    if next_token:
        try:
            parts = next_token.split(':', 1)
            if len(parts) == 2:
                target_key, offset_str = parts
                start_offset = int(offset_str)
                # Validate offset is non-negative and reasonable
                if start_offset < 0 or start_offset > MAX_PAGINATION_OFFSET:
                    return {
                        'success': False,
                        'error': 'Invalid next_token: offset out of valid range',
                        'error_type': 'ValidationError'
                    }
        except (ValueError, AttributeError) as e:
            return {
                'success': False,
                'error': f'Invalid next_token format: {str(e)}',
                'error_type': 'ValidationError'
            }

    # Apply pagination to each list key
    new_token = None
    for key in list_keys:
        if key not in result:
            continue

        arr = result.get(key, [])
        if not isinstance(arr, list):
            continue

        # Skip if this isn't the target key (when continuing pagination)
        if target_key and key != target_key:
            continue

        # Paginate
        paginated, token = paginate_section(arr, page_size, start_offset)
        result[key] = paginated

        if token is not None:
            new_token = f"{key}:{token}"
            break

    # Add pagination metadata
    if new_token:
        result['next_token'] = new_token
        result['has_more'] = True
    else:
        result.pop('next_token', None)
        result['has_more'] = False

    return result

def paginate_section(arr: Any, size: Optional[Any], offset: int = 0) -> Tuple[list, Optional[str]]:
    """
    Paginate a single array section

    Returns:
        (paginated_array, next_offset_or_none)
    """
    if not isinstance(arr, list):
        return arr, None

    if size is None or size <= 0:
        return arr, None

    try:
        size = int(size)
        offset = int(offset)
    except (ValueError, TypeError):
        return arr, None

    end = offset + size
    paginated = arr[offset:end]

    next_token = str(end) if end < len(arr) else None
    return paginated, next_token

def schema_sample(rows: List[dict], sample_size: int) -> dict:
    """
    Sample a subset of rows with count metadata

    Args:
        rows: List of row dictionaries
        sample_size: Max rows to include

    Returns:
        Dict with 'sample' and 'total_count'
    """
    if not isinstance(rows, list):
        return {'sample': [], 'total_count': 0}

    total = len(rows)
    sample = rows[:sample_size] if sample_size > 0 else []

    return {
        'sample': sample,
        'total_count': total,
        'is_sample': total > sample_size
    }

def truncate_if_needed(result: dict, max_tokens: int = DEFAULT_MAX_TOKENS) -> dict:
    """
    Truncate large results to prevent token overflow

    Args:
        result: Result dictionary
        max_tokens: Approximate max tokens (rough estimate: 4 chars = 1 token)

    Returns:
        Possibly truncated result with metadata
    """
    if not isinstance(result, dict):
        return result

    try:
        # Rough token estimation
        json_str = json.dumps(result)
        estimated_tokens = len(json_str) // 4

        if estimated_tokens <= max_tokens:
            return result

        # Need to truncate - try to preserve important data
        truncated = dict(result)
        truncated['_truncated'] = True
        truncated['_original_size_estimate'] = estimated_tokens

        # Truncate arrays
        for key in ['rows', 'measures', 'columns', 'tables', 'relationships']:
            if key in truncated and isinstance(truncated[key], list):
                original_len = len(truncated[key])
                # Keep first N items
                truncated[key] = truncated[key][:TRUNCATION_ITEM_LIMIT]
                truncated[f'_{key}_truncated_from'] = original_len

        # Truncate long strings (skip 'formatted_output' field for DAX Intelligence)
        for key, value in list(truncated.items()):
            if isinstance(value, str) and len(value) > TRUNCATION_STRING_LIMIT and key != 'formatted_output':
                truncated[key] = value[:TRUNCATION_STRING_LIMIT] + "... [truncated]"

        return truncated

    except Exception:
        return result

def truncate_expression(expression: str, max_length: int = 500) -> str:
    """
    Truncate long expressions with ellipsis

    Args:
        expression: DAX or M expression
        max_length: Maximum length

    Returns:
        Truncated expression
    """
    if not isinstance(expression, str):
        return str(expression)

    if len(expression) <= max_length:
        return expression

    return expression[:max_length] + "... [truncated]"

def apply_default_limits(arguments: dict, defaults: dict) -> dict:
    """
    Apply default values to missing arguments

    Args:
        arguments: Tool arguments
        defaults: Default values dict

    Returns:
        Arguments with defaults applied
    """
    args = dict(arguments)
    for key, default_value in defaults.items():
        if key not in args or args[key] is None:
            args[key] = default_value
    return args

def add_note(result: Any, note: str) -> Any:
    """Add a note to result metadata"""
    if not isinstance(result, dict):
        return result

    if 'notes' not in result:
        result['notes'] = []
    elif not isinstance(result['notes'], list):
        result['notes'] = [result['notes']]

    result['notes'].append(note)
    return result

def note_truncated(result: Any, limit: int) -> Any:
    """Add truncation note"""
    return add_note(result, f"Results truncated to {limit} items for performance")

def note_tom_fallback(result: Any) -> Any:
    """Add TOM fallback note"""
    return add_note(result, "Retrieved via TOM/AMO fallback (DMV query blocked)")

def note_client_filter(result: Any, table: str) -> Any:
    """Add client-side filter note"""
    return add_note(result, f"Server filter failed; applied client-side filter for table '{table}'")

def dax_quote_table(name: str) -> str:
    """Quote table name for DAX"""
    return f"'{name.replace(chr(39), chr(39) + chr(39))}'"

def dax_quote_column(name: str) -> str:
    """Quote column name for DAX"""
    return f"[{name}]"

def attach_port_if_connected(result: Any) -> Any:
    """Attach current connection port to result"""
    if not isinstance(result, dict):
        return result

    try:
        from core.infrastructure.connection_state import connection_state
        if connection_state.is_connected():
            result['connection_port'] = connection_state.current_port
    except Exception:
        pass

    return result


# =============================================================================
# TOKEN OPTIMIZATION: Compact Response Functions
# =============================================================================

# Key mapping for compact JSON responses (reduces OUTPUT tokens by 15-25%)
COMPACT_KEY_MAP = {
    'success': 'ok',
    'error': 'err',
    'error_type': 'err_type',
    'execution_time_ms': 'ms',
    'estimated_tokens': 'tokens',
    'has_more': 'more',
    'next_token': 'next',
    'total_count': 'total',
    'page_size': 'page',
    'connection_port': 'port',
    'suggestions': 'hints',
    'description': 'desc',
    'expression': 'expr',
    'table_name': 'table',
    'column_name': 'col',
    'measure_name': 'measure',
    'data_type': 'dtype',
    'format_string': 'fmt',
    'is_hidden': 'hidden',
    'is_calculated': 'calc',
    'relationship_name': 'rel',
    'from_table': 'from_tbl',
    'to_table': 'to_tbl',
    'from_column': 'from_col',
    'to_column': 'to_col',
    'cardinality': 'card',
    'cross_filtering_behavior': 'cross_filter',
    '_truncated': '_trunc',
    '_original_size_estimate': '_orig_size',
}

# Reverse mapping for expanding keys
EXPAND_KEY_MAP = {v: k for k, v in COMPACT_KEY_MAP.items()}


def compact_keys(result: Any, deep: bool = True) -> Any:
    """
    Compact response keys to reduce token usage.

    Args:
        result: Result dictionary or nested structure
        deep: If True, recursively compact nested dicts/lists

    Returns:
        Result with shortened keys
    """
    if isinstance(result, dict):
        compacted = {}
        for key, value in result.items():
            new_key = COMPACT_KEY_MAP.get(key, key)
            if deep:
                compacted[new_key] = compact_keys(value, deep=True)
            else:
                compacted[new_key] = value
        return compacted
    elif isinstance(result, list) and deep:
        return [compact_keys(item, deep=True) for item in result]
    else:
        return result


def expand_keys(result: Any, deep: bool = True) -> Any:
    """
    Expand compacted keys back to full names.

    Args:
        result: Result with compacted keys
        deep: If True, recursively expand nested dicts/lists

    Returns:
        Result with full keys
    """
    if isinstance(result, dict):
        expanded = {}
        for key, value in result.items():
            new_key = EXPAND_KEY_MAP.get(key, key)
            if deep:
                expanded[new_key] = expand_keys(value, deep=True)
            else:
                expanded[new_key] = value
        return expanded
    elif isinstance(result, list) and deep:
        return [expand_keys(item, deep=True) for item in result]
    else:
        return result


def filter_fields(result: Any, fields: Optional[List[str]], list_keys: Optional[List[str]] = None) -> Any:
    """
    Filter result to include only specified fields (field projection).

    Args:
        result: Result dictionary
        fields: List of field names to include. If None, returns full result.
        list_keys: Keys in result that contain lists of items to filter

    Returns:
        Result with only requested fields
    """
    if not fields or not isinstance(result, dict):
        return result

    # Default list keys if not specified
    if list_keys is None:
        list_keys = ['rows', 'measures', 'columns', 'tables', 'relationships', 'items', 'data']

    # Always preserve these keys even if not in fields list
    preserve_keys = {'success', 'ok', 'error', 'err', 'error_type', 'err_type',
                     'next_token', 'next', 'has_more', 'more', 'total_count', 'total'}

    filtered = {}
    fields_set = set(fields)

    for key, value in result.items():
        # Always include preserved keys
        if key in preserve_keys:
            filtered[key] = value
        # Include requested fields
        elif key in fields_set:
            filtered[key] = value
        # Filter items in list keys
        elif key in list_keys and isinstance(value, list):
            filtered[key] = [
                {k: v for k, v in item.items() if k in fields_set}
                if isinstance(item, dict) else item
                for item in value
            ]

    return filtered


def summarize_large_result(result: dict, threshold_tokens: int = SUMMARY_THRESHOLD_TOKENS) -> dict:
    """
    Summarize large results to prevent token overflow.
    Returns summary with sample when result exceeds threshold.

    Args:
        result: Result dictionary
        threshold_tokens: Token threshold to trigger summarization

    Returns:
        Original result or summarized version
    """
    if not isinstance(result, dict):
        return result

    try:
        json_str = json.dumps(result)
        estimated_tokens = len(json_str) // 4

        if estimated_tokens < threshold_tokens:
            return result

        # Build summary
        summary = {
            'ok': result.get('success', result.get('ok', True)),
            '_summarized': True,
            '_orig_tokens': estimated_tokens,
        }

        # Count items in known list keys
        list_keys = ['rows', 'measures', 'columns', 'tables', 'relationships', 'items', 'data', 'results']
        item_counts = {}
        samples = {}

        for key in list_keys:
            if key in result and isinstance(result[key], list):
                items = result[key]
                item_counts[key] = len(items)
                # Include sample of first 3 items
                samples[key] = items[:3]

        if item_counts:
            summary['counts'] = item_counts
            summary['sample'] = samples

        # Preserve key metadata fields
        for key in ['total_count', 'total', 'execution_time_ms', 'ms', 'next_token', 'next']:
            if key in result:
                summary[key] = result[key]

        summary['hint'] = 'Use pagination (page_size) or field filtering (fields) to access full data'

        return summary

    except Exception:
        return result


def compact_response(data: Dict[str, Any], compact: bool = True,
                     remove_empty: bool = True, remove_nulls: bool = True) -> Dict[str, Any]:
    """
    Comprehensive response compaction for token optimization.
    Combines key compaction, empty removal, and null removal.

    Args:
        data: Response data dictionary
        compact: If True, apply key compaction
        remove_empty: If True, remove empty strings, lists, dicts
        remove_nulls: If True, remove None values

    Returns:
        Optimized response dictionary
    """
    if not isinstance(data, dict):
        return data

    # Fields to preserve even if empty (important diagnostic info)
    PRESERVE_FIELDS = {
        'anomalies', 'pbip_warning', 'relationship_hints',
        'aggregation_info', 'retry_info', 'execution_mode',
        'success', 'ok', 'error', 'err'
    }

    # Fields to skip entirely (verbose/redundant)
    SKIP_FIELDS = {'original', 'selected_values_raw', 'hint', 'recommendations'}

    def clean_value(key: str, value: Any) -> Tuple[bool, Any]:
        """Returns (should_include, cleaned_value)"""
        # Always preserve important fields
        if key in PRESERVE_FIELDS:
            return True, value

        # Skip redundant fields
        if key in SKIP_FIELDS:
            return False, None

        # Handle None
        if value is None:
            return not remove_nulls, value

        # Handle empty values
        if remove_empty:
            if value == '' or value == [] or value == {}:
                return False, None

        # Recursively clean nested dicts
        if isinstance(value, dict):
            cleaned = clean_dict(value)
            return bool(cleaned) or not remove_empty, cleaned

        # Clean lists of dicts
        if isinstance(value, list):
            if value and isinstance(value[0], dict):
                cleaned_list = [clean_dict(item) for item in value]
                cleaned_list = [item for item in cleaned_list if item]
                return bool(cleaned_list) or not remove_empty, cleaned_list
            return bool(value) or not remove_empty, value

        return True, value

    def clean_dict(d: Dict) -> Dict:
        result = {}
        for k, v in d.items():
            should_include, cleaned = clean_value(k, v)
            if should_include:
                new_key = COMPACT_KEY_MAP.get(k, k) if compact else k
                result[new_key] = cleaned
        return result

    return clean_dict(data)


def estimate_tokens(data: Any) -> int:
    """
    Estimate token count for data.

    Args:
        data: Any JSON-serializable data

    Returns:
        Estimated token count (4 chars ≈ 1 token)
    """
    try:
        json_str = json.dumps(data)
        return len(json_str) // 4
    except Exception:
        return 0
