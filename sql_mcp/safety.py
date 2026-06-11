"""Read-only statement gate for sql-mcp (CONCEPT:SQL-1.3).

``sql_query`` accepts only read statements. The gate strips string literals,
quoted identifiers, and comments, then classifies the statement by its first
significant keyword against an allowlist (``SELECT``, ``WITH``, ``EXPLAIN``,
``SHOW``, ``DESCRIBE``, ``PRAGMA``, ``VALUES``). CTEs are inspected at paren
depth zero so ``WITH ... INSERT`` cannot smuggle a write, ``SELECT ... INTO``
is rejected, and multi-statement payloads are refused outright. Writes go
through ``sql_execute`` and only when the server was started with
``SQL_ALLOW_WRITES=True``.
"""

import re

READ_ONLY_STARTERS = {
    "select",
    "with",
    "explain",
    "show",
    "describe",
    "desc",
    "pragma",
    "values",
}

MUTATING_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "merge",
    "replace",
    "truncate",
    "create",
    "alter",
    "drop",
    "grant",
    "revoke",
    "call",
    "exec",
    "execute",
    "set",
    "copy",
    "vacuum",
    "attach",
    "detach",
}

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\(|\)|;")


class StatementNotAllowedError(ValueError):
    """Raised when a statement violates the read-only or single-statement gate."""


def strip_literals_and_comments(sql: str) -> str:
    """Replace string literals, quoted identifiers, and comments with spaces.

    Keeps offsets stable so keyword scanning cannot be fooled by SQL keywords
    embedded in strings, quoted identifiers, or comments.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"', "`"):
            quote = ch
            out.append(" ")
            i += 1
            while i < n:
                if sql[i] == quote:
                    # Doubled quote = escaped quote inside the literal.
                    if i + 1 < n and sql[i + 1] == quote:
                        out.append("  ")
                        i += 2
                        continue
                    out.append(" ")
                    i += 1
                    break
                out.append(" " if sql[i] != "\n" else "\n")
                i += 1
        elif ch == "[":
            # T-SQL bracketed identifier.
            out.append(" ")
            i += 1
            while i < n and sql[i] != "]":
                out.append(" ")
                i += 1
            if i < n:
                out.append(" ")
                i += 1
        elif ch == "-" and sql[i : i + 2] == "--":
            while i < n and sql[i] != "\n":
                out.append(" ")
                i += 1
        elif ch == "/" and sql[i : i + 2] == "/*":
            out.append("  ")
            i += 2
            while i < n and sql[i : i + 2] != "*/":
                out.append(" " if sql[i] != "\n" else "\n")
                i += 1
            if i < n:
                out.append("  ")
                i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def assert_single_statement(sql: str) -> str:
    """Reject payloads containing more than one SQL statement.

    Returns the stripped (literal/comment-free) text for further inspection.
    """
    stripped = strip_literals_and_comments(sql)
    head, sep, tail = stripped.partition(";")
    if sep and tail.strip():
        raise StatementNotAllowedError(
            "Multiple SQL statements in one call are not allowed; "
            "send one statement per call (sql_execute action 'script' runs "
            "a list of statements in a single transaction)."
        )
    if not head.strip():
        raise StatementNotAllowedError("Empty SQL statement.")
    return stripped


def first_keyword(stripped_sql: str) -> str:
    """Return the first significant keyword of a stripped statement."""
    for match in _TOKEN_RE.finditer(stripped_sql):
        tok = match.group(0)
        if tok in ("(", ")", ";"):
            continue
        return tok.lower()
    return ""


def assert_read_only(sql: str) -> None:
    """Raise :class:`StatementNotAllowedError` unless ``sql`` is a read.

    Checks, in order: single statement, allowlisted first keyword, no
    depth-zero mutating keyword inside a CTE, and no depth-zero ``INTO``
    (``SELECT INTO`` / ``INTO OUTFILE`` are writes).
    """
    stripped = assert_single_statement(sql)
    keyword = first_keyword(stripped)
    if keyword not in READ_ONLY_STARTERS:
        allowed = ", ".join(sorted(k.upper() for k in READ_ONLY_STARTERS))
        raise StatementNotAllowedError(
            f"Statement type {keyword.upper()!r} is not allowed by sql_query "
            f"(read-only). Allowed: {allowed}. Use sql_execute for writes "
            "(requires SQL_ALLOW_WRITES=True on the server)."
        )

    depth = 0
    for match in _TOKEN_RE.finditer(stripped):
        tok = match.group(0)
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            lowered = tok.lower()
            if lowered in MUTATING_KEYWORDS:
                raise StatementNotAllowedError(
                    f"Top-level {lowered.upper()!r} is not allowed in sql_query "
                    "(read-only). Use sql_execute for writes."
                )
            if lowered == "into":
                raise StatementNotAllowedError(
                    "Top-level 'INTO' is not allowed in sql_query "
                    "(SELECT INTO creates objects). Use sql_execute for writes."
                )
