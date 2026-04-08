"""DAX Optimization Pipeline — full analyze→rewrite→apply flow."""

import logging
from typing import List, Optional

from core.dax.analyzer.unified_analyzer import DaxUnifiedAnalyzer
from core.dax.analyzer.models import AnalysisContext
from core.dax.optimizer.rewrite_engine import DaxRewriteEngine
from core.dax.optimizer.models import OptimizationResult
from core.dax.knowledge import DaxFunctionDatabase

logger = logging.getLogger(__name__)


class OptimizationPipeline:
    """Full DAX optimization: analyze, rewrite, optionally apply."""

    def __init__(self, connection_state=None):
        self._connection_state = connection_state
        self._function_db = DaxFunctionDatabase.get()
        self._analyzer = DaxUnifiedAnalyzer()
        self._rewriter = DaxRewriteEngine(self._function_db)

    def optimize_expression(
        self,
        dax_expression: str,
        context: Optional[AnalysisContext] = None,
    ) -> OptimizationResult:
        """Optimize a standalone DAX expression (no model connection needed)."""
        try:
            # Step 1: Analyze
            analysis = self._analyzer.analyze(dax_expression, context)

            # Step 2: Generate rewrites
            rewrites = self._rewriter.rewrite(dax_expression, analysis.tokens, analysis.issues)

            # Step 3: Apply rewrites to generate final DAX
            final_dax = None
            if rewrites:
                final_dax = self._rewriter.apply_rewrites(dax_expression, rewrites)
                if final_dax == dax_expression:
                    final_dax = None  # No actual changes

            # Build summary
            if rewrites:
                strategies = set(r.strategy for r in rewrites)
                summary = (
                    f"{len(rewrites)} optimization(s) applied: "
                    f"{', '.join(strategies)}. "
                    f"Analysis found {analysis.total_issues} issues "
                    f"(score: {analysis.health_score}/100)."
                )
            else:
                summary = (
                    f"No automated rewrites available. "
                    f"Analysis found {analysis.total_issues} issues "
                    f"(score: {analysis.health_score}/100)."
                )

            return OptimizationResult(
                success=True,
                measure_name=None,
                original_dax=dax_expression,
                analysis=analysis,
                rewrites=rewrites,
                final_dax=final_dax,
                applied=False,
                apply_error=None,
                improvement_summary=summary,
            )
        except Exception as e:
            logger.error(f"Optimization pipeline error: {e}", exc_info=True)
            return OptimizationResult(
                success=False,
                measure_name=None,
                original_dax=dax_expression,
                analysis=None,
                rewrites=[],
                final_dax=None,
                applied=False,
                apply_error=str(e),
                improvement_summary=f"Pipeline error: {e}",
            )

    def optimize_measure(
        self,
        measure_name: str,
        table_name: str,
        dry_run: bool = True,
    ) -> OptimizationResult:
        """Full pipeline for a single measure from connected model."""
        # Step 1: Read current DAX
        dax_expression = self._read_measure_dax(measure_name, table_name)
        if dax_expression is None:
            return OptimizationResult(
                success=False,
                measure_name=measure_name,
                original_dax="",
                analysis=None,
                rewrites=[],
                final_dax=None,
                applied=False,
                apply_error=(f"Could not read measure '{measure_name}' from table '{table_name}'"),
                improvement_summary="Failed to read measure",
            )

        # Step 2: Build context with VertiPaq data if connected
        context = self._build_context(measure_name, table_name)

        # Step 3: Optimize
        result = self.optimize_expression(dax_expression, context)
        result.measure_name = measure_name

        # Step 4: Apply if not dry run and we have changes
        if not dry_run and result.final_dax and self._connection_state:
            result = self._apply_to_model(result, measure_name, table_name)

        return result

    def _read_measure_dax(self, measure_name: str, table_name: str) -> Optional[str]:
        """Read measure DAX from connected model."""
        if not self._connection_state:
            return None
        try:
            qe = self._connection_state.query_executor
            if qe:
                result = qe.execute_dax(
                    f"SELECT [Expression] FROM $SYSTEM.TMSCHEMA_MEASURES "
                    f"WHERE [Name] = '{measure_name}'"
                )
                if result.get("results") and len(result["results"]) > 0:
                    return result["results"][0].get("Expression")
        except Exception as e:
            logger.warning(f"Failed to read measure: {e}")
        return None

    def _build_context(self, measure_name: str, table_name: str) -> AnalysisContext:
        """Build analysis context with available enrichment data."""
        ctx = AnalysisContext(measure_name=measure_name, table_name=table_name)
        if self._connection_state:
            try:
                from core.dax.vertipaq_analyzer import VertiPaqAnalyzer

                VertiPaqAnalyzer(self._connection_state)
                # Signal Tier 2 availability
                ctx.vertipaq_data = {"available": True}
            except Exception:
                pass
        return ctx

    def _apply_to_model(
        self, result: OptimizationResult, measure_name: str, table_name: str
    ) -> OptimizationResult:
        """Apply optimized DAX to the model."""
        try:
            from core.dax.dax_injector import DAXInjector

            injector = DAXInjector(self._connection_state)
            apply_result = injector.upsert_measure(
                measure_name=measure_name,
                table_name=table_name,
                expression=result.final_dax,
            )
            if apply_result.get("success"):
                result.applied = True
            else:
                result.apply_error = apply_result.get("error", "Unknown apply error")
        except Exception as e:
            result.apply_error = str(e)
        return result
