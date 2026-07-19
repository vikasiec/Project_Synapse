# Session handoff — resume tomorrow

**Last session:** 2026-07-18  
**Code version:** ~0.17 (+ lab vertical)  
**Branch:** `main` (check `git status` for uncommitted work)

---

## What is done

| Area | Status |
|------|--------|
| Architecture POC H1–H16 | Owned in code + ADRs |
| Four engines (Graphiti, GraphRAG, Data-Juicer, PageIndex) | Wired (real prefer + lite) |
| Ontology load-bearing (H8) | Extract + conflict ranking boosts |
| Lab / IVD Path A | `LabResult` extractor + L1 ontology — Kaggle CSV → 27 entities, ~194 facts |
| UI wizard | 4 steps: Load → Ask → Conflicts → Decide |
| SQLite + multi-thread serve | Thread-safe fix for seed API |
| Seed UI path | Local graph only (no Graphiti hang on seed) |

**Claude review:** `claudreview.md` — ontology gap closed; lab gap addressed in follow-up section.

---

## How to resume tomorrow

### 1. Start the UI server

```powershell
cd "C:\Users\Vikas Sharma\OneDrive\Documents\Claude\Projects\Project_Synapse"
python -m synapse serve --host 127.0.0.1 --port 8787 --db .data/demo.db
```

Open: **http://127.0.0.1:8787/**  
Hard refresh: **Ctrl+F5**

### 2. Demo path (UI)

1. **Checkout outage (recommended)**  
2. **Get answer** (entity `checkout-service`)  
3. **Conflicts**  
4. **Pin** a winning source  

### 3. Useful checks

```powershell
python -m unittest discover -s tests -t .
python scripts/smoke_lab_csv.py
python -m synapse capability
```

### 4. Lab data

- CSV: `.data/kaggle_raw/lab_test_results_public.csv`  
- DB: `.data/lab_demo.db`  

---

## Known issues / caveats

- Gemini **free-tier embed quota** may 429 Graphiti live pushes — seed uses local graph only.  
- Multiple `python -m synapse serve` processes can fight for port 8787 — kill extras if “Failed to fetch”.  
- UI is a **demo wizard**, not a full product app.  
- Platform gaps still open: multi-tenancy, fuzzy ER, real SaaS OAuth CDC, real $ FinOps.

---

## Suggested next work (when you return)

1. Use UI end-to-end until comfortable  
2. Optional: commit all local changes (`git status` / `git commit`)  
3. Optional: more clinical extract patterns / Path B entity invent for unknown domains  
4. Optional: one real export (your data) via inbox or CSV  

---

## Key files

| Path | Role |
|------|------|
| `synapse/static/index.html` | Wizard UI |
| `synapse/extraction.py` | Path A rules (incl. lab) |
| `synapse/ontology.py` | L0/L1 packs |
| `synapse/sqlite_store.py` | Thread-safe SQLite |
| `docs/ADRs_H1_H16.md` | Hole ownership |
| `claudreview.md` | Claude findings + responses |
| `docs/SESSION_HANDOFF.md` | This file |
