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


from core.dax.tokenizer.lexer import DaxLexer


class TestDaxLexerBasic:
    """Basic tokenization of simple DAX expressions."""

    @pytest.fixture
    def lexer(self):
        return DaxLexer()

    def test_simple_sum(self, lexer):
        tokens = lexer.tokenize("SUM(Sales[Amount])")
        code = [t for t in tokens if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE)]
        assert code[0].type == TokenType.IDENTIFIER  # SUM (no function_db)
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

    def test_table_ref_with_column(self, lexer):
        tokens = lexer.tokenize("'My Table'[Column]")
        code = [t for t in tokens if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE)]
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
        x_tokens = [t for t in tokens if t.value == "x"]
        assert x_tokens[0].line == 2


class TestDaxLexerEdgeCases:
    """Edge cases: escaped quotes, nested strings, special chars."""

    @pytest.fixture
    def lexer(self):
        return DaxLexer()

    def test_escaped_double_quotes_in_string(self, lexer):
        dax = 'FORMAT(1234, "#,##0.00")'
        tokens = lexer.tokenize_code(dax)
        strings = [t for t in tokens if t.type == TokenType.STRING]
        assert len(strings) == 1
        assert strings[0].value == '"#,##0.00"'

    def test_escaped_single_quotes_in_table_ref(self, lexer):
        dax = "'It''s a Table'[Col]"
        tokens = lexer.tokenize_code(dax)
        qrefs = [t for t in tokens if t.type == TokenType.QUALIFIED_REF]
        assert len(qrefs) == 1
        assert "It''s a Table" in qrefs[0].value

    def test_sumx_inside_string_not_function(self, lexer):
        dax = '"SUMX is great"'
        tokens = lexer.tokenize_code(dax)
        assert all(t.type != TokenType.FUNCTION for t in tokens)
        assert tokens[0].type == TokenType.STRING

    def test_comment_inside_string_not_stripped(self, lexer):
        dax = '"Price // per unit"'
        tokens = lexer.tokenize_code(dax)
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.STRING

    def test_dotted_function_name(self, lexer):
        dax = "STDEVX.S(Table, [Col])"
        tokens = lexer.tokenize_code(dax)
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "STDEVX"
        assert tokens[1].type == TokenType.DOT
        assert tokens[2].type == TokenType.IDENTIFIER
        assert tokens[2].value == "S"

    def test_empty_expression(self, lexer):
        assert lexer.tokenize("") == []

    def test_only_whitespace(self, lexer):
        assert lexer.tokenize_code("   \n  \t  ") == []

    def test_measure_ref_standalone(self, lexer):
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
        open_indices = [i for i, t in enumerate(tokens) if t.type == TokenType.PAREN_OPEN]
        close_indices = [i for i, t in enumerate(tokens) if t.type == TokenType.PAREN_CLOSE]
        assert pmap[open_indices[0]] == close_indices[-1]
        assert pmap[open_indices[1]] == close_indices[-2]

    def test_extract_function_args(self, lexer):
        tokens = lexer.tokenize_code("CALCULATE([Sales], Filter1, Filter2)")
        args = lexer.extract_function_args(tokens, 0)
        assert len(args) == 3
        assert any(t.type == TokenType.COLUMN_REF for t in args[0])
        assert any(t.value == "Filter1" for t in args[1])
        assert any(t.value == "Filter2" for t in args[2])

    def test_extract_function_args_nested(self, lexer):
        tokens = lexer.tokenize_code("SUMX(FILTER(T, T[A] > 1), T[B])")
        args = lexer.extract_function_args(tokens, 0)
        assert len(args) == 2  # FILTER(...) and T[B]
