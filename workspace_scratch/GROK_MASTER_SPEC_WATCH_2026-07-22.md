# Grok Master-Spec Alignment Watch — 2026-07-22

**Role:** Independent architecture/implementation monitor (not implementer).  
**Authority document:** `docs/Master Architectural Specification & Implementation Roadmap.md` (+ PDF twin).  
**Ledger:** `Active_File.md` rows **38–47** (Phase 1 Semantic Discovery workstream).  
**Discipline:** Note discrepancies, risks, overclaims, and contract drift. Do not “fix” Claude’s work unless asked; surface issues with evidence.

---

## 0. How to read this file

| Severity | Meaning |
|----------|---------|
| **P0** | Spec contract / VnV broken or silent correctness hazard |
| **P1** | Material deviation from stated contracts, formulas, or platform rules |
| **P2** | Design debt, incomplete wiring, doc/ledger drift |
| **P3** | Nits, style, process hygiene |

Each finding: **ID · severity · status · evidence · recommended attention**.

---

## 1. Snapshot — monitor start

| Field | Value |
|-------|--------|
| Monitor start (local) | 2026-07-22 ~08:45 |
| Claude process | `claude` PID 42568 since 08:22:39 |
| Related process | `python3.11` PID 38544 since 08:44:54 (likely Claude/tooling) |
| Git | `main` ahead of `origin/main` by 7; **dirty** working tree |
| Spec files | Untracked: both `.md` and `.pdf` of Master Spec |
| New code (untracked) | `synapse/profiling.py`, `tests/test_profiling.py` |
| Ledger | Rows 38–47 all `🔴 PENDING`; row 35 still backlog PENDING |
| Tests | `tests.test_profiling` **4/4 OK** (2026-07-22 08:45) |

### Phase 1 ledger mapping (spec → rows)

| Spec goal | Ledger rows | Code observed at start |
|-----------|-------------|------------------------|
| MG1 Profiling & vectors | 38 | `profiling.py` present, uncommitted |
| MG2 Hybrid scoring + `POST /v1/explore/analyze` | 39 | **absent** (`matching.py` not found) |
| MG3 Curation canvas UI | 43, 45 | **absent** (`ui/` not found) |
| MG4 Ontology write-back / ER / transitive | 40–42 | **absent** |
| Catalog UI | 44 | **absent** |
| VnV automation | 46 | only Layer-1 partial tests in `test_profiling.py` |
| Doc closeout | 47 | not started; `SESSION_HANDOFF.md` still 2026-07-20 |

---

## 2. Findings (living list)

### F-001 · P1 · MITIGATED · Cross-encoder → hashing-trick stand-in

**Spec (MG1 Task 1):**  
> “embedding step … using a **lightweight cross-encoder model**.”

**Implementation:** Char-trigram **hashing-trick** BoW (`_hashing_vector`, dim=64), stdlib-only. Module docstring explicitly admits no embedding lib / offline stand-in.

**Update 2026-07-22 ~08:50:** Claude added **domain-blind synonym canonicalization** (`_SYNONYM_CANON`: cust/client→customer, id/num→identifier, …) before hashing. `cust_id` and `client_num` both canonicalize to `customer identifier` → VectorSim ≈ **1.0**. With shared-value MinHash (fixture), S_total ≈ **0.85** — VnV2 green without reweighting the formula. Residual: still not a cross-encoder; quality depends on synonym table coverage (see F-021).

---

### F-002 · P1 · OPEN · SchemaFieldProfile location vs ledger

**Ledger row 38 targets:** `synapse/profiling.py` **and** `synapse/models.py`.  
**Code:** `SchemaFieldProfile` lives only in `profiling.py` as a local `@dataclass`. Not in `models.py`, not in `docs/schemas/`, not shared as a first-class model.

**Impact:** Downstream MG2/UI/API may re-shape the contract; no JSON Schema contract yet (RC-06 backlog already notes contracts not enforced).

---

### F-003 · P0/P1 · OPEN · Profiler only parses `key: value` text payloads

```python
_KV_RE = re.compile(r"^([A-Za-z0-9_ -]{2,40})\s*[:=]\s*(.*)$", re.MULTILINE)
# ...
for m in _KV_RE.finditer(raw.raw_payload):
```

**Reality of landed data:** New Data / hospital / banking / FHIR / HL7 are **CSV, JSON, pipe-delimited** — not line-oriented `field: value` logs. Tests only land synthetic KV strings via `_land_kv`.

**Impact:** `profile_source()` against real `RawObject`s from connectors will often yield **empty or near-empty profiles** unless payloads happen to contain `k: v` lines. That breaks the “meaning discovery front door” vision for the datasets this project actually uses.

**Recommend:** Reuse existing field observation from connectors/drift (`DriftDetector` baselines / structured payload parsers) or parse JSON/CSV-shaped payloads before claiming MG1 complete.

---

### F-004 · P2 · OPEN · Spec profile fields vs implementation shape

| Spec field | Impl | Notes |
|------------|------|-------|
| `data_type` (String, Int, UUID, Timestamp…) | `Integer8`, `Integer`, `Float`, `Date`, `Email`, `Phone`, … | Extra types OK if VnV still matches; `Integer8` is good for VnV1 |
| `entropy_score` (uniqueness ratio) | `len(set)/len` | Matches stated definition |
| `regex_pattern_match` (% matching formats) | **dict** of pattern→fraction | Richer than a single %; consumers must not expect a scalar |
| `min_hash_sketch` | list[int], 16 hashes | Present; Jaccard helper exported |
| semantic vectors | `semantic_vector: list[float]` | Present; **field name only**, not descriptions |

**Spec:** “field names **and descriptions**” — descriptions never used.

---

### F-005 · P2 · OPEN · No API surface for MG1 yet

No `/v1/...` route exposes profiles. Row 38 scope is models + profiler; row 39 owns `POST /v1/explore/analyze`. Acceptable sequencing **if** profiles remain pure library until MG2. Risk: UI Explore (row 45) step “show profiling output as computed” needs a read path — not yet designed in ledger.

---

### F-006 · P2 · OPEN · Naming collision: `GET /v1/explore` vs `POST /v1/explore/analyze`

Row 37 already shipped **Explore** as query-free Sense aggregation. Spec MG2 reuses `/v1/explore/analyze` for a **different** product concept (field-pair candidate scoring). Ledger row 39 correctly flags “do not conflate.”

**Watch:** Frontend/docs that say “Explore” now have **two meanings** (Sense discovery vs semantic canvas). High confusion risk for Vikas demos and for row 43 UI rebuild.

---

### F-007 · P1 · WATCH · Phase 2 gate vs pre-existing codebase

Spec **forbids Phase 2 code** until Phase 1 is fully done and **explicitly validated by Vikas**.

Pre-existing platform already implements substantial MG6/MG7 *shape* work:
- Scalar conflicts + temporal supersession  
- HL7 FHIR “exporters” are partial **importers**  
- ABAC on API reads/exports  
- Cross-source ER  

**Assessment:** Not a violation if Claude does not start **new** Phase 2 work under rows 38–47. Risk is **narrative overclaim** (“we finished the Master Spec Phase 2”) or accidental scope creep (e.g. CDM transformers under the discovery branch).

**Gate text to enforce on every PR/close:**  
> DO NOT BEGIN … PHASE 2 UNTIL ALL PHASE 1 GOALS ARE FULLY COMPLETED, TESTED, AND EXPLICITLY VALIDATED BY VIKAS.

---

### F-008 · P2 · OPEN · VnV Layer 1 test coverage gaps

`test_vnv_layer_1_matching_8_digit_integer_fields` covers:
- same `data_type` / `Integer8`
- same `regex_pattern_match` for Integer8  
- non-empty float vectors  

Missing relative to full MG1 spirit:
- No assertion that **JSON/CSV real payloads** profile correctly (F-003)
- No ACL isolation test on profiler (code *has* principal filtering — good — but untested)
- No min_hash stability / Jaccard sanity on equal value sets
- Vectors not required to be L2-normalized in test (impl does normalize)

---

### F-009 · P3 · OPEN · Continuity docs stale during new stream

| Doc | Issue |
|-----|--------|
| `docs/SESSION_HANDOFF.md` | Still 2026-07-20; open rows 24/25 long closed; suite 167 outdated |
| `management/Road_map.md` / `Features.md` | Row 47 will update; until then discovery stream invisible |
| Master Spec | Untracked in git — easy to lose if someone hard-resets |

---

### F-010 · P2 · OPEN · Platform-vs-domain constraint (row 3 / DOMAIN_PACK_CONTRACT)

Discovery stack must stay **domain-blind**. Early profiling patterns (`Integer8`, Email, Phone) are generic — **good**.  
Watch for healthcare-only regexes or banking field names hard-coded into `matching.py` / ontology write-back.

---

### F-011 · P1 · PARTIAL → library landed · Scoring formula & CandidateEdge

**Update 2026-07-22 ~08:48:** `synapse/matching.py` now exists (untracked, ~5.6KB).

Verified against Execution Guardrail:
| Contract | Code | OK? |
|----------|------|-----|
| Weights 0.45 / 0.40 / 0.15 | `VECTOR_WEIGHT` etc. | YES |
| High ≥0.85, drop <0.50 | `HIGH_CONFIDENCE_THRESHOLD`, `CANDIDATE_THRESHOLD` | YES |
| S_total formula | `score_pair` lines 121–123 | YES |
| CandidateEdge fields | dataclass + `to_dict` | YES (core 6 keys) |
| Strict drop returns None | `if s_total < CANDIDATE_THRESHOLD` | YES |
| status labels | `"high_confidence"` / `"candidate"` | YES (reasonable) |

**Still open for full F-011 close:**
- **No** `POST /v1/explore/analyze` in `api.py` (row 39 half-done)
- **No** `tests/test_explore_analyze.py` / unit tests for `score_pair`
- VnV2 not executable yet

---

### F-012 · P1 · WATCH · Ontology / ER integration semantics (rows 40–41)

Spec: ACCEPT → Ontology Registry **and** ER blocking update for linked records.  
Ledger wisely separates field-level `SAME_ENTITY_AS` from entity `merge()`. Watch for conflating them (patient-safety class if auto-merge).

---

### F-013 · P3 · OPEN · Process / git hygiene

- Working tree dirty: `Active_File.md`, workspace_scratch notes, untracked spec + profiling + `new_data/` + `generate_lab_data.py`
- Branch 7 commits ahead of origin (pre-discovery work not pushed)
- Claude should not self-close rows 38–46 as “Phase 1 complete” without Vikas VnV sign-off (row 46 already states this — good)

---

## 3. VnV checklist (track as code lands)

| Layer | Criteria (abbrev) | Status |
|-------|-------------------|--------|
| L1 | cust_id / client_num profiles: type+regex match; valid float vectors | **PASS** (unit KV) — real CSV/JSON still F-003 |
| L2 | POST analyze → S_total > 0.80 + two reason strings | **GREEN (synthetic)** — synonym-canon vectors + shared IDs → S=0.85 high_confidence; HTTP test OK 08:51 (F-019 closed; residual F-021) |
| L3 | UI ACCEPT → exact POST body shape | **API GREEN** + UI drawer wiring mid-stream (09:07); HTTP VnV3 OK |
| L4 | Registry returns edge; Source C transitive candidate | **GREEN (synthetic)** — registry + transitive TableC; ER instance residual F-028 |
| Phase gate | Vikas explicit Phase 1 validation | NOT STARTED — Claude correctly flags in row 42 note |

---

## 4. Positive observations (not issues)

1. Module docstring is **honest** about the embedding stand-in — matches project “state limitations, don’t hide them” culture.  
2. ACL filtering hooks (`filter_raw_objects`) present from day one — good platform hygiene.  
3. Phone pattern deliberately avoids eating 8-digit IDs — thoughtful for VnV1.  
4. Ledger rows 38–47 are sequenced with dependencies and explicit VnV row — strong planning.  
5. Existing domain packs / H1–H16 stack left intact so far — additive, not rewrite.  
6. Profiling unit tests pass cleanly on first look.

---

## 5. Monitor log (append-only chron)

### 2026-07-22 08:45 — Baseline audit
- Read Master Spec MD (full Phase 1–2).
- Read Active_File rows 38–47.
- Inspected `profiling.py` + `test_profiling.py`; 4/4 pass.
- Confirmed absence of `matching.py`, `ui/`, ontology relationship APIs.
- Opened findings F-001 … F-013.
- Claude PID active; python3.11 concurrent.

### 2026-07-22 08:50 — Next checks scheduled
- Poll mtimes / git status / new files every ~3–5 min.
- Re-run relevant unit tests when new modules appear.
- Diff new code against formulas, schemas, Phase 2 gate.

### 2026-07-22 08:48–08:52 — MG2 module appears (`matching.py`)
- **New untracked:** `synapse/matching.py` (mtime 08:47:44).
- Formula weights **exact:** 0.45 / 0.40 / 0.15; thresholds 0.85 / 0.50; strict drop returns `None`.
- `CandidateEdge` fields present; `source_a`/`source_b` are **dicts** `{source_system, field_name}` (spec says opaque source_a/source_b — reasonable, document).
- **No** `POST /v1/explore/analyze` yet; **no** `tests/test_matching.py` yet.
- New findings **F-014, F-015, F-016, F-017** (below).
- Stress-test of VnV2 synthetic pair (cust_id vs client_num, disjoint values, no entities): **S_total likely fails >0.80 without GraphProximity** because name cosine is weak and MinHash overlap on disjoint value sets ≈ 0. See F-015.

---

## 6. File inventory watch (update in place)

| Path | Expected by | Present? | Last note |
|------|-------------|----------|-----------|
| `synapse/profiling.py` | R38 | YES | 08:44 local |
| `tests/test_profiling.py` | R38 | YES | 4/4 OK |
| `synapse/models.py` SchemaFieldProfile | R38 text | NO | only in profiling.py |
| `synapse/matching.py` | R39 | YES | 08:47 library only |
| `POST /v1/explore/analyze` | R39 | NO | not in api.py yet |
| `POST /v1/ontology/relationships` | R40 | NO | |
| ER blocking on ACCEPT | R41 | NO | |
| Transitive CandidateEdge | R42 | NO | |
| `ui/` Vite app | R43 | NO | |
| Catalog view | R44 | NO | |
| Explore graph canvas | R45 | NO | |
| VnV test files R46 | R46 | NO | only L1 partial |
| SESSION_HANDOFF / mgmt docs | R47 | stale | |

---

### F-014 · P2 · OPEN · match_reasons string shape vs VnV2 exact citations

**VnV Layer 2:** match_reasons must explicitly cite **"Semantic Name Similarity"** and **"Value Distribution Overlap"**.

**Impl (`_match_reasons`):**
```text
Semantic Name Similarity (0.12)
Value Distribution Overlap (0.00)  # only if voverlap > 0
```

- Substring match for the required phrases is OK **if** score > 0.
- If `voverlap == 0` (disjoint MinHash / no common values), **"Value Distribution Overlap" is omitted entirely** → VnV2 fails even when S_total somehow clears 0.80 via graph.
- Extra reasons (`Matching data_type`, `Graph Proximity`) are fine.
- Status values: `high_confidence` | `candidate` (spec used prose labels High Confidence / Candidate Recommendation — map is clear enough).

---

### F-015 · P0 · RESOLVED (for VnV fixture) · VnV Layer 2 mathematical risk on the canonical pair

**Resolved for the automated VnV2 path (2026-07-22 ~08:51)** via **both** mitigation #1 and #2:
1. Fixture plants **identical** shared IDs across TableA/TableB → ValueOverlap ≈ 1.0 (legitimate).
2. Synonym table makes VectorSim(cust_id, client_num) ≈ 1.0 → S ≈ 0.85 with gprox=0.

**Independent re-run:** `python -m unittest tests.test_explore_analyze tests.test_profiling` → **6/6 OK**.

**Residual OPEN risk (demote to watch):** Pairs **without** synonym coverage **and** without value overlap still drop. Formula weights untouched (good — no F-021-style guardrail break on reweight). Disjoint real-world IDs still need name path alone: S = 0.45*1.0 + 0 = 0.45 **&lt; 0.50** strict drop if voverlap=0 even with perfect synonyms — so **value overlap remains load-bearing** for candidate emission.

---

### F-016 · P2 · OPEN · GraphProximity is source-level, not field-level

`graph_proximity` compares **dominant ontology_type of each source_system**, not field pairs. Two fields in sources that both extract `Patient` get gprox=1 even if comparing `email` vs `blood_type`. Weight is only 0.15, so limited blast radius, but it inflates S for all pairs in “same type family” sources — may push weak pairs over 0.50.

---

### F-017 · P2 · RESOLVED · API + tests not landed with matching library

**Resolved ~08:48–08:51:** `POST /v1/explore/analyze` in `api.py`; `tests/test_explore_analyze.py` green. Response shape `{source_a, source_b, candidates: [CandidateEdge.to_dict()…]}`. Principal ACL threaded into profiler.

---

### F-018 · P3 · OPEN · CandidateEdge.to_dict omits created_at

Dataclass has `created_at`; `to_dict()` does not export it. Spec’s listed six keys do not require it — contract-OK; API consumers wanting audit timestamps need a follow-up.

---

*Grok continuous watch. Updates appended below without rewriting closed evidence.*

### 2026-07-22 08:53 — Scheduled fire (audit-only)

- **Git:** dirty; untracked still includes `matching.py`, `profiling.py`, Master Spec md/pdf, `new_data/`, watch file. Branch ahead of origin by 7.
- **Material since baseline:** `synapse/matching.py` (MG2 library) — formula/thresholds/CandidateEdge **aligned** with Master Spec.
- **Still absent:** `POST /v1/explore/analyze`, ontology relationships API, ER accept path, transitive engine, `ui/`, VnV L2–L4 tests. Rows 38–47 all 🔴 PENDING. No Phase 2 work observed.
- **Highest attention:** **F-015 (P0)** VnV2 math risk on canonical `cust_id`/`client_num` with hashing vectors + disjoint values + gprox=0.
- **Next watch:** API wire-up for analyze; any VnV fixture that plants overlapping values or synonym boosts; status flips on rows 38–39.
- Findings living list: F-001–F-013 (baseline) + F-014–F-018 (MG2 library). Duplicates from concurrent fire reconciled.

### 2026-07-22 08:55–08:56 — API + VnV2 test land; **VnV2 FAILS**

**New/changed:**
- `synapse/api.py` — `POST /v1/explore/analyze` wired (principal from body; profile both sources; `analyze_sources`; returns `{source_a, source_b, candidates}`).
- `tests/test_explore_analyze.py` — VnV2 HTTP test + missing-source 400.

**Fixture strategy (Claude mitigation path #1 for F-015):** Shared identical ID values across TableA/TableB (`84920112`, `10293847`, `55512309`) — legitimate realistic case; docstring says so.

**Independent math on that fixture:**
| Component | Value |
|-----------|-------|
| VectorSim(cust_id, client_num) | **≈ 0.202** |
| ValueOverlap (shared IDs) | **1.0** |
| GraphProximity | **0.0** (no entities) |
| S_total | **0.45×0.202 + 0.40×1.0 + 0 = 0.4909** |
| Threshold | drop if **&lt; 0.50** |

**Result:** `score_pair` → `None`; API returns `candidates: []`.

**Test run (08:56):**
```
tests.test_explore_analyze ... FAIL (assertTrue body["candidates"] — empty list)
tests.test_profiling ... 4/4 OK
```

**F-015 upgraded:** not only “may fail on disjoint values” — **fails even with perfect MinHash overlap** because hashing-trick name cosine (~0.20) cannot contribute enough under 0.45 weight to clear **0.50**, let alone **0.80**. With GraphProximity=1.0: S≈0.64 still **&lt; 0.80** VnV2 bar.

**API review notes (positive):**
- Correctly documents distinction from `GET /v1/explore`.
- ACL principal threaded into profiler.
- No Phase 2 leakage.

**New findings:** F-019, F-020. F-017 → PARTIAL (API present; tests red). Inventory updated below.

### F-019 · P0 · RESOLVED · VnV Layer 2 test currently RED

**Resolved ~08:51:** Independent re-run → GREEN (see 08:50–08:51 log). No formula reweight.

### F-020 · P1 · MITIGATED · Structural scoring gap: name vector too weak for formula

**Mitigated via synonym canon (F-001 update).** Residual: without value overlap, even perfect name S=0.45 drops below 0.50.

---

## 6. File inventory watch (update in place) — refreshed 08:51 synonym fix

| Path | Expected by | Present? | Last note |
|------|-------------|----------|-----------|
| `synapse/profiling.py` | R38 | YES | + synonym canon 08:50 |
| `tests/test_profiling.py` | R38 | YES | 4/4 OK |
| `synapse/models.py` SchemaFieldProfile | R38 text | NO | |
| `synapse/matching.py` | R39 | YES | weights **unchanged** |
| `POST /v1/explore/analyze` | R39 | YES | api.py |
| `tests/test_explore_analyze.py` | R39/R46 | YES | **VnV2 GREEN** |
| `POST /v1/ontology/relationships` | R40 | NO | |
| ER blocking on ACCEPT | R41 | NO | |
| Transitive CandidateEdge | R42 | NO | |
| `ui/` Vite app | R43 | NO | |
| Catalog / Explore canvas | R44–45 | NO | |
| Full VnV R46 | R46 | PARTIAL | L1+L2 synthetic green |
| SESSION_HANDOFF / mgmt docs | R47 | stale | |

### 2026-07-22 08:50–08:51 — Synonym canonicalization unblocks VnV2

Claude updated `profiling.py` with `_SYNONYM_CANON` + `_canonicalize_field_name` before hashing (COMA/Cupid-style; domain-blind token map: `cust`/`client`→`customer`, `id`/`num`→`identifier`, …).

**Independent re-measure (shared-ID fixture):**
| Component | Before synonyms | After |
|-----------|-----------------|-------|
| VectorSim | ~0.20 | **~1.00** |
| ValueOverlap | 1.0 | 1.0 |
| S_total | 0.4909 (drop) | **0.85** (`high_confidence`) |
| match_reasons | n/a | includes both required phrases |

HTTP `test_vnv_layer_2_...` → **ok**. Formula weights **not** mutated (good — no F-021 guardrail break).

**Finding status updates:**
- **F-015 / F-019 / F-020:** mitigated for the **spec’s canonical shared-value pair**. Residual: disjoint-value pairs still need high name sim alone (0.45×1.0=0.45 still **&lt;0.50** without value overlap or graph) — honest behavior for non-overlapping IDs.
- **F-017:** largely closed for library+API+test presence; row 38–39 still PENDING until Claude closes ledger.
- **New F-021** synonym false-positive risk (below).

### F-021 · P2 · OPEN · Aggressive synonym map may over-link fields

`_SYNONYM_CANON` maps e.g. `account`/`acct` → `customer`, and `id`/`num`/`number`/`no` → `identifier`. That makes many schema pairs nearly identical in VectorSim (e.g. `account_id` ≈ `customer_number` ≈ `client_no`). ValueOverlap + GraphProximity remain the main discriminators — OK if value distributions differ, **risky** when two unrelated high-cardinality ID columns happen to share format/sketch noise. Recommend: keep map; add negative VnV case (unrelated ID columns with different value universes must drop or score &lt;0.50).

### F-022 · P3 · NOTE · Still not a cross-encoder

Synonym+hashing is a stronger stand-in than raw trigrams, still **not** the spec’s “lightweight cross-encoder.” F-001 is **MITIGATED** (not fully closed) as accepted engineering deviation; honesty in module docstring still holds if updated to mention synonym stage.

### F-023 · P3 · RESOLVED · Ledger rows 38–39 lag green code

**Resolved ~08:56–08:57:** Rows **38 and 39 → 🟢 DONE** (Actioned 2026-07-22 09:50:00 UTC). Resolution notes match observed code (synonym canon, shared-ID fixture, VnV1/2, full suite 226/226 claim). Independent tests still **6/6 OK** this fire.

### F-024 · P1 · OPEN · CandidateCache not wired to API/session (row 40 blocker)

`matching.py` gained `CandidateCache` (put_all/get by candidate_id) — needed so `POST /v1/ontology/relationships` can ACCEPT by `candidate_id`. **Not referenced** outside `matching.py` yet: `api.py` analyze path does **not** call `put_all`; no `session.candidate_cache` (or similar). Fresh process or re-analyze regenerates new UUIDs → ACCEPT by prior id will 404 unless wired before/with row 40.

---

### 2026-07-22 08:51 (Grok scheduled fire) — confirm VnV2 green; no further material

- Re-confirmed git dirty set: `api.py` modified; untracked `matching.py`, `profiling.py`, `test_explore_analyze.py`, Master Spec, etc. No `ui/`.
- Re-ran `tests.test_explore_analyze` + `tests.test_profiling` → **6/6 OK**.
- Measured vsim(cust_id,client_num)≈1.0 post-synonym; S≈0.85.
- **No new Phase 2 / ontology / UI files** this cycle.
- Updated finding statuses: F-001 MITIGATED; F-015/F-017/F-019 RESOLVED; F-020 MITIGATED; F-021–F-023 open residuals.
- **Attention remaining:** F-003 (KV-only profiler on real data), F-021 (synonym FP), rows 40–47 still zero code.

### 2026-07-22 08:54 — Heartbeat · no material change

- Git dirty set **unchanged** (matching/profiling/test_explore_analyze still untracked; api.py modified; no new paths).
- Newest discovery mtimes still **08:50** `profiling.py` (synonym fix); matching/api/tests unchanged since last fire.
- Grep: only `POST /v1/explore/analyze` in synapse; **no** `ontology/relationships`, `RelationshipEdge`, transitive, SAME_ENTITY_AS write-back.
- `ui/` absent; `ontology.py` mtime still 2026-07-21 (pre-discovery stream).
- Ledger rows **38–47 all still PENDING** (F-023).
- Phase 2 gate: no Phase 2 work observed.
- **Still open attention:** F-003, F-021; next expected Claude work = row 40 ontology relationships or ledger closeout of 38–39.

### 2026-07-22 08:57 — Rows 38–39 DONE + CandidateCache scaffold

**Ledger:** 38 🟢 DONE, 39 🟢 DONE (09:50 UTC notes). 40–47 still 🔴 PENDING. Row 35 backlog still PENDING.

**Code change this fire:**
- `matching.py` 5615→6300 B (08:57): added **`CandidateCache`** in-memory by `candidate_id`. Formula/thresholds/CandidateEdge **unchanged**.
- Cache **not yet wired** into `api.py` analyze handler or `session` (F-024).

**Independent verify:** `tests.test_explore_analyze` + `tests.test_profiling` → **6/6 OK**.

**Spec / gate:**
| Check | Status |
|-------|--------|
| MG1+MG2 close claims vs code | Aligned (honest synonym + shared-value story in resolution notes) |
| SchemaFieldProfile in models.py | Still NO (F-002 open; ledger 38 claimed profiling only — partial vs row text) |
| Phase 2 | None |
| `POST /v1/ontology/relationships` | Absent — row 40 next |
| ui/ | Absent |

**Finding updates:** F-023 RESOLVED; **F-024 NEW** (cache unwired). Residual opens: F-002, F-003, F-014, F-016, F-018, F-021, F-022.

**VnV:** L1+L2 green synthetic; L3–L4 not started. Phase gate still needs Vikas after 40–46.

### 2026-07-22 08:58–09:00 — MG4 mid-stream: registry + HTTP + ER stub gap

Claude rapidly advanced row 40 (and partially 41) in the same burst:

| Piece | State |
|-------|--------|
| `RelationshipEdge` / `RejectedCandidate` on `OntologyRegistry` | **Present** — predicates exact; describe() exposes relationships |
| `CandidateCache` on session + `put_all` in analyze | **Present** → **F-024 RESOLVED** |
| `POST /v1/ontology/relationships` | **Present** — ACCEPT/REJECT/RELABEL; operator role gate |
| `er.link_schema_fields(...)` on ACCEPT SAME_ENTITY_AS | **BROKEN** — see **F-028 P0** |
| `link_schema_fields` on EntityResolutionService | **Missing** (grep: only the call site) |
| REJECT filter in `analyze_sources` | Still not applied (F-026) |
| SQLite durability of relationships | Still none (F-027) |
| Tests for relationships API | None yet |
| UI | None |

**Independent smoke:** `accept_relationship` / `describe` / `is_pair_rejected` / session.candidate_cache — OK.

### F-024 · update · RESOLVED

Cache wired: `session.candidate_cache` + analyze `put_all` + ACCEPT lookup by id.

### F-025 · P1 · PARTIAL → mostly closed · HTTP write-back exists

Route exists with VnV3-compatible ACCEPT body (`action`+`candidate_id`). Still need automated VnV3 test (row 46).

### F-026 · P1 · OPEN · REJECT not enforced on re-analyze

`is_pair_rejected` helper exists; `analyze_sources` / `score_pair` never consult it → rejected pairs can reappear.

### F-027 · P2 · OPEN · Relationships not durable

Registry relationships are process memory only (like DriftDetector baselines). Catalog “institutional memory” dies on restart until store-backed.

### F-028 · P0 · REVISED · ACCEPT links wrong ER instance (silent no-op for session.er)

**Prior claim (undefined `er` / missing method) was wrong after Claude’s next edit.** Current facts:

1. `make_handler` binds **local** `er = EntityResolutionService(session.store)` at line 481 — **not** `session.er`, and **without** `ontology=`.
2. `link_schema_fields` **exists** on `EntityResolutionService` (`entity_resolution.py` ~82) + `linked_sources_for` helper for transitive.
3. ACCEPT path calls `er.link_schema_fields(...)` on that **throwaway** instance.

**Independent repro (09:00):** ACCEPT returns **200** + registry edge OK; `session.er.linked_schema_fields` remains **`set()`**.

**Impact:** VnV3/L4 registry tests **pass** (they never assert ER). Row 41 “instantly update ER” is **effectively unimplemented** for the session’s ER used by the rest of the platform. Transitive engine (row 42) will walk empty links if it uses `session.er`.

**Fix:** `session.er.link_schema_fields(...)`. Bonus: pre-existing merge/suggest routes also use the orphan `er` — broader consistency risk (F-030).

### F-029 · P2 · OPEN · RELABEL-without-relationship_id creates a second edge

If RELABEL is called with only `candidate_id` (no `relationship_id`), handler calls `accept_relationship` again → **new** relationship_id rather than mutating the prior ACCEPT. Spec intent of RELABEL is change predicate on existing edge. May duplicate catalog entries.

### F-030 · P2 · OPEN · make_handler’s local `er` ≠ session.er

`er = EntityResolutionService(session.store)` at handler construction is a long-standing pattern (merge + suggestions). Discovery ACCEPT joined that pattern. Any state on ER (linked_schema_fields, maybe future) diverges from `session.er`. Prefer single `session.er` everywhere.

### F-031 · P2 · OPEN · VnV3 test does not assert ER side effect

`test_vnv_layer_3_...` checks HTTP 200 + registry membership only — misses F-028. Row 41 needs an assertion: after ACCEPT, `session.er.linked_schema_fields` (or public API) contains the pair.

### F-025 · update · RESOLVED (API+test)

`tests/test_ontology_relationships_api.py` present; VnV3 ACCEPT + L4 registry readback green. REJECT/RELABEL/403/400 covered. Operator role gate OK (`principal: l2` has operator).

### F-024 · confirmed RESOLVED

`session.candidate_cache` + analyze `put_all` + ACCEPT lookup — independently exercised.

---

### 2026-07-22 09:00 — MG4 burst audit (rows 40–41 partial)

**New/changed files:**
- `ontology.py` — RelationshipEdge, RejectedCandidate, accept/reject/relabel, describe() relationships
- `session.py` — candidate_cache
- `api.py` — explore put_all; POST /v1/ontology/relationships
- `entity_resolution.py` — link_schema_fields, linked_sources_for
- `tests/test_ontology_relationships_api.py` — 5 tests

**Independent tests:** `test_ontology_relationships_api` + `test_explore_analyze` → **7/7 OK**.

**Ledger:** 38–39 DONE; **40–47 still PENDING** (Claude mid-row, not closed).

**Spec compliance:**
| Contract | Status |
|----------|--------|
| ACCEPT body `{action, candidate_id}` | YES |
| Predicates SAME_ENTITY_AS / FOREIGN_KEY_TO / DERIVED_FROM | YES |
| Registry query returns edge (GET /v1/ontology) | YES |
| ER update on ACCEPT | **NO** — wrong instance (F-028) |
| Field-level not entity merge() | YES design intent (comments honest) |
| REJECT filters re-analyze | NO (F-026) |
| Transitive Source C | NO |
| Phase 2 | None |
| Domain-blind | Relationship API generic — OK |

**Attention:** **F-028 P0** fix `session.er.link_schema_fields`; then close row 40/41 with tests asserting ER state. Still open F-003, F-021, F-026, F-027, F-029–F-031. No ui/.

### 2026-07-22 09:03 — Transitive engine + L4.2 green; L2 negative test regressed

**New this fire:**
- `matching.transitive_candidates(...)` — walks **ontology.relationships** (SAME_ENTITY_AS), not `session.er.linked_*` (so F-028 does **not** block L4.2).
- `POST /v1/explore/analyze`: `source_b` now **optional**; omit → treat `source_a` as Source C transitive mode.
- Test `test_vnv_layer_4_target_2_transitive_candidate_to_source_a` — **PASS** (customer_identifier / shared IDs / reason cites TableB).

**Independent suite:** ontology_relationships + explore_analyze → **7/8 OK, 1 FAIL**:
| Test | Result |
|------|--------|
| VnV2 high-scoring pair | OK |
| VnV3 ACCEPT + L4 registry | OK |
| VnV4.2 transitive | OK |
| REJECT / RELABEL / 403 / 400 action | OK |
| `test_missing_source_returns_400` | **FAIL** — posts only `source_a` expects 400; API now returns **200** (transitive mode) |

**F-028 status:** still OPEN — ACCEPT still calls local `er.link_schema_fields` (api.py ~1052), not `session.er`. Transitive path correctly uses registry, so product demo of L4.2 works without ER fix.

**F-026:** still OPEN — `analyze_sources` does not call `is_pair_rejected`.

**Ledger:** 38–39 DONE; **40–47 still PENDING** despite substantial 40–42 code.

### F-032 · P1 · OPEN · explore/analyze missing-source contract drift

Row 39 / older test: require both `source_a` and `source_b` (400 if missing).  
Row 42 / new API: only `source_a` required; bare `source_a` = transitive evaluate.

Honest product change, but:
1. `tests/test_explore_analyze.py::test_missing_source_returns_400` is **red** (stale expectation).
2. Docs/ledger should state dual-mode contract: pair mode vs transitive-C mode.
3. Empty store + only source_a may return `candidates: []` with 200 — fine, but not a 400.

**Recommend:** update negative test to 400 only when **neither** source is meaningful / unknown action; or 400 when source_a missing; drop “source_b required” assertion. Add explicit test: no source_a → 400.

### F-033 · P2 · OPEN · Transitive CandidateEdge field orientation

`transitive_candidates` sets `source_a=other_side` (linked A field) and `source_b=best_c_b.source_a` (C’s field). Spec prose “link C to Source A” is satisfied in content; consumers must not assume `source_a` is always the request’s `source_a` parameter. Document for UI (row 45).

### F-034 · P2 · OPEN · Transitive skips principal on nested profile_source

`profiles_b = profiler.profile_source(source_b)` inside transitive — **no principal**. Outer call profiles C with principal. Cross-ACL leakage risk if multi-tenant raw coexists under linked source names (same class as early Explore F-gaps). Thread principal through `transitive_candidates`.

**Phase 2:** none. **ui/:** none. **Highest attention:** F-028 (session.er), F-032 (red test), then ledger close 40–42.

### 2026-07-22 09:06–09:07 — Rows 40–42 DONE; UI scaffold + Explore/Catalog views; suite claim overstated

**Ledger:** 38–42 🟢 DONE; **43–47 still PENDING**. Phase 2 explicitly blocked on Vikas (row 42 note) — good.

**Backend residual (re-verified 09:06):**
- ACCEPT → `session.er.linked_schema_fields` still **empty** (local `er` only) — **F-028 OPEN**.
- Row 41 resolution claims: (a) intentionally wired to `make_handler`'s `er`, (b) transitive exercises `linked_schema_fields`. **(b) is incorrect** — `transitive_candidates` walks `ontology.relationships`, not ER. So row 41's ER path is **orphaned metadata**; product path is registry-driven (honest enough for L4.2, but ledger overclaims ER integration).
- **F-032 still red:** `test_missing_source_returns_400` expects 400, gets 200. Independent run **7/8** on explore+ontology files — **not** 232/232 if that one is in full suite (Claude's row 42 full-suite claim needs re-run after fixing F-032).

**UI (row 43–45 mid-flight, untracked `ui/`):**
| Piece | Present? | Notes |
|-------|----------|-------|
| Vite + React 19 | YES | `package.json` |
| `reactflow` | YES | graph lib choice (spec: d3-force or react-flow) |
| `react-router-dom` | YES | unused so far (tabs via state) |
| Dev proxy `/v1`→8787 | YES | vite.config.js |
| `src/api.js` | YES | analyze dual-mode, decide ACCEPT/REJECT/RELABEL |
| `ExploreView` | YES | pair/transitive modes, ReactFlow canvas, edge click → drawer |
| `CatalogView` | YES | relationships from GET /v1/ontology, group by source pair, match_reasons |
| `ExplanationDrawer` | YES | present (not fully audited this fire) |
| Serve `ui/dist` from api.py | **NO** | STATIC_DIR still `synapse/static` only |
| Profiling step UI | **NO** | Spec journey step 2 “show profiling output” not in ExploreView |
| Sense board parity | **NO** | Old index.html still sole production UI |

**Positive UI notes:** full-width shell (`.content` flex fill); Catalog/Explore loop via `catalogVersion`; transitive mode explicit in UI (aligns F-032 dual-mode).

### F-035 · P1 · OPEN · Row 41 ledger overclaim vs ER wiring

Resolution text says transitive validates `linked_schema_fields` and that API `er` is the right instance. Evidence: transitive ignores ER links; `session.er` never receives ACCEPT updates. Either fix to `session.er` + assert in test, or amend resolution to “registry is SoT; ER link set is secondary/orphan for now.”

### F-036 · P1 · OPEN · Full-suite 232/232 claim conflicts with known red test

Until `test_missing_source_returns_400` is fixed or deleted, claiming full suite green is **overclaim**. Watch for silent test deletion vs honest dual-mode update.

### F-037 · P2 · OPEN · UI production static path not switched

Row 43 requires serving `ui/dist/` via existing static handler. Not done — fine mid-row 43; block DONE on 43 until wired + smoke.

### F-038 · P2 · OPEN · Explore UI missing live profiling panel

Spec/ledger row 45 step (2): show row-38 profiling as computed. Current UI jumps source select → analyze graph. Residual product gap for guided journey.

**No Phase 2 code.** Attention order: F-032 (red test) → F-028/F-035 (ER honesty) → finish UI static serve + profiling panel → VnV row 46 closeout.

### 2026-07-22 09:09 — F-032 fixed; UI dist + `/app/` static serve; VnV HTTP 9/9 green

**Tests:** Independent `test_explore_analyze` + `test_ontology_relationships_api` → **9/9 OK**.
- `test_missing_source_a_returns_400` (body only `source_b`) → 400
- `test_omitted_source_b_is_transitive_mode_not_an_error` → 200 + empty candidates
- VnV2/3/4 still green

**F-032 → RESOLVED** (honest dual-mode contract, not silent deletion). **F-036** suite overclaim on that red test **mitigated** for these modules (full 232 suite not re-run this fire).

**UI static (row 43 mid):**
- `ui/dist/` built (hashed assets present)
- `UI_DIST_DIR = …/ui/dist`; GET `/app` and `/app/*` SPA fallback
- Legacy `/` still `synapse/static/index.html` until parity — matches row 43 “do not delete until parity”
- `vite.config.js` `base: '/app/'` aligned with serve path
- **F-037** largely **RESOLVED** (serve path exists); residual: not default homepage, no automated smoke of `/app/`

**Still OPEN:**
- **F-028 / F-035:** ACCEPT still `er.link_schema_fields` (api.py ~1071), not `session.er` — reconfirmed by code grep
- **F-038:** Explore still no live profiling panel
- **F-026:** REJECT not filtered on re-analyze
- Rows **43–47 PENDING** (UI code largely present for 43–45; not ledger-closed)

**Phase 2:** none observed. **Attention:** close 43–45 with honesty on parity/profiling gaps; fix or document F-028 before claiming ER integration.

### 2026-07-22 09:12 — Heartbeat · no material logic change

- Git dirty set unchanged; newest touch is **ui/dist rebuild** (~09:10, asset hash same family) — no new `ui/src` edits since 09:07.
- `api.py` still 09:09 (`/app/` serve); ACCEPT still `er.link_schema_fields` (F-028 OPEN).
- Ledger **38–42 DONE / 43–47 PENDING** unchanged.
- No Phase 2; no SESSION_HANDOFF/mgmt closeout (row 47).
- Residual stack: F-028/F-035, F-026, F-038 (profiling panel), F-003 (KV profiler), close rows 43–46 with parity honesty.

### 2026-07-22 09:15 — Rows 43–45 ledger DONE (UI); code unchanged since ~09:10

**Ledger:** 38–45 🟢 DONE; **46–47 still PENDING**. No new Python/JS source mtimes after prior fire — closeout is **documentation of already-landed UI** + claimed Chrome E2E.

**Row claims vs code audit:**

| Claim | Assessment |
|-------|------------|
| Vite + React full-viewport shell | **Match** (`index.css` / `App.css` flex 100vh) |
| `base: '/app/'` + API serve `/app/*` | **Match** (api.py UI_DIST_DIR) |
| Legacy `/` kept until Sense parity | **Match** / honest (RAW/MEANING/… not in new UI) |
| Catalog: ontology relationships + match_reasons + refreshKey loop | **Match** CatalogView.jsx |
| Explore: ReactFlow canvas, edge→drawer, ACCEPT/REJECT/RELABEL | **Match** ExploreView + ExplanationDrawer |
| Graph lib = **reactflow** | **Match** package.json (spec allowed) |
| Live E2E Billing-Zuora ↔ CRM-Salesforce | **Not re-run by Grok this fire** — plausible; Graph Proximity 1.00 in reasons implies extracted entities (gprox path works when store has types) |
| Full suite 38–45 | Deferred to row 46 — good discipline |

**Spec journey gap still open (F-038):**
Row 45 scope listed step (2) **“show row-38 profiling output as it's computed.”** Code has **no** profiling UI (`grep` profile/profiling in `ui/src` = empty). Resolution note describes source→analyze→graph→drawer→accept→Catalog and **omits** the profiling step without calling out residual. Treat as **incomplete vs original row text**, not necessarily a false E2E of the rest.

**Backend residuals unchanged:**
- F-028/F-035: ACCEPT → local `er`, not `session.er`
- F-026: REJECT not applied on re-analyze
- F-003: KV-only profiler (real CSV still weak unless KV-shaped)

**VnV checklist update:** L3 now **UI+API** for ACCEPT path (drawer dispatches correct body shape with candidate_id). L1–L4 synthetic API still green from prior fire. Phase gate: still needs Vikas + row 46–47.

### F-039 · P2 · OPEN · Row 45 closed without residual note on profiling step

Product may be acceptable for demo, but ledger DONE implies full row scope. Recommend row-46 or a follow-up residual: “profiling panel deferred” or implement before Phase 1 sign-off narrative.

### F-040 · P3 · NOTE · New UI is discovery-only, not Sense replacement

Correct per row 43 “do not delete legacy until parity.” Risk: demos at `/app` only → operators lose Sense panels unless told to use `/`. SESSION_HANDOFF (row 47) should document both URLs.

**Phase 2:** none. **Next:** row 46 VnV automation/consolidation; row 47 docs; optional F-028 honesty fix.

### 2026-07-22 09:08 — F-032 fixed honestly; UI scaffold live

**Tests:** `test_missing_source_returns_400` replaced by:
- `test_missing_source_a_returns_400` (only source_b → 400)
- `test_omitted_source_b_is_transitive_mode_not_an_error` (only source_a → 200, empty candidates)

This is the correct dual-mode contract documentation-in-tests — **F-032 RESOLVED**, **F-036 mitigated** for this suite (full suite re-verify still recommended).

**UI burst (rows 43–45 mid):** Vite + React + **reactflow**, Explore + Catalog + ExplanationDrawer, dev proxy to 8787. Still open: **F-037** (no ui/dist serve), **F-038** (no profiling panel), F-028 session.er.

**Ledger:** 38–42 DONE; 43–47 PENDING.

### 2026-07-22 09:09 — `ui/dist` built + `/app/` static serve (F-037 largely closed)

| Piece | State |
|-------|--------|
| `ui/dist/` production build | YES (assets + index.html with `base: /app/`) |
| `UI_DIST_DIR` in api.py | YES |
| GET `/app` and `/app/*` | YES — path traversal guard; SPA fallback to index.html; 404 hint if not built |
| Legacy Sense board at `/` | **Preserved** (honest until panel parity — matches row 43) |
| Vite `base: '/app/'` | Aligns with served asset paths |

**F-037 → RESOLVED** for “serve built bundle from Python.” Residual: no automated smoke that GET /app returns 200; npm build not in CI.

**Still open for rows 43–45 DONE:** F-038 profiling panel; Sense parity; F-028 session.er; ledger still shows 43–47 PENDING (correct mid-flight).

**No Phase 2.**

### 2026-07-22 09:18 IST — Row 46 DONE + row 47 mid-flight docs; no new code

**Clock:** local 2026-07-22 09:18 (+05:30). Git: `main` ahead origin by 7, dirty (same untracked set: Master Spec md/pdf, `new_data/`, profiling/matching, tests, `ui/`, this watch file).

**What changed since 09:15 (material = docs/ledger only):**

| Path | mtime (local) | Delta |
|------|---------------|-------|
| `Active_File.md` | 09:16 | **Row 46 → 🟢 DONE**; row 47 still 🔴 PENDING |
| `docs/SESSION_HANDOFF.md` | 09:17 | Semantic Discovery section + dual URLs `/app` vs `/`; Phase 2 gated language; claims suite 232/232 |
| `management/Road_map.md` | 09:18 | New section rows 38–47; Phase 1 narrative; Phase 2 not started |
| `management/Features.md` | 09:18 | New capability table (profiling / scoring / relationships / transitive / Vite UI) |
| `synapse/*`, `ui/src/*`, VnV tests | unchanged | last code ~09:01–09:09; UI src ~09:07 |

**Independent VnV re-run this fire:**  
`python -m unittest tests.test_explore_analyze tests.test_ontology_relationships_api tests.test_profiling -q` → **13 tests OK** (~25s). Full 232 suite **not** re-run here; handoff/Features claim retained as Claude’s claim pending full discover if needed.

**Ledger snapshot:**

| Rows | State |
|------|--------|
| 38–46 | 🟢 DONE |
| 47 | 🔴 PENDING (docs already largely written — closeout may complete next fire) |
| 35 | still backlog 🔴 PENDING (RC-06 etc., pre-spec) |

**Doc honesty audit (row 47 content vs residual findings):**

| Claim in Handoff / Roadmap / Features | Grok assessment |
|--------------------------------------|-----------------|
| MG1–4 landed; formula/thresholds exact | **Match** prior code audit |
| Hashing-trick + synonym stand-in for cross-encoder | **Honest** (F-001 MITIGATED residual quality) |
| `/app` Vite + legacy `/` Sense until parity | **Match** (F-040) |
| Phase 2 not started; needs Vikas sign-off | **Match** — no Phase 2 code |
| ACCEPT “wires into” `link_schema_fields` | **Partial** — method exists and is called, but on **handler-local `er`**, not `session.er` (**F-028 OPEN**). Product ER instance does not see links. Docs do not mention this gap. |
| Explore journey “pick → analyze → graph → drawer → Catalog” | **Match code**; still **omits** row-45 step (2) profiling panel (**F-038 / F-039**) |
| 232/232 | VnV modules green; full suite not re-verified this fire |
| Transitive via registry | **Match** (not via ER links) |

**Finding status updates:**

| ID | Status this fire |
|----|------------------|
| F-028 | **OPEN** — reconfirmed `api.py:1071` `er.link_schema_fields(...)` |
| F-035 | **OPEN** — Features/Roadmap still overclaim “wired into ER” without session instance |
| F-026 | **OPEN** — no new REJECT-filter code |
| F-038/F-039 | **OPEN** — no `profil*` in `ui/src`; docs still omit residual |
| F-037 | **RESOLVED** (prior) — `/app` serve |
| F-032/F-036 | **RESOLVED** (prior) — dual-mode tests green |
| F-003 | **OPEN** — KV profiler vs real CSV |
| F-040 | **PARTIALLY ADDRESSED** — Handoff now documents both `/` and `/app` |

### F-041 · P2 · OPEN · Row 47 docs omit known Phase-1 residuals

Closeout docs (Handoff, Road_map, Features) correctly gate Phase 2 and describe dual UI URLs, but do **not** surface:
1. session.er vs handler-local ER (F-028),
2. missing live profiling UI step (F-038),
3. REJECT not filtering re-analyze (F-026),
4. KV-only profiler vs production CSV/JSON payloads (F-003).

**Recommend:** before calling Phase 1 “ready for Vikas sign-off,” add a short “Known residuals / not blocking demo” bullet list in SESSION_HANDOFF. Otherwise sign-off reviewers only see green narrative.

**VnV checklist (spec layers):**

| Layer | Evidence | State |
|-------|----------|-------|
| L1 profiles / vectors | `test_profiling` | green |
| L2 S_total + reasons | explore_analyze VnV2 | green |
| L3 ACCEPT body + registry | ontology_relationships | green (API); UI path prior E2E claim not re-run |
| L4 transitive Source C | VnV4.2 | green |
| Phase gate | Vikas explicit sign-off | **not claimed** — correct |

**Phase 2:** none. **No catastrophic issues.** Attention: finish row 47 honestly (F-041); optional F-028 fix before “ER integration” marketing; Vikas Phase-1 review.

### 2026-07-22 ~09:20 — Monitor STOPPED (Claude stream complete)

User confirmed Claude finished. Continuous 3‑minute scheduler **cancelled**.

**Final disposition:**
- Ledger rows **38–47 all 🟢 DONE** (Phase 1 discovery stream closed in process terms).
- Automated VnV L1–L4 suite green (profiling + explore_analyze + ontology).
- Phase 2 correctly **not started**.
- **Not** the same as “Vikas Phase 1 sign-off” per Master Spec gate — that is still a human decision.
- Open residuals remain in this file (F-003, F-026, F-028/F-035, F-038/F-039, F-021, F-041, etc.) for any follow-up; not blocking *stopping the watch*.

End of continuous monitoring.


### 2026-07-22 ~09:20 � Monitor STOPPED (Claude stream complete)

User confirmed Claude finished. Continuous 3-minute scheduler **cancelled**.

**Final disposition:**
- Ledger rows **38-47 all DONE** (Phase 1 discovery stream closed in process terms).
- Automated VnV L1-L4 suite: **13/13 OK** (profiling + explore_analyze + ontology).
- Phase 2 correctly **not started**.
- Not the same as Vikas Phase 1 sign-off per Master Spec gate � that remains a human decision.
- Open residuals remain in this file (F-003, F-026, F-028/F-035, F-038/F-039, F-021, F-041, etc.) for any follow-up; not blocking stopping the watch.

End of continuous monitoring.

### 2026-07-22 09:21 IST — Phase 1 ledger batch closed (row 47 DONE); code idle

**Clock:** 2026-07-22 09:21:15 +05:30.

**Delta vs 09:18 fire:**
- `Active_File.md` mtime **09:18:52** — **row 47 → 🟢 DONE** (docs were already written at 09:17–09:18; this fire is ledger closeout only).
- No synapse / tests / ui/src mtime changes since prior fires.
- Git still dirty, ahead 7; untracked set unchanged (Master Spec, matching/profiling, ui/, new_data/, VnV tests, watch file).
- No rows 48+; no Phase 2 keywords in synapse/ or ui/src.

**Ledger:** **38–47 all 🟢 DONE**. Row 35 backlog still PENDING (unrelated RC-06+). Resolution note on 47 correctly states: self-reviewed solo; **Vikas has not signed off Phase 1**; Phase 2 not claimed.

**Code residual re-spot-check (unchanged):**
- F-028 OPEN: `api.py:1071` still `er.link_schema_fields` (handler-local), not `session.er`.
- F-026 OPEN: REJECT re-analyze filter still absent (no code churn).
- F-038/F-039 OPEN: no profiling panel in ui/src.
- F-003 OPEN: KV-oriented profiler.
- F-041 still OPEN: Handoff “Currently open” lists Phase 2 + Master Spec path, not F-028/F-038/F-003 — narrative clean but residual-light.

**Finding status rollup (end of Phase-1 ledger batch):**

| ID | Sev | Status | One-liner |
|----|-----|--------|-----------|
| F-001 | P1 | MITIGATED | Hashing + synonym, not cross-encoder |
| F-003 | P0/P1 | OPEN | KV regex vs real CSV/JSON |
| F-026 | P1 | OPEN | REJECT not filtering re-analyze |
| F-028 | P0 | OPEN | ACCEPT → local er, not session.er |
| F-035 | P1 | OPEN | Ledger/docs overclaim ER product path |
| F-038/039 | P2 | OPEN | No live profiling UI step |
| F-041 | P2 | OPEN | Closeout docs omit residuals |
| F-032/036/037 | — | RESOLVED | dual-mode tests; /app serve |

**VnV:** Prior fire 13/13 green; not re-run (no code change). Full 232 claim remains Claude’s, not re-verified.

**Phase 2 gate:** Intact — no MG5–7 work. Next real attention is **Vikas Phase-1 review** against residuals above, not more ledger theater.

**This fire:** material for **ledger completion only**; engineering surface **no material change**.


---

# RESIDUAL FIX WATCH (resumed 2026-07-22 ~09:25)

User: Claude is working on issues Grok raised. Monitor re-armed (scheduler 019f87f796a8, every 3m).

## Snapshot ~09:26

### F-028 / F-030 session.er � RESOLVED (code)
`make_handler` now does `er = session.er` with explicit comment that a second throwaway ER made ACCEPT `link_schema_fields` invisible. ACCEPT still calls `er.link_schema_fields` � now the session instance. **Recommend:** regression test ACCEPT then assert `session.er.linked_schema_fields` non-empty (F-031 residual).

### F-026 REJECT re-analyze filter � RESOLVED (code)
`analyze_sources` skips edges where `ontology.is_pair_rejected(source_a, source_b)`. Docstring honest. Transitive path goes through `analyze_sources` for C-B scoring so inherits filter for those pairs; pure transitive C-A synthesis does not re-score rejected C-A pairs separately (acceptable if C-A never was REJECT-scored). **Recommend:** unit test REJECT then re-analyze pair returns empty for that field pair.

### F-038 / F-039 profiling UI step � RESOLVED (code, needs rebuild)
- `GET /v1/explore/profile?source=...` ACL via principal
- `ui/src/views/ProfilePreview.jsx` + CSS; chips for field_name/data_type/entropy title
- `ExploreView` shows ProfilePreview for sourceA and sourceB in pair mode
- `ui/src/api.js` `profile()` helper
**Residual:** `ui/dist` still mtime ~09:10 � production `/app` may not show ProfilePreview until `npm run build`. Dev server would.

### F-003 KV-only profiler � STILL OPEN
`profiling.py` still only `_KV_RE` over `raw.raw_payload`. No JSON object walk / CSV header path. Highest remaining product gap for real New Data.

### F-034 principal on transitive � PARTIAL check
API analyze transitive call: `transitive_candidates(..., principal=principal)` � verify signature accepts it (in progress this session).

### F-041 docs residuals � STILL OPEN
Handoff/Features/Road_map not re-touched since 09:18 (before residual fixes). Should list residual work after Claude finishes.

### Phase 2
None observed. Good.

### Next watch
- Tests for F-028/F-026
- Rebuild ui/dist
- F-003 structured payload profiling
- Full suite green

### 2026-07-22 ~09:28 � Residual fixes in flight; product logic OK, tests brittle (2 FAIL)

**Independent verification:**
- Core analyze + REJECT filter: after REJECT, `analyze_sources` returns 0 edges (F-026 product OK).
- `er = session.er` in make_handler; ACCEPT populates `session.er.linked_schema_fields` with **suffixed** source names (F-028 product OK � evidence from failing assertion showing the set is non-empty with correct pairs).
- `transitive_candidates(..., principal=principal)` threads ACL (F-034 closed).
- Profile UI + GET `/v1/explore/profile` present (F-038 code OK; dist may be stale).

**`tests.test_ontology_relationships_api`: 9 tests, 2 FAIL:**

1. `test_accept_updates_session_er_blocking_metadata` � asserts hardcoded `('TableA','cust_id','TableB','client_num')` but seed uses `TableA_{testMethodName}`. ER **did** record the link; assertion is wrong.
2. `test_vnv_layer_4_target_2_transitive_candidate_to_source_a` � looks for a specific TableA/B/C pattern among candidates; shared session has many ACCEPTs from other tests so results are multi-edge noise; assertion `[] is not true` with a long candidates list that **includes** the expected direction under suffixed names � filter too strict / wrong names.

**F-042 � P1 � OPEN � Test isolation / naming lag after unique-source seed**
Product residual fixes are ahead of test updates. Claude already added unique sources per method (good for F-026 session pollution) but left assertions and one re-analyze path on bare `TableA`/`TableB`.

**F-003** still OPEN (KV profiler).
**F-041** docs not yet updated for residual fix pass.
**ui/dist** rebuild not observed after ProfilePreview.

**Attention for Claude:** fix ER assert to use actual `top['source_a']` systems; fix reject reanalyze to use same suffix sources; fix transitive test to seed in isolation or filter by expected source names from this test's seed; rebuild ui/dist.

### 2026-07-22 ~09:29 � Suite progress: 16 tests, 1 FAIL left

- Transitive VnV4.2 failure **cleared** (test isolation naming fixed).
- Remaining: `test_accept_updates_session_er_blocking_metadata` still asserts bare `TableA`/`TableB`; actual set has correct suffixed pair � **F-028 product works**, assertion lag only (F-042 partial).
- F-003 profiling.py untouched (08:50). ui/dist still 09:10. SESSION_HANDOFF still 09:17.

### 2026-07-22 09:29 IST — Residual re-verify fire (scheduler 019f87f796a8)

**Clock:** 2026-07-22 09:29 local. **Git:** `main` ahead origin by 7; dirty (same untracked discovery set: Master Spec, matching/profiling, ui/, new_data/, VnV tests, this watch file). Modified: api/ontology/session/entity_resolution + docs/ledger.

**Material mtimes this residual window:**
| Path | mtime | Note |
|------|-------|------|
| `synapse/api.py` | 09:25 | `er = session.er`; GET `/v1/explore/profile` |
| `synapse/matching.py` | 09:23 | `is_pair_rejected` in analyze; principal on transitive |
| `synapse/ontology.py` | 09:24 | reject helpers |
| `tests/test_ontology_relationships_api.py` | 09:28 | F-042 assertion + isolation fixes |
| `ui/src/views/ProfilePreview.jsx` | 09:25 | live profiling chips |
| `ui/dist` assets | **09:29** | rebuilt — production `/app` includes profile-preview |
| `synapse/profiling.py` | **08:50** | **unchanged** — still KV-only |
| `docs/SESSION_HANDOFF.md` | 09:17 | **not** updated for residual-fix pass |

**Independent tests this fire:**
```
python -m unittest tests.test_explore_analyze tests.test_ontology_relationships_api tests.test_profiling -v
→ Ran 16 tests in ~21s — OK
```
Includes: VnV L1–L4, dual-mode analyze, ACCEPT→session.er, REJECT then re-analyze empty, transitive Source C.

**Priority findings re-verify:**

| ID | Status | Evidence |
|----|--------|----------|
| **F-028** | **RESOLVED** | `make_handler`: `er = session.er` (api.py ~491) + comment; ACCEPT `er.link_schema_fields`; test asserts `session.er.linked_schema_fields` with dynamic `top['source_*']` systems — **PASS** |
| **F-026** | **RESOLVED** | `analyze_sources` skips `ontology.is_pair_rejected`; `test_reject_then_reanalyze_does_not_resurface_pair` **PASS** |
| **F-038/F-039** | **RESOLVED** | GET `/v1/explore/profile?source=` + principal; ProfilePreview in ExploreView; **ui/dist rebuilt 09:29** embeds `profile-preview` / `x.profile` / entropy chips |
| **F-034** | **RESOLVED** | `transitive_candidates(..., principal=principal)` + nested `profile_source(..., principal=principal)` |
| **F-003** | **OPEN** | profiling.py still only `_KV_RE` over raw_payload; mtime 08:50; no JSON/CSV walk |
| **F-041** | **OPEN** | Handoff/Road_map/Features mtime still 09:17–09:18; do not list residual-fix outcomes or remaining F-003 |
| **F-042** | **RESOLVED** | ER assert uses suffixed systems from seed; suite green (was assertion lag only) |
| **F-030** | **RESOLVED** | with F-028 (single session.er) |
| **F-035** | **MITIGATED** | product path now matches "wires into ER"; docs still lag (F-041) |

**Phase 2 gate:** No MG5–7 / CDM / new Phase-2 surface. Ledger 38–47 remain DONE; **Vikas sign-off still required** before Phase 2.

**Still open (attention for Claude / Vikas):**
1. **F-003 (P0/P1)** — structured JSON/CSV profiling for real New Data / connectors
2. **F-041 (P2)** — honest residual list in SESSION_HANDOFF (fixed vs remaining)
3. Lower: F-001 (not cross-encoder), F-002 (SchemaFieldProfile not in models.py), F-021 (synonym FP), F-027 (relationships not durable)

**This fire summary:** Residual product fixes **landed and green** (ER instance, REJECT filter, ProfilePreview+API+dist, principal transitive, tests). No catastrophic issues. Highest remaining product gap is **F-003**.


### 2026-07-22 09:32 IST — Residual watch fire (scheduler 019f87f796a8)

**Clock:** 2026-07-22 09:32 local. **Git:** dirty; ahead origin by 7; discovery modules still untracked. **Code mtimes vs 09:29 fire:** synapse/matching, api, profiling, ontology, ui/src **unchanged**. **Docs/ledger churn only:**
| Path | mtime | Delta |
|------|-------|-------|
| `docs/SESSION_HANDOFF.md` | **09:30** | New "Known residuals in the Semantic Discovery subsystem" (row 48) |
| `Active_File.md` | **09:30** | **Row 48 🟢 DONE** — residual fixes F-028/F-026/F-038 + honesty notes |
| Features/Road_map | 09:18 | still pre-residual-pass |
| `profiling.py` | 08:50 | still KV-only |

**Independent tests:** `tests.test_explore_analyze` + `test_ontology_relationships_api` + `test_profiling` → **16/16 OK** (~22s). No code change re-run is confirmation-only.

**Priority findings:**

| ID | Status | Evidence this fire |
|----|--------|--------------------|
| **F-028** | **RESOLVED** | `er = session.er` still; suite includes ACCEPT→session.er assert green |
| **F-026** | **RESOLVED** | `is_pair_rejected` in analyze_sources; reject-reanalyze test green |
| **F-038/039** | **RESOLVED** | GET profile + ProfilePreview + dist 09:29 unchanged |
| **F-034** | **RESOLVED** | principal threaded in transitive (matching.py) |
| **F-003** | **OPEN** | `_KV_RE` only; handoff now **honestly documents** FHIR/HL7/JSONL sparse profiles |
| **F-041** | **RESOLVED** | Handoff § residuals lists KV profiler + synonym FP; Phase 2 still gated; dual UI noted. Features/Road_map not refreshed (secondary) |
| **F-021** | OPEN (doc'd) | synonym aggression called out in handoff — no negative VnV yet |
| **Phase 2** | **NOT STARTED** | Handoff + row 48: Vikas sign-off required |

**Assessment:** Claude closed residual *product* work earlier and this fire closed residual *documentation honesty* (F-041 / row 48). Engineering surface idle. **Only material OPEN product finding remains F-003** (structured payload profiling) — correctly framed as not demo-blocking for CSV wire format but real for JSON/HL7/FHIR sources.

**Attention:** Optional F-003 JSON/CSV field extraction; optional Features/Road_map echo of residuals; Vikas Phase-1 review. No Phase 2 work observed. No catastrophic issues.


### 2026-07-22 ~09:33 � F-003 work in flight (JSON-aware profiler)

`profiling.py` now has:
- `_flatten_json` (dotted paths; lists collapse onto same field name)
- `_extract_field_values`: try JSON if payload starts with `{`/`[`, else KV regex
- Honest residual in docstring: **HL7v2 pipe-delimited not covered** (domain-blind choice)

**Assessment:**
- F-003 **largely MITIGATED** for FHIR/JSONL/JSON connectors (was the main hole).
- CSV path already was KV-line via csv_drop connector convention (docstring reaffirms) � not a raw DictReader of .csv files, but matches how this platform lands CSV.
- Tests: still only 4 KV VnV tests; **no regression test for JSON flatten yet** (F-043 recommend).
- Handoff residual text may be slightly stale if it still says JSON sparse without update after this code lands.

Smoke: JSON payload yields fields `cust_id` and `nested.client_num` expected.

### 2026-07-22 09:35 IST — Residual watch fire (scheduler 019f87f796a8)

**Clock:** 2026-07-22 09:35 local. **Git:** dirty; discovery set still untracked. **Material code change this fire:** `synapse/profiling.py` **09:33** (F-003 JSON path), `tests/test_profiling.py` **09:33** (+2 JSON tests), `docs/SESSION_HANDOFF.md` **09:34** (row 49 residual rewrite), `Active_File.md` **09:35** (**row 49** closed).

**Independent tests:** profiling + explore_analyze + ontology_relationships → **18/18 OK** (~22s). Prior residual suite still green; new JSON tests:
- `test_json_shaped_payload_profiles_correctly` (FHIR-shaped nested + identifier.value)
- `test_repeated_list_items_collapse_onto_one_field_not_indexed` (no `.0.` explosion)

**Code audit (F-003):**
- `_extract_field_values`: JSON first if payload starts with `{`/`[`; recursive `_flatten_json` (domain-blind dotted paths); list items share field names; fallback `_KV_RE` for CSV connector wire format.
- Docstring **honest**: HL7v2 pipe-delimited **not** covered without domain-specific knowledge — residual scoped, not silent claim.
- `profile_source` walks `_extract_field_values(raw.raw_payload)` (no longer KV-only).

**Priority findings:**

| ID | Status | Evidence |
|----|--------|----------|
| **F-028** | **RESOLVED** | `er = session.er` unchanged |
| **F-026** | **RESOLVED** | `is_pair_rejected` in analyze_sources unchanged |
| **F-038/039** | **RESOLVED** | profile route + ProfilePreview + dist 09:29 |
| **F-034** | **RESOLVED** | principal on transitive unchanged |
| **F-003** | **RESOLVED (JSON + KV/CSV)** · residual **HL7 OPEN** | JSON flattener + tests green; CSV path still KV (matches `csv_drop` emit); HL7 pipe format still empty profiles — handoff names it explicitly (good honesty) |
| **F-041** | **RESOLVED** | Handoff updated row 49: synonym FP + HL7 residual; Phase 2 gated; JSON fixed claimed correctly |
| **F-021** | OPEN (watch) | synonym map still aggressive; no negative VnV |
| **Phase 2** | **NOT STARTED** | gate intact |

**Ledger:** rows 1–49 closed per handoff; row 49 = F-003 fix + residual doc update.

**Assessment:** Claude landed the main remaining product residual (JSON/FHIR/JSONL profiling). Residual stack now is **quality/watch items** (HL7 profiler, synonym FP, durability F-027, embedding stand-in) — not silent P0 correctness of the discovery path for the connectors that land JSON or KV/CSV.

**Attention:** Optional HL7 segment-aware extraction (pack/connector, not domain-blind core); F-021 negative test; Vikas Phase-1 sign-off. No Phase 2. No catastrophic issues.


### 2026-07-22 09:38 IST — Residual watch fire (scheduler 019f87f796a8)

**Clock:** 2026-07-22 09:38 local. **Git:** dirty; new modified: `synapse/store.py`, `synapse/sqlite_store.py`, `synapse/ontology.py` (09:37–09:38). Discovery profiling/API/matching mtimes **unchanged** since prior fires.

**New material this fire — F-027 durability (not Phase 2):**
| Piece | Present? |
|-------|----------|
| `SemanticStore.relationship_edges` / `rejected_candidates` + put_* | YES |
| SQLite tables `relationship_edges` / `rejected_candidates` + load/upsert | YES |
| `_relationship_edge_from_dict` / `_rejected_candidate_from_dict` | YES |
| `OntologyRegistry.store` write-through on accept/reject/relabel | YES |
| `ontology.load_from_store(store)` on `open_session` | YES (session.py) |
| Automated round-trip durability test | **Not observed** this fire |
| Ledger row / Handoff residual update for F-027 | **Not yet** (rows end at 49; handoff still HL7+synonym only) |

**Independent tests:** profiling + explore_analyze + ontology_relationships → **18/18 OK** (~24s). In-memory path unaffected; SQLite durability untested by this suite.

**Priority findings:**

| ID | Status | Evidence |
|----|--------|----------|
| **F-028** | **RESOLVED** | `er = session.er` |
| **F-026** | **RESOLVED** | `is_pair_rejected` filter |
| **F-038/039** | **RESOLVED** | profile API + ProfilePreview + dist |
| **F-034** | **RESOLVED** | principal on transitive |
| **F-003** | **RESOLVED (JSON+KV)** · HL7 residual OPEN | `_extract_field_values` + tests |
| **F-041** | **RESOLVED** for prior residuals | Handoff honest on synonym + HL7; **not yet** mentioning F-027 fix mid-flight |
| **F-027** | **RESOLVED (code)** · tests/docs lag | write-through + rehydrate wired; recommend restart round-trip unit test |
| **Phase 2** | **NOT STARTED** | durability is Phase-1 Catalog institutional memory, not MG5–7 |

**Assessment:** Idle residual stack (F-028/026/038/003) remains green. Claude mid-fix of **F-027** (relationship durability) — architecture looks correct (store + sqlite + registry dual-write + session rehydrate). No CDM/Phase-2 surface. Gate intact.

**Attention for Claude:** add SQLite ACCEPT → new session → catalog still has edge test; update SESSION_HANDOFF residual list when F-027 closes; optional HL7 residual / F-021 watch. No catastrophic issues.


### 2026-07-22 09:41 IST — Residual watch fire (scheduler 019f87f796a8)

**Clock:** 2026-07-22 09:41 local. **Git:** dirty; `tests/test_sqlite_store.py` modified; **new untracked** `tests/test_matching.py`. Store/ontology/session durability mtimes ~09:38–09:39. Handoff/Active_File still 09:34–09:35 (no row 50 yet).

**F-027 closed with test (was code-only last fire):**
- `test_ontology_relationships_survive_restart` in `test_sqlite_store.py` (mtime 09:39): `open_session` → ACCEPT → `session.close` → new `open_session(same db)` → edge in `ontology.relationships` with correct field names.
- Write-through + rehydrate path unchanged/confirmed from 09:38.

**Also new:** `tests/test_matching.py` (09:41) — 1 unit test OK (library-level matching coverage; not re-audited in depth this fire).

**Independent tests this fire:**
```
tests.test_sqlite_store + test_profiling + test_explore_analyze + test_ontology_relationships_api → 21/21 OK
tests.test_matching → 1/1 OK
```

**Priority findings:**

| ID | Status | Evidence |
|----|--------|----------|
| **F-028** | **RESOLVED** | `er = session.er` |
| **F-026** | **RESOLVED** | `is_pair_rejected` |
| **F-038/039** | **RESOLVED** | profile route + ProfilePreview |
| **F-034** | **RESOLVED** | principal on transitive |
| **F-003** | **RESOLVED (JSON+KV)** · HL7 residual OPEN | flattener + tests |
| **F-027** | **RESOLVED** | store+sqlite+session rehydrate **and** restart unit test green |
| **F-041** | **PARTIAL** | Handoff still lists synonym + HL7 only; **does not yet note F-027 fixed** (docs lag product). Phase 2 gate still clear |
| **Phase 2** | **NOT STARTED** | no MG5–7 |

**Assessment:** Residual engineering stack for Grok priority list is **effectively closed** except HL7 profiler residual + doc lag on F-027. Suite green. Idle on F-028/026/038/003/034.

**Attention:** Update SESSION_HANDOFF (and optional ledger row) for F-027 durability; F-021/HL7 watch-only; Vikas Phase-1 sign-off. No catastrophic issues. No Phase 2.

