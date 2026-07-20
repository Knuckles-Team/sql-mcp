"""Read-only statement gate for sql-mcp (CONCEPT:SQ-OS.safety.allow-deny-classification).

``sql_query`` accepts only read statements. The gate strips string literals,
quoted identifiers, and comments, then classifies the statement by its first
significant keyword against an allowlist (``SELECT``, ``WITH``, ``EXPLAIN``,
``SHOW``, ``DESCRIBE``, ``PRAGMA``, ``VALUES``). Mutating keywords are rejected
at every nesting depth so a data-modifying CTE cannot smuggle a write,
``SELECT ... INTO`` is rejected, and multi-statement payloads are refused
outright. SQLite ``PRAGMA`` statements use a narrower allowlist containing only
read-only inspection operations. Writes go through ``sql_execute`` and only
when the server was started with ``SQL_ALLOW_WRITES=True`` and the target is in
the explicit ``SQL_WRITE_CONNECTIONS`` allowlist.
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

# SQLite PRAGMAs that only inspect metadata or database health. Pragmas with a
# setter/action form (for example ``journal_mode``, ``user_version``,
# ``wal_checkpoint``, or ``optimize``) stay denied even when their bare form can
# also read state. Keeping dual-purpose operations out makes this boundary
# auditable and prevents syntax variants from turning an allowed read into a
# write or session-state change.
READ_ONLY_PRAGMAS = {
    "collation_list",
    "compile_options",
    "data_version",
    "database_list",
    "foreign_key_check",
    "foreign_key_list",
    "freelist_count",
    "function_list",
    "index_info",
    "index_list",
    "index_xinfo",
    "integrity_check",
    "module_list",
    "page_count",
    "pragma_list",
    "quick_check",
    "table_info",
    "table_list",
    "table_xinfo",
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
    "lock",
    "unlock",
    "use",
}

# Read-shaped calls that can mutate server state, terminate sessions, touch the
# filesystem/network, or execute native extensions. This is intentionally a
# conservative portable floor; database credentials must still be least-privilege.
SIDE_EFFECTING_READ_TOKENS = {
    "benchmark",
    "dbms_lock",
    "dblink_exec",
    "get_lock",
    "httpuritype",
    "load_extension",
    "load_file",
    "lo_export",
    "lo_import",
    "nextval",
    "openrowset",
    "opendatasource",
    "pg_advisory_lock",
    "pg_cancel_backend",
    "pg_read_file",
    "pg_terminate_backend",
    "release_lock",
    "setval",
    "sleep",
    "utl_file",
    "utl_http",
    "xp_cmdshell",
}

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\(|\)|;")
_PRAGMA_RE = re.compile(
    r"""
    \A\s*pragma\s+
    (?:[A-Za-z_][A-Za-z0-9_]*\s*\.\s*)?
    (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    \s*(?:\(\s*[^()=;]*\s*\))?\s*;?\s*\Z
    """,
    re.IGNORECASE | re.VERBOSE,
)

_TRANSACTION_CONTROL_STARTERS = {
    "abort",
    "begin",
    "commit",
    "end",
    "release",
    "rollback",
    "savepoint",
}

_UNSAFE_MANAGED_STATEMENT_STARTERS = _TRANSACTION_CONTROL_STARTERS | {
    "call",
    "do",
    "exec",
    "execute",
    "lock",
    "set",
    "unlock",
    "use",
}


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
            if i + 2 < n and not sql[i + 2].isspace():
                raise StatementNotAllowedError(
                    "Ambiguous '--' syntax is not allowed; add whitespace for a comment."
                )
            while i < n and sql[i] != "\n":
                out.append(" ")
                i += 1
        elif ch == "/" and sql[i : i + 2] == "/*":
            if sql[i : i + 3] == "/*!":
                raise StatementNotAllowedError(
                    "Executable SQL comments are not allowed."
                )
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


def _word_tokens(stripped_sql: str) -> list[str]:
    """Return normalized word tokens from literal/comment-free SQL."""
    return [
        match.group(0).lower()
        for match in _TOKEN_RE.finditer(stripped_sql)
        if match.group(0) not in ("(", ")", ";")
    ]


def _assert_read_only_pragma(stripped_sql: str) -> None:
    """Reject every SQLite PRAGMA except explicitly read-only inspections."""
    match = _PRAGMA_RE.fullmatch(stripped_sql)
    pragma = match.group("name").lower() if match else ""
    if pragma not in READ_ONLY_PRAGMAS:
        allowed = ", ".join(sorted(name.upper() for name in READ_ONLY_PRAGMAS))
        raise StatementNotAllowedError(
            f"PRAGMA {pragma.upper()!r} is not allowed in sql_query. "
            f"Read-only PRAGMAs: {allowed}."
        )


def assert_no_transaction_control(sql: str) -> None:
    """Reject SQL that can escape a caller-managed transaction boundary.

    ``execute`` and ``execute_script`` own their SQLAlchemy transaction. Letting
    a statement issue ``COMMIT``/``ROLLBACK``/``BEGIN`` (or a dialect synonym)
    can make an earlier write permanent even if a later statement fails.
    """
    stripped = assert_single_statement(sql)
    words = _word_tokens(stripped)
    if not words:
        return

    first = words[0]
    transaction_control = first in _UNSAFE_MANAGED_STATEMENT_STARTERS
    transaction_control = transaction_control or (
        first == "start" and len(words) > 1 and words[1] == "transaction"
    )
    transaction_control = transaction_control or (
        first == "prepare" and len(words) > 1 and words[1] == "transaction"
    )
    transaction_control = transaction_control or (
        first == "save" and len(words) > 1 and words[1] in {"tran", "transaction"}
    )
    transaction_control = transaction_control or (
        first == "set"
        and any(word in {"autocommit", "transaction"} for word in words[1:5])
    )
    transaction_control = transaction_control or (
        first in {"lock", "unlock"} and len(words) > 1 and words[1] == "tables"
    )
    if transaction_control:
        raise StatementNotAllowedError(
            f"Transaction/session-control statement {first.upper()!r} is not allowed "
            "inside a managed sql_execute transaction."
        )


def assert_read_only(sql: str) -> None:
    """Raise :class:`StatementNotAllowedError` unless ``sql`` is a read.

    Checks, in order: single statement, allowlisted first keyword, read-only
    PRAGMA allowlist, no mutating keyword at any nesting depth, and no ``INTO``
    (``SELECT INTO`` / ``INTO OUTFILE`` are writes).
    """
    stripped = assert_single_statement(sql)
    keyword = first_keyword(stripped)
    if keyword not in READ_ONLY_STARTERS:
        allowed = ", ".join(sorted(k.upper() for k in READ_ONLY_STARTERS))
        raise StatementNotAllowedError(
            f"Statement type {keyword.upper()!r} is not allowed by sql_query "
            f"(read-only). Allowed: {allowed}. Use sql_execute for writes "
            "(requires SQL_ALLOW_WRITES=True and an explicit "
            "SQL_WRITE_CONNECTIONS allowlist entry on the server)."
        )

    if keyword == "pragma":
        _assert_read_only_pragma(stripped)

    for match in _TOKEN_RE.finditer(stripped):
        tok = match.group(0)
        lowered = tok.lower()
        if lowered in MUTATING_KEYWORDS:
            raise StatementNotAllowedError(
                f"Keyword {lowered.upper()!r} is not allowed in sql_query "
                "(read-only). Use sql_execute for writes."
            )
        if lowered in SIDE_EFFECTING_READ_TOKENS:
            raise StatementNotAllowedError(
                f"Side-effecting operation {lowered.upper()!r} is not allowed "
                "in sql_query."
            )
        if lowered == "into":
            raise StatementNotAllowedError(
                "'INTO' is not allowed in sql_query "
                "(SELECT INTO creates objects). Use sql_execute for writes."
            )
