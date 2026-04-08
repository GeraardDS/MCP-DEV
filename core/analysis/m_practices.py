from typing import Any, Dict, List, Optional


def scan_m_practices(query_executor: Any, dmv_cap: int = 1000, issues_max: Optional[int] = None) -> Dict[str, Any]:
    """Scan M expressions for common issues.

    Returns a dict with keys: success: bool, count: int, issues: List[dict]
    """
    try:
        m_query = f'''EVALUATE
        SELECTCOLUMNS(
            TOPN({dmv_cap}, $SYSTEM.TMSCHEMA_EXPRESSIONS),
            "Name", [Name],
            "Expression", [Expression],
            "Kind", [Kind]
        )'''
        data = query_executor.validate_and_execute_dax(m_query, dmv_cap)
        if not isinstance(data, dict) or not data.get('success'):
            # Fallback to TOM enumeration on Desktop where DMV may be blocked
            try:
                data = query_executor.enumerate_m_expressions_tom(dmv_cap)
            except Exception as _e:
                return data if isinstance(data, dict) else {'success': False, 'error': str(_e)}
        issues: List[Dict[str, Any]] = []
        for row in data.get('rows', []):
            if str(row.get('Kind', '')).upper() != 'M':
                continue
            name = row.get('Name') or '<unknown>'
            expr = (row.get('Expression') or '')
            expr_lower = expr.lower()
            if 'table.buffer(' in expr_lower:
                issues.append({'rule': 'M001', 'severity': 'warning', 'name': name, 'description': 'Table.Buffer used; can cause high memory usage if misapplied.'})
            if 'web.contents(' in expr_lower and ('relativepath' not in expr_lower and 'query=' not in expr_lower):
                issues.append({'rule': 'M002', 'severity': 'info', 'name': name, 'description': 'Web.Contents without RelativePath/Query options may be less cache-friendly.'})
            # Detect absolute Windows (C:\) or URL-like (C:/) paths in any File.Contents call
            if 'file.contents(' in expr_lower and (':\\' in expr_lower or ':/' in expr_lower):
                issues.append({'rule': 'M003', 'severity': 'warning', 'name': name, 'description': 'File.Contents with absolute path detected; consider parameterizing path.'})
            if 'table.selectrows(' in expr_lower:
                issues.append({'rule': 'M004', 'severity': 'info', 'name': name, 'description': 'Table.SelectRows found; ensure filtering is pushed to source where possible.'})
        if isinstance(issues_max, int) and issues_max > 0 and len(issues) > issues_max:
            issues = issues[:issues_max]
        return {'success': True, 'count': len(issues), 'issues': issues}
    except Exception as e:
        return {'success': False, 'error': str(e)}
