"""
DAX Context Handler
Handles DAX context analysis and debugging operations with integrated validation
"""
from typing import Dict, Any, Tuple, Optional
import logging
from server.registry import ToolDefinition
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)

# Try to load AMO for TOM access
AMO_AVAILABLE = False
AMOServer = None
AdomdCommand = None

try:
    from core.infrastructure.dll_paths import (
        load_amo_assemblies,
        load_adomd_assembly,
    )

    load_amo_assemblies()
    load_adomd_assembly()

    from Microsoft.AnalysisServices.Tabular import Server as AMOServer
    from Microsoft.AnalysisServices.AdomdClient import AdomdCommand
    AMO_AVAILABLE = True
    logger.debug("AMO available for DAX context handler")

except Exception as e:
    logger.debug(f"AMO not available for DAX context handler: {e}")


def _get_server_db_model(conn_state):
    """
    Get AMO server, database, and model objects.

    Args:
        conn_state: ConnectionState instance

    Returns:
        Tuple of (server, database, model) or (None, None, None) if unavailable
    """
    if not AMO_AVAILABLE:
        logger.debug("AMO not available - cannot access model")
        return None, None, None

    if not conn_state.connection_manager:
        logger.debug("No connection manager - cannot access model")
        return None, None, None

    connection = conn_state.connection_manager.get_connection()
    if not connection:
        logger.debug("No active connection - cannot access model")
        return None, None, None

    server = AMOServer()
    try:
        server.Connect(connection.ConnectionString)

        # Get database name
        db_name = None
        try:
            db_query = "SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS"
            cmd = AdomdCommand(db_query, connection)
            reader = cmd.ExecuteReader()
            if reader.Read():
                db_name = str(reader.GetValue(0))
            reader.Close()
        except Exception:
            db_name = None

        if not db_name and server.Databases.Count > 0:
            db_name = server.Databases[0].Name

        if not db_name:
            server.Disconnect()
            return None, None, None

        db = server.Databases.GetByName(db_name)
        model = db.Model

        return server, db, model

    except Exception as e:
        try:
            server.Disconnect()
        except Exception:
            pass
        logger.error(f"Error connecting to AMO server: {e}")
        return None, None, None


def _cleanup_amo_connection(server):
    """
    Safely disconnect and cleanup AMO server connection.

    Args:
        server: AMO Server instance
    """
    if server:
        try:
            server.Disconnect()
        except Exception:
            pass


def _validate_dax_syntax(expression: str) -> Tuple[bool, str]:
    """
    Validate DAX syntax before analysis

    FIXED in v6.0.5:
    1. Improved connection error message with actionable guidance
    2. Fixed table expression detection logic that incorrectly classified measure definitions
       - Old logic: Checked if keywords like FILTER/VALUES existed ANYWHERE in expression
       - New logic: Checks if expression STARTS WITH a table-returning function at ROOT level
       - Example: CALCULATE(SUM(...), FILTER(...)) is now correctly identified as scalar (measure)
       - Example: FILTER(Table, ...) is correctly identified as table expression

    Args:
        expression: DAX expression to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not connection_state.is_connected():
        return False, "Not connected to Power BI instance. Please connect using tool '01_Connect_To_Instance' first."

    qe = connection_state.query_executor
    if not qe:
        return False, "Query executor not available"

    try:
        # Prepare query for validation
        test_query = expression.strip()

        # If already an EVALUATE query, use as-is
        if test_query.upper().startswith('EVALUATE'):
            pass
        else:
            # IMPROVED: Check if the expression starts with a table-returning function at the ROOT level
            # This fixes the issue where measure definitions containing FILTER/VALUES were misclassified

            # Extract first function name (before first opening parenthesis)
            first_token = test_query.lstrip().split('(')[0].upper().strip() if '(' in test_query else test_query.upper().strip()

            # Table-returning functions that are ONLY used at root level (definite table expressions)
            root_table_functions = [
                'SELECTCOLUMNS', 'ADDCOLUMNS', 'SUMMARIZE', 'SUMMARIZECOLUMNS',
                'TOPN', 'SAMPLE', 'ROW', 'DATATABLE', 'CROSSJOIN', 'UNION',
                'INTERSECT', 'EXCEPT', 'GENERATE', 'GENERATEALL', 'GENERATESERIES'
            ]

            # Functions that can appear at root OR nested (ambiguous - need more context)
            ambiguous_functions = ['FILTER', 'VALUES', 'ALL', 'ALLSELECTED', 'DISTINCT', 'CALCULATETABLE']

            # Check if expression definitely starts with a table function
            is_definitely_table = any(first_token == func for func in root_table_functions)

            # Check if it might be a table expression (starts with ambiguous function)
            is_possibly_table = any(first_token == func for func in ambiguous_functions)

            # Aggregation functions indicate this is a measure (scalar expression)
            # Remove spaces to handle cases like "CALCULATE (" or "SUM  ("
            normalized_query = test_query.upper().replace(' ', '')
            has_aggregation = any(agg in normalized_query for agg in [
                'CALCULATE(', 'SUM(', 'SUMX(', 'AVERAGE(', 'AVERAGEX(',
                'COUNT(', 'COUNTX(', 'COUNTROWS(', 'MIN(', 'MINX(',
                'MAX(', 'MAXX(', 'DIVIDE('
            ])

            # Decision logic:
            # 1. If starts with definite table function -> table expression
            # 2. If starts with ambiguous function BUT has aggregation -> scalar (measure)
            # 3. If starts with ambiguous function AND no aggregation -> table expression
            # 4. Default -> scalar (measure definition)

            if is_definitely_table:
                # Definite table expression
                test_query = f'EVALUATE {test_query}'
            elif is_possibly_table and not has_aggregation:
                # Ambiguous function at root without aggregation -> likely table expression
                test_query = f'EVALUATE {test_query}'
            else:
                # Scalar expression (measure definition) - wrap in ROW()
                test_query = f'EVALUATE ROW("Result", {test_query})'

        # Use query executor to validate
        result = qe.validate_and_execute_dax(test_query, top_n=0)

        if result.get('success'):
            return True, ""
        else:
            error_msg = result.get('error', 'Unknown validation error')
            # Clean up error message if it mentions ROW wrapper (user didn't write ROW)
            if 'ROW' in error_msg and 'ROW' not in expression.upper():
                # Try to remove ROW wrapper artifacts from error message
                error_msg = error_msg.replace('ROW("Result",', '').replace('ROW("Result", ', '')
            return False, error_msg
    except Exception as e:
        return False, str(e)

def handle_analyze_dax_context(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze DAX context transitions with integrated syntax validation

    This tool combines:
    1. DAX syntax validation (former tool 03)
    2. Context transition analysis

    Returns validation status + context analysis
    """
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    expression = args.get('expression')
    skip_validation = args.get('skip_validation', False)

    if not expression:
        return {
            'success': False,
            'error': 'expression parameter is required'
        }

    # Step 1: Validate DAX syntax (unless explicitly skipped)
    validation_result = {'valid': True, 'message': 'Validation skipped'}
    if not skip_validation:
        is_valid, error_msg = _validate_dax_syntax(expression)
        validation_result = {
            'valid': is_valid,
            'message': 'DAX syntax is valid' if is_valid else f'DAX syntax error: {error_msg}'
        }

        if not is_valid:
            return {
                'success': True,
                'validation': validation_result,
                'analysis': None,
                'note': 'Analysis skipped due to syntax errors'
            }

    # Step 2: Perform context analysis
    try:
        from core.dax import DaxContextAnalyzer
        analyzer = DaxContextAnalyzer()

        result = analyzer.analyze_context_transitions(expression)

        return {
            'success': True,
            'validation': validation_result,
            'analysis': result.to_dict() if hasattr(result, 'to_dict') else result
        }

    except ImportError as ie:
        logger.error(f"Import error: {ie}", exc_info=True)
        return {
            'success': False,
            'validation': validation_result,
            'error': 'DaxContextAnalyzer not available. This is an internal error.',
            'error_type': 'import_error'
        }
    except Exception as e:
        logger.error(f"Error analyzing DAX context: {e}", exc_info=True)
        return {
            'success': False,
            'validation': validation_result,
            'error': f'Error analyzing DAX context: {str(e)}'
        }

def handle_debug_dax_context(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Debug DAX step-by-step with integrated syntax validation

    This tool combines:
    1. DAX syntax validation (former tool 03)
    2. Step-by-step DAX debugging with context transitions

    Returns validation status + debugging steps
    """
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    expression = args.get('expression')
    breakpoints = args.get('breakpoints')
    include_profiling = args.get('include_profiling', True)
    include_optimization = args.get('include_optimization', True)
    output_format = args.get('format', 'friendly')  # 'friendly', 'steps', or 'report'
    skip_validation = args.get('skip_validation', False)

    if not expression:
        return {
            'success': False,
            'error': 'expression parameter is required'
        }

    # Step 1: Validate DAX syntax (unless explicitly skipped)
    validation_result = {'valid': True, 'message': 'Validation skipped'}
    if not skip_validation:
        is_valid, error_msg = _validate_dax_syntax(expression)
        validation_result = {
            'valid': is_valid,
            'message': 'DAX syntax is valid' if is_valid else f'DAX syntax error: {error_msg}'
        }

        if not is_valid:
            return {
                'success': True,
                'validation': validation_result,
                'debug_steps': None,
                'note': 'Debugging skipped due to syntax errors. Fix the syntax errors first.'
            }

    # Step 2: Perform debugging
    try:
        from core.dax import DaxContextDebugger
        debugger = DaxContextDebugger()

        if output_format == 'report':
            # Generate full debug report
            result = debugger.generate_debug_report(
                expression,
                include_profiling=include_profiling,
                include_optimization=include_optimization
            )
            return {
                'success': True,
                'validation': validation_result,
                'report': result
            }
        else:
            # Step-through debugging
            steps = debugger.step_through(
                dax_expression=expression,
                breakpoints=breakpoints
            )

            if not steps:
                return {
                    'success': True,
                    'validation': validation_result,
                    'message': '✅ No context transitions detected in this DAX expression.',
                    'explanation': 'This is a simple expression without CALCULATE, iterators, or measure references that would cause context transitions.',
                    'total_steps': 0
                }

            # Format output based on requested format
            if output_format == 'friendly':
                formatted_output = _format_debug_steps_friendly(expression, steps)
                # Add validation header
                if validation_result['valid']:
                    validation_header = "✅ DAX SYNTAX VALIDATION: PASSED\n\n"
                    formatted_output = validation_header + formatted_output

                return {
                    'success': True,
                    'validation': validation_result,
                    'formatted_output': formatted_output,
                    'total_steps': len(steps)
                }
            else:
                # 'steps' format - raw data
                steps_dict = [
                    {
                        'step_number': step.step_number,
                        'code_fragment': step.code_fragment,
                        'filter_context': step.filter_context,
                        'row_context': step.row_context,
                        'intermediate_result': step.intermediate_result,
                        'explanation': step.explanation,
                        'execution_time_ms': step.execution_time_ms
                    }
                    for step in steps
                ]

                return {
                    'success': True,
                    'validation': validation_result,
                    'debug_steps': steps_dict,
                    'total_steps': len(steps_dict)
                }

    except ImportError as ie:
        logger.error(f"Import error: {ie}", exc_info=True)
        return {
            'success': False,
            'validation': validation_result,
            'error': 'DaxContextDebugger not available. This is an internal error.',
            'error_type': 'import_error'
        }
    except Exception as e:
        logger.error(f"Error debugging DAX: {e}", exc_info=True)
        return {
            'success': False,
            'validation': validation_result,
            'error': f'Error debugging DAX: {str(e)}'
        }


def _format_debug_steps_friendly(expression: str, steps) -> str:
    """Format debug steps in a user-friendly way"""
    lines = []

    lines.append("=" * 80)
    lines.append("🔍 DAX CONTEXT DEBUGGER - STEP-BY-STEP EXECUTION ANALYSIS")
    lines.append("=" * 80)
    lines.append("")

    lines.append("📝 Your DAX Expression:")
    lines.append("-" * 80)
    lines.append(expression)
    lines.append("")

    lines.append("=" * 80)
    lines.append(f"🎯 Found {len(steps)} Context Transitions")
    lines.append("=" * 80)
    lines.append("")

    lines.append("💡 What are Context Transitions?")
    lines.append("   Context transitions occur when DAX switches between filter context and row context.")
    lines.append("   Understanding these is crucial for writing efficient DAX and avoiding common pitfalls.")
    lines.append("")

    for step in steps:
        lines.append("-" * 80)
        lines.append(f"Step {step.step_number} of {len(steps)}")
        lines.append("-" * 80)
        lines.append("")

        # Show code fragment with pointer
        lines.append("📍 Execution Point:")
        lines.append(f"   {step.code_fragment}")
        lines.append("   ⬆️  The ▶ arrow shows exactly where DAX is evaluating")
        lines.append("")

        # Context information
        lines.append("🔄 Context Information:")

        if step.row_context:
            lines.append(f"   • Row Context: {step.row_context.get('type', 'Active')}")
            if 'function' in step.row_context:
                lines.append(f"     Function: {step.row_context['function']}")
            lines.append("     ℹ️  Row context = iterating over rows of a table")
        else:
            lines.append("   • Row Context: None")
            lines.append("     ℹ️  No row iteration at this point")

        if step.filter_context:
            lines.append(f"   • Filter Context: {len(step.filter_context)} active filters")
            for table, filters in step.filter_context.items():
                lines.append(f"     - {table}: {filters}")
        else:
            lines.append("   • Filter Context: Inherited from visual/slicer")
            lines.append("     ℹ️  Using the filter context from your report")

        lines.append("")

        # Explanation
        lines.append("📖 What's Happening:")
        # Wrap explanation text
        explanation_lines = _wrap_text(step.explanation, width=76, indent=3)
        lines.extend(explanation_lines)
        lines.append("")

        # Performance hint
        if step.execution_time_ms:
            lines.append(f"⏱️  Execution Time: {step.execution_time_ms:.2f}ms")
            lines.append("")

        # Visual separation between steps
        lines.append("")

    lines.append("=" * 80)
    lines.append("✅ ANALYSIS COMPLETE")
    lines.append("=" * 80)
    lines.append("")
    lines.append("💡 Key Takeaways:")
    lines.append("   • Context transitions can impact performance - minimize unnecessary transitions")
    lines.append("   • Measure references inside iterators cause row-by-row context transitions")
    lines.append("   • CALCULATE modifies filter context and transitions from row to filter context")
    lines.append("   • Use variables (VAR) to cache values and reduce repeated transitions")
    lines.append("")
    lines.append("📚 Need more details? Use format='report' for optimization suggestions!")
    lines.append("")

    return "\n".join(lines)


def _wrap_text(text: str, width: int = 80, indent: int = 0) -> list:
    """Wrap text to specified width with indentation"""
    import textwrap

    wrapper = textwrap.TextWrapper(
        width=width,
        initial_indent=" " * indent,
        subsequent_indent=" " * indent,
        break_long_words=False,
        break_on_hyphens=False
    )

    return wrapper.wrap(text)

def handle_dax_intelligence(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Unified DAX Intelligence Tool

    Combines validation, analysis, and debugging into a single intelligent tool.

    Modes:
    - 'all' (DEFAULT): Runs ALL analysis modes - analyze + debug + report
    - 'analyze': Context transition analysis with anti-patterns
    - 'debug': Step-by-step debugging with friendly/steps output
    - 'report': Comprehensive report with optimization + profiling

    Smart measure detection: Automatically fetches measure expressions if a measure name is provided.
    Auto-skips validation for auto-fetched measures (already in model, must be valid).
    Online research enabled for DAX optimization articles and recommendations.
    """
    import re  # For fuzzy measure name matching
    from difflib import SequenceMatcher  # For proper fuzzy matching scores

    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    expression = args.get('expression')
    analysis_mode = args.get('analysis_mode', 'all')  # Default to 'all' mode (analyze + debug + report)
    skip_validation = args.get('skip_validation', False)

    if not expression:
        return {
            'success': False,
            'error': 'expression parameter is required'
        }

    # Smart measure detection: Check if expression looks like a measure name rather than DAX code
    # Measure names are typically short and don't contain DAX keywords/operators
    original_expression = expression
    measure_name = None
    measure_table = None
    warnings = []

    dax_keywords = [
        'CALCULATE', 'FILTER', 'SUM', 'SUMX', 'AVERAGE', 'COUNT', 'COUNTROWS',
        'IF', 'SWITCH', 'VAR', 'RETURN', 'ALL', 'VALUES', 'DISTINCT', 'RELATED',
        'SELECTEDVALUE', 'DIVIDE', 'MAX', 'MIN', 'EVALUATE', '=', '+', '-', '*', '/',
        '[', '(', ')', '{', '}', '&&', '||', '<', '>', '<=', '>=', '<>'
    ]

    # Check if this looks like a simple measure name (not a DAX expression)
    is_likely_measure_name = (
        len(expression) < 150 and  # Measure names are typically short
        not any(keyword in expression.upper() for keyword in dax_keywords[:15]) and  # No major DAX keywords
        expression.count('[') == 0 and  # No column references
        expression.count('(') == 0  # No function calls
    )

    if is_likely_measure_name:
        # Try to fetch the measure expression automatically
        logger.info(f"Expression looks like a measure name: '{expression}'. Attempting auto-fetch...")

        # Try to find the measure in the model using AMO
        server, db, model = _get_server_db_model(connection_state)
        if not model and not AMO_AVAILABLE:
            warnings.append("AMO assemblies not loaded — measure auto-fetch disabled")
        if model:
            try:
                # Search for measure across all tables
                found_measure = None
                found_table = None

                # Normalize search term for fuzzy matching
                search_term = expression.lower().strip()
                exact_matches = []
                partial_matches = []

                # Split search term into words, removing common separators
                search_words = [w for w in re.split(r'[\s\-_]+', search_term) if w]

                for table in model.Tables:
                    for measure in table.Measures:
                        measure_name_lower = measure.Name.lower()

                        # Try exact match first (case-insensitive)
                        if measure_name_lower == search_term:
                            exact_matches.append((measure, table.Name))
                        # Try fuzzy match using SequenceMatcher for proper similarity scoring
                        else:
                            # Calculate similarity ratio (0.0 to 1.0)
                            similarity = SequenceMatcher(None, search_term, measure_name_lower).ratio()

                            # Also check if all significant search words appear in measure name
                            # Filter out very short words like "in", "to", "a" which are noise
                            significant_search_words = [w for w in search_words if len(w) > 2]
                            measure_words = set(re.split(r'[\s\-_]+', measure_name_lower))

                            # Calculate word match score (what fraction of significant words match)
                            word_match_count = sum(
                                1 for sw in significant_search_words
                                if any(sw in mw or mw in sw for mw in measure_words)
                            )
                            word_match_ratio = word_match_count / len(significant_search_words) if significant_search_words else 0

                            # Combined score: weight similarity higher for exact-ish matches,
                            # but also consider word coverage
                            combined_score = (similarity * 0.6) + (word_match_ratio * 0.4)

                            # Only consider if similarity is reasonable (> 0.3) or most words match
                            if similarity > 0.3 or word_match_ratio >= 0.7:
                                partial_matches.append((measure, table.Name, combined_score, similarity))

                # Prioritize exact matches, then partial matches by HIGHEST score (not shortest name)
                if exact_matches:
                    found_measure, found_table = exact_matches[0]
                elif partial_matches:
                    # Sort by combined score DESCENDING - highest score wins
                    partial_matches.sort(key=lambda x: x[2], reverse=True)
                    found_measure, found_table, score, sim = partial_matches[0]
                    logger.info(f"Using fuzzy match: '{found_measure.Name}' (score={score:.2f}, similarity={sim:.2f}) for search term '{expression}'")

                if found_measure:
                    expression = found_measure.Expression
                    measure_name = original_expression
                    measure_table = found_table
                    logger.info(f"Auto-fetched measure '{found_measure.Name}' from table '{found_table}'")
                    # Clean up AMO connection
                    _cleanup_amo_connection(server)
                else:
                    # Measure not found - provide helpful suggestions ranked by similarity
                    all_measures_with_scores = []
                    for table in model.Tables:
                        for measure in table.Measures:
                            measure_name_lower = measure.Name.lower()
                            # Calculate similarity score for suggestions
                            similarity = SequenceMatcher(None, search_term, measure_name_lower).ratio()
                            if similarity > 0.2:  # Only suggest if somewhat similar
                                all_measures_with_scores.append((measure.Name, table.Name, similarity))

                    # Clean up AMO connection before returning error
                    _cleanup_amo_connection(server)

                    # Sort by similarity score (highest first) and take top suggestions
                    all_measures_with_scores.sort(key=lambda x: x[2], reverse=True)
                    suggestions = [f"[{t}].[{m}]" for m, t, _ in all_measures_with_scores[:10]]

                    error_msg = f"The expression '{original_expression}' looks like a measure name, but no match was found in the model."
                    if suggestions:
                        error_msg += f"\n\nDid you mean one of these measures?\n" + "\n".join(f"  • {s}" for s in suggestions[:5])
                    error_msg += f"\n\nPlease provide either:\n1. The full DAX expression to analyze, or\n2. A valid measure name"

                    return {
                        'success': False,
                        'error': error_msg,
                        'suggestions': suggestions if suggestions else None,
                        'hint': 'Try using the exact measure name or more specific keywords'
                    }
            except Exception as e:
                logger.warning(f"Error during auto-fetch: {e}")
                # Clean up AMO connection
                _cleanup_amo_connection(server)
                # Continue with original expression
                pass

    # Step 1: Validate DAX syntax (unless explicitly skipped)
    # IMPORTANT: Auto-skip validation for auto-fetched measures (they're already in the model and must be valid)
    if measure_name and not skip_validation:
        logger.info(f"Auto-fetched measure '{measure_name}' - skipping validation (already in model)")
        skip_validation = True

    validation_result = {'valid': True, 'message': 'Validation skipped'}
    if not skip_validation:
        is_valid, error_msg = _validate_dax_syntax(expression)
        validation_result = {
            'valid': is_valid,
            'message': 'DAX syntax is valid' if is_valid else f'DAX syntax error: {error_msg}'
        }

        if not is_valid:
            return {
                'success': True,
                'validation': validation_result,
                'analysis': None,
                'note': f'{analysis_mode.title()} skipped due to syntax errors. Fix the syntax errors first.'
            }

    # Step 2: Route to appropriate analysis mode
    try:
        if analysis_mode == 'all':
            # Run all modes: analyze, debug, and report
            from core.dax import DaxContextAnalyzer, DaxContextDebugger
            from core.dax.analysis_pipeline import (
                run_context_analysis, run_vertipaq_analysis,
                run_best_practices, run_call_tree,
            )
            analyzer = DaxContextAnalyzer()
            debugger = DaxContextDebugger()

            # Run analyze mode (shared pipeline - returns raw object + dict)
            result_analyze, _ = run_context_analysis(expression)
            if result_analyze is None:
                # Fallback: create minimal result for downstream consumers
                result_analyze = analyzer.analyze_context_transitions(expression)
            anti_patterns = analyzer.detect_dax_anti_patterns(expression)

            # Run static analysis rules engine
            rules_analysis = None
            try:
                from core.dax.dax_rules_engine import DaxRulesEngine
                rules_analysis = DaxRulesEngine().analyze(expression)
            except Exception as e:
                logger.warning(f"Rules engine analysis not available: {e}")

            # Generate annotated DAX code for visual display
            annotated_dax = analyzer.format_dax_with_annotations(expression, result_analyze.transitions)

            # VertiPaq + best practices (shared pipeline)
            vertipaq_analysis = run_vertipaq_analysis(expression, connection_state)
            context_dict = result_analyze.to_dict() if hasattr(result_analyze, 'to_dict') else result_analyze
            best_practices_result = run_best_practices(expression, context_dict, vertipaq_analysis)

            improvements = debugger.generate_improved_dax(
                dax_expression=expression,
                context_analysis=result_analyze,
                anti_patterns=anti_patterns,
                vertipaq_analysis=vertipaq_analysis,
                connection_state=connection_state
            )

            # Run debug mode
            steps = debugger.step_through(
                dax_expression=expression,
                breakpoints=args.get('breakpoints')
            )

            debug_steps_data = None
            if steps:
                debug_steps_data = [
                    {
                        'step_number': step.step_number,
                        'code_fragment': step.code_fragment,
                        'filter_context': step.filter_context,
                        'row_context': step.row_context,
                        'intermediate_result': step.intermediate_result,
                        'explanation': step.explanation,
                        'execution_time_ms': step.execution_time_ms
                    }
                    for step in steps
                ]

            # Call tree analysis (shared pipeline)
            call_tree_data = run_call_tree(expression, connection_state)
            total_iterations = call_tree_data.get('total_iterations', 0) if call_tree_data else 0

            # Combine all articles from various sources
            all_articles = []

            # From anti-pattern detection
            if anti_patterns.get('articles'):
                all_articles.extend(anti_patterns['articles'])

            # From best practices analyzer
            if best_practices_result and best_practices_result.get('articles_referenced'):
                all_articles.extend(best_practices_result['articles_referenced'])

            # Deduplicate articles by URL
            seen_urls = set()
            unique_articles = []
            for article in all_articles:
                url = article.get('url', '')
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique_articles.append(article)

            # Combine all results in structured format
            response = {
                'success': True,
                'validation': validation_result,
                'mode': 'all',

                # ============================================
                # 🚨 CRITICAL AI INSTRUCTIONS - READ FIRST 🚨
                # ============================================
                'AI_INSTRUCTIONS': {
                    'READ_THIS_FIRST': '🚨 This response contains ONLY structured data fields. There is NO text report field. You must read and present the structured fields below.',

                    'FORMATTING_CRITICAL': '🚨 CRITICAL FORMATTING: Each section MUST be a separate markdown section with a ### header followed by content. Use --- horizontal rules between major sections. DO NOT put everything in one code block or one continuous paragraph. Each analysis area gets its own distinct section with a header.',

                    'PRIORITY_1_SHOW_ANNOTATED_CODE_FIRST': '🚨 MANDATORY: Start with "### Annotated DAX Code" header, then display annotated_dax_code.code in a ```dax code block. Then OUTSIDE the code block, show "**Legend:**" followed by the legend as a bullet list. Add --- after this section.',

                    'PRIORITY_2_PRESENT_ANALYSIS_SUMMARY': 'Add "### Analysis Summary" header. Present analysis_summary as a clean table or bullet list showing: complexity score, total transitions, patterns detected, improvements available, best practices score. Add --- after.',

                    'PRIORITY_3_BEST_PRACTICES': 'Add "### Best Practices Analysis" header. Show issues grouped by priority (HIGH, MEDIUM, LOW). Each issue on its own line. Add --- after.',

                    'PRIORITY_4_ANTI_PATTERNS': 'Add "### Anti-Pattern Detection" header. For each pattern: show pattern name, matched instances, link to article. Add --- after.',

                    'PRIORITY_5_CONTEXT_TRANSITIONS': 'Add "### Context Transition Analysis" header. List each transition with function, line, type, and performance impact. Add --- after.',

                    'PRIORITY_6_IMPROVEMENTS': 'Add "### Improvement Opportunities" header. Number each improvement with before/after examples where applicable. Add --- after.',

                    'PRIORITY_7_CALL_TREE': 'Add "### Call Tree Visualization" header. Display call_tree.visualization in a ```text code block to preserve the tree structure. The visualization already includes its own legend. Add --- after.',

                    'PRIORITY_8_VERTIPAQ': 'If vertipaq_analysis has data, add "### VertiPaq Analysis" header. Show column metrics in a table format. Add --- after.',

                    'PRIORITY_9_WRITE_OPTIMIZED_CODE': '🚨 CRITICAL: Add "### Optimized DAX Code" header. YOU (the AI) MUST write the complete optimized DAX measure. The rewriter_draft field is just a SUGGESTION. Write production-ready code in a ```dax code block. Add --- after.',

                    'PRIORITY_10_EXPLAIN_CHANGES': 'Add "### Optimization Explanation" header. Explain what specific optimizations you applied and WHY they improve performance. Reference articles_referenced when relevant.',

                    'DATA_STRUCTURE_GUIDE': 'Key fields: annotated_dax_code.code (visual code), annotated_dax_code.legend (show as bullets), analysis_summary (stats), best_practices_analysis.issues (violations), anti_patterns.pattern_matches (patterns), context_analysis.transitions (transitions), improvements.details (improvement list), call_tree.visualization (pre-formatted tree - put in ```text block), vertipaq_analysis.column_analysis (metrics), articles_referenced.articles (links)',

                    'WORKFLOW_SUMMARY': 'SECTION HEADERS: ### Annotated DAX Code → --- → ### Analysis Summary → --- → ### Best Practices Analysis → --- → ### Anti-Pattern Detection → --- → ### Context Transitions → --- → ### Improvements → --- → ### Call Tree Visualization → --- → ### VertiPaq Analysis → --- → ### Optimized DAX Code → --- → ### Optimization Explanation'
                },

                # ============================================
                # ANNOTATED DAX CODE - SHOW THIS FIRST!
                # ============================================
                'annotated_dax_code': {
                    'code': annotated_dax,
                    'legend': {
                        '🔄': 'Iterator function (creates row context)',
                        '📊': 'Measure reference (implicit CALCULATE)',
                        '⚡': 'Explicit CALCULATE/CALCULATETABLE',
                        '🔴': 'HIGH performance impact',
                        '🟡': 'MEDIUM performance impact',
                        '🟢': 'LOW performance impact'
                    },
                    'formatting_instructions': '🚨 CRITICAL FORMATTING: Put the "code" field inside a ```dax code block. The "legend" field must be rendered OUTSIDE the code block as a markdown bullet list AFTER the closing ``` backticks. NEVER include the legend inside the code block - it breaks formatting.'
                },
                'analysis_summary': {
                    'complexity_score': result_analyze.complexity_score,
                    'max_nesting_level': result_analyze.max_nesting_level,
                    'total_transitions': len(result_analyze.transitions),
                    'patterns_detected': anti_patterns.get('patterns_detected', 0),
                    'improvements_available': improvements.get('has_improvements', False),
                    'improvements_count': improvements.get('improvements_count', 0),
                    'best_practices_score': best_practices_result.get('overall_score', 0) if best_practices_result else None,
                    'best_practices_issues': best_practices_result.get('total_issues', 0) if best_practices_result else 0,
                    'health_score': rules_analysis.get('health_score') if rules_analysis else None,
                    'static_analysis_issues': rules_analysis.get('issue_count', 0) if rules_analysis else 0
                },
                'context_analysis': {
                    'summary': result_analyze.summary,
                    'complexity_score': result_analyze.complexity_score,
                    'max_nesting_level': result_analyze.max_nesting_level,
                    'transitions': [
                        {
                            'function': t.function,
                            'line': t.line,
                            'column': t.column,
                            'type': t.type.value,
                            'performance_impact': t.performance_impact.value,
                            'explanation': t.explanation
                        }
                        for t in result_analyze.transitions
                    ]
                },
                'best_practices_analysis': best_practices_result if best_practices_result else {'note': 'Best practices analysis not available'},
                'anti_patterns': {
                    'success': anti_patterns.get('success', False),
                    'patterns_detected': anti_patterns.get('patterns_detected', 0),
                    'pattern_matches': anti_patterns.get('pattern_matches', {}),
                    'recommendations': anti_patterns.get('recommendations', []),
                    'articles': anti_patterns.get('articles', []),
                    'error': anti_patterns.get('error') if not anti_patterns.get('success') else None
                },
                'static_analysis': rules_analysis if rules_analysis else {'note': 'Static analysis not available'},
                'improvements': {
                    'has_improvements': improvements.get('has_improvements', False),
                    'summary': improvements.get('summary', 'No improvements suggested'),
                    'count': improvements.get('improvements_count', 0),
                    'details': improvements.get('improvements', []),
                    'original_code': expression,
                    'rewriter_draft': improvements.get('rewriter_draft')
                },
                'vertipaq_analysis': vertipaq_analysis if vertipaq_analysis and vertipaq_analysis.get('success') else {
                    'note': 'VertiPaq analysis not available',
                    'reason': vertipaq_analysis.get('error') if vertipaq_analysis else 'Analysis failed or not connected to model'
                },
                'call_tree': call_tree_data,
                'debug_steps': debug_steps_data,

                # ============================================
                # 🚨 AI WRITES THE FINAL OPTIMIZED MEASURE 🚨
                # ============================================
                'optimized_measure': {
                    'rewriter_draft': improvements.get('rewriter_draft'),
                    'has_optimization_opportunities': improvements.get('has_improvements', False),
                    'opportunities_count': improvements.get('improvements_count', 0),
                    'AI_INSTRUCTION': (
                        '🚨 CRITICAL: YOU (the AI) must write the final optimized DAX measure. '
                        'The rewriter_draft field (if present) is just a SUGGESTION from the code rewriter. '
                        'Review ALL analysis data: context transitions, anti-patterns, VertiPaq metrics, best practices, '
                        'and the rewriter suggestions. Then write your OWN complete, production-ready optimized DAX. '
                        'You may use the rewriter draft as a starting point, improve upon it, or write something '
                        'entirely different based on the full analysis. ALWAYS explain your optimization choices.'
                    )
                },
                # PROMINENT ARTICLE REFERENCES SECTION
                'articles_referenced': {
                    'total_count': len(unique_articles),
                    'articles': unique_articles,
                    'note': 'These articles were referenced during the analysis and provide detailed explanations of the patterns detected'
                }
            }

            if measure_name:
                response['measure_info'] = {
                    'name': measure_name,
                    'table': measure_table,
                    'note': f"Auto-fetched measure expression from [{measure_table}].[{measure_name}]"
                }

            return response

        elif analysis_mode == 'analyze':
            # Context transition analysis with anti-pattern detection
            from core.dax import DaxContextAnalyzer, DaxContextDebugger
            analyzer = DaxContextAnalyzer()
            debugger = DaxContextDebugger()

            result = analyzer.analyze_context_transitions(expression)

            # Generate annotated DAX code for visual display
            annotated_dax = analyzer.format_dax_with_annotations(expression, result.transitions)

            # Add anti-pattern detection
            anti_patterns = analyzer.detect_dax_anti_patterns(expression)

            # Run static analysis rules engine
            rules_analysis = None
            try:
                from core.dax.dax_rules_engine import DaxRulesEngine
                rules_engine = DaxRulesEngine()
                rules_analysis = rules_engine.analyze(expression)
            except Exception as e:
                logger.warning(f"Rules engine analysis not available: {e}")

            # Get VertiPaq analysis for comprehensive optimization
            vertipaq_analysis = None
            try:
                from core.dax.vertipaq_analyzer import VertiPaqAnalyzer
                vertipaq = VertiPaqAnalyzer(connection_state)
                vertipaq_analysis = vertipaq.analyze_dax_columns(expression)
                if not vertipaq_analysis.get('success'):
                    logger.warning(f"VertiPaq analysis failed: {vertipaq_analysis.get('error', 'Unknown error')}")
            except Exception as e:
                logger.warning(f"VertiPaq analysis not available: {e}")

            # Run comprehensive best practices analysis
            best_practices_result = None
            try:
                from core.dax.dax_best_practices import DaxBestPracticesAnalyzer
                bp_analyzer = DaxBestPracticesAnalyzer()
                best_practices_result = bp_analyzer.analyze(
                    dax_expression=expression,
                    context_analysis=result.to_dict() if hasattr(result, 'to_dict') else result,
                    vertipaq_analysis=vertipaq_analysis
                )
                logger.info(f"Best practices analysis: {best_practices_result.get('total_issues', 0)} issues found")
            except Exception as e:
                logger.warning(f"Best practices analysis not available: {e}")

            # Generate specific improvements and new DAX code
            improvements = debugger.generate_improved_dax(
                dax_expression=expression,
                context_analysis=result,
                anti_patterns=anti_patterns,
                vertipaq_analysis=vertipaq_analysis,
                connection_state=connection_state  # Pass for output validation
            )

            # Combine all articles
            all_articles = []
            if anti_patterns.get('articles'):
                all_articles.extend(anti_patterns['articles'])
            if best_practices_result and best_practices_result.get('articles_referenced'):
                all_articles.extend(best_practices_result['articles_referenced'])

            # Deduplicate
            seen_urls = set()
            unique_articles = []
            for article in all_articles:
                url = article.get('url', '')
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique_articles.append(article)

            response = {
                'success': True,
                'validation': validation_result,
                'mode': 'analyze',

                # ============================================
                # 🚨 CRITICAL AI INSTRUCTIONS - READ FIRST 🚨
                # ============================================
                'AI_INSTRUCTIONS': {
                    'READ_THIS_FIRST': '🚨 This response contains ONLY structured data fields. You must read and present the structured fields below.',

                    'FORMATTING_CRITICAL': '🚨 CRITICAL FORMATTING: Each section MUST be a separate markdown section with a ### header followed by content. Use --- horizontal rules between major sections. DO NOT put everything in one code block or one continuous paragraph.',

                    'PRIORITY_1_SHOW_ANNOTATED_CODE_FIRST': '🚨 MANDATORY: Start with "### Annotated DAX Code" header, then display annotated_dax_code.code in a ```dax code block. Then OUTSIDE the code block, show "**Legend:**" followed by the legend as a bullet list. Add --- after this section.',

                    'PRIORITY_2_BEST_PRACTICES': 'Add "### Best Practices Analysis" header. Show issues grouped by priority (HIGH, MEDIUM, LOW). Each issue on its own line. Add --- after.',

                    'PRIORITY_3_ANTI_PATTERNS': 'Add "### Anti-Pattern Detection" header. For each pattern: show pattern name, matched instances, link to article. Add --- after.',

                    'PRIORITY_4_TRANSITIONS': 'Add "### Context Transition Analysis" header. List each transition with function, line, type, and performance impact. Add --- after.',

                    'PRIORITY_5_IMPROVEMENTS': 'Add "### Improvement Opportunities" header. Number each improvement with before/after examples where applicable. Add --- after.',

                    'PRIORITY_6_VERTIPAQ': 'If vertipaq_analysis has data, add "### VertiPaq Analysis" header. Show column metrics in a table format. Add --- after.',

                    'PRIORITY_7_WRITE_OPTIMIZED_CODE': '🚨 CRITICAL: Add "### Optimized DAX Code" header. YOU (the AI) MUST write the complete optimized DAX measure. The rewriter_draft field is just a SUGGESTION. Write production-ready code in a ```dax code block. Add --- after.',

                    'PRIORITY_8_EXPLAIN_CHANGES': 'Add "### Optimization Explanation" header. Explain what specific optimizations you applied and WHY they improve performance. Reference articles_referenced when relevant.',

                    'DATA_STRUCTURE_GUIDE': 'Key fields: annotated_dax_code.code (visual code), annotated_dax_code.legend (show as bullets), best_practices_analysis.issues (violations), anti_patterns.pattern_matches (patterns), analysis.transitions (transitions), improvements.details (improvement list), vertipaq_analysis.column_analysis (metrics), articles_referenced.articles (links)',

                    'WORKFLOW_SUMMARY': 'SECTION HEADERS: ### Annotated DAX Code → --- → ### Best Practices Analysis → --- → ### Anti-Pattern Detection → --- → ### Context Transitions → --- → ### Improvements → --- → ### VertiPaq Analysis → --- → ### Optimized DAX Code → --- → ### Optimization Explanation'
                },

                # ============================================
                # ANNOTATED DAX CODE - SHOW THIS FIRST!
                # ============================================
                'annotated_dax_code': {
                    'code': annotated_dax,
                    'legend': {
                        '🔄': 'Iterator function (creates row context)',
                        '📊': 'Measure reference (implicit CALCULATE)',
                        '⚡': 'Explicit CALCULATE/CALCULATETABLE',
                        '🔴': 'HIGH performance impact',
                        '🟡': 'MEDIUM performance impact',
                        '🟢': 'LOW performance impact'
                    },
                    'formatting_instructions': '🚨 CRITICAL FORMATTING: Put the "code" field inside a ```dax code block. The "legend" field must be rendered OUTSIDE the code block as a markdown bullet list AFTER the closing ``` backticks. NEVER include the legend inside the code block - it breaks formatting.'
                },
                'analysis': result.to_dict() if hasattr(result, 'to_dict') else result
            }

            # Include measure info if auto-fetched
            if measure_name:
                response['measure_info'] = {
                    'name': measure_name,
                    'table': measure_table,
                    'note': f"Auto-fetched measure expression from [{measure_table}].[{measure_name}]"
                }

            # Include best practices analysis
            response['best_practices_analysis'] = best_practices_result if best_practices_result else {'note': 'Best practices analysis not available'}

            # ALWAYS include anti-pattern detection results (even if failed or no patterns found)
            response['anti_patterns'] = {
                'success': anti_patterns.get('success', False),
                'patterns_detected': anti_patterns.get('patterns_detected', 0),
                'pattern_matches': anti_patterns.get('pattern_matches', {}),
                'recommendations': anti_patterns.get('recommendations', []),
                'articles': anti_patterns.get('articles', []),
                'error': anti_patterns.get('error') if not anti_patterns.get('success') else None
            }

            # Include static analysis (rules engine)
            response['static_analysis'] = rules_analysis if rules_analysis else {'note': 'Static analysis not available'}

            # Include VertiPaq analysis
            response['vertipaq_analysis'] = vertipaq_analysis if vertipaq_analysis and vertipaq_analysis.get('success') else {
                'note': 'VertiPaq analysis not available',
                'reason': vertipaq_analysis.get('error') if vertipaq_analysis else 'Analysis failed or not connected to model'
            }

            # Include specific improvements with rewriter draft
            if improvements.get('has_improvements'):
                response['improvements'] = {
                    'summary': improvements.get('summary'),
                    'count': improvements.get('improvements_count'),
                    'details': improvements.get('improvements'),
                    'original_code': improvements.get('original_code'),
                    'rewriter_draft': improvements.get('rewriter_draft')
                }

            # ============================================
            # 🚨 AI WRITES THE FINAL OPTIMIZED MEASURE 🚨
            # ============================================
            response['final_optimized_measure'] = {
                'rewriter_draft': improvements.get('rewriter_draft'),
                'has_optimization_opportunities': improvements.get('has_improvements', False),
                'opportunities_count': improvements.get('improvements_count', 0),
                'AI_INSTRUCTION': (
                    '🚨 CRITICAL: YOU (the AI) must write the final optimized DAX measure. '
                    'The rewriter_draft field (if present) is just a SUGGESTION from the code rewriter. '
                    'Review ALL analysis data: context transitions, anti-patterns, VertiPaq metrics, best practices, '
                    'and the rewriter suggestions. Then write your OWN complete, production-ready optimized DAX. '
                    'You may use the rewriter draft as a starting point, improve upon it, or write something '
                    'entirely different based on the full analysis. ALWAYS explain your optimization choices.'
                )
            }

            # PROMINENT ARTICLE REFERENCES
            response['articles_referenced'] = {
                'total_count': len(unique_articles),
                'articles': unique_articles,
                'note': 'These articles were referenced during the analysis and provide detailed explanations of the patterns detected'
            }

            if warnings:
                response['warnings'] = warnings

            return response

        elif analysis_mode == 'debug':
            # Step-by-step debugging
            from core.dax import DaxContextDebugger
            debugger = DaxContextDebugger()

            output_format = args.get('output_format', 'friendly')
            breakpoints = args.get('breakpoints')

            steps = debugger.step_through(
                dax_expression=expression,
                breakpoints=breakpoints
            )

            if not steps:
                result = {
                    'success': True,
                    'validation': validation_result,
                    'message': '✅ No context transitions detected in this DAX expression.',
                    'explanation': 'This is a simple expression without CALCULATE, iterators, or measure references that would cause context transitions.',
                    'total_steps': 0,
                    'mode': 'debug'
                }
                if measure_name:
                    result['measure_info'] = {
                        'name': measure_name,
                        'table': measure_table,
                        'note': f"Auto-fetched measure expression from [{measure_table}].[{measure_name}]"
                    }
                if warnings:
                    result['warnings'] = warnings
                return result

            # Format output based on requested format
            if output_format == 'friendly':
                formatted_output = _format_debug_steps_friendly(expression, steps)
                # Add validation header
                if validation_result['valid']:
                    validation_header = "✅ DAX SYNTAX VALIDATION: PASSED\n\n"
                    formatted_output = validation_header + formatted_output

                # Add measure info header if auto-fetched
                if measure_name:
                    measure_header = f"📊 Analyzing measure: [{measure_table}].[{measure_name}]\n\n"
                    formatted_output = measure_header + formatted_output

                result = {
                    'success': True,
                    'validation': validation_result,
                    'formatted_output': formatted_output,
                    'total_steps': len(steps),
                    'mode': 'debug'
                }
                if measure_name:
                    result['measure_info'] = {
                        'name': measure_name,
                        'table': measure_table,
                        'note': f"Auto-fetched measure expression from [{measure_table}].[{measure_name}]"
                    }
                if warnings:
                    result['warnings'] = warnings
                return result
            else:
                # 'steps' format - raw data
                steps_dict = [
                    {
                        'step_number': step.step_number,
                        'code_fragment': step.code_fragment,
                        'filter_context': step.filter_context,
                        'row_context': step.row_context,
                        'intermediate_result': step.intermediate_result,
                        'explanation': step.explanation,
                        'execution_time_ms': step.execution_time_ms
                    }
                    for step in steps
                ]

                result = {
                    'success': True,
                    'validation': validation_result,
                    'debug_steps': steps_dict,
                    'total_steps': len(steps_dict),
                    'mode': 'debug'
                }
                if measure_name:
                    result['measure_info'] = {
                        'name': measure_name,
                        'table': measure_table,
                        'note': f"Auto-fetched measure expression from [{measure_table}].[{measure_name}]"
                    }
                if warnings:
                    result['warnings'] = warnings
                return result

        elif analysis_mode == 'report':
            # Comprehensive debug report with all enhancements
            from core.dax import DaxContextDebugger
            debugger = DaxContextDebugger()

            include_profiling = args.get('include_profiling', True)
            include_optimization = args.get('include_optimization', True)

            result = debugger.generate_debug_report(
                expression,
                include_profiling=include_profiling,
                include_optimization=include_optimization,
                connection_state=connection_state  # Pass connection state for enhanced analysis
            )

            response = {
                'success': True,
                'validation': validation_result,
                'report': result,
                'mode': 'report'
            }

            # Extract optimized code from report if available
            # The report already includes the optimized measure in the text
            # Let's also provide it in structured format
            try:
                # Try to get the improvements from the report generation
                from core.dax import DaxContextAnalyzer
                analyzer = DaxContextAnalyzer()
                result_analyze = analyzer.analyze_context_transitions(expression)
                anti_patterns = analyzer.detect_dax_anti_patterns(expression)

                # Run static analysis rules engine
                try:
                    from core.dax.dax_rules_engine import DaxRulesEngine
                    rules_engine = DaxRulesEngine()
                    response['static_analysis'] = rules_engine.analyze(expression)
                except Exception as rules_err:
                    logger.warning(f"Rules engine not available in report mode: {rules_err}")

                from core.dax import DaxContextDebugger
                debugger_temp = DaxContextDebugger()

                # Get VertiPaq analysis for comprehensive optimization
                vertipaq_analysis = None
                try:
                    from core.dax.vertipaq_analyzer import VertiPaqAnalyzer
                    vertipaq = VertiPaqAnalyzer(connection_state)
                    vertipaq_analysis = vertipaq.analyze_dax_columns(expression)
                except Exception:
                    pass

                improvements = debugger_temp.generate_improved_dax(
                    dax_expression=expression,
                    context_analysis=result_analyze,
                    anti_patterns=anti_patterns,
                    vertipaq_analysis=vertipaq_analysis
                )

                response['final_optimized_measure'] = {
                    'rewriter_draft': improvements.get('rewriter_draft'),
                    'has_optimization_opportunities': improvements.get('has_improvements', False),
                    'opportunities_count': improvements.get('improvements_count', 0),
                    'AI_INSTRUCTION': (
                        '🚨 CRITICAL: YOU (the AI) must write the final optimized DAX measure. '
                        'The rewriter_draft field (if present) is just a SUGGESTION from the code rewriter. '
                        'Review ALL analysis data from the report and write your OWN complete, production-ready optimized DAX. '
                        'You may use the rewriter draft as a starting point, improve upon it, or write something '
                        'entirely different based on the full analysis. ALWAYS explain your optimization choices.'
                    )
                }
            except Exception as e:
                logger.warning(f"Could not extract optimized measure: {e}")

            if measure_name:
                response['measure_info'] = {
                    'name': measure_name,
                    'table': measure_table,
                    'note': f"Auto-fetched measure expression from [{measure_table}].[{measure_name}]"
                }
            if warnings:
                response['warnings'] = warnings
            return response
        else:
            return {
                'success': False,
                'error': f"Invalid analysis_mode: {analysis_mode}. Use 'all' (default), 'analyze', 'debug', or 'report'."
            }

    except ImportError as ie:
        logger.error(f"Import error: {ie}", exc_info=True)
        return {
            'success': False,
            'validation': validation_result,
            'error': f'DAX Intelligence components not available. This is an internal error.',
            'error_type': 'import_error'
        }
    except Exception as e:
        logger.error(f"Error in DAX Intelligence ({analysis_mode} mode): {e}", exc_info=True)
        return {
            'success': False,
            'validation': validation_result,
            'error': f'Error in DAX Intelligence ({analysis_mode} mode): {str(e)}'
        }


def register_dax_handlers(registry):
    """Register unified DAX Intelligence handler (Tool 03)"""
    from server.tool_schemas import TOOL_SCHEMAS

    tools = [
        ToolDefinition(
            name="05_DAX_Intelligence",
            description="DAX analysis: context transitions, anti-patterns, VertiPaq, call tree, optimized code.",
            handler=handle_dax_intelligence,
            input_schema=TOOL_SCHEMAS.get('dax_intelligence', {}),
            category="dax",
            sort_order=50,  # 05 = DAX Intelligence
            annotations={"readOnlyHint": True},
        ),
    ]

    for tool in tools:
        registry.register(tool)

    logger.info(f"Registered {len(tools)} DAX Intelligence handler (Tool 05)")
