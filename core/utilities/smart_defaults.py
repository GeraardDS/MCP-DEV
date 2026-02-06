"""
Smart Defaults System

This module provides intelligent default values for tool parameters based on
context, model characteristics, and best practices.
"""

from typing import Any, Optional, Dict
import logging

logger = logging.getLogger(__name__)


class SmartDefaults:
    """Provides intelligent default values based on context"""

    def __init__(self, connection_state=None):
        """
        Initialize smart defaults system

        Args:
            connection_state: Optional connection state for accessing model info
        """
        self.connection_state = connection_state
        self._table_size_cache: Dict[str, int] = {}
        self._model_complexity_cache: Optional[str] = None

    def get_default_top_n(self, table_name: Optional[str] = None, context: Optional[Dict[str, Any]] = None) -> int:
        """
        Get smart default for top_n parameter based on table size

        Args:
            table_name: Optional table name to check size
            context: Optional context with additional information

        Returns:
            Recommended top_n value
        """
        context = context or {}

        # If table name provided, base on table size
        if table_name:
            row_count = self._get_table_row_count(table_name)

            if row_count > 1000000:
                return 10  # Large table, small sample
            elif row_count > 100000:
                return 50  # Medium table
            elif row_count > 10000:
                return 100  # Smaller table
            else:
                return min(row_count, 100) if row_count > 0 else 100  # Very small table

        # Default based on context
        operation = context.get('operation', 'preview')

        if operation == 'preview':
            return 50  # Quick preview
        elif operation == 'analysis':
            return 100  # More data for analysis
        elif operation == 'export':
            return 1000  # More data for export
        else:
            return 100  # Safe default

    def get_default_analysis_depth(
        self,
        object_count: Optional[int] = None,
        complexity: Optional[str] = None
    ) -> str:
        """
        Get smart depth parameter based on model complexity

        Args:
            object_count: Number of objects in model (tables + measures)
            complexity: Known complexity level ('simple', 'medium', 'complex')

        Returns:
            Recommended depth: 'fast', 'balanced', or 'deep'
        """
        if complexity:
            complexity_map = {
                'simple': 'deep',
                'medium': 'balanced',
                'complex': 'fast'
            }
            return complexity_map.get(complexity, 'balanced')

        if object_count is not None:
            if object_count > 100:
                return "fast"  # Large model, use fast analysis
            elif object_count > 30:
                return "balanced"  # Medium model
            else:
                return "deep"  # Small model, can afford deep analysis

        # Try to get from model
        model_complexity = self._get_model_complexity()

        if model_complexity == 'large':
            return 'fast'
        elif model_complexity == 'medium':
            return 'balanced'
        else:
            return 'balanced'  # Safe default

    def get_default_timeout(
        self,
        operation_type: str,
        estimated_complexity: Optional[str] = None
    ) -> int:
        """
        Get smart timeout value based on operation type

        Args:
            operation_type: Type of operation ('query', 'analysis', 'export', etc.)
            estimated_complexity: Optional complexity estimate

        Returns:
            Timeout in seconds
        """
        base_timeouts = {
            'query': 30,
            'profile': 60,
            'analysis': 120,
            'comprehensive_analysis': 180,
            'export': 300,
            'import': 300,
            'documentation': 120,
            'comparison': 180
        }

        base_timeout = base_timeouts.get(operation_type, 60)

        # Adjust for complexity
        if estimated_complexity == 'high':
            return int(base_timeout * 1.5)
        elif estimated_complexity == 'low':
            return int(base_timeout * 0.75)

        return base_timeout

    def get_default_batch_size(
        self,
        operation_type: str,
        total_items: Optional[int] = None
    ) -> int:
        """
        Get smart batch size for bulk operations

        Args:
            operation_type: Type of operation ('create_measures', 'update_measures', etc.)
            total_items: Total number of items to process

        Returns:
            Recommended batch size
        """
        base_batch_sizes = {
            'create_measures': 10,
            'update_measures': 10,
            'delete_measures': 20,
            'analyze_measures': 5,
            'export_tables': 5
        }

        base_size = base_batch_sizes.get(operation_type, 10)

        # Adjust based on total items
        if total_items:
            if total_items < 5:
                return total_items  # Process all at once
            elif total_items < 20:
                return 5  # Small batches
            elif total_items < 100:
                return 10  # Medium batches
            else:
                return 20  # Larger batches for many items

        return base_size

    def get_default_max_rows(
        self,
        purpose: str,
        table_name: Optional[str] = None
    ) -> int:
        """
        Get smart default for max_rows parameter

        Args:
            purpose: Purpose of data retrieval ('preview', 'analysis', 'distribution', etc.)
            table_name: Optional table name to check size

        Returns:
            Recommended max_rows value
        """
        purpose_defaults = {
            'preview': 50,
            'analysis': 1000,
            'distribution': 10000,
            'sample': 100,
            'validation': 500
        }

        base_rows = purpose_defaults.get(purpose, 100)

        # Adjust based on table size if available
        if table_name:
            row_count = self._get_table_row_count(table_name)

            if row_count < base_rows:
                return row_count  # Return all rows if table is small
            elif row_count > 10000000:
                # Very large table - reduce sample
                return min(base_rows, 100)

        return base_rows

    def get_default_dependency_depth(
        self,
        analysis_type: str,
        known_complexity: Optional[int] = None
    ) -> int:
        """
        Get smart default for dependency depth parameter

        Args:
            analysis_type: Type of analysis ('measure', 'impact', 'full')
            known_complexity: Known complexity score (0-100)

        Returns:
            Recommended dependency depth
        """
        if analysis_type == 'quick':
            return 3  # Quick check
        elif analysis_type == 'measure':
            return 5  # Standard measure analysis
        elif analysis_type == 'impact':
            return 10  # Deep impact analysis
        elif analysis_type == 'full':
            return 20  # Comprehensive analysis
        else:
            # Adjust based on complexity
            if known_complexity:
                if known_complexity > 70:
                    return 5  # High complexity - limit depth
                elif known_complexity < 30:
                    return 10  # Low complexity - deeper search
            return 5  # Safe default

    def get_default_analysis_mode(
        self,
        context: str,
        user_intent: Optional[str] = None
    ) -> str:
        """
        Get smart default for DAX analysis mode

        Args:
            context: Context of analysis ('review', 'optimize', 'debug', 'learn')
            user_intent: Optional user intent

        Returns:
            Recommended analysis mode
        """
        if 'optimize' in context.lower() or 'performance' in context.lower():
            return 'optimize'
        elif 'learn' in context.lower() or 'explain' in context.lower():
            return 'explain'
        elif 'debug' in context.lower() or 'error' in context.lower():
            return 'debug'
        elif 'report' in context.lower() or 'comprehensive' in context.lower():
            return 'report'
        else:
            return 'report'  # Safe default - comprehensive analysis

    def get_default_export_format(
        self,
        export_type: str,
        size_estimate: Optional[str] = None
    ) -> str:
        """
        Get smart default for export format

        Args:
            export_type: Type of export ('model', 'documentation', 'analysis')
            size_estimate: Size estimate ('small', 'medium', 'large')

        Returns:
            Recommended export format
        """
        if export_type == 'model':
            # Model export formats
            if size_estimate == 'large':
                return 'tmsl'  # More efficient for large models
            else:
                return 'tmdl'  # More readable

        elif export_type == 'documentation':
            return 'markdown'  # Human-readable

        elif export_type == 'analysis':
            return 'json'  # Structured data

        elif export_type == 'data':
            if size_estimate == 'large':
                return 'csv'  # More efficient
            else:
                return 'json'  # More structured

        return 'json'  # Safe default

    def should_use_caching(
        self,
        operation_type: str,
        frequency: Optional[str] = None
    ) -> bool:
        """
        Determine if caching should be enabled for operation

        Args:
            operation_type: Type of operation
            frequency: Expected frequency ('once', 'occasional', 'frequent')

        Returns:
            True if caching recommended
        """
        # Operations that benefit from caching
        cache_friendly = [
            'list_tables',
            'list_measures',
            'list_relationships',
            'describe_table',
            'get_measure_details'
        ]

        if operation_type in cache_friendly:
            if frequency in ['frequent', 'occasional', None]:
                return True

        return False

    def get_smart_scope(
        self,
        intent: str,
        time_constraint: Optional[str] = None
    ) -> str:
        """
        Get smart scope for analysis based on intent

        Args:
            intent: Analysis intent ('quick_check', 'thorough', 'specific')
            time_constraint: Time constraint ('fast', 'normal', 'no_limit')

        Returns:
            Recommended scope
        """
        if intent == 'quick_check' or time_constraint == 'fast':
            return 'performance'  # Focus on performance issues

        elif intent == 'thorough' and time_constraint != 'fast':
            return 'all'  # Comprehensive analysis

        elif intent == 'specific':
            return 'integrity'  # Focus on data integrity

        else:
            return 'balanced'  # Balanced analysis

    def _get_table_row_count(self, table_name: str) -> int:
        """
        Get table row count (with caching)

        Args:
            table_name: Table name

        Returns:
            Row count, or 0 if unable to determine
        """
        # Check cache first
        if table_name in self._table_size_cache:
            return self._table_size_cache[table_name]

        # Try to get from connection state
        if self.connection_state:
            try:
                # This would require connection state to have a method to get table info
                # For now, return a default
                pass
            except Exception:
                pass

        # Default assumption for unknown tables
        return 100000  # Assume medium-sized table

    def _get_model_complexity(self) -> str:
        """
        Get model complexity estimate

        Returns:
            'small', 'medium', or 'large'
        """
        if self._model_complexity_cache:
            return self._model_complexity_cache

        # Try to determine from connection state
        if self.connection_state:
            try:
                # This would require connection state to have model info
                # For now, return default
                pass
            except Exception:
                pass

        return 'medium'  # Safe default

    def get_default_parameters(
        self,
        tool_name: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get all recommended default parameters for a tool

        Args:
            tool_name: Name of the tool
            context: Optional context information

        Returns:
            Dictionary of recommended parameters
        """
        context = context or {}
        defaults = {}

        # Tool-specific defaults
        if tool_name == 'preview_table_data':
            defaults['max_rows'] = self.get_default_max_rows('preview', context.get('table'))

        elif tool_name == 'comprehensive_analysis':
            defaults['depth'] = self.get_default_analysis_depth()
            defaults['scope'] = self.get_smart_scope('thorough')

        elif tool_name == 'analyze_measure_dependencies':
            defaults['depth'] = self.get_default_dependency_depth('measure')

        elif tool_name == 'get_measure_impact':
            defaults['depth'] = self.get_default_dependency_depth('impact')

        elif tool_name == 'dax_intelligence':
            defaults['analysis_mode'] = self.get_default_analysis_mode('review')

        elif tool_name == 'run_dax':
            defaults['timeout'] = self.get_default_timeout('query')

        elif tool_name == 'bulk_create_measures':
            defaults['batch_size'] = self.get_default_batch_size('create_measures')

        return defaults

    def explain_default(self, parameter: str, value: Any, reason: str = "") -> Dict[str, Any]:
        """
        Explain why a default was chosen

        Args:
            parameter: Parameter name
            value: Default value
            reason: Optional reason

        Returns:
            Explanation dictionary
        """
        return {
            'parameter': parameter,
            'default_value': value,
            'reason': reason or f"Smart default based on best practices",
            'can_override': True
        }


# Global instance for easy access
_smart_defaults_instance: Optional[SmartDefaults] = None


def get_smart_defaults(connection_state=None) -> SmartDefaults:
    """Get or create global SmartDefaults instance"""
    global _smart_defaults_instance

    if _smart_defaults_instance is None:
        _smart_defaults_instance = SmartDefaults(connection_state)

    return _smart_defaults_instance


def apply_smart_defaults(
    tool_name: str,
    provided_params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Apply smart defaults to tool parameters

    Args:
        tool_name: Name of the tool
        provided_params: Parameters provided by user
        context: Optional context

    Returns:
        Parameters with smart defaults applied
    """
    defaults = get_smart_defaults()
    default_params = defaults.get_default_parameters(tool_name, context)

    # Merge: provided params override defaults
    final_params = {**default_params, **provided_params}

    logger.debug(f"Applied smart defaults for {tool_name}: {default_params}")

    return final_params
