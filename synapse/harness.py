"""
Core End-to-End Query & Ingestion Simulation Harness.

Runs the checkout-service incident locally (no cloud).
Optional SQLite durability and human-pin demonstration.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Optional

from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.store import SemanticStore


def run_checkout_incident_simulation(
    *,
    verbose: bool = True,
    db_path: Optional[str] = None,
    demonstrate_pin: bool = True,
) -> dict[str, Any]:
    store: SemanticStore
    sqlite_store = None
    if db_path:
        from synapse.sqlite_store import SqliteSemanticStore

        sqlite_store = SqliteSemanticStore(db_path)
        store = sqlite_store
    else:
        store = SemanticStore()

    scenario = CheckoutIncidentScenario(store=store)
    already = bool(store.raw_objects)
    bundle = scenario.seed(skip_if_populated=already)

    if verbose:
        print("=" * 80)
        print("PROJECT SYNAPSE — Phase 1 Simulation Harness")
        print("Scenario: GitHub-CI vs K8s-Cluster-Alpha vs Slack-Incident-Feed")
        if db_path:
            print(f"Store: SQLite @ {db_path}")
        else:
            print("Store: in-memory")
        print("=" * 80)

        print("\n[1] Ingestion — raw landing zone")
        for raw in store.raw_objects.values():
            print(
                f"  • {raw.source_system:22} id={raw.object_id[:8]}… "
                f"hash={raw.content_hash[:12]} acl={raw.acl_tags}"
            )

        print("\n[2] Episodes + rule extraction")
        print(
            f"  episodes={len(store.episodes)} entities={len(store.entities)} "
            f"facts={len(store.facts)}"
        )
        for ent in store.entities.values():
            print(f"  • entity {ent.canonical_name} ({ent.entity_type}) id={ent.entity_id[:8]}…")
        for fact in store.facts.values():
            print(
                f"  • fact {fact.predicate}={fact.object!r} "
                f"src={fact.source_system} conf={fact.confidence:.2f}"
            )

    user_l1 = CheckoutIncidentScenario.principal_l1()
    user_l2 = CheckoutIncidentScenario.principal_l2()

    denied = bundle.query.ask(user_l1, entity_name=bundle.entity_name)
    allowed = bundle.query.ask(user_l2, entity_name=bundle.entity_name)

    if verbose:
        print("\n[3] ABAC gate")
        print(
            f"  • {user_l1.principal_id} attrs={sorted(user_l1.attributes)} "
            f"→ allowed={denied.allowed} reason={denied.denial_reason}"
        )
        print(
            f"  • {user_l2.principal_id} attrs={sorted(user_l2.attributes)} "
            f"→ allowed={allowed.allowed}"
        )

        if allowed.route:
            print("\n[4] Control-plane routing")
            print(
                f"  • IDF={allowed.route.idf:.4f} route={allowed.route.route.value} "
                f"latency={allowed.route.latency_class.value}"
            )
            print(f"  • {allowed.route.reason}")

        print("\n[5] Conflict resolution (validity weights) — pre-pin")
        for view in allowed.conflict_views:
            print(
                f"  • predicate={view.conflict.predicate} "
                f"policy={view.surface_policy} status={view.conflict.status.value}"
            )
            for r in view.ranked:
                print(
                    f"      - {r.fact.object!r:10} src={r.fact.source_system:20} "
                    f"Wv={r.validity_weight:.4f}"
                )

        print("\n[6] Claim packet (pre-pin)")
        print(json.dumps(allowed.claim.to_dict() if allowed.claim else {}, indent=2))

    pin_info: Optional[dict[str, Any]] = None
    after_pin = None

    if demonstrate_pin and allowed.allowed and allowed.conflict_views:
        version_view = next(
            (v for v in allowed.conflict_views if v.conflict.predicate == "current_version"),
            None,
        )
        if version_view and version_view.surface_policy == "SURFACED_AMBIGUOUS_CONFLICT":
            k8s_ranked = next(
                (r for r in version_view.ranked if r.fact.source_system == "K8s-Cluster-Alpha"),
                version_view.preferred,
            )
            if k8s_ranked:
                result = bundle.adjudication.human_pin(
                    version_view.conflict.conflict_id,
                    chosen_fact_id=k8s_ranked.fact.fact_id,
                    adjudicator="oncall@example.com",
                    reason=(
                        "Production traffic is on fallback v2.4.0; "
                        "CI success is deploy intent not runtime state."
                    ),
                )
                pin_info = {
                    "conflict_id": result.conflict.conflict_id,
                    "previous_status": result.previous_status,
                    "status": result.conflict.status.value,
                    "chosen_fact_id": k8s_ranked.fact.fact_id,
                    "chosen_object": k8s_ranked.fact.object,
                }
                after_pin = bundle.query.ask(user_l2, entity_name=bundle.entity_name)

    if verbose and pin_info:
        print("\n[7] Human pin adjudication")
        print(json.dumps(pin_info, indent=2))
        print("\n[8] Claim packet (post-pin)")
        print(
            json.dumps(
                after_pin.claim.to_dict() if after_pin and after_pin.claim else {},
                indent=2,
            )
        )

    if verbose:
        print("=" * 80)

    report: dict[str, Any] = {
        "version": "0.2.0",
        "scenario": "checkout_incident",
        "store": {"backend": "sqlite" if db_path else "memory", "path": db_path},
        "counts": {
            "raw_objects": len(store.raw_objects),
            "episodes": len(store.episodes),
            "entities": len(store.entities),
            "facts": len(store.facts),
            "conflicts": len(store.conflicts),
            "claims": len(store.claims),
        },
        "abac": {
            "l1_allowed": denied.allowed,
            "l1_reason": denied.denial_reason,
            "l2_allowed": allowed.allowed,
        },
        "query_l2_pre_pin": allowed.to_dict(),
        "human_pin": pin_info,
        "query_l2_post_pin": after_pin.to_dict() if after_pin else None,
    }

    if sqlite_store is not None:
        sqlite_store.close()

    return report


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Project Synapse Phase 1 harness")
    parser.add_argument(
        "--db",
        dest="db_path",
        default=None,
        help="SQLite path for durable store (default: in-memory)",
    )
    parser.add_argument(
        "--no-pin",
        action="store_true",
        help="Skip human-pin demonstration",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output",
    )
    args = parser.parse_args(argv)
    run_checkout_incident_simulation(
        verbose=not args.quiet,
        db_path=args.db_path,
        demonstrate_pin=not args.no_pin,
    )


if __name__ == "__main__":
    main()
