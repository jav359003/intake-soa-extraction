"""Output schema for an extracted Schedule of Activities.

Shaped as a graph rather than a nested table, for one concrete reason: a
footnote marker can sit on a cell, a row, a column, or a header, and in nested
JSON each of those needs a different home. As edges they are one relation with
four possible targets, which is exactly what the brief asks to be preserved --
"the specific cell, row, column, or header that each footnote marker sits on".

The node vocabulary deliberately tracks CDISC USDM (ScheduleTimeline, Encounter,
Activity) and FHIR PlanDefinition/ActivityDefinition, which are the standard
target formats for this artifact. Both are entity-relation models, so a graph is
the shape the destination already expects.

Nothing here normalises. Cell values are carried verbatim, ambiguity is recorded
rather than resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal, Any
import json

NodeType = Literal["period", "visit", "category", "assessment", "cell", "footnote", "table"]
EdgeType = Literal[
    "visit_in_period",       # visit      -> period
    "assessment_in_category",# assessment -> category
    "cell_of_assessment",    # cell       -> assessment
    "cell_at_visit",         # cell       -> visit
    "footnote_annotates",    # footnote   -> cell | assessment | visit | period | table
]


@dataclass
class Provenance:
    """Where this came from in the source document. Non-optional in a
    regulated setting: every extracted value must be traceable to a page."""
    page: int
    bbox: tuple[float, float, float, float] | None = None
    source: str = "vlm"      # vlm | text-layer | stitched | human


@dataclass
class Node:
    id: str
    type: NodeType
    label: str                          # verbatim text as printed
    attrs: dict[str, Any] = field(default_factory=dict)
    provenance: list[Provenance] = field(default_factory=list)
    ambiguous: bool = False
    note: str = ""                      # why it is ambiguous, if it is


@dataclass
class Edge:
    src: str
    dst: str
    type: EdgeType
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class SoAGraph:
    protocol: str
    table_id: str
    pages: list[int]
    title: str = ""
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # -- construction helpers -------------------------------------------------

    def add(self, node: Node) -> str:
        self.nodes.append(node)
        return node.id

    def link(self, src: str, dst: str, type: EdgeType, **attrs) -> None:
        self.edges.append(Edge(src=src, dst=dst, type=type, attrs=attrs))

    # -- views ----------------------------------------------------------------

    def by_type(self, t: NodeType) -> list[Node]:
        return [n for n in self.nodes if n.type == t]

    def grid(self) -> dict:
        """Flatten to rows x columns for display and for eyeball diffing
        against the source page. Lossy on purpose -- the graph stays canonical."""
        visits = self.by_type("visit")
        assessments = self.by_type("assessment")
        cell_of = {e.src: e.dst for e in self.edges if e.type == "cell_of_assessment"}
        cell_at = {e.src: e.dst for e in self.edges if e.type == "cell_at_visit"}
        fn_on: dict[str, list[str]] = {}
        for e in self.edges:
            if e.type == "footnote_annotates":
                fn_on.setdefault(e.dst, []).append(e.src)
        table: dict[tuple[str, str], dict] = {}
        for c in self.by_type("cell"):
            key = (cell_of.get(c.id, ""), cell_at.get(c.id, ""))
            table[key] = {"raw": c.label, "markers": [
                next((n.attrs.get("marker", "") for n in self.nodes if n.id == f), "")
                for f in fn_on.get(c.id, [])
            ], "ambiguous": c.ambiguous}
        return {
            "visits": [{"id": v.id, "label": v.label, **v.attrs} for v in visits],
            "assessments": [{"id": a.id, "label": a.label, **a.attrs} for a in assessments],
            "cells": [{"assessment": k[0], "visit": k[1], **v} for k, v in table.items()],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent, ensure_ascii=False)

    def stats(self) -> dict:
        return {
            "periods": len(self.by_type("period")),
            "visits": len(self.by_type("visit")),
            "categories": len(self.by_type("category")),
            "assessments": len(self.by_type("assessment")),
            "cells": len(self.by_type("cell")),
            "footnotes": len(self.by_type("footnote")),
            "footnote_links": sum(1 for e in self.edges if e.type == "footnote_annotates"),
            "ambiguous": sum(1 for n in self.nodes if n.ambiguous),
            "warnings": len(self.warnings),
        }
