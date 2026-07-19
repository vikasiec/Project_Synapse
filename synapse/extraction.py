"""
Rule-based schema-on-read extractors for Phase 1+.

No LLM required. Covers:
  - Service incidents (checkout-service pattern)
  - Customer / revenue (CRM vs Billing pattern)
  - Person / identity access (HR / IdP / ITSM)
  - Lab / IVD panel results (Test_Name / Result / Unit — clinical vertical)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from synapse.entity_resolution import EntityResolutionService
from synapse.fhir import (
    FhirParseError,
    bundle_resources,
    coding_display_and_code,
    first_identifier_value,
    human_name,
    looks_like_fhir,
    parse_fhir_resource,
    reference_range_string,
    resolve_local_reference,
)
from synapse.hl7v2 import Hl7ParseError, looks_like_hl7, parse_hl7_message
from synapse.models import Entity, Episode, Fact, RawObject
from synapse.ontology import OntologyRegistry
from synapse.store import SemanticStore
from synapse.temporal import TemporalService

VERSION_RE = re.compile(r"\bv(\d+\.\d+\.\d+)\b", re.IGNORECASE)
SERVICE_RE = re.compile(r"\b([a-z0-9-]+-service)\b", re.IGNORECASE)
CRASH_RE = re.compile(r"CrashLoopBackOff|crash loop", re.IGNORECASE)
BUILD_OK_RE = re.compile(r"BUILD SUCCESSFUL|deployed image tag", re.IGNORECASE)
MANUAL_BYPASS_RE = re.compile(r"manually bypassed|manual(?:ly)? .*v\d", re.IGNORECASE)
INCIDENT_RE = re.compile(r"\[Incident-(\d+)\]", re.IGNORECASE)

# Customer / revenue
CUSTOMER_RE = re.compile(
    r"(?:customer|client)\s*[:=]\s*[\"']?([A-Za-z0-9 .,&'-]+)[\"']?",
    re.IGNORECASE,
)
CUSTOMER_NAME_LINE_RE = re.compile(
    r"^(?:name|company)\s*[:=]\s*[\"']?([A-Za-z0-9 .,&'-]+)[\"']?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
REVENUE_RE = re.compile(
    r"(?:annual[_ ]?revenue|arr|revenue)\s*[:=]\s*\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
STATUS_RE = re.compile(
    r"(?:account[_ ]?status|status)\s*[:=]\s*([A-Za-z_]+)",
    re.IGNORECASE,
)

# Lab / IVD (CSV drop emits "Test_Name: Ferritin" style lines)
LAB_SIGNAL_RE = re.compile(
    r"(?:test[_ ]?name|analyte)\s*[:=]",
    re.IGNORECASE,
)

# HIS patient record (CSV drop emits "Patient_id: P001" style lines)
PATIENT_SIGNAL_RE = re.compile(
    r"patient[_ ]?id\s*[:=]",
    re.IGNORECASE,
)

# HIS doctor record
DOCTOR_SIGNAL_RE = re.compile(
    r"doctor[_ ]?id\s*[:=]",
    re.IGNORECASE,
)

# HIS appointment (scheduling) row — links Patient + Doctor
APPOINTMENT_SIGNAL_RE = re.compile(
    r"appointment[_ ]?id\s*[:=]",
    re.IGNORECASE,
)

# HIS treatment row — links to Appointment
TREATMENT_SIGNAL_RE = re.compile(
    r"treatment[_ ]?id\s*[:=]",
    re.IGNORECASE,
)

# HIS billing row — links to Patient + Treatment
BILLING_SIGNAL_RE = re.compile(
    r"bill[_ ]?id\s*[:=]",
    re.IGNORECASE,
)

# Banking account holder
HOLDER_SIGNAL_RE = re.compile(
    r"holder[_ ]?id\s*[:=]",
    re.IGNORECASE,
)

# Banking account — links to AccountHolder
ACCOUNT_SIGNAL_RE = re.compile(
    r"account[_ ]?id\s*[:=]",
    re.IGNORECASE,
)

# Banking ledger transaction — links to Account
TRANSACTION_SIGNAL_RE = re.compile(
    r"transaction[_ ]?id\s*[:=]",
    re.IGNORECASE,
)

# Person / identity
EMPLOYEE_RE = re.compile(
    r"(?:employee|user|person)\s*[:=]\s*[\"']?([A-Za-z][A-Za-z .'-]{1,60})[\"']?",
    re.IGNORECASE,
)
EMPLOYEE_INLINE_RE = re.compile(
    r"\bemployee\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b",
)
EMPLOYEE_ID_RE = re.compile(
    r"(?:employee[_ ]?id|emp[_ ]?id)\s*[:=]\s*([A-Za-z0-9-]+)",
    re.IGNORECASE,
)
EMPLOYEE_ID_PAREN_RE = re.compile(r"\(([A-Z]?-?\d{3,})\)")


@dataclass
class ExtractionResult:
    entity: Entity
    facts: list[Fact]


class RuleExtractor:
    def __init__(
        self,
        store: SemanticStore,
        *,
        ontology: Optional[OntologyRegistry] = None,
    ) -> None:
        self.store = store
        self.ontology = ontology or OntologyRegistry.default()
        self.er = EntityResolutionService(store, ontology=self.ontology)
        self.temporal = TemporalService(store)

    def extract_from_episode(self, episode: Episode, raw: RawObject) -> Optional[ExtractionResult]:
        text = episode.payload_text
        # HL7v2 messages are unambiguous (MSH segment first) — check before
        # any key:value-style pattern, since this text has no ":" at all.
        if looks_like_hl7(text):
            hl7 = self._extract_hl7_oru(episode, raw, text)
            if hl7 is not None:
                return hl7
        # FHIR is JSON, also unambiguous (no ":" key:value shape) — check
        # right alongside HL7, before any key:value-style pattern.
        if looks_like_fhir(text):
            fhir = self._extract_fhir_bundle(episode, raw, text)
            if fhir is not None:
                return fhir
        # Prefer service incident patterns when present
        if SERVICE_RE.search(text):
            return self._extract_service(episode, raw, text)
        # Lab panel / IVD before generic person/customer (Status: is shared vocabulary)
        if LAB_SIGNAL_RE.search(text) or self._looks_like_lab(text):
            lab = self._extract_lab(episode, raw, text)
            if lab is not None:
                return lab
        # HIS patient record — only when patient_id co-occurs with identity fields,
        # so appointment/billing/treatment rows (patient_id as foreign key only)
        # correctly fall through as "not yet extracted" rather than a broken entity.
        if PATIENT_SIGNAL_RE.search(text) and self._looks_like_patient(text):
            patient = self._extract_patient(episode, raw, text)
            if patient is not None:
                return patient
        if DOCTOR_SIGNAL_RE.search(text) and self._looks_like_doctor(text):
            doctor = self._extract_doctor(episode, raw, text)
            if doctor is not None:
                return doctor
        if APPOINTMENT_SIGNAL_RE.search(text) and self._looks_like_appointment(text):
            appt = self._extract_appointment(episode, raw, text)
            if appt is not None:
                return appt
        if TREATMENT_SIGNAL_RE.search(text) and self._looks_like_treatment(text):
            treatment = self._extract_treatment(episode, raw, text)
            if treatment is not None:
                return treatment
        if BILLING_SIGNAL_RE.search(text) and self._looks_like_billing(text):
            bill = self._extract_billing(episode, raw, text)
            if bill is not None:
                return bill
        if HOLDER_SIGNAL_RE.search(text) and self._looks_like_holder(text):
            holder = self._extract_holder(episode, raw, text)
            if holder is not None:
                return holder
        if ACCOUNT_SIGNAL_RE.search(text) and self._looks_like_account(text):
            account = self._extract_account(episode, raw, text)
            if account is not None:
                return account
        if TRANSACTION_SIGNAL_RE.search(text) and self._looks_like_transaction(text):
            txn = self._extract_transaction(episode, raw, text)
            if txn is not None:
                return txn
        if (
            EMPLOYEE_RE.search(text)
            or EMPLOYEE_INLINE_RE.search(text)
            or EMPLOYEE_ID_RE.search(text)
        ):
            return self._extract_person(episode, raw, text)
        if CUSTOMER_RE.search(text) or CUSTOMER_NAME_LINE_RE.search(text) or REVENUE_RE.search(text):
            return self._extract_customer(episode, raw, text)
        return None

    @staticmethod
    def _parse_kv(text: str) -> dict[str, str]:
        """Parse key: value lines (CSV connector format)."""
        out: dict[str, str] = {}
        for line in (text or "").splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            k = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
            v = val.strip()
            if k and v:
                out[k] = v
        return out

    @staticmethod
    def _looks_like_lab(text: str) -> bool:
        kv = RuleExtractor._parse_kv(text)
        keys = set(kv.keys())
        # Need test name + result-like field
        has_test = bool(keys & {"test_name", "analyte", "test"})
        has_result = bool(keys & {"result", "value", "measurement"})
        return has_test and has_result

    @staticmethod
    def _looks_like_patient(text: str) -> bool:
        kv = RuleExtractor._parse_kv(text)
        keys = set(kv.keys())
        has_id = "patient_id" in keys
        has_identity = bool(
            keys & {"first_name", "last_name", "insurance_provider", "date_of_birth"}
        )
        return has_id and has_identity

    @staticmethod
    def _looks_like_doctor(text: str) -> bool:
        kv = RuleExtractor._parse_kv(text)
        keys = set(kv.keys())
        has_id = "doctor_id" in keys
        has_identity = bool(keys & {"first_name", "last_name", "specialization"})
        return has_id and has_identity

    @staticmethod
    def _looks_like_appointment(text: str) -> bool:
        kv = RuleExtractor._parse_kv(text)
        keys = set(kv.keys())
        has_id = "appointment_id" in keys
        has_link = bool(keys & {"patient_id", "doctor_id"})
        return has_id and has_link

    @staticmethod
    def _looks_like_treatment(text: str) -> bool:
        kv = RuleExtractor._parse_kv(text)
        keys = set(kv.keys())
        # treatment_id alone is ambiguous with billing.csv (which also has
        # treatment_id as a foreign key) — appointment_id disambiguates.
        return "treatment_id" in keys and "appointment_id" in keys

    @staticmethod
    def _looks_like_billing(text: str) -> bool:
        kv = RuleExtractor._parse_kv(text)
        return "bill_id" in kv

    @staticmethod
    def _looks_like_holder(text: str) -> bool:
        kv = RuleExtractor._parse_kv(text)
        keys = set(kv.keys())
        has_id = "holder_id" in keys
        has_identity = bool(
            keys & {"first_name", "last_name", "national_id", "date_of_birth"}
        )
        return has_id and has_identity

    @staticmethod
    def _looks_like_account(text: str) -> bool:
        kv = RuleExtractor._parse_kv(text)
        keys = set(kv.keys())
        # accounts.csv only — transactions.csv also has account_id (as a
        # foreign key) but never these account-attribute columns.
        has_id = "account_id" in keys
        has_attrs = bool(keys & {"account_type", "branch", "status"})
        return has_id and has_attrs

    @staticmethod
    def _looks_like_transaction(text: str) -> bool:
        kv = RuleExtractor._parse_kv(text)
        return "transaction_id" in kv

    def _extract_lab(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        """
        Clinical lab / IVD panel row → LabResult entity + structured facts.

        Aligns with master doc multi-domain schema-on-read: new vertical without
        warehouse ETL — Path A deterministic parsers for known key clusters.
        """
        kv = self._parse_kv(text)
        test_name = (
            kv.get("test_name")
            or kv.get("analyte")
            or kv.get("test")
            or ""
        ).strip()
        if not test_name:
            return None

        # Canonical entity name = analyte; ER collapses same test across rows
        entity = self.er.get_or_create(
            "LabResult",
            test_name,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=test_name.lower(),
            trust_score=0.75,
            domain=episode.domain if episode.domain else "clinical_lab",
        )

        facts: list[Fact] = []
        result_val = kv.get("result") or kv.get("value") or kv.get("measurement")
        if result_val is not None and str(result_val).strip() != "":
            # Prefer numeric when possible for conflict detection
            obj: Any = result_val.strip()
            try:
                obj = float(str(result_val).replace(",", ""))
            except ValueError:
                pass
            facts.append(self._fact(entity, "result", obj, 0.92, raw, episode))

        unit = kv.get("unit") or kv.get("unit_description")
        if unit:
            facts.append(self._fact(entity, "unit", unit.strip(), 0.9, raw, episode))

        ref = kv.get("reference_range") or kv.get("ref_range") or kv.get("range")
        if ref:
            facts.append(
                self._fact(entity, "reference_range", ref.strip(), 0.88, raw, episode)
            )

        # Lab status (Normal/Abnormal/…) — not account_status
        lab_status = kv.get("status") or kv.get("result_status") or kv.get("flag")
        if lab_status:
            facts.append(
                self._fact(
                    entity,
                    "result_status",
                    lab_status.strip(),
                    0.9,
                    raw,
                    episode,
                )
            )

        comment = kv.get("comment") or kv.get("notes") or kv.get("recommended_followup")
        if comment:
            facts.append(
                self._fact(entity, "comment", comment.strip()[:500], 0.7, raw, episode)
            )

        test_date = kv.get("date") or kv.get("test_date") or kv.get("collected_at")
        if test_date:
            facts.append(
                self._fact(entity, "test_date", test_date.strip(), 0.85, raw, episode)
            )

        if not facts:
            return None

        for f in facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(entity.entity_id)
        return ExtractionResult(entity=entity, facts=facts)

    def _extract_patient(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        """
        HIS patient record row -> Patient entity + structured facts.

        Own storage_type/ontology family (never ER-merges with employee
        identity Person) — same-name patient and employee must stay distinct.
        """
        kv = self._parse_kv(text)
        patient_id = kv.get("patient_id", "").strip()
        first = kv.get("first_name", "").strip()
        last = kv.get("last_name", "").strip()
        name = f"{first} {last}".strip() or patient_id
        if not patient_id or not name:
            return None

        entity = self.er.get_or_create(
            "Patient",
            name,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=patient_id,
            trust_score=0.8,
            domain=episode.domain if episode.domain else "hospital_ops",
        )

        facts: list[Fact] = []
        field_map = {
            "date_of_birth": "date_of_birth",
            "gender": "gender",
            "contact_number": "contact_number",
            "address": "address",
            "registration_date": "registration_date",
            "insurance_provider": "insurance_provider",
            "insurance_number": "insurance_number",
            "email": "email",
        }
        for kv_key, predicate in field_map.items():
            val = kv.get(kv_key)
            if val:
                facts.append(self._fact(entity, predicate, val.strip(), 0.9, raw, episode))

        if not facts:
            return None

        for f in facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(entity.entity_id)
        return ExtractionResult(entity=entity, facts=facts)

    def _extract_doctor(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        """HIS doctor record row -> Doctor entity + structured facts."""
        kv = self._parse_kv(text)
        doctor_id = kv.get("doctor_id", "").strip()
        first = kv.get("first_name", "").strip()
        last = kv.get("last_name", "").strip()
        name = f"{first} {last}".strip() or doctor_id
        if not doctor_id or not name:
            return None

        entity = self.er.get_or_create(
            "Doctor",
            name,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=doctor_id,
            trust_score=0.8,
            domain=episode.domain if episode.domain else "hospital_ops",
        )

        facts: list[Fact] = []
        field_map = {
            "specialization": "specialization",
            "phone_number": "phone_number",
            "years_experience": "years_experience",
            "hospital_branch": "hospital_branch",
            "email": "email",
        }
        for kv_key, predicate in field_map.items():
            val = kv.get(kv_key)
            if val:
                facts.append(self._fact(entity, predicate, val.strip(), 0.9, raw, episode))

        if not facts:
            return None

        for f in facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(entity.entity_id)
        return ExtractionResult(entity=entity, facts=facts)

    def _extract_appointment(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        """
        HIS scheduling row -> Appointment entity, resolving Patient/Doctor
        entity ids by external id when they've already landed (best-effort;
        an unresolved link is still an honest partial result, not a failure).
        """
        kv = self._parse_kv(text)
        appointment_id = kv.get("appointment_id", "").strip()
        if not appointment_id:
            return None

        entity = self.er.get_or_create(
            "Appointment",
            appointment_id,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=appointment_id,
            trust_score=0.8,
            domain=episode.domain if episode.domain else "hospital_ops",
        )

        facts: list[Fact] = []
        field_map = {
            "appointment_date": "appointment_date",
            "appointment_time": "appointment_time",
            "reason_for_visit": "reason_for_visit",
            "status": "appointment_status",
        }
        for kv_key, predicate in field_map.items():
            val = kv.get(kv_key)
            if val:
                facts.append(self._fact(entity, predicate, val.strip(), 0.9, raw, episode))

        patient_id = kv.get("patient_id", "").strip()
        if patient_id:
            facts.append(self._fact(entity, "patient_id", patient_id, 0.9, raw, episode))
            patient_ent = self.er.find_by_external_id_value(
                patient_id, entity_type="Patient"
            )
            if patient_ent:
                facts.append(
                    self._fact(
                        entity, "patient_entity_id", patient_ent.entity_id, 0.85, raw, episode
                    )
                )

        doctor_id = kv.get("doctor_id", "").strip()
        if doctor_id:
            facts.append(self._fact(entity, "doctor_id", doctor_id, 0.9, raw, episode))
            doctor_ent = self.er.find_by_external_id_value(
                doctor_id, entity_type="Doctor"
            )
            if doctor_ent:
                facts.append(
                    self._fact(
                        entity, "doctor_entity_id", doctor_ent.entity_id, 0.85, raw, episode
                    )
                )

        if not facts:
            return None

        for f in facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(entity.entity_id)
        return ExtractionResult(entity=entity, facts=facts)

    def _extract_treatment(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        """HIS treatment row -> Treatment entity, resolving the Appointment
        entity id by external id when it has already landed."""
        kv = self._parse_kv(text)
        treatment_id = kv.get("treatment_id", "").strip()
        if not treatment_id:
            return None

        entity = self.er.get_or_create(
            "Treatment",
            treatment_id,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=treatment_id,
            trust_score=0.8,
            domain=episode.domain if episode.domain else "hospital_ops",
        )

        facts: list[Fact] = []
        field_map = {
            "treatment_type": "treatment_type",
            "description": "description",
            "cost": "cost",
            "treatment_date": "treatment_date",
        }
        for kv_key, predicate in field_map.items():
            val = kv.get(kv_key)
            if val:
                facts.append(self._fact(entity, predicate, val.strip(), 0.9, raw, episode))

        appointment_id = kv.get("appointment_id", "").strip()
        if appointment_id:
            facts.append(
                self._fact(entity, "appointment_id", appointment_id, 0.9, raw, episode)
            )
            appt_ent = self.er.find_by_external_id_value(
                appointment_id, entity_type="Appointment"
            )
            if appt_ent:
                facts.append(
                    self._fact(
                        entity, "appointment_entity_id", appt_ent.entity_id, 0.85, raw, episode
                    )
                )

        if not facts:
            return None

        for f in facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(entity.entity_id)
        return ExtractionResult(entity=entity, facts=facts)

    def _extract_billing(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        """HIS billing row -> Billing entity, resolving Patient + Treatment
        entity ids by external id when they've already landed."""
        kv = self._parse_kv(text)
        bill_id = kv.get("bill_id", "").strip()
        if not bill_id:
            return None

        entity = self.er.get_or_create(
            "Billing",
            bill_id,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=bill_id,
            trust_score=0.8,
            domain=episode.domain if episode.domain else "hospital_ops",
        )

        facts: list[Fact] = []
        field_map = {
            "bill_date": "bill_date",
            "amount": "amount",
            "payment_method": "payment_method",
            "payment_status": "payment_status",
        }
        for kv_key, predicate in field_map.items():
            val = kv.get(kv_key)
            if val:
                facts.append(self._fact(entity, predicate, val.strip(), 0.9, raw, episode))

        patient_id = kv.get("patient_id", "").strip()
        if patient_id:
            facts.append(self._fact(entity, "patient_id", patient_id, 0.9, raw, episode))
            patient_ent = self.er.find_by_external_id_value(
                patient_id, entity_type="Patient"
            )
            if patient_ent:
                facts.append(
                    self._fact(
                        entity, "patient_entity_id", patient_ent.entity_id, 0.85, raw, episode
                    )
                )

        treatment_id = kv.get("treatment_id", "").strip()
        if treatment_id:
            facts.append(self._fact(entity, "treatment_id", treatment_id, 0.9, raw, episode))
            treatment_ent = self.er.find_by_external_id_value(
                treatment_id, entity_type="Treatment"
            )
            if treatment_ent:
                facts.append(
                    self._fact(
                        entity,
                        "treatment_entity_id",
                        treatment_ent.entity_id,
                        0.85,
                        raw,
                        episode,
                    )
                )

        if not facts:
            return None

        for f in facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(entity.entity_id)
        return ExtractionResult(entity=entity, facts=facts)

    def _extract_holder(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        """Bank account-holder row -> AccountHolder entity + facts."""
        kv = self._parse_kv(text)
        holder_id = kv.get("holder_id", "").strip()
        first = kv.get("first_name", "").strip()
        last = kv.get("last_name", "").strip()
        name = f"{first} {last}".strip() or holder_id
        if not holder_id or not name:
            return None

        entity = self.er.get_or_create(
            "AccountHolder",
            name,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=holder_id,
            trust_score=0.8,
            domain=episode.domain if episode.domain else "banking",
        )

        facts: list[Fact] = []
        field_map = {
            "date_of_birth": "date_of_birth",
            "national_id": "national_id",
            "email": "email",
            "phone": "phone",
            "address": "address",
            "registration_date": "registration_date",
        }
        for kv_key, predicate in field_map.items():
            val = kv.get(kv_key)
            if val:
                facts.append(self._fact(entity, predicate, val.strip(), 0.9, raw, episode))

        if not facts:
            return None

        for f in facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(entity.entity_id)
        return ExtractionResult(entity=entity, facts=facts)

    def _extract_account(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        """Bank account row -> Account entity, resolving the AccountHolder
        entity id by external id when it has already landed."""
        kv = self._parse_kv(text)
        account_id = kv.get("account_id", "").strip()
        if not account_id:
            return None

        entity = self.er.get_or_create(
            "Account",
            account_id,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=account_id,
            trust_score=0.8,
            domain=episode.domain if episode.domain else "banking",
        )

        facts: list[Fact] = []
        field_map = {
            "account_type": "account_type",
            "branch": "branch",
            "opened_date": "opened_date",
            "status": "account_status",
        }
        for kv_key, predicate in field_map.items():
            val = kv.get(kv_key)
            if val:
                facts.append(self._fact(entity, predicate, val.strip(), 0.9, raw, episode))

        holder_id = kv.get("holder_id", "").strip()
        if holder_id:
            facts.append(self._fact(entity, "holder_id", holder_id, 0.9, raw, episode))
            holder_ent = self.er.find_by_external_id_value(
                holder_id, entity_type="AccountHolder"
            )
            if holder_ent:
                facts.append(
                    self._fact(
                        entity, "holder_entity_id", holder_ent.entity_id, 0.85, raw, episode
                    )
                )

        if not facts:
            return None

        for f in facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(entity.entity_id)
        return ExtractionResult(entity=entity, facts=facts)

    def _extract_transaction(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        """Bank ledger row -> Transaction entity, resolving the Account
        entity id by external id when it has already landed."""
        kv = self._parse_kv(text)
        transaction_id = kv.get("transaction_id", "").strip()
        if not transaction_id:
            return None

        entity = self.er.get_or_create(
            "Transaction",
            transaction_id,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=transaction_id,
            trust_score=0.85,
            domain=episode.domain if episode.domain else "banking",
        )

        facts: list[Fact] = []
        field_map = {
            "transaction_date": "transaction_date",
            "amount": "amount",
            "transaction_type": "transaction_type",
            "description": "description",
            "balance_after": "balance_after",
        }
        for kv_key, predicate in field_map.items():
            val = kv.get(kv_key)
            if val:
                facts.append(self._fact(entity, predicate, val.strip(), 0.9, raw, episode))

        account_id = kv.get("account_id", "").strip()
        if account_id:
            facts.append(self._fact(entity, "account_id", account_id, 0.9, raw, episode))
            account_ent = self.er.find_by_external_id_value(
                account_id, entity_type="Account"
            )
            if account_ent:
                facts.append(
                    self._fact(
                        entity, "account_entity_id", account_ent.entity_id, 0.85, raw, episode
                    )
                )

        if not facts:
            return None

        for f in facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(entity.entity_id)
        return ExtractionResult(entity=entity, facts=facts)

    def _extract_hl7_oru(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        """
        HL7v2 ORU^R01 (observation result) message -> a Patient entity
        (reusing the existing Patient type, cross-domain: the same patient
        identity concept whether it arrives via a hospital_ops CSV or a
        clinical_lab HL7 feed) plus one LabResult entity per OBX segment,
        each linked back to the patient. Scoped to ORU^R01 only — other
        message types fall through as "not yet extracted", honestly.
        """
        try:
            msg = parse_hl7_message(text)
        except Hl7ParseError:
            return None

        msh = msg.first("MSH")
        if msh is None or msh.value(9, 1) != "ORU" or msh.value(9, 2) != "R01":
            return None

        pid = msg.first("PID")
        if pid is None:
            return None
        patient_id = pid.value(3, 1)
        last = pid.value(5, 1)
        first = pid.value(5, 2)
        name = f"{first} {last}".strip() or patient_id
        if not patient_id or not name:
            return None

        patient = self.er.get_or_create(
            "Patient",
            name,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=patient_id,
            trust_score=0.85,
            domain="hospital_ops",
        )
        all_facts: list[Fact] = []
        dob = pid.value(7)
        if dob:
            all_facts.append(self._fact(patient, "date_of_birth", dob, 0.9, raw, episode))
        gender = pid.value(8)
        if gender:
            all_facts.append(self._fact(patient, "gender", gender, 0.9, raw, episode))

        for obx in msg.get("OBX"):
            test_code = obx.value(3, 1)
            test_name = obx.value(3, 2) or test_code
            if not test_name:
                continue

            # Codex review finding 3: a bare test-name/code key (e.g. "hgb")
            # would let two different patients' results silently converge
            # into one shared entity -- clinically wrong, and it produces a
            # false conflict (their two values look like a disagreement
            # about "the" Hemoglobin result instead of two people's actual,
            # unrelated results). Scope the identity key by patient so each
            # patient's occurrence of a test stays its own entity, same
            # strict_identity pattern already proven for Patient (task 4).
            result_key = f"{patient_id}:{test_code or test_name}".lower()
            result = self.er.get_or_create(
                "LabResult",
                test_name,
                source_system=raw.source_system,
                acl_tags=list(raw.acl_tags),
                external_id=result_key,
                trust_score=0.8,
                domain="clinical_lab",
            )

            value = obx.value(5)
            if value:
                obj: Any = value
                try:
                    obj = float(value)
                except ValueError:
                    pass
                all_facts.append(self._fact(result, "result", obj, 0.92, raw, episode))
            unit = obx.value(6)
            if unit:
                all_facts.append(self._fact(result, "unit", unit, 0.9, raw, episode))
            ref_range = obx.value(7)
            if ref_range:
                all_facts.append(
                    self._fact(result, "reference_range", ref_range, 0.88, raw, episode)
                )
            flag = obx.value(8)
            if flag:
                all_facts.append(self._fact(result, "abnormal_flag", flag, 0.9, raw, episode))
            status = obx.value(11)
            if status:
                all_facts.append(
                    self._fact(result, "result_status", status, 0.9, raw, episode)
                )

            all_facts.append(self._fact(result, "patient_id", patient_id, 0.9, raw, episode))
            all_facts.append(
                self._fact(result, "patient_entity_id", patient.entity_id, 0.85, raw, episode)
            )

        if not all_facts:
            return None

        for f in all_facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(patient.entity_id)
        return ExtractionResult(entity=patient, facts=all_facts)

    def _extract_fhir_bundle(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        """
        FHIR Bundle (Patient + Observation resources) -> a Patient entity
        plus one LabResult entity per Observation, linked back to the
        patient. The FHIR analogue of an HL7v2 ORU^R01 message. Scoped to
        Bundle-of-inline-resources only -- no external reference fetching,
        no `contained` resources.

        LabResult identity is scoped by patient_id from the start here
        (Active_File.md task 13/Codex's review found this the hard way for
        the HL7 path -- applying it proactively this time, not after a
        cross-patient conflation bug).
        """
        try:
            data = parse_fhir_resource(text)
        except FhirParseError:
            return None
        if data.get("resourceType") != "Bundle":
            return None

        resources = bundle_resources(data)
        patient_res = next(
            (r for r in resources if r.get("resourceType") == "Patient"), None
        )
        if patient_res is None:
            return None

        patient_id = first_identifier_value(patient_res)
        family, given = human_name(patient_res)
        name = f"{given} {family}".strip() or patient_id
        if not patient_id or not name:
            return None

        patient = self.er.get_or_create(
            "Patient",
            name,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=patient_id,
            trust_score=0.85,
            domain="hospital_ops",
        )
        all_facts: list[Fact] = []
        dob = patient_res.get("birthDate")
        if dob:
            all_facts.append(self._fact(patient, "date_of_birth", dob, 0.9, raw, episode))
        gender = patient_res.get("gender")
        if gender:
            all_facts.append(self._fact(patient, "gender", gender, 0.9, raw, episode))

        for obs in resources:
            if obs.get("resourceType") != "Observation":
                continue
            subject = resolve_local_reference(
                resources, (obs.get("subject") or {}).get("reference")
            )
            if subject is not patient_res:
                # Observation for a different/unresolvable subject in this
                # bundle -- do not attribute it to this patient by accident.
                continue

            test_name, test_code = coding_display_and_code(obs.get("code"))
            if not test_name:
                continue

            result_key = f"{patient_id}:{test_code or test_name}".lower()
            result = self.er.get_or_create(
                "LabResult",
                test_name,
                source_system=raw.source_system,
                acl_tags=list(raw.acl_tags),
                external_id=result_key,
                trust_score=0.8,
                domain="clinical_lab",
            )

            qty = obs.get("valueQuantity") or {}
            value = qty.get("value")
            if value is not None:
                all_facts.append(self._fact(result, "result", value, 0.92, raw, episode))
            unit = qty.get("unit")
            if unit:
                all_facts.append(self._fact(result, "unit", unit, 0.9, raw, episode))
            ref_range = reference_range_string(obs)
            if ref_range:
                all_facts.append(
                    self._fact(result, "reference_range", ref_range, 0.88, raw, episode)
                )
            status = obs.get("status")
            if status:
                all_facts.append(
                    self._fact(result, "result_status", status, 0.9, raw, episode)
                )
            interp_display, interp_code = coding_display_and_code(
                (obs.get("interpretation") or [{}])[0]
                if obs.get("interpretation")
                else None
            )
            if interp_code:
                all_facts.append(
                    self._fact(result, "abnormal_flag", interp_code, 0.9, raw, episode)
                )

            all_facts.append(self._fact(result, "patient_id", patient_id, 0.9, raw, episode))
            all_facts.append(
                self._fact(result, "patient_entity_id", patient.entity_id, 0.85, raw, episode)
            )

        if not all_facts:
            return None

        for f in all_facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(patient.entity_id)
        return ExtractionResult(entity=patient, facts=all_facts)

    def _extract_service(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        service_match = SERVICE_RE.search(text)
        if not service_match:
            return None

        service_name = service_match.group(1).lower()
        entity = self.er.get_or_create(
            "Service",
            service_name,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=service_name,
            domain=episode.domain,
        )

        facts: list[Fact] = []
        versions = VERSION_RE.findall(text)

        if BUILD_OK_RE.search(text) and versions:
            facts.append(
                self._fact(
                    entity,
                    "deployed_version",
                    f"v{versions[0]}",
                    0.95,
                    raw,
                    episode,
                )
            )
            facts.append(
                self._fact(
                    entity,
                    "current_version",
                    f"v{versions[0]}",
                    0.90,
                    raw,
                    episode,
                )
            )
            facts.append(
                self._fact(entity, "deploy_status", "success", 0.95, raw, episode)
            )

        if CRASH_RE.search(text):
            facts.append(
                self._fact(
                    entity, "runtime_state", "CrashLoopBackOff", 0.98, raw, episode
                )
            )
            if versions:
                active = versions[-1]
                facts.append(
                    self._fact(
                        entity,
                        "current_version",
                        f"v{active}",
                        0.98,
                        raw,
                        episode,
                    )
                )

        if MANUAL_BYPASS_RE.search(text) and versions:
            facts.append(
                self._fact(
                    entity,
                    "current_version",
                    f"v{versions[-1]}",
                    0.85,
                    raw,
                    episode,
                )
            )
            facts.append(
                self._fact(entity, "change_method", "manual_bypass", 0.9, raw, episode)
            )

        incident = INCIDENT_RE.search(text)
        if incident:
            facts.append(
                self._fact(
                    entity,
                    "related_incident",
                    f"Incident-{incident.group(1)}",
                    0.9,
                    raw,
                    episode,
                )
            )

        for f in facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(entity.entity_id)
        return ExtractionResult(entity=entity, facts=facts)

    def _extract_customer(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        name = None
        m = CUSTOMER_RE.search(text)
        if m:
            name = m.group(1).strip().strip("\"'")
        if not name:
            m2 = CUSTOMER_NAME_LINE_RE.search(text)
            if m2:
                name = m2.group(1).strip().strip("\"'")
        if not name:
            # last resort: line after Customer
            m3 = re.search(r"Customer\s+([A-Za-z0-9 .,&'-]{2,60})", text, re.I)
            if m3:
                name = m3.group(1).strip()

        if not name:
            return None

        entity = self.er.get_or_create(
            "Customer",
            name,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=name,
            trust_score=0.65,
            domain=episode.domain,
        )

        facts: list[Fact] = []
        rev = REVENUE_RE.search(text)
        if rev:
            amount = float(rev.group(1).replace(",", ""))
            # Normalize predicate to annual_revenue for conflict detection
            facts.append(
                self._fact(entity, "annual_revenue", amount, 0.9, raw, episode)
            )

        st = STATUS_RE.search(text)
        if st:
            facts.append(
                self._fact(
                    entity,
                    "account_status",
                    st.group(1).lower(),
                    0.85,
                    raw,
                    episode,
                )
            )

        for f in facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(entity.entity_id)
        return ExtractionResult(entity=entity, facts=facts)

    def _extract_person(
        self, episode: Episode, raw: RawObject, text: str
    ) -> Optional[ExtractionResult]:
        name = None
        m = EMPLOYEE_RE.search(text)
        if m:
            name = m.group(1).strip().strip("\"'")
        if not name:
            m2 = EMPLOYEE_INLINE_RE.search(text)
            if m2:
                name = m2.group(1).strip()
        if not name:
            return None

        # Drop trailing noise from capture
        name = re.sub(r"\s+for\b.*$", "", name, flags=re.I).strip()
        name = re.split(r"\s+pending\b", name, maxsplit=1, flags=re.I)[0].strip()

        emp_id = None
        mid = EMPLOYEE_ID_RE.search(text)
        if mid:
            emp_id = mid.group(1).strip()
        else:
            mpar = EMPLOYEE_ID_PAREN_RE.search(text)
            if mpar:
                emp_id = mpar.group(1).strip()

        # Prefer external_id = employee_id for cross-system ER
        entity = self.er.get_or_create(
            "Person",
            name,
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            external_id=emp_id or name,
            trust_score=0.7,
            domain=episode.domain,
        )
        # Also index global employee_id key if present
        if emp_id:
            self.er.get_or_create(
                "Person",
                name,
                source_system="employee_id",
                acl_tags=list(raw.acl_tags),
                external_id=emp_id,
                domain=episode.domain,
            )

        facts: list[Fact] = []
        if emp_id:
            facts.append(self._fact(entity, "employee_id", emp_id, 0.95, raw, episode))

        st = STATUS_RE.search(text)
        if st:
            status = st.group(1).lower()
            # normalize
            if status in {"deprovisioned", "disabled", "terminated", "inactive"}:
                status = "deprovisioned" if status != "inactive" else "inactive"
            facts.append(self._fact(entity, "account_status", status, 0.92, raw, episode))

        for f in facts:
            self.store.put_fact(f)
        self.temporal.apply_for_entity(entity.entity_id)
        return ExtractionResult(entity=entity, facts=facts)

    def _fact(
        self,
        entity: Entity,
        predicate: str,
        obj,
        confidence: float,
        raw: RawObject,
        episode: Episode,
    ) -> Fact:
        return Fact.create(
            entity.entity_id,
            predicate,
            obj,
            confidence=confidence,
            evidence_refs=[raw.object_id, episode.episode_id],
            source_system=raw.source_system,
            acl_tags=list(raw.acl_tags),
            valid_from=raw.ingested_at,
        )
