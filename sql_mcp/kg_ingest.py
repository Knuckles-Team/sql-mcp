"""Native epistemic-graph ingestion for SQL schemas (typed graph nodes).

CONCEPT:AU-KG.ingest.enterprise-source-extractor. sql-mcp natively pushes the
**reflected relational schema** of any configured connection into the ONE
epistemic-graph knowledge graph as **typed OWL nodes** — :DatabaseSchema,
:DatabaseTable, :DatabaseColumn, :DatabaseView, :DatabaseIndex — plus their
structural links (:hasTable / :hasColumn / :hasView / :hasIndex /
:referencesTable), matching the classes federated by ``sql_mcp.ontology``.

The txn write path is the shared fleet primitive
(``agent_utilities.knowledge_graph.memory.native_ingest``); it is imported
GUARDED and, when it is not present in the installed agent_utilities, a
self-contained txn fallback over ``GraphComputeEngine()._client`` is used
instead — the same fast client the blob ``MediaStore`` rides. Everything is
dependency-/engine-guarded: with no KG stack or no reachable engine every entry
point **no-ops** (returns ``None``), so the connector runs with zero KG
infrastructure. Node ids follow ``database:<class>:<externalId>``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("sql_mcp.kg")

_SOURCE = "sql-mcp"
_DOMAIN = "database"
_DEFAULT_GRAPH = "__commons__"


def _shared_primitive() -> Any | None:
    """Return the shared ``native_ingest`` module, or ``None`` when absent."""
    try:
        from agent_utilities.knowledge_graph.memory import (  # type: ignore
            native_ingest,
        )

        return native_ingest
    except Exception as e:  # noqa: BLE001 — primitive not in installed AU yet
        logger.debug("shared native_ingest unavailable: %s", e)
        return None


def _client() -> tuple[Any | None, str]:
    """Self-contained fallback: ``(engine_client, graph)`` or ``(None, "")``."""
    try:
        from agent_utilities.knowledge_graph.core.graph_compute import (
            GraphComputeEngine,
        )
    except Exception as e:  # noqa: BLE001 — KG stack absent
        logger.debug("KG ingest unavailable (import): %s", e)
        return None, ""
    try:
        engine = GraphComputeEngine()
        client = getattr(engine, "_client", None)
        if client is None:
            return None, ""
        return client, (getattr(engine, "graph_name", None) or _DEFAULT_GRAPH)
    except Exception as e:  # noqa: BLE001 — engine unreachable
        logger.debug("KG ingest: engine unreachable: %s", e)
        return None, ""


def _write_entities(
    client: Any,
    graph: str,
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]] | None,
    source: str,
    domain: str,
) -> dict[str, int] | None:
    """Self-contained txn: stamp provenance, MERGE nodes, then add edges."""
    try:
        txn = client.txn.begin(graph=graph)
        for ent in entities:
            props = {k: v for k, v in ent.items() if k != "id" and v is not None}
            props.setdefault("source", source)
            props.setdefault("domain", domain)
            client.txn.add_node(txn, ent["id"], props)
        committed = client.txn.commit(txn)
    except Exception as e:  # noqa: BLE001 — engine/txn failure is non-fatal
        logger.warning("KG ingest: txn failed: %s", e)
        return None
    if not committed:
        logger.warning("KG ingest: txn not committed (conflict)")
        return None

    edges = 0
    for rel in relationships or []:
        try:
            client.edges.add(
                rel["source"], rel["target"], {"type": rel.get("type", "RELATED")}
            )
            edges += 1
        except Exception as e:  # noqa: BLE001 — pure edge link, best-effort
            logger.debug("KG ingest: edge skipped: %s", e)

    logger.info("KG ingest: wrote %d nodes, %d edges", len(entities), edges)
    return {"nodes": len(entities), "edges": edges}


def ingest_entities(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]] | None = None,
    *,
    source: str = _SOURCE,
    domain: str = _DOMAIN,
    client: Any | None = None,
    graph: str | None = None,
) -> dict[str, int] | None:
    """Write typed OWL nodes (+ edges) into epistemic-graph.

    ``entities``: ``[{"id":..., "type":<owl:Class>, ...props}]``.
    ``relationships``: ``[{"source":id, "target":id, "type":<link>}]``.
    Prefers the shared ``native_ingest`` primitive; falls back to a
    self-contained txn over the fast engine client. Returns ``{"nodes":n,
    "edges":m}`` or ``None`` (no engine / failure; never raises). ``client``/
    ``graph`` may be injected (tests) — that routes straight to the fallback.
    """
    entities = [e for e in (entities or []) if e.get("id")]
    if not entities:
        return None
    if client is None:
        shared = _shared_primitive()
        if shared is not None:
            return shared.ingest_entities(
                entities, relationships, source=source, domain=domain
            )
        client, graph = _client()
    if client is None:
        return None
    return _write_entities(
        client, graph or _DEFAULT_GRAPH, entities, relationships, source, domain
    )


# ---------------------------------------------------------------------------- #
# Mappers — reflected relational schema -> typed entity/relationship dicts
# ---------------------------------------------------------------------------- #


def _schema_label(schema: str | None) -> str:
    return schema or "default"


def schema_to_entities(
    api: Any,
    connection: str | None = None,
    schema: str | None = None,
    *,
    include_views: bool = True,
    include_indexes: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reflect one connection/schema into typed entity + relationship dicts.

    Pure mapper (no KG writes) — reads through the :class:`SqlApi` facade
    (``list_tables`` / ``list_columns`` / ``list_foreign_keys`` /
    ``list_indexes`` / ``list_views``) and returns ``(entities, relationships)``
    for :func:`ingest_entities`. Best-effort per artifact: a reflection error on
    one table is logged and skipped, not raised.
    """
    conn = api.resolve_connection(connection)
    dialect = None
    try:
        spec = api.dialect_spec(conn)
        dialect = spec.name if spec is not None else None
    except Exception:  # noqa: BLE001 — dialect is decorative provenance
        dialect = None

    label = _schema_label(schema)
    schema_id = f"database:schema:{conn}.{label}"
    entities: list[dict[str, Any]] = [
        {
            "id": schema_id,
            "type": "DatabaseSchema",
            "name": label,
            "connection": conn,
            "sqlDialect": dialect,
            "externalToolId": f"{conn}.{label}",
        }
    ]
    relationships: list[dict[str, Any]] = []

    for table in api.list_tables(schema=schema, connection=conn):
        table_id = f"database:table:{conn}.{label}.{table}"
        entities.append(
            {
                "id": table_id,
                "type": "DatabaseTable",
                "name": table,
                "schema": label,
                "connection": conn,
                "externalToolId": f"{conn}.{label}.{table}",
            }
        )
        relationships.append(
            {"source": schema_id, "target": table_id, "type": "hasTable"}
        )

        fk_columns: set[str] = set()
        try:
            fks = api.list_foreign_keys(table, schema=schema, connection=conn)
        except Exception as e:  # noqa: BLE001 — reflection best-effort
            logger.debug("KG ingest: FK reflection skipped for %s: %s", table, e)
            fks = []
        for fk in fks:
            fk_columns.update(fk.get("columns") or [])
            referred = fk.get("referred_table")
            if referred:
                relationships.append(
                    {
                        "source": table_id,
                        "target": f"database:table:{conn}.{label}.{referred}",
                        "type": "referencesTable",
                    }
                )

        try:
            columns = api.list_columns(table, schema=schema, connection=conn)
        except Exception as e:  # noqa: BLE001 — reflection best-effort
            logger.debug("KG ingest: column reflection skipped for %s: %s", table, e)
            columns = []
        for col in columns:
            cname = col.get("name")
            if not cname:
                continue
            col_id = f"database:column:{conn}.{label}.{table}.{cname}"
            entities.append(
                {
                    "id": col_id,
                    "type": "DatabaseColumn",
                    "name": cname,
                    "table": table,
                    "schema": label,
                    "connection": conn,
                    "dataType": col.get("type"),
                    "isNullable": bool(col.get("nullable", True)),
                    "isPrimaryKey": bool(col.get("primary_key", False)),
                    "isForeignKey": cname in fk_columns,
                    "externalToolId": f"{conn}.{label}.{table}.{cname}",
                }
            )
            relationships.append(
                {"source": table_id, "target": col_id, "type": "hasColumn"}
            )

        if include_indexes:
            try:
                indexes = api.list_indexes(table, schema=schema, connection=conn)
            except Exception as e:  # noqa: BLE001 — reflection best-effort
                logger.debug("KG ingest: index reflection skipped for %s: %s", table, e)
                indexes = []
            for idx in indexes:
                iname = idx.get("name")
                if not iname:
                    continue
                idx_id = f"database:index:{conn}.{label}.{table}.{iname}"
                entities.append(
                    {
                        "id": idx_id,
                        "type": "DatabaseIndex",
                        "name": iname,
                        "table": table,
                        "schema": label,
                        "connection": conn,
                        "columns": ",".join(idx.get("columns") or []),
                        "isUnique": bool(idx.get("unique", False)),
                        "externalToolId": f"{conn}.{label}.{table}.{iname}",
                    }
                )
                relationships.append(
                    {"source": table_id, "target": idx_id, "type": "hasIndex"}
                )

    if include_views:
        try:
            views = api.list_views(schema=schema, connection=conn)
        except Exception as e:  # noqa: BLE001 — reflection best-effort
            logger.debug("KG ingest: view reflection skipped: %s", e)
            views = []
        for view in views:
            view_id = f"database:view:{conn}.{label}.{view}"
            entities.append(
                {
                    "id": view_id,
                    "type": "DatabaseView",
                    "name": view,
                    "schema": label,
                    "connection": conn,
                    "externalToolId": f"{conn}.{label}.{view}",
                }
            )
            relationships.append(
                {"source": schema_id, "target": view_id, "type": "hasView"}
            )

    return entities, relationships


def ingest_schema(
    api: Any,
    connection: str | None = None,
    schema: str | None = None,
    *,
    include_views: bool = True,
    include_indexes: bool = True,
    client: Any | None = None,
    graph: str | None = None,
) -> dict[str, int] | None:
    """Reflect a connection/schema and push it into the KG as typed nodes.

    Thin orchestration over :func:`schema_to_entities` +
    :func:`ingest_entities`. Best-effort: returns ``None`` when nothing is
    reflected or no engine is reachable.
    """
    entities, relationships = schema_to_entities(
        api,
        connection=connection,
        schema=schema,
        include_views=include_views,
        include_indexes=include_indexes,
    )
    return ingest_entities(entities, relationships, client=client, graph=graph)
