# Project Synapse — Setup decisions

**Purpose:** Non-secret decisions only.  
**Secrets:** Live **only** in local `.env` (gitignored). **Never** paste API keys, passwords, or tokens into this file, README, chat, or git.

**Date:** 2026-07-18  
**Status:** Decisions captured · POC complete v0.14 (H1–H16 owned) · keys local only  

---

## Security rules (mandatory)

1. **Keys stay on this machine** — in `.env` only (project root).  
2. **Never commit** `.env` (listed in `.gitignore`).  
3. **Never put secrets** in `docs/`, `README`, code, logs, or screenshots.  
4. This file may only say **env var names** (e.g. `GEMINI_API_KEY`), never values.  
5. If a key is ever pasted into chat, git history, or a shared doc → **rotate/revoke** it in Google AI Studio and create a new one.  
6. Health/metrics endpoints report `gemini_configured: true/false` only — not the key.

---

## POC policy (agreed)

| Topic | Decision |
|-------|----------|
| Goal | POCs to prove the architecture; paid/real APIs later |
| LLM residual (Path B) | **Google Gemini free tier** (Flash-Lite class) |
| Free-tier envelope | ~15 RPM / ~1000 RPD → code throttle **12 RPM / 900 RPD** |
| Path A | Deterministic rules (no LLM) |
| Key storage | **Local `.env` only** (`GEMINI_API_KEY` and/or `GOOGLE_API_KEY`) |
| Model | Set `GEMINI_MODEL` to exact AI Studio id (default `gemini-2.5-flash-lite`) |
| Blueprint engines | Install all four packages; adapters prefer real import, lite fallback if broken |
| Optional cloud PageIndex | `PAGEINDEX_API_KEY` in `.env` only (never commit) |

---

## 0. Machine setup — Graphiti on this PC

### Answers

```
0.1: yes — Neo4j Docker OK (dev)
0.2: yes — pip install graphiti/neo4j OK
0.3: yes — dev password via .env
0.4: yes — ports 7474/7687 OK
0.5: no issue with LibreChat containers
```

---

## 1. Live Neo4j / Graphiti

### Answers

```
1.1: Docker local
1.2: bolt://localhost:7687 — credentials only in .env (NEO4J_*)
1.3: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, GRAPHITI_ENABLED, GEMINI_API_KEY
1.4: Gemini free tier (Flash-Lite; ~15 RPM / ~1000 RPD)
1.5: GEMINI_API_KEY / GOOGLE_API_KEY in local .env only
1.6: Yes — disposable test data OK
1.7: Lowest cost — free tier only for POC
```

---

## 2. LLM residual Path B — **POC LOCKED**

### Answers

```
2.1: Google Gemini
2.2: Gemini 3.1 Flash-Lite class (set GEMINI_MODEL to exact Studio model id)
2.3: GEMINI_API_KEY and GOOGLE_API_KEY (local .env)
2.4: yes for POC only (cloud API) — revisit for sensitive prod
2.5: free tier; throttle 12 RPM / 900 RPD; maxOutputTokens 512
2.6: N/A
```

### Code wiring

| Item | Location |
|------|----------|
| Gemini residual | `synapse/llm_gemini.py` |
| Dual-path | `synapse/dual_path.py` (auto Gemini if key present) |
| Load `.env` | `synapse/env_load.py` (CLI / session / serve) |
| Env template (no secrets) | `.env.example` |

---

## 3. First real connector

### Answers

```
3.1: files
3.2: recommend path/layout (assistant to propose)
3.3: env variables for any auth later
3.4: all (start with sample file drops)
3.5: samples TBD — generate or user will provide
3.6: recommend ACL (e.g. domain:sre or domain:ops + clearance:l2)
3.7: yes — ingest/read-only, no write-back
```

---

## 4. Priority (recommended)

```
1. Gemini Path B residual POC (keys local) — done in code
2. Neo4j Docker + Graphiti smoke (when you ask to run it)
3. File-drop connector with sample JSONL under .data/inbox/ (next data step)
```

---

## 5. Anything else

```
Keys must stay on this machine and redacted everywhere (docs, git, chat, logs).
```

---

## Checklist

- [x] Gemini chosen for Path B POC  
- [x] Residual extractor + free-tier throttle  
- [x] `.env` gitignored; `.env.example` has no secrets  
- [x] Error redaction for API keys in Gemini client  
- [x] Decisions doc contains **no secret values**  
- [x] Keys load locally (`configured True`, `gemini_residual`)  
- [x] Model id fixed to API form `gemini-3.1-flash-lite` (not display name with spaces)  
- [x] Neo4j Docker `synapse-neo4j` on 7474/7687  
- [x] `graphiti-core` installed; live smoke `AddEpisodeResults` OK  
- [x] File-drop samples in `.data/inbox/events.jsonl`  
- [x] Dual-path on connector poll (rules + residual)  
- [x] CLI: `inbox`, `graphiti-search`, `poc-status`  
- [x] Live Graphiti search ops (`synapse/graphiti_ops.py`)  
- [ ] Optional: rotate key if ever exposed outside this machine  
- [ ] Optional: Browser UI http://localhost:7474 (Neo4j) to inspect graph  

---

## Verify key is configured (safe — no secret printed)

```powershell
cd "C:\Users\Vikas Sharma\OneDrive\Documents\Claude\Projects\Project_Synapse"
python -c "from synapse.env_load import load_dotenv; from synapse.llm_gemini import gemini_configured, create_residual_extractor; load_dotenv(); print('configured=', gemini_configured()); print('backend=', create_residual_extractor().name)"
```

Expect: `configured= True` and `backend= gemini_residual`

---

*Secrets: local `.env` only. This document: decisions only.*
