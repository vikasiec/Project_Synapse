# SYNAPSE: AI-Driven Semantic Discovery & Interoperability Engine
**Document Type:** Master Architectural Specification & Implementation Roadmap  
**Target Agent:** Claude (AI Engineering Agent)  
**Execution Guardrail:** Zero deviation permitted from JSON contracts, scoring formulas, execution gates, or Verification & Validation (VnV) criteria.

---

## 0. Architectural Abstract & System Vision

Project Synapse establishes an automated, human-in-the-loop semantic integration core. Instead of building brittle, static ETL pipelines, this engine dynamically discovers entity and attribute relationships across disparate data sources, allows human domain experts to curate and confirm those connections, and persists them into a living Ontology Registry.

The architecture evolves across two distinct operational phases:
1. **Phase 1: Discovery, Learning & Semantic Layer Persistence** (Building the data map and self-adapting ontology).
2. **Phase 2: Active Interoperability & Automated Harmonization** (Transforming discovered relationships into dynamic cross-system data exchange and translation).

---

# PHASE 1: Semantic Discovery & Self-Adapting Core

---

## Major Goal 1: Data Profiling & Vector Extraction (The "Meaning" Layer)
**Objective:** Replace literal string matching with deep semantic and structural profiling for all ingested schema attributes.

### Tasks
1. **Semantic Vectorization:** Implement an embedding step for incoming schema field names and descriptions using a lightweight cross-encoder model.
2. **Value Distribution Fingerprinting:** Compute lightweight structural profiles for each column *without* storing raw sensitive values:
   * Dominant `data_type` (e.g., String, Int, UUID, Timestamp).
   * `entropy_score` (uniqueness ratio).
   * `regex_pattern_match` (% matching standard formats like Email, Phone, or 8-digit Integer).
   * `min_hash_sketch` (Jaccard similarity approximation over distinct value sets).

### VnV Layer 1 (Verification & Validation)
* **Test Input:** Inject Table A with `cust_id` (values: 8-digit integers) and Table B with `client_num` (values: 8-digit integers).
* **Validation Criteria:** The engine must generate JSON profiles for both fields where `regex_pattern_match` and `data_type` match, and both fields successfully return valid float arrays for their semantic vectors.

---

## Major Goal 2: Hybrid Candidate Matching & Scoring (The Inference Engine)
**Objective:** Calculate deterministic confidence scores between cross-system fields to generate candidate relationship edges.

### Tasks
1. **Matching Algorithm:** Implement `POST /v1/explore/analyze` to evaluate field pairs across systems.
2. **Scoring Formula:** Calculate the total similarity score S_total using the exact weighting formula:

$$S_{\text{total}} = (0.45 \cdot \text{VectorSim}(A, B)) + (0.40 \cdot \text{ValueOverlap}(A, B)) + (0.15 \cdot \text{GraphProximity}(A, B))$$

3. **Threshold Enforcement:**
   * **High Confidence:** S_total >= 0.85.
   * **Candidate Recommendation:** 0.50 <= S_total < 0.85.
   * **Strict Drop:** Discard all candidate pairs where S_total < 0.50.
4. **Data Contract Compliance:** Output candidate pairs strictly using the `CandidateEdge` schema (`candidate_id`, `source_a`, `source_b`, `similarity_score`, `match_reasons`, `status`).

### VnV Layer 2 (Verification & Validation)
* **Test Input:** Run `POST /v1/explore/analyze` against profiles of `cust_id` and `client_num`.
* **Validation Criteria:** Returns HTTP 200 with a `CandidateEdge` object containing S_total > 0.80, and `match_reasons` explicitly citing both "Semantic Name Similarity" and "Value Distribution Overlap".

---

## Major Goal 3: Interactive Curation Canvas (Human-in-the-Loop UI)
**Objective:** Provide a visual node-link canvas for domain experts to review, accept, reject, or relabel AI-suggested relationships.

### Tasks
1. **Visual Graph Rendering:** Render data sources as visual clusters with `CandidateEdge` objects as connecting lines.
2. **Explanation Drawer:** Show the full `match_reasons` array upon clicking an edge to explain *why* the AI recommended the connection.
3. **Curation Micro-Actions:**
   * `[ ACCEPT ]`: Approves the relationship.
   * `[ REJECT ]`: Discards the edge and logs a negative feedback signal to prevent future false positives.
   * `[ RELABEL ]`: Allows the user to change the relationship predicate (e.g., `SAME_ENTITY_AS`, `FOREIGN_KEY_TO`, `DERIVED_FROM`).

### VnV Layer 3 (Verification & Validation)
* **Test Input:** A user clicks `[ ACCEPT ]` on the candidate edge connecting `cust_id` and `client_num`.
* **Validation Criteria:** Frontend dispatches `POST /v1/ontology/relationships` with payload `{"action": "ACCEPT", "candidate_id": "<uuid>"}`.

---

## Major Goal 4: Semantic Persistence & Auto-Classification (Self-Adapting Layer)
**Objective:** Ensure human feedback updates the core system, enabling auto-classification for newly added data sources.

### Tasks
1. **Ontology Write-Back:** Implement `POST /v1/ontology/relationships`. On `ACCEPT`, write the edge into the Synapse Ontology Registry (L1 Domain or L2 Team tier).
2. **Entity Resolution (ER) Integration:** Instantly update blocking keys in the ER module (`ER.suggest_merges()`), instructing Graphiti to treat these records as linked entities moving forward.
3. **Transitive Learning Engine:** When a new Source C is ingested, evaluate it against the updated Ontology Registry. If C matches Source B, automatically propose a candidate link to Source A via transitive inference.

### VnV Layer 4 (Verification & Validation)
* **Test Input 1:** Issue `ACCEPT` payload to `POST /v1/ontology/relationships`.
* **Validation Criteria 1:** Querying the Ontology Registry endpoint returns the newly committed edge.
* **Test Input 2:** Ingest a new "Source C" containing `customer_identifier`.
* **Validation Criteria 2:** Engine returns a new `CandidateEdge` linking Source C to Source A, citing the transitive mapping established by the prior acceptance.

---

# PHASE 2: Evolution Toward Active Interoperability

> **CRITICAL EXECUTION GATE & DEPENDENCY:**
> **DO NOT BEGIN ANY CODE CHANGES OR IMPLEMENTATION FOR PHASE 2 UNTIL ALL PHASE 1 GOALS ARE FULLY COMPLETED, TESTED, AND EXPLICITLY VALIDATED BY VIKAS.**

---

## Major Goal 5: Semantic Translation & Dynamic Schema Mapping
**Objective:** Convert confirmed ontology relationships into active, bidirectional runtime translation transformers across systems (Syntactic & Structural Interoperability).

### Tasks
1. **Canonical Data Model (CDM) Bridge:** Construct runtime mapping functions that translate incoming raw source payloads (JSON, XML, CSV) into normalized Canonical Data Model structures using the edges persisted in Phase 1.
2. **Field-Level Transformation Engine:** Implement type conversion and value normalizers (e.g., converting date formats YYYY-MM-DD <-> Unix Epoch, or merging first_name + last_name <-> full_name).
3. **Transformation Lineage Tracker:** Attach a cryptographically hashed lineage key to every transformed payload, explicitly recording which ontology version and rules performed the mapping.

### VnV Layer 5 (Verification & Validation)
* **Test Input:** Send a raw payload from System A (`{"cust_id": "84920112", "dob_str": "1986-05-02"}`) to the translation transformer targeting System B's schema.
* **Validation Criteria:** Transformer outputs System B's exact format (`{"client_num": "84920112", "birth_timestamp": 515376000}`) with zero data loss, accompanied by a valid lineage provenance key.

---

## Major Goal 6: Cross-System Entity Resolution & Conflict Routing
**Objective:** Achieve semantic interoperability by unifying entity identities across disparate operational databases while safely handling conflicting data claims.

### Tasks
1. **Global Entity Graph Federation:** Construct an immutable Global Unique Identifier (GUID) mapping layer across all onboarded systems based on accepted `SAME_ENTITY_AS` ontology links.
2. **Multi-Vector Conflict Resolution Routing:** Integrate the Synapse Conflict Resolution Matrix to handle data discrepancies across systems:
   * **Scalar Clash:** Surface split-view flags (`AMBIGUOUS_CONFLICT`) if numeric values differ across systems within the same time window.
   * **Temporal Supersession:** Automatically update the active state if a newer event carries a higher Validity Weight, while preserving historical states as past graph edges.
3. **Change Data Capture (CDC) Event Bus:** Broadcast entity update events across connected systems whenever an entity state updates in one source.

### VnV Layer 6 (Verification & Validation)
* **Test Input:** Ingest two contradictory records for the same entity: System A claims `status: "ACTIVE"`, System B (with higher authority rank) claims `status: "SUSPENDED"`.
* **Validation Criteria:** The global entity graph merges both records under a single GUID, assigns the current view to `"SUSPENDED"` based on the validity weight, and retains the `"ACTIVE"` record as an open, queryable conflict state without silently overwriting data.

---

## Major Goal 7: Federated Interoperability API & Standardized Exports
**Objective:** Expose the unified semantic data layer through standardized enterprise formats (HL7 FHIR, OpenEHR, GraphQL, OpenAPI) and governed access points (Level 4 Organizational Interoperability).

### Tasks
1. **Dynamic Open Standard Exporters:** Build exporter modules capable of serializing unified Synapse entity graphs into industry-standard formats (e.g., FHIR resources for healthcare, BIAN for banking, or OpenAPI/GraphQL endpoints for general IT).
2. **Attribute-Based Access Control (ABAC) Enforcement:** Ensure all federated API exports strictly apply the cryptographic ABAC intersection rule:

$$\text{Derived Export Clearance} = \text{ACL}_{\text{Object 1}} \cap \text{ACL}_{\text{Object 2}} \cap \dots \cap \text{ACL}_{\text{Object } n}$$

3. **Self-Describing Interoperability Catalog:** Automatically generate and publish live OpenAPI/AsyncAPI specifications detailing all active schemas, relationships, and endpoints currently available in the platform.

### VnV Layer 7 (Verification & Validation)
* **Test Input:** Issue a federated API query requesting patient/customer profile data for a user with restricted `domain:clinical` permissions.
* **Validation Criteria:** The system outputs a fully valid, standardized JSON/FHIR payload containing the unified entity data, while automatically omitting any attributes matching restricted tags (e.g., `domain:financial`) prior to prompt compilation or payload return.