"""
Server Handlers Package
Individual handler modules for different tool categories
"""
from server.handlers.connection_handler import register_connection_handlers
from server.handlers.query_handler import register_query_handlers
from server.handlers.analysis_handler import register_analysis_handlers
from server.handlers.column_usage_handler import register_column_usage_handler
from server.handlers.documentation_handler import register_documentation_handlers
from server.handlers.pbip_operations_handler import register_pbip_operations_handler
from server.handlers.tmdl_handler import register_tmdl_operations_handler
from server.handlers.dax_context_handler import register_dax_handlers
from server.handlers.user_guide_handler import register_user_guide_handlers
from server.handlers.debug_handler import register_debug_handlers

# Phase 1 Consolidated Operations (Tool Consolidation Plan)
from server.handlers.table_operations_handler import register_table_operations_handler
from server.handlers.column_operations_handler import register_column_operations_handler
from server.handlers.measure_operations_handler import register_measure_operations_handler

# Phase 2 Extended CRUD Operations
from server.handlers.relationship_operations_handler import register_relationship_operations_handler
from server.handlers.calculation_group_operations_handler import register_calculation_group_operations_handler

# Phase 3 Batch Operations & Transactions
from server.handlers.batch_operations_handler import register_batch_operations_handler
from server.handlers.transaction_management_handler import register_transaction_management_handler

# SVG Visual Generation
from server.handlers.svg_handler import register_svg_operations_handler

# PBIP Prototyping (kept from authoring — prototype is a distinct workflow)
from server.handlers.prototype_handler import register_prototype_handler
from server.handlers.authoring_handler import register_authoring_handler

# Consolidated PBIP/Report tools (v12 consolidation)
from server.handlers.report_operations_handler import register_report_operations_handler
from server.handlers.page_operations_handler import register_page_operations_handler
from server.handlers.visual_operations_handler import (
    register_visual_operations_handler,
    register_visual_sync_handler,
)
from server.handlers.bookmark_operations_handler import register_bookmark_operations_handler
from server.handlers.theme_operations_handler import register_theme_operations_handler

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

    # Phase 3: Batch operations & transactions
    register_batch_operations_handler(registry)
    register_transaction_management_handler(registry)

    # Query & search
    register_query_handlers(registry)
    register_analysis_handlers(registry)
    register_column_usage_handler(registry)
    register_documentation_handlers(registry)
    register_tmdl_operations_handler(registry)
    register_dax_handlers(registry)
    register_user_guide_handlers(registry)
    register_debug_handlers(registry)

    # PBIP model analysis
    register_pbip_operations_handler(registry)

    # Consolidated PBIP/Report tools (v12)
    register_report_operations_handler(registry)
    register_page_operations_handler(registry)
    register_visual_operations_handler(registry)
    register_visual_sync_handler(registry)
    register_bookmark_operations_handler(registry)
    register_theme_operations_handler(registry)

    # SVG Visual Generation
    register_svg_operations_handler(registry)

    # PBIP Prototyping
    register_prototype_handler(registry)

    # PBIP Authoring (page/visual cloning, creation, deletion, templates)
    register_authoring_handler(registry)

__all__ = [
    'register_all_handlers',
]
