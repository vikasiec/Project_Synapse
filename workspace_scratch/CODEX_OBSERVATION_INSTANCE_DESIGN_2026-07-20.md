# LabResult observation-instance identity — row 25

## Decision

Widen the LabResult external identity key with a source-provided observation
instance identifier when one exists. FHIR uses `Observation.id`, falling back
to the first `basedOn` reference. HL7v2 uses the nearest preceding OBR's
placer order (OBR-2), falling back to filler order (OBR-3). If neither format
provides an instance ID, retain the existing patient-plus-test key for backward
compatibility.

The key remains patient- and assigning-authority-scoped. This means two sources
describing the same observation instance can still converge and surface a
same-time scalar conflict (row 24), while two separate orders/specimens for the
same patient and analyte get separate LabResult entities. Temporal supersession
continues to apply only within each entity and `(predicate, source_system)` as
defined in `synapse/temporal.py`; it must not decide entity identity.

The instance ID is also stored as an `observation_instance_id` fact so the
identity decision is inspectable and available to downstream consumers.
