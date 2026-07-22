"""Factory helpers: open memory or SQLite store + wired services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from synapse.action_bus import ActionBus
from synapse.adjudication import AdjudicationService
from synapse.claim_cache import ClaimCache
from synapse.connectors.registry import ConnectorRegistry, build_default_registry
from synapse.connectors.runner import ConnectorRunner
from synapse.control_plane import ControlPlane
from synapse.drift import DriftDetector
from synapse.dual_path import DualPathExtractor
from synapse.engines import EngineRegistry, build_engine_registry
from synapse.entity_resolution import EntityResolutionService
from synapse.extraction import RuleExtractor
from synapse.graph_memory import GraphMemoryAdapter, create_graph_adapter
from synapse.ingestion import IngestionService
from synapse.materialize import Materializer
from synapse.matching import CandidateCache
from synapse.metrics import METRICS
from synapse.ontology import OntologyRegistry
from synapse.operators import OperatorPipeline
from synapse.orchestrator import QueryOrchestrator
from synapse.query import QueryService
from synapse.reprocess import ReprocessService
from synapse.resolution import ConflictResolver
from synapse.scenarios.checkout_incident import DEFAULT_AUTHORITY
from synapse.store import SemanticStore
from synapse.temporal import TemporalService


@dataclass
class SynapseSession:
    store: SemanticStore
    control_plane: ControlPlane
    ingestion: IngestionService
    extractor: RuleExtractor
    dual_path: DualPathExtractor
    resolver: ConflictResolver
    query: QueryService
    adjudication: AdjudicationService
    er: EntityResolutionService
    temporal: TemporalService
    graph: GraphMemoryAdapter
    connectors: ConnectorRegistry
    connector_runner: ConnectorRunner
    engines: EngineRegistry
    ontology: OntologyRegistry
    orchestrator: QueryOrchestrator
    reprocess: ReprocessService
    materializer: Materializer
    actions: ActionBus
    drift: DriftDetector
    claim_cache: ClaimCache
    candidate_cache: CandidateCache
    db_path: Optional[str] = None

    def close(self) -> None:
        close = getattr(self.store, "close", None)
        if callable(close):
            close()

    def sync_graph(self):
        with METRICS.timer("graph.sync"):
            snap = self.graph.sync_from_store(self.store)
        METRICS.inc("graph.sync.total")
        return snap


def open_session(
    db_path: Optional[str] = None,
    *,
    authority: Optional[dict[str, float]] = None,
    domain: str = "infra_ops",
    graph_backend: Optional[str] = None,
    graphiti_client: Any = None,
) -> SynapseSession:
    # Local secrets from .env (gitignored) — never logged
    try:
        from synapse.env_load import load_dotenv

        load_dotenv()
    except Exception:
        pass

    if db_path:
        from synapse.sqlite_store import SqliteSemanticStore

        store: SemanticStore = SqliteSemanticStore(db_path)
    else:
        store = SemanticStore()

    # Combined authority map for multi-scenario sessions
    auth = dict(DEFAULT_AUTHORITY)
    auth.update(
        {
            "CRM-Salesforce": 0.75,
            "Billing-Zuora": 0.92,
            "Support-Zendesk": 0.60,
            "HR-Workday": 0.88,
            "IdP-Okta": 0.95,
            "ITSM-ServiceNow": 0.70,
            "FileDrop": 0.65,
            "GitHub-CI": 0.90,
            "K8s-Cluster-Alpha": 0.95,
            "Webhook": 0.55,
            "Slack-Incident-Feed": 0.70,
            "HIS-Patients": 0.85,
            "HIS-Doctors": 0.80,
            "HIS-Scheduling": 0.75,
            "HIS-Billing": 0.85,
            "HIS-Treatments": 0.80,
            "FrontDesk-Intake": 0.55,
            "Bank-CoreBanking": 0.85,
            "Bank-Ledger": 0.9,
        }
    )
    if authority:
        auth.update(authority)

    cp = ControlPlane(auth)
    ontology = OntologyRegistry.default()
    # F-027: rehydrate curated relationship edges + rejection log from a
    # durable store, and write-through future ACCEPT/REJECT/RELABEL
    # decisions to it -- without this, the Catalog silently resets to
    # empty every restart even under a SQLite-backed store, since
    # OntologyRegistry itself is reconstructed fresh every open_session().
    ontology.load_from_store(store)
    prep_pipeline = OperatorPipeline()
    ingestion = IngestionService(store, domain=domain, pipeline=prep_pipeline)
    extractor = RuleExtractor(store, ontology=ontology)
    dual_path = DualPathExtractor(store, enable_residual=True)
    # Dual-path Path A should share the same ontology-aware extractor
    dual_path.path_a = extractor
    resolver = ConflictResolver(store, cp, ontology=ontology)
    query = QueryService(store, cp, resolver)
    adjudication = AdjudicationService(store)
    er = EntityResolutionService(store, ontology=ontology)
    temporal = TemporalService(store)
    graph = create_graph_adapter(graph_backend, client=graphiti_client)
    connectors = build_default_registry()
    connector_runner = ConnectorRunner(
        store,
        connectors,
        ingestion=ingestion,
        extractor=extractor,
        dual_path=dual_path,
        domain=domain,
        use_dual_path=True,
    )
    engines = build_engine_registry(store, pipeline=prep_pipeline)
    claim_cache = ClaimCache()
    orchestrator = QueryOrchestrator(
        store, cp, query, engines, ontology=ontology, claim_cache=claim_cache
    )
    reprocess = ReprocessService(store, offline_residual=True)
    materializer = Materializer(store)
    actions = ActionBus(store)
    drift = DriftDetector(store)
    candidate_cache = CandidateCache()
    METRICS.inc("session.open")
    return SynapseSession(
        store=store,
        control_plane=cp,
        ingestion=ingestion,
        extractor=extractor,
        dual_path=dual_path,
        resolver=resolver,
        query=query,
        adjudication=adjudication,
        er=er,
        temporal=temporal,
        graph=graph,
        connectors=connectors,
        connector_runner=connector_runner,
        engines=engines,
        ontology=ontology,
        orchestrator=orchestrator,
        reprocess=reprocess,
        materializer=materializer,
        actions=actions,
        drift=drift,
        claim_cache=claim_cache,
        candidate_cache=candidate_cache,
        db_path=db_path,
    )
