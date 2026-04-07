"""
Documentation Handler
Handles Word documentation generation and updates via unified tool.
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)


def handle_documentation_word(args: Dict[str, Any]) -> Dict[str, Any]:
    """Unified Word documentation: generate or update."""
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    agent_policy = connection_state.agent_policy
    if not agent_policy:
        return ErrorHandler.handle_manager_unavailable('agent_policy')

    mode = args.get('mode', 'generate')
    output_path = args.get('output_path')

    if mode == 'update':
        input_path = args.get('input_path')
        if not input_path:
            return {
                'success': False,
                'error': "input_path is required for mode='update'"
            }
        return agent_policy.documentation_orch.update_word_documentation(
            connection_state, input_path, output_path
        )

    # Default: generate
    return agent_policy.documentation_orch.generate_word_documentation(
        connection_state, output_path
    )


def register_documentation_handlers(registry):
    """Register documentation handler"""
    tool = ToolDefinition(
        name="08_Documentation_Word",
        description="Generate or update Word documentation report.",
        handler=handle_documentation_word,
        input_schema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["generate", "update"],
                },
                "output_path": {
                    "type": "string",
                    "description": "Output Word file path",
                },
                "input_path": {
                    "type": "string",
                    "description": "Existing doc path (required for update)",
                },
            },
            "required": [],
        },
        category="docs",
        sort_order=80,
        annotations={"readOnlyHint": False},
    )

    registry.register(tool)
    logger.info("Registered 1 documentation handler")
