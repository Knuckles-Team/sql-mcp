"""Epistemic-graph typed-node ingestion -- Wire-First coverage for sql-mcp.

Exercises the real ``ingest_entities`` seam against a fake
``agent_connector_sdk.ingest`` transport (no engine required), plus the pure
``catalog_to_entities`` mapper (unaffected by the ingestion migration). The
real SDK request builder (``agent_connector_sdk.ingest.request.build_request``)
still runs, so a malformed change set is still caught by the SDK's own
contract, not re-derived here; only the final network commit is faked.
CONCEPT:AU-KG.ingest.enterprise-source-extractor.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from agent_connector_sdk.ingest import IngestError, KnowledgeIngest
from epistemic_graph.generated.source_ingestion import SourceIngestionRequest

from sql_mcp.kg_ingest import catalog_to_entities, ingest_entities


class _FakeTransport:
    """Records every submitted request; no epistemic-graph engine required."""

    def __init__(self) -> None:
        self.requests: list[SourceIngestionRequest] = []

    async def source_status(self, _connector: str, _stream: str) -> Any:
        return SimpleNamespace(accepted_checkpoint=None)

    async def submit(self, request: SourceIngestionRequest) -> Any:
        self.requests.append(request)
        return SimpleNamespace(
            affected_count=len(request.records),
            relationship_count=len(request.relationships),
        )

    async def store_blob(self, _data: bytes) -> str:
        raise AssertionError("sql-mcp ingestion carries no media")


@pytest.fixture
def ingest() -> tuple[KnowledgeIngest, _FakeTransport]:
    transport = _FakeTransport()
    return KnowledgeIngest(transport, loop=None), transport


def _catalog():
    return {
        "connection": "default",
        "schema": "public",
        "dialect": "postgres",
        "objects": [
            {
                "name": "users",
                "type": "table",
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "nullable": False,
                        "primary_key": True,
                    },
                    {"name": "org_id", "type": "INTEGER", "nullable": True},
                ],
                "foreign_keys": [
                    {"columns": ["org_id"], "referred_table": "orgs"}
                ],
                "indexes": [
                    {
                        "name": "ix_users_org",
                        "columns": ["org_id"],
                        "unique": False,
                    }
                ],
            },
            {"name": "active_users", "type": "view"},
        ],
    }


@pytest.mark.asyncio
async def test_ingest_entities_writes_nodes_and_edges(ingest):
    service, transport = ingest
    res = await ingest_entities(
        [
            {"id": "a", "node_type": "DatabaseTable", "name": "t"},
            {"id": "b", "node_type": "DatabaseColumn"},
        ],
        [{"source": "a", "target": "b", "relationship": "hasColumn"}],
        ingest=service,
    )
    assert res == {"nodes": 2, "edges": 1}
    assert len(transport.requests) == 1
    request = transport.requests[0]
    record_ids = {record.record_id for record in request.records}
    assert record_ids == {"a", "b"}
    a_record = next(r for r in request.records if r.record_id == "a")
    assert a_record.payload["name"] == "t"
    assert request.relationships[0].relation_reference.endswith(
        "resources/DatabaseTable/relations/hasColumn"
    )


def test_catalog_to_entities_maps_tables_columns_views_indexes():
    entities, rels = catalog_to_entities(_catalog())
    by_id = {e["id"]: e for e in entities}

    schema_id = "database:schema:default.public"
    table_id = "database:table:default.public.users"
    col_id = "database:column:default.public.users.org_id"
    view_id = "database:view:default.public.active_users"
    idx_id = "database:index:default.public.users.ix_users_org"

    assert by_id[schema_id]["node_type"] == "DatabaseSchema"
    assert by_id[schema_id]["sqlDialect"] == "postgres"
    assert by_id[table_id]["node_type"] == "DatabaseTable"
    assert by_id[col_id]["node_type"] == "DatabaseColumn"
    assert by_id[col_id]["dataType"] == "INTEGER"
    assert by_id[col_id]["isForeignKey"] is True
    assert by_id["database:column:default.public.users.id"]["isPrimaryKey"] is True
    assert by_id[view_id]["node_type"] == "DatabaseView"
    assert by_id[idx_id]["node_type"] == "DatabaseIndex"
    assert by_id[idx_id]["isUnique"] is False

    assert {"source": schema_id, "target": table_id, "relationship": "hasTable"} in rels
    assert {"source": table_id, "target": col_id, "relationship": "hasColumn"} in rels
    assert {"source": schema_id, "target": view_id, "relationship": "hasView"} in rels
    assert {"source": table_id, "target": idx_id, "relationship": "hasIndex"} in rels
    assert {
        "source": table_id,
        "target": "database:table:default.public.orgs",
        "relationship": "referencesTable",
    } in rels


def test_catalog_to_entities_can_skip_indexes_and_bound_output():
    entities, relationships = catalog_to_entities(
        _catalog(), include_indexes=False, max_objects=4
    )
    types = {e["node_type"] for e in entities}
    assert "DatabaseIndex" not in types
    assert "DatabaseTable" in types
    assert len(entities) <= 4
    assert len(relationships) <= 16


@pytest.mark.parametrize("max_objects", [0, 5_001, True, 1.5])
def test_catalog_to_entities_rejects_invalid_bounds(max_objects):
    with pytest.raises(ValueError, match="max_objects"):
        catalog_to_entities(_catalog(), max_objects=max_objects)


@pytest.mark.asyncio
async def test_retired_structural_alias_is_rejected(ingest):
    service, _transport = ingest
    with pytest.raises(IngestError, match="node_type"):
        await ingest_entities([{"id": "a", "type": "DatabaseTable"}], ingest=service)


@pytest.mark.asyncio
async def test_empty_ingest_is_rejected(ingest):
    service, _transport = ingest
    with pytest.raises(IngestError, match="at least one entity"):
        await ingest_entities([], ingest=service)


# --------------------------------------------------------------------- #
# catalog_to_entities: branches the happy-path fixture above never visits
# --------------------------------------------------------------------- #


def test_catalog_to_entities_rejects_missing_objects_list():
    with pytest.raises(ValueError, match="bounded SQL schema catalog"):
        catalog_to_entities({"connection": "default"})


def test_catalog_to_entities_rejects_non_dict_catalog():
    invalid_catalog: Any = "not-a-catalog"
    with pytest.raises(ValueError, match="bounded SQL schema catalog"):
        catalog_to_entities(invalid_catalog)


def test_catalog_to_entities_defaults_unset_schema_to_default_label():
    catalog = {"connection": "default", "objects": []}
    entities, _ = catalog_to_entities(catalog)
    assert entities[0]["id"] == "database:schema:default.default"
    assert entities[0]["name"] == "default"


def test_catalog_to_entities_skips_non_dict_and_unrecognized_objects():
    catalog = {
        "connection": "default",
        "schema": "public",
        "objects": [
            "not-a-dict-object",
            {"name": "some_sequence", "type": "sequence"},
            {"type": "table"},  # missing name -> skipped
            {"name": "", "type": "table"},  # empty name -> skipped
        ],
    }
    entities, relationships = catalog_to_entities(catalog)
    # Only the schema entity itself survives; every object was rejected.
    assert [e["node_type"] for e in entities] == ["DatabaseSchema"]
    assert relationships == []


def test_catalog_to_entities_stops_at_first_non_dict_object():
    catalog = {
        "connection": "default",
        "schema": "public",
        "objects": [{"name": "a", "type": "view"}, None, {"name": "b", "type": "view"}],
    }
    entities, _ = catalog_to_entities(catalog)
    view_names = {e["name"] for e in entities if e["node_type"] == "DatabaseView"}
    assert view_names == {"a"}


def test_catalog_to_entities_skips_non_dict_foreign_keys():
    catalog = {
        "connection": "default",
        "schema": "public",
        "objects": [
            {
                "name": "orders",
                "type": "table",
                "columns": [],
                "foreign_keys": ["not-a-dict-fk", {"referred_table": "users"}],
            }
        ],
    }
    entities, relationships = catalog_to_entities(catalog)
    table_id = "database:table:default.public.orders"
    assert {
        "source": table_id,
        "target": "database:table:default.public.users",
        "relationship": "referencesTable",
    } in relationships
    assert len([r for r in relationships if r["relationship"] == "referencesTable"]) == 1


def test_catalog_to_entities_skips_invalid_columns_and_indexes():
    catalog = {
        "connection": "default",
        "schema": "public",
        "objects": [
            {
                "name": "widgets",
                "type": "table",
                "columns": ["not-a-dict-column", {"name": ""}, {"type": "INTEGER"}],
                "indexes": ["not-a-dict-index", {"name": ""}],
            }
        ],
    }
    entities, _ = catalog_to_entities(catalog)
    assert [e for e in entities if e["node_type"] == "DatabaseColumn"] == []
    assert [e for e in entities if e["node_type"] == "DatabaseIndex"] == []


def test_catalog_to_entities_caps_relationships_independently_of_entity_count():
    # Each foreign key produces a relationship WITHOUT a new entity (the
    # referenced table isn't itself a catalog object), so a table with many
    # foreign keys can attempt far more relationships than max_relationships
    # (max_objects * 4) while entities stays well under max_objects -- the
    # only way to exercise add_relationship's own cap independently of
    # entities_full().
    foreign_keys = [
        {"columns": [], "referred_table": f"ref_{i}"} for i in range(20)
    ]
    catalog = {
        "connection": "default",
        "schema": "public",
        "objects": [
            {
                "name": "hub",
                "type": "table",
                "columns": [],
                "foreign_keys": foreign_keys,
            }
        ],
    }
    entities, relationships = catalog_to_entities(catalog, max_objects=2)
    # schema + hub table = 2 entities; max_relationships = 2 * 4 = 8.
    assert len(entities) == 2
    assert len(relationships) == 8
