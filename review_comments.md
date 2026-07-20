# Project Synapse — Unified Master Architecture Review

Review date: 2026-07-20  
Reviewer: Codex  
Reference: `docs/Project_Synapse_Unified_Master_Architecture_By_Grok.pdf`  
Scope: implementation, tests, API surface, persistence, integrations, and project documentation.

## Executive conclusion

The repository is a credible, well-tested POC for the semantic data-plane thesis:
raw landing, lineage-bearing facts, temporal history, explicit conflicts, domain
packs, reprocess, materialization, and local fallbacks are all represented. The
current test suite passes (172/172).

It is not yet safe to describe the running HTTP service as an enterprise ABAC,
multi-tenant semantic core. The most important gap is that several read and write
API routes bypass the policy path entirely. The second concrete correctness gap is
global content-hash deduplication, which can erase source and ACL provenance when
two systems submit identical bytes. The remaining findings are production-maturity
gaps explicitly anticipated by the PDF, not reasons to reject the POC.

Severity convention: **P0** blocks any shared or regulated deployment; **P1** can
produce incorrect lineage/security/answer behavior; **P2** is a production
completeness gap or operational risk; **P3** is an evidence/documentation gap.

## Findings

### RC-01 — P0: API read and mutation routes bypass ABAC/authentication

The PDF §6.4 requires policy-scoped retrieval and says security follows every raw
block and derivative. `api.py` applies `_principal_from_body()` to `/v1/query` and
`/v1/ask`, but the following routes return data without a principal or ACL filter:

- `/v1/raw` exposes raw payload previews (`synapse/api.py:181-202`)
- `/v1/episodes` exposes episode previews (`:204-232`)
- `/v1/facts` returns facts without `filter_facts()` (`:234-263`)
- `/v1/conflicts`, `/v1/entities`, and `/v1/history` return semantic state directly (`:327-361`, `:530-549`)
- `/v1/export`, `/v1/audit`, metrics/status and graph/search endpoints are also not policy-scoped.

Mutation and adjudication routes such as `/v1/entities/merge`, conflict pin,
reprocess, materialize, action decision, connector polling, and sense drop also
have no authenticated role/capability gate (`api.py:566-603`, `:726-777`). This
means an unauthenticated caller can read restricted data or alter semantic state
unless the server is protected by an external, undocumented perimeter.

Recommended action: introduce one authenticated request context and require it on
every route; apply entity/fact/raw ACL filtering before serialization; separate
viewer, extractor, adjudicator, operator, and export permissions; add negative
tests for every sensitive route. Keep the current demo principal presets only
behind an explicit development mode.

### RC-02 — P1: content-hash deduplication drops cross-source provenance

`IngestionService.land()` looks up only `content_hash` (`synapse/ingestion.py:90`)
and returns the existing `RawObject` before considering the new source, URI, or
ACL. A direct reproduction with identical payloads from `Source-A` and `Source-B`
produced one raw object; the second result was marked deduplicated and retained
`Source-A` plus `domain:a` ACL.

This violates the PDF's “raw is sacred,” mandatory lineage, discrepancy-first
principles and can suppress a legitimate same-byte event from another owner.
It is especially dangerous when identical structured payloads arrive under
different tenant or sensitivity tags.

Recommended action: make deduplication scope explicit, for example
`(source_system, source_uri, content_hash)` for connector replay, while retaining
cross-source identical payloads as separate raw objects. If byte-level global
deduplication is desired for storage, create source-specific provenance/ACL
references rather than returning the first source's object as the second source's
record. Add a regression test with equal bytes and different source/ACL.

### RC-03 — P1: Graphiti push and search do not carry the ABAC contract

The optional remote graph path pushes `ep.payload_text` with only the domain as
`source_description` (`synapse/graph_memory.py:314-383`). The episode ACL tags,
source ACL intersection, tenant identity, sensitivity, and legal-hold metadata
are not attached to the remote episode. `/v1/graphiti/search` also has no
principal-scoped filtering (`api.py:651-673`).

Under the PDF's “security follows the block” rule, a remote graph is a derivative
and must not become a policy escape hatch. Local store filtering cannot repair a
payload already sent to an unscoped remote index.

Recommended action: model tenant/domain/security metadata in the Graphiti
episode/node/edge payload, enforce a per-tenant graph partition, filter search
results by principal before returning them, and add an end-to-end cross-ACL
negative test with the remote client recording adapter.

### RC-04 — P1: claim cache is ACL-bound but not data-version-bound

`ClaimCache.make_key()` includes the question, principal attributes, intent,
entity, budget, and `as_of`, but not a semantic-store revision, latest-ingest
watermark, conflict version, or relevant fact IDs (`synapse/claim_cache.py:37-57`).
The cache is invalidated on reprocess/materialize, but ordinary ingest does not
invalidate it (`claim_cache.py:99-102`; `api.py:726-746`). A new conflicting fact
can therefore leave a prior answer cached for up to the TTL, including an answer
whose uncertainty and citations predate the new evidence.

Recommended action: maintain a monotonic store/query revision and include it in
the key, or invalidate affected entity/predicate keys on every land/extract,
conflict change, merge, and pin. Add a test: ask, ingest a conflicting fact, ask
again immediately, and require the second answer to surface the conflict.

### RC-05 — P1: reprocess overwrites episode pipeline version in place

`ReprocessService.run()` assigns `ep.prep_pipeline_version = self.pipeline_version`
and writes the same episode back (`synapse/reprocess.py:73-76`). The PDF's H4/H6
design calls for versioned derived views, catalog/pipeline versioning, and
rebuildability from raw. In-place replacement loses the prior extraction-version
identity on the episode, which weakens audit comparison and rollback even though
facts retain extractor versions.

Recommended action: preserve the original episode as immutable history and create
a new derived episode/view keyed by `(raw_object_ids, pipeline_version)`, or add
an append-only episode-version table with an active pointer. Add a regression test
that reprocesses with two versions and verifies both versions remain inspectable.

### RC-06 — P2: canonical JSON contracts are not an enforced runtime boundary

`schema_validate.py` provides a lightweight validator, but the main Path A
landing/extraction flow does not validate `RawObject`, `Episode`, `Entity`, `Fact`,
`Conflict`, or `Claim` before persistence. The Python model also uses
`Episode.payload_text`, while the architecture contract describes a
`payload_ref`; this is a deliberate local simplification only if the divergence
is explicitly versioned and documented.

Recommended action: validate at persistence or at a clearly named POC boundary,
version the Python-to-contract mapping, and add contract fixtures for every
canonical object. Do not silently accept unknown/malformed fields in a future
cross-service implementation.

### RC-07 — P2: raw landing is durable locally, but not a WORM/object-store root

`RawObject` stores the entire payload in the model and assigns
`bytes_ref="mem://raw_landing/<hash>"` (`synapse/models.py:45-74`). SQLite persists
JSON rows, but there is no object-store/WORM adapter, retention enforcement,
legal-hold workflow, cryptographic integrity verification on read, or disaster
recovery drill in the runtime path. `export_import.py:50-96` is a useful snapshot
utility, not a governed backup/restore protocol.

This is consistent with the PDF's prototype boundary but fails H13 if interpreted
as production completeness. Recommended action: define the raw-store interface,
immutable object versioning, retention/erasure policy, encryption/key scope,
backup verification, and rebuild-from-raw acceptance tests.

### RC-08 — P2: materialization and exports can produce policy-blind derivatives

`Materializer.entity_fact_table()` and `conflict_table()` iterate the whole store
without a principal or ACL argument (`synapse/materialize.py:42-157`), and the
API lets the caller choose an output directory (`api.py:735-746`). Export similarly
serializes the complete store. Because H16 views are derivatives, they need the
same ACL intersection and tenant partition as query claims; a note about open
conflicts is not a security boundary.

Recommended action: require an authorized export principal, materialize only
policy-visible rows, carry ACL/tenant metadata into each output, and make output
locations controlled rather than caller-arbitrary for a service deployment.

### RC-09 — P2: GraphRAG/PageIndex/Data-Juicer package detection is stronger than execution

The adapters honestly report package availability, but GraphRAG queries are always
served by `GraphRAGLite` over the local store (`synapse/integrations/graphrag_adapter.py`),
PageIndex uses the local tree, and Data-Juicer runs the local `OperatorPipeline`
even when the package is importable (`data_juicer_adapter.py`). This is acceptable
for the POC and documented as a fallback, but it does not yet validate the PDF's
full engine behavior, async job path, corpus partitioning, or operational back
pressure.

Recommended action: keep the capability response explicit as it is, then add
contract tests for package-backed adapters when dependencies are available and
separate “package detected” from “package executed for this request” in telemetry.

### RC-10 — P3: evaluation proves functional regressions, not architecture quality gates

The 172-test suite is valuable and covers extraction, joins, conflicts, API flows,
and reprocess. It does not yet establish the PDF's H9/H10 metrics: citation
precision, answer correctness against golden claims, conflict-honesty rate,
latency/cost envelopes under representative workloads, tenant isolation, or
rebuild-from-raw equivalence. The architecture document explicitly calls eval a
product and requires promotion gates.

Recommended action: create golden sets per domain and intent, measure citation
recall/precision and conflict surfacing, add budget/latency load cases, and make
ABAC-negative and raw-rebuild tests CI gates before production claims.

## Positive evidence confirmed

- Raw, episode, entity, fact, conflict, and claim models exist and preserve
  evidence references and temporal fields.
- Conflict detection leaves cross-source scalar disagreements open and exposes
  competing fact IDs rather than silently selecting a winner.
- Entity resolution has strict identity and identifier-authority handling for the
  healthcare cases; observation-instance identity was recently added.
- Reprocess has interoperability coverage for HL7v2, FHIR, and banking and the
  current suite passes 172/172.
- Budget classes, IDF routing, claim caching, local GraphRAG/PageIndex fallbacks,
  audit events, action approval, and materialization are present as POC seams.
- Existing documentation honestly calls out non-multi-tenant and other maturity
  boundaries (`docs/THREAT_MODEL.md:19`, `docs/SESSION_HANDOFF.md:69`).

## Recommended order of work

1. Close RC-01 and RC-03 before any shared or regulated deployment.
2. Fix RC-02 and RC-04 because they can silently change provenance or hide new
   discrepancies even in a trusted local deployment.
3. Version reprocess outputs (RC-05) and harden raw durability/exports (RC-07/08).
4. Freeze and enforce canonical contracts (RC-06).
5. Build golden evaluation and operational gates (RC-10), then promote real engine
   adapters and scale controls (RC-09).

## Review disposition

No production code was changed during this review. RC-01, RC-02, RC-03, RC-04,
and RC-05 should become explicit tracker items before the project claims the
architecture's enterprise security, discrepancy, and reprocess guarantees.
