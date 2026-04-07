# DAX Engine Overhaul — Design Specification

**Date:** 2026-04-07
**Status:** Draft
**Scope:** Comprehensive overhaul of all DAX analysis, optimization, rewriting, and knowledge systems in MCP-PowerBi-Finvision

## 1. Goals

1. Build a proper DAX tokenizer as foundation for all analysis/rewriting
2. Create a comprehensive DAX function knowledge base (200+ functions)
3. Consolidate 3 overlapping analyzers into a single unified engine with hybrid config/code rules
4. Expand rule coverage from ~35 to 80+ rules, incorporating latest SQLBI/Microsoft research
5. Build an end-to-end optimize pipeline: analyze → rewrite → apply
6. Wire integration: VertiPaq informs rule severity, SE traces confirm findings, function DB informs everything
7. Improve rewriter: tokenizer-based transforms, meaningful variable names, higher confidence
8. **Zero breaking changes** to existing tool APIs or handler contracts

## 2. Hard Constraints

- All 22 MCP tools must continue working identically
- Existing class constructors and method signatures are frozen (see Section 10)
- Existing `__init__.py` exports are frozen
- `analysis_pipeline.py` functions keep their signatures; new functions are additive
- Handler files (`dax_context_handler.py`, `debug_handler.py`) require zero changes initially; improvements are optional follow-ups
- Thread safety maintained (all new code must be safe for `run_in_executor`)
- Windows-only runtime constraints respected

## 3. Tiered Analysis Model

The system works at three tiers. Each tier enriches the previous. **Tier 1 must produce high-quality, actionable results on its own.**

### Tier 1 — Static Analysis (always available)
- Input: DAX expression string only
- Uses: Tokenizer, function DB, all rules (JSON + Python), rewriter
- Output: Issues with severity, fix suggestions, rewritten DAX, health score
- No connection to Power BI required
- Works for: PBIP/TMDL offline analysis, AI assistant review, pasted DAX

### Tier 2 — Connected Analysis (PBI Desktop running)
- Adds: VertiPaq column metrics (cardinality, encoding, memory), table row counts, live DAX syntax validation
- Enriches: Rule severity adjusted by real data (e.g., "SUMX iterating 5M rows" vs "SUMX iterating a table")
- Requires: Active connection via `connection_state`

### Tier 3 — Trace-Enhanced Analysis (profiler available)
- Adds: SE/FE timing split, CallbackDataID confirmation, fusion break evidence, datacache sizes
- Enriches: Static findings gain "confirmed by trace" evidence; false positives can be suppressed
- Requires: Query trace execution (not always possible)

Each analysis result labels findings by tier: `source: "static"`, `source: "vertipaq"`, `source: "trace"`.

## 4. Component Design

### 4.1 DAX Tokenizer (`core/dax/tokenizer/`)

**Files:**
- `tokens.py` — Token type enum + Token dataclass
- `lexer.py` — `DaxLexer` class

**Token types:**
```
KEYWORD        — VAR, RETURN, IF, ELSE, SWITCH, TRUE, FALSE, AND, OR, NOT, IN,
                 EVALUATE, DEFINE, MEASURE, ORDER, BY, ASC, DESC, COLUMN, TABLE
FUNCTION       — Any identifier followed by ( that's in the function DB
IDENTIFIER     — Unquoted identifiers not classified as KEYWORD/FUNCTION
TABLE_REF      — 'Quoted Table Name'
COLUMN_REF     — [Column or Measure]  (full token includes brackets)
QUALIFIED_REF  — 'Table'[Column]  (composite token: TABLE_REF + COLUMN_REF)
STRING         — "double quoted strings" with "" escape handling
NUMBER         — Integer and decimal literals
OPERATOR       — +, -, *, /, =, <>, <, >, <=, >=, &&, ||, &
PAREN_OPEN     — (
PAREN_CLOSE    — )
COMMA          — ,
COMMENT_LINE   — // to end of line
COMMENT_BLOCK  — /* ... */
WHITESPACE     — Spaces, tabs (not newlines)
NEWLINE        — \n, \r\n
DOT            — . (for STDEVX.S etc.)
UNKNOWN        — Unrecognized characters
```

**Token dataclass:**
```python
@dataclass(frozen=True, slots=True)
class Token:
    type: TokenType
    value: str
    start: int        # Char offset in source
    end: int          # Char offset (exclusive)
    line: int         # 1-based line number
    col: int          # 1-based column number
```

**DaxLexer API:**
```python
class DaxLexer:
    def __init__(self, function_db: Optional[DaxFunctionDatabase] = None):
        """If no function_db, FUNCTION tokens fall back to IDENTIFIER."""

    def tokenize(self, dax: str) -> List[Token]:
        """Full token stream including comments and whitespace."""

    def tokenize_code(self, dax: str) -> List[Token]:
        """Token stream with COMMENT_LINE, COMMENT_BLOCK, WHITESPACE, NEWLINE filtered out.
        Replaces normalize_dax() usage across the codebase."""

    def build_paren_map(self, tokens: List[Token]) -> Dict[int, int]:
        """Pre-computed map: index of PAREN_OPEN → index of matching PAREN_CLOSE.
        Replaces find_matching_paren() character-by-character loops."""

    def extract_function_args(self, tokens: List[Token], func_index: int) -> List[List[Token]]:
        """Given index of a FUNCTION token, return token slices for each argument,
        respecting nested parens. Replaces extract_function_body() + manual parsing."""
```

**Implementation notes:**
- Single-pass, O(n). No backtracking.
- Handles `""` escape in strings, `''` in table references
- TABLE_REF + COLUMN_REF adjacency detected in post-pass to emit QUALIFIED_REF
- FUNCTION vs IDENTIFIER: if function_db loaded, check name against DB. If not loaded, classify any identifier followed by `(` as FUNCTION.
- Pre-compiled character class checks for performance
- Thread-safe: no mutable state after __init__

**Replaces/improves:**
- `dax_utilities.normalize_dax()` → `lexer.tokenize_code()`
- `dax_utilities.extract_function_body()` → `lexer.extract_function_args()`
- `dax_utilities.find_matching_paren()` → `lexer.build_paren_map()`
- `dax_utilities.extract_variables()` → scan for KEYWORD(VAR) tokens
- `code_rewriter._validate_syntax()` → structural checks on token stream
- Comment/string stripping duplicated in `callback_detector.py`, `dax_rules_engine.py`

The existing `dax_utilities.py` functions are kept and internally refactored to use the tokenizer (backward-compatible).

### 4.2 DAX Function Knowledge Base (`core/dax/knowledge/`)

**Files:**
- `function_db.py` — `DaxFunctionDatabase` class
- `functions.json` — Full catalog (200+ functions)

**Function entry schema:**
```json
{
  "name": "SUMX",
  "category": "iterator",
  "subcategory": "aggregation",
  "return_type": "scalar",
  "se_pushable": "expression_dependent",
  "creates_row_context": true,
  "creates_filter_context": false,
  "parameters": [
    {"name": "table", "type": "table", "required": true, "description": "Table to iterate"},
    {"name": "expression", "type": "scalar", "required": true, "description": "Expression evaluated per row"}
  ],
  "callback_risk": "high_if_complex_expression",
  "performance_tier": "depends",
  "performance_notes": "Simple arithmetic pushed to SE. Complex functions (ROUND, FORMAT, string ops) trigger CallbackDataID.",
  "alternatives": [
    {
      "when": "expression is single column reference",
      "use": "SUM",
      "example_before": "SUMX(Sales, Sales[Amount])",
      "example_after": "SUM(Sales[Amount])",
      "improvement": "Eliminates unnecessary iterator overhead"
    },
    {
      "when": "iterating FILTER() result",
      "use": "CALCULATE",
      "example_before": "SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])",
      "example_after": "CALCULATE(SUM(Sales[Amount]), Sales[Qty] > 10)",
      "improvement": "5-10x faster. Enables SE optimization."
    }
  ],
  "references": [
    {"source": "DAX Guide", "url": "https://dax.guide/sumx/"},
    {"source": "SQLBI", "url": "https://www.sqlbi.com/articles/optimizing-callbacks-in-a-sumx-iterator/"}
  ],
  "since": "2010-01",
  "deprecated": false
}
```

**Function categories:**
- `aggregation` — SUM, AVERAGE, COUNT, COUNTROWS, MIN, MAX, DISTINCTCOUNT, etc.
- `iterator` — SUMX, AVERAGEX, COUNTX, MAXX, MINX, PRODUCTX, RANKX, CONCATENATEX, etc.
- `filter` — CALCULATE, CALCULATETABLE, FILTER, ALL, ALLEXCEPT, ALLSELECTED, REMOVEFILTERS, KEEPFILTERS, VALUES, DISTINCT, etc.
- `table` — SUMMARIZE, SUMMARIZECOLUMNS, ADDCOLUMNS, SELECTCOLUMNS, GENERATE, CROSSJOIN, UNION, INTERSECT, EXCEPT, DATATABLE, etc.
- `relationship` — RELATED, RELATEDTABLE, USERELATIONSHIP, CROSSFILTER, TREATAS, LOOKUPVALUE, etc.
- `logical` — IF, SWITCH, AND, OR, NOT, COALESCE, TRUE, FALSE, etc.
- `text` — CONCATENATE, FORMAT, LEFT, RIGHT, MID, LEN, UPPER, LOWER, SUBSTITUTE, SEARCH, FIND, etc.
- `datetime` — DATE, TIME, YEAR, MONTH, DAY, HOUR, NOW, TODAY, EOMONTH, DATEDIFF, etc.
- `time_intelligence` — DATEADD, SAMEPERIODLASTYEAR, PARALLELPERIOD, TOTALYTD, TOTALQTD, TOTALMTD, DATESBETWEEN, DATESINPERIOD, STARTOFMONTH, ENDOFMONTH, FIRSTDATE, LASTDATE, LASTNONBLANK, CLOSINGBALANCEMONTH, etc.
- `math` — DIVIDE, ABS, ROUND, ROUNDUP, ROUNDDOWN, INT, CEILING, FLOOR, MOD, POWER, SQRT, LOG, EXP, etc.
- `statistical` — STDEV.S, STDEV.P, VAR.S, VAR.P, MEDIAN, PERCENTILE.INC, RANK, ROWNUMBER, etc.
- `info` — ISBLANK, ISERROR, ISINSCOPE, HASONEVALUE, SELECTEDVALUE, ISEMPTY, CONTAINS, etc.
- `parent_child` — PATH, PATHITEM, PATHITEMREVERSE, PATHLENGTH, PATHCONTAINS, etc.
- `conversion` — CONVERT, CURRENCY, VALUE, BLANK, ERROR, etc.
- `visual_calculation` — OFFSET, INDEX, WINDOW, MOVINGAVERAGE, RUNNINGSUM, PARTITIONBY, ORDERBY, ROWS, COLUMNS, etc. (2024+)
- `calculation_group` — SELECTEDMEASURE, SELECTEDMEASURENAME, SELECTEDMEASUREFORMATSTRING, ISSELECTEDMEASURE, etc.

**DaxFunctionDatabase API:**
```python
class DaxFunctionDatabase:
    _instance: Optional["DaxFunctionDatabase"] = None  # Singleton, loaded once

    @classmethod
    def get(cls) -> "DaxFunctionDatabase":
        """Lazy singleton — loaded on first access, shared across threads."""

    def lookup(self, name: str) -> Optional[DaxFunction]:
        """Case-insensitive lookup by function name."""

    def is_function(self, name: str) -> bool:
        """Check if name is a known DAX function."""

    def get_se_classification(self, name: str) -> str:
        """Returns: 'se_safe', 'fe_only', 'expression_dependent', 'unknown'"""

    def get_alternatives(self, name: str) -> List[Alternative]:
        """Get known optimized alternatives for a function."""

    def creates_row_context(self, name: str) -> bool:
        """True if function creates a new row context (iterators)."""

    def creates_filter_context(self, name: str) -> bool:
        """True if function creates/modifies filter context (CALCULATE, etc.)."""

    def get_by_category(self, category: str) -> List[DaxFunction]:
        """List all functions in a category."""

    def get_callback_risk(self, name: str) -> str:
        """Returns: 'none', 'low', 'medium', 'high', 'high_if_complex_expression'"""
```

### 4.3 Hybrid Rule System (`core/dax/knowledge/rules/` + `core/dax/analyzer/rules/`)

#### JSON Rules (simple pattern detection)

**Files:** `performance.json`, `correctness.json`, `maintainability.json`, `callback.json`

**JSON rule schema:**
```json
{
  "rule_id": "PERF_SUMX_FILTER",
  "category": "performance",
  "severity": "critical",
  "title": "SUMX(FILTER()) anti-pattern",
  "description": "Forces row-by-row FE evaluation, preventing query fusion and parallelization. 5-10x slower than CALCULATE.",
  "pattern_type": "function_nesting",
  "match": {
    "outer": ["SUMX", "AVERAGEX", "MINX", "MAXX", "COUNTX"],
    "inner": "FILTER",
    "position": "first_arg"
  },
  "fix_suggestion": "Replace with CALCULATE(AGG(Column), filter_condition)",
  "fix_template": "CALCULATE(${agg_func}(${column}), ${filter_condition})",
  "rewrite_strategy": "iterator_filter_to_calculate",
  "estimated_improvement": "5-10x",
  "references": [
    {"source": "Microsoft Learn", "url": "https://learn.microsoft.com/en-us/power-bi/guidance/dax-avoid-avoid-filter-as-filter-argument"},
    {"source": "SQLBI", "title": "Filter columns, not tables"}
  ],
  "vertipaq_escalation": {
    "condition": "table_rows > 1000000",
    "escalate_to": "critical",
    "message_suffix": "Table has {row_count} rows — severe impact expected."
  }
}
```

**Supported `pattern_type` values:**
- `function_nesting` — Function A contains function B (at specified argument position)
- `function_in_context` — Function A appears inside an iterator's expression argument
- `function_usage` — Function A is used at all (e.g., FORMAT, IFERROR)
- `missing_function` — Expected function not found (e.g., no DIVIDE for division)
- `bare_table_arg` — First arg of FILTER is a bare table reference
- `repeated_reference` — Same measure/expression referenced multiple times without VAR
- `nesting_depth` — Function nesting exceeds threshold
- `unused_var` — VAR defined but never referenced before RETURN
- `switch_without_default` — SWITCH missing else/default branch

**JSON rule evaluation** uses tokenizer output. Each `pattern_type` has a corresponding evaluator in `rule_engine.py` that matches tokens against the rule's `match` spec.

#### Python Rules (complex structural analysis)

**Files in `core/dax/analyzer/rules/`:**

**`iterator_rules.py`:**
- `NestedIteratorRule` — Detects iterator inside iterator (Cartesian product). Uses call tree depth.
- `IfSwitchInIteratorRule` — IF/SWITCH in iterator expression arg. Checks only the expression argument (2nd arg), not the table argument.
- `DivideInIteratorRule` — DIVIDE() in iterator creates CallbackDataID in SE queries.
- `CallbackPreAggregationRule` — Detects ROUND/FORMAT/string ops in iterators; suggests pre-aggregation with SUMMARIZE + smaller iteration set.
- `UnnecessaryIteratorRule` — SUMX(T, T[Col]) → SUM(T[Col]).
- `RelatedInIteratorRule` — RELATED() in iterator expression forces row-by-row relationship traversal.

**`calculate_rules.py`:**
- `NestedCalculateRule` — Multiple CALCULATE layers that could be flattened into one.
- `FilterTableNotColumnRule` — CALCULATE with FILTER(Table, ...) where column predicate would work. The single most impactful rule (117x measured improvement per SQLBI).
- `KeepfiltersOpportunityRule` — FILTER(VALUES(col), ...) patterns that could use KEEPFILTERS.
- `AllTableVsColumnRule` — ALL(Table) removes too many filters; suggest ALL(Table[Col]).
- `ValuesInCalculateRule` — Detects potentially unnecessary context transitions.

**`filter_rules.py`:**
- `FilterBareTableRule` — FILTER's first arg is a full table (not wrapped in ALL/VALUES etc.).
- `FilterAllMaterializationRule` — FILTER(ALL(...)) forces full materialization in memory.
- `IntersectVsTreatasRule` — INTERSECT for virtual relationships should use TREATAS (fewer materializations).
- `SummarizeInlineRule` — SUMMARIZE with inline expressions (deprecated, can produce incorrect results).
- `AddcolumnsSummarizeRule` — ADDCOLUMNS(SUMMARIZE(...)) should use SUMMARIZECOLUMNS.

**`context_rules.py`:**
- `VarDefeatingShortCircuitRule` — VAR with expensive expressions (CALCULATE/SUMX) before IF/SWITCH. Detects disconnected slicer patterns where all branches evaluate.
- `UnusedVarRule` — VAR defined but not referenced in RETURN or subsequent VARs.
- `MeasureRefWithoutVarRule` — Same measure referenced 3+ times without VAR caching.
- `ContextTransitionInIteratorRule` — Measure reference inside iterator creates context transition per row.
- `BlankPropagationRule` — `1 - (x/y)` pattern where BLANK propagation gives wrong results. Suggests `DIVIDE(x - y, y)`.

**`model_rules.py`:**
- `PrimaryKeyInSummarizeColumnsRule` — PK columns in SUMMARIZECOLUMNS force DENSE queries.
- `LookupvalueVsRelatedRule` — LOOKUPVALUE where physical relationship + RELATED would work.
- `SemiAdditivePatternRule` — Ranks semi-additive patterns (LASTDATE > MAX > LASTNONBLANK).
- `DirectMeasureReferenceRule` — Measure that's just `[OtherMeasure]` (pass-through).
- `FusionBreakRule` — Detects patterns that break vertical/horizontal fusion (limited relationships, type casts between SWITCH branches).
- `BiDirectionalHighCardinalityRule` — Bi-directional relationship on column with >100K cardinality.
- `FormatInCalcGroupRule` — FORMAT/SELECTEDMEASURE in calculation group format strings (double evaluation).
- `SwitchOptimizationRule` — Detects SWITCH patterns where indirect column filtering prevents optimization.

**Python rule base class:**
```python
class PythonRule(ABC):
    rule_id: str
    category: str          # "performance", "correctness", "maintainability"
    severity: str          # "critical", "high", "medium", "low", "info"
    requires_tier: int     # 1 = static only, 2 = needs VertiPaq, 3 = needs trace

    @abstractmethod
    def evaluate(self, tokens: List[Token], function_db: DaxFunctionDatabase,
                 context: Optional[AnalysisContext] = None) -> List[AnalysisIssue]:
        """Evaluate rule against tokenized DAX. Context provides VertiPaq/trace data when available."""
```

### 4.4 Unified Analyzer (`core/dax/analyzer/`)

**Files:**
- `unified_analyzer.py` — `DaxUnifiedAnalyzer` class
- `rule_engine.py` — Loads and evaluates JSON rules against token stream
- `rules/` — Python rule classes (see 4.3)

**DaxUnifiedAnalyzer API:**
```python
class DaxUnifiedAnalyzer:
    def __init__(self):
        """Loads function DB (singleton), JSON rules, Python rules."""

    def analyze(self, dax_expression: str,
                context: Optional[AnalysisContext] = None) -> UnifiedAnalysisResult:
        """
        Full analysis at the highest available tier.

        Args:
            dax_expression: DAX code to analyze
            context: Optional AnalysisContext with vertipaq_data, trace_data, model_info

        Returns:
            UnifiedAnalysisResult with issues, health_score, tier_used, rewrite_candidates
        """

    def analyze_batch(self, measures: List[MeasureInput],
                      context: Optional[AnalysisContext] = None) -> BatchAnalysisResult:
        """Analyze multiple measures efficiently (shared tokenizer/DB instances)."""
```

**AnalysisContext dataclass:**
```python
@dataclass
class AnalysisContext:
    """Encapsulates all optional enrichment data."""
    # Tier 2
    vertipaq_data: Optional[Dict[str, Any]] = None       # Column metrics from VertiPaq DMVs
    table_row_counts: Optional[Dict[str, int]] = None     # Table name → row count
    model_relationships: Optional[List[Dict]] = None      # Relationship metadata
    calculation_groups: Optional[List[Dict]] = None        # Calculation group info
    # Tier 3
    trace_data: Optional[Dict[str, Any]] = None           # SE/FE trace results
    # Metadata
    measure_name: Optional[str] = None                     # For context in messages
    table_name: Optional[str] = None
```

**UnifiedAnalysisResult dataclass:**
```python
@dataclass
class UnifiedAnalysisResult:
    success: bool
    issues: List[AnalysisIssue]
    health_score: int                        # 0-100
    tier_used: int                            # 1, 2, or 3
    total_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    rewrite_candidates: List[RewriteCandidate]  # Issues that have automated fixes
    summary: str
    tokens: Optional[List[Token]] = None     # Cached for rewriter use

    def to_best_practices_format(self) -> Dict[str, Any]:
        """Convert to DaxBestPracticesAnalyzer.analyze() return format."""

    def to_rules_engine_format(self) -> Dict[str, Any]:
        """Convert to DaxRulesEngine.analyze() return format."""

    def to_callback_format(self) -> Dict[str, Any]:
        """Convert to CallbackDetector.detect_dict() return format."""
```

**AnalysisIssue dataclass:**
```python
@dataclass
class AnalysisIssue:
    rule_id: str
    category: str
    severity: str
    title: str
    description: str
    fix_suggestion: str
    source: str                               # "static", "vertipaq", "trace"
    location: Optional[str] = None            # Token position / line number
    code_before: Optional[str] = None         # Example or actual code
    code_after: Optional[str] = None          # Suggested fix
    estimated_improvement: Optional[str] = None
    rewrite_strategy: Optional[str] = None    # Links to rewriter strategy
    references: Optional[List[Dict]] = None   # SQLBI/Microsoft Learn links
    confidence: str = "high"                  # "high", "medium", "low"
    vertipaq_detail: Optional[str] = None     # e.g., "Table has 5M rows"
    trace_detail: Optional[str] = None        # e.g., "Confirmed: 47 callbacks detected"
```

### 4.5 Optimization Pipeline (`core/dax/optimizer/`)

**Files:**
- `pipeline.py` — `OptimizationPipeline` class
- `rewrite_engine.py` — `DaxRewriteEngine` class (replaces code_rewriter.py internals)
- `measure_applier.py` — Bridges to existing measure CRUD
- `strategies/` — Rewrite strategy implementations
  - `__init__.py`
  - `variable_extraction.py` — Extract repeated expressions to VARs
  - `calculate_optimization.py` — Flatten nested CALCULATE, convert FILTER patterns
  - `iterator_optimization.py` — SUMX(FILTER)→CALCULATE, unnecessary iterator removal
  - `pattern_replacement.py` — HASONEVALUE→SELECTEDVALUE, INTERSECT→TREATAS, etc.
  - `callback_reduction.py` — Pre-aggregation strategies for CallbackDataID
  - `fusion_optimization.py` — Restructure to enable vertical/horizontal fusion

**OptimizationPipeline API:**
```python
class OptimizationPipeline:
    def __init__(self, connection_state=None):
        """
        Args:
            connection_state: Optional. Enables Tier 2/3 analysis and apply.
        """

    def optimize_measure(self, measure_name: str, table_name: str,
                         dry_run: bool = True) -> OptimizationResult:
        """
        Full pipeline for a single measure:
        1. Read current DAX from model (if connected) or accept expression directly
        2. Run unified analysis at highest available tier
        3. Generate rewrites for all fixable issues
        4. If not dry_run and connected: apply via existing measure CRUD
        """

    def optimize_expression(self, dax_expression: str,
                            context: Optional[AnalysisContext] = None) -> OptimizationResult:
        """
        Optimize a standalone DAX expression (no model connection needed).
        Pure Tier 1 unless context provides enrichment data.
        """

    def optimize_batch(self, measures: Optional[List[str]] = None,
                       severity_threshold: str = "high",
                       dry_run: bool = True) -> BatchOptimizationResult:
        """
        Batch optimization across model measures.
        If measures is None, optimizes all measures in the model.
        Only applies fixes for issues at or above severity_threshold.
        """
```

**OptimizationResult dataclass:**
```python
@dataclass
class OptimizationResult:
    success: bool
    measure_name: Optional[str]
    original_dax: str
    analysis: UnifiedAnalysisResult
    rewrites: List[RewriteResult]          # Each rewrite for each fixable issue
    final_dax: Optional[str]                # Combined rewritten DAX (all rewrites applied)
    applied: bool                           # True if pushed to model
    apply_error: Optional[str]              # Error if apply failed
    improvement_summary: str                # Human-readable summary
```

**DaxRewriteEngine:**
```python
class DaxRewriteEngine:
    def __init__(self, function_db: DaxFunctionDatabase):
        self.function_db = function_db
        self.strategies = load_rewrite_strategies()

    def rewrite(self, dax_expression: str, tokens: List[Token],
                issues: List[AnalysisIssue]) -> List[RewriteResult]:
        """
        Generate rewrites for all fixable issues.
        Each issue with a rewrite_strategy gets processed by the matching strategy.
        Returns individual RewriteResult per transformation.
        """

    def apply_rewrites(self, dax_expression: str,
                       rewrites: List[RewriteResult]) -> str:
        """Apply all rewrites in dependency order to produce final DAX."""

    def generate_variable_name(self, expression: str, context: str) -> str:
        """Generate meaningful variable name from expression content.
        E.g., [Sales Amount] → _SalesAmount, SUM(Sales[Qty]) → _TotalQty"""
```

**RewriteResult:**
```python
@dataclass
class RewriteResult:
    strategy: str                    # "variable_extraction", "calculate_optimization", etc.
    rule_id: str                     # Which rule triggered this rewrite
    original_fragment: str           # The specific code being rewritten
    rewritten_fragment: str          # The optimized version
    full_rewritten_dax: str          # Complete DAX with this single rewrite applied
    explanation: str                 # Human-readable explanation
    confidence: str                  # "high", "medium", "low"
    estimated_improvement: str       # "5-10x", "2-3x", "10-50%", etc.
    validation_passed: bool          # Re-tokenized successfully, structural integrity OK
```

**Rewrite strategy base class:**
```python
class RewriteStrategy(ABC):
    strategy_name: str

    @abstractmethod
    def can_apply(self, issue: AnalysisIssue, tokens: List[Token],
                  function_db: DaxFunctionDatabase) -> bool:
        """Check if this strategy can fix the given issue."""

    @abstractmethod
    def apply(self, dax: str, tokens: List[Token], issue: AnalysisIssue,
              function_db: DaxFunctionDatabase) -> RewriteResult:
        """Apply the rewrite and return result with validation."""
```

### 4.6 Backward-Compatible Facades

Existing classes are preserved but internally delegate to the unified engine.

**`dax_best_practices.py`** (facade):
```python
class DaxBestPracticesAnalyzer:
    """Preserved API. Internally delegates to DaxUnifiedAnalyzer."""

    def __init__(self):
        self._analyzer = DaxUnifiedAnalyzer()

    def analyze(self, dax_expression, context_analysis=None, vertipaq_analysis=None):
        """Same signature, same return format."""
        context = AnalysisContext(
            vertipaq_data=vertipaq_analysis,
            # Map old context_analysis dict to new format
        )
        result = self._analyzer.analyze(dax_expression, context)
        return result.to_best_practices_format()
```

**`dax_rules_engine.py`** (facade):
```python
class DaxRulesEngine:
    """Preserved API. Internally delegates to DaxUnifiedAnalyzer."""

    def __init__(self):
        self._analyzer = DaxUnifiedAnalyzer()

    def analyze(self, dax_expression):
        """Same signature, same return format (health_score, issues)."""
        result = self._analyzer.analyze(dax_expression)
        return result.to_rules_engine_format()
```

**`callback_detector.py`** (facade):
```python
class CallbackDetector:
    """Preserved API. Internally delegates to DaxUnifiedAnalyzer."""

    def __init__(self):
        self._analyzer = DaxUnifiedAnalyzer()

    def detect_dict(self, dax_expression):
        """Same signature, same return format."""
        result = self._analyzer.analyze(dax_expression)
        return result.to_callback_format()

    def detect(self, dax_expression):
        """Returns List[CallbackDetection] — preserved for internal consumers."""
        result = self._analyzer.analyze(dax_expression)
        return [CallbackDetection(...) for issue in result.issues
                if issue.rule_id.startswith("CB")]
```

**`code_rewriter.py`** (facade):
```python
class DaxCodeRewriter:
    """Preserved API. Internally delegates to DaxRewriteEngine."""

    def __init__(self):
        self._engine = DaxRewriteEngine(DaxFunctionDatabase.get())

    def rewrite_dax(self, dax_expression):
        """Same signature, same return format."""
        analyzer = DaxUnifiedAnalyzer()
        analysis = analyzer.analyze(dax_expression)
        rewrites = self._engine.rewrite(dax_expression, analysis.tokens, analysis.issues)
        # Map to legacy format
        return {
            "success": True,
            "has_changes": bool(rewrites),
            "original_code": dax_expression,
            "rewritten_code": self._engine.apply_rewrites(dax_expression, rewrites) if rewrites else None,
            "transformations": [self._map_to_legacy(r) for r in rewrites],
            "transformation_count": len(rewrites),
        }
```

**`dax_utilities.py`** — functions refactored to use tokenizer internally but signatures unchanged:
- `normalize_dax(dax)` → uses `DaxLexer().tokenize_code()` to strip comments, returns joined values
- `extract_function_body(dax, pos)` → uses tokenizer for correct paren matching
- `find_matching_paren(dax, pos)` → uses tokenizer paren map
- `extract_variables(dax)` → scans for KEYWORD(VAR) tokens
- `get_line_column(dax, pos)` → unchanged (position-based, no tokenizer needed)
- `validate_dax_identifier(name)` → unchanged

### 4.7 Integration Wiring

**VertiPaq → Rule Severity Escalation:**
Rules can declare `vertipaq_escalation` in their JSON definition. When VertiPaq data is available:
- `table_rows > N` → escalate severity and append row count to message
- `column_cardinality > N` → escalate and note cardinality
- `encoding_type == "hash"` → note poor compression

**Function DB → Everywhere:**
- Tokenizer uses it to classify FUNCTION vs IDENTIFIER tokens
- Rules use it to check SE/FE classification, parameter types, alternatives
- Rewriter uses it to verify function signatures in generated code
- Call tree builder uses it to know which functions create row context

**Analysis → Rewriter → Applier Flow:**
```
measure_name
    ↓
[read from model via existing measure_operations]
    ↓
dax_expression
    ↓
[DaxLexer.tokenize()]
    ↓
tokens
    ↓
[DaxUnifiedAnalyzer.analyze(tokens, context)]
    ↓
UnifiedAnalysisResult (issues + rewrite_candidates)
    ↓
[DaxRewriteEngine.rewrite(dax, tokens, issues)]
    ↓
List[RewriteResult]
    ↓
[DaxRewriteEngine.apply_rewrites(dax, rewrites)]
    ↓
optimized_dax
    ↓
[measure_applier → dax_injector.upsert_measure() / measure_operations]
    ↓
applied to model
```

## 5. New Directory Structure

```
core/dax/
├── tokenizer/
│   ├── __init__.py              # Exports DaxLexer, Token, TokenType
│   ├── tokens.py                # ~60 LOC — Token dataclass, TokenType enum
│   └── lexer.py                 # ~350 LOC — DaxLexer implementation
│
├── knowledge/
│   ├── __init__.py              # Exports DaxFunctionDatabase, DaxFunction
│   ├── function_db.py           # ~200 LOC — Database class, lazy singleton
│   ├── functions.json           # ~3000 LOC — 200+ function definitions
│   └── rules/
│       ├── performance.json     # ~30 rules
│       ├── correctness.json     # ~15 rules
│       ├── maintainability.json # ~15 rules
│       └── callback.json        # ~10 rules (~70 JSON rules total)
│
├── analyzer/
│   ├── __init__.py              # Exports DaxUnifiedAnalyzer, AnalysisIssue, etc.
│   ├── unified_analyzer.py      # ~250 LOC — Main analyzer class
│   ├── rule_engine.py           # ~300 LOC — JSON rule loader + evaluators
│   ├── models.py                # ~150 LOC — Dataclasses (AnalysisContext, UnifiedAnalysisResult, etc.)
│   └── rules/
│       ├── __init__.py           # Auto-discovers and loads all Python rules
│       ├── base.py               # ~40 LOC — PythonRule ABC
│       ├── iterator_rules.py     # ~250 LOC — 6 rules
│       ├── calculate_rules.py    # ~200 LOC — 5 rules
│       ├── filter_rules.py       # ~200 LOC — 5 rules
│       ├── context_rules.py      # ~200 LOC — 5 rules
│       └── model_rules.py        # ~250 LOC — 8 rules
│
├── optimizer/
│   ├── __init__.py              # Exports OptimizationPipeline, etc.
│   ├── pipeline.py              # ~200 LOC — OptimizationPipeline class
│   ├── rewrite_engine.py        # ~250 LOC — DaxRewriteEngine class
│   ├── measure_applier.py       # ~100 LOC — Bridge to existing measure CRUD
│   ├── models.py                # ~100 LOC — OptimizationResult, RewriteResult, etc.
│   └── strategies/
│       ├── __init__.py           # Auto-discovers strategies
│       ├── base.py               # ~30 LOC — RewriteStrategy ABC
│       ├── variable_extraction.py      # ~150 LOC
│       ├── calculate_optimization.py   # ~200 LOC
│       ├── iterator_optimization.py    # ~150 LOC
│       ├── pattern_replacement.py      # ~150 LOC
│       ├── callback_reduction.py       # ~150 LOC
│       └── fusion_optimization.py      # ~100 LOC
│
├── # EXISTING FILES — preserved as facades
├── __init__.py                  # Updated: adds new exports, keeps all existing
├── analysis_pipeline.py         # Updated: adds run_optimization_pipeline(), keeps existing 4 functions
├── dax_best_practices.py        # Refactored: facade delegating to unified_analyzer
├── dax_rules_engine.py          # Refactored: facade delegating to unified_analyzer
├── callback_detector.py         # Refactored: facade delegating to unified_analyzer
├── code_rewriter.py             # Refactored: facade delegating to optimizer/rewrite_engine
├── dax_utilities.py             # Refactored: uses tokenizer internally, same signatures
├── context_analyzer.py          # Updated: uses tokenizer for pattern detection
├── context_debugger.py          # Updated: uses tokenizer, improved optimization suggestions
├── call_tree_builder.py         # Updated: uses tokenizer + function_db for classification
├── vertipaq_analyzer.py         # Unchanged
├── se_event_analyzer.py         # Unchanged
├── dax_injector.py              # Unchanged
├── dax_validator.py             # Updated: uses tokenizer for structural validation
├── dax_reference_parser.py      # Updated: uses tokenizer for reference extraction
├── context_visualizer.py        # Unchanged
├── visual_flow.py               # Unchanged
├── vertipaq_storage_report.py   # Unchanged
├── calculation_group_analyzer.py # Unchanged
```

## 6. New Rule Inventory

### Rules from research NOT currently in codebase (~25 additions):

| Rule ID | Category | Severity | Description |
|---------|----------|----------|-------------|
| PERF_LOOKUPVALUE_VS_RELATED | performance | high | LOOKUPVALUE where RELATED would work (physical relationship exists) |
| PERF_PK_IN_SUMMARIZECOLUMNS | performance | high | PK columns in SUMMARIZECOLUMNS force DENSE queries |
| PERF_SEMI_ADDITIVE_RANKING | performance | medium | Suboptimal semi-additive pattern (LASTNONBLANK when LASTDATE would work) |
| PERF_FORMAT_IN_CALC_GROUP | performance | high | FORMAT/SELECTEDMEASURE in calc group format string (double eval) |
| PERF_SWITCH_INDIRECT_FILTER | performance | medium | SWITCH optimization broken by indirect column filtering |
| PERF_FUSION_BREAK_LIMITED_REL | performance | medium | Fusion disabled due to limited relationship |
| PERF_FUSION_BREAK_TYPE_CAST | performance | medium | Implicit type cast between SWITCH branches breaks fusion |
| PERF_BIDIR_HIGH_CARDINALITY | performance | high | Bi-directional relationship on >100K cardinality column |
| PERF_MANY_TO_MANY_SCALE | performance | high | Many-to-many relationship (20x SE CPU cost at scale) |
| PERF_DENSE_BLANK_CONVERSION | performance | medium | Converting BLANK to 0 forces dense evaluation |
| PERF_CALCULATE_FILTER_COLUMN | performance | critical | Filter entire table in CALCULATE instead of column (117x measured) |
| PERF_COUNTROWS_DISTINCT_VS_DISTINCTCOUNT | performance | low | COUNTROWS(DISTINCT(col)) → DISTINCTCOUNT(col) |
| PERF_EARLIER_DEPRECATED | maintainability | medium | EARLIER/EARLIEST deprecated — use VAR |
| CORR_BLANK_PROPAGATION_1_MINUS | correctness | high | 1-(x/y) pattern: BLANK propagation gives wrong results |
| CORR_INTERSECT_VS_TREATAS | performance | medium | INTERSECT for virtual rel → TREATAS (fewer materializations) |
| CORR_SUMMARIZE_INLINE_DEPRECATED | correctness | high | SUMMARIZE with inline expressions (deprecated, can be wrong) |
| MAINT_QUALIFY_COLUMNS | maintainability | medium | Column reference not fully qualified ('Table'[Col]) |
| MAINT_UNQUALIFY_MEASURES | maintainability | medium | Measure reference should not use table prefix |
| MAINT_DIRECT_MEASURE_REF | maintainability | low | Measure is just [OtherMeasure] (pass-through) |
| MAINT_NONDESCRIPTIVE_VARS | maintainability | low | Variable names like V1, V2, A, B |
| MAINT_FORMAT_STRING_MISSING | maintainability | medium | Visible measure without format string |
| PERF_CALLBACK_PRE_AGGREGATE | performance | high | ROUND/FORMAT in iterator — suggest pre-aggregation |
| PERF_SUMMARIZECOLUMNS_IN_MEASURE | info | low | SUMMARIZECOLUMNS now usable in measures (2025+) |
| PERF_UNUSED_VAR_EVALUATED | performance | medium | Unused VAR still evaluated — remove or use |
| PERF_VAR_EXPENSIVE_BEFORE_SWITCH | performance | high | VAR with CALCULATE/SUMX before SWITCH defeats short-circuit |

### Existing rules consolidated (deduplicated from 3 sources):

The ~35 existing rules across `dax_best_practices.py` (28 checks), `dax_rules_engine.py` (10 rules), and `callback_detector.py` (6 rules) have significant overlap. After deduplication: ~30 unique rules. Combined with ~25 new = **~55 Python rules + ~25 JSON rules = ~80 total rules**.

## 7. Handler Integration (Optional Follow-up)

After the core engine is built and all facades are working, handlers can optionally be updated to use new capabilities:

**`dax_context_handler.py` (05_DAX_Intelligence):**
- New `optimize` operation: calls `OptimizationPipeline.optimize_measure()` or `.optimize_expression()`
- Existing operations (`analyze`, `debug`, etc.) work unchanged via facades

**`debug_handler.py` (09_Debug_Operations.optimize):**
- Currently calls `CallbackDetector`, `DaxBestPracticesAnalyzer`, `DaxCodeRewriter` separately
- Could call `OptimizationPipeline.optimize_expression()` for unified results
- But existing separate calls continue working via facades

**`analysis_pipeline.py`:**
- New function: `run_optimization_pipeline(expression, connection_state, dry_run)` → calls `OptimizationPipeline`
- Existing 4 functions unchanged

## 8. Testing Strategy

- **Tokenizer tests:** Known DAX expressions → expected token streams. Edge cases: nested strings, escaped quotes, multiline comments, table names with special chars.
- **Function DB tests:** Lookup coverage, category classification, SE/FE checks.
- **Rule tests:** Each rule tested with known-bad and known-good DAX expressions. Regression tests: current analysis results should not degrade.
- **Facade tests:** Each facade produces identical output format to the original class.
- **Rewriter tests:** Known anti-patterns → expected rewrites. Validation: rewritten DAX re-tokenizes successfully.
- **Pipeline tests:** End-to-end measure optimization with mock connection state.
- **Backward compat tests:** Existing handler test fixtures still pass.

## 9. Phasing

**Phase 1 — Foundation (tokenizer + function DB + models):**
- `core/dax/tokenizer/` — complete
- `core/dax/knowledge/function_db.py` + `functions.json` — complete
- `core/dax/analyzer/models.py` — dataclasses
- Tests for tokenizer and function DB

**Phase 2 — Unified Analyzer + Rules:**
- `core/dax/analyzer/` — unified analyzer + rule engine + all Python rules
- `core/dax/knowledge/rules/` — all JSON rules
- Facades for `dax_best_practices.py`, `dax_rules_engine.py`, `callback_detector.py`
- Refactor `dax_utilities.py` to use tokenizer
- Tests for rules and facades

**Phase 3 — Optimizer Pipeline + Rewriter:**
- `core/dax/optimizer/` — pipeline, rewrite engine, strategies
- Facade for `code_rewriter.py`
- `analysis_pipeline.py` — add `run_optimization_pipeline()`
- Tests for rewriter strategies and pipeline

**Phase 4 — Integration + Polish:**
- Wire VertiPaq escalation into rules
- Update `context_analyzer.py`, `call_tree_builder.py`, `dax_reference_parser.py` to use tokenizer
- Optional handler improvements
- Comprehensive regression testing

## 10. Frozen API Contracts

These signatures MUST NOT change:

```python
# Constructors
DaxBestPracticesAnalyzer()
DaxRulesEngine()
CallbackDetector()
DaxCodeRewriter()
DaxContextAnalyzer()
VertiPaqAnalyzer(connection_state)
CallTreeBuilder()
DaxContextDebugger(config=None)
CalculationGroupAnalyzer(connection_state)

# Methods
DaxBestPracticesAnalyzer().analyze(dax_expression, context_analysis=None, vertipaq_analysis=None) -> Dict
DaxRulesEngine().analyze(dax_expression) -> Dict
CallbackDetector().detect_dict(dax_expression) -> Dict
CallbackDetector().detect(dax_expression) -> List[CallbackDetection]
DaxCodeRewriter().rewrite_dax(dax_expression) -> Dict
DaxContextAnalyzer().analyze_context_transitions(expression) -> ContextFlowExplanation
VertiPaqAnalyzer(cs).analyze_dax_columns(expression) -> Dict
CallTreeBuilder().build_call_tree(expression) -> CallTreeNode
CallTreeBuilder().visualize_tree(node) -> str
DaxContextDebugger(cfg).step_through(expression, breakpoints=None, sample_data=None) -> List
DaxContextDebugger(cfg).generate_debug_report(expression, ...) -> Dict
DaxContextDebugger(cfg).generate_improved_dax(expression, ...) -> Dict

# Pipeline helpers
run_context_analysis(expression) -> Tuple[Optional, Optional[Dict]]
run_vertipaq_analysis(expression, conn_state) -> Optional[Dict]
run_best_practices(expression, context_analysis=None, vertipaq_analysis=None) -> Optional[Dict]
run_call_tree(expression, conn_state=None) -> Optional[Dict]

# __init__.py exports — all 52 current exports preserved
```

## 11. Out of Scope

- Full DAX parser/AST (tokenizer is sufficient)
- DirectQuery-specific optimization
- Power BI Service API integration
- DAX query generation for reports (visual_query_builder is separate)
- Changes to SVG template system
- Changes to TMDL/PBIP subsystems (except as consumers of improved analysis)
