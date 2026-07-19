# Grok → Claude feedback (via Vikas)

**Created (UTC):** 2026-07-19 05:30:00 UTC  
**From → To:** Grok → Claude  
**Type:** Architecture constraint for all healthcare / domain work  
**Authority:** Vikas directed: follow collaboration model; pass this to Claude  

---

## Question Vikas asked

If we want to convert Synapse into a **platform used by anybody**, does current work help or hurt?

## Verdict

**Mostly good IF core stays domain-blind and healthcare is a domain pack.**  
**Bad IF healthcare hard-codes into shared engine/UI/store paths.**

---

## Platform model (must preserve)

```
PLATFORM CORE (domain-blind)
  land · contracts · dual-path hooks · graph · conflict · budget · sense UI shell · connectors

DOMAIN PACKS (current focus = healthcare #1)
  ontology L1 · extract rules · authority/SoR · samples · eval golden set

FUTURE PACKS
  banking · … same slot
```

One deep vertical **tests the pack interface**. That is how platforms are born — not fake multi-domain thinness.

---

## Current work impact

### GOOD for platform (continue)
- Raw + contracts, dual-path, conflicts-first, L0/L1 ontology, budgeted ask, Sense board shell, reprocess/drift/materialize, connector runner
- Healthcare-first depth (fills first pack slot)

### BAD for platform (avoid)
- `if healthcare:` in orchestrator/store/api/core
- Hospital-only entity extract as the only path in core `extraction.py` without pack registration
- Sense board that only understands clinical fields (tabs must stay generic; domain = config/content)
- One-off hospital joins that skip generic ER/conflict APIs
- Premature multi-tenant product work now

---

## Rule for every change (Claude must apply)

> **Core = domain-blind. Healthcare = pack + data + eval.**  
> If a change only makes sense for hospitals, it goes in a healthcare domain pack (or scenario/pack module), not hard-wired as the only behavior of generic `synapse/` without a pack hook.

Ask before merging logic:  
**“Is this a core primitive or a healthcare pack feature?”**

---

## Recommended concrete actions (does not cancel ID 1)

1. **Do not block ID 1** (`hospital_management` probe). Proceed; put findings in `workspace_scratch/`.
2. When adding Patient/Appointment/Treatment extract or ontology: structure as **domain pack** pattern (extend ontology L1 + rules the same way as `clinical_lab`), not as one-off special cases only Claude understands.
3. Optional follow-up task (new Active_File row after ID 1): draft `docs/DOMAIN_PACK_CONTRACT.md` — what a pack must provide vs what core must never own. Protects “platform for anybody.”
4. Sense board: keep RAW/MEANING/CONFLICTS/ASK/EMIT generic; no healthcare-only nav rewrite.

---

## Non-goals (reaffirm)
- Not replacing HIS/LIS as systems of record
- Not multi-tenant platform sprint this phase
- Not inventing FHIR server from scratch in ID 1

---

## End state alignment
Current healthcare work, done as **first pack**, is an **investment** in a platform anyone can extend.  
Same work, done as **vertical app hardcode**, is a **detour**.

Claude: acknowledge in Active_File Resolution when read; apply on all subsequent healthcare implementation rows.
