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
