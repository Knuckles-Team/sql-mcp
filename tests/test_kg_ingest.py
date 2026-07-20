"""Native epistemic-graph typed-node ingestion — Wire-First coverage.

Exercises the real ``ingest_entities`` and pure ``catalog_to_entities`` seam with
a fake engine client (no engine or database required), asserting the transaction
add_node/commit + edge calls and reflected schema mapping.  CONCEPT:AU-KG.ingest.
enterprise-source-extractor.
"""

from __future__ import annotations

import pytest
from agent_utilities.knowledge_graph.memory.native_ingest import NativeIngestError

from sql_mcp.kg_ingest import catalog_to_entities, ingest_entities


class _FakeTxn:
    def __init__(self):
        self.nodes = {}
        self.edges = []
        self.committed = False

    def begin(self, graph=None):
        self.graph = graph
        return "txn-1"

    def add_node(self, txn, node_id, props):
        self.nodes[node_id] = props

    def add_edge(self, txn, source, target, props):
        self.edges.append((source, target, props))

    def commit(self, txn):
        self.committed = True
        return True


class _FakeClient:
    def __init__(self):
        self.txn = _FakeTxn()


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


def test_ingest_entities_writes_nodes_and_edges():
    c = _FakeClient()
    res = ingest_entities(
        [
            {"id": "a", "node_type": "DatabaseTable", "name": "t"},
            {"id": "b", "node_type": "DatabaseColumn"},
        ],
        [{"source": "a", "target": "b", "relationship": "hasColumn"}],
        client=c,
        graph="__commons__",
    )
    assert res == {"nodes": 2, "edges": 1}
    assert c.txn.committed is True
    assert set(c.txn.nodes) == {"a", "b"}
    # provenance is stamped
    assert c.txn.nodes["a"]["source"] == "sql-mcp"
    assert c.txn.nodes["a"]["domain"] == "database"
    assert c.txn.edges == [("a", "b", {"relationship": "hasColumn"})]


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


def test_retired_structural_alias_is_rejected():
    with pytest.raises(NativeIngestError, match="canonical node_type"):
        ingest_entities([{"id": "a", "type": "DatabaseTable"}], client=_FakeClient())


def test_empty_native_ingest_is_rejected():
    with pytest.raises(NativeIngestError, match="at least one entity"):
        ingest_entities([], client=_FakeClient())
