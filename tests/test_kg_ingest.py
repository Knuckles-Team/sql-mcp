"""Native epistemic-graph typed-node ingestion — Wire-First coverage.

Exercises the real ``ingest_entities`` / ``schema_to_entities`` / ``ingest_schema``
seam with a fake engine client and a fake SQL API (no engine, no database
required), asserting the txn add_node/commit + edge calls and the reflected
schema -> :DatabaseSchema/:DatabaseTable/:DatabaseColumn/:DatabaseView/
:DatabaseIndex mapping. CONCEPT:AU-KG.ingest.enterprise-source-extractor.
"""

from __future__ import annotations

from sql_mcp.kg_ingest import ingest_entities, ingest_schema, schema_to_entities


class _FakeTxn:
    def __init__(self):
        self.nodes = {}
        self.committed = False

    def begin(self, graph=None):
        self.graph = graph
        return "txn-1"

    def add_node(self, txn, node_id, props):
        self.nodes[node_id] = props

    def commit(self, txn):
        self.committed = True
        return True


class _FakeEdges:
    def __init__(self):
        self.edges = []

    def add(self, src, dst, props):
        self.edges.append((src, dst, props))


class _FakeClient:
    def __init__(self):
        self.txn = _FakeTxn()
        self.edges = _FakeEdges()


class _FakeSpec:
    name = "postgres"


class _FakeApi:
    """Minimal SqlApi stand-in returning canned reflection data."""

    def resolve_connection(self, connection=None):
        return connection or "default"

    def dialect_spec(self, connection=None):
        return _FakeSpec()

    def list_tables(self, schema=None, connection=None):
        return ["users"]

    def list_views(self, schema=None, connection=None):
        return ["active_users"]

    def list_columns(self, table, schema=None, connection=None):
        return [
            {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
            {"name": "org_id", "type": "INTEGER", "nullable": True},
        ]

    def list_foreign_keys(self, table, schema=None, connection=None):
        return [{"columns": ["org_id"], "referred_table": "orgs"}]

    def list_indexes(self, table, schema=None, connection=None):
        return [{"name": "ix_users_org", "columns": ["org_id"], "unique": False}]


def test_ingest_entities_writes_nodes_and_edges():
    c = _FakeClient()
    res = ingest_entities(
        [
            {"id": "a", "type": "DatabaseTable", "name": "t"},
            {"id": "b", "type": "DatabaseColumn"},
        ],
        [{"source": "a", "target": "b", "type": "hasColumn"}],
        client=c,
        graph="__commons__",
    )
    assert res == {"nodes": 2, "edges": 1}
    assert c.txn.committed is True
    assert set(c.txn.nodes) == {"a", "b"}
    # provenance is stamped
    assert c.txn.nodes["a"]["source"] == "sql-mcp"
    assert c.txn.nodes["a"]["domain"] == "database"
    assert c.edges.edges == [("a", "b", {"type": "hasColumn"})]


def test_schema_to_entities_maps_tables_columns_views_indexes():
    entities, rels = schema_to_entities(
        _FakeApi(), connection="default", schema="public"
    )
    by_id = {e["id"]: e for e in entities}

    schema_id = "database:schema:default.public"
    table_id = "database:table:default.public.users"
    col_id = "database:column:default.public.users.org_id"
    view_id = "database:view:default.public.active_users"
    idx_id = "database:index:default.public.users.ix_users_org"

    assert by_id[schema_id]["type"] == "DatabaseSchema"
    assert by_id[schema_id]["sqlDialect"] == "postgres"
    assert by_id[table_id]["type"] == "DatabaseTable"
    assert by_id[col_id]["type"] == "DatabaseColumn"
    assert by_id[col_id]["dataType"] == "INTEGER"
    assert by_id[col_id]["isForeignKey"] is True
    assert by_id["database:column:default.public.users.id"]["isPrimaryKey"] is True
    assert by_id[view_id]["type"] == "DatabaseView"
    assert by_id[idx_id]["type"] == "DatabaseIndex"
    assert by_id[idx_id]["isUnique"] is False

    assert {"source": schema_id, "target": table_id, "type": "hasTable"} in rels
    assert {"source": table_id, "target": col_id, "type": "hasColumn"} in rels
    assert {"source": schema_id, "target": view_id, "type": "hasView"} in rels
    assert {"source": table_id, "target": idx_id, "type": "hasIndex"} in rels
    assert {
        "source": table_id,
        "target": "database:table:default.public.orgs",
        "type": "referencesTable",
    } in rels


def test_ingest_schema_pushes_reflected_nodes():
    c = _FakeClient()
    res = ingest_schema(_FakeApi(), connection="default", schema="public", client=c)
    assert res is not None
    assert res["nodes"] >= 5  # schema + table + 2 cols + view + index
    assert c.txn.committed is True
    assert "database:table:default.public.users" in c.txn.nodes
    assert c.txn.nodes["database:table:default.public.users"]["source"] == "sql-mcp"


def test_schema_to_entities_can_skip_views_and_indexes():
    entities, _ = schema_to_entities(
        _FakeApi(),
        connection="default",
        schema="public",
        include_views=False,
        include_indexes=False,
    )
    types = {e["type"] for e in entities}
    assert "DatabaseView" not in types
    assert "DatabaseIndex" not in types
    assert "DatabaseTable" in types


def test_ingest_noops_without_engine():
    # No injected client + no reachable engine -> clean no-op.
    assert ingest_entities([{"id": "a", "type": "DatabaseTable"}]) is None


def test_ingest_empty_is_noop():
    assert ingest_entities([], client=_FakeClient()) is None
