"""Shared fixtures: in-memory SQLite connections, seeded schema, no live DBs."""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from sql_mcp.api_client import Api

SEED_STATEMENTS = [
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT
    )
    """,
    "CREATE INDEX ix_users_name ON users (name)",
    """
    CREATE TABLE orders (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users (id),
        total REAL NOT NULL
    )
    """,
    "CREATE VIEW user_emails AS SELECT name, email FROM users",
    "INSERT INTO users (id, name, email) VALUES (1, 'ada', 'ada@example.com')",
    "INSERT INTO users (id, name, email) VALUES (2, 'grace', 'grace@example.com')",
    "INSERT INTO users (id, name, email) VALUES (3, 'alan', NULL)",
    "INSERT INTO orders (id, user_id, total) VALUES (10, 1, 99.5)",
    "INSERT INTO orders (id, user_id, total) VALUES (11, 2, 12.0)",
]

MEMORY_URL = "sqlite+pysqlite:///:memory:"


def seed(engine) -> None:
    with engine.begin() as conn:
        for stmt in SEED_STATEMENTS:
            conn.execute(text(stmt))


def build_api(**overrides) -> Api:
    """A read-only Api with two independent in-memory SQLite connections."""
    kwargs: dict = {
        "connections": {
            "primary": make_url(MEMORY_URL),
            "analytics": make_url(MEMORY_URL),
        },
        "allow_writes": False,
        "max_rows": 100,
        "timeout": 10.0,
    }
    kwargs.update(overrides)
    return Api(**kwargs)


@pytest.fixture
def api():
    """Read-only Api; 'primary' is seeded, 'analytics' is empty."""
    client = build_api()
    seed(client.engine("primary"))
    yield client
    client.dispose()


@pytest.fixture
def writable_api():
    """Same registry with writes enabled."""
    client = build_api(allow_writes=True)
    seed(client.engine("primary"))
    yield client
    client.dispose()
