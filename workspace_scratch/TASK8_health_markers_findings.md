# Task 8 findings — anonymous-observation datasets don't fit the entity model (and that's the right conclusion, not a gap to fill)

**From:** Claude · **Date:** 2026-07-19 · **Ledger row:** Active_File.md ID 8

## Baseline result

28,000 rows land cleanly across both files (25,000 + 3,000) — schema-on-read
landing continues to scale fine to real volume. **0 entities extracted from
either, as predicted**: neither file has a patient_id, doctor_id, or any other
identity/foreign-key column. Every row is a fully anonymous observation
(a set of lab-marker values + a condition label, or a set of symptom flags +
a diagnosis label) — there is nothing to resolve an entity against.

## Why I'm not building extraction rules for these — and why that's the correct call, not a shortfall

I considered adding a "row = its own anonymous entity" pattern (using
`RawObject.content_hash` as identity) so something would extract. I'm not doing
that, for a reason worth stating plainly rather than quietly deciding:

**This data doesn't test anything the pack pattern exists to prove.** Every
pack built in tasks 1-7 earns its keep by demonstrating multi-source
understanding — the same real thing (a patient, a doctor, an appointment)
described or referenced from more than one place, requiring resolution and
sometimes surfacing disagreement. These two files have no "same thing
described twice" anywhere in them — each row is independent, there is no
second source to agree or disagree with it, and there is no cross-reference
to resolve. Turning each row into an "entity" would be extraction theater:
technically producing Fact/Entity records, but not exercising entity
resolution, conflict detection, or citation-back-to-source in any way that
differs from just reading the CSV directly.

This is also **exactly the shape the master architecture doc calls out as a
non-goal**: *"not one embedding store for everything"* and *"Synapse sits
above systems of record"* — a flat, already-structured, already-analyzable
table like this is closer to what a warehouse/BI view (H16) or a plain
dataframe already handles well. Forcing it through the entity/conflict
pipeline would be adding pack surface area without adding proof value —
precisely what Grok's platform-vs-domain constraint warns against ("premature
... work," "one-off ... that skip generic APIs").

## What this data would actually be good for (not attempted here, flagging for later)

If a real question shows up that needs it — e.g. "do the marker ranges this
dataset calls 'Anemia' overlap with what `lab_test_results_public.csv`'s
`Reference_Range` calls abnormal Hemoglobin?" — that's a **statistical/schema
comparison across two independent tabular sources**, not an entity-conflict
question. It would be a different capability (closer to H16 materialize +
manual analysis, or a new comparison tool) than anything the current pack
contract covers. Not building it speculatively; noting it as a real,
different, future question rather than pretending it's covered.

## Conclusion

`hospital_management/` (tasks 1, 4-6) is the dataset that actually tests and
proves the thesis, and it's done — 660/660 rows, full chain joined, a real
bug found and fixed, a conflict genuinely surfaced and correctly ranked. These
two anonymous datasets don't need pack work; they need a different capability
this project hasn't built yet, and shouldn't be built speculatively. This is a
natural stopping point for new dataset work in the healthcare vertical —
recommend review/consolidation next rather than pushing further breadth.
