"""Native epistemic-graph ingestion for reflected relational schemas.

All writes use the required ``agent_utilities.knowledge_graph.memory.native_ingest``
primitive. Nodes use canonical ``node_type`` and edges use canonical ``relationship``;
nodes and edges commit in one native transaction. Missing engine dependencies, rejected
records, conflicts, and transaction failures propagate as ``NativeIngestError``.
"""

from __future__ import annotations

from typing import Any

from agent_utilities.knowledge_graph.memory.native_ingest import (
    ingest_entities as _native_ingest_entities,
)

_SOURCE = "sql-mcp"
_DOMAIN = "database"
_MAX_OBJECTS = 5_000
_RELATIONSHIPS_PER_OBJECT = 4


def ingest_entities(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]] | None = None,
    *,
    source: str = _SOURCE,
    domain: str = _DOMAIN,
    client: Any | None = None,
    graph: str | None = None,
) -> dict[str, int]:
    """Write canonical typed nodes and relationships in one native transaction."""
    return _native_ingest_entities(
        entities, relationships, source=source, domain=domain, client=client, graph=graph
    )


# ---------------------------------------------------------------------------- #
# Mappers — reflected relational schema -> typed entity/relationship dicts
# ---------------------------------------------------------------------------- #


def _schema_label(schema: str | None) -> str:
    return schema or "default"


def catalog_to_entities(
    catalog: dict[str, Any],
    *,
    include_indexes: bool = True,
    max_objects: int = _MAX_OBJECTS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Map one bounded :meth:`SqlApi.schema_catalog` result into graph records."""
    if (
        isinstance(max_objects, bool)
        or not isinstance(max_objects, int)
        or not 1 <= max_objects <= _MAX_OBJECTS
    ):
        raise ValueError(f"max_objects must be between 1 and {_MAX_OBJECTS}.")
    if not isinstance(catalog, dict) or not isinstance(catalog.get("objects"), list):
        raise ValueError("catalog must be a bounded SQL schema catalog object.")

    connection = str(catalog.get("connection") or "default")
    label = _schema_label(catalog.get("schema"))
    schema_id = f"database:schema:{connection}.{label}"
    entities: list[dict[str, Any]] = [
        {
            "id": schema_id,
            "node_type": "DatabaseSchema",
            "name": label,
            "connection": connection,
            "sqlDialect": catalog.get("dialect"),
            "externalToolId": f"{connection}.{label}",
        }
    ]
    relationships: list[dict[str, Any]] = []
    max_relationships = max_objects * _RELATIONSHIPS_PER_OBJECT

    def add_relationship(source: str, target: str, relationship: str) -> None:
        if len(relationships) < max_relationships:
            relationships.append(
                {
                    "source": source,
                    "target": target,
                    "relationship": relationship,
                }
            )

    for item in catalog["objects"]:
        if len(entities) >= max_objects or not isinstance(item, dict):
            break
        name = item.get("name")
        object_type = item.get("type")
        if not isinstance(name, str) or not name:
            continue
        if object_type == "view":
            view_id = f"database:view:{connection}.{label}.{name}"
            entities.append(
                {
                    "id": view_id,
                    "node_type": "DatabaseView",
                    "name": name,
                    "schema": label,
                    "connection": connection,
                    "externalToolId": f"{connection}.{label}.{name}",
                }
            )
            add_relationship(schema_id, view_id, "hasView")
            continue
        if object_type != "table":
            continue

        table_id = f"database:table:{connection}.{label}.{name}"
        entities.append(
            {
                "id": table_id,
                "node_type": "DatabaseTable",
                "name": name,
                "schema": label,
                "connection": connection,
                "externalToolId": f"{connection}.{label}.{name}",
            }
        )
        add_relationship(schema_id, table_id, "hasTable")
        foreign_keys = item.get("foreign_keys") or []
        foreign_key_columns: set[str] = set()
        for foreign_key in foreign_keys:
            if not isinstance(foreign_key, dict):
                continue
            foreign_key_columns.update(foreign_key.get("columns") or [])
            referred = foreign_key.get("referred_table")
            if isinstance(referred, str) and referred:
                target = f"database:table:{connection}.{label}.{referred}"
                add_relationship(table_id, target, "referencesTable")

        for column in item.get("columns") or []:
            if len(entities) >= max_objects or not isinstance(column, dict):
                break
            column_name = column.get("name")
            if not isinstance(column_name, str) or not column_name:
                continue
            column_id = (
                f"database:column:{connection}.{label}.{name}.{column_name}"
            )
            entities.append(
                {
                    "id": column_id,
                    "node_type": "DatabaseColumn",
                    "name": column_name,
                    "table": name,
                    "schema": label,
                    "connection": connection,
                    "dataType": column.get("type"),
                    "isNullable": bool(column.get("nullable", True)),
                    "isPrimaryKey": bool(column.get("primary_key", False)),
                    "isForeignKey": column_name in foreign_key_columns,
                    "externalToolId": (
                        f"{connection}.{label}.{name}.{column_name}"
                    ),
                }
            )
            add_relationship(table_id, column_id, "hasColumn")

        if not include_indexes:
            continue
        for index in item.get("indexes") or []:
            if len(entities) >= max_objects or not isinstance(index, dict):
                break
            index_name = index.get("name")
            if not isinstance(index_name, str) or not index_name:
                continue
            index_id = f"database:index:{connection}.{label}.{name}.{index_name}"
            entities.append(
                {
                    "id": index_id,
                    "node_type": "DatabaseIndex",
                    "name": index_name,
                    "table": name,
                    "schema": label,
                    "connection": connection,
                    "columns": ",".join(index.get("columns") or []),
                    "isUnique": bool(index.get("unique", False)),
                    "externalToolId": (
                        f"{connection}.{label}.{name}.{index_name}"
                    ),
                }
            )
            add_relationship(table_id, index_id, "hasIndex")

    return entities, relationships
