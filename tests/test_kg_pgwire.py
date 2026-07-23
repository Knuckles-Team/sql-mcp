"""Tests for the epistemic-graph pg-wire backend helpers (CONCEPT:KG-2.205)."""

import hashlib
import hmac

import pytest

from sql_mcp.kg_pgwire import derive_pg_password, kg_dsn, main


def _reference(secret: str, user: str) -> str:
    """Independent recomputation of the engine's derivation (auth.rs)."""
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(b"pgwire:")
    mac.update(user.encode("utf-8"))
    return mac.hexdigest()


def test_derive_pg_password_matches_engine_formula():
    secret = "super-secret-engine-key"  # sanitizer:ignore  (test fixture, not a real secret)
    user = "sql-mcp"
    assert derive_pg_password(secret, user) == _reference(secret, user)


def test_derive_pg_password_is_deterministic_and_user_scoped():
    secret = "k"
    assert derive_pg_password(secret, "a") == derive_pg_password(secret, "a")
    assert derive_pg_password(secret, "a") != derive_pg_password(secret, "b")
    # 64 hex chars = 32-byte HMAC-SHA256 digest.
    assert len(derive_pg_password(secret, "a")) == 64


def test_kg_dsn_shape():
    dsn = kg_dsn(
        "sql-mcp", "deadbeef", host="127.0.0.1", port=5433, graph="__commons__"
    )
    assert dsn == "postgresql+psycopg://sql-mcp:deadbeef@127.0.0.1:5433/__commons__"


def test_cli_derive_password(capsys, monkeypatch):
    monkeypatch.setenv("GRAPH_SERVICE_AUTH_SECRET", "envsecret")
    rc = main(["derive-password", "--user", "sql-mcp"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == _reference("envsecret", "sql-mcp")


def test_cli_dsn_uses_secret_flag(capsys):
    rc = main(["dsn", "--user", "kguser", "--secret", "s", "--graph", "team:alpha"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    expected_pw = _reference("s", "kguser")
    assert out == f"postgresql+psycopg://kguser:{expected_pw}@127.0.0.1:5433/team:alpha"


def test_cli_requires_secret(monkeypatch):
    monkeypatch.delenv("GRAPH_SERVICE_AUTH_SECRET", raising=False)
    with pytest.raises(SystemExit):
        main(["derive-password", "--user", "sql-mcp"])
