"""
Server Handlers Package — 22 tools registered (v13 consolidation)

Tool inventory:
  01_Connection, 02_Model_Operations, 02_TMDL_Operations, 03_Batch_Operations,
  04_Run_DAX, 04_Query_Operations, 05_DAX_Intelligence, 05_Column_Usage_Mapping,
  06_Analysis_Operations, 07_Report_Operations, 07_PBIP_Operations,
  07_Page_Operations, 07_Visual_Operations, 07_Bookmark_Operations,
  07_Theme_Operations, 08_Documentation_Word, 09_Debug_Operations,
  09_Validate, 09_Profile, 09_Document, 10_Show_User_Guide,
  11_PBIP_Authoring, SVG_Visual_Operations
"""
from server.handlers.connection_handler import register_connection_handlers
from server.handlers.model_operations_handler import register_model_operations_handler
from server.handlers.tmdl_handler import register_tmdl_operations_handler
from server.handlers.batch_operations_handler import register_batch_operations_handler
from server.handlers.query_handler import register_query_handlers
from server.handlers.dax_context_handler import register_dax_handlers
from server.handlers.column_usage_handler import register_column_usage_handler
from server.handlers.analysis_handler import register_analysis_handlers
from server.handlers.report_operations_handler import register_report_operations_handler
from server.handlers.pbip_operations_handler import register_pbip_operations_handler
from server.handlers.page_operations_handler import register_page_operations_handler
from server.handlers.visual_operations_handler import register_visual_operations_handler
from server.handlers.bookmark_operations_handler import register_bookmark_operations_handler
from server.handlers.theme_operations_handler import register_theme_operations_handler
from server.handlers.documentation_handler import register_documentation_handlers
from server.handlers.debug_handler import register_debug_handlers
from server.handlers.user_guide_handler import register_user_guide_handlers
from server.handlers.authoring_handler import register_authoring_handler
from server.handlers.svg_handler import register_svg_operations_handler


def register_all_handlers(registry):
    """Register all handlers with the registry — 22 tools total"""
    register_connection_handlers(registry)         # 01_Connection
    register_model_operations_handler(registry)    # 02_Model_Operations
    register_tmdl_operations_handler(registry)     # 02_TMDL_Operations
    register_batch_operations_handler(registry)    # 03_Batch_Operations
    register_query_handlers(registry)              # 04_Run_DAX + 04_Query_Operations
    register_dax_handlers(registry)                # 05_DAX_Intelligence
    register_column_usage_handler(registry)        # 05_Column_Usage_Mapping
    register_analysis_handlers(registry)           # 06_Analysis_Operations
    register_report_operations_handler(registry)   # 07_Report_Operations
    register_pbip_operations_handler(registry)     # 07_PBIP_Operations
    register_page_operations_handler(registry)     # 07_Page_Operations
    register_visual_operations_handler(registry)   # 07_Visual_Operations
    register_bookmark_operations_handler(registry) # 07_Bookmark_Operations
    register_theme_operations_handler(registry)    # 07_Theme_Operations
    register_documentation_handlers(registry)      # 08_Documentation_Word
    register_debug_handlers(registry)              # 09_Debug_Operations + 09_Validate + 09_Profile + 09_Document
    register_user_guide_handlers(registry)         # 10_Show_User_Guide
    register_authoring_handler(registry)           # 11_PBIP_Authoring
    register_svg_operations_handler(registry)      # SVG_Visual_Operations


__all__ = ['register_all_handlers']
