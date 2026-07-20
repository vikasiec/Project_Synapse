"""
Layered ontology registry (org-wide design H8).

L0 — universal types (Person, Org, Asset, Event, Document, Service)
L1 — domain packs (Billing, Infra, Support, Identity)
L2 — team extensions (soft; low trust until promoted)

Load-bearing roles (not decoration-only):
  - govern_extract() maps extractor types → storage type + ontology type/layer
  - compatible_types() for ER blocking across L0/L1 families
  - predicate_source_boost() for domain-overlap conflict ranking
  - is_predicate_in_scope() for soft validation of facts vs type
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class OntologyType:
    name: str
    layer: str  # L0 | L1 | L2
    domain: Optional[str] = None
    parent: Optional[str] = None
    predicates: tuple[str, ...] = ()
    description: str = ""
    # Types where a name collision must NEVER cause a silent merge (e.g. two
    # different real patients sharing a name are two different people — a
    # missing external_id match must create a new entity, not fall back to
    # name-blocking). Default False preserves existing merge behavior for
    # Service/Customer/Person/etc.
    strict_identity: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GovernedType:
    """Result of governing an extractor type for a domain episode."""

    storage_type: str  # stable ER key: Service | Customer | Person | …
    ontology_type: str  # L0/L1 name e.g. InfraService
    ontology_layer: str  # L0 | L1 | L2
    domain: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Universal L0
_L0: list[OntologyType] = [
    OntologyType("Person", "L0", predicates=("account_status", "email", "title"), description="Natural person"),
    OntologyType("Org", "L0", predicates=("annual_revenue", "legal_name", "industry"), description="Organization"),
    OntologyType("Asset", "L0", predicates=("owner", "status"), description="Managed asset"),
    OntologyType(
        "Service",
        "L0",
        parent="Asset",
        predicates=("current_version", "deploy_status", "runtime_state", "deployed_version", "change_method"),
        description="Runtime service",
    ),
    OntologyType("Event", "L0", predicates=("severity", "related_incident"), description="Incident or change event"),
    OntologyType("Document", "L0", predicates=("title", "section"), description="Structured document"),
]

# Domain L1 packs
_L1: list[OntologyType] = [
    OntologyType(
        "InfraService",
        "L1",
        domain="infra_ops",
        parent="Service",
        predicates=("current_version", "deployed_version", "deploy_status", "runtime_state", "change_method", "related_incident"),
        description="Deployed service under SRE",
    ),
    OntologyType(
        "BillingAccount",
        "L1",
        domain="revenue",
        parent="Org",
        predicates=("annual_revenue", "billing_plan", "arr"),
        description="Customer in CRM/Billing",
    ),
    OntologyType(
        "IdentityPrincipal",
        "L1",
        domain="identity",
        parent="Person",
        predicates=("account_status", "mfa_enabled", "last_login"),
        description="Workforce identity subject",
    ),
    OntologyType(
        "SupportTicket",
        "L1",
        domain="support",
        parent="Event",
        predicates=("ticket_status", "priority", "related_incident"),
        description="Support / ITSM ticket",
    ),
    OntologyType(
        "LabResult",
        "L1",
        domain="clinical_lab",
        parent="Event",
        strict_identity=True,
        predicates=(
            "result",
            "observation_instance_id",
            "unit",
            "reference_range",
            "result_status",
            "comment",
            "test_date",
            "abnormal_flag",
            "patient_id",
            "patient_entity_id",
        ),
        description="IVD / lab panel analyte result (schema-on-read clinical vertical). "
        "Sourced from CSV drop or HL7v2 ORU messages -- patient_id/patient_entity_id "
        "populated only for the HL7 path.",
    ),
    OntologyType(
        "Patient",
        "L1",
        domain="hospital_ops",
        parent="Person",
        strict_identity=True,
        predicates=(
            "date_of_birth",
            "gender",
            "contact_number",
            "address",
            "registration_date",
            "insurance_provider",
            "insurance_number",
            "email",
        ),
        description="HIS patient record (own family — never ER-merged with employee/identity Person)",
    ),
    OntologyType(
        "Doctor",
        "L1",
        domain="hospital_ops",
        parent="Person",
        strict_identity=True,
        predicates=(
            "specialization",
            "phone_number",
            "years_experience",
            "hospital_branch",
            "email",
        ),
        description="HIS doctor record (own family — strict identity: doctor name collisions are realistic at scale)",
    ),
    OntologyType(
        "Appointment",
        "L1",
        domain="hospital_ops",
        parent="Event",
        predicates=(
            "appointment_date",
            "appointment_time",
            "reason_for_visit",
            "appointment_status",
            "patient_id",
            "doctor_id",
            "patient_entity_id",
            "doctor_entity_id",
        ),
        description="HIS scheduling row — links Patient and Doctor entities when both are resolvable",
    ),
    OntologyType(
        "Treatment",
        "L1",
        domain="hospital_ops",
        parent="Event",
        predicates=(
            "treatment_type",
            "description",
            "cost",
            "treatment_date",
            "appointment_id",
            "appointment_entity_id",
        ),
        description="HIS treatment row — links to the Appointment it was performed under",
    ),
    OntologyType(
        "Billing",
        "L1",
        domain="hospital_ops",
        parent="Event",
        predicates=(
            "bill_date",
            "amount",
            "payment_method",
            "payment_status",
            "patient_id",
            "treatment_id",
            "patient_entity_id",
            "treatment_entity_id",
        ),
        description="HIS billing row — links to Patient and the Treatment it charges for",
    ),
    OntologyType(
        "AccountHolder",
        "L1",
        domain="banking",
        parent="Person",
        strict_identity=True,
        predicates=(
            "date_of_birth",
            "national_id",
            "email",
            "phone",
            "address",
            "registration_date",
        ),
        description="Bank account holder (own family — strict identity: two different real "
        "holders can and do share a name)",
    ),
    OntologyType(
        "Account",
        "L1",
        domain="banking",
        parent="Asset",
        predicates=(
            "account_type",
            "branch",
            "opened_date",
            "account_status",
            "holder_id",
            "holder_entity_id",
        ),
        description="Bank account — links to the AccountHolder it belongs to",
    ),
    OntologyType(
        "Transaction",
        "L1",
        domain="banking",
        parent="Event",
        predicates=(
            "transaction_date",
            "amount",
            "transaction_type",
            "description",
            "balance_after",
            "account_id",
            "account_entity_id",
        ),
        description="Bank ledger transaction — links to the Account it was posted against",
    ),
]

# Domain-overlap: prefer SoR for regulated predicates (additive to Ar in Wv)
# Values are modest boosts so source Ar still dominates.
PREDICATE_SOURCE_BOOST: dict[str, dict[str, float]] = {
    "annual_revenue": {"Billing-Zuora": 0.12, "CRM-Salesforce": 0.04},
    "arr": {"Billing-Zuora": 0.12, "CRM-Salesforce": 0.04},
    "account_status": {"IdP-Okta": 0.12, "HR-Workday": 0.04, "ITSM-ServiceNow": 0.02},
    "current_version": {"K8s-Cluster-Alpha": 0.10, "GitHub-CI": 0.04, "Metrics-TSDB": 0.03},
    "deployed_version": {"GitHub-CI": 0.08, "K8s-Cluster-Alpha": 0.06},
    "runtime_state": {"K8s-Cluster-Alpha": 0.12, "Metrics-TSDB": 0.08},
    "deploy_status": {"GitHub-CI": 0.08, "K8s-Cluster-Alpha": 0.06},
    # Lab / IVD — LIS / analyzer preferred over spreadsheet drop when both exist
    "result": {"Lab-LIS": 0.12, "Lab-Analyzer": 0.10, "Spreadsheet": 0.04},
    "result_status": {"Lab-LIS": 0.10, "Lab-Analyzer": 0.08, "Spreadsheet": 0.03},
    # HIS patient registration — HIS is system of record over front-desk re-entry
    "insurance_provider": {"HIS-Patients": 0.12, "FrontDesk-Intake": 0.02},
    "contact_number": {"HIS-Patients": 0.12, "FrontDesk-Intake": 0.02},
}

# Extractor storage types stay stable for ER; L1 is annotation + ranking context
_STORAGE_ALIASES: dict[str, str] = {
    "service": "Service",
    "Service": "Service",
    "customer": "Customer",
    "Customer": "Customer",
    "org": "Customer",
    "Org": "Customer",
    "person": "Person",
    "Person": "Person",
    "user": "Person",
    "InfraService": "Service",
    "BillingAccount": "Customer",
    "IdentityPrincipal": "Person",
    "LabResult": "LabResult",
    "labresult": "LabResult",
    "lab_test": "LabResult",
    "LabTest": "LabResult",
    "Patient": "Patient",
    "patient": "Patient",
    "Doctor": "Doctor",
    "doctor": "Doctor",
    "Appointment": "Appointment",
    "appointment": "Appointment",
    "Treatment": "Treatment",
    "treatment": "Treatment",
    "Billing": "Billing",
    "billing": "Billing",
    "AccountHolder": "AccountHolder",
    "accountholder": "AccountHolder",
    "Account": "Account",
    "account": "Account",
    "Transaction": "Transaction",
    "transaction": "Transaction",
}


@dataclass
class OntologyRegistry:
    """Governed type catalog; L2 extensions can be registered soft."""

    types: dict[str, OntologyType] = field(default_factory=dict)
    soft_extensions: dict[str, OntologyType] = field(default_factory=dict)
    source_boosts: dict[str, dict[str, float]] = field(
        default_factory=lambda: {k: dict(v) for k, v in PREDICATE_SOURCE_BOOST.items()}
    )

    @classmethod
    def default(cls) -> "OntologyRegistry":
        reg = cls()
        for t in _L0 + _L1:
            reg.types[t.name] = t
        return reg

    def get(self, name: str) -> Optional[OntologyType]:
        return self.types.get(name) or self.soft_extensions.get(name)

    def register_l2(
        self,
        name: str,
        *,
        parent: str,
        domain: str,
        predicates: list[str] | None = None,
        description: str = "",
    ) -> OntologyType:
        t = OntologyType(
            name=name,
            layer="L2",
            domain=domain,
            parent=parent,
            predicates=tuple(predicates or ()),
            description=description or f"Soft team extension under {parent}",
        )
        self.soft_extensions[name] = t
        return t

    def promote(self, name: str) -> bool:
        """Promote L2 soft type into governed registry."""
        t = self.soft_extensions.pop(name, None)
        if not t:
            return False
        self.types[name] = OntologyType(
            name=t.name,
            layer="L1",
            domain=t.domain,
            parent=t.parent,
            predicates=t.predicates,
            description=t.description + " (promoted)",
        )
        return True

    def map_entity_type(self, entity_type: str) -> OntologyType:
        """Map extractor entity_type strings to ontology types (L0 default)."""
        key = (entity_type or "").strip()
        aliases = {
            "service": "Service",
            "Service": "Service",
            "customer": "Org",
            "Customer": "Org",
            "org": "Org",
            "person": "Person",
            "Person": "Person",
            "user": "Person",
            "InfraService": "InfraService",
            "BillingAccount": "BillingAccount",
            "IdentityPrincipal": "IdentityPrincipal",
        }
        name = aliases.get(key, key if key in self.types or key in self.soft_extensions else "Asset")
        return self.get(name) or OntologyType(name or "Unknown", "L2", description="unmapped")

    def govern_extract(
        self,
        entity_type: str,
        *,
        domain: Optional[str] = None,
    ) -> GovernedType:
        """
        Load-bearing extract step: choose storage ER type + L0/L1 ontology tag.

        Storage type stays Service/Customer/Person for stable ER blocking.
        Ontology type upgrades to L1 pack when domain matches.
        """
        storage = _STORAGE_ALIASES.get((entity_type or "").strip(), entity_type or "Asset")
        # Prefer L1 pack by domain
        domain = (domain or "").strip() or None
        # Direct L1 types from extractor
        if storage == "LabResult" or (entity_type or "").strip() in {
            "LabResult",
            "LabTest",
            "lab_test",
        }:
            ot = self.get("LabResult")
            if ot:
                return GovernedType(
                    storage_type="LabResult",
                    ontology_type=ot.name,
                    ontology_layer=ot.layer,
                    domain=ot.domain or domain or "clinical_lab",
                )
        if storage == "Patient" or (entity_type or "").strip() in {"Patient", "patient"}:
            ot = self.get("Patient")
            if ot:
                return GovernedType(
                    storage_type="Patient",
                    ontology_type=ot.name,
                    ontology_layer=ot.layer,
                    domain=ot.domain or domain or "hospital_ops",
                )
        if storage == "Doctor" or (entity_type or "").strip() in {"Doctor", "doctor"}:
            ot = self.get("Doctor")
            if ot:
                return GovernedType(
                    storage_type="Doctor",
                    ontology_type=ot.name,
                    ontology_layer=ot.layer,
                    domain=ot.domain or domain or "hospital_ops",
                )
        if storage == "Appointment" or (entity_type or "").strip() in {
            "Appointment",
            "appointment",
        }:
            ot = self.get("Appointment")
            if ot:
                return GovernedType(
                    storage_type="Appointment",
                    ontology_type=ot.name,
                    ontology_layer=ot.layer,
                    domain=ot.domain or domain or "hospital_ops",
                )
        if storage == "Treatment" or (entity_type or "").strip() in {
            "Treatment",
            "treatment",
        }:
            ot = self.get("Treatment")
            if ot:
                return GovernedType(
                    storage_type="Treatment",
                    ontology_type=ot.name,
                    ontology_layer=ot.layer,
                    domain=ot.domain or domain or "hospital_ops",
                )
        if storage == "Billing" or (entity_type or "").strip() in {"Billing", "billing"}:
            ot = self.get("Billing")
            if ot:
                return GovernedType(
                    storage_type="Billing",
                    ontology_type=ot.name,
                    ontology_layer=ot.layer,
                    domain=ot.domain or domain or "hospital_ops",
                )
        if storage == "AccountHolder" or (entity_type or "").strip() in {
            "AccountHolder",
            "accountholder",
        }:
            ot = self.get("AccountHolder")
            if ot:
                return GovernedType(
                    storage_type="AccountHolder",
                    ontology_type=ot.name,
                    ontology_layer=ot.layer,
                    domain=ot.domain or domain or "banking",
                )
        if storage == "Account" or (entity_type or "").strip() in {"Account", "account"}:
            ot = self.get("Account")
            if ot:
                return GovernedType(
                    storage_type="Account",
                    ontology_type=ot.name,
                    ontology_layer=ot.layer,
                    domain=ot.domain or domain or "banking",
                )
        if storage == "Transaction" or (entity_type or "").strip() in {
            "Transaction",
            "transaction",
        }:
            ot = self.get("Transaction")
            if ot:
                return GovernedType(
                    storage_type="Transaction",
                    ontology_type=ot.name,
                    ontology_layer=ot.layer,
                    domain=ot.domain or domain or "banking",
                )

        l1_by_domain = {
            "infra_ops": ("Service", "InfraService"),
            "revenue": ("Customer", "BillingAccount"),
            "identity": ("Person", "IdentityPrincipal"),
            "support": ("Event", "SupportTicket"),
            "clinical_lab": ("LabResult", "LabResult"),
            "lab": ("LabResult", "LabResult"),
            # hospital_ops has 5 L1 types (Patient/Doctor/Appointment/
            # Treatment/Billing), each caught by its own early-return above —
            # no single (storage, l1_name) pair is meaningful here.
        }
        if domain in l1_by_domain:
            want_storage, l1_name = l1_by_domain[domain]
            # Only upgrade when extractor type is in the same family
            family = {
                "Service": {"Service"},
                "Customer": {"Customer", "Org"},
                "Person": {"Person"},
                "Event": {"Event"},
                "LabResult": {"LabResult", "LabTest", "Event"},
                "Patient": {"Patient"},
            }
            if storage in family.get(want_storage, {want_storage}) or storage == want_storage:
                ot = self.get(l1_name)
                if ot:
                    stor = (
                        storage
                        if want_storage == "Event" and storage != "Event"
                        else want_storage
                    )
                    if want_storage == "LabResult":
                        stor = "LabResult"
                    return GovernedType(
                        storage_type=stor,
                        ontology_type=ot.name,
                        ontology_layer=ot.layer,
                        domain=ot.domain,
                    )
                if want_storage not in ("Event",):
                    storage = want_storage

        # L0 map for storage types
        l0_name = {
            "Service": "Service",
            "Customer": "Org",
            "Person": "Person",
            "Event": "Event",
            "LabResult": "LabResult",
        }.get(storage, storage)
        ot = self.map_entity_type(l0_name)
        return GovernedType(
            storage_type=storage,
            ontology_type=ot.name,
            ontology_layer=ot.layer,
            domain=ot.domain or domain,
        )

    def compatible_types(self, entity_type: str) -> set[str]:
        """ER type family: Service ↔ InfraService, Customer ↔ Org ↔ BillingAccount, etc."""
        key = (entity_type or "").strip()
        families = [
            {"Service", "InfraService", "Asset"},
            {"Customer", "Org", "BillingAccount"},
            {"Person", "IdentityPrincipal", "user", "User"},
            {"Event", "SupportTicket"},
            {"LabResult", "LabTest", "lab_test"},
            {"Patient", "patient"},
            {"Doctor", "doctor"},
            {"Appointment", "appointment"},
            {"Treatment", "treatment"},
            {"Billing", "billing"},
            {"AccountHolder", "accountholder"},
            {"Account", "account"},
            {"Transaction", "transaction"},
        ]
        for fam in families:
            if key in fam:
                return set(fam)
        return {key} if key else set()

    def types_match(self, a: str, b: str) -> bool:
        if a == b:
            return True
        return b in self.compatible_types(a) or a in self.compatible_types(b)

    def is_predicate_in_scope(
        self,
        ontology_type_name: Optional[str],
        predicate: str,
    ) -> bool:
        if not ontology_type_name or not predicate:
            return True
        ot = self.get(ontology_type_name) or self.map_entity_type(ontology_type_name)
        if not ot.predicates:
            return True
        if predicate in ot.predicates:
            return True
        # Parent predicates also in scope
        if ot.parent:
            parent = self.get(ot.parent)
            if parent and predicate in parent.predicates:
                return True
        return False

    def predicate_source_boost(self, predicate: str, source_system: str) -> float:
        """Additive boost for domain-overlap SoR preference (H8)."""
        return float(self.source_boosts.get(predicate, {}).get(source_system, 0.0))

    def predicates_for_domain(self, domain: str) -> list[str]:
        out: list[str] = []
        for t in self.types.values():
            if t.domain == domain or t.layer == "L0":
                out.extend(t.predicates)
        seen: set[str] = set()
        uniq: list[str] = []
        for p in out:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        return uniq

    def describe(self) -> dict[str, Any]:
        by_layer: dict[str, list[dict[str, Any]]] = {"L0": [], "L1": [], "L2": []}
        for t in self.types.values():
            by_layer.setdefault(t.layer, []).append(t.to_dict())
        for t in self.soft_extensions.values():
            by_layer.setdefault("L2", []).append(t.to_dict())
        return {
            "layers": by_layer,
            "governed_count": len(self.types),
            "soft_count": len(self.soft_extensions),
            "load_bearing": True,
            "predicate_source_boosts": {
                k: dict(v) for k, v in self.source_boosts.items()
            },
        }
