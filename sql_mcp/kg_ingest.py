"""Epistemic-graph ingestion for reflected relational schemas.

Writes use ``agent_connector_sdk.ingest`` -- the generated ``SourceIngest`` client,
not a local ingestion helper. Nodes use canonical ``node_type`` and edges use
canonical ``relationship``; nodes and edges commit in one transaction. Missing
engine dependencies, rejected records, conflicts, and transaction failures
propagate as ``IngestError``.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import (
    ChangeSet,
    Entity,
    IngestBinding,
    IngestError,
    KnowledgeIngest,
    Relationship,
    current_ingest,
)

_BINDING = IngestBinding(connector="sql-mcp", stream="database")
_MAX_OBJECTS = 5_000
_RELATIONSHIPS_PER_OBJECT = 4

_ENTITY_RESERVED_KEYS = frozenset({"id", "node_type"})
_RELATIONSHIP_RESERVED_KEYS = frozenset({"source", "target", "relationship"})


def _to_entity(record: dict[str, Any]) -> Entity:
    return Entity(
        id=record.get("id"),
        node_type=record.get("node_type"),
        properties={
            key: value
            for key, value in record.items()
            if key not in _ENTITY_RESERVED_KEYS
        },
    )


def _to_relationship(record: dict[str, Any]) -> Relationship:
    properties = {
        key: value
        for key, value in record.items()
        if key not in _RELATIONSHIP_RESERVED_KEYS
    }
    return Relationship(
        source=record["source"],
        target=record["target"],
        relationship=record["relationship"],
        properties=properties or None,
    )


async def ingest_entities(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]] | None = None,
    *,
    ingest: KnowledgeIngest | None = None,
) -> dict[str, int]:
    """Write canonical typed nodes and relationships in one transaction."""
    if not entities:
        raise IngestError("ingest_entities needs at least one entity")
    change_set = ChangeSet(
        entities=tuple(_to_entity(entity) for entity in entities),
        relationships=tuple(
            _to_relationship(relationship) for relationship in relationships or ()
        ),
    )
    service = ingest or current_ingest()
    receipt = await service.submit(_BINDING, change_set)
    return {"nodes": receipt.affected_count, "edges": receipt.relationship_count}


# ---------------------------------------------------------------------------- #
# Mappers — reflected relational schema -> typed entity/relationship dicts
# ---------------------------------------------------------------------------- #


def _schema_label(schema: str | None) -> str:
    return schema or "default"


class _CatalogIngestState:
    """Accumulates entities/relationships while mapping one schema catalog,
    enforcing the bounded max_objects/max_relationships caps.
    """

    def __init__(
        self, connection: str, label: str, schema_id: str, max_objects: int
    ) -> None:
        self.connection = connection
        self.label = label
        self.schema_id = schema_id
        self.max_objects = max_objects
        self.max_relationships = max_objects * _RELATIONSHIPS_PER_OBJECT
        self.entities: list[dict[str, Any]] = []
        self.relationships: list[dict[str, Any]] = []

    def entities_full(self) -> bool:
        return len(self.entities) >= self.max_objects

    def add_entity(self, entity: dict[str, Any]) -> None:
        self.entities.append(entity)

    def add_relationship(self, source: str, target: str, relationship: str) -> None:
        if len(self.relationships) < self.max_relationships:
            self.relationships.append(
                {
                    "source": source,
                    "target": target,
                    "relationship": relationship,
                }
            )


def _validate_max_objects(max_objects: int) -> None:
    if (
        isinstance(max_objects, bool)
        or not isinstance(max_objects, int)
        or not 1 <= max_objects <= _MAX_OBJECTS
    ):
        raise ValueError(f"max_objects must be between 1 and {_MAX_OBJECTS}.")


def _validate_catalog_shape(catalog: dict[str, Any]) -> None:
    if not isinstance(catalog, dict) or not isinstance(catalog.get("objects"), list):
        raise ValueError("catalog must be a bounded SQL schema catalog object.")


def _add_view_entity(state: _CatalogIngestState, name: str) -> None:
    view_id = f"database:view:{state.connection}.{state.label}.{name}"
    state.add_entity(
        {
            "id": view_id,
            "node_type": "DatabaseView",
            "name": name,
            "schema": state.label,
            "connection": state.connection,
            "externalToolId": f"{state.connection}.{state.label}.{name}",
        }
    )
    state.add_relationship(state.schema_id, view_id, "hasView")


def _add_table_entity(state: _CatalogIngestState, name: str) -> str:
    table_id = f"database:table:{state.connection}.{state.label}.{name}"
    state.add_entity(
        {
            "id": table_id,
            "node_type": "DatabaseTable",
            "name": name,
            "schema": state.label,
            "connection": state.connection,
            "externalToolId": f"{state.connection}.{state.label}.{name}",
        }
    )
    state.add_relationship(state.schema_id, table_id, "hasTable")
    return table_id


def _add_foreign_key_relationships(
    state: _CatalogIngestState, table_id: str, foreign_keys: list
) -> set[str]:
    foreign_key_columns: set[str] = set()
    for foreign_key in foreign_keys:
        if not isinstance(foreign_key, dict):
            continue
        foreign_key_columns.update(foreign_key.get("columns") or [])
        referred = foreign_key.get("referred_table")
        if isinstance(referred, str) and referred:
            target = f"database:table:{state.connection}.{state.label}.{referred}"
            state.add_relationship(table_id, target, "referencesTable")
    return foreign_key_columns


def _add_column_entities(
    state: _CatalogIngestState,
    table_id: str,
    table_name: str,
    columns: list,
    foreign_key_columns: set[str],
) -> None:
    for column in columns:
        if state.entities_full() or not isinstance(column, dict):
            break
        column_name = column.get("name")
        if not isinstance(column_name, str) or not column_name:
            continue
        column_id = (
            f"database:column:{state.connection}.{state.label}."
            f"{table_name}.{column_name}"
        )
        state.add_entity(
            {
                "id": column_id,
                "node_type": "DatabaseColumn",
                "name": column_name,
                "table": table_name,
                "schema": state.label,
                "connection": state.connection,
                "dataType": column.get("type"),
                "isNullable": bool(column.get("nullable", True)),
                "isPrimaryKey": bool(column.get("primary_key", False)),
                "isForeignKey": column_name in foreign_key_columns,
                "externalToolId": (
                    f"{state.connection}.{state.label}.{table_name}.{column_name}"
                ),
            }
        )
        state.add_relationship(table_id, column_id, "hasColumn")


def _add_index_entities(
    state: _CatalogIngestState, table_id: str, table_name: str, indexes: list
) -> None:
    for index in indexes:
        if state.entities_full() or not isinstance(index, dict):
            break
        index_name = index.get("name")
        if not isinstance(index_name, str) or not index_name:
            continue
        index_id = (
            f"database:index:{state.connection}.{state.label}.{table_name}.{index_name}"
        )
        state.add_entity(
            {
                "id": index_id,
                "node_type": "DatabaseIndex",
                "name": index_name,
                "table": table_name,
                "schema": state.label,
                "connection": state.connection,
                "columns": ",".join(index.get("columns") or []),
                "isUnique": bool(index.get("unique", False)),
                "externalToolId": (
                    f"{state.connection}.{state.label}.{table_name}.{index_name}"
                ),
            }
        )
        state.add_relationship(table_id, index_id, "hasIndex")


def _add_table_object(
    state: _CatalogIngestState, item: dict, name: str, include_indexes: bool
) -> None:
    table_id = _add_table_entity(state, name)
    foreign_key_columns = _add_foreign_key_relationships(
        state, table_id, item.get("foreign_keys") or []
    )
    _add_column_entities(
        state, table_id, name, item.get("columns") or [], foreign_key_columns
    )
    if include_indexes:
        _add_index_entities(state, table_id, name, item.get("indexes") or [])


def _add_catalog_object(
    state: _CatalogIngestState, item: dict, include_indexes: bool
) -> None:
    name = item.get("name")
    object_type = item.get("type")
    if not isinstance(name, str) or not name:
        return
    if object_type == "view":
        _add_view_entity(state, name)
        return
    if object_type != "table":
        return
    _add_table_object(state, item, name, include_indexes)


def catalog_to_entities(
    catalog: dict[str, Any],
    *,
    include_indexes: bool = True,
    max_objects: int = _MAX_OBJECTS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Map one bounded :meth:`SqlApi.schema_catalog` result into graph records."""
    _validate_max_objects(max_objects)
    _validate_catalog_shape(catalog)

    connection = str(catalog.get("connection") or "default")
    label = _schema_label(catalog.get("schema"))
    schema_id = f"database:schema:{connection}.{label}"
    state = _CatalogIngestState(connection, label, schema_id, max_objects)
    state.add_entity(
        {
            "id": schema_id,
            "node_type": "DatabaseSchema",
            "name": label,
            "connection": connection,
            "sqlDialect": catalog.get("dialect"),
            "externalToolId": f"{connection}.{label}",
        }
    )

    for item in catalog["objects"]:
        if state.entities_full() or not isinstance(item, dict):
            break
        _add_catalog_object(state, item, include_indexes)

    return state.entities, state.relationships
