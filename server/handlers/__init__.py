"""
Server Handlers Package
Individual handler modules for different tool categories
"""
from server.handlers.connection_handler import register_connection_handlers
# metadata_handler: merged into query_handler (04_Query_Operations + 04_Search_String)
from server.handlers.query_handler import register_query_handlers
from server.handlers.query_trace_handler import register_query_trace_handler
from server.handlers.analysis_handler import register_analysis_handlers
from server.handlers.dependencies_handler import register_dependencies_handlers
from server.handlers.column_usage_handler import register_column_usage_handler
# export_dax_measures: merged into dependencies_handler (05_DAX_Operations.export)
from server.handlers.documentation_handler import register_documentation_handlers
# comparison_handler: merged into analysis_handler (06_Analysis_Operations.compare)
from server.handlers.pbip_operations_handler import (
    register_pbip_model_analysis_handler,
    register_pbip_query_handler,
)
from server.handlers.slicer_operations_handler import register_slicer_operations_handler
from server.handlers.visual_operations_handler import (
    register_visual_operations_handler,
    register_visual_sync_handler,
)
from server.handlers.report_info_handler import register_report_info_handler
from server.handlers.tmdl_handler import register_tmdl_operations_handler
from server.handlers.dax_context_handler import register_dax_handlers
from server.handlers.user_guide_handler import register_user_guide_handlers
from server.handlers.hybrid_analysis_handler import register_hybrid_analysis_handlers
from server.handlers.aggregation_handler import register_aggregation_handler
from server.handlers.bookmark_theme_handler import register_bookmark_theme_handlers
from server.handlers.debug_handler import register_debug_handlers

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

    # metadata_handlers removed - merged into query_handler
    register_query_handlers(registry)
    register_query_trace_handler(registry)
    register_analysis_handlers(registry)
    register_dependencies_handlers(registry)
    register_column_usage_handler(registry)
    # export_dax_measures removed - merged into dependencies_handler
    register_documentation_handlers(registry)
    # comparison_handlers removed - merged into analysis_handler
    register_pbip_model_analysis_handler(registry)
    register_pbip_query_handler(registry)
    register_slicer_operations_handler(registry)
    register_visual_operations_handler(registry)
    register_visual_sync_handler(registry)
    register_report_info_handler(registry)
    register_tmdl_operations_handler(registry)
    register_dax_handlers(registry)
    register_user_guide_handlers(registry)
    register_hybrid_analysis_handlers(registry)
    register_aggregation_handler(registry)
    register_bookmark_theme_handlers(registry)
    register_debug_handlers(registry)

    # SVG Visual Generation
    register_svg_operations_handler(registry)

__all__ = [
    'register_all_handlers',
]
