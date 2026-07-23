"""
Standard domain-grammar mapping, shared by every format-specific extractor.

This module is the answer to "what must a healthcare interoperability
extractor anticipate, independent of any one sample file's shape" (Claude_
Instructions.md Step 1). It holds knowledge about the *standards*
(HL7v2 Table 0396, FHIR terminology system URIs) rather than about any
particular message this proof has been tested against.

1. Coding systems (LOINC / SNOMED CT / RxNorm identity normalization)
----------------------------------------------------------------------
The same lab analyte is described with a locally-meaningful code plus an
explicit pointer to *which* code system that code belongs to:

  - HL7v2 OBX-3 (and OBR-4, etc.) is a CE/CWE-type field:
    `<code>^<display>^<coding system>` — component 3 is the coding-system
    identifier, drawn from HL7 Table 0396 ("L"/"L2" = local, "LN" = LOINC,
    "SCT"/"SNM"/"SNM3" = SNOMED CT, "RXNORM"/"RXN" = RxNorm, ...).
  - FHIR `CodeableConcept.coding[]` gives the same triple as
    `{"system": <URI>, "code": <code>, "display": <display>}` — `system`
    is a canonical URI (`http://loinc.org`, `http://snomed.info/sct`,
    `http://www.nlm.nih.gov/research/umls/rxnorm`) rather than a short
    token, but it is the *same* piece of information Table 0396 encodes.

`normalize_code()` collapses both representations to one canonical key:
`"<system-slug>:<code>"`. Two extractors that both read the coding-system
component (instead of discarding it, as this proof's original HL7/FHIR
extractors both did) and both call this same function will converge on
identical LabResult identity for the identical analyte, regardless of
which wire format carried it.

Caveat, stated up front rather than discovered later: normalization here
is standards-based (system-slug + trimmed/uppercased code), not a fuzzy
matcher. If two sources both *claim* LOINC but send different code
strings for the conceptually same test (e.g. a synthetic fixture using a
placeholder like "LOINC-TSH" on one side and a bare local code "TSH" on
the other), that is a data-quality defect in the source feed, not
something a normalizer should paper over with sample-specific string
surgery — doing so would just be a more elaborate way of hardcoding to
one file's shape. See workspace_scratch/ for a worked example against
the real "New Data" fixture.

2. FHIR resource links
----------------------------------------------------------------------
`Observation.subject` is a `Reference`, which in real bundles is far more
often a bare `"Patient/<id>"` string (or a `urn:uuid:` fullUrl pairing)
than an inline `contained`/bundled `Patient` resource. An extractor that
requires an embedded `Patient` resource to exist before it will accept
any Observation only works on hand-built demo bundles. See
`synapse/extraction.py::_extract_fhir_bundle` for the stub-entity
fallback this module's normalization feeds into.

3. HL7v2 message types
----------------------------------------------------------------------
Real interface engines carry ADT (admit/discharge/transfer), ORM (order),
SIU (scheduling), and ORU (results) on the same channel, not ORU alone.
`synapse/hl7v2.py`'s tokenizer is already message-type agnostic (it
parses the generic segment/field/component grammar for *any* MSH-9).
Semantic handlers are registered per (message-type, trigger-event) pair
in `synapse/extraction.py::_HL7_MESSAGE_HANDLERS` — currently only
`("ORU", "R01")` has a handler, matching what this proof actually
implements end to end. Unregistered types fall through and are *not*
extracted, which is the existing, deliberately-honest behavior (see
`tests/test_hl7_extract.py::test_non_oru_message_type_not_extracted`) —
this module turns that single hardcoded `if` into a lookup table so
adding ADT/ORM support later is additive, not a rewrite.

4. Schema synonym mapping (LIS / middleware CSV headers)
----------------------------------------------------------------------
`CSV_FIELD_SYNONYMS` is a canonical-field -> header-alias dictionary,
scoped per ontology type, so `PatientID`/`MRN`/`patient_id` all resolve
to the same domain attribute instead of requiring an exact column-name
allowlist per known file. See `synapse/extraction.py::resolve_synonyms`.
"""

from __future__ import annotations

from typing import Optional

# --- HL7v2 Table 0396 (Coding System) -> canonical slug ------------------
# Not exhaustive (Table 0396 is a large, extensible HL7 table); covers the
# systems this proof's identity normalization cares about, plus the
# explicit "local code, no external system" markers so those don't get
# mis-slotted into a real terminology.
_HL7_CODING_SYSTEM_SLUGS: dict[str, str] = {
    "LN": "loinc",
    "SCT": "snomed",
    "SNM": "snomed",
    "SNM3": "snomed",
    "RXNORM": "rxnorm",
    "RXN": "rxnorm",
    "L": "local",
    "L2": "local",
    "99ZZZ": "local",
}

# --- FHIR CodeableConcept.coding[].system URI -> canonical slug ----------
_FHIR_SYSTEM_URI_SLUGS: dict[str, str] = {
    "http://loinc.org": "loinc",
    "https://loinc.org": "loinc",
    "http://snomed.info/sct": "snomed",
    "https://snomed.info/sct": "snomed",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "rxnorm",
    "https://www.nlm.nih.gov/research/umls/rxnorm": "rxnorm",
}


def normalize_code(system: Optional[str], code: Optional[str]) -> str:
    """
    Canonical `"<system-slug>:<code>"` identity key for a coded value,
    shared by the HL7v2 and FHIR extractors.

    `system` may be an HL7 Table 0396 token ("LN") or a FHIR system URI
    ("http://loinc.org") -- both are checked. An unrecognized or missing
    system falls back to the "local" slug rather than silently dropping
    the system distinction, so a genuinely local/proprietary code from
    one source is never accidentally treated as equal to a same-spelled
    code from an unrelated coding system.

    Returns "" if there is no code to key on at all -- callers should
    fall back to a display-name-based key in that case, same as before
    this normalization existed.
    """
    code = (code or "").strip()
    if not code:
        return ""
    sys_raw = (system or "").strip()
    slug = None
    if sys_raw:
        slug = _HL7_CODING_SYSTEM_SLUGS.get(sys_raw.upper()) or _FHIR_SYSTEM_URI_SLUGS.get(
            sys_raw.lower()
        )
    if slug is None:
        slug = "local"
    return f"{slug}:{code.upper()}"


# --- Local vendor code -> LOINC translation (docs/Instrument_Data_Format.md
# section 4, "Clinical Normalization Engine") -----------------------------
# `normalize_code()` above answers "do these two sources both claim the
# SAME coding system for this code" -- it never translates a genuinely
# local/proprietary code into a standard one. This table does that
# translation, scoped ONLY to the specific local codes actually observed
# in this project's real sample files (Roche Cobas 8000's ASTM codes,
# Siemens Atellica's numeric local codes, Abbott Alinity's ALIN- prefixed
# codes, Beckman AU5800's channel-abbreviation codes, Sysmex's CBC/diff
# panel field names) -- real, independently-verifiable LOINC codes for
# well-established, standard lab analytes, not invented mappings. A code
# with no entry here simply has no known LOINC translation; callers should
# treat that as "unknown," not assume equivalence.
#
# Known limitation, stated up front: this is a flat local-code -> LOINC
# table with no per-source scoping. A different vendor reusing one of
# these exact short codes for a genuinely different analyte would collide.
# None of the codes below are known to collide across the sources this
# project actually has -- if a new source introduces one that does, this
# table needs a (source_system, code) key instead of a bare code key.
LOCAL_CODE_TO_LOINC: dict[str, str] = {
    # Roche Cobas 8000 (ASTM R record test codes)
    "GLUC3": "2345-7",  # Glucose
    "CREP2": "2160-0",  # Creatinine
    "TSH3": "3016-3",  # Thyroid Stimulating Hormone
    "ALTL": "1742-6",  # Alanine Aminotransferase (ALT)
    "ASTL": "1920-8",  # Aspartate Aminotransferase (AST)
    "TNTHS": "10839-9",  # Troponin I, cardiac, high sensitivity
    "UREAL": "3094-0",  # Urea Nitrogen (BUN)
    "FERR2": "2276-4",  # Ferritin
    # Siemens Atellica (numeric local codes from OBX-3's CE component)
    "4055": "1989-3",  # Vitamin D, 25-Hydroxy
    "4080": "2132-9",  # Vitamin B12
    "4030": "3016-3",  # TSH, 3rd generation
    "4001": "10839-9",  # Troponin I, High Sensitivity
    "4025": "3024-7",  # Free Thyroxine (Free T4)
    # Abbott Alinity ci-series
    "ALIN-GLU": "2345-7",  # Glucose
    "ALIN-TRIG": "2571-8",  # Triglycerides
    "ALIN-HBA1C": "4548-4",  # Hemoglobin A1c
    "ALIN-CHOL": "2093-3",  # Total Cholesterol
    # Beckman AU5800 (channel/assay abbreviation codes)
    "UA": "3084-1",  # Uric Acid
    "ALP": "6768-6",  # Alkaline Phosphatase
    "TP": "2885-2",  # Total Protein
    "ALB": "1751-7",  # Albumin
    "CA": "17861-6",  # Calcium
    "PHOS": "2777-1",  # Phosphorus
    # Sysmex XN-1000 (CBC/diff panel column names double as the analyte code)
    "WBC": "6690-2",  # White Blood Cell count
    "RBC": "789-8",  # Red Blood Cell count
    "HGB": "718-7",  # Hemoglobin
    "HCT": "4544-3",  # Hematocrit
    "MCV": "787-2",  # Mean Corpuscular Volume
    "MCH": "785-6",  # Mean Corpuscular Hemoglobin
    "MCHC": "786-4",  # Mean Corpuscular Hemoglobin Concentration
    "PLT": "777-3",  # Platelet count
    "NEUT%": "770-8",  # Neutrophils, percent
    "LYMPH%": "736-9",  # Lymphocytes, percent
    "MONO%": "5905-5",  # Monocytes, percent
    "EO%": "713-8",  # Eosinophils, percent
    "BASO%": "706-2",  # Basophils, percent
}


def to_loinc(local_code: Optional[str]) -> Optional[str]:
    """Translates a known local/vendor code to its real LOINC code, or None
    if the code isn't in LOCAL_CODE_TO_LOINC -- "unknown," never a guess."""
    if not local_code:
        return None
    return LOCAL_CODE_TO_LOINC.get(local_code.strip().upper())


# --- CSV / LIS / middleware header synonyms -------------------------------
# Canonical field -> the header spellings a real feed might use for it.
# Scoped per ontology type: the same raw word ("status") can mean
# different things for different row shapes, so synonym resolution is
# only ever applied within one type's own vocabulary, never globally.
CSV_FIELD_SYNONYMS: dict[str, dict[str, tuple[str, ...]]] = {
    "Patient": {
        "patient_id": (
            "patient_id",
            "patientid",
            "mrn",
            "mrn_number",
            "medical_record_number",
            "patient_no",
            "patient_number",
        ),
        "first_name": ("first_name", "firstname", "given_name", "givenname"),
        "last_name": ("last_name", "lastname", "family_name", "surname"),
        "full_name": ("full_name", "fullname", "name", "patient_name"),
        "date_of_birth": ("date_of_birth", "dob", "birth_date", "birthdate"),
        "gender": ("gender", "gendercode", "sex"),
        "contact_number": (
            "contact_number",
            "contactnumber",
            "phone",
            "phone_number",
            "telephone",
            "mobile",
        ),
        "insurance_provider": ("insurance_provider", "insurer", "payer"),
        "insurance_number": ("insurance_number", "policy_number", "member_id"),
        "address": ("address", "home_address", "street_address"),
    },
    "Doctor": {
        "doctor_id": ("doctor_id", "doctorid", "physician_id", "provider_id", "npi"),
        "first_name": ("first_name", "firstname", "given_name"),
        "last_name": ("last_name", "lastname", "family_name", "surname"),
        "specialization": ("specialization", "specialty", "department"),
    },
    "LabResult": {
        "test_name": (
            "test_name",
            "testname",
            "test_description",
            "testdescription",
            "analyte",
            "test",
            "param_name",
        ),
        "test_code": (
            "test_code",
            "testcode",
            "analyte_code",
            "param_code",
            "loinc_code",
        ),
        "result": (
            "result",
            "value",
            "measurement",
            "val_numeric",
            "result_value",
        ),
        "unit": ("unit", "units", "unit_description", "uom"),
        "reference_range": (
            "reference_range",
            "ref_range",
            "range",
            "normal_range",
        ),
        "result_status": (
            "result_status",
            "status",
            "flag",
            "abnormal_flag",
            "result_flag",
        ),
    },
    "AccountHolder": {
        "holder_id": ("holder_id", "holderid", "customer_id", "client_id"),
        "national_id": ("national_id", "ssn", "tax_id", "govt_id"),
        "date_of_birth": ("date_of_birth", "dob", "birth_date"),
    },
    "Account": {
        "account_id": ("account_id", "accountid", "acct_no", "account_number"),
        "account_type": ("account_type", "accounttype", "acct_type"),
        "branch": ("branch", "branch_code", "branch_name"),
        "account_status": ("account_status", "status"),
    },
    "Transaction": {
        "transaction_id": ("transaction_id", "transactionid", "txn_id", "txn_no"),
        "account_id": ("account_id", "accountid", "acct_no"),
        "amount": ("amount", "txn_amount", "value"),
        "transaction_type": ("transaction_type", "txn_type", "type"),
    },
}


def resolve_synonyms(kv: dict[str, str], type_name: str) -> dict[str, str]:
    """
    Return `kv` augmented with canonical-field copies wherever a known
    header alias is present, for the given ontology type's synonym
    table. Additive only: never removes or overwrites an existing key,
    so a source that already speaks the canonical vocabulary (e.g. the
    existing hospital/banking CSV fixtures) is completely unaffected --
    this only fills gaps for header spellings the exact-match rules
    would otherwise silently drop.
    """
    table = CSV_FIELD_SYNONYMS.get(type_name)
    if not table:
        return kv
    out = dict(kv)
    for canonical, aliases in table.items():
        if canonical in out:
            continue
        for alias in aliases:
            if alias in kv and kv[alias]:
                out[canonical] = kv[alias]
                break
    return out
