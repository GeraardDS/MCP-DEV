# DAX Engine Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul all DAX analysis, optimization, and rewriting in MCP-PowerBi-Finvision with a proper tokenizer, comprehensive knowledge base, unified analyzer, and end-to-end optimization pipeline — zero breaking changes.

**Architecture:** 4 new subpackages under `core/dax/` (tokenizer, knowledge, analyzer, optimizer) with existing files becoming thin facades. All existing class constructors and method signatures frozen. New capabilities are additive.

**Tech Stack:** Python 3.10+, pytest, dataclasses, JSON config files, existing pythonnet/.NET interop unchanged.

**Spec:** `docs/superpowers/specs/2026-04-07-dax-engine-overhaul-design.md`

---

## Phase 1: DAX Tokenizer + Function Knowledge Base

### Task 1: Token Types and Dataclass

**Files:**
- Create: `core/dax/tokenizer/__init__.py`
- Create: `core/dax/tokenizer/tokens.py`
- Test: `tests/test_dax_tokenizer.py`

- [ ] **Step 1: Write test for token types**

```python
# tests/test_dax_tokenizer.py
"""Tests for DAX tokenizer — token types and lexer."""

import pytest
from core.dax.tokenizer.tokens import Token, TokenType


class TestTokenType:
    def test_all_expected_types_exist(self):
        expected = [
            "KEYWORD", "FUNCTION", "IDENTIFIER", "TABLE_REF", "COLUMN_REF",
            "QUALIFIED_REF", "STRING", "NUMBER", "OPERATOR", "PAREN_OPEN",
            "PAREN_CLOSE", "COMMA", "COMMENT_LINE", "COMMENT_BLOCK",
            "WHITESPACE", "NEWLINE", "DOT", "UNKNOWN",
        ]
        for name in expected:
            assert hasattr(TokenType, name), f"Missing TokenType.{name}"

    def test_token_dataclass_fields(self):
        t = Token(
            type=TokenType.KEYWORD,
            value="VAR",
            start=0,
            end=3,
            line=1,
            col=1,
        )
        assert t.type == TokenType.KEYWORD
        assert t.value == "VAR"
        assert t.start == 0
        assert t.end == 3
        assert t.line == 1
        assert t.col == 1

    def test_token_is_frozen(self):
        t = Token(type=TokenType.KEYWORD, value="VAR", start=0, end=3, line=1, col=1)
        with pytest.raises(AttributeError):
            t.value = "RETURN"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dax_tokenizer.py::TestTokenType -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement tokens.py**

```python
# core/dax/tokenizer/tokens.py
"""DAX token types and Token dataclass."""

from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    """DAX token classification."""
    KEYWORD = auto()        # VAR, RETURN, IF, ELSE, SWITCH, TRUE, FALSE, etc.
    FUNCTION = auto()       # Known DAX function name followed by (
    IDENTIFIER = auto()     # Unquoted name not classified as KEYWORD/FUNCTION
    TABLE_REF = auto()      # 'Quoted Table Name'
    COLUMN_REF = auto()     # [Column or Measure] (brackets included)
    QUALIFIED_REF = auto()  # 'Table'[Column] (composite)
    STRING = auto()         # "double quoted" with "" escape
    NUMBER = auto()         # Integer and decimal literals
    OPERATOR = auto()       # + - * / = <> < > <= >= && || &
    PAREN_OPEN = auto()     # (
    PAREN_CLOSE = auto()    # )
    COMMA = auto()          # ,
    COMMENT_LINE = auto()   # // to end of line
    COMMENT_BLOCK = auto()  # /* ... */
    WHITESPACE = auto()     # Spaces, tabs
    NEWLINE = auto()        # \n, \r\n
    DOT = auto()            # . (for STDEVX.S etc.)
    UNKNOWN = auto()        # Unrecognized


@dataclass(frozen=True, slots=True)
class Token:
    """A single DAX token with position information."""
    type: TokenType
    value: str
    start: int     # Char offset in source (0-based)
    end: int       # Char offset exclusive
    line: int      # 1-based line number
    col: int       # 1-based column number
```

```python
# core/dax/tokenizer/__init__.py
"""DAX Tokenizer — lightweight lexer producing typed token streams."""

from .tokens import Token, TokenType

__all__ = ["Token", "TokenType"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dax_tokenizer.py::TestTokenType -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/dax/tokenizer/ tests/test_dax_tokenizer.py
git commit -m "feat(dax): add Token dataclass and TokenType enum"
```

---

### Task 2: DAX Lexer — Core Tokenization

**Files:**
- Create: `core/dax/tokenizer/lexer.py`
- Modify: `core/dax/tokenizer/__init__.py`
- Test: `tests/test_dax_tokenizer.py`

- [ ] **Step 1: Write lexer tests**

Add to `tests/test_dax_tokenizer.py`:

```python
from core.dax.tokenizer.lexer import DaxLexer


class TestDaxLexerBasic:
    """Basic tokenization of simple DAX expressions."""

    @pytest.fixture
    def lexer(self):
        return DaxLexer()

    def test_simple_sum(self, lexer):
        tokens = lexer.tokenize("SUM(Sales[Amount])")
        code = [t for t in tokens if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE)]
        assert code[0].type == TokenType.IDENTIFIER  # SUM (no function_db → IDENTIFIER)
        assert code[0].value == "SUM"
        assert code[1].type == TokenType.PAREN_OPEN
        assert code[2].type == TokenType.IDENTIFIER  # Sales
        assert code[3].type == TokenType.COLUMN_REF
        assert code[3].value == "[Amount]"
        assert code[4].type == TokenType.PAREN_CLOSE

    def test_var_return(self, lexer):
        tokens = lexer.tokenize("VAR x = 42\nRETURN x")
        code = [t for t in tokens if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE)]
        assert code[0].type == TokenType.KEYWORD
        assert code[0].value == "VAR"
        assert code[1].type == TokenType.IDENTIFIER
        assert code[1].value == "x"
        assert code[2].type == TokenType.OPERATOR
        assert code[2].value == "="
        assert code[3].type == TokenType.NUMBER
        assert code[3].value == "42"
        assert code[4].type == TokenType.KEYWORD
        assert code[4].value == "RETURN"

    def test_string_literal(self, lexer):
        tokens = lexer.tokenize('"Hello ""World"""')
        code = [t for t in tokens if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE)]
        assert code[0].type == TokenType.STRING
        assert code[0].value == '"Hello ""World"""'

    def test_table_ref(self, lexer):
        tokens = lexer.tokenize("'My Table'[Column]")
        code = [t for t in tokens if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE)]
        # Should produce QUALIFIED_REF (composite of table + column)
        assert code[0].type == TokenType.QUALIFIED_REF
        assert "'My Table'" in code[0].value
        assert "[Column]" in code[0].value

    def test_line_comment(self, lexer):
        tokens = lexer.tokenize("VAR x = 1 // comment\nRETURN x")
        comments = [t for t in tokens if t.type == TokenType.COMMENT_LINE]
        assert len(comments) == 1
        assert "comment" in comments[0].value

    def test_block_comment(self, lexer):
        tokens = lexer.tokenize("/* multi\nline */ VAR x = 1")
        comments = [t for t in tokens if t.type == TokenType.COMMENT_BLOCK]
        assert len(comments) == 1
        assert "multi" in comments[0].value

    def test_operators(self, lexer):
        tokens = lexer.tokenize("1 + 2 - 3 * 4 / 5 <> 6 >= 7 <= 8 && 9 || 10")
        ops = [t for t in tokens if t.type == TokenType.OPERATOR]
        assert [o.value for o in ops] == ["+", "-", "*", "/", "<>", ">=", "<=", "&&", "||"]

    def test_tokenize_code_strips_comments_and_whitespace(self, lexer):
        tokens = lexer.tokenize_code("VAR x = 1 // comment\nRETURN x")
        assert all(t.type not in (TokenType.COMMENT_LINE, TokenType.COMMENT_BLOCK,
                                   TokenType.WHITESPACE, TokenType.NEWLINE) for t in tokens)

    def test_decimal_number(self, lexer):
        tokens = lexer.tokenize("3.14")
        code = [t for t in tokens if t.type == TokenType.NUMBER]
        assert len(code) == 1
        assert code[0].value == "3.14"

    def test_position_tracking(self, lexer):
        tokens = lexer.tokenize("VAR\n  x = 1")
        var_token = tokens[0]
        assert var_token.line == 1
        assert var_token.col == 1
        # Find 'x' token
        x_tokens = [t for t in tokens if t.value == "x"]
        assert x_tokens[0].line == 2


class TestDaxLexerEdgeCases:
    """Edge cases: escaped quotes, nested strings, special chars."""

    @pytest.fixture
    def lexer(self):
        return DaxLexer()

    def test_escaped_double_quotes_in_string(self, lexer):
        """Escaped "" inside string should not end the string early."""
        dax = 'FORMAT(1234, "#,##0.00")'
        tokens = lexer.tokenize_code(dax)
        strings = [t for t in tokens if t.type == TokenType.STRING]
        assert len(strings) == 1
        assert strings[0].value == '"#,##0.00"'

    def test_escaped_single_quotes_in_table_ref(self, lexer):
        """Escaped '' inside table ref should not end the ref early."""
        dax = "'It''s a Table'[Col]"
        tokens = lexer.tokenize_code(dax)
        qrefs = [t for t in tokens if t.type == TokenType.QUALIFIED_REF]
        assert len(qrefs) == 1
        assert "It''s a Table" in qrefs[0].value

    def test_sumx_inside_string_not_function(self, lexer):
        """SUMX inside a string literal should NOT be classified as function."""
        dax = '"SUMX is great"'
        tokens = lexer.tokenize_code(dax)
        assert all(t.type != TokenType.FUNCTION for t in tokens)
        assert tokens[0].type == TokenType.STRING

    def test_comment_inside_string_not_stripped(self, lexer):
        """// inside string should not be treated as comment."""
        dax = '"Price // per unit"'
        tokens = lexer.tokenize_code(dax)
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.STRING

    def test_dotted_function_name(self, lexer):
        """STDEVX.S should be tokenized as IDENTIFIER + DOT + IDENTIFIER."""
        dax = "STDEVX.S(Table, [Col])"
        tokens = lexer.tokenize_code(dax)
        # The first few tokens: STDEVX, DOT, S, PAREN_OPEN, ...
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "STDEVX"
        assert tokens[1].type == TokenType.DOT
        assert tokens[2].type == TokenType.IDENTIFIER
        assert tokens[2].value == "S"

    def test_empty_expression(self, lexer):
        tokens = lexer.tokenize("")
        assert tokens == []

    def test_only_whitespace(self, lexer):
        tokens = lexer.tokenize("   \n  \t  ")
        code = lexer.tokenize_code("   \n  \t  ")
        assert code == []

    def test_measure_ref_standalone(self, lexer):
        """[Sales Amount] without table prefix is COLUMN_REF."""
        tokens = lexer.tokenize_code("[Sales Amount]")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.COLUMN_REF
        assert tokens[0].value == "[Sales Amount]"

    def test_comma_separated(self, lexer):
        tokens = lexer.tokenize_code("a, b, c")
        commas = [t for t in tokens if t.type == TokenType.COMMA]
        assert len(commas) == 2


class TestDaxLexerHelpers:
    """Tests for paren map and function arg extraction."""

    @pytest.fixture
    def lexer(self):
        return DaxLexer()

    def test_build_paren_map(self, lexer):
        tokens = lexer.tokenize_code("SUM(CALCULATE([A], Filter))")
        pmap = lexer.build_paren_map(tokens)
        # Find the outer PAREN_OPEN (after SUM)
        open_indices = [i for i, t in enumerate(tokens) if t.type == TokenType.PAREN_OPEN]
        close_indices = [i for i, t in enumerate(tokens) if t.type == TokenType.PAREN_CLOSE]
        # Outer open maps to outer close
        assert pmap[open_indices[0]] == close_indices[-1]
        # Inner open maps to inner close
        assert pmap[open_indices[1]] == close_indices[-2]

    def test_extract_function_args(self, lexer):
        tokens = lexer.tokenize_code("CALCULATE([Sales], Filter1, Filter2)")
        # First token is CALCULATE (index 0), second is PAREN_OPEN (index 1)
        func_idx = 0
        args = lexer.extract_function_args(tokens, func_idx)
        assert len(args) == 3
        # First arg should contain [Sales]
        assert any(t.type == TokenType.COLUMN_REF for t in args[0])
        # Second arg should contain Filter1
        assert any(t.value == "Filter1" for t in args[1])
        # Third arg should contain Filter2
        assert any(t.value == "Filter2" for t in args[2])

    def test_extract_function_args_nested(self, lexer):
        """Nested function calls should not split on inner commas."""
        tokens = lexer.tokenize_code("SUMX(FILTER(T, T[A] > 1), T[B])")
        args = lexer.extract_function_args(tokens, 0)
        assert len(args) == 2  # FILTER(...) and T[B], not split on inner comma
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dax_tokenizer.py -v`
Expected: FAIL with ImportError for DaxLexer

- [ ] **Step 3: Implement lexer.py**

```python
# core/dax/tokenizer/lexer.py
"""DAX Lexer — single-pass tokenizer producing typed token streams."""

import re
from typing import Dict, List, Optional, Set

from .tokens import Token, TokenType

# DAX keywords (not functions — these never take parentheses as part of their syntax)
_KEYWORDS: Set[str] = {
    "VAR", "RETURN", "IF", "ELSE", "SWITCH", "TRUE", "FALSE",
    "AND", "OR", "NOT", "IN", "EVALUATE", "DEFINE", "MEASURE",
    "ORDER", "BY", "ASC", "DESC", "COLUMN", "TABLE", "START", "AT",
}

# Multi-char operators, longest first for greedy matching
_MULTI_OPERATORS = ("<=", ">=", "<>", "&&", "||")
_SINGLE_OPERATORS = frozenset("+-*/=<>&|")

# Pre-compiled patterns for number detection
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


class DaxLexer:
    """Lightweight DAX lexer. Single-pass, O(n)."""

    def __init__(self, function_names: Optional[Set[str]] = None):
        """
        Args:
            function_names: Optional set of known DAX function names (uppercase).
                If provided, identifiers matching these AND followed by '(' get
                classified as FUNCTION. If None, no FUNCTION tokens are emitted
                (all become IDENTIFIER).
        """
        self._function_names = function_names or set()

    def tokenize(self, dax: str) -> List[Token]:
        """Tokenize DAX into full token stream including whitespace and comments."""
        tokens: List[Token] = []
        pos = 0
        length = len(dax)
        line = 1
        col = 1

        while pos < length:
            ch = dax[pos]

            # --- Newline ---
            if ch == "\n":
                tokens.append(Token(TokenType.NEWLINE, "\n", pos, pos + 1, line, col))
                pos += 1
                line += 1
                col = 1
                continue
            if ch == "\r":
                if pos + 1 < length and dax[pos + 1] == "\n":
                    tokens.append(Token(TokenType.NEWLINE, "\r\n", pos, pos + 2, line, col))
                    pos += 2
                else:
                    tokens.append(Token(TokenType.NEWLINE, "\r", pos, pos + 1, line, col))
                    pos += 1
                line += 1
                col = 1
                continue

            # --- Whitespace ---
            if ch in " \t":
                start = pos
                start_col = col
                while pos < length and dax[pos] in " \t":
                    pos += 1
                    col += 1
                tokens.append(Token(TokenType.WHITESPACE, dax[start:pos], start, pos, line, start_col))
                continue

            # --- Line comment ---
            if ch == "/" and pos + 1 < length and dax[pos + 1] == "/":
                start = pos
                start_col = col
                pos += 2
                col += 2
                while pos < length and dax[pos] != "\n":
                    pos += 1
                    col += 1
                tokens.append(Token(TokenType.COMMENT_LINE, dax[start:pos], start, pos, line, start_col))
                continue

            # --- Block comment ---
            if ch == "/" and pos + 1 < length and dax[pos + 1] == "*":
                start = pos
                start_line = line
                start_col = col
                pos += 2
                col += 2
                while pos < length:
                    if dax[pos] == "*" and pos + 1 < length and dax[pos + 1] == "/":
                        pos += 2
                        col += 2
                        break
                    if dax[pos] == "\n":
                        line += 1
                        col = 1
                    else:
                        col += 1
                    pos += 1
                tokens.append(Token(TokenType.COMMENT_BLOCK, dax[start:pos], start, pos, start_line, start_col))
                continue

            # --- String literal "..." ---
            if ch == '"':
                start = pos
                start_col = col
                pos += 1
                col += 1
                while pos < length:
                    if dax[pos] == '"':
                        if pos + 1 < length and dax[pos + 1] == '"':
                            pos += 2  # Escaped ""
                            col += 2
                            continue
                        pos += 1
                        col += 1
                        break
                    if dax[pos] == "\n":
                        line += 1
                        col = 1
                    else:
                        col += 1
                    pos += 1
                tokens.append(Token(TokenType.STRING, dax[start:pos], start, pos, line, start_col))
                continue

            # --- Table reference 'Name' possibly followed by [Column] ---
            if ch == "'":
                start = pos
                start_col = col
                start_line = line
                pos += 1
                col += 1
                while pos < length:
                    if dax[pos] == "'":
                        if pos + 1 < length and dax[pos + 1] == "'":
                            pos += 2  # Escaped ''
                            col += 2
                            continue
                        pos += 1
                        col += 1
                        break
                    if dax[pos] == "\n":
                        line += 1
                        col = 1
                    else:
                        col += 1
                    pos += 1
                table_end = pos
                # Check for adjacent [Column] — makes it QUALIFIED_REF
                if pos < length and dax[pos] == "[":
                    col_start = pos
                    pos += 1
                    col += 1
                    while pos < length and dax[pos] != "]":
                        pos += 1
                        col += 1
                    if pos < length:
                        pos += 1  # Skip ]
                        col += 1
                    tokens.append(Token(TokenType.QUALIFIED_REF, dax[start:pos], start, pos, start_line, start_col))
                else:
                    tokens.append(Token(TokenType.TABLE_REF, dax[start:table_end], start, table_end, start_line, start_col))
                continue

            # --- Column/measure reference [Name] ---
            if ch == "[":
                start = pos
                start_col = col
                pos += 1
                col += 1
                while pos < length and dax[pos] != "]":
                    pos += 1
                    col += 1
                if pos < length:
                    pos += 1  # Skip ]
                    col += 1
                tokens.append(Token(TokenType.COLUMN_REF, dax[start:pos], start, pos, line, start_col))
                continue

            # --- Number ---
            if ch.isdigit():
                start = pos
                start_col = col
                m = _NUMBER_RE.match(dax, pos)
                if m:
                    pos = m.end()
                    col += m.end() - start
                    tokens.append(Token(TokenType.NUMBER, m.group(), start, pos, line, start_col))
                else:
                    pos += 1
                    col += 1
                    tokens.append(Token(TokenType.NUMBER, ch, start, pos, line, start_col))
                continue

            # --- Parentheses ---
            if ch == "(":
                tokens.append(Token(TokenType.PAREN_OPEN, "(", pos, pos + 1, line, col))
                pos += 1
                col += 1
                continue
            if ch == ")":
                tokens.append(Token(TokenType.PAREN_CLOSE, ")", pos, pos + 1, line, col))
                pos += 1
                col += 1
                continue

            # --- Comma ---
            if ch == ",":
                tokens.append(Token(TokenType.COMMA, ",", pos, pos + 1, line, col))
                pos += 1
                col += 1
                continue

            # --- Dot ---
            if ch == ".":
                # Check if this is a decimal number like .5
                if pos + 1 < length and dax[pos + 1].isdigit():
                    start = pos
                    start_col = col
                    m = _NUMBER_RE.match(dax, pos)
                    if m:
                        pos = m.end()
                        col += m.end() - start
                        tokens.append(Token(TokenType.NUMBER, m.group(), start, pos, line, start_col))
                        continue
                tokens.append(Token(TokenType.DOT, ".", pos, pos + 1, line, col))
                pos += 1
                col += 1
                continue

            # --- Multi-char operators ---
            matched_op = False
            for op in _MULTI_OPERATORS:
                if dax[pos:pos + len(op)] == op:
                    tokens.append(Token(TokenType.OPERATOR, op, pos, pos + len(op), line, col))
                    pos += len(op)
                    col += len(op)
                    matched_op = True
                    break
            if matched_op:
                continue

            # --- Single-char operators ---
            if ch in _SINGLE_OPERATORS:
                tokens.append(Token(TokenType.OPERATOR, ch, pos, pos + 1, line, col))
                pos += 1
                col += 1
                continue

            # --- Identifier or keyword ---
            if ch.isalpha() or ch == "_":
                start = pos
                start_col = col
                while pos < length and (dax[pos].isalnum() or dax[pos] == "_"):
                    pos += 1
                    col += 1
                word = dax[start:pos]
                word_upper = word.upper()

                # Check if it's a known DAX function (followed by parenthesis)
                if word_upper in self._function_names:
                    # Peek ahead past whitespace to check for (
                    peek = pos
                    while peek < length and dax[peek] in " \t":
                        peek += 1
                    if peek < length and dax[peek] == "(":
                        tokens.append(Token(TokenType.FUNCTION, word, start, pos, line, start_col))
                        continue

                if word_upper in _KEYWORDS:
                    tokens.append(Token(TokenType.KEYWORD, word, start, pos, line, start_col))
                else:
                    # Could be table name followed by [Column] (unquoted)
                    peek = pos
                    while peek < length and dax[peek] in " \t":
                        peek += 1
                    if peek < length and dax[peek] == "[":
                        # This is an unquoted table name — leave as IDENTIFIER
                        # The next token will be COLUMN_REF
                        pass
                    tokens.append(Token(TokenType.IDENTIFIER, word, start, pos, line, start_col))
                continue

            # --- Unknown ---
            tokens.append(Token(TokenType.UNKNOWN, ch, pos, pos + 1, line, col))
            pos += 1
            col += 1

        return tokens

    def tokenize_code(self, dax: str) -> List[Token]:
        """Tokenize and strip comments, whitespace, newlines.

        This is the primary entry point for analysis — returns only
        code-bearing tokens.
        """
        return [
            t for t in self.tokenize(dax)
            if t.type not in (
                TokenType.COMMENT_LINE, TokenType.COMMENT_BLOCK,
                TokenType.WHITESPACE, TokenType.NEWLINE,
            )
        ]

    def build_paren_map(self, tokens: List[Token]) -> Dict[int, int]:
        """Build map from PAREN_OPEN index → matching PAREN_CLOSE index.

        Args:
            tokens: Token list (typically from tokenize_code)

        Returns:
            Dict mapping open paren indices to close paren indices
        """
        paren_map: Dict[int, int] = {}
        stack: List[int] = []
        for i, t in enumerate(tokens):
            if t.type == TokenType.PAREN_OPEN:
                stack.append(i)
            elif t.type == TokenType.PAREN_CLOSE:
                if stack:
                    open_idx = stack.pop()
                    paren_map[open_idx] = i
        return paren_map

    def extract_function_args(self, tokens: List[Token], func_index: int) -> List[List[Token]]:
        """Extract argument token slices for a function call.

        Args:
            tokens: Code token list
            func_index: Index of the FUNCTION or IDENTIFIER token

        Returns:
            List of token lists, one per comma-separated argument.
            Empty list if no parentheses found.
        """
        # Find the opening paren (should be right after func_index)
        open_idx = func_index + 1
        while open_idx < len(tokens) and tokens[open_idx].type != TokenType.PAREN_OPEN:
            open_idx += 1
        if open_idx >= len(tokens):
            return []

        paren_map = self.build_paren_map(tokens)
        close_idx = paren_map.get(open_idx)
        if close_idx is None:
            return []

        # Split on commas at depth 0 within the parens
        args: List[List[Token]] = []
        current_arg: List[Token] = []
        depth = 0
        for i in range(open_idx + 1, close_idx):
            t = tokens[i]
            if t.type == TokenType.PAREN_OPEN:
                depth += 1
                current_arg.append(t)
            elif t.type == TokenType.PAREN_CLOSE:
                depth -= 1
                current_arg.append(t)
            elif t.type == TokenType.COMMA and depth == 0:
                args.append(current_arg)
                current_arg = []
            else:
                current_arg.append(t)
        if current_arg:
            args.append(current_arg)

        return args
```

- [ ] **Step 4: Update __init__.py**

```python
# core/dax/tokenizer/__init__.py
"""DAX Tokenizer — lightweight lexer producing typed token streams."""

from .tokens import Token, TokenType
from .lexer import DaxLexer

__all__ = ["Token", "TokenType", "DaxLexer"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_dax_tokenizer.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add core/dax/tokenizer/ tests/test_dax_tokenizer.py
git commit -m "feat(dax): implement DaxLexer with full tokenization and helpers"
```

---

### Task 3: DAX Function Knowledge Base

**Files:**
- Create: `core/dax/knowledge/__init__.py`
- Create: `core/dax/knowledge/function_db.py`
- Create: `core/dax/knowledge/functions.json`
- Test: `tests/test_dax_knowledge.py`

- [ ] **Step 1: Write function DB tests**

```python
# tests/test_dax_knowledge.py
"""Tests for DAX function knowledge base."""

import pytest
from core.dax.knowledge.function_db import DaxFunctionDatabase


class TestDaxFunctionDatabase:

    @pytest.fixture
    def db(self):
        return DaxFunctionDatabase.get()

    def test_singleton(self):
        db1 = DaxFunctionDatabase.get()
        db2 = DaxFunctionDatabase.get()
        assert db1 is db2

    def test_lookup_sum(self, db):
        func = db.lookup("SUM")
        assert func is not None
        assert func.name == "SUM"
        assert func.category == "aggregation"

    def test_lookup_case_insensitive(self, db):
        assert db.lookup("sumx") is not None
        assert db.lookup("SUMX") is not None
        assert db.lookup("SumX") is not None

    def test_lookup_nonexistent(self, db):
        assert db.lookup("NOTAREALFUNCTION") is None

    def test_is_function(self, db):
        assert db.is_function("CALCULATE")
        assert db.is_function("SUMX")
        assert db.is_function("DIVIDE")
        assert not db.is_function("VAR")
        assert not db.is_function("RETURN")

    def test_se_classification_sum(self, db):
        assert db.get_se_classification("SUM") == "se_safe"

    def test_se_classification_format(self, db):
        assert db.get_se_classification("FORMAT") == "fe_only"

    def test_creates_row_context(self, db):
        assert db.creates_row_context("SUMX")
        assert db.creates_row_context("FILTER")
        assert not db.creates_row_context("SUM")
        assert not db.creates_row_context("CALCULATE")

    def test_creates_filter_context(self, db):
        assert db.creates_filter_context("CALCULATE")
        assert db.creates_filter_context("CALCULATETABLE")
        assert not db.creates_filter_context("SUM")

    def test_get_alternatives(self, db):
        alts = db.get_alternatives("SUMX")
        assert len(alts) > 0

    def test_get_callback_risk(self, db):
        assert db.get_callback_risk("FORMAT") in ("high", "fe_only")
        assert db.get_callback_risk("SUM") in ("none", "low")

    def test_function_count_minimum(self, db):
        """Must have at least 150 functions."""
        assert db.count() >= 150

    def test_all_functions_have_category(self, db):
        for func in db.all_functions():
            assert func.category, f"{func.name} missing category"

    def test_get_function_names_set(self, db):
        names = db.get_function_names()
        assert isinstance(names, set)
        assert "SUM" in names
        assert "CALCULATE" in names
        assert len(names) >= 150
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dax_knowledge.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Create functions.json**

This is a large file. Create `core/dax/knowledge/functions.json` with 200+ DAX functions. The file is structured as a JSON object where each key is the uppercase function name. Here is the schema and a representative subset — the full file must contain **all** standard DAX functions.

The complete `functions.json` must include entries for every function in these categories:
- **aggregation** (12): SUM, AVERAGE, COUNT, COUNTA, COUNTBLANK, COUNTROWS, DISTINCTCOUNT, MIN, MAX, PRODUCT, MEDIAN, PERCENTILE.INC
- **iterator** (14): SUMX, AVERAGEX, COUNTX, MAXX, MINX, PRODUCTX, RANKX, CONCATENATEX, MEDIANX, PERCENTILE.EXC, STDEVX.S, STDEVX.P, VARX.S, VARX.P
- **filter** (16): CALCULATE, CALCULATETABLE, FILTER, ALL, ALLEXCEPT, ALLSELECTED, ALLNOBLANKROW, ALLCROSSFILTERED, REMOVEFILTERS, KEEPFILTERS, VALUES, DISTINCT, SELECTEDVALUE, HASONEVALUE, HASONEFILTER, ISFILTERED
- **table** (20): SUMMARIZE, SUMMARIZECOLUMNS, ADDCOLUMNS, SELECTCOLUMNS, TOPN, SAMPLE, ROW, DATATABLE, GENERATE, GENERATEALL, GENERATESERIES, CROSSJOIN, UNION, INTERSECT, EXCEPT, NATURALINNERJOIN, NATURALLEFTOUTERJOIN, GROUPBY, ROLLUP, ROLLUPADDISSUBTOTAL
- **relationship** (8): RELATED, RELATEDTABLE, USERELATIONSHIP, CROSSFILTER, TREATAS, LOOKUPVALUE, CONTAINS, CONTAINSROW
- **logical** (8): IF, SWITCH, AND, OR, NOT, COALESCE, TRUE, FALSE
- **text** (18): CONCATENATE, CONCATENATEX, FORMAT, LEFT, RIGHT, MID, LEN, UPPER, LOWER, TRIM, SUBSTITUTE, SEARCH, FIND, REPLACE, REPT, EXACT, UNICHAR, UNICODE
- **datetime** (18): DATE, TIME, YEAR, MONTH, DAY, HOUR, MINUTE, SECOND, NOW, TODAY, EOMONTH, EDATE, DATEDIFF, WEEKDAY, WEEKNUM, CALENDAR, CALENDARAUTO, UTCNOW
- **time_intelligence** (22): DATEADD, SAMEPERIODLASTYEAR, PARALLELPERIOD, DATESBETWEEN, DATESINPERIOD, TOTALYTD, TOTALQTD, TOTALMTD, DATESYTD, DATESQTD, DATESMTD, STARTOFMONTH, ENDOFMONTH, STARTOFQUARTER, ENDOFQUARTER, STARTOFYEAR, ENDOFYEAR, FIRSTDATE, LASTDATE, FIRSTNONBLANK, LASTNONBLANK, PREVIOUSMONTH, PREVIOUSQUARTER, PREVIOUSYEAR, NEXTMONTH, NEXTQUARTER, NEXTYEAR, OPENINGBALANCEMONTH, OPENINGBALANCEQUARTER, OPENINGBALANCEYEAR, CLOSINGBALANCEMONTH, CLOSINGBALANCEQUARTER, CLOSINGBALANCEYEAR
- **math** (22): DIVIDE, ABS, ROUND, ROUNDUP, ROUNDDOWN, MROUND, INT, CEILING, FLOOR, MOD, POWER, SQRT, LOG, LOG10, LN, EXP, SIGN, EVEN, ODD, FACT, GCD, LCM, TRUNC, QUOTIENT, RAND, RANDBETWEEN, PI, CURRENCY, CONVERT
- **statistical** (10): STDEV.S, STDEV.P, VAR.S, VAR.P, GEOMEAN, GEOMEANX, RANK, ROWNUMBER, BETA.DIST, BETA.INV, NORM.DIST, NORM.INV, PERMUT, COMBIN
- **info** (14): ISBLANK, ISERROR, ISINSCOPE, ISEMPTY, ISLOGICAL, ISNONTEXT, ISNUMBER, ISTEXT, ISEVEN, ISODD, BLANK, ERROR, USERCULTURE, USERNAME
- **parent_child** (5): PATH, PATHITEM, PATHITEMREVERSE, PATHLENGTH, PATHCONTAINS
- **conversion** (4): CONVERT, CURRENCY, VALUE, FIXED
- **calculation_group** (5): SELECTEDMEASURE, SELECTEDMEASURENAME, SELECTEDMEASUREFORMATSTRING, ISSELECTEDMEASURE, CALCULATIONGROUP
- **visual_calculation** (8): OFFSET, INDEX, WINDOW, MOVINGAVERAGE, RUNNINGSUM, PARTITIONBY, ORDERBY, RANK (visual)

Each entry in functions.json follows this structure. The agent creating this file must include ALL listed functions with accurate metadata. Here is a representative sample of entries showing the JSON structure:

```json
{
  "SUM": {
    "name": "SUM",
    "category": "aggregation",
    "return_type": "scalar",
    "se_pushable": "se_safe",
    "creates_row_context": false,
    "creates_filter_context": false,
    "parameters": [
      {"name": "column", "type": "column", "required": true}
    ],
    "callback_risk": "none",
    "performance_notes": "Fully pushed to Storage Engine. Optimal for single-column aggregation.",
    "alternatives": [],
    "references": [{"source": "DAX Guide", "url": "https://dax.guide/sum/"}]
  },
  "SUMX": {
    "name": "SUMX",
    "category": "iterator",
    "return_type": "scalar",
    "se_pushable": "expression_dependent",
    "creates_row_context": true,
    "creates_filter_context": false,
    "parameters": [
      {"name": "table", "type": "table", "required": true},
      {"name": "expression", "type": "scalar", "required": true}
    ],
    "callback_risk": "high_if_complex_expression",
    "performance_notes": "Simple arithmetic pushed to SE. Complex functions (ROUND, FORMAT, string ops) trigger CallbackDataID.",
    "alternatives": [
      {"when": "expression is single column", "use": "SUM", "improvement": "Eliminates iterator overhead"},
      {"when": "iterating FILTER() result", "use": "CALCULATE", "improvement": "5-10x faster, enables SE optimization"}
    ],
    "references": [
      {"source": "DAX Guide", "url": "https://dax.guide/sumx/"},
      {"source": "SQLBI", "url": "https://www.sqlbi.com/articles/optimizing-callbacks-in-a-sumx-iterator/"}
    ]
  },
  "CALCULATE": {
    "name": "CALCULATE",
    "category": "filter",
    "return_type": "scalar",
    "se_pushable": "se_safe",
    "creates_row_context": false,
    "creates_filter_context": true,
    "parameters": [
      {"name": "expression", "type": "scalar", "required": true},
      {"name": "filter", "type": "filter", "required": false, "variadic": true}
    ],
    "callback_risk": "none",
    "performance_notes": "Filter arguments should be column predicates, not table filters. FILTER(Table,...) as argument is 10-117x slower than direct column predicates.",
    "alternatives": [],
    "references": [
      {"source": "SQLBI", "url": "https://www.sqlbi.com/articles/filter-arguments-in-calculate/"},
      {"source": "SQLBI", "url": "https://www.sqlbi.com/articles/filter-columns-not-tables-in-dax/"}
    ]
  },
  "FORMAT": {
    "name": "FORMAT",
    "category": "text",
    "return_type": "scalar",
    "se_pushable": "fe_only",
    "creates_row_context": false,
    "creates_filter_context": false,
    "parameters": [
      {"name": "value", "type": "scalar", "required": true},
      {"name": "format_string", "type": "string", "required": true}
    ],
    "callback_risk": "high",
    "performance_notes": "Always forces Formula Engine evaluation. Never use in measures — use FormatString property instead. In iterators, triggers CallbackDataID.",
    "alternatives": [
      {"when": "formatting a measure result", "use": "FormatString property", "improvement": "Avoid FE overhead entirely"}
    ],
    "references": [{"source": "DAX Guide", "url": "https://dax.guide/format/"}]
  },
  "FILTER": {
    "name": "FILTER",
    "category": "filter",
    "return_type": "table",
    "se_pushable": "expression_dependent",
    "creates_row_context": true,
    "creates_filter_context": false,
    "parameters": [
      {"name": "table", "type": "table", "required": true},
      {"name": "filter_expression", "type": "boolean", "required": true}
    ],
    "callback_risk": "medium",
    "performance_notes": "Iterates entire expanded table. When used as CALCULATE filter argument, prevents column predicate optimization. FILTER(BareTable, ...) is 10-100x slower than column predicate.",
    "alternatives": [
      {"when": "inside CALCULATE as filter", "use": "column predicate", "improvement": "10-117x faster per SQLBI"},
      {"when": "FILTER(ALL(col), ...)", "use": "KEEPFILTERS", "improvement": "Simpler and sometimes faster"}
    ],
    "references": [
      {"source": "SQLBI", "url": "https://www.sqlbi.com/articles/filter-columns-not-tables-in-dax/"},
      {"source": "Microsoft Learn", "url": "https://learn.microsoft.com/en-us/power-bi/guidance/dax-avoid-avoid-filter-as-filter-argument"}
    ]
  },
  "DIVIDE": {
    "name": "DIVIDE",
    "category": "math",
    "return_type": "scalar",
    "se_pushable": "fe_only",
    "creates_row_context": false,
    "creates_filter_context": false,
    "parameters": [
      {"name": "numerator", "type": "scalar", "required": true},
      {"name": "denominator", "type": "scalar", "required": true},
      {"name": "alternate_result", "type": "scalar", "required": false}
    ],
    "callback_risk": "medium",
    "performance_notes": "Always creates CallbackDataID in SE queries when inside iterators. 17% faster than IF-based zero-check, but forces FE evaluation.",
    "alternatives": [],
    "references": [
      {"source": "SQLBI", "url": "https://www.sqlbi.com/articles/divide-performance/"},
      {"source": "DAX Guide", "url": "https://dax.guide/divide/"}
    ]
  }
}
```

The agent creating this file must populate ALL 200+ functions with accurate metadata following this exact schema. Use the SQLBI research, DAX Guide, and Microsoft Learn as sources.

- [ ] **Step 4: Implement function_db.py**

```python
# core/dax/knowledge/function_db.py
"""DAX Function Knowledge Base — comprehensive catalog of DAX functions."""

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class Alternative:
    """An optimized alternative for a function in a specific context."""
    when: str
    use: str
    improvement: str = ""


@dataclass
class DaxFunction:
    """Metadata for a single DAX function."""
    name: str
    category: str
    return_type: str  # "scalar", "table", "boolean"
    se_pushable: str  # "se_safe", "fe_only", "expression_dependent"
    creates_row_context: bool
    creates_filter_context: bool
    parameters: List[Dict]
    callback_risk: str  # "none", "low", "medium", "high", "high_if_complex_expression"
    performance_notes: str = ""
    alternatives: List[Alternative] = field(default_factory=list)
    references: List[Dict] = field(default_factory=list)


class DaxFunctionDatabase:
    """Singleton DAX function knowledge base loaded from functions.json."""

    _instance: Optional["DaxFunctionDatabase"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._functions: Dict[str, DaxFunction] = {}
        self._load()

    @classmethod
    def get(cls) -> "DaxFunctionDatabase":
        """Lazy singleton — thread-safe, loaded once."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing only)."""
        with cls._lock:
            cls._instance = None

    def _load(self) -> None:
        """Load functions from JSON file."""
        json_path = Path(__file__).parent / "functions.json"
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.error(f"functions.json not found at {json_path}")
            return
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in functions.json: {e}")
            return

        for name, entry in data.items():
            alts = [
                Alternative(
                    when=a.get("when", ""),
                    use=a.get("use", ""),
                    improvement=a.get("improvement", ""),
                )
                for a in entry.get("alternatives", [])
            ]
            self._functions[name.upper()] = DaxFunction(
                name=entry.get("name", name),
                category=entry.get("category", "unknown"),
                return_type=entry.get("return_type", "scalar"),
                se_pushable=entry.get("se_pushable", "unknown"),
                creates_row_context=entry.get("creates_row_context", False),
                creates_filter_context=entry.get("creates_filter_context", False),
                parameters=entry.get("parameters", []),
                callback_risk=entry.get("callback_risk", "unknown"),
                performance_notes=entry.get("performance_notes", ""),
                alternatives=alts,
                references=entry.get("references", []),
            )
        logger.info(f"Loaded {len(self._functions)} DAX functions from knowledge base")

    def lookup(self, name: str) -> Optional[DaxFunction]:
        """Case-insensitive function lookup."""
        return self._functions.get(name.upper())

    def is_function(self, name: str) -> bool:
        """Check if name is a known DAX function."""
        return name.upper() in self._functions

    def get_se_classification(self, name: str) -> str:
        """Returns SE pushability: 'se_safe', 'fe_only', 'expression_dependent', 'unknown'."""
        func = self.lookup(name)
        return func.se_pushable if func else "unknown"

    def get_alternatives(self, name: str) -> List[Alternative]:
        """Get known optimized alternatives."""
        func = self.lookup(name)
        return func.alternatives if func else []

    def creates_row_context(self, name: str) -> bool:
        """True if function creates a new row context."""
        func = self.lookup(name)
        return func.creates_row_context if func else False

    def creates_filter_context(self, name: str) -> bool:
        """True if function creates/modifies filter context."""
        func = self.lookup(name)
        return func.creates_filter_context if func else False

    def get_by_category(self, category: str) -> List[DaxFunction]:
        """List all functions in a category."""
        return [f for f in self._functions.values() if f.category == category]

    def get_callback_risk(self, name: str) -> str:
        """Returns callback risk level."""
        func = self.lookup(name)
        return func.callback_risk if func else "unknown"

    def count(self) -> int:
        """Total number of functions in the database."""
        return len(self._functions)

    def all_functions(self) -> List[DaxFunction]:
        """Return all functions."""
        return list(self._functions.values())

    def get_function_names(self) -> Set[str]:
        """Return set of all function names (uppercase)."""
        return set(self._functions.keys())
```

```python
# core/dax/knowledge/__init__.py
"""DAX Knowledge Base — function catalog and rule definitions."""

from .function_db import DaxFunctionDatabase, DaxFunction, Alternative

__all__ = ["DaxFunctionDatabase", "DaxFunction", "Alternative"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_dax_knowledge.py -v`
Expected: PASS (will fail on `test_function_count_minimum` until functions.json is fully populated — that's the enforcement test)

- [ ] **Step 6: Commit**

```bash
git add core/dax/knowledge/ tests/test_dax_knowledge.py
git commit -m "feat(dax): add DAX function knowledge base with 200+ functions"
```

---

### Task 4: Wire Tokenizer to Function DB + Integration Test

**Files:**
- Modify: `core/dax/tokenizer/lexer.py`
- Test: `tests/test_dax_tokenizer.py`

- [ ] **Step 1: Write integration test**

Add to `tests/test_dax_tokenizer.py`:

```python
class TestLexerWithFunctionDb:
    """Lexer with function DB classifies FUNCTION tokens correctly."""

    @pytest.fixture
    def lexer(self):
        from core.dax.knowledge.function_db import DaxFunctionDatabase
        db = DaxFunctionDatabase.get()
        return DaxLexer(function_names=db.get_function_names())

    def test_sum_classified_as_function(self, lexer):
        tokens = lexer.tokenize_code("SUM(Sales[Amount])")
        assert tokens[0].type == TokenType.FUNCTION
        assert tokens[0].value == "SUM"

    def test_calculate_classified_as_function(self, lexer):
        tokens = lexer.tokenize_code("CALCULATE([Sales], Filter)")
        assert tokens[0].type == TokenType.FUNCTION
        assert tokens[0].value == "CALCULATE"

    def test_var_still_keyword_not_function(self, lexer):
        tokens = lexer.tokenize_code("VAR x = 1")
        assert tokens[0].type == TokenType.KEYWORD
        assert tokens[0].value == "VAR"

    def test_identifier_without_paren_stays_identifier(self, lexer):
        """SUM without ( should be IDENTIFIER, not FUNCTION."""
        tokens = lexer.tokenize_code("VAR SUM = 1")
        sum_token = [t for t in tokens if t.value == "SUM"][0]
        assert sum_token.type == TokenType.IDENTIFIER

    def test_complex_expression(self, lexer):
        dax = """
        VAR _Sales = CALCULATE(
            SUM('Fact Sales'[Amount]),
            FILTER(ALL('Date'[Year]), 'Date'[Year] = 2024)
        )
        RETURN
            IF(_Sales > 0, DIVIDE(_Sales, [Budget]), BLANK())
        """
        tokens = lexer.tokenize_code(dax)
        functions = [t for t in tokens if t.type == TokenType.FUNCTION]
        func_names = {t.value.upper() for t in functions}
        assert "CALCULATE" in func_names
        assert "SUM" in func_names
        assert "FILTER" in func_names
        assert "ALL" in func_names
        assert "IF" in func_names
        assert "DIVIDE" in func_names
        assert "BLANK" in func_names

        keywords = [t for t in tokens if t.type == TokenType.KEYWORD]
        kw_names = {t.value.upper() for t in keywords}
        assert "VAR" in kw_names
        assert "RETURN" in kw_names
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_dax_tokenizer.py::TestLexerWithFunctionDb -v`
Expected: All PASS (lexer already supports function_names parameter)

- [ ] **Step 3: Commit**

```bash
git add tests/test_dax_tokenizer.py
git commit -m "test(dax): add lexer + function DB integration tests"
```

---

## Phase 2: Unified Analyzer + Hybrid Rules

### Task 5: Analyzer Models (Dataclasses)

**Files:**
- Create: `core/dax/analyzer/__init__.py`
- Create: `core/dax/analyzer/models.py`
- Test: `tests/test_dax_analyzer.py`

- [ ] **Step 1: Write model tests**

```python
# tests/test_dax_analyzer.py
"""Tests for unified DAX analyzer."""

import pytest
from core.dax.analyzer.models import (
    AnalysisContext, AnalysisIssue, UnifiedAnalysisResult,
    RewriteCandidate,
)


class TestAnalyzerModels:
    def test_analysis_issue_creation(self):
        issue = AnalysisIssue(
            rule_id="PERF_SUMX_FILTER",
            category="performance",
            severity="critical",
            title="SUMX(FILTER()) anti-pattern",
            description="Forces row-by-row evaluation",
            fix_suggestion="Use CALCULATE instead",
            source="static",
        )
        assert issue.rule_id == "PERF_SUMX_FILTER"
        assert issue.confidence == "high"  # default

    def test_analysis_context_defaults(self):
        ctx = AnalysisContext()
        assert ctx.vertipaq_data is None
        assert ctx.table_row_counts is None
        assert ctx.trace_data is None

    def test_unified_result_health_score(self):
        issues = [
            AnalysisIssue("R1", "performance", "critical", "T", "D", "F", "static"),
            AnalysisIssue("R2", "performance", "high", "T", "D", "F", "static"),
            AnalysisIssue("R3", "maintainability", "low", "T", "D", "F", "static"),
        ]
        result = UnifiedAnalysisResult.from_issues(issues, tier_used=1)
        assert 0 <= result.health_score <= 100
        assert result.total_issues == 3
        assert result.critical_issues == 1
        assert result.high_issues == 1

    def test_to_best_practices_format(self):
        issues = [
            AnalysisIssue("R1", "performance", "critical", "Title", "Desc", "Fix", "static",
                          code_before="BAD", code_after="GOOD", estimated_improvement="5x"),
        ]
        result = UnifiedAnalysisResult.from_issues(issues, tier_used=1)
        bp_format = result.to_best_practices_format()
        assert "total_issues" in bp_format
        assert "issues" in bp_format
        assert "overall_score" in bp_format
        assert bp_format["success"] is True

    def test_to_rules_engine_format(self):
        issues = [
            AnalysisIssue("PERF001", "performance", "high", "T", "D", "F", "static"),
        ]
        result = UnifiedAnalysisResult.from_issues(issues, tier_used=1)
        re_format = result.to_rules_engine_format()
        assert "health_score" in re_format
        assert "issues" in re_format
        assert "issue_count" in re_format

    def test_to_callback_format(self):
        issues = [
            AnalysisIssue("CB001", "performance", "critical", "T", "D", "F", "static"),
            AnalysisIssue("PERF001", "performance", "high", "T", "D", "F", "static"),
        ]
        result = UnifiedAnalysisResult.from_issues(issues, tier_used=1)
        cb_format = result.to_callback_format()
        # Only CB-prefixed rules
        assert cb_format["total_detections"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dax_analyzer.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement models.py**

```python
# core/dax/analyzer/models.py
"""Dataclasses for the unified DAX analyzer."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AnalysisContext:
    """Encapsulates optional enrichment data for tiered analysis."""
    # Tier 2 — connected
    vertipaq_data: Optional[Dict[str, Any]] = None
    table_row_counts: Optional[Dict[str, int]] = None
    model_relationships: Optional[List[Dict]] = None
    calculation_groups: Optional[List[Dict]] = None
    # Tier 3 — trace
    trace_data: Optional[Dict[str, Any]] = None
    # Metadata
    measure_name: Optional[str] = None
    table_name: Optional[str] = None


@dataclass
class AnalysisIssue:
    """A single analysis finding."""
    rule_id: str
    category: str       # "performance", "correctness", "maintainability"
    severity: str       # "critical", "high", "medium", "low", "info"
    title: str
    description: str
    fix_suggestion: str
    source: str         # "static", "vertipaq", "trace"
    location: Optional[str] = None
    code_before: Optional[str] = None
    code_after: Optional[str] = None
    estimated_improvement: Optional[str] = None
    rewrite_strategy: Optional[str] = None
    references: Optional[List[Dict]] = None
    confidence: str = "high"
    vertipaq_detail: Optional[str] = None
    trace_detail: Optional[str] = None
    match_text: Optional[str] = None
    line: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "fix_suggestion": self.fix_suggestion,
            "source": self.source,
            "location": self.location,
            "code_example_before": self.code_before,
            "code_example_after": self.code_after,
            "estimated_improvement": self.estimated_improvement,
            "rewrite_strategy": self.rewrite_strategy,
            "article_reference": self.references[0] if self.references else None,
            "confidence": self.confidence,
        }


@dataclass
class RewriteCandidate:
    """An issue that has an automated fix available."""
    issue: AnalysisIssue
    strategy_name: str
    estimated_confidence: str = "medium"


_SEVERITY_DEDUCTIONS = {
    "critical": 20,
    "high": 10,
    "medium": 5,
    "low": 2,
    "info": 1,
}

_SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


@dataclass
class UnifiedAnalysisResult:
    """Complete analysis output with backward-compatible format converters."""
    success: bool
    issues: List[AnalysisIssue]
    health_score: int
    tier_used: int
    total_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    rewrite_candidates: List[RewriteCandidate]
    summary: str
    tokens: Optional[Any] = None  # Cached token list for rewriter

    @classmethod
    def from_issues(cls, issues: List[AnalysisIssue], tier_used: int = 1,
                    tokens: Optional[Any] = None) -> "UnifiedAnalysisResult":
        """Create result from a list of issues with auto-calculated metrics."""
        sorted_issues = sorted(issues, key=lambda i: _SEVERITY_ORDER.get(i.severity, 99))
        score = 100
        for issue in sorted_issues:
            score -= _SEVERITY_DEDUCTIONS.get(issue.severity, 0)
        score = max(0, score)

        critical = sum(1 for i in sorted_issues if i.severity == "critical")
        high = sum(1 for i in sorted_issues if i.severity == "high")
        medium = sum(1 for i in sorted_issues if i.severity == "medium")

        rewrite_candidates = [
            RewriteCandidate(issue=i, strategy_name=i.rewrite_strategy)
            for i in sorted_issues
            if i.rewrite_strategy
        ]

        summary = f"{len(sorted_issues)} issues found (score: {score}/100)"
        if critical:
            summary += f" — {critical} critical"

        return cls(
            success=True,
            issues=sorted_issues,
            health_score=score,
            tier_used=tier_used,
            total_issues=len(sorted_issues),
            critical_issues=critical,
            high_issues=high,
            medium_issues=medium,
            rewrite_candidates=rewrite_candidates,
            summary=summary,
            tokens=tokens,
        )

    def to_best_practices_format(self) -> Dict[str, Any]:
        """Convert to DaxBestPracticesAnalyzer.analyze() return format."""
        articles = []
        seen_urls = set()
        for issue in self.issues:
            if issue.references:
                for ref in issue.references:
                    url = ref.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        articles.append(ref)

        return {
            "success": True,
            "total_issues": self.total_issues,
            "critical_issues": self.critical_issues,
            "high_issues": self.high_issues,
            "medium_issues": self.medium_issues,
            "issues": [i.to_dict() for i in self.issues],
            "summary": self.summary,
            "articles_referenced": articles,
            "overall_score": self.health_score,
            "complexity_level": (
                "complex" if self.critical_issues > 0
                else "moderate" if self.high_issues > 0
                else "simple"
            ),
        }

    def to_rules_engine_format(self) -> Dict[str, Any]:
        """Convert to DaxRulesEngine.analyze() return format."""
        return {
            "health_score": self.health_score,
            "issues": [
                {
                    "rule_id": i.rule_id,
                    "category": i.category,
                    "severity": i.severity,
                    "description": i.description,
                    "fix_suggestion": i.fix_suggestion,
                    "line": i.line,
                    "match_text": i.match_text or "",
                }
                for i in self.issues
            ],
            "issue_count": self.total_issues,
            "categories": {
                "performance": sum(1 for i in self.issues if i.category == "performance"),
                "readability": sum(1 for i in self.issues if i.category == "maintainability"),
                "correctness": sum(1 for i in self.issues if i.category == "correctness"),
            },
        }

    def to_callback_format(self) -> Dict[str, Any]:
        """Convert to CallbackDetector.detect_dict() return format."""
        cb_issues = [i for i in self.issues if i.rule_id.startswith("CB")]
        return {
            "success": True,
            "total_detections": len(cb_issues),
            "detections": [
                {
                    "rule_id": i.rule_id,
                    "severity": i.severity,
                    "description": i.description,
                    "location": i.location,
                    "fix_suggestion": i.fix_suggestion,
                }
                for i in cb_issues
            ],
        }
```

```python
# core/dax/analyzer/__init__.py
"""Unified DAX Analyzer — single engine for all static analysis."""

from .models import (
    AnalysisContext,
    AnalysisIssue,
    UnifiedAnalysisResult,
    RewriteCandidate,
)

__all__ = [
    "AnalysisContext",
    "AnalysisIssue",
    "UnifiedAnalysisResult",
    "RewriteCandidate",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dax_analyzer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add core/dax/analyzer/ tests/test_dax_analyzer.py
git commit -m "feat(dax): add unified analyzer models with backward-compatible format converters"
```

---

### Task 6: JSON Rule Engine

**Files:**
- Create: `core/dax/knowledge/rules/performance.json`
- Create: `core/dax/knowledge/rules/correctness.json`
- Create: `core/dax/knowledge/rules/maintainability.json`
- Create: `core/dax/knowledge/rules/callback.json`
- Create: `core/dax/analyzer/rule_engine.py`
- Test: `tests/test_dax_analyzer.py`

This task creates the JSON rule files and the engine that evaluates them against token streams. Each JSON rule defines a `pattern_type` and a `match` specification. The rule engine has an evaluator per `pattern_type`.

The agent implementing this task must:
1. Create the 4 JSON rule files with all rules listed in spec Section 6
2. Implement `rule_engine.py` with evaluators for each `pattern_type`
3. Add tests verifying rule detection on known-bad DAX

The JSON rule schema is defined in the spec Section 4.3. Each rule has: `rule_id`, `category`, `severity`, `title`, `description`, `pattern_type`, `match`, `fix_suggestion`, `estimated_improvement`, `references`, and optional `rewrite_strategy` and `vertipaq_escalation`.

Supported `pattern_type` evaluators:
- `function_nesting`: outer function contains inner function at specified arg position
- `function_in_context`: function appears inside an iterator's expression argument
- `function_usage`: function used at all (e.g. FORMAT, IFERROR)
- `missing_function`: expected function not found (e.g. no DIVIDE for division)
- `bare_table_arg`: FILTER's first arg is a bare table
- `repeated_reference`: same measure referenced 3+ times without VAR
- `nesting_depth`: function nesting exceeds threshold
- `unused_var`: VAR defined but never referenced
- `switch_without_default`: SWITCH missing else branch

- [ ] **Step 1: Write JSON rule engine tests**

Add to `tests/test_dax_analyzer.py`:

```python
from core.dax.analyzer.rule_engine import JsonRuleEngine
from core.dax.tokenizer import DaxLexer, TokenType
from core.dax.knowledge import DaxFunctionDatabase


class TestJsonRuleEngine:

    @pytest.fixture
    def engine(self):
        return JsonRuleEngine()

    @pytest.fixture
    def lexer(self):
        db = DaxFunctionDatabase.get()
        return DaxLexer(function_names=db.get_function_names())

    def test_loads_rules(self, engine):
        assert engine.rule_count() > 0

    def test_detects_sumx_filter_nesting(self, engine, lexer):
        dax = "SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])"
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        perf_ids = [i.rule_id for i in issues]
        assert any("SUMX_FILTER" in rid or "ITERATOR_FILTER" in rid for rid in perf_ids)

    def test_detects_format_usage(self, engine, lexer):
        dax = 'FORMAT([Sales], "#,##0")'
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        assert any("FORMAT" in i.rule_id for i in issues)

    def test_detects_iferror_usage(self, engine, lexer):
        dax = "IFERROR([Sales] / [Cost], 0)"
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        assert any("IFERROR" in i.rule_id for i in issues)

    def test_clean_dax_no_issues(self, engine, lexer):
        dax = "CALCULATE(SUM(Sales[Amount]), Sales[Year] = 2024)"
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        # Simple clean DAX should have 0 or very few issues
        critical = [i for i in issues if i.severity == "critical"]
        assert len(critical) == 0

    def test_detects_division_without_divide(self, engine, lexer):
        dax = "[Sales] / [Cost]"
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        assert any("DIVIDE" in i.rule_id or "DIVISION" in i.rule_id for i in issues)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dax_analyzer.py::TestJsonRuleEngine -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Create JSON rule files and implement rule_engine.py**

The agent must create 4 JSON files in `core/dax/knowledge/rules/` following the schema from the spec, and implement `core/dax/analyzer/rule_engine.py` with the `JsonRuleEngine` class that:
1. Loads all JSON rule files from `core/dax/knowledge/rules/`
2. Implements an evaluator per `pattern_type`
3. Returns `List[AnalysisIssue]` from `evaluate(tokens, dax)`

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dax_analyzer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add core/dax/knowledge/rules/ core/dax/analyzer/rule_engine.py tests/test_dax_analyzer.py
git commit -m "feat(dax): add JSON rule engine with pattern-based DAX analysis"
```

---

### Task 7: Python Rules (Complex Structural Analysis)

**Files:**
- Create: `core/dax/analyzer/rules/__init__.py`
- Create: `core/dax/analyzer/rules/base.py`
- Create: `core/dax/analyzer/rules/iterator_rules.py`
- Create: `core/dax/analyzer/rules/calculate_rules.py`
- Create: `core/dax/analyzer/rules/filter_rules.py`
- Create: `core/dax/analyzer/rules/context_rules.py`
- Create: `core/dax/analyzer/rules/model_rules.py`
- Test: `tests/test_dax_analyzer.py`

Each Python rule inherits from `PythonRule` base class and implements `evaluate(tokens, function_db, context)`. The rules are listed in spec Section 4.3 with their exact logic.

The agent implementing this task must create all 29 Python rules across 5 files as specified. Each rule must:
1. Use the tokenizer (not regex) for pattern detection
2. Use function_db for function classification
3. Return `List[AnalysisIssue]`
4. Include `rewrite_strategy` when an automated fix exists

- [ ] **Step 1: Write Python rule tests**

Add to `tests/test_dax_analyzer.py`:

```python
from core.dax.analyzer.rules import load_python_rules


class TestPythonRules:

    @pytest.fixture
    def rules(self):
        return load_python_rules()

    @pytest.fixture
    def lexer(self):
        db = DaxFunctionDatabase.get()
        return DaxLexer(function_names=db.get_function_names())

    @pytest.fixture
    def function_db(self):
        return DaxFunctionDatabase.get()

    def test_loads_all_rules(self, rules):
        assert len(rules) >= 20

    def test_nested_iterator_detected(self, rules, lexer, function_db):
        dax = "SUMX(Sales, SUMX(RELATEDTABLE(Products), Products[Price]))"
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any("NESTED" in i.rule_id.upper() for i in all_issues)

    def test_if_in_iterator_detected(self, rules, lexer, function_db):
        dax = "SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))"
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any("IF" in i.rule_id.upper() and "ITERATOR" in i.rule_id.upper()
                    for i in all_issues)

    def test_unnecessary_iterator_detected(self, rules, lexer, function_db):
        dax = "SUMX(Sales, Sales[Amount])"
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any("UNNECESSARY" in i.rule_id.upper() for i in all_issues)

    def test_var_defeating_shortcircuit(self, rules, lexer, function_db):
        dax = """
        VAR _A = CALCULATE([Sales], Filter1)
        VAR _B = CALCULATE([Sales LY], Filter2)
        VAR _C = CALCULATE([Sales YOY], Filter3)
        RETURN SWITCH(TRUE(), Sel = "C", _A, Sel = "LY", _B, _C)
        """
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any("SHORT" in i.rule_id.upper() or "VAR" in i.rule_id.upper()
                    for i in all_issues)

    def test_blank_propagation_1_minus(self, rules, lexer, function_db):
        dax = "1 - DIVIDE([Sales], [Budget])"
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any("BLANK" in i.rule_id.upper() for i in all_issues)

    def test_clean_dax_minimal_issues(self, rules, lexer, function_db):
        dax = """
        VAR _Sales = SUM(Sales[Amount])
        VAR _Budget = SUM(Budget[Amount])
        RETURN DIVIDE(_Sales, _Budget)
        """
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        critical = [i for i in all_issues if i.severity == "critical"]
        assert len(critical) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dax_analyzer.py::TestPythonRules -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement Python rules**

The agent must create all files in `core/dax/analyzer/rules/` with the 29 Python rules as specified. The `__init__.py` must export a `load_python_rules()` function that auto-discovers and instantiates all rules.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dax_analyzer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add core/dax/analyzer/rules/ tests/test_dax_analyzer.py
git commit -m "feat(dax): add 29 Python structural analysis rules"
```

---

### Task 8: Unified Analyzer + Facades

**Files:**
- Create: `core/dax/analyzer/unified_analyzer.py`
- Modify: `core/dax/analyzer/__init__.py`
- Modify: `core/dax/dax_best_practices.py` (facade)
- Modify: `core/dax/dax_rules_engine.py` (facade)
- Modify: `core/dax/callback_detector.py` (facade)
- Test: `tests/test_dax_analyzer.py`
- Test: `tests/test_dax_facades.py`

- [ ] **Step 1: Write unified analyzer + facade tests**

```python
# tests/test_dax_facades.py
"""Tests verifying backward compatibility of facade classes."""

import pytest


class TestBestPracticesFacade:
    """DaxBestPracticesAnalyzer facade produces same format as original."""

    def test_analyze_returns_expected_keys(self):
        from core.dax.dax_best_practices import DaxBestPracticesAnalyzer
        analyzer = DaxBestPracticesAnalyzer()
        result = analyzer.analyze("SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])")
        assert result["success"] is True
        assert "total_issues" in result
        assert "critical_issues" in result
        assert "high_issues" in result
        assert "medium_issues" in result
        assert "issues" in result
        assert "summary" in result
        assert "overall_score" in result
        assert isinstance(result["issues"], list)

    def test_analyze_with_context_and_vertipaq(self):
        from core.dax.dax_best_practices import DaxBestPracticesAnalyzer
        analyzer = DaxBestPracticesAnalyzer()
        result = analyzer.analyze("SUM(Sales[Amount])", context_analysis=None, vertipaq_analysis=None)
        assert result["success"] is True

    def test_issue_dict_has_expected_fields(self):
        from core.dax.dax_best_practices import DaxBestPracticesAnalyzer
        analyzer = DaxBestPracticesAnalyzer()
        result = analyzer.analyze("SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])")
        if result["total_issues"] > 0:
            issue = result["issues"][0]
            assert "title" in issue
            assert "description" in issue
            assert "severity" in issue
            assert "category" in issue


class TestRulesEngineFacade:
    """DaxRulesEngine facade produces same format as original."""

    def test_analyze_returns_expected_keys(self):
        from core.dax.dax_rules_engine import DaxRulesEngine
        engine = DaxRulesEngine()
        result = engine.analyze("SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))")
        assert "health_score" in result
        assert "issues" in result
        assert "issue_count" in result
        assert isinstance(result["health_score"], int)
        assert 0 <= result["health_score"] <= 100

    def test_issue_dict_has_expected_fields(self):
        from core.dax.dax_rules_engine import DaxRulesEngine
        engine = DaxRulesEngine()
        result = engine.analyze("SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))")
        if result["issue_count"] > 0:
            issue = result["issues"][0]
            assert "rule_id" in issue
            assert "severity" in issue
            assert "description" in issue
            assert "fix_suggestion" in issue


class TestCallbackDetectorFacade:
    """CallbackDetector facade produces same format as original."""

    def test_detect_dict_returns_expected_keys(self):
        from core.dax.callback_detector import CallbackDetector
        detector = CallbackDetector()
        result = detector.detect_dict("SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))")
        assert result["success"] is True
        assert "total_detections" in result
        assert "detections" in result

    def test_detect_returns_list(self):
        from core.dax.callback_detector import CallbackDetector
        detector = CallbackDetector()
        result = detector.detect("SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))")
        assert isinstance(result, list)
```

Add to `tests/test_dax_analyzer.py`:

```python
from core.dax.analyzer.unified_analyzer import DaxUnifiedAnalyzer
from core.dax.analyzer.models import AnalysisContext


class TestDaxUnifiedAnalyzer:
    @pytest.fixture
    def analyzer(self):
        return DaxUnifiedAnalyzer()

    def test_analyze_basic(self, analyzer):
        result = analyzer.analyze("SUM(Sales[Amount])")
        assert result.success is True
        assert result.tier_used == 1
        assert 0 <= result.health_score <= 100

    def test_analyze_detects_sumx_filter(self, analyzer):
        result = analyzer.analyze("SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])")
        assert result.total_issues > 0
        assert any("FILTER" in i.rule_id for i in result.issues)

    def test_analyze_with_vertipaq_context(self, analyzer):
        ctx = AnalysisContext(
            vertipaq_data={"success": True, "columns": {}},
            table_row_counts={"Sales": 5_000_000}
        )
        result = analyzer.analyze("SUMX(Sales, Sales[Amount] * Sales[Qty])", context=ctx)
        assert result.success is True

    def test_analyze_batch(self, analyzer):
        measures = [
            ("Sales Total", "SUM(Sales[Amount])"),
            ("Bad Pattern", "SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])"),
        ]
        results = analyzer.analyze_batch(measures)
        assert len(results) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dax_facades.py tests/test_dax_analyzer.py::TestDaxUnifiedAnalyzer -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement unified_analyzer.py**

The agent must implement `DaxUnifiedAnalyzer` that:
1. Instantiates `DaxLexer` with function names from `DaxFunctionDatabase`
2. Loads `JsonRuleEngine` and Python rules
3. Tokenizes input, runs all rules, builds `UnifiedAnalysisResult`
4. Supports optional `AnalysisContext` for tier 2/3 enrichment

- [ ] **Step 4: Convert existing files to facades**

The agent must refactor:
- `dax_best_practices.py`: Keep class name, `__init__`, and `analyze()` signature. Internally delegate to `DaxUnifiedAnalyzer`. Keep the existing `_initialize_checks` and check methods as fallback (call unified analyzer, if it fails fall back to original logic). This ensures zero risk of breakage.
- `dax_rules_engine.py`: Same pattern — facade + fallback.
- `callback_detector.py`: Same pattern — facade + fallback.

**Critical**: Each facade must catch any exception from the unified analyzer and fall back to the original implementation. This is a safety net during the transition.

- [ ] **Step 5: Run ALL tests to verify nothing breaks**

Run: `pytest tests/ -v`
Expected: All existing tests PASS + new tests PASS

- [ ] **Step 6: Commit**

```bash
git add core/dax/analyzer/ core/dax/dax_best_practices.py core/dax/dax_rules_engine.py core/dax/callback_detector.py tests/
git commit -m "feat(dax): unified analyzer with backward-compatible facades"
```

---

## Phase 3: Optimizer Pipeline + Rewriter

### Task 9: Rewrite Engine + Strategies

**Files:**
- Create: `core/dax/optimizer/__init__.py`
- Create: `core/dax/optimizer/models.py`
- Create: `core/dax/optimizer/rewrite_engine.py`
- Create: `core/dax/optimizer/strategies/__init__.py`
- Create: `core/dax/optimizer/strategies/base.py`
- Create: `core/dax/optimizer/strategies/variable_extraction.py`
- Create: `core/dax/optimizer/strategies/calculate_optimization.py`
- Create: `core/dax/optimizer/strategies/iterator_optimization.py`
- Create: `core/dax/optimizer/strategies/pattern_replacement.py`
- Test: `tests/test_dax_optimizer.py`

The agent implementing this must create the rewrite engine that:
1. Takes analysis issues + tokenized DAX
2. Matches each fixable issue to a rewrite strategy
3. Applies strategies using token positions (not regex)
4. Re-tokenizes output to validate structural integrity
5. Generates meaningful variable names

- [ ] **Step 1: Write optimizer tests**

```python
# tests/test_dax_optimizer.py
"""Tests for DAX optimization pipeline."""

import pytest
from core.dax.optimizer.rewrite_engine import DaxRewriteEngine
from core.dax.optimizer.models import RewriteResult
from core.dax.analyzer.unified_analyzer import DaxUnifiedAnalyzer
from core.dax.knowledge import DaxFunctionDatabase


class TestRewriteEngine:

    @pytest.fixture
    def engine(self):
        return DaxRewriteEngine(DaxFunctionDatabase.get())

    @pytest.fixture
    def analyzer(self):
        return DaxUnifiedAnalyzer()

    def test_rewrites_unnecessary_iterator(self, engine, analyzer):
        """SUMX(T, T[Col]) → SUM(T[Col])"""
        dax = "SUMX(Sales, Sales[Amount])"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        applicable = [r for r in rewrites if "iterator" in r.strategy.lower()]
        if applicable:
            assert "SUM" in applicable[0].rewritten_fragment

    def test_generates_meaningful_var_names(self, engine, analyzer):
        dax = "[Sales Amount] + [Sales Amount] + [Sales Amount]"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        var_rewrites = [r for r in rewrites if "variable" in r.strategy.lower()]
        if var_rewrites:
            assert "_SalesAmount" in var_rewrites[0].full_rewritten_dax or "_M" not in var_rewrites[0].full_rewritten_dax

    def test_rewrite_validation(self, engine, analyzer):
        """Rewritten DAX must re-tokenize without structural errors."""
        dax = "SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        for r in rewrites:
            assert r.validation_passed

    def test_apply_multiple_rewrites(self, engine, analyzer):
        dax = "[Sales] + [Sales] + [Sales]"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        if rewrites:
            final = engine.apply_rewrites(dax, rewrites)
            assert final != dax  # Something changed
            assert "VAR" in final  # Variables extracted
```

- [ ] **Step 2-5: Implement, run tests, commit**

Pattern same as previous tasks. The agent creates all strategy files and the rewrite engine.

- [ ] **Step 6: Commit**

```bash
git add core/dax/optimizer/ tests/test_dax_optimizer.py
git commit -m "feat(dax): add rewrite engine with 4 optimization strategies"
```

---

### Task 10: Optimization Pipeline + Code Rewriter Facade

**Files:**
- Create: `core/dax/optimizer/pipeline.py`
- Create: `core/dax/optimizer/measure_applier.py`
- Modify: `core/dax/code_rewriter.py` (facade)
- Modify: `core/dax/analysis_pipeline.py` (add `run_optimization_pipeline`)
- Test: `tests/test_dax_optimizer.py`

- [ ] **Step 1: Write pipeline tests**

Add to `tests/test_dax_optimizer.py`:

```python
from core.dax.optimizer.pipeline import OptimizationPipeline


class TestOptimizationPipeline:

    @pytest.fixture
    def pipeline(self):
        return OptimizationPipeline()

    def test_optimize_expression_basic(self, pipeline):
        result = pipeline.optimize_expression("SUM(Sales[Amount])")
        assert result.success is True
        assert result.original_dax == "SUM(Sales[Amount])"

    def test_optimize_expression_with_issues(self, pipeline):
        result = pipeline.optimize_expression("SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])")
        assert result.success is True
        assert result.analysis.total_issues > 0
        assert len(result.rewrites) >= 0  # May or may not have automated rewrites

    def test_dry_run_does_not_apply(self, pipeline):
        result = pipeline.optimize_expression("[Sales] + [Sales] + [Sales]")
        assert result.applied is False


class TestCodeRewriterFacade:
    """Verify code_rewriter.py facade produces same format as original."""

    def test_rewrite_dax_returns_expected_keys(self):
        from core.dax.code_rewriter import DaxCodeRewriter
        rewriter = DaxCodeRewriter()
        result = rewriter.rewrite_dax("SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])")
        assert "success" in result
        assert "has_changes" in result
        assert "original_code" in result
        assert "transformations" in result
        assert "transformation_count" in result

    def test_existing_tests_still_pass(self):
        """Run a representative test from the original test suite."""
        from core.dax.code_rewriter import DaxCodeRewriter
        rewriter = DaxCodeRewriter()
        dax = "[Sales] + [Sales] + [Sales]"
        result = rewriter.rewrite_dax(dax)
        if result["has_changes"]:
            assert "VAR" in result["rewritten_code"]
```

- [ ] **Step 2: Implement pipeline, measure_applier, and facades**

The agent must:
1. Create `pipeline.py` with `OptimizationPipeline` class
2. Create `measure_applier.py` that bridges to existing `dax_injector.py` and `measure_operations.py`
3. Convert `code_rewriter.py` to a facade (same pattern: delegate to new engine, fallback to original on error)
4. Add `run_optimization_pipeline()` to `analysis_pipeline.py`

- [ ] **Step 3: Run ALL tests**

Run: `pytest tests/ -v`
Expected: All PASS including existing `test_code_rewriter.py` and `test_dax_parsing.py`

- [ ] **Step 4: Commit**

```bash
git add core/dax/optimizer/ core/dax/code_rewriter.py core/dax/analysis_pipeline.py tests/
git commit -m "feat(dax): add optimization pipeline with code rewriter facade"
```

---

## Phase 4: Integration + Polish

### Task 11: Update core/dax/__init__.py Exports

**Files:**
- Modify: `core/dax/__init__.py`

- [ ] **Step 1: Add new exports while preserving all existing ones**

The agent must update `__init__.py` to add exports for:
- `DaxLexer`, `Token`, `TokenType` from tokenizer
- `DaxFunctionDatabase`, `DaxFunction` from knowledge
- `DaxUnifiedAnalyzer`, `AnalysisContext`, `AnalysisIssue`, `UnifiedAnalysisResult` from analyzer
- `OptimizationPipeline` from optimizer
- `run_optimization_pipeline` from analysis_pipeline

All 52 existing exports MUST remain.

- [ ] **Step 2: Run ALL tests**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add core/dax/__init__.py
git commit -m "feat(dax): update exports with new tokenizer, knowledge, analyzer, optimizer modules"
```

---

### Task 12: Refactor dax_utilities.py to Use Tokenizer

**Files:**
- Modify: `core/dax/dax_utilities.py`
- Test: `tests/test_dax_parsing.py` (existing tests must still pass)

- [ ] **Step 1: Refactor normalize_dax to use tokenizer**

Internally use `DaxLexer().tokenize_code()` then join values. Same signature, same output.

- [ ] **Step 2: Refactor extract_function_body to use tokenizer**

Use tokenizer paren map for correct matching. Same signature, same output.

- [ ] **Step 3: Run existing tests**

Run: `pytest tests/test_dax_parsing.py tests/test_code_rewriter.py -v`
Expected: All PASS (backward compatible)

- [ ] **Step 4: Commit**

```bash
git add core/dax/dax_utilities.py
git commit -m "refactor(dax): use tokenizer internally in dax_utilities for reliable parsing"
```

---

### Task 13: Final Integration Test + Regression

**Files:**
- Create: `tests/test_dax_integration.py`

- [ ] **Step 1: Write end-to-end integration tests**

```python
# tests/test_dax_integration.py
"""End-to-end integration tests for DAX engine overhaul."""

import pytest


class TestEndToEndPipeline:
    """Full pipeline: analyze → rewrite → validate."""

    def test_complex_measure_full_pipeline(self):
        from core.dax.optimizer.pipeline import OptimizationPipeline
        dax = """
        SUMX(
            FILTER(ALL('Product'), 'Product'[Category] = "Electronics"),
            [Sales Amount] + [Sales Amount]
        )
        """
        pipeline = OptimizationPipeline()
        result = pipeline.optimize_expression(dax)
        assert result.success
        assert result.analysis.total_issues > 0
        if result.final_dax:
            # Final DAX should be different from original
            assert result.final_dax.strip() != dax.strip()

    def test_clean_measure_no_changes(self):
        from core.dax.optimizer.pipeline import OptimizationPipeline
        dax = """
        VAR _Sales = SUM(Sales[Amount])
        VAR _Budget = SUM(Budget[Amount])
        RETURN DIVIDE(_Sales, _Budget)
        """
        pipeline = OptimizationPipeline()
        result = pipeline.optimize_expression(dax)
        assert result.success
        # Clean DAX should have minimal issues and no critical rewrites
        critical_rewrites = [r for r in result.rewrites if "critical" in r.rule_id.lower()]
        assert len(critical_rewrites) == 0


class TestBackwardCompatibility:
    """Verify all existing APIs still work."""

    def test_best_practices_analyzer_api(self):
        from core.dax.dax_best_practices import DaxBestPracticesAnalyzer
        result = DaxBestPracticesAnalyzer().analyze("SUM(Sales[Amount])")
        assert result["success"] is True

    def test_rules_engine_api(self):
        from core.dax.dax_rules_engine import DaxRulesEngine
        result = DaxRulesEngine().analyze("SUM(Sales[Amount])")
        assert "health_score" in result

    def test_callback_detector_api(self):
        from core.dax.callback_detector import CallbackDetector
        result = CallbackDetector().detect_dict("SUM(Sales[Amount])")
        assert result["success"] is True

    def test_code_rewriter_api(self):
        from core.dax.code_rewriter import DaxCodeRewriter
        result = DaxCodeRewriter().rewrite_dax("SUM(Sales[Amount])")
        assert result["success"] is True

    def test_analysis_pipeline_functions(self):
        from core.dax.analysis_pipeline import run_context_analysis, run_best_practices
        _, ctx = run_context_analysis("SUM(Sales[Amount])")
        bp = run_best_practices("SUM(Sales[Amount])")
        # These may return None if dependencies fail, but shouldn't raise
        assert ctx is None or isinstance(ctx, dict)
        assert bp is None or isinstance(bp, dict)

    def test_tokenizer_available(self):
        from core.dax.tokenizer import DaxLexer, Token, TokenType
        tokens = DaxLexer().tokenize("VAR x = 1")
        assert len(tokens) > 0

    def test_function_db_available(self):
        from core.dax.knowledge import DaxFunctionDatabase
        db = DaxFunctionDatabase.get()
        assert db.count() >= 150

    def test_unified_analyzer_available(self):
        from core.dax.analyzer import DaxUnifiedAnalyzer
        result = DaxUnifiedAnalyzer().analyze("SUM(Sales[Amount])")
        assert result.success
```

- [ ] **Step 2: Run all tests**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_dax_integration.py
git commit -m "test(dax): add end-to-end integration and backward compatibility tests"
```

---

### Task 14: Final Cleanup

- [ ] **Step 1: Run full test suite with coverage**

Run: `pytest tests/ -v --cov=core/dax --cov-report=term`
Expected: All PASS, coverage report shows new modules

- [ ] **Step 2: Run linting**

Run: `black --check --line-length 100 core/dax/`
Fix any formatting issues.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore(dax): DAX engine overhaul complete — tokenizer, knowledge base, unified analyzer, optimizer pipeline"
```
