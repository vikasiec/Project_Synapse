"""
Materialized semantic views for classical BI (H16 escape hatch).

When a view stabilizes (high trust, high use), emit schema-on-write tables
as a *product of the graph* — not the other way around.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from synapse.models import EntityStatus, utc_now_iso
from synapse.security import Principal, filter_conflicts, filter_entities, filter_facts
from synapse.store import SemanticStore


@dataclass
class MaterializedView:
    view_name: str
    rows: list[dict[str, Any]]
    columns: list[str]
    built_at: str
    trust_score: float
    source: str = "semantic_store"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "view_name": self.view_name,
            "row_count": len(self.rows),
            "columns": self.columns,
            "built_at": self.built_at,
            "trust_score": self.trust_score,
            "source": self.source,
            "notes": list(self.notes),
            "rows_preview": self.rows[:20],
        }


class Materializer:
    """Emit stable entity/fact projections for BI tools."""

    def __init__(self, store: SemanticStore) -> None:
        self.store = store

    def entity_fact_table(
        self,
        *,
        predicates: Optional[list[str]] = None,
        min_confidence: float = 0.0,
        principal: Optional[Principal] = None,
    ) -> MaterializedView:
        """
        Wide-ish projection: one row per (entity, predicate) with best active
        fact. `principal`, when given, restricts the view to ACL-visible
        entities/facts (Active_File.md row 36 -- H16 views are derivatives
        and need the same ACL treatment as query claims, not a policy-blind
        dump). `None` preserves prior behavior for existing full-access
        callers (CLI, tests, other internal use) that don't have a
        principal to scope by.
        """
        rows: list[dict[str, Any]] = []
        notes: list[str] = []
        open_conflicts = {
            c.conflict_id
            for c in self.store.conflicts.values()
            if c.status.value == "open"
        }
        if open_conflicts:
            notes.append(
                f"{len(open_conflicts)} open conflicts — rows may be ambiguous; "
                "prefer conflict-aware query path for regulated predicates."
            )

        entities = self.store.entities.values()
        if principal is not None:
            entities = filter_entities(principal, entities)

        for ent in entities:
            if ent.status != EntityStatus.ACTIVE and ent.status.value != "active":
                continue
            facts = [
                f
                for f in self.store.facts_for_entity(ent.entity_id)
                if f.valid_to is None and f.confidence >= min_confidence
            ]
            if principal is not None:
                facts = filter_facts(principal, facts)
            by_pred: dict[str, list] = {}
            for f in facts:
                if predicates and f.predicate not in predicates:
                    continue
                by_pred.setdefault(f.predicate, []).append(f)
            for pred, flist in sorted(by_pred.items()):
                # Prefer highest confidence; flag multi-value
                flist.sort(key=lambda f: f.confidence, reverse=True)
                best = flist[0]
                multi = len({str(f.object) for f in flist}) > 1
                rows.append(
                    {
                        "entity_id": ent.entity_id,
                        "entity_name": ent.canonical_name,
                        "entity_type": ent.entity_type,
                        "predicate": pred,
                        "value": best.object,
                        "source_system": best.source_system,
                        "confidence": best.confidence,
                        "multi_value": multi,
                        "alt_values": (
                            [str(f.object) for f in flist[1:4]] if multi else []
                        ),
                        "valid_from": best.valid_from,
                    }
                )

        trust = 0.9 if not open_conflicts else 0.65
        if any(r["multi_value"] for r in rows):
            trust = min(trust, 0.7)
            notes.append("multi_value rows present — BI consumers should filter.")

        cols = [
            "entity_id",
            "entity_name",
            "entity_type",
            "predicate",
            "value",
            "source_system",
            "confidence",
            "multi_value",
            "alt_values",
            "valid_from",
        ]
        return MaterializedView(
            view_name="entity_facts_active",
            rows=rows,
            columns=cols,
            built_at=utc_now_iso(),
            trust_score=trust,
            notes=notes,
        )

    def conflict_table(self, *, principal: Optional[Principal] = None) -> MaterializedView:
        """`principal`, when given, restricts rows to conflicts the
        principal can see every competing fact of (row 36) -- `None`
        preserves prior unrestricted behavior."""
        rows = []
        conflicts = self.store.conflicts.values()
        if principal is not None:
            conflicts = filter_conflicts(principal, conflicts, self.store.facts)
        for c in conflicts:
            rows.append(
                {
                    "conflict_id": c.conflict_id,
                    "entity_id": c.subject_entity_id,
                    "predicate": c.predicate,
                    "status": c.status.value,
                    "competing_fact_ids": ",".join(c.competing_fact_ids),
                    "resolution_method": (
                        c.resolution.method if c.resolution else None
                    ),
                }
            )
        return MaterializedView(
            view_name="conflicts",
            rows=rows,
            columns=[
                "conflict_id",
                "entity_id",
                "predicate",
                "status",
                "competing_fact_ids",
                "resolution_method",
            ],
            built_at=utc_now_iso(),
            trust_score=1.0,
            notes=["Conflict store is source of truth for discrepancy UX."],
        )

    def write(
        self,
        view: MaterializedView,
        out_dir: str | Path,
        *,
        formats: tuple[str, ...] = ("json", "csv"),
    ) -> dict[str, str]:
        """Write view to disk for warehouse/BI loaders."""
        root = Path(out_dir)
        root.mkdir(parents=True, exist_ok=True)
        paths: dict[str, str] = {}
        if "json" in formats:
            p = root / f"{view.view_name}.json"
            p.write_text(
                json.dumps(
                    {
                        "meta": {
                            k: v
                            for k, v in view.to_dict().items()
                            if k != "rows_preview"
                        },
                        "rows": view.rows,
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            paths["json"] = str(p)
        if "csv" in formats:
            p = root / f"{view.view_name}.csv"
            with p.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=view.columns, extrasaction="ignore")
                w.writeheader()
                for row in view.rows:
                    flat = dict(row)
                    if isinstance(flat.get("alt_values"), list):
                        flat["alt_values"] = "|".join(str(x) for x in flat["alt_values"])
                    w.writerow(flat)
            paths["csv"] = str(p)
        return paths
