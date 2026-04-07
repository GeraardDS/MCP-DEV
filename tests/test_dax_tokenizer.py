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
