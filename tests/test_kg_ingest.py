"""Native epistemic-graph typed-node ingestion — Wire-First coverage.

Exercises the real ``ingest_entities`` and pure ``catalog_to_entities`` seam with
a fake ChangeEnvelope-capable engine client (no engine or database required),
asserting the applied node/edge writes and reflected schema mapping. The fake
client and governed-session fixture mirror agent-utilities' own
``tests/knowledge_graph/test_native_ingest.py`` reference fake — the shape
``_change_envelope_authority`` actually requires (``changes``/``nodes``/``rdf``/
``supports``; the retired raw ``txn``-only fake is rejected).
CONCEPT:AU-KG.ingest.enterprise-source-extractor.
"""

from __future__ import annotations

from typing import Any

import msgpack
import pytest
from agent_utilities.knowledge_graph.core.session import GraphSession, use_session
from agent_utilities.knowledge_graph.memory.native_ingest import NativeIngestError
from agent_utilities.models.company_brain import ActorType
from agent_utilities.security.brain_context import ActorContext, use_actor

from sql_mcp.kg_ingest import catalog_to_entities, ingest_entities


@pytest.fixture(autouse=True)
def _governed_session():
    """Ambient actor + GraphSession required by native_ingest's injected-client path."""
    actor = ActorContext(
        actor_id="subject:opaque:synthetic",
        actor_type=ActorType.AUTOMATED_SERVICE,
        roles=(),
        tenant_id="tenant:opaque:synthetic",
        authenticated=True,
    )
    session = GraphSession(
        actor=actor,
        tenant=actor.tenant_id,
        scopes=frozenset({"kg:write"}),
        graph="__commons__",
        policy_version="policy:opaque:synthetic",
        audience="epistemic-graph",
    )
    with use_actor(actor), use_session(session):
        yield


class _FakeNodes:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}

    def properties(self, node_id: str) -> dict[str, Any] | None:
        return self.values.get(node_id)

    def list(self) -> list[tuple[str, dict[str, Any]]]:
        return list(self.values.items())


class _FakeChanges:
    def __init__(self, nodes: _FakeNodes) -> None:
        self.nodes = nodes
        self.edges: list[tuple[str, str, dict[str, Any]]] = []
        self.applied: list[dict[str, Any]] = []
        self.records: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, dict[str, Any]] = {}

    def get(self, envelope_id: str) -> dict[str, Any] | None:
        return self.records.get(envelope_id)

    def content_version(self, object_id: str) -> dict[str, Any] | None:
        return self.versions.get(object_id)

    def cursor(self, _source: str, _partition: str = "") -> None:
        return None

    def apply(self, envelope: dict[str, Any]) -> dict[str, Any]:
        self.applied.append(envelope)
        mutation = envelope["mutation"]
        for operation in mutation["operations"]:
            method = operation["method"]
            params = method["params"]
            properties = msgpack.unpackb(params["properties_msgpack"], raw=False)
            if method["method"] == "AddNode":
                self.nodes.values[params["node_id"]] = properties
            elif method["method"] == "AddEdge":
                self.edges.append(
                    (params["source_id"], params["target_id"], properties)
                )
        version = envelope["content_version"]
        self.versions[version["object_id"]] = version
        self.records[envelope["envelope_id"]] = envelope
        return {
            "batch_id": mutation["batch_id"],
            "replayed": False,
            "projection_pending": False,
        }


class _FakeRdf:
    def validate_shacl(self, _shapes: str, _data_graph: str) -> dict[str, Any]:
        return {"conforms": True, "results": []}


class _FakeClient:
    def __init__(self) -> None:
        self.nodes = _FakeNodes()
        self.changes = _FakeChanges(self.nodes)
        self.rdf = _FakeRdf()

    @staticmethod
    def supports(operation: str) -> bool:
        return operation == "ApplyChangeEnvelope"


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
    assert len(c.changes.applied) == 1
    assert set(c.nodes.values) == {"a", "b"}
    # provenance is stamped
    assert c.nodes.values["a"]["source"] == "sql-mcp"
    assert c.nodes.values["a"]["domain"] == "database"
    assert c.changes.edges == [("a", "b", {"relationship": "hasColumn"})]


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
