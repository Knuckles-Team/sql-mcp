"""epistemic-graph pg-wire backend helpers for sql-mcp (CONCEPT:SQL-1.7, CONCEPT:KG-2.205).

The epistemic-graph engine exposes its Knowledge Graph over the Postgres wire
protocol (CONCEPT:KG-2.189): a server built ``--features pgwire`` and run with
``EPISTEMIC_GRAPH_PGWIRE_ADDR`` set (documented loopback ``127.0.0.1:5433``)
accepts native SQLAlchemy/psycopg connections and runs read-only SQL over the
``nodes``/``edges`` tables. That makes the KG just another named sql-mcp
connection — no special transport, no bespoke connector.

Auth (CONCEPT:KG-2.202): under SCRAM mode a pg ``user`` maps to an engine
``agent_id`` and its password is **derived** from the engine's shared secret::

    derived_password(user) = hex(HMAC-SHA256(GRAPH_SERVICE_AUTH_SECRET,
                                             "pgwire:" + user))

An operator who holds the engine secret computes each agent's pg password
offline; the engine validates the SCRAM proof against the same derivation
without storing per-user passwords. This module reproduces that derivation so
the sql-mcp ``kg`` connection's password can be generated and stored as a vault
ref (OpenBao ``apps/sql-mcp`` key ``KG_PGWIRE_PASSWORD``).

CLI::

    python -m sql_mcp.kg_pgwire derive-password --user sql-mcp [--secret …]
    python -m sql_mcp.kg_pgwire dsn --user sql-mcp [--host 127.0.0.1] [--port 5433]

``--secret`` falls back to the ``GRAPH_SERVICE_AUTH_SECRET`` env var so the
secret never has to appear on the command line.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys

#: HMAC prefix the engine uses (`auth.rs::derive_pg_password`). Keep in lockstep.
_PGWIRE_PREFIX = b"pgwire:"


def derive_pg_password(secret: str, user: str) -> str:
    """Return ``hex(HMAC-SHA256(secret, "pgwire:"+user))`` (CONCEPT:KG-2.202).

    Byte-for-byte the engine's ``derive_pg_password`` in
    ``epistemic-graph/src/server/pgwire/auth.rs`` — the SCRAM password the engine
    validates a login against, computable offline by anyone holding the engine
    secret. A change there is a breaking change here (No-Legacy: keep them atomic).
    """
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(_PGWIRE_PREFIX)
    mac.update(user.encode("utf-8"))
    return mac.hexdigest()


def kg_dsn(
    user: str,
    password: str,
    *,
    host: str = "127.0.0.1",
    port: int = 5433,
    graph: str = "__commons__",
) -> str:
    """Build the SQLAlchemy DSN for the KG pg-wire connection.

    ``postgresql+psycopg://<user>:<password>@<host>:<port>/<graph>`` — the
    ``database`` segment selects the engine graph the connection runs against
    (CONCEPT:KG-2.189), defaulting to ``__commons__``.
    """
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{graph}"


def _resolve_secret(arg_secret: str | None) -> str:
    secret = arg_secret or os.environ.get("GRAPH_SERVICE_AUTH_SECRET", "")
    if not secret:
        raise SystemExit(
            "no engine secret: pass --secret or set GRAPH_SERVICE_AUTH_SECRET."
        )
    return secret


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sql_mcp.kg_pgwire",
        description="Derive the epistemic-graph pg-wire SCRAM password / DSN.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pw = sub.add_parser("derive-password", help="Print the derived pg password.")
    p_pw.add_argument("--user", required=True, help="pg user = engine agent_id.")
    p_pw.add_argument(
        "--secret", default=None, help="Engine GRAPH_SERVICE_AUTH_SECRET."
    )

    p_dsn = sub.add_parser("dsn", help="Print the full SQLAlchemy DSN.")
    p_dsn.add_argument("--user", required=True, help="pg user = engine agent_id.")
    p_dsn.add_argument(
        "--secret", default=None, help="Engine GRAPH_SERVICE_AUTH_SECRET."
    )
    p_dsn.add_argument("--host", default="127.0.0.1")
    p_dsn.add_argument("--port", type=int, default=5433)
    p_dsn.add_argument("--graph", default="__commons__")

    args = parser.parse_args(argv)
    secret = _resolve_secret(args.secret)
    password = derive_pg_password(secret, args.user)

    if args.cmd == "derive-password":
        print(password)
    else:  # dsn
        print(
            kg_dsn(
                args.user,
                password,
                host=args.host,
                port=args.port,
                graph=args.graph,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
