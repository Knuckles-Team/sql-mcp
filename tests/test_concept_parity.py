"""Every CONCEPT:SQ-OS.governance.sql-x marker in code must be registered in docs/concepts.md."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MARKER = re.compile(r"CONCEPT:SQ-OS\.governance\.sql-\d+")


def collect_code_markers() -> set[str]:
    markers: set[str] = set()
    for path in (REPO / "sql_mcp").rglob("*.py"):
        markers.update(MARKER.findall(path.read_text(encoding="utf-8")))
    return markers


def test_code_markers_are_registered_in_docs():
    registry = (REPO / "docs" / "concepts.md").read_text(encoding="utf-8")
    documented = set(MARKER.findall(registry))
    in_code = collect_code_markers()
    assert in_code, "Expected CONCEPT:SQ-OS.governance.sql-x markers in sql_mcp/"
    assert in_code <= documented, f"Unregistered concepts: {in_code - documented}"


def test_root_concept_exists_in_code_and_docs():
    registry = (REPO / "docs" / "concepts.md").read_text(encoding="utf-8")
    assert "CONCEPT:SQ-OS.governance.sql-2" in registry
    assert "CONCEPT:SQ-OS.governance.sql-2" in collect_code_markers()
