"""
Server Handlers Package
Individual handler modules for different tool categories

Token Optimization: Discovery handler enables progressive tool loading.
"""
from server.handlers.connection_handler import register_connection_handlers
from server.handlers.metadata_handler import register_metadata_handlers
from server.handlers.discovery_handler import register_discovery_handler
from server.handlers.query_handler import register_query_handlers
from server.handlers.analysis_handler import register_analysis_handlers
from server.handlers.dependencies_handler import register_dependencies_handlers
from server.handlers.column_usage_handler import register_column_usage_handler, register_export_dax_measures_handler
from server.handlers.export_handler import register_export_handlers
from server.handlers.documentation_handler import register_documentation_handlers
from server.handlers.comparison_handler import register_comparison_handlers
from server.handlers.pbip_handler import register_pbip_handlers
from server.handlers.slicer_operations_handler import register_slicer_operations_handler
from server.handlers.visual_operations_handler import register_visual_operations_handler
from server.handlers.report_info_handler import register_report_info_handler
from server.handlers.tmdl_handler import register_tmdl_operations_handler
from server.handlers.dax_context_handler import register_dax_handlers
from server.handlers.user_guide_handler import register_user_guide_handlers
from server.handlers.hybrid_analysis_handler import register_hybrid_analysis_handlers
from server.handlers.aggregation_handler import register_aggregation_handler
from server.handlers.bookmark_theme_handler import register_bookmark_theme_handlers
from server.handlers.debug_handler import register_debug_handlers
# Workflow handlers are internalized and not registered as public tools

# Phase 1 Consolidated Operations (Tool Consolidation Plan)
from server.handlers.table_operations_handler import register_table_operations_handler
from server.handlers.column_operations_handler import register_column_operations_handler
from server.handlers.measure_operations_handler import register_measure_operations_handler

# Phase 2 Extended CRUD Operations
from server.handlers.relationship_operations_handler import register_relationship_operations_handler
from server.handlers.calculation_group_operations_handler import register_calculation_group_operations_handler
from server.handlers.role_operations_handler import register_role_operations_handler

# Phase 3 Batch Operations & Transactions
from server.handlers.batch_operations_handler import register_batch_operations_handler
from server.handlers.transaction_management_handler import register_transaction_management_handler

# SVG Visual Generation
from server.handlers.svg_handler import register_svg_operations_handler

def register_all_handlers(registry):
    """Register all handlers with the registry"""
    # Register discovery handler first (meta-tool for token optimization)
    register_discovery_handler(registry)

    # Register all proper handlers (no more bridge!)
    register_connection_handlers(registry)

    # Phase 1: Consolidated operations (replaces parts of metadata handlers)
    register_table_operations_handler(registry)
    register_column_operations_handler(registry)
    register_measure_operations_handler(registry)

    # Phase 2: Extended CRUD operations
    register_relationship_operations_handler(registry)
    register_calculation_group_operations_handler(registry)
    register_role_operations_handler(registry)

    # Phase 3: Batch operations & transactions
    register_batch_operations_handler(registry)
    register_transaction_management_handler(registry)

    register_metadata_handlers(registry)
    register_query_handlers(registry)
    register_analysis_handlers(registry)
    register_dependencies_handlers(registry)
    register_column_usage_handler(registry)
    register_export_dax_measures_handler(registry)
    register_export_handlers(registry)
    register_documentation_handlers(registry)
    register_comparison_handlers(registry)
    register_pbip_handlers(registry)
    register_slicer_operations_handler(registry)
    register_visual_operations_handler(registry)
    register_report_info_handler(registry)
    register_tmdl_operations_handler(registry)
    register_dax_handlers(registry)
    register_user_guide_handlers(registry)
    register_hybrid_analysis_handlers(registry)
    register_aggregation_handler(registry)
    register_bookmark_theme_handlers(registry)
    register_debug_handlers(registry)
    # Workflow handlers are internalized and not registered as public tools

    # SVG Visual Generation
    register_svg_operations_handler(registry)

__all__ = [
    'register_all_handlers',
]
