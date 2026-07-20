# Row 34 — Episode versioning design

## Decision

Do not replace `Episode.prep_pipeline_version` during reprocess. That field is
the version that created the stored episode payload and must remain stable for
lineage and rollback. Add an append-only `pipeline_version_history` list to the
episode, initialized with the creation version; each reprocess pass records its
requested version once.

This is deliberately narrower than creating a second Episode row for every pass:
the raw object and prepared payload are unchanged, while facts already preserve
their own extractor versions and temporal history. Creating duplicate episode
rows would make the next full reprocess walk repeat the same raw input again and
would require a larger active-version/derived-view model. The history field keeps
the current Phase-1 storage model stable and makes all reprocess versions
inspectable. A future multi-version extraction product can promote this to a
separate immutable derived-view table.

## Acceptance criteria

1. Original `prep_pipeline_version` is unchanged after reprocess.
2. The requested reprocess version appears once in the append-only history.
3. Repeating the same version is idempotent.
4. Existing entity/fact reprocess tests continue to pass.
