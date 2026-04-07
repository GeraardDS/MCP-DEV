"""DAX Lexer — single-pass tokenizer producing typed token streams."""

from typing import Dict, List, Optional, Set

from .tokens import Token, TokenType

_KEYWORDS: Set[str] = {
    "VAR", "RETURN", "IF", "ELSE", "SWITCH", "TRUE", "FALSE",
    "AND", "OR", "NOT", "IN", "EVALUATE", "DEFINE", "MEASURE",
    "ORDER", "BY", "ASC", "DESC", "COLUMN", "TABLE", "START", "AT",
}

_MULTI_CHAR_OPS: List[str] = ["<=", ">=", "<>", "&&", "||"]
_SINGLE_CHAR_OPS: Set[str] = {"+", "-", "*", "/", "=", "<", ">", "&", "|"}


class DaxLexer:
    """Single-pass DAX tokenizer.

    Converts DAX source text into a flat list of ``Token`` objects,
    tracking line and column for every token.
    """

    def __init__(self, function_names: Optional[Set[str]] = None) -> None:
        self._function_names: Set[str] = (
            {n.upper() for n in function_names} if function_names else set()
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tokenize(self, dax: str) -> List[Token]:
        """Return full token stream including whitespace and comments."""
        tokens: List[Token] = []
        length = len(dax)
        pos = 0
        line = 1
        col = 1

        while pos < length:
            ch = dax[pos]

            # --- Newlines (\r\n or \n) ---
            if ch == "\r" and pos + 1 < length and dax[pos + 1] == "\n":
                tokens.append(Token(TokenType.NEWLINE, "\r\n", pos, pos + 2, line, col))
                pos += 2
                line += 1
                col = 1
                continue
            if ch == "\n":
                tokens.append(Token(TokenType.NEWLINE, "\n", pos, pos + 1, line, col))
                pos += 1
                line += 1
                col = 1
                continue

            # --- Whitespace (spaces, tabs) ---
            if ch in (" ", "\t"):
                start = pos
                start_col = col
                while pos < length and dax[pos] in (" ", "\t"):
                    pos += 1
                    col += 1
                tokens.append(
                    Token(TokenType.WHITESPACE, dax[start:pos], start, pos, line, start_col)
                )
                continue

            # --- Line comment ---
            if ch == "/" and pos + 1 < length and dax[pos + 1] == "/":
                start = pos
                start_col = col
                while pos < length and dax[pos] != "\n" and dax[pos] != "\r":
                    pos += 1
                    col += 1
                tokens.append(
                    Token(TokenType.COMMENT_LINE, dax[start:pos], start, pos, line, start_col)
                )
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
                        pos += 1
                    elif dax[pos] == "\r" and pos + 1 < length and dax[pos + 1] == "\n":
                        line += 1
                        col = 1
                        pos += 2
                    else:
                        pos += 1
                        col += 1
                tokens.append(
                    Token(
                        TokenType.COMMENT_BLOCK,
                        dax[start:pos],
                        start,
                        pos,
                        start_line,
                        start_col,
                    )
                )
                continue

            # --- String literal ("..." with "" escape) ---
            if ch == '"':
                start = pos
                start_col = col
                pos += 1
                col += 1
                while pos < length:
                    if dax[pos] == '"':
                        pos += 1
                        col += 1
                        # doubled quote → escape, keep going
                        if pos < length and dax[pos] == '"':
                            pos += 1
                            col += 1
                            continue
                        break
                    if dax[pos] == "\n":
                        line += 1
                        col = 1
                        pos += 1
                    elif dax[pos] == "\r" and pos + 1 < length and dax[pos + 1] == "\n":
                        line += 1
                        col = 1
                        pos += 2
                    else:
                        pos += 1
                        col += 1
                tokens.append(
                    Token(TokenType.STRING, dax[start:pos], start, pos, line, start_col)
                )
                continue

            # --- Table ref / Qualified ref ('Table'[Col]) ---
            if ch == "'":
                start = pos
                start_col = col
                pos += 1
                col += 1
                while pos < length:
                    if dax[pos] == "'":
                        pos += 1
                        col += 1
                        if pos < length and dax[pos] == "'":
                            pos += 1
                            col += 1
                            continue
                        break
                    pos += 1
                    col += 1
                # Check if immediately followed by [Col]
                if pos < length and dax[pos] == "[":
                    col_start = pos
                    pos += 1
                    col += 1
                    while pos < length and dax[pos] != "]":
                        pos += 1
                        col += 1
                    if pos < length:
                        pos += 1  # consume ]
                        col += 1
                    tokens.append(
                        Token(
                            TokenType.QUALIFIED_REF,
                            dax[start:pos],
                            start,
                            pos,
                            line,
                            start_col,
                        )
                    )
                else:
                    tokens.append(
                        Token(
                            TokenType.TABLE_REF,
                            dax[start:pos],
                            start,
                            pos,
                            line,
                            start_col,
                        )
                    )
                continue

            # --- Column / measure ref [Name] ---
            if ch == "[":
                start = pos
                start_col = col
                pos += 1
                col += 1
                while pos < length and dax[pos] != "]":
                    pos += 1
                    col += 1
                if pos < length:
                    pos += 1  # consume ]
                    col += 1
                tokens.append(
                    Token(TokenType.COLUMN_REF, dax[start:pos], start, pos, line, start_col)
                )
                continue

            # --- Number (digits, decimal, scientific) ---
            if ch.isdigit() or (ch == "." and pos + 1 < length and dax[pos + 1].isdigit()):
                start = pos
                start_col = col
                # integer part
                while pos < length and dax[pos].isdigit():
                    pos += 1
                    col += 1
                # decimal part
                if pos < length and dax[pos] == ".":
                    pos += 1
                    col += 1
                    while pos < length and dax[pos].isdigit():
                        pos += 1
                        col += 1
                # scientific notation
                if pos < length and dax[pos] in ("e", "E"):
                    pos += 1
                    col += 1
                    if pos < length and dax[pos] in ("+", "-"):
                        pos += 1
                        col += 1
                    while pos < length and dax[pos].isdigit():
                        pos += 1
                        col += 1
                tokens.append(
                    Token(TokenType.NUMBER, dax[start:pos], start, pos, line, start_col)
                )
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

            # --- Multi-char operators (check longest first) ---
            matched_op = False
            if pos + 1 < length:
                two = dax[pos : pos + 2]
                if two in _MULTI_CHAR_OPS:
                    tokens.append(
                        Token(TokenType.OPERATOR, two, pos, pos + 2, line, col)
                    )
                    pos += 2
                    col += 2
                    matched_op = True
            if matched_op:
                continue

            # --- Single-char operators ---
            if ch in _SINGLE_CHAR_OPS:
                tokens.append(Token(TokenType.OPERATOR, ch, pos, pos + 1, line, col))
                pos += 1
                col += 1
                continue

            # --- Dot ---
            if ch == ".":
                tokens.append(Token(TokenType.DOT, ".", pos, pos + 1, line, col))
                pos += 1
                col += 1
                continue

            # --- Identifier / Keyword / Function ---
            if ch.isalpha() or ch == "_":
                start = pos
                start_col = col
                while pos < length and (dax[pos].isalnum() or dax[pos] == "_"):
                    pos += 1
                    col += 1
                word = dax[start:pos]
                upper = word.upper()

                # Determine classification
                token_type = self._classify_word(upper, dax, pos, length)
                tokens.append(Token(token_type, word, start, pos, line, start_col))
                continue

            # --- Unknown ---
            tokens.append(Token(TokenType.UNKNOWN, ch, pos, pos + 1, line, col))
            pos += 1
            col += 1

        return tokens

    def tokenize_code(self, dax: str) -> List[Token]:
        """Tokenize and strip comments, whitespace, and newlines."""
        _skip = {
            TokenType.COMMENT_LINE,
            TokenType.COMMENT_BLOCK,
            TokenType.WHITESPACE,
            TokenType.NEWLINE,
        }
        return [t for t in self.tokenize(dax) if t.type not in _skip]

    def build_paren_map(self, tokens: List[Token]) -> Dict[int, int]:
        """Map PAREN_OPEN index -> matching PAREN_CLOSE index."""
        stack: List[int] = []
        pmap: Dict[int, int] = {}
        for i, tok in enumerate(tokens):
            if tok.type == TokenType.PAREN_OPEN:
                stack.append(i)
            elif tok.type == TokenType.PAREN_CLOSE:
                if stack:
                    open_idx = stack.pop()
                    pmap[open_idx] = i
        return pmap

    def extract_function_args(
        self, tokens: List[Token], func_index: int
    ) -> List[List[Token]]:
        """Extract argument token lists for a function call.

        *func_index* is the index of the FUNCTION/IDENTIFIER token.
        Finds the next PAREN_OPEN after it, uses ``build_paren_map``
        to locate the matching PAREN_CLOSE, then splits on COMMA at
        depth 0.
        """
        # Find the opening paren after the function token
        paren_idx: Optional[int] = None
        for i in range(func_index + 1, len(tokens)):
            if tokens[i].type == TokenType.PAREN_OPEN:
                paren_idx = i
                break

        if paren_idx is None:
            return []

        pmap = self.build_paren_map(tokens)
        close_idx = pmap.get(paren_idx)
        if close_idx is None:
            return []

        # Split on commas at depth 0 within the parens
        args: List[List[Token]] = []
        current: List[Token] = []
        depth = 0

        for i in range(paren_idx + 1, close_idx):
            tok = tokens[i]
            if tok.type == TokenType.PAREN_OPEN:
                depth += 1
                current.append(tok)
            elif tok.type == TokenType.PAREN_CLOSE:
                depth -= 1
                current.append(tok)
            elif tok.type == TokenType.COMMA and depth == 0:
                args.append(current)
                current = []
            else:
                current.append(tok)

        if current:
            args.append(current)

        return args

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify_word(self, upper: str, dax: str, pos: int, length: int) -> TokenType:
        """Classify an identifier word as FUNCTION, KEYWORD, or IDENTIFIER."""
        # Check if followed by ( (skip whitespace)
        followed_by_paren = self._next_non_ws_is_paren(dax, pos, length)

        # Function names take priority when followed by (
        if followed_by_paren and upper in self._function_names:
            return TokenType.FUNCTION

        # Keywords (only when NOT in function_names-followed-by-paren path)
        if upper in _KEYWORDS:
            # Special case: some keywords are also functions (IF, SWITCH, AND, OR, NOT)
            # If in function_names AND followed by (, it was caught above.
            # If followed by ( but NOT in function_names, still KEYWORD.
            return TokenType.KEYWORD

        return TokenType.IDENTIFIER

    @staticmethod
    def _next_non_ws_is_paren(dax: str, pos: int, length: int) -> bool:
        """Check whether the next non-whitespace character is ``(``."""
        j = pos
        while j < length and dax[j] in (" ", "\t", "\r", "\n"):
            j += 1
        return j < length and dax[j] == "("
