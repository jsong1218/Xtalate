"""Stage 1 of the CIF reader: text → tokens (DECISIONS.md D65).

Knows CIF 1.1 *syntax* and nothing else — it cannot tell a cell length from an author name.
Everything semantic (which tags are required, what they mean, how they map to the Canonical
Model) lives in stages 3 and 4, so this module and ``_document`` are the pair a future
gemmi-backed reader would replace wholesale.

The one piece of information this layer must not throw away is **quoting**. CIF spells
"unknown" as a bare ``?`` and "inapplicable" as a bare ``.``, but ``'?'`` in quotes is the
literal one-character string — so ``Token.quoted`` is what lets ``_document`` map the bare
forms to ``None`` and preserve the quoted ones. That distinction is the absence convention
(**P3**) arriving already at the tokenizer.
"""

from __future__ import annotations

from dataclasses import dataclass

# Semicolon-delimited text fields are the one construct that is line-oriented rather than
# token-oriented: a ';' in column 0 opens the field and the next ';' in column 0 closes it.
_TEXT_FIELD_DELIMITER = ";"


@dataclass(frozen=True)
class Token:
    """One lexical unit. ``line`` is 1-based and is what every downstream ``ParseIssue``
    reports as its location, so an error always points at the source line the user can see."""

    kind: str  # "data" | "loop" | "tag" | "value"
    value: str  # data block name, tag spelling, or raw value text (quotes stripped)
    line: int
    quoted: bool = False  # True iff the value came from quotes or a text field


class CifSyntaxError(Exception):
    """A CIF that cannot be tokenized at all — an unterminated quote or text field.

    Deliberately *not* a ``ParseError``: this layer knows nothing about the Canonical Model or
    the report schema, and must not import them (D65's stage rule). The plugin catches this and
    re-raises it as a structured ``ParseError``, which keeps the error contract in one place.
    """

    def __init__(self, message: str, line: int) -> None:
        super().__init__(message)
        self.message = message
        self.line = line


def tokenize(text: str) -> list[Token]:
    """Tokenize a whole CIF. Raises :class:`CifSyntaxError` on unterminated constructs."""
    tokens: list[Token] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        lineno = i + 1
        if line.startswith(_TEXT_FIELD_DELIMITER):
            value, i = _read_text_field(lines, i)
            tokens.append(Token(kind="value", value=value, line=lineno, quoted=True))
            continue
        _tokenize_line(line, lineno, tokens)
        i += 1
    return tokens


def _read_text_field(lines: list[str], start: int) -> tuple[str, int]:
    """Read a ``;``-delimited multiline text field beginning at ``lines[start]``.

    Returns the field's content and the index of the line *after* the closing delimiter. The
    opening ';' is stripped from the first line and the closing ';' line is dropped entirely;
    interior lines are preserved verbatim, since a text field is the one CIF value whose
    internal whitespace is significant (it holds abstracts, chemical names, and free prose).
    """
    body = [lines[start][1:]]
    i = start + 1
    while i < len(lines):
        if lines[i].startswith(_TEXT_FIELD_DELIMITER):
            # A text field of one line is written ";value\n;" — drop the empty leading fragment
            # rather than emitting a spurious blank first line.
            if len(body) == 1:
                return body[0].strip(), i + 1
            return "\n".join(body).strip("\n"), i + 1
        body.append(lines[i])
        i += 1
    raise CifSyntaxError(
        "unterminated semicolon text field (no closing ';' in column 1)", start + 1
    )


def _tokenize_line(line: str, lineno: int, tokens: list[Token]) -> None:
    """Tokenize one ordinary (non-text-field) line, appending to ``tokens``."""
    pos = 0
    n = len(line)
    while pos < n:
        ch = line[pos]
        if ch in " \t":
            pos += 1
            continue
        if ch == "#":
            return  # comment runs to end of line
        if ch in ("'", '"'):
            value, pos = _read_quoted(line, pos, lineno)
            tokens.append(Token(kind="value", value=value, line=lineno, quoted=True))
            continue
        word, pos = _read_bare(line, pos)
        tokens.append(_classify(word, lineno))


def _read_quoted(line: str, start: int, lineno: int) -> tuple[str, int]:
    """Read a quoted value beginning at ``line[start]``.

    CIF 1.1's closing rule is deliberately lenient: a quote character only *closes* the value
    if it is followed by whitespace or end of line. That is what lets ``'Ca(2+) O'Brien'``
    and chemical names containing apostrophes survive without escaping, so the rule is honored
    here rather than stopping at the first matching quote.
    """
    quote = line[start]
    pos = start + 1
    while pos < len(line):
        if line[pos] == quote and (pos + 1 >= len(line) or line[pos + 1] in " \t"):
            return line[start + 1 : pos], pos + 1
        pos += 1
    raise CifSyntaxError(f"unterminated {quote!r}-quoted value", lineno)


def _read_bare(line: str, start: int) -> tuple[str, int]:
    """Read an unquoted whitespace-delimited word beginning at ``line[start]``."""
    pos = start
    while pos < len(line) and line[pos] not in " \t":
        pos += 1
    return line[start:pos], pos


def _classify(word: str, lineno: int) -> Token:
    """Classify a bare word as a data heading, a ``loop_`` keyword, a tag, or a value.

    CIF keywords are case-insensitive (``DATA_`` and ``data_`` are the same construct), which
    real files exercise often enough that a case-sensitive check here would reject valid input.
    """
    lowered = word.lower()
    if lowered.startswith("data_"):
        return Token(kind="data", value=word[5:], line=lineno)
    if lowered == "loop_":
        return Token(kind="loop", value=word, line=lineno)
    if word.startswith("_"):
        return Token(kind="tag", value=word, line=lineno)
    return Token(kind="value", value=word, line=lineno)
