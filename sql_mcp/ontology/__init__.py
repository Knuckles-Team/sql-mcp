"""Database ontology contribution (CONCEPT:KG-2.325).

Data-only subpackage: it carries ``database.ttl`` (the ``owl:Ontology``
``http://knuckles.team/kg/database`` module — databases, schemas, tables,
columns and their relationships) which the agent-utilities hub federates in via
the ``agent_utilities.ontology_providers`` entry-point. It holds no business
logic and no heavy imports so the hub can resolve it cheaply.
"""
