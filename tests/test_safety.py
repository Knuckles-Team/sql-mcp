"""Read-only statement gate (CONCEPT:SQL-1.3) — allow/deny classification."""

import pytest

from sql_mcp.safety import (
    StatementNotAllowedError,
    assert_read_only,
    assert_single_statement,
    first_keyword,
    strip_literals_and_comments,
)

ALLOWED = [
    "SELECT 1",
    "select name from users where id = :id",
    "  \n SELECT * FROM users -- trailing comment",
    "WITH top AS (SELECT id FROM users) SELECT * FROM top",
    "WITH a AS (SELECT 1), b AS (SELECT 2) SELECT * FROM a JOIN b",
    "EXPLAIN QUERY PLAN SELECT * FROM users",
    "SHOW TABLES",
    "DESCRIBE users",
    "PRAGMA table_info(users)",
    "VALUES (1, 2)",
    "SELECT 'delete from users' AS phrase",
    "SELECT * FROM users; ",
    "/* leading comment */ SELECT 1",
    "SELECT (SELECT max(id) FROM orders) AS m FROM users",
]

DENIED = [
    "INSERT INTO users (id) VALUES (1)",
    "UPDATE users SET name = 'x'",
    "DELETE FROM users",
    "DROP TABLE users",
    "CREATE TABLE t (a int)",
    "ALTER TABLE users ADD COLUMN x int",
    "TRUNCATE TABLE users",
    "GRANT ALL ON users TO bob",
    "MERGE INTO t USING s ON t.id = s.id",
    "CALL some_procedure()",
    "EXEC sp_who",
    "WITH cte AS (SELECT 1) DELETE FROM users",
    "WITH cte AS (SELECT 1) INSERT INTO t SELECT * FROM cte",
    "SELECT * INTO new_table FROM users",
    "SELECT 1; DROP TABLE users",
    "SELECT 1; -- ok\nDELETE FROM users",
    "VACUUM",
    "ATTACH DATABASE 'x.db' AS x",
    "",
    "   ",
    "-- just a comment",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_read_only_statements_pass(sql):
    assert_read_only(sql)


@pytest.mark.parametrize("sql", DENIED)
def test_non_read_statements_rejected(sql):
    with pytest.raises(StatementNotAllowedError):
        assert_read_only(sql)


def test_keywords_inside_strings_are_ignored():
    stripped = strip_literals_and_comments("SELECT 'DROP TABLE x' AS a, \"b\" FROM t")
    assert "DROP" not in stripped
    assert first_keyword(stripped) == "select"


def test_doubled_quotes_stay_inside_literal():
    assert_read_only("SELECT 'it''s; DELETE FROM users' AS quip")


def test_bracketed_identifiers_are_stripped():
    stripped = strip_literals_and_comments("SELECT [delete] FROM t")
    assert "delete" not in stripped.lower()


def test_block_comment_cannot_hide_second_statement():
    with pytest.raises(StatementNotAllowedError):
        assert_read_only("SELECT 1 /* x */; UPDATE users SET name='y'")


def test_single_statement_returns_stripped_text():
    stripped = assert_single_statement("SELECT 1 -- note")
    assert "note" not in stripped


def test_multi_statement_error_mentions_script():
    with pytest.raises(StatementNotAllowedError, match="script"):
        assert_single_statement("SELECT 1; SELECT 2")


def test_rejection_error_names_allowed_types():
    with pytest.raises(StatementNotAllowedError, match="SELECT"):
        assert_read_only("DELETE FROM users")
